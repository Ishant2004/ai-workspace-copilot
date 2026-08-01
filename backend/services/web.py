"""Web search (live internet access for the agent).

Gives the agent a window onto the live web — weather, GitHub, news, docs, any
current fact the model's training data can't know. We use DuckDuckGo via the
`ddgs` package: no API key, no signup, independent of the Gemini quota.

It returns a compact list of results (title, snippet, URL); the agent reads
those and synthesizes an answer, citing the links.
"""

import logging

from ddgs import DDGS

logger = logging.getLogger("uvicorn.error")


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return the top results as text."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:
        logger.warning("Web search failed: %s", exc)
        return f"Web search failed: {exc}"

    if not results:
        return "No web results found."

    blocks = []
    for r in results:
        title = r.get("title", "").strip()
        body = r.get("body", "").strip()
        url = r.get("href", "").strip()
        blocks.append(f"{title}\n{body}\n{url}")
    return "\n\n".join(blocks)
