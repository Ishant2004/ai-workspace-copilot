---
name: add-a-feature
description: Build one new feature the way this project does (plan → build → test → docs).
when_to_use: When the user asks to add a new capability or feature to the app.
---
# Steps
1. Read `process.md` first — the rules: build ONE feature at a time, write basic
   first-principles functional code, then TEST it. The user pushes to GitHub
   themselves; never push.
2. Check `plan.md` / `plan2.md` / `plan3.md` — if the feature is a planned phase,
   follow that phase's intent.
3. Build the backend: logic in `backend/services/`, endpoints in `backend/api/`,
   schemas in `backend/models.py`, settings in `backend/config.py`. Wire routers
   and any table init in `backend/main.py`.
4. Build the frontend if user-facing: API calls in
   `frontend/src/services/api.ts`, UI in `frontend/src/components/`.
5. Test end to end: backend import check (`python -c "import main"`), a scratch
   E2E via FastAPI `TestClient`, and `npm run build` for the frontend. Clean up
   any test data you create.
6. Update docs: the `README.md` status table, a phase section in
   `docs/architecture.md`, and `docs/backend.md` / `docs/frontend.md` as relevant.
7. Stop and let the user push.

# Context
- process.md — how this repo is built (one feature → test → user pushes).
- plan.md / plan2.md / plan3.md — the phased roadmaps.
- backend/main.py — where routers and startup table-init live.
- docs/ — architecture.md (mental model), backend.md, frontend.md.
