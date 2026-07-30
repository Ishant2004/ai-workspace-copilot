"""User profile endpoints (Phase 13).

  GET    /profile   — the durable facts the assistant remembers about the user
  DELETE /profile   — forget everything (clear the profile)
"""

from fastapi import APIRouter

from services import profile

router = APIRouter()


@router.get("/profile")
def get_profile() -> dict:
    return {"facts": profile.get_facts()}


@router.delete("/profile")
def clear_profile() -> dict:
    profile.clear_facts()
    return {"facts": []}
