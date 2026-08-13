"""Code workspace endpoints (Phase 32).

  GET  /workspace — the directory the code tools currently operate on (or null)
  POST /workspace — select that directory (the user chooses their own root)

The chosen root is validated (must be an existing directory, and inside
WORKSPACE_ALLOWED_BASE if that fence is configured). All code-tool file access is
confined to it (services/workspace.py).
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user_id
from models import WorkspaceRequest
from services import audit, workspace

router = APIRouter()


@router.get("/workspace")
def get_workspace(user_id: int = Depends(current_user_id)) -> dict:
    return {"root": workspace.get_root(user_id)}


@router.post("/workspace")
def set_workspace(
    body: WorkspaceRequest, user_id: int = Depends(current_user_id)
) -> dict:
    try:
        root = workspace.set_root(user_id, body.path)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.log("workspace.set", user_id, {"root": root})
    return {"root": root}
