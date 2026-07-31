"""Auth endpoints (per-user segregation).

  POST /auth/signup — create an account, returns a JWT
  POST /auth/login  — verify credentials, returns a JWT
  GET  /auth/me     — return the current user (validates the token)
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user_id
from models import AuthRequest, AuthResponse
from services import auth

router = APIRouter()


@router.post("/auth/signup", response_model=AuthResponse)
def signup(body: AuthRequest) -> AuthResponse:
    email = body.email.strip().lower()
    if "@" not in email or len(body.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid email and a password of at least 6 characters.",
        )
    try:
        user = auth.create_user(email, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return AuthResponse(token=auth.create_token(user["id"]), email=user["email"])


@router.post("/auth/login", response_model=AuthResponse)
def login(body: AuthRequest) -> AuthResponse:
    user = auth.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return AuthResponse(token=auth.create_token(user["id"]), email=user["email"])


@router.get("/auth/me")
def me(user_id: int = Depends(current_user_id)) -> dict:
    return {"user_id": user_id}
