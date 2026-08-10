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
import time
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
from services import coordinator, planner, profile, threads, tools, tracing
from services.gemini import stream_chat
from services.search import search_expanded

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


@router.get("/threads/{thread_id}/traces")
def get_traces(
    thread_id: int, user_id: int = Depends(current_user_id)
) -> list[dict]:
    """Recent per-turn traces for this thread (Phase 20 observability)."""
    if not threads.thread_exists(thread_id, user_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return tracing.list_thread_traces(thread_id, user_id)


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

    if request.regenerate:
        # Phase 28: re-answer the last question. Drop the previous answer; the
        # user message is already in history, so we don't add it again.
        threads.delete_last_answer(thread_id)
    else:
        # Persist the user's message first, so it's saved even if generation fails.
        threads.add_message(thread_id, "user", request.content)
        # Auto-title a brand-new thread from its first message.
        history = threads.get_messages(thread_id)
        if len(history) == 1:
            threads.update_title(thread_id, _make_title(request.content))

    def event_stream() -> Iterator[str]:
        reply = ""
        # Phase 20: a trace collects the timed spans of this turn (retrieval,
        # each tool call, generation) so the UI can show a little timeline.
        trace = tracing.Trace(user_id, thread_id, request.mode)
        try:
            # Replay only the recent window to the model (bounded prompt/cost).
            window = threads.get_recent_messages(
                thread_id, settings.history_window
            )
            # Phase 13: what we durably know about the user, injected into the
            # system prompt so the assistant remembers across conversations.
            # Phase 25: only the facts *relevant* to this message (semantic
            # retrieval over the profile), not the entire profile every turn.
            user_profile = profile.relevant_preamble(user_id, request.content)

            if request.mode == "rag":
                # RAG stays grounded on the retrieved documents only (no tools):
                # its whole point is answering *from the user's files*. Time
                # retrieval and generation as separate spans.
                messages = [
                    Message(role=m["role"], content=m["content"]) for m in window
                ]
                # Phase 21: expand the question into standalone/paraphrased
                # queries (resolving pronouns from prior turns) and fuse. History
                # excludes the just-persisted current message.
                prior = [m for m in window[:-1]]
                history_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in prior[-6:]
                )
                r_start = time.perf_counter()
                hits = search_expanded(
                    user_id, request.content, 4, history_text
                )
                trace.add(
                    "retrieval",
                    round((time.perf_counter() - r_start) * 1000),
                    strategy="multi_query"
                    if settings.retrieval_multi_query
                    else "hybrid",
                    hits=len(hits),
                )
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
                g_start = time.perf_counter()
                for piece in stream_chat(messages, system_prompt):
                    reply += piece
                    yield _sse({"type": "chunk", "content": piece})
                trace.add(
                    "generation",
                    round((time.perf_counter() - g_start) * 1000),
                    mode="rag",
                )
            else:
                # team / plan / agent / chat all yield an event stream. Pick the
                # right producer, then run one loop that (a) streams the events,
                # (b) times each tool call as a span, (c) accumulates the reply.
                #   - team (Phase 16): agent_start/agent_message per sub-agent.
                #   - plan (Phase 12): plan + step_start/step_result per step.
                #   - agent (Phase 11): tool_call/tool_result, answer → chunk.
                #   - chat: tool-aware, streamed token-by-token.
                if request.mode == "team":
                    events = coordinator.run_team(user_id, request.content)
                elif request.mode == "plan":
                    events = planner.run_plan(user_id, request.content)
                elif request.mode == "agent":
                    events = tools.run_tool_loop(
                        user_id,
                        window,
                        user_profile + build_agent_system_prompt(),
                    )
                else:  # chat
                    events = tools.stream_with_tools(
                        user_id,
                        window,
                        user_profile + build_chat_system_prompt(),
                    )

                pending: dict[str, float] = {}
                g_start = time.perf_counter()
                for event in events:
                    etype = event["type"]
                    if etype == "tool_call":
                        pending[event["name"]] = time.perf_counter()
                    elif etype == "tool_result":
                        started = pending.pop(event["name"], None)
                        if started is not None:
                            trace.add(
                                f"tool:{event['name']}",
                                round((time.perf_counter() - started) * 1000),
                                result_chars=len(event.get("result", "")),
                            )
                    # `answer` events (agent/plan/team) and `chunk` events (chat)
                    # both carry text and become chunks that accumulate the reply.
                    if etype in ("answer", "chunk"):
                        reply += event["content"]
                        yield _sse({"type": "chunk", "content": event["content"]})
                    else:
                        yield _sse(event)
                trace.add(
                    "generation",
                    round((time.perf_counter() - g_start) * 1000),
                    mode=request.mode,
                )

            # Persist the assistant's reply now that it's complete.
            if reply:
                threads.add_message(thread_id, "assistant", reply)
                # Phase 13: learn durable facts from this turn, in the
                # background so it never delays the response.
                profile.extract_in_background(user_id, request.content)

            # Finalise the trace: estimate tokens, persist, and send to the UI.
            trace.set_tokens(
                tracing.estimate_tokens(user_profile + request.content),
                tracing.estimate_tokens(reply),
            )
            try:
                tracing.save_trace(trace)
            except Exception:  # tracing must never break the chat itself
                pass
            yield _sse({"type": "trace", "trace": trace.summary()})
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
