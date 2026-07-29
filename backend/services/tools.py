"""Tool calling / function calling (Phase 10).

An LLM can't *do* anything on its own — it only produces text. "Tool calling"
lets it ask *us* to run a function: we hand the model a list of tool
declarations (name, description, JSON-schema arguments); when it needs one, it
replies not with prose but with a structured `function_call`. We execute the
real Python function, hand the result back, and let the model continue. This is
how an LLM reaches live data and real computation.

The loop here is deliberately explicit (rather than the SDK's automatic function
calling) so the mechanics are visible:

    prompt + tool declarations ─► model
        └─ returns function_call(s) ─► we run them ─► return results ─► model
        └─ returns text ─► done

Tools provided: search_documents (our knowledge base), calculate (safe math),
get_current_time.
"""

import ast
import operator
from collections.abc import Iterator
from datetime import datetime, timezone

from google.genai import types

from services import gemini
from services.search import run_search

MAX_STEPS = 5  # safety cap on tool-call rounds


# --- The actual Python functions -------------------------------------------


def get_current_time() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# Only these AST node types are allowed in `calculate`, so we never `eval`
# arbitrary code — just arithmetic.
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](
            _eval_node(node.left), _eval_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval_node(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    raise ValueError("unsupported expression")


def calculate(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression (+ - * / ** %)."""
    try:
        result = _eval_node(ast.parse(expression, mode="eval").body)
        return str(result)
    except Exception:
        return f"Could not evaluate expression: {expression!r}"


def search_documents(query: str) -> str:
    """Search the stored knowledge base and return the top matching chunks."""
    hits = run_search(query, 3, "hybrid")
    if not hits:
        return "No matching documents found."
    return "\n\n".join(
        f"[#{h['id']}] {h['title']}\n{h['text']}" for h in hits
    )


# --- Declarations the model sees (name + JSON-schema args) -----------------

_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_current_time",
        description="Get the current date and time in UTC (ISO-8601).",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="calculate",
        description="Evaluate a basic arithmetic expression, e.g. '3 * (4 + 5)'.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "expression": types.Schema(
                    type=types.Type.STRING,
                    description="The arithmetic expression to evaluate.",
                )
            },
            required=["expression"],
        ),
    ),
    types.FunctionDeclaration(
        name="search_documents",
        description=(
            "Search the user's uploaded documents / knowledge base for "
            "information relevant to a query."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="What to look for in the documents.",
                )
            },
            required=["query"],
        ),
    ),
]

_FUNCTIONS = {
    "get_current_time": get_current_time,
    "calculate": calculate,
    "search_documents": search_documents,
}


def declarations() -> list[dict]:
    """Lightweight tool list for the UI (name + description)."""
    return [{"name": d.name, "description": d.description} for d in _DECLARATIONS]


def dispatch(name: str, args: dict) -> str:
    fn = _FUNCTIONS.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    try:
        return str(fn(**args))
    except Exception as exc:
        return f"Tool {name} failed: {exc}"


# --- The tool-calling loop --------------------------------------------------


def run_tool_loop(
    messages: list[dict], system_instruction: str | None = None
) -> Iterator[dict]:
    """Drive the model through tool calls over a conversation, yielding events
    as they happen: {type: tool_call|tool_result|answer}.

    `messages` is the conversation so far ({role, content}); the model sees it
    all, so the agent has context. This is the ReAct loop of Phase 11 — reason,
    act (call a tool), observe (its result), repeat — and also backs the simple
    single-message tool demo.
    """
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=_DECLARATIONS)],
        system_instruction=system_instruction,
    )

    for _ in range(MAX_STEPS):
        response = gemini.generate(contents, config)
        candidate = response.candidates[0]
        parts = candidate.content.parts or []
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        if not calls:
            # No more tools requested — the model produced the final answer.
            yield {"type": "answer", "content": response.text or ""}
            return

        # Record the model's turn (its function-call request), then execute.
        contents.append(candidate.content)
        result_parts = []
        for call in calls:
            args = dict(call.args or {})
            yield {"type": "tool_call", "name": call.name, "args": args}
            result = dispatch(call.name, args)
            yield {"type": "tool_result", "name": call.name, "result": result}
            result_parts.append(
                types.Part.from_function_response(
                    name=call.name, response={"result": result}
                )
            )
        contents.append(types.Content(role="user", parts=result_parts))

    yield {"type": "answer", "content": "(stopped after the tool-step limit)"}
