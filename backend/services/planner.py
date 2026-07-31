"""Plan-and-execute agent (Phase 12).

The Phase 11 agent is *reactive*: it decides the next tool one step at a time.
That's great for simple requests but can wander on complex, multi-part ones.
Plan-and-execute instead:

  1. PLAN   — ask the model for an explicit, ordered list of subtasks (as JSON).
  2. EXECUTE — run each subtask with the tool agent, feeding prior results
               forward, retrying on transient failures.
  3. SYNTHESIZE — combine the step results into one final answer.

Committing to a plan up front makes the agent's strategy visible and each step
independently checkable. We stream the plan and every step's progress so the UI
can show the whole workflow.
"""

import json
from collections.abc import Iterator

from google.genai import types

from prompts import (
    build_agent_system_prompt,
    build_planner_prompt,
    build_step_prompt,
    build_synthesis_prompt,
)
from services import gemini, tools

MAX_RETRIES = 2  # per step, for transient model errors


# JSON schema that forces the planner to return a clean list of steps.
_PLAN_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "steps": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={"task": types.Schema(type=types.Type.STRING)},
                required=["task"],
            ),
        )
    },
    required=["steps"],
)


def make_plan(goal: str) -> list[str]:
    """Return an ordered list of subtask descriptions for the goal."""
    response = gemini.generate(
        [types.Content(role="user", parts=[types.Part(text=build_planner_prompt(goal))])],
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_PLAN_SCHEMA,
        ),
    )
    data = json.loads(response.text or "{}")
    tasks = [s["task"] for s in data.get("steps", []) if s.get("task")]
    return tasks or [goal]  # fall back to treating the goal as one step


def _execute_step(
    user_id: int, goal: str, task: str, prior: list[str]
) -> Iterator[dict]:
    """Run one step with the tool agent, retrying transient failures.

    Yields the loop's tool_call/tool_result events plus a final step_result.
    """
    prompt = build_step_prompt(goal, task, prior)
    messages = [{"role": "user", "content": prompt}]

    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        events: list[dict] = []
        result = ""
        try:
            for event in tools.run_tool_loop(
                user_id, messages, build_agent_system_prompt()
            ):
                if event["type"] == "answer":
                    result = event["content"]
                else:
                    events.append(event)
            # Success: emit buffered tool events, then the step result.
            yield from events
            yield {"type": "step_result", "result": result}
            return
        except Exception as exc:  # transient (e.g. model 503) — retry
            last_error = str(exc)

    yield {"type": "step_result", "result": f"[step failed: {last_error}]"}


def run_plan(user_id: int, goal: str) -> Iterator[dict]:
    """Plan, execute each step, then synthesize. Yields events:
    plan | step_start | tool_call | tool_result | step_result | answer."""
    tasks = make_plan(goal)
    yield {"type": "plan", "steps": [{"task": t} for t in tasks]}

    prior: list[str] = []
    for i, task in enumerate(tasks):
        yield {"type": "step_start", "index": i, "task": task}
        result = ""
        for event in _execute_step(user_id, goal, task, prior):
            if event["type"] == "step_result":
                result = event["result"]
                yield {"type": "step_result", "index": i, "result": result}
            else:
                yield event
        prior.append(f"{i + 1}. {task}: {result}")

    # Synthesize the final answer from all the step results.
    response = gemini.generate(
        [
            types.Content(
                role="user",
                parts=[types.Part(text=build_synthesis_prompt(goal, prior))],
            )
        ]
    )
    yield {"type": "answer", "content": response.text or ""}
