"""Tool-calling endpoints (Phase 10).

  GET  /tools        — list the available tools (for the UI)
  POST /tools/chat   — answer a message, letting the model call tools

The chat response is an SSE stream that surfaces the *whole* process, not just
the final answer, so you can watch the model decide to call a tool, see the
arguments and the result, and then read the grounded answer. Event types:
`tool_call`, `tool_result`, `chunk` (final answer), `done`, `error`.
"""

import json
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from models import ToolsChatRequest
from services import tools

router = APIRouter()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.get("/tools")
def list_tools() -> dict:
    return {"tools": tools.declarations()}


@router.post("/tools/chat")
def tools_chat(request: ToolsChatRequest) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        try:
            messages = [{"role": "user", "content": request.message}]
            for event in tools.run_tool_loop(messages):
                if event["type"] == "answer":
                    yield _sse({"type": "chunk", "content": event["content"]})
                else:
                    yield _sse(event)
            yield _sse({"type": "done"})
        except Exception as exc:
            yield _sse({"type": "error", "content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
