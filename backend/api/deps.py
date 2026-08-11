"""Shared request dependencies (per-user segregation).

`current_user_id` is a FastAPI dependency that reads the `Authorization: Bearer
<token>` header, validates the JWT, and returns the caller's user id. Every
data endpoint depends on it, so a request can only ever touch its own rows.
"""

from fastapi import Depends, Header, HTTPException

from config import settings
from services import auth, ratelimit


def current_user_id(authorization: str = Header(default="")) -> int:
    """Extract and validate the user id from the Authorization header."""
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = auth.decode_token(authorization[len(prefix):])
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


def rate_limited_user_id(user_id: int = Depends(current_user_id)) -> int:
    """Like current_user_id, but also enforces the per-user rate limit (Phase 29).

    Use on expensive endpoints (chat, upload, ingest). Over the limit → 429.
    """
    if not ratelimit.allow(
        f"user:{user_id}",
        settings.rate_limit_max,
        settings.rate_limit_window_seconds,
    ):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — please slow down and retry shortly.",
        )
    return user_id
