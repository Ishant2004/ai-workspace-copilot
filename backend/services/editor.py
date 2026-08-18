"""Code editing: propose → review → apply (Phase 33).

Letting an agent write files is the riskiest capability in the app, so edits are
never silent. The editing tools *propose* a change: they compute the resulting
content and a **unified diff**, and stage it — nothing touches disk. The user
then reviews the pending diffs and explicitly **applies** (or discards) them.

Every path goes through `workspace.resolve()` (Phase 32) at propose *and* apply
time, so edits are confined to the selected workspace; content is size-capped;
and each applied write is written to the audit log.
"""

import difflib
import os
import threading

from config import settings
from services import audit, workspace

# user_id -> {rel_path: {path, content, diff, is_new}}  (in-memory proposal buffer)
_pending: dict[int, dict[str, dict]] = {}
_lock = threading.Lock()


def _unified_diff(old: str, new: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _check_size(content: str) -> None:
    if len(content.encode("utf-8")) > settings.workspace_max_file_bytes:
        raise workspace.WorkspaceError(
            f"Content too large (> {settings.workspace_max_file_bytes} bytes)."
        )


def _current_text(target: str) -> str | None:
    if os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as fh:
            return fh.read()
    return None


def _stage(user_id: int, path: str, content: str, diff: str, is_new: bool) -> None:
    with _lock:
        _pending.setdefault(user_id, {})[path] = {
            "path": path,
            "content": content,
            "diff": diff,
            "is_new": is_new,
        }


def propose_write(user_id: int, path: str, content: str) -> str:
    """Stage a create/overwrite of `path` with `content`; return its diff."""
    target = workspace.resolve(user_id, path)  # raises on escape / no workspace
    if os.path.isdir(target):
        raise workspace.WorkspaceError("Path is a directory, not a file.")
    _check_size(content)
    old = _current_text(target)
    is_new = old is None
    if not is_new and old == content:
        return f"No changes: {path} already has this content."
    diff = _unified_diff(old or "", content, path)
    _stage(user_id, path, content, diff, is_new)
    header = "Proposed new file" if is_new else "Proposed changes to"
    return f"{header} {path}:\n{diff}\nReview and apply, or discard."


def propose_edit(user_id: int, path: str, old_text: str, new_text: str) -> str:
    """Stage an exact-match replacement of `old_text` with `new_text` in `path`."""
    target = workspace.resolve(user_id, path)
    current = _current_text(target)
    if current is None:
        return f"File not found: {path}"
    occurrences = current.count(old_text)
    if occurrences == 0:
        return f"Text to replace was not found in {path}."
    if occurrences > 1:
        return (
            f"Text appears {occurrences} times in {path}; include more surrounding "
            "context so it matches exactly once."
        )
    updated = current.replace(old_text, new_text, 1)
    _check_size(updated)
    diff = _unified_diff(current, updated, path)
    _stage(user_id, path, updated, diff, False)
    return f"Proposed changes to {path}:\n{diff}\nReview and apply, or discard."


def list_pending(user_id: int) -> list[dict]:
    with _lock:
        return [
            {"path": e["path"], "diff": e["diff"], "is_new": e["is_new"]}
            for e in _pending.get(user_id, {}).values()
        ]


def discard_pending(user_id: int) -> int:
    with _lock:
        count = len(_pending.get(user_id, {}))
        _pending.pop(user_id, None)
    return count


def apply_pending(user_id: int) -> list[dict]:
    """Write all staged edits to disk (re-confined), audit each, and clear them."""
    with _lock:
        edits = list(_pending.get(user_id, {}).values())
        _pending.pop(user_id, None)
    results = []
    for e in edits:
        # Re-resolve at apply time — never trust a staged path blindly.
        target = workspace.resolve(user_id, e["path"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(e["content"])
        audit.log(
            "code.edit_applied", user_id, {"path": e["path"], "new_file": e["is_new"]}
        )
        results.append({"path": e["path"], "applied": True, "new_file": e["is_new"]})
    return results
