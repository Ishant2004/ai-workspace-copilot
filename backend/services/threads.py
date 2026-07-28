"""Conversation persistence (Phase 9).

The LLM itself is stateless — it only knows what we put in the prompt. "Memory"
is therefore something *we* store and replay. Here we persist conversations in
Postgres as two tables:

    threads  — one row per conversation (id, title, created_at)
    messages — one row per turn (thread_id, role, content, created_at)

On each turn we save the user's message, replay the recent history to the model
(a sliding window — see get_recent_messages), then save the assistant's reply.
Reloading a thread later reconstructs the whole conversation.

We reuse the DB connection helper from services/db.py; no vectors are involved,
so we open connections with the pgvector adapter turned off.
"""

from services.db import get_conn


def init_threads() -> None:
    """Create the threads/messages tables if they don't exist."""
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id         BIGSERIAL PRIMARY KEY,
                title      TEXT NOT NULL DEFAULT 'New chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id         BIGSERIAL PRIMARY KEY,
                thread_id  BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS messages_thread_idx "
            "ON messages (thread_id, id);"
        )


def create_thread(title: str = "New chat") -> dict:
    with get_conn(register=False) as conn:
        row = conn.execute(
            "INSERT INTO threads (title) VALUES (%s) RETURNING id, title;",
            (title or "New chat",),
        ).fetchone()
    return {"id": row[0], "title": row[1]}


def list_threads() -> list[dict]:
    """All threads, most recently active first, with a message count."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.title, count(m.id) AS message_count,
                   coalesce(max(m.created_at), t.created_at) AS last_at
            FROM threads t
            LEFT JOIN messages m ON m.thread_id = t.id
            GROUP BY t.id
            ORDER BY last_at DESC;
            """
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "message_count": r[2]} for r in rows
    ]


def thread_exists(thread_id: int) -> bool:
    with get_conn(register=False) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM threads WHERE id = %s;", (thread_id,)
            ).fetchone()
            is not None
        )


def add_message(thread_id: int, role: str, content: str) -> None:
    with get_conn(register=False) as conn:
        conn.execute(
            "INSERT INTO messages (thread_id, role, content) "
            "VALUES (%s, %s, %s);",
            (thread_id, role, content),
        )


def get_messages(thread_id: int) -> list[dict]:
    """Full conversation, oldest first (for reloading a thread in the UI)."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE thread_id = %s ORDER BY id;",
            (thread_id,),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


def get_recent_messages(thread_id: int, limit: int) -> list[dict]:
    """The last `limit` messages, oldest first — the sliding window we replay
    to the model so the prompt (and cost) stays bounded on long conversations."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT role, content FROM ("
            "  SELECT id, role, content FROM messages "
            "  WHERE thread_id = %s ORDER BY id DESC LIMIT %s"
            ") sub ORDER BY id;",
            (thread_id, limit),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


def update_title(thread_id: int, title: str) -> None:
    with get_conn(register=False) as conn:
        conn.execute(
            "UPDATE threads SET title = %s WHERE id = %s;", (title, thread_id)
        )


def delete_thread(thread_id: int) -> bool:
    with get_conn(register=False) as conn:
        result = conn.execute(
            "DELETE FROM threads WHERE id = %s;", (thread_id,)
        )
        return result.rowcount > 0
