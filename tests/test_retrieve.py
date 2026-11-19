"""Fusion and re-ranking logic, tested without touching a model or a store."""

from app.models import Chunk, Hit
from app.retrieve import RRF_K, fuse, tokenize


def _chunk(cid: str, text: str = "text") -> Chunk:
    return Chunk(id=cid, doc_id="d", source=f"{cid}.md", ordinal=0, text=text, token_count=1)


def test_tokenize_is_lowercase_and_keeps_unicode_words():
    assert tokenize("Kafka's 48 Partitions — ઘર") == ["kafka", "s", "48", "partitions", "ઘર"]


def test_fuse_prefers_the_chunk_both_retrievers_rank_highly():
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    dense = [(b, 0.9), (a, 0.8)]
    lexical = [(a, 12.0), (c, 3.0)]
    hits = fuse(dense, lexical, alpha=0.5)
    # `a` is 2nd dense and 1st lexical; `b` is 1st dense but absent lexically.
    assert hits[0].chunk.id == "a"


def test_fuse_alpha_one_ignores_the_lexical_list_ordering():
    a, b = _chunk("a"), _chunk("b")
    hits = fuse([(a, 0.1)], [(b, 99.0)], alpha=1.0)
    assert hits[0].chunk.id == "a"
    assert [h.chunk.id for h in hits if h.fused_score == 0.0] == ["b"]


def test_fuse_uses_ranks_not_raw_scores():
    """A 100x bigger BM25 score must not outrank a better-ranked dense hit."""
    a, b = _chunk("a"), _chunk("b")
    small = fuse([(a, 0.9)], [(b, 1.0)], alpha=0.5)
    huge = fuse([(a, 0.9)], [(b, 100000.0)], alpha=0.5)
    assert [h.chunk.id for h in small] == [h.chunk.id for h in huge]


def test_fuse_carries_both_component_scores_for_debugging():
    a = _chunk("a")
    hit = fuse([(a, 0.77)], [(a, 4.2)], alpha=0.6)[0]
    assert hit.dense_score == 0.77
    assert hit.bm25_score == 4.2
    assert hit.fused_score == 1.0 / (RRF_K + 1)


def test_hit_score_prefers_rerank_when_present():
    hit = Hit(chunk=_chunk("a"), fused_score=0.5)
    assert hit.score == 0.5
    hit.rerank_score = -2.0
    assert hit.score == -2.0
