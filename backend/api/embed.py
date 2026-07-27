"""The /embed endpoint (Phase 2: Embedding Service).

An *embedding* maps a piece of text to a fixed-length vector of numbers such
that texts with similar meaning land close together in that vector space. This
is the raw material for semantic search and RAG (coming in later phases): to
find relevant documents we will embed the query and look for the nearest
document vectors.

This endpoint just exposes that mapping so we can see and reason about it.
"""

from fastapi import APIRouter

from config import settings
from models import EmbedRequest, EmbedResponse
from services.gemini import embed_text

router = APIRouter()


@router.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> EmbedResponse:
    vector = embed_text(request.text)
    return EmbedResponse(
        model=settings.gemini_embed_model,
        dimension=len(vector),
        embedding=vector,
    )
