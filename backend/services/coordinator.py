"""Multi-agent coordinator (Phase 16).

Instead of one model doing everything, a small team of specialists hands work
down a line, each with its own focused role and system prompt:

    Planner  → outlines the approach
    Retriever → gathers relevant context from the knowledge base
    Solver   → drafts an answer using the plan + context
    Reviewer → checks and polishes it into the final answer

The "coordinator" is just lightweight Python that runs them in order and passes
each output to the next — no framework needed. Splitting the work into narrow,
single-purpose prompts tends to produce better results than one do-everything
prompt, and it makes each step's contribution visible.
"""

from collections.abc import Iterator

from google.genai import types

from prompts import (
    build_reviewer_prompt,
    build_solver_prompt,
    build_team_planner_prompt,
)
from services import gemini
from services.search import run_search

_MAX_RETRIES = 2  # per model call, for transient failures


def _generate(prompt: str) -> str:
    """One focused LLM call, retried a couple times for transient errors."""
    last = ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = gemini.generate(
                [types.Content(role="user", parts=[types.Part(text=prompt)])]
            )
            return (resp.text or "").strip()
        except Exception as exc:
            last = str(exc)
    raise RuntimeError(last)


def run_team(user_id: int, goal: str) -> Iterator[dict]:
    """Run the pipeline, yielding events:
    agent_start | agent_message | answer."""

    # 1. Planner — outline the approach.
    yield {"type": "agent_start", "role": "Planner"}
    plan = _generate(build_team_planner_prompt(goal))
    yield {"type": "agent_message", "role": "Planner", "content": plan}

    # 2. Retriever — gather context from the user's knowledge base
    #    (deterministic hybrid search; this is the tool the retriever role uses).
    yield {"type": "agent_start", "role": "Retriever"}
    hits = run_search(user_id, goal, 4, "hybrid")
    context = "\n\n".join(
        f"[#{h['id']}] {h['title']}\n{h['text']}" for h in hits
    )
    found = (
        "Found:\n" + "\n".join(f"- {h['title'] or f'Document {h['id']}'}" for h in hits)
        if hits
        else "No relevant documents found."
    )
    yield {"type": "agent_message", "role": "Retriever", "content": found}

    # 3. Solver — draft an answer from the plan + context.
    yield {"type": "agent_start", "role": "Solver"}
    draft = _generate(build_solver_prompt(goal, plan, context))
    yield {"type": "agent_message", "role": "Solver", "content": draft}

    # 4. Reviewer — polish into the final answer. The polished text is the
    #    final answer (streamed as `answer`); the card gets a short note so it
    #    doesn't look unfinished.
    yield {"type": "agent_start", "role": "Reviewer"}
    final = _generate(build_reviewer_prompt(goal, draft, context))
    yield {
        "type": "agent_message",
        "role": "Reviewer",
        "content": "Refined the draft into the final answer below.",
    }
    yield {"type": "answer", "content": final}
