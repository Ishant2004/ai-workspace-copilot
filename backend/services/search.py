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

from services import db
from services.gemini import embed_text

# How many candidates to pull from each retriever before fusing.
_CANDIDATES = 20
# RRF dampening constant. 60 is the value from the original RRF paper; larger
# means top ranks matter slightly less relative to the long tail.
_RRF_K = 60


def run_search(query: str, k: int, mode: str) -> list[dict]:
    """Dispatch to the requested strategy: 'vector', 'keyword', or 'hybrid'."""
    if mode == "keyword":
        hits = db.keyword_search(query, k)
        return [
            {**h, "similarity": 0.0, "matched_by": ["keyword"]} for h in hits
        ]

    if mode == "vector":
        hits = db.search(embed_text(query), k)
        return [{**h, "matched_by": ["vector"]} for h in hits]

    return _hybrid(query, k)


def _hybrid(query: str, k: int) -> list[dict]:
    vector_hits = db.search(embed_text(query), _CANDIDATES)
    keyword_hits = db.keyword_search(query, _CANDIDATES)

    scores: dict[int, float] = {}
    data: dict[int, dict] = {}
    matched: dict[int, list[str]] = {}

    for name, hits in (("vector", vector_hits), ("keyword", keyword_hits)):
        for rank, hit in enumerate(hits):
            doc_id = hit["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            # Prefer the vector row's dict so we keep its cosine `similarity`
            # for display; only fall back to the keyword row if unseen.
            data.setdefault(doc_id, hit)
            matched.setdefault(doc_id, []).append(name)

    fused = []
    for doc_id, rrf in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        hit = data[doc_id]
        fused.append(
            {
                "id": doc_id,
                "title": hit["title"],
                "text": hit["text"],
                "metadata": hit.get("metadata", {}),
                # Keep cosine similarity when we have it (vector hit); else 0.
                "similarity": float(hit.get("similarity", 0.0)),
                "rrf_score": round(rrf, 6),
                "matched_by": matched[doc_id],
            }
        )
    return fused[:k]
