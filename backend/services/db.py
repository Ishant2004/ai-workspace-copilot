"""Vector database access (Phase 3; user-scoped for multi-tenancy).

This is our own tiny vector database built on Postgres + the `pgvector`
extension. Every document is stored with its embedding (a vector column) and,
now, an owning `user_id` — every read/write is filtered by it so users only ever
see their own documents.

Because our embeddings are unit-normalized (see services/gemini.py), cosine
similarity is simply `1 - cosine_distance`.

We open a fresh connection per request for simplicity.
"""

from contextlib import contextmanager
from collections.abc import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from config import settings
from services import cache


@contextmanager
def get_conn(register: bool = True) -> Iterator[psycopg.Connection]:
    """Open a connection, teach it about vectors, and clean up afterwards.

    `register` adapts Python lists <-> the pgvector `vector` type. It requires
    the extension to already exist, so `init_db` opens its first connection with
    register=False (before the extension is created).
    """
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        if register:
            register_vector(conn)
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create the vector extension and the documents table if missing."""
    dim = settings.gemini_embed_dim
    with get_conn(register=False) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
                id        BIGSERIAL PRIMARY KEY,
                user_id   BIGINT,
                title     TEXT,
                text      TEXT NOT NULL,
                embedding vector({dim}) NOT NULL,
                metadata  JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        # Phase 6: metadata column for older tables.
        conn.execute(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL "
            "DEFAULT '{}'::jsonb;"
        )
        # Multi-tenancy: owner column, indexed for fast per-user filtering.
        conn.execute(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id BIGINT;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS documents_user_idx "
            "ON documents (user_id);"
        )
        # Phase 30: chat-scoped attachments. NULL = global knowledge base (visible
        # everywhere); a thread id = a file attached to that one conversation.
        conn.execute(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS thread_id BIGINT;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS documents_user_thread_idx "
            "ON documents (user_id, thread_id);"
        )
        # Phase 7: generated tsvector column + GIN index for keyword search.
        conn.execute(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS text_search tsvector "
            "GENERATED ALWAYS AS ("
            "  to_tsvector('english', coalesce(title, '') || ' ' || coalesce(text, ''))"
            ") STORED;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS documents_text_search_idx "
            "ON documents USING GIN (text_search);"
        )


def _scope(user_id: int, thread_id: int | None) -> tuple[str, list]:
    """Build the ownership/visibility WHERE fragment + params (Phase 30).

    Global retrieval (thread_id None) sees only the global KB (thread_id NULL); a
    thread sees the global KB PLUS its own attachments — never another thread's.
    """
    if thread_id is None:
        return "user_id = %s AND thread_id IS NULL", [user_id]
    return "user_id = %s AND (thread_id IS NULL OR thread_id = %s)", [
        user_id,
        thread_id,
    ]


def insert_document(
    user_id: int,
    title: str,
    text: str,
    embedding: list[float],
    metadata: dict | None = None,
    thread_id: int | None = None,
) -> int:
    """Store one document owned by `user_id`. Returns the new id.

    `thread_id` scopes the row to one conversation (an attachment); NULL means the
    global knowledge base.
    """
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO documents "
            "(user_id, thread_id, title, text, embedding, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;",
            (user_id, thread_id, title, text, embedding, Jsonb(metadata or {})),
        ).fetchone()
    cache.bump_user_version(user_id)  # invalidate cached retrievals for this user
    return row[0]


def insert_documents(
    user_id: int,
    rows: list[tuple[str, str, list[float], dict]],
    thread_id: int | None = None,
) -> int:
    """Insert many (title, text, embedding, metadata) rows for `user_id`.

    All rows share `thread_id` (NULL = global KB, an id = attachments of one chat).
    """
    if not rows:
        return 0
    params = [(user_id, thread_id, t, x, e, Jsonb(m or {})) for (t, x, e, m) in rows]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents "
                "(user_id, thread_id, title, text, embedding, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                params,
            )
    cache.bump_user_version(user_id)  # invalidate cached retrievals for this user
    return len(rows)


def search(
    user_id: int,
    query_embedding: list[float],
    k: int,
    thread_id: int | None = None,
) -> list[dict]:
    """Return the user's k documents most similar to the query embedding.

    Scoped by `thread_id` (Phase 30): global KB by default, or global + a chat's
    attachments when a thread id is given.
    """
    scope_sql, scope_params = _scope(user_id, thread_id)
    with get_conn() as conn:
        # Cast the parameter to `vector`: a plain Python list arrives as a
        # Postgres float8[] otherwise, and `<=>` is only defined on vectors.
        rows = conn.execute(
            f"""
            SELECT id, title, text, metadata,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            WHERE {scope_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (query_embedding, *scope_params, query_embedding, k),
        ).fetchall()

    return [
        {
            "id": r[0],
            "title": r[1],
            "text": r[2],
            "metadata": r[3] or {},
            "similarity": float(r[4]),
        }
        for r in rows
    ]


def keyword_search(
    user_id: int, query: str, k: int, thread_id: int | None = None
) -> list[dict]:
    """Full-text keyword search over the user's documents (Phase 7), scoped by
    thread (Phase 30)."""
    scope_sql, scope_params = _scope(user_id, thread_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, text, metadata,
                   ts_rank(text_search, q) AS rank
            FROM documents, websearch_to_tsquery('english', %s) AS q
            WHERE {scope_sql} AND text_search @@ q
            ORDER BY rank DESC
            LIMIT %s;
            """,
            (query, *scope_params, k),
        ).fetchall()
    return [
        {
            "id": r[0],
            "title": r[1],
            "text": r[2],
            "metadata": r[3] or {},
            "rank": float(r[4]),
        }
        for r in rows
    ]


def list_documents(user_id: int) -> list[dict]:
    """Return the user's global-KB documents (newest first), without embeddings.

    Chat attachments (thread_id set) are excluded so the knowledge-base view isn't
    polluted by per-chat files — those are listed via `list_attachments`.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, text, metadata FROM documents "
            "WHERE user_id = %s AND thread_id IS NULL ORDER BY id DESC;",
            (user_id,),
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "text": r[2], "metadata": r[3] or {}}
        for r in rows
    ]


def list_attachments(user_id: int, thread_id: int) -> list[dict]:
    """Distinct files attached to one chat (grouped from their chunk rows)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT metadata->>'filename' AS filename, count(*) AS chunks, "
            "min(id) AS first_id "
            "FROM documents WHERE user_id = %s AND thread_id = %s "
            "GROUP BY metadata->>'filename' ORDER BY first_id;",
            (user_id, thread_id),
        ).fetchall()
    return [
        {"filename": r[0] or "attachment", "chunks": r[1], "id": r[2]}
        for r in rows
    ]


def delete_attachment(user_id: int, thread_id: int, filename: str) -> int:
    """Delete all chunk rows for one attached file in a chat. Returns count."""
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM documents WHERE user_id = %s AND thread_id = %s "
            "AND metadata->>'filename' = %s;",
            (user_id, thread_id, filename),
        )
    if result.rowcount:
        cache.bump_user_version(user_id)
    return result.rowcount


def delete_thread_documents(user_id: int, thread_id: int) -> int:
    """Delete all attachments of a thread (called when the thread is deleted)."""
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM documents WHERE user_id = %s AND thread_id = %s;",
            (user_id, thread_id),
        )
    if result.rowcount:
        cache.bump_user_version(user_id)
    return result.rowcount


def update_document(
    user_id: int, doc_id: int, title: str, text: str, embedding: list[float]
) -> bool:
    """Replace one of the user's documents. False if id missing or not theirs."""
    with get_conn() as conn:
        result = conn.execute(
            "UPDATE documents SET title = %s, text = %s, embedding = %s "
            "WHERE id = %s AND user_id = %s;",
            (title, text, embedding, doc_id, user_id),
        )
        changed = result.rowcount > 0
    if changed:
        cache.bump_user_version(user_id)
    return changed


def delete_document(user_id: int, doc_id: int) -> bool:
    """Delete one of the user's documents. False if missing or not theirs."""
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM documents WHERE id = %s AND user_id = %s;",
            (doc_id, user_id),
        )
        changed = result.rowcount > 0
    if changed:
        cache.bump_user_version(user_id)
    return changed


def count_documents(user_id: int) -> int:
    """Count the user's global-KB documents (excludes chat attachments)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT count(*) FROM documents "
            "WHERE user_id = %s AND thread_id IS NULL;",
            (user_id,),
        ).fetchone()[0]
