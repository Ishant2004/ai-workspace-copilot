"""CLI runner + regression gate for the evaluation harness (Phases 18-19).

Usage (from the backend/ directory):

    .venv/bin/python -m eval.run_eval            # full run, LLM-judge on
    .venv/bin/python -m eval.run_eval --no-judge # faster: skip the judge
    .venv/bin/python -m eval.run_eval --compare  # Phase 21: single vs multi-query

Requires DATABASE_URL and GEMINI_API_KEY (loaded from backend/.env). Prints a
per-question table and headline metrics, writes a JSON report to eval/reports/,
and — this is the Phase 19 part — **exits non-zero if any metric falls below its
threshold**, so a quality regression fails the run (and, in CI, the build).

Thresholds can be overridden with env vars: EVAL_MIN_RETRIEVAL, EVAL_MIN_ANSWER
(0-1 rates), EVAL_MIN_FAITHFULNESS, EVAL_MIN_RELEVANCE (1-5 scores).
"""

import os
import sys

from eval.harness import compare_retrieval, evaluate, save_report

# Baselines a healthy pipeline must clear. Set below the current 100%/5.0 so
# normal model variance doesn't fail the gate, but a real regression does.
_DEFAULTS = {
    "retrieval": 0.8,
    "answer": 0.8,
    "faithfulness": 4.0,
    "relevance": 4.0,
}


def _threshold(name: str, env: str) -> float:
    try:
        return float(os.environ[env])
    except (KeyError, ValueError):
        return _DEFAULTS[name]


def check_gate(report: dict, judge: bool) -> list[str]:
    """Return a list of threshold failures (empty means the gate passes).

    Pure function of the report + env thresholds, so it's testable without any
    API calls — the runner just acts on its result.
    """
    failures = []
    if report["retrieval_hit_rate"] < _threshold("retrieval", "EVAL_MIN_RETRIEVAL"):
        m = _threshold("retrieval", "EVAL_MIN_RETRIEVAL")
        failures.append(
            f"retrieval hit rate {report['retrieval_hit_rate']:.0%} < {m:.0%}"
        )
    if report["answer_accuracy"] < _threshold("answer", "EVAL_MIN_ANSWER"):
        m = _threshold("answer", "EVAL_MIN_ANSWER")
        failures.append(
            f"answer accuracy {report['answer_accuracy']:.0%} < {m:.0%}"
        )
    if judge:
        if report["avg_faithfulness"] < _threshold(
            "faithfulness", "EVAL_MIN_FAITHFULNESS"
        ):
            m = _threshold("faithfulness", "EVAL_MIN_FAITHFULNESS")
            failures.append(f"faithfulness {report['avg_faithfulness']} < {m}")
        if report["avg_relevance"] < _threshold("relevance", "EVAL_MIN_RELEVANCE"):
            m = _threshold("relevance", "EVAL_MIN_RELEVANCE")
            failures.append(f"relevance {report['avg_relevance']} < {m}")
    return failures


def _fmt_row(cols: list[str], widths: list[int]) -> str:
    return "  ".join(c.ljust(w) for c, w in zip(cols, widths))


def run_compare() -> None:
    """Phase 21: show retrieval hit@k for single-query vs multi-query.

    Uses k=1 (the most selective top-k) over a corpus that includes confusable
    same-topic distractors, so the effect of query rewriting is visible rather
    than hidden by an easy ceiling.
    """
    print("Comparing single-query hybrid vs multi-query retrieval (k=1)...\n")
    report = compare_retrieval(k=1)

    widths = [46, 8, 8]
    print(_fmt_row(["Question", "Single", "Multi"], widths))
    print(_fmt_row(["-" * w for w in widths], widths))
    for r in report["results"]:
        print(
            _fmt_row(
                [
                    r["question"][:45],
                    "hit" if r["single_hit"] else "MISS",
                    "hit" if r["multi_hit"] else "MISS",
                ],
                widths,
            )
        )

    print()
    print(f"Corpus docs (incl. distractors): {report['documents_seeded']}")
    print(f"Questions                      : {report['num_questions']}")
    print(f"k (top-k retrieved)            : {report['k']}")
    print(f"Single-query hit@k             : {report['single_hit_rate']:.0%}")
    print(f"Multi-query  hit@k             : {report['multi_hit_rate']:.0%}")
    print(f"Delta                          : {report['delta']:+.0%}")

    path = save_report(report)
    print(f"\nReport written to {path}")


def main() -> None:
    if "--compare" in sys.argv:
        run_compare()
        return

    judge = "--no-judge" not in sys.argv
    print(f"Running RAG evaluation (judge={'on' if judge else 'off'})...\n")
    report = evaluate(judge=judge)

    if judge:
        widths = [34, 6, 7, 6, 5, 9]
        header = ["Question", "Retr", "Answer", "Faith", "Rel", "Latency"]
    else:
        widths = [40, 8, 8, 10]
        header = ["Question", "Retr", "Answer", "Latency"]
    print(_fmt_row(header, widths))
    print(_fmt_row(["-" * w for w in widths], widths))
    for r in report["results"]:
        retr = "hit" if r["retrieval_hit"] else "MISS"
        ans = "ok" if r["answer_correct"] else "WRONG"
        if judge:
            cols = [
                r["question"][:33],
                retr,
                ans,
                str(r["faithfulness"]),
                str(r["relevance"]),
                f"{r['latency_ms']}ms",
            ]
        else:
            cols = [r["question"][:39], retr, ans, f"{r['latency_ms']}ms"]
        print(_fmt_row(cols, widths))

    print()
    print(f"Documents seeded : {report['documents_seeded']}")
    print(f"Questions        : {report['num_questions']}")
    print(f"Retrieval hit@{report['k']}  : {report['retrieval_hit_rate']:.0%}")
    print(f"Answer accuracy  : {report['answer_accuracy']:.0%}")
    if judge:
        print(f"Avg faithfulness : {report['avg_faithfulness']}/5")
        print(f"Avg relevance    : {report['avg_relevance']}/5")
    print(f"Avg latency      : {report['avg_latency_ms']}ms")

    path = save_report(report)
    print(f"\nReport written to {path}")

    # --- Regression gate (Phase 19) ---
    failures = check_gate(report, judge)
    if failures:
        print("\nGATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nGATE PASSED: all metrics meet thresholds.")


if __name__ == "__main__":
    main()
