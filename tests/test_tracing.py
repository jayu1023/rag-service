"""Tracing must be free when off, correct when on, and never break the request.

The failure mode worth guarding: tracing that throws, or that quietly costs
something on every request when nobody asked for it.
"""

import json
import os

import pytest

from app import tracing


@pytest.fixture(autouse=True)
def reset_tracing():
    tracing._provider.cache_clear()
    tracing.tracer.cache_clear()
    yield
    tracing._provider.cache_clear()
    tracing.tracer.cache_clear()


def test_tracing_is_off_by_default(monkeypatch):
    """Opt-in, not opt-out. A library that traces by default is a nuisance."""
    monkeypatch.delenv("TRACE_EXPORTER", raising=False)
    assert tracing._provider() is None


def test_spans_are_a_no_op_when_disabled(monkeypatch):
    """The call sites have no `if enabled` guard, so this has to hold."""
    monkeypatch.delenv("TRACE_EXPORTER", raising=False)
    with tracing.span("rag.anything", **{"rag.x": 1}) as s:
        tracing.set_attributes(s, **{"rag.y": 2})
    tracing.flush()  # must not raise with no provider


def test_an_unknown_exporter_fails_loudly(monkeypatch):
    monkeypatch.setenv("TRACE_EXPORTER", "carrier-pigeon")
    with pytest.raises(ValueError, match="unknown TRACE_EXPORTER"):
        tracing._provider()


def test_file_exporter_writes_one_json_object_per_span(monkeypatch, tmp_path):
    path = tmp_path / "t.jsonl"
    monkeypatch.setenv("TRACE_EXPORTER", "file")
    monkeypatch.setenv("TRACE_FILE", str(path))

    with tracing.span("rag.parent", **{"rag.top_k": 5}):
        with tracing.span("rag.child", **{"rag.hits": 3}):
            pass
    tracing.flush()

    spans = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(spans) == 2
    by_name = {s["name"]: s for s in spans}
    assert by_name["rag.parent"]["attributes"]["rag.top_k"] == 5
    assert by_name["rag.child"]["attributes"]["rag.hits"] == 3


def test_child_spans_record_their_parent(monkeypatch, tmp_path):
    """A flat list of spans is not a trace. Nesting is the whole product."""
    path = tmp_path / "t.jsonl"
    monkeypatch.setenv("TRACE_EXPORTER", "file")
    monkeypatch.setenv("TRACE_FILE", str(path))

    with tracing.span("rag.parent"):
        with tracing.span("rag.child"):
            pass
    tracing.flush()

    spans = {s["name"]: s for s in (json.loads(l) for l in path.read_text().splitlines() if l.strip())}
    assert spans["rag.parent"]["parent_id"] is None
    assert spans["rag.child"]["parent_id"] == spans["rag.parent"]["span_id"]
    assert spans["rag.child"]["trace_id"] == spans["rag.parent"]["trace_id"]


def test_none_valued_attributes_are_dropped(monkeypatch, tmp_path):
    """OTel rejects None attribute values; the helper must filter them."""
    path = tmp_path / "t.jsonl"
    monkeypatch.setenv("TRACE_EXPORTER", "file")
    monkeypatch.setenv("TRACE_FILE", str(path))

    with tracing.span("rag.x", **{"rag.present": 1, "rag.absent": None}):
        pass
    tracing.flush()

    attributes = json.loads(path.read_text().splitlines()[0])["attributes"]
    assert attributes == {"rag.present": 1}


def test_the_file_is_truncated_per_run(monkeypatch, tmp_path):
    """A trace file that accumulates across runs is an archive, not a trace."""
    path = tmp_path / "t.jsonl"
    path.write_text('{"stale": true}\n')
    monkeypatch.setenv("TRACE_EXPORTER", "file")
    monkeypatch.setenv("TRACE_FILE", str(path))

    with tracing.span("rag.fresh"):
        pass
    tracing.flush()

    assert "stale" not in path.read_text()


def test_duration_is_recorded_in_milliseconds(monkeypatch, tmp_path):
    import time

    path = tmp_path / "t.jsonl"
    monkeypatch.setenv("TRACE_EXPORTER", "file")
    monkeypatch.setenv("TRACE_FILE", str(path))

    with tracing.span("rag.slow"):
        time.sleep(0.05)
    tracing.flush()

    duration = json.loads(path.read_text().splitlines()[0])["duration_ms"]
    assert 40 < duration < 500
