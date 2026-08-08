"""User feedback loop (Phase 23).

Evals (Phases 18-22) measure quality on a *fixed* golden set. Real users hit
cases we never thought to write down — so we let them rate each answer 👍/👎 with
an optional note, and store it. Two payoffs:

  - a live **satisfaction rate** (a health signal beyond offline evals);
  - a **data flywheel**: thumbs-down cases are exactly the questions the system
    got wrong, which become candidates for the golden set (see
    eval/export_feedback.py) — so production failures feed back into evaluation.

Feedback is stored with the question + answer text (not just a message id) so an
export is self-contained and the row survives even if the thread is deleted.
"""

from services.db import get_conn


def init_feedback() -> None:
    """Create the feedback table if it doesn't exist."""
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id         BIGSERIAL PRIMARY KEY,
                user_id    BIGINT,
                thread_id  BIGINT,
                question   TEXT NOT NULL,
                answer     TEXT NOT NULL,
                rating     TEXT NOT NULL,
                note       TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS feedback_user_idx ON feedback (user_id);"
        )


def add_feedback(
    user_id: int,
    thread_id: int | None,
    question: str,
    answer: str,
    rating: str,
    note: str = "",
) -> None:
    """Record (or replace) a rating for one answer.

    We upsert by (user_id, thread_id, answer): re-clicking a thumb or adding a
    note updates the existing row instead of double-counting the stats.
    """
    with get_conn(register=False) as conn:
        conn.execute(
            "DELETE FROM feedback WHERE user_id = %s AND thread_id = %s "
            "AND answer = %s;",
            (user_id, thread_id, answer),
        )
        conn.execute(
            "INSERT INTO feedback (user_id, thread_id, question, answer, rating, note) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (user_id, thread_id, question, answer, rating, note or ""),
        )


def stats(user_id: int) -> dict:
    """Up/down counts and satisfaction rate for one user."""
    with get_conn(register=False) as conn:
        row = conn.execute(
            "SELECT "
            "  COUNT(*) FILTER (WHERE rating = 'up'), "
            "  COUNT(*) FILTER (WHERE rating = 'down'), "
            "  COUNT(*) "
            "FROM feedback WHERE user_id = %s;",
            (user_id,),
        ).fetchone()
    up, down, total = row[0], row[1], row[2]
    rated = up + down
    return {
        "up": up,
        "down": down,
        "total": total,
        "satisfaction_rate": round(up / rated, 3) if rated else None,
    }


def list_negative(user_id: int, limit: int = 100) -> list[dict]:
    """Thumbs-down cases — the raw material for new golden-set questions."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT question, answer, note, created_at FROM feedback "
            "WHERE user_id = %s AND rating = 'down' ORDER BY id DESC LIMIT %s;",
            (user_id, limit),
        ).fetchall()
    return [
        {
            "question": r[0],
            "answer": r[1],
            "note": r[2],
            "created_at": r[3].isoformat(),
        }
        for r in rows
    ]
