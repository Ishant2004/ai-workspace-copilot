"""Evaluation harness (Phase 18).

You cannot improve what you cannot measure. This harness scores the RAG pipeline
objectively so every later change (query rewriting, contextual retrieval, …) can
be judged better-or-worse against a fixed baseline instead of a gut feeling.

How it works:
  1. Seed a small, known corpus of documents under a dedicated *eval user*
     (so it never touches real user data).
  2. For each golden question, measure two things:
       - retrieval:  did the document that *should* answer it appear in top-k?
       - answer:     does the generated answer contain the expected fact(s)?
     …plus the latency of producing the answer.
  3. Aggregate into hit-rate / accuracy / avg-latency and return a report.

The golden set lives in golden.json: a corpus + questions, each tagged with the
document it should retrieve and substrings the answer must contain.
"""

import json
import time
from pathlib import Path

from eval.judge import judge_answer
from models import Message
from prompts import build_rag_system_prompt, format_context_block
from services import db
from services.gemini import embed_texts, stream_chat
from services.search import run_search

# A sentinel owner id for eval data. Real users come from a BIGSERIAL starting at
# 1 (positive), so a negative id can never collide with a real account.
EVAL_USER_ID = -1

_GOLDEN_PATH = Path(__file__).resolve().parent / "golden.json"


def load_golden() -> dict:
    """Load the golden corpus + questions from disk."""
    return json.loads(_GOLDEN_PATH.read_text())


def seed_corpus(documents: list[dict]) -> int:
    """Replace the eval user's corpus with the golden documents.

    We wipe first so repeated runs are deterministic (no duplicate docs piling
    up across runs). Then we embed every document and insert them in one batch.
    """
    with db.get_conn() as conn:
        conn.execute("DELETE FROM documents WHERE user_id = %s;", (EVAL_USER_ID,))

    texts = [d["text"] for d in documents]
    vectors = embed_texts(texts)
    rows = [
        (d["title"], d["text"], vec, {"source": "eval"})
        for d, vec in zip(documents, vectors)
    ]
    return db.insert_documents(EVAL_USER_ID, rows)


def _rag_answer(question: str, k: int) -> tuple[str, list[dict], str]:
    """Run the real RAG path for one question: retrieve, ground, generate.

    Mirrors the `rag` mode in the chat endpoint (hybrid retrieval + the RAG
    system prompt) so we're measuring the pipeline users actually get. Returns
    the answer, the retrieved hits, and the joined context (for the judge).
    """
    hits = run_search(EVAL_USER_ID, question, k, "hybrid")
    blocks = [format_context_block(h["id"], h["title"], h["text"]) for h in hits]
    context = "\n\n".join(blocks)
    system_prompt = build_rag_system_prompt(blocks)
    messages = [Message(role="user", content=question)]

    # The free tier caps at ~15 requests/min; a judged run makes 2 calls per
    # question, so long backoffs let a 429 cooldown (~27s) pass rather than
    # failing the run for a reason unrelated to quality.
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            answer = "".join(stream_chat(messages, system_prompt))
            return answer, hits, context
        except Exception as exc:  # noqa: BLE001 - eval should be robust
            last_exc = exc
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"generation failed after retries: {last_exc}")


def _answer_ok(answer: str, expected: list[str]) -> bool:
    """An answer passes if it contains every expected substring (case-insensitive)."""
    low = answer.lower()
    return all(sub.lower() in low for sub in expected)


def evaluate(k: int = 4, judge: bool = True) -> dict:
    """Seed the corpus, run every golden question, and return a scored report.

    When `judge` is on (Phase 19), each answer is also graded 1-5 for
    faithfulness (grounded in the retrieved context) and relevance (addresses the
    question) by an LLM-as-judge, and those are averaged into the report.
    """
    golden = load_golden()
    seeded = seed_corpus(golden["documents"])

    per_question = []
    for item in golden["questions"]:
        question = item["q"]
        start = time.perf_counter()
        answer, hits, context = _rag_answer(question, k)
        latency_ms = round((time.perf_counter() - start) * 1000)

        titles = [h["title"] for h in hits]
        retrieval_hit = item["expected_doc_title"] in titles
        answer_correct = _answer_ok(answer, item["expected_answer_contains"])

        record = {
            "question": question,
            "expected_doc": item["expected_doc_title"],
            "retrieved_docs": titles,
            "retrieval_hit": retrieval_hit,
            "answer_correct": answer_correct,
            "latency_ms": latency_ms,
            "answer": answer.strip(),
        }
        if judge:
            grade = judge_answer(question, context, answer)
            record["faithfulness"] = grade["faithfulness"]
            record["relevance"] = grade["relevance"]
            record["rationale"] = grade["rationale"]
        per_question.append(record)

    n = len(per_question)
    retrieval_hits = sum(1 for r in per_question if r["retrieval_hit"])
    answer_hits = sum(1 for r in per_question if r["answer_correct"])
    avg_latency = round(sum(r["latency_ms"] for r in per_question) / n) if n else 0

    report = {
        "k": k,
        "judged": judge,
        "documents_seeded": seeded,
        "num_questions": n,
        "retrieval_hit_rate": round(retrieval_hits / n, 3) if n else 0.0,
        "answer_accuracy": round(answer_hits / n, 3) if n else 0.0,
        "avg_latency_ms": avg_latency,
        "results": per_question,
    }
    if judge and n:
        report["avg_faithfulness"] = round(
            sum(r["faithfulness"] for r in per_question) / n, 2
        )
        report["avg_relevance"] = round(
            sum(r["relevance"] for r in per_question) / n, 2
        )
    return report


def save_report(report: dict) -> Path:
    """Write a timestamped JSON report under eval/reports/ and return its path."""
    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"report-{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    return path
