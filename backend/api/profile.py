"""User profile endpoints (Phase 13).

  GET    /profile   — the durable facts the assistant remembers about the user
  DELETE /profile   — forget everything (clear the profile)
"""

from fastapi import APIRouter, Depends

from api.deps import current_user_id
from services import profile

router = APIRouter()


@router.get("/profile")
def get_profile(user_id: int = Depends(current_user_id)) -> dict:
    return {"facts": profile.get_facts(user_id)}


@router.delete("/profile")
def clear_profile(user_id: int = Depends(current_user_id)) -> dict:
    profile.clear_facts(user_id)
    return {"facts": []}
