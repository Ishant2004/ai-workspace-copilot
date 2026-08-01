"""CLI runner for the evaluation harness (Phase 18).

Usage (from the backend/ directory):

    .venv/bin/python -m eval.run_eval

Requires DATABASE_URL and GEMINI_API_KEY (loaded from backend/.env). Prints a
per-question table and headline metrics, and writes a JSON report to
eval/reports/ so you can compare runs over time.
"""

from eval.harness import evaluate, save_report


def _fmt_row(cols: list[str], widths: list[int]) -> str:
    return "  ".join(c.ljust(w) for c, w in zip(cols, widths))


def main() -> None:
    print("Running RAG evaluation...\n")
    report = evaluate()

    widths = [40, 8, 8, 10]
    print(_fmt_row(["Question", "Retr", "Answer", "Latency"], widths))
    print(_fmt_row(["-" * 40, "-" * 8, "-" * 8, "-" * 10], widths))
    for r in report["results"]:
        q = r["question"][:39]
        retr = "hit" if r["retrieval_hit"] else "MISS"
        ans = "ok" if r["answer_correct"] else "WRONG"
        lat = f"{r['latency_ms']}ms"
        print(_fmt_row([q, retr, ans, lat], widths))

    print()
    print(f"Documents seeded : {report['documents_seeded']}")
    print(f"Questions        : {report['num_questions']}")
    print(f"Retrieval hit@{report['k']}  : {report['retrieval_hit_rate']:.0%}")
    print(f"Answer accuracy  : {report['answer_accuracy']:.0%}")
    print(f"Avg latency      : {report['avg_latency_ms']}ms")

    path = save_report(report)
    print(f"\nReport written to {path}")


if __name__ == "__main__":
    main()
