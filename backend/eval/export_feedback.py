"""Turn thumbs-down feedback into golden-set candidates (Phase 23).

Closes the flywheel: production answers users marked 👎 are exactly the cases the
system got wrong, and therefore the most valuable questions to add to the eval
set. This dumps them in a shape close to golden.json so a human can fill in the
`expected_doc_title` / `expected_answer_contains` and drop them in.

We can't auto-label the *correct* answer (that's the human judgment the whole
eval depends on), so this produces **candidates**, not finished golden entries.

Usage (from backend/):
    .venv/bin/python -m eval.export_feedback <user_id> [out.json]
"""

import json
import sys
from pathlib import Path

from services import feedback


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m eval.export_feedback <user_id> [out.json]")
        sys.exit(2)

    user_id = int(sys.argv[1])
    negatives = feedback.list_negative(user_id)

    candidates = [
        {
            "q": item["question"],
            "expected_doc_title": "",  # TODO: fill in the right document
            "expected_answer_contains": [],  # TODO: fill in the expected fact(s)
            "_downvoted_answer": item["answer"],
            "_note": item["note"],
        }
        for item in negatives
    ]
    payload = {"questions": candidates}
    text = json.dumps(payload, indent=2)

    if len(sys.argv) >= 3:
        Path(sys.argv[2]).write_text(text)
        print(f"Wrote {len(candidates)} candidate(s) to {sys.argv[2]}")
    else:
        print(text)
        print(f"\n{len(candidates)} thumbs-down candidate(s) for user {user_id}.")


if __name__ == "__main__":
    main()
