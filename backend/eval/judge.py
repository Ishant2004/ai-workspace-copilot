"""LLM-as-judge (Phase 19).

Phase 18's substring checks answer "is the expected fact present?" — but not "is
the answer *grounded* in the retrieved context, or hallucinated?" nor "does it
actually address the question?". A model is well suited to grade those, so we ask
a separate Gemini call to score each answer 1-5 on faithfulness and relevance,
with a one-line rationale so a low score is explainable.

Using structured JSON output (response_schema) means we get back clean numbers,
not prose we'd have to parse.
"""

import json
import time

from google.genai import types

from prompts import build_judge_prompt
from services import gemini

# Force the model to return exactly the fields we score on, as integers/string.
_JUDGE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "faithfulness": types.Schema(type=types.Type.INTEGER),
        "relevance": types.Schema(type=types.Type.INTEGER),
        "rationale": types.Schema(type=types.Type.STRING),
    },
    required=["faithfulness", "relevance", "rationale"],
)


def _clamp(value, lo: int = 1, hi: int = 5) -> int:
    """Keep a score in range even if the model returns something odd."""
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return lo


def judge_answer(question: str, context: str, answer: str) -> dict:
    """Grade one answer. Returns {faithfulness, relevance, rationale}.

    On repeated failure we return the lowest scores with an error rationale so a
    flaky judge call surfaces as a bad grade rather than crashing the whole run.
    """
    prompt = build_judge_prompt(question, context, answer)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_JUDGE_SCHEMA,
    )

    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            response = gemini.generate(contents, config)
            data = json.loads(response.text or "{}")
            return {
                "faithfulness": _clamp(data.get("faithfulness")),
                "relevance": _clamp(data.get("relevance")),
                "rationale": (data.get("rationale") or "").strip(),
            }
        except Exception as exc:  # noqa: BLE001 - eval must be robust
            last_exc = exc
            # Long backoff so a free-tier 429 cooldown (~27s) can pass.
            time.sleep(15 * (attempt + 1))

    return {
        "faithfulness": 1,
        "relevance": 1,
        "rationale": f"judge failed: {last_exc}",
    }
