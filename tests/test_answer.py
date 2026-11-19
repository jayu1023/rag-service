"""Context budgeting and citation numbering — the parts that silently overflow."""

from app.answer import CONTEXT_TOKEN_BUDGET, build_context, build_messages
from app.models import Chunk, Hit


def _hit(n: int, words: int = 10) -> Hit:
    return Hit(
        chunk=Chunk(
            id=f"c{n}", doc_id="d", source=f"doc{n}.md", ordinal=n,
            text=" ".join(f"w{n}" for _ in range(words)), token_count=words,
        ),
        fused_score=1.0 / (n + 1),
    )


def test_citations_are_numbered_from_one_and_match_the_context_markers():
    context, citations = build_context([_hit(1), _hit(2), _hit(3)])
    assert [c.n for c in citations] == [1, 2, 3]
    for c in citations:
        assert f"[{c.n}]" in context


def test_context_stops_at_the_token_budget_and_citations_stay_in_sync():
    hits = [_hit(i, words=900) for i in range(1, 11)]
    context, citations = build_context(hits)
    from app.ingest import count_tokens

    assert count_tokens(context) <= CONTEXT_TOKEN_BUDGET + 1200  # one block may overshoot
    assert len(citations) < len(hits)
    assert len(citations) == context.count("source=")


def test_a_single_oversized_chunk_is_still_included():
    """Better a too-long prompt than an answer with no context at all."""
    _, citations = build_context([_hit(1, words=5000)])
    assert len(citations) == 1


def test_no_hits_yields_empty_context_and_no_citations():
    assert build_context([]) == ("", [])


def test_system_prompt_forbids_outside_knowledge():
    messages = build_messages("q", "ctx")
    assert messages[0]["role"] == "system"
    assert "do not answer" in messages[0]["content"].lower() or "never use outside" in messages[0]["content"].lower()
    assert "q" in messages[1]["content"] and "ctx" in messages[1]["content"]
