"""Feedback endpoints (Phase 23).

  POST /feedback         — rate an answer 👍/👎 (with an optional note)
  GET  /feedback/stats   — this user's up/down counts + satisfaction rate
  GET  /feedback/export  — this user's thumbs-down cases (golden-set candidates)

Everything is scoped to the authenticated user.
"""

from fastapi import APIRouter, Depends

from api.deps import current_user_id
from models import FeedbackRequest
from services import feedback

router = APIRouter()


@router.post("/feedback")
def submit_feedback(
    body: FeedbackRequest, user_id: int = Depends(current_user_id)
) -> dict:
    feedback.add_feedback(
        user_id,
        body.thread_id,
        body.question,
        body.answer,
        body.rating,
        body.note,
    )
    return {"ok": True}


@router.get("/feedback/stats")
def feedback_stats(user_id: int = Depends(current_user_id)) -> dict:
    return feedback.stats(user_id)


@router.get("/feedback/export")
def feedback_export(user_id: int = Depends(current_user_id)) -> list[dict]:
    """Thumbs-down cases — candidates to curate into the golden eval set."""
    return feedback.list_negative(user_id)
