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
from services import context, db, rewrite
from services.gemini import embed_texts, stream_chat
from services.search import multi_query_search, run_search

# A sentinel owner id for eval data. Real users come from a BIGSERIAL starting at
# 1 (positive), so a negative id can never collide with a real account.
EVAL_USER_ID = -1

_GOLDEN_PATH = Path(__file__).resolve().parent / "golden.json"


def load_golden() -> dict:
    """Load the golden corpus + questions from disk."""
    return json.loads(_GOLDEN_PATH.read_text())


def load_hard() -> dict:
    """Load the harder, vaguer question set used to compare retrieval (Phase 21).

    These use different vocabulary than the documents and add distractor docs, so
    single-query retrieval has room to miss — which is exactly where query
    rewriting + multi-query fusion is meant to help.
    """
    path = Path(__file__).resolve().parent / "golden_hard.json"
    return json.loads(path.read_text())


def seed_corpus(documents: list[dict]) -> int:
    """Replace the eval user's corpus with the given documents.

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


def compare_retrieval(k: int = 2, variants: int = 3) -> dict:
    """Compare single-query hybrid vs query-rewriting multi-query retrieval.

    Isolates the Phase 21 change: it measures **retrieval hit@k only** (did the
    right document make the top-k?), so it needs no answer generation — just
    embeddings and one rewrite call per question. A smaller k over a corpus with
    distractors makes retrieval selective enough for the difference to show.
    """
    golden = load_golden()
    hard = load_hard()
    corpus = golden["documents"] + hard.get("extra_documents", [])
    seeded = seed_corpus(corpus)

    per_question = []
    for item in hard["questions"]:
        q = item["q"]
        expected = item["expected_doc_title"]

        base_hits = run_search(EVAL_USER_ID, q, k, "hybrid")
        base_hit = expected in [h["title"] for h in base_hits]

        queries = rewrite.expand_query(q, "", variants)
        multi_hits = multi_query_search(EVAL_USER_ID, queries, k)
        multi_hit = expected in [h["title"] for h in multi_hits]

        per_question.append(
            {
                "question": q,
                "expected_doc": expected,
                "queries": queries,
                "single_hit": base_hit,
                "multi_hit": multi_hit,
            }
        )

    n = len(per_question)
    single_rate = sum(1 for r in per_question if r["single_hit"]) / n if n else 0
    multi_rate = sum(1 for r in per_question if r["multi_hit"]) / n if n else 0
    return {
        "k": k,
        "variants": variants,
        "documents_seeded": seeded,
        "num_questions": n,
        "single_hit_rate": round(single_rate, 3),
        "multi_hit_rate": round(multi_rate, 3),
        "delta": round(multi_rate - single_rate, 3),
        "results": per_question,
    }


def load_context_eval() -> dict:
    """Load the chunked-document scenario used to compare contextual retrieval."""
    path = Path(__file__).resolve().parent / "golden_context.json"
    return json.loads(path.read_text())


def _seed_vectors(
    titles: list[str], texts: list[str], vectors: list[list[float]]
) -> None:
    """Replace the eval user's corpus with rows using *given* embeddings.

    Lets the contextual comparison store the same display text while embedding
    two different things (raw vs contextualized), isolating the embedding change.
    """
    with db.get_conn() as conn:
        conn.execute("DELETE FROM documents WHERE user_id = %s;", (EVAL_USER_ID,))
    rows = [
        (title, text, vec, {"source": "eval"})
        for title, text, vec in zip(titles, texts, vectors)
    ]
    db.insert_documents(EVAL_USER_ID, rows)


def compare_contextual(k: int = 1) -> dict:
    """Compare raw vs contextual chunk embeddings (Phase 22).

    Same chunks, same display text — only what we embed differs: the raw chunk
    vs a context-line-prepended version. We retrieve with *vector* search (to
    isolate the embedding change) at a selective k, over a chunked document whose
    passages are ambiguous in isolation (e.g. two sections both starting "The
    annual allowance is N days").
    """
    data = load_context_eval()
    chunks = data["chunks"]
    titles = [c["title"] for c in chunks]
    texts = [c["text"] for c in chunks]
    full_text = "\n\n".join(texts)

    def _hits(question: str, expected: str) -> bool:
        found = run_search(EVAL_USER_ID, question, k, "vector")
        return expected in [h["title"] for h in found]

    # Pass 1: raw embeddings.
    _seed_vectors(titles, texts, embed_texts(texts))
    raw = {q["q"]: _hits(q["q"], q["expected"]) for q in data["questions"]}

    # Pass 2: contextualized embeddings (store original text, embed context+text).
    ctx_lines = context.contextualize_all(data["doc_title"], full_text, texts)
    ctx_input = [
        context.contextual_text(c, t) for c, t in zip(ctx_lines, texts)
    ]
    _seed_vectors(titles, texts, embed_texts(ctx_input))
    ctx = {q["q"]: _hits(q["q"], q["expected"]) for q in data["questions"]}

    per_question = [
        {
            "question": q["q"],
            "expected": q["expected"],
            "raw_hit": raw[q["q"]],
            "contextual_hit": ctx[q["q"]],
        }
        for q in data["questions"]
    ]
    n = len(per_question)
    raw_rate = sum(1 for r in per_question if r["raw_hit"]) / n if n else 0
    ctx_rate = sum(1 for r in per_question if r["contextual_hit"]) / n if n else 0
    return {
        "k": k,
        "num_chunks": len(chunks),
        "num_questions": n,
        "raw_hit_rate": round(raw_rate, 3),
        "contextual_hit_rate": round(ctx_rate, 3),
        "delta": round(ctx_rate - raw_rate, 3),
        "context_lines": ctx_lines,
        "results": per_question,
    }


def save_report(report: dict) -> Path:
    """Write a timestamped JSON report under eval/reports/ and return its path."""
    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"report-{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    return path
