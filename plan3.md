# AI Workspace Copilot — Part 3: Agentic Coding, Skills & Per-Chat Knowledge

Part 1 (Phases 0–17) built the assistant; Part 2 (Phases 18–29) made it
measurable, faster, and safe. **Part 3 turns it into a workspace copilot that can
act on a codebase** — three capabilities:

1. **Code editing (Cursor-style).** The agent can read, search, and modify code
   in a configured workspace, working from real files instead of guesses.
2. **Skills.** Reusable, versioned playbooks (add a feature, add a tool, add an
   MCP server…) that give the agent the *steps and context* for a task up front,
   so it doesn't rebuild understanding from scratch every time.
3. **Chat-level RAG.** Attach a file inside a conversation; its context is scoped
   to *that chat only* and disappears when the chat is deleted.

Same rules as before: **one feature at a time → test → then it's pushed to
GitHub**, first-principles functional code, docs updated each phase, all on the
**$0 free tier**.

---

## ⚠️ Safety first (code editing)

Letting an LLM read and write files is powerful and genuinely risky. Every
code-editing phase is built around these non-negotiables, introduced *before* any
write capability:

- **Workspace confinement.** All file operations are restricted to a single
  configured `WORKSPACE_ROOT`. Paths are resolved to their real location and
  rejected if they escape the root (no `..`, no absolute paths outside, no
  symlink escape).
- **Read before write.** Read-only tools (Phase 32) ship and are exercised before
  any editing tool (Phase 33) exists.
- **Reviewable, reversible edits.** Every edit returns a **diff**; edits go
  through a preview/approval path rather than silently overwriting. The tool
  never deletes outside the workspace and never touches VCS history.
- **No arbitrary shell.** There is no "run anything" tool. A command runner, if
  added, is an explicit allowlist (e.g. the test command) and opt-in.
- **Per-user, size-bounded, rate-limited** like every other endpoint (Phase 29).

---

## Guiding themes

| Theme | Why it matters |
| ----- | -------------- |
| **Ground actions in real files** | A coding agent must read the actual code, not hallucinate it. |
| **Capability behind guardrails** | Read-only first; edits are confined, diffed, and approved. |
| **Don't rebuild context** | Skills package the steps + file pointers so the agent starts informed. |
| **Scope knowledge correctly** | A chat attachment belongs to that chat, not the whole account. |

---

## Roadmap at a glance

| Phase | Feature | Track |
| ----- | ------- | ----- |
| 30 | Chat-scoped document attachments (backend) | Per-chat RAG |
| 31 | Attach-a-file UI + auto-RAG in chat | Per-chat RAG |
| 32 | Workspace + read-only code tools (list / read / search) | Code editing |
| 33 | Code-editing tools (create / edit) with diffs + confinement | Code editing |
| 34 | Coding agent ("code" mode: read → plan → edit → diff) | Code editing |
| 35 | Skills framework (format, registry, loader, `use_skill`) | Skills |
| 36 | Skill library (add-feature, add-tool, add-mcp-server, …) | Skills |

Order rationale: chat-RAG first (self-contained warm-up extending existing RAG),
then the code-editing stack read-only → edit → agent (safety-first), then skills
(most valuable once there's an agent doing multi-step work).

---

# PHASE 30: Chat-Scoped Document Attachments (backend)

## Goal
Let a file be attached to *one conversation* and used as RAG context there only —
never visible in other chats or the global knowledge base.

## Implementation
- Add a nullable `thread_id` to `documents` (global KB rows keep it NULL;
  attachments carry the thread id). Index `(user_id, thread_id)`.
- `POST /threads/{id}/attach` — upload a file (reuse Phase 26 `extract` +
  `ingest`) but stamp `thread_id`; `GET /threads/{id}/attachments` to list;
  `DELETE` an attachment.
- Retrieval scoping: a thread's RAG search returns the user's global docs **plus**
  that thread's attachments; other threads never see them.
- Cleanup: deleting a thread deletes its attachments (cascade / explicit).

## Concepts learned
Scoped retrieval, row-level knowledge boundaries, ingestion reuse.

---

# PHASE 31: Attach-a-File UI + Auto-RAG in Chat

## Goal
Make attachments usable from the chat, and let the assistant automatically ground
on them.

## Implementation
- A 📎 attach control in the composer → `POST /threads/{id}/attach`; show the
  chat's attachments as chips with a remove ✕.
- When a chat has attachments, retrieval includes them (works in `chat` mode via
  the existing tool-aware path, and in `rag` mode).
- Trace (Phase 20) shows an attachment-retrieval span so it's observable.

## Concepts learned
Contextual UI affordances, blending global + per-chat knowledge.

---

# PHASE 32: Workspace + Read-Only Code Tools

## Goal
Give the agent a safe window onto a real codebase — read and search only.

## Implementation
- `WORKSPACE_ROOT` config; a `services/workspace.py` that resolves and
  **confines** every path to that root (reject escapes) — the security spine for
  all later file work.
- Agent tools (tool registry + MCP): `list_dir(path)`, `read_file(path)`,
  `search_code(query)` (ripgrep-style, but pure-Python walk + match to stay
  dependency-free), each returning bounded output.
- No write capability yet — this phase is deliberately read-only and tested for
  confinement (path-escape attempts must fail).

## Concepts learned
Path confinement / sandboxing, safe file exposure, tool-shaped file access.

---

# PHASE 33: Code-Editing Tools (create / edit) with Diffs

## Goal
Let the agent modify files — safely, visibly, reversibly.

## Implementation
- `write_file(path, content)` and `edit_file(path, old, new)` (exact-match
  replace), both confined to `WORKSPACE_ROOT`, size-capped, and returning a
  **unified diff** of what changed.
- A preview/apply flow: edits are returned as proposed diffs the user confirms
  (no silent overwrite); an audit-log entry per applied edit (Phase 29).
- Never creates/deletes outside the workspace; refuses binary/oversized files.

## Concepts learned
Diff generation, apply-with-approval, guarded mutation of the filesystem.

---

# PHASE 34: Coding Agent ("code" mode)

## Goal
An agent that completes a small coding task end to end: understand, change, and
report — like a focused Cursor edit.

## Implementation
- A new `code` chat mode that runs the ReAct loop with the file tools (read /
  search / edit), a coding-focused system prompt, and a step cap.
- It reads relevant files, proposes edits as diffs, and summarises what it
  changed; optional guarded test run (allowlisted command) to self-check.
- Surfaces each file read/edit as tool events + trace spans.

## Concepts learned
Tool-using coding loops, plan-read-edit-verify, grounded code changes.

---

# PHASE 35: Skills Framework

## Goal
Package repeatable know-how so the agent starts a task already informed, instead
of rebuilding context every time.

## Implementation
- A `skills/` directory of skill files (Markdown + small frontmatter: `name`,
  `description`, `when_to_use`, ordered `steps`, and `context` pointers — files to
  read, conventions to follow).
- `services/skills.py`: discover skills, and a `use_skill(name)` tool that loads a
  skill's steps/context into the agent's working prompt. `GET /skills` lists them.
- The agent (or user) selects a skill; its steps guide the coding agent (Phase 34)
  and its `context` pointers tell it which files to read first.

## Concepts learned
Skills/playbooks as reusable context, progressive disclosure, agent scaffolding.

---

# PHASE 36: Skill Library

## Goal
Author the initial, project-specific skills that encode how *this* repo is built.

## Implementation
Write skills that follow `process.md` and the existing architecture, e.g.:
- **add-a-feature** — branch of thinking: plan → build one feature → test → update
  docs → (user pushes). Points at `plan*.md`, `process.md`, `docs/`.
- **add-a-tool** — how to add an agent tool (declaration + `_FUNCTIONS` + MCP +
  prompt + test), pointing at `services/tools.py`.
- **add-an-mcp-server-tool** — extend `mcp_server.py`.
- **add-an-eval-case** — extend the golden set + run the gate.
- **add-a-phase** — how a phase is structured and documented here.

## Concepts learned
Encoding institutional knowledge as skills; making the copilot self-aware of its
own conventions.

---

## Summary of Part 3 milestones

- ✅ Chat-scoped attachments (backend) + retrieval isolation
- ✅ Attach-a-file chat UI + auto-RAG on attachments
- ✅ Workspace confinement + read-only code tools
- ✅ Code-editing tools with diffs + approval
- ✅ Coding agent (`code` mode)
- ⬜ Skills framework (`use_skill`, registry)
- ⬜ Project skill library
