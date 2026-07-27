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


class TokenizeRequest(BaseModel):
    """Body of POST /tokenize."""

    text: str


class TokenizeResponse(BaseModel):
    """Metrics returned by POST /tokenize.

    Characters/words are cheap local counts; tokens come from the model's real
    tokenizer. Cost and context% help build intuition for how much of the
    model's budget a prompt consumes.
    """

    model: str
    characters: int
    words: int
    tokens: int
    context_window: int
    context_used_percent: float
    # Actual cost on the free tier (always 0). Kept explicit so the UI can show
    # "$0.00 (free tier)" honestly.
    estimated_cost_usd: float
    # What this many tokens would cost at paid-tier pricing — for intuition.
    reference_cost_usd: float


class EmbedRequest(BaseModel):
    """Body of POST /embed."""

    text: str


class EmbedResponse(BaseModel):
    """A text embedding plus metadata.

    `embedding` is a list of floats (a point in high-dimensional space).
    `dimension` is its length. Same model + dimension must be reused for every
    document so vectors are comparable in the vector DB later.
    """

    model: str
    dimension: int
    embedding: list[float]
