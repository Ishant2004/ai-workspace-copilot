"""User profile endpoints (Phase 13; management in Phase 25).

  GET    /profile           — the durable facts the assistant remembers (with ids)
  DELETE /profile           — forget everything (clear the profile)
  DELETE /profile/{fact_id} — forget one specific fact
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user_id
from services import profile

router = APIRouter()


@router.get("/profile")
def get_profile(user_id: int = Depends(current_user_id)) -> dict:
    # Facts now come with ids so the UI can delete them individually (Phase 25).
    return {"facts": profile.get_facts_with_ids(user_id)}


@router.delete("/profile")
def clear_profile(user_id: int = Depends(current_user_id)) -> dict:
    profile.clear_facts(user_id)
    return {"facts": []}


@router.delete("/profile/{fact_id}")
def delete_fact(fact_id: int, user_id: int = Depends(current_user_id)) -> dict:
    if not profile.delete_fact(user_id, fact_id):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"deleted": True, "id": fact_id}
