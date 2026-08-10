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


def insert_document(
    user_id: int,
    title: str,
    text: str,
    embedding: list[float],
    metadata: dict | None = None,
) -> int:
    """Store one document owned by `user_id`. Returns the new id."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO documents (user_id, title, text, embedding, metadata) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id;",
            (user_id, title, text, embedding, Jsonb(metadata or {})),
        ).fetchone()
    cache.bump_user_version(user_id)  # invalidate cached retrievals for this user
    return row[0]


def insert_documents(
    user_id: int, rows: list[tuple[str, str, list[float], dict]]
) -> int:
    """Insert many (title, text, embedding, metadata) rows for `user_id`."""
    if not rows:
        return 0
    params = [(user_id, t, x, e, Jsonb(m or {})) for (t, x, e, m) in rows]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents "
                "(user_id, title, text, embedding, metadata) "
                "VALUES (%s, %s, %s, %s, %s);",
                params,
            )
    cache.bump_user_version(user_id)  # invalidate cached retrievals for this user
    return len(rows)


def search(user_id: int, query_embedding: list[float], k: int) -> list[dict]:
    """Return the user's k documents most similar to the query embedding."""
    with get_conn() as conn:
        # Cast the parameter to `vector`: a plain Python list arrives as a
        # Postgres float8[] otherwise, and `<=>` is only defined on vectors.
        rows = conn.execute(
            """
            SELECT id, title, text, metadata,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            WHERE user_id = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (query_embedding, user_id, query_embedding, k),
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


def keyword_search(user_id: int, query: str, k: int) -> list[dict]:
    """Full-text keyword search over the user's documents (Phase 7)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, text, metadata,
                   ts_rank(text_search, q) AS rank
            FROM documents, websearch_to_tsquery('english', %s) AS q
            WHERE user_id = %s AND text_search @@ q
            ORDER BY rank DESC
            LIMIT %s;
            """,
            (query, user_id, k),
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
    """Return the user's stored documents (newest first), without embeddings."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, text, metadata FROM documents "
            "WHERE user_id = %s ORDER BY id DESC;",
            (user_id,),
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "text": r[2], "metadata": r[3] or {}}
        for r in rows
    ]


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
    with get_conn() as conn:
        return conn.execute(
            "SELECT count(*) FROM documents WHERE user_id = %s;", (user_id,)
        ).fetchone()[0]
