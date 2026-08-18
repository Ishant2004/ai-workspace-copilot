---
name: add-a-phase
description: Structure and document a new roadmap phase the way this project does.
when_to_use: When starting a new numbered phase of work.
---
# Steps
1. Add the phase to the relevant plan file (`plan.md` / `plan2.md` / `plan3.md`):
   a Goal, an Implementation outline, and Concepts learned; add it to that file's
   roadmap table and milestones list.
2. Add a row to the `README.md` status table (⬜ Planned → ✅ Done).
3. Build the feature — follow the add-a-feature skill (one feature, tested).
4. Document it: a narrative "Phase N" section in `docs/architecture.md` (explain
   the *why*), plus details in `docs/backend.md` / `docs/frontend.md` as relevant.
5. Flip the phase to ✅ in the plan file and README once it's built and tested.

# Context
- plan.md / plan2.md / plan3.md — phase format (Goal / Implementation / Concepts
  learned) and the milestones lists.
- README.md — the phase status tables.
- docs/architecture.md — one narrative section per phase (mental model, not a
  changelog).
- Convention: match the existing tone — explain the reasoning, note what was
  verified, and be honest about limitations.
