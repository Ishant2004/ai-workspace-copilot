"""Thin wrapper around the Google Gemini SDK.

Everything Gemini-specific lives here so the rest of the app never imports the
SDK directly. Capabilities exposed so far:
  - stream_chat:  stream a chat reply token-by-token (Phase 0)
  - count_tokens: exact token count for a string (Phase 1)
  - embed_text:   turn a string into an embedding vector (Phase 2)
"""

import math
from collections.abc import Iterator

from google import genai
from google.genai import types

from config import settings
from models import Message

# One client for the whole process. It is cheap to keep around and reuses the
# underlying HTTP connection.
_client = genai.Client(api_key=settings.gemini_api_key)


def _to_gemini_contents(messages: list[Message]) -> list[types.Content]:
    """Convert our simple {role, content} messages into Gemini's format.

    Gemini uses the role name "model" for the assistant, so we translate.
    """
    contents: list[types.Content] = []
    for m in messages:
        role = "model" if m.role == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=m.content)])
        )
    return contents


def stream_chat(
    messages: list[Message], system_instruction: str | None = None
) -> Iterator[str]:
    """Yield the assistant's reply in chunks as Gemini generates it.

    `system_instruction` is an optional up-front instruction that steers the
    model without being part of the visible conversation. RAG (Phase 4) uses it
    to inject the retrieved document context and the "answer only from this"
    rule.
    """
    config = None
    if system_instruction:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction
        )
    response = _client.models.generate_content_stream(
        model=settings.gemini_model,
        contents=_to_gemini_contents(messages),
        config=config,
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text


def embed_text(text: str) -> list[float]:
    """Turn a string into an embedding: a fixed-length list of floats that
    captures its meaning. Texts with similar meaning produce vectors that point
    in similar directions — that is what makes semantic search possible later.

    We truncate to `gemini_embed_dim` dimensions and normalize to unit length.
    Google recommends normalizing when using a reduced dimension, and unit
    vectors make cosine-similarity math in the vector DB simpler.
    """
    result = _client.models.embed_content(
        model=settings.gemini_embed_model,
        contents=text,
        config=types.EmbedContentConfig(
            output_dimensionality=settings.gemini_embed_dim
        ),
    )
    vector = list(result.embeddings[0].values)

    magnitude = math.sqrt(sum(v * v for v in vector))
    if magnitude > 0:
        vector = [v / magnitude for v in vector]
    return vector


def count_tokens(text: str) -> int:
    """Ask Gemini exactly how many tokens a piece of text costs.

    Token counts are model-specific: the same words tokenize differently across
    models. Rather than guess with a local heuristic, we use the model's own
    tokenizer via the API so the number is exact for the model we actually use.
    """
    result = _client.models.count_tokens(
        model=settings.gemini_model,
        contents=[types.Content(role="user", parts=[types.Part(text=text)])],
    )
    return result.total_tokens
