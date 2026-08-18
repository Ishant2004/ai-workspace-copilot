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
from services import audit, editor, workspace

router = APIRouter()


@router.get("/workspace")
def get_workspace(user_id: int = Depends(current_user_id)) -> dict:
    return {"root": workspace.get_root(user_id)}


@router.get("/workspace/browse")
def browse_workspace(
    path: str = "", user_id: int = Depends(current_user_id)
) -> dict:
    """List subfolders so the UI can offer a click-through folder picker."""
    return workspace.browse(path or None)


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


# --- Pending code edits: review → apply / discard (Phase 33) ----------------


@router.get("/workspace/edits")
def get_edits(user_id: int = Depends(current_user_id)) -> list[dict]:
    """Proposed edits staged by the coding tools (diffs), awaiting approval."""
    return editor.list_pending(user_id)


@router.post("/workspace/edits/apply")
def apply_edits(user_id: int = Depends(current_user_id)) -> dict:
    """Write all staged edits to disk (confined + audited)."""
    applied = editor.apply_pending(user_id)
    return {"applied": applied, "count": len(applied)}


@router.post("/workspace/edits/discard")
def discard_edits(user_id: int = Depends(current_user_id)) -> dict:
    """Throw away all staged edits without writing anything."""
    return {"discarded": editor.discard_pending(user_id)}
