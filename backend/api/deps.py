"""Shared request dependencies (per-user segregation).

`current_user_id` is a FastAPI dependency that reads the `Authorization: Bearer
<token>` header, validates the JWT, and returns the caller's user id. Every
data endpoint depends on it, so a request can only ever touch its own rows.
"""

from fastapi import Header, HTTPException

from services import auth


def current_user_id(authorization: str = Header(default="")) -> int:
    """Extract and validate the user id from the Authorization header."""
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = auth.decode_token(authorization[len(prefix):])
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id
