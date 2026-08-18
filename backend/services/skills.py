"""Skills: reusable playbooks for the agent (Phase 35).

A "skill" is a Markdown file that packages *how* to do a recurring task — the
ordered steps plus pointers to the files and conventions that matter — so the
agent starts a task already informed instead of rediscovering the codebase every
time. Each file has a small frontmatter header:

    ---
    name: add-a-tool
    description: Add a new agent tool end to end.
    when_to_use: When the user wants to give the agent a new capability.
    ---
    # Steps
    1. ...
    # Context
    - backend/services/tools.py — the tool registry

The agent calls `use_skill(name)` to load a skill's body into its working context.
We parse the frontmatter by hand (simple `key: value` lines) to avoid a YAML
dependency.
"""

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _parse(text: str) -> tuple[dict, str]:
    """Split a skill file into (frontmatter dict, markdown body)."""
    meta: dict[str, str] = {}
    body = text.strip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()
            body = text[end + 4 :].strip()
    return meta, body


def _skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("*.md")) if SKILLS_DIR.is_dir() else []


def list_skills() -> list[dict]:
    """Name/description/when_to_use for every available skill."""
    out = []
    for path in _skill_files():
        meta, _ = _parse(path.read_text())
        out.append(
            {
                "name": meta.get("name", path.stem),
                "description": meta.get("description", ""),
                "when_to_use": meta.get("when_to_use", ""),
            }
        )
    return out


def get_skill(name: str) -> dict | None:
    for path in _skill_files():
        meta, body = _parse(path.read_text())
        if meta.get("name", path.stem) == name or path.stem == name:
            return {
                "name": meta.get("name", path.stem),
                "description": meta.get("description", ""),
                "when_to_use": meta.get("when_to_use", ""),
                "body": body,
            }
    return None


def use_skill(name: str) -> str:
    """Tool: load a skill's steps + context for the agent to follow."""
    skill = get_skill(name)
    if skill is None:
        available = ", ".join(s["name"] for s in list_skills()) or "(none)"
        return f"Skill '{name}' not found. Available: {available}"
    return f"# Skill: {skill['name']}\n{skill['description']}\n\n{skill['body']}"


def catalog() -> str:
    """A short catalogue to inject into the agent prompt so it knows what exists."""
    items = list_skills()
    if not items:
        return ""
    lines = "\n".join(
        f"- {s['name']}: {s['when_to_use'] or s['description']}" for s in items
    )
    return (
        "\n\nAvailable skills — call use_skill(name) to load a step-by-step "
        "playbook before starting a matching task:\n" + lines + "\n"
    )
