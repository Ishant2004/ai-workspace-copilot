"""Skills endpoints (Phase 35).

  GET /skills        — list available skills (name, description, when_to_use)
  GET /skills/{name} — the full skill (with its steps + context body)

Skills are Markdown files in backend/skills/ (see services/skills.py); the agent
loads one via the `use_skill` tool.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user_id
from services import skills

router = APIRouter()


@router.get("/skills")
def list_skills(user_id: int = Depends(current_user_id)) -> list[dict]:
    return skills.list_skills()


@router.get("/skills/{name}")
def get_skill(name: str, user_id: int = Depends(current_user_id)) -> dict:
    skill = skills.get_skill(name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill
