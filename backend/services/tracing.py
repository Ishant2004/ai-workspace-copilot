"""Observability: per-turn tracing (Phase 20).

When a chat turn feels slow or wrong, "it was slow" isn't actionable — *which
part* was slow is. A trace answers that: it records a list of **spans** (named,
timed sub-steps like retrieval, each tool call, and generation) plus a token
estimate, so every turn becomes a little timeline you can inspect.

Design notes:
  - A `Trace` is a plain in-memory collector built at the start of a turn. The
    endpoint records spans as work happens, then persists the trace and emits it
    to the UI as a `trace` SSE event.
  - Token counts are *estimated* locally (~4 chars/token) rather than via an API
    call, so tracing never adds latency or burns the free-tier quota. The Phase 1
    tokenizer exists for exact counts when a user asks; per-turn we stay cheap.
"""

import time
from contextlib import contextmanager

from psycopg.types.json import Jsonb

from services.db import get_conn


def estimate_tokens(text: str) -> int:
    """Cheap local token estimate (~4 chars/token). Good enough for a per-turn
    cost signal without an extra API round-trip."""
    return max(0, round(len(text or "") / 4))


class Trace:
    """Collects the timed spans of one chat turn."""

    def __init__(self, user_id: int, thread_id: int, mode: str):
        self.user_id = user_id
        self.thread_id = thread_id
        self.mode = mode
        self.spans: list[dict] = []
        self.tokens: dict = {}
        self._start = time.perf_counter()

    def add(self, name: str, duration_ms: int, **meta) -> None:
        """Record a finished span by name + duration, with optional metadata."""
        self.spans.append(
            {"name": name, "duration_ms": duration_ms, "meta": meta}
        )

    @contextmanager
    def span(self, name: str, **meta):
        """Time a block of work as a span: `with trace.span("retrieval"): ...`."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, round((time.perf_counter() - start) * 1000), **meta)

    def set_tokens(self, prompt: int, response: int) -> None:
        self.tokens = {
            "prompt_est": prompt,
            "response_est": response,
            "total_est": prompt + response,
        }

    def total_ms(self) -> int:
        return round((time.perf_counter() - self._start) * 1000)

    def summary(self) -> dict:
        """The shape sent to the UI and stored (minus db ids)."""
        return {
            "mode": self.mode,
            "total_ms": self.total_ms(),
            "tokens": self.tokens,
            "spans": self.spans,
        }


def init_traces() -> None:
    """Create the traces table if it doesn't exist."""
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traces (
                id         BIGSERIAL PRIMARY KEY,
                user_id    BIGINT,
                thread_id  BIGINT,
                mode       TEXT,
                total_ms   INTEGER,
                spans      JSONB NOT NULL DEFAULT '[]'::jsonb,
                tokens     JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS traces_thread_idx "
            "ON traces (thread_id, id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS traces_user_idx ON traces (user_id);"
        )


def save_trace(trace: Trace) -> int:
    """Persist a finished trace; returns its id."""
    with get_conn(register=False) as conn:
        row = conn.execute(
            "INSERT INTO traces (user_id, thread_id, mode, total_ms, spans, tokens) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;",
            (
                trace.user_id,
                trace.thread_id,
                trace.mode,
                trace.total_ms(),
                Jsonb(trace.spans),
                Jsonb(trace.tokens),
            ),
        ).fetchone()
        return row[0]


def list_thread_traces(
    thread_id: int, user_id: int, limit: int = 20
) -> list[dict]:
    """Recent traces for one thread, owned by user_id, newest first."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT id, mode, total_ms, spans, tokens, created_at FROM traces "
            "WHERE thread_id = %s AND user_id = %s ORDER BY id DESC LIMIT %s;",
            (thread_id, user_id, limit),
        ).fetchall()
    return [
        {
            "id": r[0],
            "mode": r[1],
            "total_ms": r[2],
            "spans": r[3],
            "tokens": r[4],
            "created_at": r[5].isoformat(),
        }
        for r in rows
    ]
