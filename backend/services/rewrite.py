"""Query rewriting & expansion (Phase 21).

Retrieval quality is capped by the query you feed it. A raw user message is often
a poor search query: it leans on pronouns ("how many can I carry over?") and uses
different words than the documents. This module turns one message into a small set
of **standalone, paraphrased queries** — the original intent made self-contained,
plus a couple of vocabulary variants — which the caller retrieves for and fuses
(RRF) into a single ranked list.

The LLM call is best-effort: if it fails or returns nothing usable, we fall back
to the original question, so retrieval always has at least one query to run.
"""

import json
import logging

from google.genai import types

from prompts import build_rewrite_prompt
from services import gemini

logger = logging.getLogger("uvicorn.error")

_QUERIES_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "queries": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        )
    },
    required=["queries"],
)


def expand_query(question: str, history: str = "", n: int = 3) -> list[str]:
    """Return up to n standalone search queries for `question`.

    The first is always usable — on any failure we return just the original
    question, so callers can treat the result as "one or more queries to run".
    """
    question = (question or "").strip()
    if not question:
        return []

    prompt = build_rewrite_prompt(question, history, n)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_QUERIES_SCHEMA,
    )
    try:
        response = gemini.generate(contents, config)
        data = json.loads(response.text or "{}")
        queries = [q.strip() for q in data.get("queries", []) if q and q.strip()]
    except Exception as exc:  # noqa: BLE001 - rewriting is best-effort
        logger.warning("Query rewrite failed, using original: %s", exc)
        queries = []

    # Always include the original, de-duplicate (case-insensitive), keep order.
    out: list[str] = []
    seen: set[str] = set()
    for q in [question, *queries]:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out[:n]
