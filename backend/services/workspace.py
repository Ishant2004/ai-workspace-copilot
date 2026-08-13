"""Code workspace: per-user root + path confinement (Phase 32).

This is the security spine for all code tools. The user selects a workspace
directory (POST /workspace); every file operation resolves paths **inside** that
root and rejects anything that escapes it (`..`, absolute paths, symlink escape).
Read-only tools (this phase) and, later, editing tools (Phase 33) all go through
`resolve()`, so confinement is enforced in exactly one place.

The root is stored per user in a tiny table. An optional `WORKSPACE_ALLOWED_BASE`
fences *which* directories may be chosen; `WORKSPACE_ROOT` is an optional default.
"""

import os

from config import settings
from services.db import get_conn


class WorkspaceError(Exception):
    """Raised for an unset workspace or a path that escapes it."""


def init_workspace() -> None:
    with get_conn(register=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace (
                user_id BIGINT PRIMARY KEY,
                root    TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


def get_root(user_id: int) -> str | None:
    """The user's selected workspace root, or the env default, or None."""
    with get_conn(register=False) as conn:
        row = conn.execute(
            "SELECT root FROM workspace WHERE user_id = %s;", (user_id,)
        ).fetchone()
    if row:
        return row[0]
    return settings.workspace_root or None


def set_root(user_id: int, path: str) -> str:
    """Validate and store the user's workspace root. Returns the resolved path."""
    if not path or not path.strip():
        raise WorkspaceError("A directory path is required.")
    root = os.path.realpath(os.path.expanduser(path.strip()))
    if not os.path.isdir(root):
        raise WorkspaceError(f"Not a directory: {root}")
    # Optional fence: the chosen root must live inside the allowed base.
    base = settings.workspace_allowed_base
    if base:
        base = os.path.realpath(os.path.expanduser(base))
        if root != base and not root.startswith(base + os.sep):
            raise WorkspaceError(f"Workspace must be inside {base}")
    with get_conn(register=False) as conn:
        conn.execute(
            "INSERT INTO workspace (user_id, root) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET root = EXCLUDED.root;",
            (user_id, root),
        )
    return root


def resolve(user_id: int, rel_path: str) -> str:
    """Resolve `rel_path` against the user's root, confined to it.

    Raises WorkspaceError if no workspace is set or the path escapes the root.
    This is the single chokepoint every file operation must pass through.
    """
    root = get_root(user_id)
    if not root:
        raise WorkspaceError("No workspace selected. Set one with POST /workspace.")
    root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, rel_path or "."))
    # realpath collapses .. and follows symlinks, so a prefix check is enough to
    # guarantee the target stays inside the root.
    if target != root and not target.startswith(root + os.sep):
        raise WorkspaceError("Path escapes the workspace root.")
    return target


# Directories never worth walking/reading for a code workspace.
IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}
