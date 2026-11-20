"""The renderer that produces the README's trace evidence."""

from app.trace_tree import render


def span(name, span_id, parent_id, start, end, **attributes):
    return {
        "name": name, "span_id": span_id, "parent_id": parent_id,
        "trace_id": "t", "start": start, "end": end,
        "duration_ms": (end - start) / 1e6, "status": "UNSET",
        "attributes": attributes,
    }


def test_renders_nesting_with_tree_connectors():
    out = render([
        span("rag.ask", "a", None, 0, 100_000_000),
        span("rag.retrieve", "b", "a", 10_000_000, 90_000_000),
        span("rag.rerank", "c", "b", 20_000_000, 80_000_000),
    ])
    assert "rag.ask" in out
    assert "└─ rag.retrieve" in out or "├─ rag.retrieve" in out
    assert "rag.rerank" in out


def test_reports_each_span_share_of_wall_clock():
    out = render([
        span("rag.ask", "a", None, 0, 100_000_000),
        span("rag.rerank", "b", "a", 0, 95_000_000),
    ])
    assert "100.0%" in out
    assert "95.0%" in out


def test_interesting_attributes_are_shown_inline():
    out = render([span("rag.retrieve", "a", None, 0, 1_000_000, **{"rag.hits": 22})])
    assert "hits=22" in out


def test_absolute_source_paths_are_shortened():
    out = render([
        span("rag.retrieve", "a", None, 0, 1_000_000,
             **{"rag.top_source": "/very/long/path/to/data/corpus/14-incident-comms.md"})
    ])
    assert "top_source=14-incident-comms.md" in out
    assert "/very/long/path" not in out


def test_an_orphaned_span_is_still_rendered():
    """If a parent was never exported, its child must not vanish silently."""
    out = render([span("rag.child", "b", "missing-parent", 0, 1_000_000)])
    assert "rag.child" in out


def test_empty_input_does_not_crash():
    assert render([]) == "(no spans)"


def test_span_count_and_wall_clock_are_summarised():
    out = render([
        span("a", "1", None, 0, 50_000_000),
        span("b", "2", "1", 0, 25_000_000),
    ])
    assert "2 spans" in out
    assert "50.00ms" in out


def test_children_are_ordered_by_start_time():
    out = render([
        span("root", "r", None, 0, 100_000_000),
        span("second", "s", "r", 50_000_000, 60_000_000),
        span("first", "f", "r", 10_000_000, 20_000_000),
    ])
    assert out.index("first") < out.index("second")
