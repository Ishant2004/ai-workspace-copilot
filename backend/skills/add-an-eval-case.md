---
name: add-an-eval-case
description: Add a question to the RAG golden set and re-run the evaluation gate.
when_to_use: When you want to measure a new retrieval/answer case or lock in a fix (e.g. from a thumbs-down).
---
# Steps
1. Open `backend/eval/golden.json`. If needed, add document(s) to `documents`
   (title + text), then add a question to `questions` with `expected_doc_title`
   and `expected_answer_contains` (substrings the answer must include).
2. For real failures, run `python -m eval.export_feedback <user_id>` to turn
   thumbs-down feedback into candidate questions to curate.
3. From `backend/`, run the eval + gate:
   `PYTHONPATH="$(pwd)" .venv/bin/python -m eval.run_eval`
   (`--no-judge` skips the LLM judge; `--compare` / `--compare-context` compare
   retrieval strategies).
4. Confirm the gate passes (retrieval hit rate, answer accuracy, faithfulness,
   relevance above thresholds). If it regresses, fix retrieval or prompts — don't
   lower the thresholds to pass.

# Context
- backend/eval/golden.json — the golden corpus + questions.
- backend/eval/run_eval.py — CLI + regression gate (thresholds; `EVAL_MIN_*` env
  overrides).
- backend/eval/harness.py — how retrieval and answers are scored.
- backend/eval/export_feedback.py — thumbs-down feedback → golden candidates.
