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

Tools provided: search_documents (our knowledge base), web_search (live web via
DuckDuckGo), fetch_url (read a page), analyze_csv (tabular data), calculate (safe
math), get_current_time.
"""

import ast
import csv
import io
import operator
from collections.abc import Iterator
from datetime import datetime, timezone

from google.genai import types

from services import extract, gemini, mcp_client
from services.search import run_search
from services.web import web_search

# How much fetched page text to hand back to the model (keeps the prompt bounded).
_FETCH_MAX_CHARS = 4000

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


def search_documents(user_id: int, query: str) -> str:
    """Search the user's knowledge base and return the top matching chunks."""
    hits = run_search(user_id, query, 3, "hybrid")
    if not hits:
        return "No matching documents found."
    return "\n\n".join(
        f"[#{h['id']}] {h['title']}\n{h['text']}" for h in hits
    )


def fetch_url(url: str) -> str:
    """Fetch a web page and return its readable text (truncated).

    web_search returns snippets + links; this lets the agent actually *read* a
    page it found to pull out the answer. Composes: search → fetch → answer.
    """
    try:
        text, title = extract.fetch_url(url)
    except Exception as exc:  # noqa: BLE001 - surface a usable message to the model
        return f"Could not fetch {url}: {exc}"
    text = text.strip()
    if not text:
        return f"No readable text found at {url}."
    snippet = text[:_FETCH_MAX_CHARS]
    suffix = "…" if len(text) > _FETCH_MAX_CHARS else ""
    return f"{title}\n{url}\n\n{snippet}{suffix}"


def analyze_csv(csv_text: str) -> str:
    """Parse small CSV text and return a summary: columns, row count, numeric
    aggregates (sum/mean/min/max), and a few sample rows.

    Deterministic (stdlib `csv`, no code execution), so the model can answer
    tabular questions — totals, averages, counts — from real computed numbers
    instead of guessing over raw rows.
    """
    try:
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        rows = list(reader)
    except Exception as exc:  # noqa: BLE001
        return f"Could not parse CSV: {exc}"
    cols = reader.fieldnames or []
    if not rows or not cols:
        return "No tabular data found in the CSV."

    lines = [f"Columns: {', '.join(cols)}", f"Rows: {len(rows)}"]
    for col in cols:
        nums = []
        for r in rows:
            raw = (r.get(col) or "").replace(",", "").replace("$", "").strip()
            try:
                nums.append(float(raw))
            except ValueError:
                pass
        # Treat a column as numeric only if most of its values parse as numbers.
        if len(nums) >= max(1, len(rows) // 2):
            total = sum(nums)
            lines.append(
                f"{col}: sum={total:g}, mean={total / len(nums):g}, "
                f"min={min(nums):g}, max={max(nums):g}"
            )
    lines.append("Sample rows:")
    for r in rows[:5]:
        lines.append("  " + ", ".join(f"{k}={v}" for k, v in r.items()))
    return "\n".join(lines)


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
    types.FunctionDeclaration(
        name="web_search",
        description=(
            "Search the live web for current, real-world information — weather, "
            "news, GitHub, docs, prices, anything the model may not know. Use "
            "this for anything current or beyond the user's own documents."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="The web search query.",
                )
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="fetch_url",
        description=(
            "Fetch a web page and return its readable text. Use after web_search "
            "to actually read a promising result and extract the answer."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "url": types.Schema(
                    type=types.Type.STRING,
                    description="The full http(s) URL of the page to read.",
                )
            },
            required=["url"],
        ),
    ),
    types.FunctionDeclaration(
        name="analyze_csv",
        description=(
            "Summarise small CSV data: columns, row count, numeric aggregates "
            "(sum/mean/min/max), and sample rows. Use to answer questions about "
            "tabular data the user provides (totals, averages, counts)."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "csv_text": types.Schema(
                    type=types.Type.STRING,
                    description="The raw CSV text, including the header row.",
                )
            },
            required=["csv_text"],
        ),
    ),
]

# Tools that don't need a user context.
_FUNCTIONS = {
    "get_current_time": get_current_time,
    "calculate": calculate,
    "web_search": web_search,
    "fetch_url": fetch_url,
    "analyze_csv": analyze_csv,
}


def declarations() -> list[dict]:
    """Lightweight tool list for the UI (name + description)."""
    return [{"name": d.name, "description": d.description} for d in _DECLARATIONS]


def dispatch(name: str, args: dict, user_id: int) -> str:
    # search_documents is scoped to the calling user.
    if name == "search_documents":
        try:
            return search_documents(user_id, **args)
        except Exception as exc:
            return f"Tool {name} failed: {exc}"
    # Other local tools need no user context.
    fn = _FUNCTIONS.get(name)
    if fn is not None:
        try:
            return str(fn(**args))
        except Exception as exc:
            return f"Tool {name} failed: {exc}"
    # Otherwise route to an external MCP tool (Phase 15).
    return mcp_client.call_tool(name, args)


# --- External (MCP) tools → Gemini declarations (Phase 15) ------------------

_JSON_TYPE_TO_GENAI = {
    "string": types.Type.STRING,
    "number": types.Type.NUMBER,
    "integer": types.Type.INTEGER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _json_schema_to_genai(schema: dict) -> types.Schema:
    """Convert an MCP tool's JSON-Schema (a dict) into Gemini's Schema type.

    Handles the common subset MCP tools use; anything unknown falls back to a
    permissive object/string so the tool is still callable.
    """
    if not isinstance(schema, dict):
        return types.Schema(type=types.Type.STRING)
    gtype = _JSON_TYPE_TO_GENAI.get(schema.get("type", "object"), types.Type.OBJECT)

    if gtype == types.Type.OBJECT:
        props = {
            key: _json_schema_to_genai(val)
            for key, val in (schema.get("properties") or {}).items()
        }
        return types.Schema(
            type=types.Type.OBJECT,
            properties=props or None,
            required=schema.get("required") or None,
        )
    if gtype == types.Type.ARRAY:
        return types.Schema(
            type=types.Type.ARRAY,
            items=_json_schema_to_genai(schema.get("items") or {"type": "string"}),
        )
    return types.Schema(type=gtype, description=schema.get("description"))


def _external_declarations() -> list[types.FunctionDeclaration]:
    """Discover external MCP tools and describe them for the model."""
    decls = []
    for name, info in mcp_client.discover().items():
        decls.append(
            types.FunctionDeclaration(
                name=name,
                description=info["description"],
                parameters=_json_schema_to_genai(info["schema"]),
            )
        )
    return decls


def all_declarations() -> list[types.FunctionDeclaration]:
    """Local tools plus any discovered external MCP tools."""
    return _DECLARATIONS + _external_declarations()


# --- The tool-calling loop --------------------------------------------------


def run_tool_loop(
    user_id: int,
    messages: list[dict],
    system_instruction: str | None = None,
) -> Iterator[dict]:
    """Drive the model through tool calls over a conversation, yielding events
    as they happen: {type: tool_call|tool_result|answer}.

    `user_id` scopes any document search the agent performs. `messages` is the
    conversation so far ({role, content}); the model sees it all, so the agent
    has context. This is the ReAct loop of Phase 11 — reason, act (call a tool),
    observe (its result), repeat.
    """
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=all_declarations())],
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
            result = dispatch(call.name, args, user_id)
            yield {"type": "tool_result", "name": call.name, "result": result}
            result_parts.append(
                types.Part.from_function_response(
                    name=call.name, response={"result": result}
                )
            )
        contents.append(types.Content(role="user", parts=result_parts))

    yield {"type": "answer", "content": "(stopped after the tool-step limit)"}


def stream_with_tools(
    user_id: int,
    messages: list[dict],
    system_instruction: str | None = None,
) -> Iterator[dict]:
    """Chat that can *optionally* reach for tools, but streams its final answer
    token-by-token (unlike run_tool_loop, which returns whole answers).

    Each round is a streaming generation. If the model streams text, we forward
    it as `chunk` events. If instead it asks for tools, we execute them (emitting
    `tool_call` / `tool_result`) and loop so it can answer with the results.

    This is what powers plain chat mode once tools are enabled there: a normal
    turn is a single stream (as fast as before), but the model can now search the
    web, the knowledge base, etc. when the question calls for it.
    """
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=all_declarations())],
        system_instruction=system_instruction,
    )

    for _ in range(MAX_STEPS):
        calls = []
        model_parts = []
        for chunk in gemini.generate_stream(contents, config):
            candidate = chunk.candidates[0] if chunk.candidates else None
            if candidate is None or candidate.content is None:
                continue
            for part in candidate.content.parts or []:
                if getattr(part, "function_call", None):
                    calls.append(part.function_call)
                    model_parts.append(part)
                elif getattr(part, "text", None):
                    model_parts.append(part)
                    yield {"type": "chunk", "content": part.text}

        if not calls:
            # The model answered in text (already streamed) — we're done.
            return

        # Record the model's tool-call turn, run the tools, then loop.
        contents.append(types.Content(role="model", parts=model_parts))
        result_parts = []
        for call in calls:
            args = dict(call.args or {})
            yield {"type": "tool_call", "name": call.name, "args": args}
            result = dispatch(call.name, args, user_id)
            yield {"type": "tool_result", "name": call.name, "result": result}
            result_parts.append(
                types.Part.from_function_response(
                    name=call.name, response={"result": result}
                )
            )
        contents.append(types.Content(role="user", parts=result_parts))
