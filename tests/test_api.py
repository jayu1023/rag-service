"""End-to-end over the real embedder and embedded Qdrant.

Slow (loads a sentence-transformers model) but it is the only test that proves
the pieces actually compose: ingest -> index -> hybrid retrieve -> SSE answer.
"""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(corpus_dir):
    from app.main import app

    with TestClient(app) as c:
        resp = c.post("/ingest", json={"paths": [str(corpus_dir)], "reset": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["chunks"] > 0
        yield c


def test_health_reports_the_live_index_size(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["backend"] == "qdrant"
    assert body["chunks"] > 0


def test_ingest_rejects_an_empty_path_list(client):
    assert client.post("/ingest", json={"paths": []}).status_code == 422


def test_ingest_rejects_paths_with_nothing_ingestable(client, tmp_path):
    assert client.post("/ingest", json={"paths": [str(tmp_path)]}).status_code == 422


def test_ask_rejects_a_blank_question(client):
    assert client.post("/ask", json={"question": "   "}).status_code == 422


def test_ask_sync_returns_citations_pointing_at_the_right_document(client):
    body = client.post(
        "/ask/sync",
        json={"question": "How many partitions does the events.raw Kafka topic have?"},
    ).json()
    assert body["citations"], body
    assert any("06-architecture" in c["source"] for c in body["citations"])


def test_ask_streams_sources_before_any_token(client):
    with client.stream(
        "POST", "/ask", json={"question": "What is the backend rollback target?"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in resp.iter_lines():
            if line.startswith("event: "):
                events.append(line.removeprefix("event: ").strip())
            elif line.startswith("data: ") and events and events[-1] == "sources":
                payload = json.loads(line.removeprefix("data: "))
                assert payload["citations"]

    assert events[0] == "sources"
    assert "token" in events
    assert events[-1] in {"done", "error"}


def test_disabling_hybrid_still_answers(client):
    body = client.post(
        "/ask/sync",
        json={"question": "Which plan can use customer-managed encryption keys?", "hybrid": False},
    ).json()
    assert body["citations"]
