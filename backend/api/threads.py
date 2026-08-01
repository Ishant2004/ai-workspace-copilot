"""Conversation thread endpoints (Phase 9).

CRUD over persisted conversations, plus a streaming chat that remembers:

  POST   /threads                 — create a conversation
  GET    /threads                 — list conversations
  GET    /threads/{id}/messages   — full history of one conversation
  DELETE /threads/{id}            — delete a conversation
  POST   /threads/{id}/chat       — send a message; the backend loads history,
                                    answers (optionally with RAG), and persists
                                    both the question and the answer

The key difference from the stateless /chat (Phase 0): the frontend sends only
the *new* message. History lives in the database, and we replay a sliding window
of it to the model each turn.
"""

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.deps import current_user_id
from config import settings
from models import (
    Message,
    ThreadChatRequest,
    ThreadCreate,
    ThreadItem,
    ThreadMessage,
)
from prompts import (
    build_agent_system_prompt,
    build_chat_system_prompt,
    build_rag_system_prompt,
    format_context_block,
)
from services import coordinator, planner, profile, threads, tools
from services.gemini import stream_chat
from services.search import run_search

router = APIRouter()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.post("/threads", response_model=ThreadItem)
def create_thread(
    body: ThreadCreate, user_id: int = Depends(current_user_id)
) -> ThreadItem:
    return ThreadItem(**threads.create_thread(user_id, body.title))


@router.get("/threads", response_model=list[ThreadItem])
def list_threads(user_id: int = Depends(current_user_id)) -> list[ThreadItem]:
    return [ThreadItem(**t) for t in threads.list_threads(user_id)]


@router.get("/threads/{thread_id}/messages", response_model=list[ThreadMessage])
def get_messages(
    thread_id: int, user_id: int = Depends(current_user_id)
) -> list[ThreadMessage]:
    if not threads.thread_exists(thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return [ThreadMessage(**m) for m in threads.get_messages(thread_id)]


@router.delete("/threads/{thread_id}")
def delete_thread(
    thread_id: int, user_id: int = Depends(current_user_id)
) -> dict:
    if not threads.delete_thread(thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"deleted": True, "id": thread_id}


@router.post("/threads/{thread_id}/chat")
def thread_chat(
    thread_id: int,
    request: ThreadChatRequest,
    user_id: int = Depends(current_user_id),
) -> StreamingResponse:
    if not threads.thread_exists(thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    # Persist the user's message first, so it's saved even if generation fails.
    threads.add_message(thread_id, "user", request.content)

    # Auto-title a brand-new thread from its first message.
    history = threads.get_messages(thread_id)
    if len(history) == 1:
        threads.update_title(thread_id, _make_title(request.content))

    def event_stream() -> Iterator[str]:
        reply = ""
        try:
            # Replay only the recent window to the model (bounded prompt/cost).
            window = threads.get_recent_messages(
                thread_id, settings.history_window
            )
            # Phase 13: what we durably know about the user, injected into the
            # system prompt so the assistant remembers across conversations.
            user_profile = profile.preamble(user_id)

            if request.mode == "team":
                # Phase 16: multi-agent pipeline. Each sub-agent's contribution
                # streams as agent_start/agent_message; the reviewer's output is
                # the final answer (an `answer` event → chunk).
                for event in coordinator.run_team(user_id, request.content):
                    if event["type"] == "answer":
                        reply += event["content"]
                        yield _sse({"type": "chunk", "content": event["content"]})
                    else:
                        yield _sse(event)
            elif request.mode == "plan":
                # Phase 12: plan-and-execute. Emit the plan and each step's
                # progress; the synthesized final answer arrives as `answer`.
                for event in planner.run_plan(user_id, request.content):
                    if event["type"] == "answer":
                        reply += event["content"]
                        yield _sse({"type": "chunk", "content": event["content"]})
                    else:
                        yield _sse(event)
            elif request.mode == "agent":
                # Phase 11: the agent decides which tools to call, looping until
                # it can answer. Surface each tool call/result; the final answer
                # arrives as `answer` events which we stream as chunks.
                for event in tools.run_tool_loop(
                    user_id, window, user_profile + build_agent_system_prompt()
                ):
                    if event["type"] == "answer":
                        reply += event["content"]
                        yield _sse({"type": "chunk", "content": event["content"]})
                    else:
                        yield _sse(event)
            elif request.mode == "rag":
                # RAG stays grounded on the retrieved documents only (no tools):
                # its whole point is answering *from the user's files*.
                messages = [
                    Message(role=m["role"], content=m["content"]) for m in window
                ]
                hits = run_search(user_id, request.content, 4, "hybrid")
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
                blocks = [
                    format_context_block(h["id"], h["title"], h["text"])
                    for h in hits
                ]
                system_prompt = user_profile + build_rag_system_prompt(blocks)
                for piece in stream_chat(messages, system_prompt):
                    reply += piece
                    yield _sse({"type": "chunk", "content": piece})
            else:
                # Plain chat: conversational, but it can quietly reach for tools
                # (web_search, search_documents, calculate…) when the question
                # needs live or computed facts. Streams token-by-token.
                system_prompt = user_profile + build_chat_system_prompt()
                for event in tools.stream_with_tools(
                    user_id, window, system_prompt
                ):
                    if event["type"] == "chunk":
                        reply += event["content"]
                    yield _sse(event)

            # Persist the assistant's reply now that it's complete.
            if reply:
                threads.add_message(thread_id, "assistant", reply)
                # Phase 13: learn durable facts from this turn, in the
                # background so it never delays the response.
                profile.extract_in_background(user_id, request.content)
            yield _sse({"type": "done"})
        except Exception as exc:
            yield _sse({"type": "error", "content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _make_title(text: str) -> str:
    """A short thread title from the first message."""
    title = " ".join(text.strip().split())
    return title[:40] + ("…" if len(title) > 40 else "") or "New chat"
