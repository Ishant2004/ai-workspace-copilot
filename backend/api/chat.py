"""The /chat endpoint.

We stream the reply using Server-Sent Events (SSE). Streaming matters because a
full LLM answer can take several seconds; sending it word-by-word makes the UI
feel instant instead of frozen.

SSE wire format: each event is a line beginning with "data: " followed by the
payload and a blank line. We send small JSON objects so the frontend can tell a
normal text chunk apart from the "done" signal or an error.
"""

import json
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from models import ChatRequest
from services.gemini import stream_chat

router = APIRouter()


def _sse(data: dict) -> str:
    """Format one dict as a single SSE event."""
    return f"data: {json.dumps(data)}\n\n"


@router.post("/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        try:
            for piece in stream_chat(request.messages):
                yield _sse({"type": "chunk", "content": piece})
            yield _sse({"type": "done"})
        except Exception as exc:  # surface the error to the UI instead of hanging
            yield _sse({"type": "error", "content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
