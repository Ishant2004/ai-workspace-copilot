"""Contextual retrieval (Phase 22).

When a long document is split into chunks, each chunk is embedded in isolation —
so "It increased 3% quarter over quarter" embeds as a vague statement about a 3%
increase, with no hint it's about ACME's Q2 revenue. Retrieval then misses it for
"ACME Q2 revenue growth".

The fix (Anthropic's "contextual retrieval"): before embedding, prepend a short
model-written sentence that situates the chunk in its document. We embed the
*contextualized* text but keep the *original* chunk text for display and keyword
search — so citations stay clean while the vector captures the topic.

The context call is best-effort and retried; on failure we fall back to a cheap
heuristic (the document title), so ingestion never breaks.
"""

import logging
import time

from google.genai import types

from prompts import build_context_prompt
from services import gemini

logger = logging.getLogger("uvicorn.error")

# Cap the document text we send as context so the prompt stays bounded on big
# files (the chunk itself is always included in full).
_MAX_DOC_CHARS = 8000


def contextualize(doc_title: str, doc_text: str, chunk: str) -> str:
    """Return a one-sentence context situating `chunk` within its document."""
    prompt = build_context_prompt(doc_title, doc_text[:_MAX_DOC_CHARS], chunk)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    for attempt in range(3):
        try:
            response = gemini.generate(contents)
            line = (response.text or "").strip()
            if line:
                return line
        except Exception as exc:  # noqa: BLE001 - best-effort enrichment
            logger.warning("Contextualize failed (attempt %s): %s", attempt + 1, exc)
            time.sleep(10 * (attempt + 1))
    return f"From {doc_title}."  # heuristic fallback so ingestion never fails


def contextual_text(context: str, chunk: str) -> str:
    """Combine a context line and chunk into the text we embed."""
    return f"{context}\n\n{chunk}"


def contextualize_all(
    doc_title: str, doc_text: str, chunks: list[str]
) -> list[str]:
    """Context line for each chunk (one model call per chunk)."""
    return [contextualize(doc_title, doc_text, c) for c in chunks]
