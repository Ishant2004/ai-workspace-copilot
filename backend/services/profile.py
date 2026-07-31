"""Long-term user profile memory (Phase 13).

Phase 9's memory is *per conversation* (a thread's messages). This is memory
*across* conversations: durable facts about the user — their name, role,
preferences — that should persist no matter which thread they're in.

How it works:
  - After each user turn, a background task asks the LLM to extract any durable
    facts worth remembering (ignoring one-off questions) and stores the new ones
    in a `user_facts` table.
  - Every new turn injects those facts into the system prompt (`preamble`), so
    the assistant "remembers" the user everywhere.

This is a single-user app (no auth), so there's one implicit profile.
"""

import json
import logging
import threading

from google.genai import types

from services import gemini
from services.db import get_conn

logger = logging.getLogger("uvicorn.error")

# Extraction returns a JSON array of short fact strings.
_FACTS_SCHEMA = types.Schema(
    type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
)

_EXTRACT_PROMPT = (
    "From the user's message below, extract durable facts about the USER that "
    "are worth remembering long-term across conversations — e.g. their name, "
    "role, team, preferences, tools they use, ongoing projects. Ignore one-off "
    "questions, requests, and anything transient. Return a JSON array of short, "
    "self-contained fact strings (e.g. \"Prefers Python\", \"Works in "
    "marketing\"). Return an empty array if there's nothing worth saving.\n\n"
    "USER MESSAGE:\n"
)


def init_profile() -> None:
    """Create the user_facts table if it doesn't exist (facts are per-user)."""
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_facts (
                id         BIGSERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL,
                fact       TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        # Migrate tables created before multi-tenancy: add user_id, drop the old
        # global UNIQUE(fact), and enforce uniqueness per (user_id, fact).
        conn.execute(
            "ALTER TABLE user_facts ADD COLUMN IF NOT EXISTS user_id BIGINT;"
        )
        conn.execute(
            "ALTER TABLE user_facts DROP CONSTRAINT IF EXISTS user_facts_fact_key;"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS user_facts_user_fact_idx "
            "ON user_facts (user_id, fact);"
        )


def get_facts(user_id: int) -> list[str]:
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT fact FROM user_facts WHERE user_id = %s ORDER BY id;",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]


def add_facts(user_id: int, facts: list[str]) -> None:
    """Insert new facts for the user, ignoring duplicates ((user_id,fact) UNIQUE)."""
    clean = [f.strip() for f in facts if f and f.strip()]
    if not clean:
        return
    with get_conn(register=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO user_facts (user_id, fact) VALUES (%s, %s) "
                "ON CONFLICT (user_id, fact) DO NOTHING;",
                [(user_id, f) for f in clean],
            )


def clear_facts(user_id: int) -> None:
    with get_conn(register=False) as conn:
        conn.execute("DELETE FROM user_facts WHERE user_id = %s;", (user_id,))


def preamble(user_id: int) -> str:
    """A system-prompt block describing the user, or '' if we know nothing."""
    facts = get_facts(user_id)
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"What you know about the user:\n{lines}\n\n"


def _extract(user_id: int, user_message: str) -> None:
    """Extract durable facts from a message and store them (runs in a thread).

    Best-effort: retries a couple of times for transient model errors (the free
    tier occasionally returns 503/504), and never raises into the caller.
    """
    for attempt in range(3):
        try:
            response = gemini.generate(
                [
                    types.Content(
                        role="user",
                        parts=[types.Part(text=_EXTRACT_PROMPT + user_message)],
                    )
                ],
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_FACTS_SCHEMA,
                ),
            )
            facts = json.loads(response.text or "[]")
            if isinstance(facts, list):
                add_facts(user_id, [str(f) for f in facts])
            return
        except Exception as exc:  # never let memory extraction break the chat
            if attempt == 2:
                logger.warning("Profile extraction failed: %s", exc)


def extract_in_background(user_id: int, user_message: str) -> None:
    """Fire-and-forget fact extraction so it never delays the chat response."""
    threading.Thread(
        target=_extract, args=(user_id, user_message), daemon=True
    ).start()
