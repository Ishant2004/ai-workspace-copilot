"""Auth endpoints (per-user segregation; hardened in Phase 29).

  POST /auth/signup  — create an account, returns a JWT
  POST /auth/login   — verify credentials, returns a JWT
  POST /auth/refresh — exchange a valid token for a fresh one (sliding session)
  GET  /auth/me      — return the current user (validates the token)

Phase 29: login/signup are rate-limited per client IP (brute-force / abuse
defence) and every attempt is written to the audit log.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import current_user_id
from config import settings
from models import AuthRequest, AuthResponse
from services import audit, auth, ratelimit

router = APIRouter()


def _rate_limit_ip(request: Request, event: str) -> str:
    """Enforce the per-IP auth rate limit; return the client IP for auditing."""
    ip = request.client.host if request.client else "unknown"
    if not ratelimit.allow(
        f"auth:{event}:{ip}",
        settings.auth_rate_limit_max,
        settings.rate_limit_window_seconds,
    ):
        raise HTTPException(
            status_code=429, detail="Too many attempts — please wait and retry."
        )
    return ip


@router.post("/auth/signup", response_model=AuthResponse)
def signup(body: AuthRequest, request: Request) -> AuthResponse:
    ip = _rate_limit_ip(request, "signup")
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
    audit.log("auth.signup", user["id"], {"email": email}, ip)
    return AuthResponse(token=auth.create_token(user["id"]), email=user["email"])


@router.post("/auth/login", response_model=AuthResponse)
def login(body: AuthRequest, request: Request) -> AuthResponse:
    ip = _rate_limit_ip(request, "login")
    user = auth.authenticate(body.email, body.password)
    if user is None:
        audit.log("auth.login_failed", None, {"email": body.email.strip().lower()}, ip)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    audit.log("auth.login", user["id"], {}, ip)
    return AuthResponse(token=auth.create_token(user["id"]), email=user["email"])


@router.post("/auth/refresh", response_model=AuthResponse)
def refresh(user_id: int = Depends(current_user_id)) -> AuthResponse:
    """Issue a fresh token for a still-valid one (sliding session).

    Keeps active users signed in without a 30-day static token. A production
    system would use a separate, revocable refresh token; this is the honest
    lightweight version for a $0 single-service app.
    """
    email = auth.email_for(user_id) or ""
    return AuthResponse(token=auth.create_token(user_id), email=email)


@router.get("/auth/me")
def me(user_id: int = Depends(current_user_id)) -> dict:
    return {"user_id": user_id}


@router.get("/audit")
def audit_log(user_id: int = Depends(current_user_id)) -> list[dict]:
    """This user's recent security-relevant events (Phase 29)."""
    return audit.list_recent(user_id)
