"""Reranking (Phase 8).

Retrieval (vector/keyword/hybrid) is fast but approximate: it compares the query
and each document *independently* (a query vector vs. precomputed doc vectors),
so it casts a wide net but gets the fine ordering wrong.

A **cross-encoder reranker** reads the query and a candidate *together* and
scores how well that specific document answers that specific query. It's far
more accurate but too slow to run over the whole corpus — so the standard
pattern is: retrieve ~20 cheap candidates, then rerank them down to the best few.

We use **FlashRank**: a tiny cross-encoder that runs in-memory on CPU (ONNX),
no API calls, no GPU. The model (~3MB) downloads once on first use.
"""

from flashrank import Ranker, RerankRequest

from config import settings

# Created lazily so importing this module (and starting the app) doesn't trigger
# a model download until reranking is actually used.
_ranker: Ranker | None = None


def _get_ranker() -> Ranker:
    global _ranker
    if _ranker is None:
        _ranker = Ranker(model_name=settings.rerank_model)
    return _ranker


def rerank(query: str, hits: list[dict], k: int) -> list[dict]:
    """Re-score `hits` against `query` with the cross-encoder, keep the top k.

    Each returned hit gets a `rerank_score`. We pass the list index as the
    passage id so we can map FlashRank's result back to our original dict.
    """
    if not hits:
        return []

    passages = [{"id": i, "text": h["text"]} for i, h in enumerate(hits)]
    ranked = _get_ranker().rerank(
        RerankRequest(query=query, passages=passages)
    )

    out: list[dict] = []
    for r in ranked[:k]:
        hit = hits[r["id"]]
        out.append({**hit, "rerank_score": float(r["score"])})
    return out
