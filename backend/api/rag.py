"""RAG chat endpoint (Phase 4: Retrieval-Augmented Generation).

This is where the previous phases come together. Plain chat (Phase 0) answers
from the model's own memory. RAG instead *grounds* the answer in the user's own
documents:

    question -> embed -> vector search (top-k) -> build grounded prompt
             -> Gemini -> stream answer (with citations)

The wire format matches /chat's SSE, with one addition: before any answer text
we emit a `sources` event listing the retrieved documents, so the UI can show
exactly what the answer was based on.
"""

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.deps import current_user_id
from models import Message, RagChatRequest
from prompts import build_rag_system_prompt, format_context_block
from services import db
from services.gemini import embed_text, stream_chat

router = APIRouter()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _last_user_message(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


@router.post("/rag/chat")
def rag_chat(
    request: RagChatRequest, user_id: int = Depends(current_user_id)
) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        try:
            # 1. Retrieve: embed the latest question and find similar documents.
            query = _last_user_message(request.messages)
            hits = db.search(user_id, embed_text(query), request.k) if query else []

            # 2. Tell the UI which documents we're grounding on, up front.
            yield _sse(
                {
                    "type": "sources",
                    "sources": [
                        {
                            "id": h["id"],
                            "title": h["title"],
                            "similarity": h["similarity"],
                        }
                        for h in hits
                    ],
                }
            )

            # 3. Build the grounded prompt from the retrieved text.
            context_blocks = [
                format_context_block(h["id"], h["title"], h["text"])
                for h in hits
            ]
            system_prompt = build_rag_system_prompt(context_blocks)

            # 4. Generate: stream the grounded answer just like /chat.
            for piece in stream_chat(request.messages, system_prompt):
                yield _sse({"type": "chunk", "content": piece})
            yield _sse({"type": "done"})
        except Exception as exc:
            yield _sse({"type": "error", "content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
