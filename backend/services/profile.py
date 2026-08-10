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

from config import settings
from services import gemini
from services.db import get_conn
from services.gemini import embed_text

logger = logging.getLogger("uvicorn.error")

# Phase 25: how many relevant facts to inject per turn when the profile is large.
_RELEVANT_K = 5

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
        # Phase 25: an embedding per fact, so we can inject only the facts
        # *relevant* to the current message instead of the whole profile.
        # Nullable — legacy rows are back-filled lazily on first relevant read.
        conn.execute(
            f"ALTER TABLE user_facts ADD COLUMN IF NOT EXISTS "
            f"embedding vector({settings.gemini_embed_dim});"
        )


def get_facts(user_id: int) -> list[str]:
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT fact FROM user_facts WHERE user_id = %s ORDER BY id;",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]


def get_facts_with_ids(user_id: int) -> list[dict]:
    """Facts with their ids, for the management UI (view/delete individually)."""
    with get_conn(register=False) as conn:
        rows = conn.execute(
            "SELECT id, fact FROM user_facts WHERE user_id = %s ORDER BY id;",
            (user_id,),
        ).fetchall()
    return [{"id": r[0], "fact": r[1]} for r in rows]


def add_facts(user_id: int, facts: list[str]) -> None:
    """Insert new facts for the user, ignoring duplicates ((user_id,fact) UNIQUE).

    Each fact is embedded (Phase 25) so it can later be retrieved by relevance.
    Embedding is cached (Phase 24), so re-seeing a fact is cheap.
    """
    clean = [f.strip() for f in facts if f and f.strip()]
    if not clean:
        return
    rows = [(user_id, f, embed_text(f)) for f in clean]
    with get_conn() as conn:  # register=True: adapt Python lists to pgvector
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO user_facts (user_id, fact, embedding) "
                "VALUES (%s, %s, %s) ON CONFLICT (user_id, fact) DO NOTHING;",
                rows,
            )


def delete_fact(user_id: int, fact_id: int) -> bool:
    """Delete one of the user's facts. False if missing or not theirs."""
    with get_conn(register=False) as conn:
        result = conn.execute(
            "DELETE FROM user_facts WHERE id = %s AND user_id = %s;",
            (fact_id, user_id),
        )
        return result.rowcount > 0


def clear_facts(user_id: int) -> None:
    with get_conn(register=False) as conn:
        conn.execute("DELETE FROM user_facts WHERE user_id = %s;", (user_id,))


def _format_preamble(facts: list[str]) -> str:
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"What you know about the user:\n{lines}\n\n"


def preamble(user_id: int) -> str:
    """A system-prompt block describing the user (ALL facts), or '' if none."""
    return _format_preamble(get_facts(user_id))


def _backfill_embeddings(user_id: int) -> None:
    """Embed any of the user's facts that predate Phase 25 (embedding IS NULL)."""
    with get_conn(register=False) as conn:
        missing = conn.execute(
            "SELECT id, fact FROM user_facts "
            "WHERE user_id = %s AND embedding IS NULL;",
            (user_id,),
        ).fetchall()
    if not missing:
        return
    with get_conn() as conn:  # register=True for vector params
        for fact_id, fact in missing:
            conn.execute(
                "UPDATE user_facts SET embedding = %s WHERE id = %s;",
                (embed_text(fact), fact_id),
            )


def _search_facts(user_id: int, query: str, k: int) -> list[str]:
    """Top-k facts most relevant to the query, by embedding cosine distance."""
    qvec = embed_text(query)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT fact FROM user_facts "
            "WHERE user_id = %s AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s;",
            (user_id, qvec, k),
        ).fetchall()
    return [r[0] for r in rows]


def relevant_preamble(user_id: int, query: str, k: int = _RELEVANT_K) -> str:
    """System-prompt block with only the facts *relevant* to `query` (Phase 25).

    Injecting the entire profile every turn wastes context and dilutes the
    relevant facts as it grows. Instead we embed the message and pull the top-k
    closest facts. Small profiles (<= k) skip the ranking (and its embed call)
    and just return everything — cheaper and identical in effect.
    """
    facts = get_facts(user_id)
    if not facts:
        return ""
    if len(facts) <= k or not (query or "").strip():
        return _format_preamble(facts)
    _backfill_embeddings(user_id)
    selected = _search_facts(user_id, query, k)
    return _format_preamble(selected or facts)


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
