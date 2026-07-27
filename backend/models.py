"""Pydantic request/response schemas shared across the API.

These are the contracts between the frontend and backend. Validation happens
automatically: if the frontend sends the wrong shape, FastAPI rejects it with a
422 before our code ever runs.
"""

from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    """A single turn in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Body of POST /chat. The full message history is sent every time because
    the LLM itself is stateless — it only knows what we hand it in the prompt."""

    messages: list[Message]
