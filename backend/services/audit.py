"""Audit log (Phase 29).

A durable record of security-relevant events — sign-ups, logins, document
uploads/deletes, and flagged prompt-injection attempts — so there's an
after-the-fact trail of who did what. Best-effort: logging must never break the
action it describes, so failures are swallowed.
"""

import logging

from psycopg.types.json import Jsonb

from services.db import get_conn

logger = logging.getLogger("uvicorn.error")


def init_audit() -> None:
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id         BIGSERIAL PRIMARY KEY,
                user_id    BIGINT,
                event      TEXT NOT NULL,
                detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
                ip         TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS audit_user_idx ON audit_log (user_id, id);"
        )


def log(
    event: str,
    user_id: int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """Record one event. Never raises into the caller."""
    try:
        with get_conn(register=False) as conn:
            conn.execute(
                "INSERT INTO audit_log (user_id, event, detail, ip) "
                "VALUES (%s, %s, %s, %s);",
                (user_id, event, Jsonb(detail or {}), ip),
            )
    except Exception as exc:  # noqa: BLE001 - auditing must not break actions
        logger.warning("Audit log failed for %s: %s", event, exc)


def list_recent(user_id: int, limit: int = 100) -> list[dict]:
    """This user's recent audit events, newest first."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT event, detail, ip, created_at FROM audit_log "
            "WHERE user_id = %s ORDER BY id DESC LIMIT %s;",
            (user_id, limit),
        ).fetchall()
    return [
        {
            "event": r[0],
            "detail": r[1],
            "ip": r[2],
            "created_at": r[3].isoformat(),
        }
        for r in rows
    ]
