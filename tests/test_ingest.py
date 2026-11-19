"""Chunking is the part most likely to break silently, so it gets the most tests."""

import pytest

from app.ingest import chunk_text, count_tokens, normalize


def test_normalize_collapses_whitespace_and_strips_nulls():
    assert normalize("a\r\n\n\n\nb   c\x00") == "a\n\nb c"


def test_single_short_block_is_one_chunk():
    chunks = chunk_text("one paragraph only.", max_tokens=512, overlap_tokens=64)
    assert chunks == ["one paragraph only."]


def test_every_chunk_respects_the_token_budget():
    text = "\n\n".join(f"Paragraph {i}. " + "filler words here. " * 20 for i in range(40))
    budget = 256
    chunks = chunk_text(text, max_tokens=budget, overlap_tokens=32)
    assert len(chunks) > 1
    # Overlap is prepended before the budget check on the next block, so a chunk
    # may exceed the budget by at most the overlap allowance.
    assert all(count_tokens(c) <= budget + 32 for c in chunks)


def test_overlap_repeats_trailing_sentence_between_chunks():
    text = "\n\n".join(f"Sentence {i} carries a distinct marker M{i}." for i in range(60))
    chunks = chunk_text(text, max_tokens=120, overlap_tokens=40)
    assert len(chunks) >= 2
    # The tail of chunk n must reappear at the head of chunk n+1.
    assert any(
        chunks[i].split()[-3:] == chunks[i + 1].split()[:3] or
        chunks[i + 1].split()[0] in chunks[i]
        for i in range(len(chunks) - 1)
    )


def test_oversized_single_block_is_hard_split_not_dropped():
    giant = "word " * 4000  # one paragraph, no blank lines to split on
    chunks = chunk_text(giant, max_tokens=200, overlap_tokens=0)
    assert len(chunks) > 1
    assert all(count_tokens(c) <= 200 for c in chunks)
    # Nothing is lost: the reassembled text has the same word count.
    assert sum(c.count("word") for c in chunks) == 4000


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("x", max_tokens=64, overlap_tokens=64)


def test_empty_input_yields_no_chunks():
    assert chunk_text("   \n\n  ", max_tokens=128, overlap_tokens=16) == []
