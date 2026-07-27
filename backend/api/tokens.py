"""The /tokenize endpoint (Phase 1: Token Inspector).

LLMs don't read characters or words — they read *tokens* (sub-word chunks).
Every limit and price is measured in tokens, so understanding token counts is
the foundation for reasoning about context windows and cost. This endpoint
turns a piece of text into those numbers.
"""

from fastapi import APIRouter

from config import settings
from models import TokenizeRequest, TokenizeResponse
from services.gemini import count_tokens

router = APIRouter()


@router.post("/tokenize", response_model=TokenizeResponse)
def tokenize(request: TokenizeRequest) -> TokenizeResponse:
    text = request.text

    characters = len(text)
    words = len(text.split())  # whitespace-separated; a rough human unit
    tokens = count_tokens(text)

    # Fraction of the model's context window this text would occupy.
    context_percent = (tokens / settings.gemini_context_window) * 100

    # Paid-tier reference cost: price is quoted per 1,000,000 tokens.
    reference_cost = (tokens / 1_000_000) * settings.gemini_input_price_per_1m

    return TokenizeResponse(
        model=settings.gemini_model,
        characters=characters,
        words=words,
        tokens=tokens,
        context_window=settings.gemini_context_window,
        context_used_percent=round(context_percent, 6),
        estimated_cost_usd=0.0,  # free tier
        reference_cost_usd=round(reference_cost, 8),
    )
