"""Search strategies (Phase 7: Hybrid Search).

Two retrievers see different things:
  - **Vector search** (Phase 3) matches *meaning* — great for paraphrases, but
    it can miss exact terms, names, codes, or rare words that don't embed well.
  - **Keyword search** (Postgres full-text) matches *words* — great for exact
    terms, but blind to synonyms and paraphrasing.

**Hybrid** runs both and fuses their ranked lists with **Reciprocal Rank Fusion
(RRF)**. RRF only looks at each result's *rank* in each list (not the raw,
incomparable scores), giving each document `sum(1 / (k + rank))`. A document
ranked highly by either retriever floats to the top; one ranked well by *both*
wins decisively. It's simple, needs no score normalization, and works well.
"""

from config import settings
from services import db, rerank as rerank_service, rewrite
from services.gemini import embed_text

# How many candidates to pull from each retriever before fusing.
_CANDIDATES = 20
# RRF dampening constant. 60 is the value from the original RRF paper; larger
# means top ranks matter slightly less relative to the long tail.
_RRF_K = 60


def run_search(
    user_id: int, query: str, k: int, mode: str, rerank: bool = False
) -> list[dict]:
    """Search the user's documents, then optionally rerank.

    When reranking, we first retrieve a larger candidate set (so the
    cross-encoder has enough to choose from), then trim to k. Otherwise we just
    retrieve k directly.
    """
    if not (query or "").strip():
        return []  # nothing to search for — avoid embedding an empty string
    n = settings.rerank_candidates if rerank else k
    hits = _retrieve(user_id, query, n, mode)
    if rerank:
        hits = rerank_service.rerank(query, hits, k)
    return hits


def _retrieve(user_id: int, query: str, n: int, mode: str) -> list[dict]:
    """Return up to n of the user's candidates using the requested strategy."""
    if mode == "keyword":
        hits = db.keyword_search(user_id, query, n)
        return [
            {**h, "similarity": 0.0, "matched_by": ["keyword"]} for h in hits
        ]

    if mode == "vector":
        hits = db.search(user_id, embed_text(query), n)
        return [{**h, "matched_by": ["vector"]} for h in hits]

    return _hybrid(user_id, query, n)


def _fuse(ranked_lists: list[tuple[str, list[dict]]], k: int) -> list[dict]:
    """Reciprocal Rank Fusion over several named ranked lists.

    Each document scores `sum over lists of 1 / (RRF_K + rank)`, so anything
    ranked highly by *any* list floats up and anything ranked well by *many*
    lists wins. Used for both hybrid (vector + keyword) and multi-query (the same
    two retrievers run for several query variants) — same math, more lists.
    """
    scores: dict[int, float] = {}
    data: dict[int, dict] = {}
    matched: dict[int, list[str]] = {}

    for name, hits in ranked_lists:
        for rank, hit in enumerate(hits):
            doc_id = hit["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            # Prefer a vector row's dict so we keep its cosine `similarity` for
            # display; only fall back to a keyword row if unseen.
            if doc_id not in data or hit.get("similarity"):
                data.setdefault(doc_id, hit)
            if name not in matched.setdefault(doc_id, []):
                matched[doc_id].append(name)

    fused = []
    for doc_id, rrf in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        hit = data[doc_id]
        fused.append(
            {
                "id": doc_id,
                "title": hit["title"],
                "text": hit["text"],
                "metadata": hit.get("metadata", {}),
                "similarity": float(hit.get("similarity", 0.0)),
                "rrf_score": round(rrf, 6),
                "matched_by": matched[doc_id],
            }
        )
    return fused[:k]


def _hybrid(user_id: int, query: str, k: int) -> list[dict]:
    if not (query or "").strip():
        return []
    candidates = max(_CANDIDATES, k)
    vector_hits = db.search(user_id, embed_text(query), candidates)
    keyword_hits = db.keyword_search(user_id, query, candidates)
    return _fuse([("vector", vector_hits), ("keyword", keyword_hits)], k)


def multi_query_search(user_id: int, queries: list[str], k: int) -> list[dict]:
    """Retrieve for several query variants (Phase 21) and fuse everything.

    We run both retrievers for each query and fuse all the resulting ranked
    lists in one RRF pass, so a document that's relevant across variants is
    rewarded. Falls back to plain hybrid when there's a single query.
    """
    queries = [q for q in queries if q and q.strip()]
    if not queries:
        return []
    if len(queries) == 1:
        return _hybrid(user_id, queries[0], k)

    candidates = max(_CANDIDATES, k)
    ranked_lists: list[tuple[str, list[dict]]] = []
    for i, q in enumerate(queries):
        ranked_lists.append((f"vector{i}", db.search(user_id, embed_text(q), candidates)))
        ranked_lists.append((f"keyword{i}", db.keyword_search(user_id, q, candidates)))
    return _fuse(ranked_lists, k)


def search_expanded(
    user_id: int, question: str, k: int, history: str = ""
) -> list[dict]:
    """RAG retrieval with query rewriting (Phase 21): expand the question into a
    few standalone queries, then multi-query-fuse. Honours the config flag — if
    multi-query is off (or expansion yields one query) it's plain hybrid."""
    if not settings.retrieval_multi_query:
        return _hybrid(user_id, question, k)
    queries = rewrite.expand_query(question, history, settings.rewrite_variants)
    return multi_query_search(user_id, queries, k)
