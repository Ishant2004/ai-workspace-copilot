"""Thin wrapper around the Google Gemini SDK.

Phase 0 only needs one capability: take a list of chat messages and stream back
the model's reply token-by-token. Everything Gemini-specific lives here so the
rest of the app just sees a plain Python generator of text pieces.
"""

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


def stream_chat(messages: list[Message]) -> Iterator[str]:
    """Yield the assistant's reply in chunks as Gemini generates it."""
    response = _client.models.generate_content_stream(
        model=settings.gemini_model,
        contents=_to_gemini_contents(messages),
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text
