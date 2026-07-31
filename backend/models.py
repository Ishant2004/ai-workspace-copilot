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


class RagChatRequest(BaseModel):
    """Body of POST /rag/chat. Like a chat request, but the last user message
    is used to retrieve grounding documents before answering."""

    messages: list[Message]
    k: int = 4  # how many documents to retrieve as context


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


class DocumentRequest(BaseModel):
    """Body of POST /documents — a document to embed and store."""

    text: str
    title: str = ""


class DocumentResponse(BaseModel):
    id: int
    title: str
    total_documents: int


class DocumentItem(BaseModel):
    """A stored document as shown in the management list (no raw embedding)."""

    id: int
    title: str
    text: str
    metadata: dict = {}


class DeleteResponse(BaseModel):
    id: int
    deleted: bool
    total_documents: int


class UploadResponse(BaseModel):
    """Result of ingesting a PDF (POST /upload)."""

    filename: str
    pages: int
    chunks_stored: int
    total_documents: int


class SearchRequest(BaseModel):
    """Body of POST /search — a natural-language query."""

    query: str
    k: int = 5  # how many results to return
    # Which retrieval strategy to use (Phase 7).
    mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    # Rerank the retrieved candidates with a cross-encoder (Phase 8).
    rerank: bool = False


class SearchHit(BaseModel):
    id: int
    title: str
    text: str
    similarity: float  # cosine similarity 0..1 (0 for keyword-only hits)
    metadata: dict = {}
    # Which retriever(s) surfaced this hit (Phase 7): "vector" and/or "keyword".
    matched_by: list[str] = []
    # Fused rank score, present only for hybrid mode.
    rrf_score: float | None = None
    # Cross-encoder score, present only when reranking is on (Phase 8).
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    query: str
    mode: str
    results: list[SearchHit]


# --- Conversation memory (Phase 9) ---


class ThreadCreate(BaseModel):
    """Body of POST /threads (title optional)."""

    title: str = "New chat"


class ThreadItem(BaseModel):
    id: int
    title: str
    message_count: int = 0


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ThreadChatRequest(BaseModel):
    """Body of POST /threads/{id}/chat — one new user message to answer.

    Only the new message is sent; the backend loads the rest of the thread's
    history from the database itself.

    mode:
      - "chat"  plain conversation
      - "rag"   grounded in retrieved documents (Phase 4)
      - "agent" ReAct agent that decides which tools to call (Phase 11)
      - "plan"  plan-and-execute agent (Phase 12)
      - "team"  multi-agent pipeline: planner→retriever→solver→reviewer (Phase 16)
    """

    content: str
    mode: Literal["chat", "rag", "agent", "plan", "team"] = "chat"


class ToolsChatRequest(BaseModel):
    """Body of POST /tools/chat — a message the model may answer using tools."""

    message: str
