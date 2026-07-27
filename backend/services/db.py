"""Vector database access (Phase 3).

This is our own tiny vector database built on Postgres + the `pgvector`
extension. The idea:

  - Every document is stored alongside its embedding (a vector(768) column).
  - To "search", we embed the query and ask Postgres for the rows whose vectors
    are closest to it, using the cosine-distance operator `<=>`.

Because our embeddings are unit-normalized (see services/gemini.py), cosine
similarity is simply `1 - cosine_distance`. A similarity of 1.0 means identical
direction (very related); 0.0 means unrelated.

We open a fresh connection per request for simplicity. That is slightly slower
than pooling but keeps the code obvious, which matters more while learning.
"""

from contextlib import contextmanager
from collections.abc import Iterator

import psycopg
from pgvector.psycopg import register_vector

from config import settings


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
    """Create the vector extension and the documents table if missing.

    The embedding column size is fixed to the configured embedding dimension.
    Every document must be embedded with the same model/dimension or the
    distances are meaningless.
    """
    dim = settings.gemini_embed_dim
    # register=False: on a brand-new database the `vector` type doesn't exist
    # yet, so we must create the extension before the adapter can be registered.
    with get_conn(register=False) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
                id        BIGSERIAL PRIMARY KEY,
                title     TEXT,
                text      TEXT NOT NULL,
                embedding vector({dim}) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


def insert_document(title: str, text: str, embedding: list[float]) -> int:
    """Store one document + its embedding. Returns the new row id."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO documents (title, text, embedding) "
            "VALUES (%s, %s, %s) RETURNING id;",
            (title, text, embedding),
        ).fetchone()
        return row[0]


def search(query_embedding: list[float], k: int) -> list[dict]:
    """Return the k documents most similar to the query embedding.

    `<=>` is pgvector's cosine-distance operator. We order by it ascending
    (smaller distance = more similar) and convert to a 0..1 similarity score.
    """
    with get_conn() as conn:
        # Cast the parameter to `vector`: a plain Python list arrives as a
        # Postgres float8[] otherwise, and `<=>` is only defined on vectors.
        rows = conn.execute(
            """
            SELECT id, title, text,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (query_embedding, query_embedding, k),
        ).fetchall()

    return [
        {"id": r[0], "title": r[1], "text": r[2], "similarity": float(r[3])}
        for r in rows
    ]


def list_documents() -> list[dict]:
    """Return every stored document (newest first), without the embedding.

    We omit the 768-number embedding here — it's large and the UI never needs
    the raw vector just to list or manage records.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, text FROM documents ORDER BY id DESC;"
        ).fetchall()
    return [{"id": r[0], "title": r[1], "text": r[2]} for r in rows]


def update_document(
    doc_id: int, title: str, text: str, embedding: list[float]
) -> bool:
    """Replace a document's title/text/embedding. Returns False if id missing.

    The caller re-embeds the new text before calling this, so the stored vector
    always matches the stored text.
    """
    with get_conn() as conn:
        result = conn.execute(
            "UPDATE documents SET title = %s, text = %s, embedding = %s "
            "WHERE id = %s;",
            (title, text, embedding, doc_id),
        )
        return result.rowcount > 0


def delete_document(doc_id: int) -> bool:
    """Delete one document. Returns False if the id did not exist."""
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM documents WHERE id = %s;", (doc_id,)
        )
        return result.rowcount > 0


def count_documents() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT count(*) FROM documents;").fetchone()[0]
