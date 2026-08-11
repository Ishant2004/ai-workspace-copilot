"""Prompt-injection detection for ingested/retrieved content (Phase 29).

The real defence against injected documents is the RAG prompt telling the model
to treat context as untrusted data (see prompts.build_rag_system_prompt). This
adds a cheap second layer: a heuristic scan for the tell-tale phrases of an
injection attempt, so we can *flag and audit* suspicious retrieved chunks.

It's deliberately detection-only (not blocking): heuristics have false positives,
and a legitimate document might quote these phrases. We surface the signal rather
than silently dropping the user's own content.
"""

import re

# Phrases that commonly appear in prompt-injection payloads.
_PATTERNS = [
    r"ignore (all |your |the )?(previous|prior|above) (instructions|prompts?)",
    r"disregard (all |the )?(previous|prior|above)",
    r"forget (everything|all|your instructions)",
    r"you are now",
    r"new instructions?:",
    r"system prompt",
    r"reveal (your|the) (system )?prompt",
    r"act as (an? )?(dan|jailbreak)",
]
_REGEX = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def looks_injected(text: str) -> bool:
    """True if the text contains a likely prompt-injection phrase."""
    return bool(_REGEX.search(text or ""))
