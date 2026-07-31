"""Authentication (per-user segregation).

Email + password auth from first principles:
  - passwords are hashed with bcrypt (never stored in plain text),
  - a signed JWT carries the user's id after login,
  - each request presents the JWT; we decode it to know who's calling.

This is the identity half of multi-tenancy; the data half is `user_id` columns
on every table, filtered on every query (see services/db.py, threads.py, etc.).
"""

import datetime as dt

import bcrypt
import jwt

from config import settings
from services.db import get_conn


def init_auth() -> None:
    """Create the users table if it doesn't exist."""
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            BIGSERIAL PRIMARY KEY,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


# --- Passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# --- Users -----------------------------------------------------------------


def create_user(email: str, password: str) -> dict:
    """Create a user; raises ValueError if the email is already taken."""
    email = email.strip().lower()
    with get_conn(register=False) as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email = %s;", (email,)
        ).fetchone()
        if exists:
            raise ValueError("An account with that email already exists.")
        row = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) "
            "RETURNING id, email;",
            (email, hash_password(password)),
        ).fetchone()
    return {"id": row[0], "email": row[1]}


def authenticate(email: str, password: str) -> dict | None:
    """Return the user if email+password are valid, else None."""
    email = email.strip().lower()
    with get_conn(register=False) as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s;",
            (email,),
        ).fetchone()
    if row and verify_password(password, row[2]):
        return {"id": row[0], "email": row[1]}
    return None


# --- Tokens ----------------------------------------------------------------


def create_token(user_id: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int | None:
    """Return the user_id from a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
