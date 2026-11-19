"""Dense + BM25 hybrid retrieval, then cross-encoder re-ranking.

Fusion uses weighted Reciprocal Rank Fusion rather than blending raw scores.
Cosine similarity lives in [-1, 1] and BM25 is an unbounded corpus-dependent
sum; adding them means the weight silently changes with corpus size. RRF only
consumes *ranks*, so the single tunable (`hybrid_alpha`) actually means what it
says. Cost: it throws away score margins, which is why the cross-encoder runs
afterwards on the fused candidate set.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache

from .config import settings
from .embed import embedder, store
from .models import Chunk, Hit

RRF_K = 60  # standard damping constant from the original RRF paper
_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25Index:
    """Lexical half of the hybrid. Rebuilt from the store after each ingest.

    ponytail: in-process index, fine up to ~1e5 chunks. Past that move BM25 into
    the engine that already holds the text (Qdrant sparse vectors, or Postgres
    tsvector) instead of growing this.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bm25 = None
        self._chunks: list[Chunk] = []

    def build(self, chunks: list[Chunk]) -> None:
        from rank_bm25 import BM25Okapi

        with self._lock:
            self._chunks = chunks
            self._bm25 = BM25Okapi([tokenize(c.text) for c in chunks]) if chunks else None

    def ready(self) -> bool:
        return self._bm25 is not None

    def search(self, query: str, limit: int) -> list[tuple[Chunk, float]]:
        with self._lock:
            if self._bm25 is None:
                return []
            scores = self._bm25.get_scores(tokenize(query))
            ranked = sorted(zip(self._chunks, scores), key=lambda p: p[1], reverse=True)
        return [(c, float(s)) for c, s in ranked[:limit] if s > 0]


@lru_cache
def bm25() -> BM25Index:
    return BM25Index()


def refresh_bm25() -> int:
    chunks = store().all_chunks()
    bm25().build(chunks)
    return len(chunks)


@lru_cache
def reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(settings().rerank_model)


def _rrf(rank: int) -> float:
    return 1.0 / (RRF_K + rank + 1)


def fuse(
    dense: list[tuple[Chunk, float]],
    lexical: list[tuple[Chunk, float]],
    alpha: float,
) -> list[Hit]:
    hits: dict[str, Hit] = {}

    for rank, (chunk, score) in enumerate(dense):
        hit = hits.setdefault(chunk.id, Hit(chunk=chunk))
        hit.dense_score = score
        hit.fused_score += alpha * _rrf(rank)

    for rank, (chunk, score) in enumerate(lexical):
        hit = hits.setdefault(chunk.id, Hit(chunk=chunk))
        hit.bm25_score = score
        hit.fused_score += (1.0 - alpha) * _rrf(rank)

    return sorted(hits.values(), key=lambda h: h.fused_score, reverse=True)


def rerank(question: str, hits: list[Hit]) -> list[Hit]:
    if not hits:
        return hits
    scores = reranker().predict([(question, h.chunk.text) for h in hits])
    for hit, score in zip(hits, scores):
        hit.rerank_score = float(score)
    return sorted(hits, key=lambda h: h.rerank_score or 0.0, reverse=True)


def retrieve(
    question: str,
    *,
    top_k: int | None = None,
    hybrid: bool = True,
    use_rerank: bool | None = None,
) -> list[Hit]:
    cfg = settings()
    top_k = top_k or cfg.top_k
    use_rerank = cfg.rerank_enabled if use_rerank is None else use_rerank

    # Over-fetch: the re-ranker can only promote what retrieval already found,
    # so recall@candidate_k is the real ceiling on precision@top_k.
    candidates = max(cfg.candidate_k, top_k)

    query_vector = embedder().encode([question], is_query=True)[0]
    dense = store().search(query_vector, candidates)

    if not hybrid:
        hits = [Hit(chunk=c, dense_score=s, fused_score=_rrf(i)) for i, (c, s) in enumerate(dense)]
    else:
        if not bm25().ready():
            refresh_bm25()
        hits = fuse(dense, bm25().search(question, candidates), cfg.hybrid_alpha)

    if use_rerank:
        hits = rerank(question, hits[:candidates])
    return hits[:top_k]
