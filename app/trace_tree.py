#!/usr/bin/env python
"""Render a JSONL trace file as a tree. The README's trace evidence comes from here.

    TRACE_EXPORTER=file python -m app.trace_tree --demo
    python -m app.trace_tree data/trace.jsonl

A rendered tree rather than a screenshot, deliberately: it is diffable, it
survives in a README without an image host, and anyone can regenerate it with
one command and check it matches. A screenshot of Jaeger proves only that a
screenshot exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Attributes worth printing inline. Everything else stays in the JSON.
INTERESTING = (
    "rag.hits", "rag.returned", "rag.chunks", "rag.citations", "rag.context_tokens",
    "rag.scored", "rag.rerank_changed_top", "rag.fused_candidates", "rag.alpha",
    "rag.backend", "rag.top_k", "rag.candidate_k", "rag.hybrid", "rag.rerank",
    "rag.llm", "rag.top_source", "rag.dim",
)


def load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"no trace file at {path} — run with TRACE_EXPORTER=file first")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def render(spans: list[dict]) -> str:
    if not spans:
        return "(no spans)"

    by_parent: dict[str | None, list[dict]] = {}
    for s in spans:
        by_parent.setdefault(s["parent_id"], []).append(s)
    for children in by_parent.values():
        children.sort(key=lambda s: s["start"])

    known = {s["span_id"] for s in spans}
    # A span whose parent was never exported is a root for rendering purposes.
    roots = [s for s in spans if s["parent_id"] is None or s["parent_id"] not in known]
    roots.sort(key=lambda s: s["start"])

    total = max(s["end"] for s in spans) - min(s["start"] for s in spans)
    total_ms = total / 1e6 or 1.0
    lines: list[str] = []

    def walk(span: dict, prefix: str, is_last: bool, depth: int) -> None:
        connector = "" if depth == 0 else ("└─ " if is_last else "├─ ")
        share = span["duration_ms"] / total_ms * 100
        bar = "█" * max(1, round(share / 5)) if share >= 2.5 else ""
        def fmt(key: str) -> str:
            value = span["attributes"][key]
            # Absolute corpus paths make the tree unreadable in a README.
            if key == "rag.top_source" and isinstance(value, str):
                value = value.rsplit("/", 1)[-1]
            return f"{key.removeprefix('rag.')}={value}"

        attrs = " ".join(fmt(k) for k in INTERESTING if k in span["attributes"])
        lines.append(
            f"{prefix}{connector}{span['name']:<22} {span['duration_ms']:>8.2f}ms "
            f"{share:>5.1f}% {bar:<20} {attrs}"
        )
        kids = by_parent.get(span["span_id"], [])
        child_prefix = prefix + ("" if depth == 0 else ("   " if is_last else "│  "))
        for i, kid in enumerate(kids):
            walk(kid, child_prefix, i == len(kids) - 1, depth + 1)

    for root in roots:
        walk(root, "", True, 0)
    lines.append("")
    lines.append(f"{len(spans)} spans, {total_ms:.2f}ms wall clock")
    return "\n".join(lines)


def demo() -> int:
    """Index the corpus and answer one question, with tracing on."""
    os.environ.setdefault("TRACE_EXPORTER", "file")
    trace_file = os.environ.setdefault("TRACE_FILE", str(ROOT / "data" / "trace.jsonl"))
    sys.path.insert(0, str(ROOT))

    from app.answer import answer_sync
    from app.embed import embed_and_upsert, store
    from app.ingest import chunk_file, iter_files
    from app.retrieve import refresh_bm25
    from app.tracing import flush, span

    question = "How often is the status page updated during a Sev-1?"

    # ensure() before count(): on a cold clone the collection does not exist
    # yet and count() raises rather than returning 0.
    store().ensure()
    if store().count() == 0:
        with span("rag.ingest"):
            for path in iter_files([str(ROOT / "data" / "corpus")]):
                embed_and_upsert(chunk_file(path))
        refresh_bm25()
        flush()
        print(f"indexed {store().count()} chunks\n")
    else:
        refresh_bm25()

    # Warm the models BEFORE the measured call. The first answer pays ~2.5s to
    # load the cross-encoder, which would otherwise dominate the tree and make
    # `rag.rerank` look 20x more expensive than it is in steady state. A trace
    # of a cold start is a real thing to measure, but it is not the thing this
    # tree is showing.
    answer_sync(question)
    flush()

    # Truncate so the rendered tree is one warm /ask, not ingest + warmup + ask.
    open(trace_file, "w").close()
    answer, citations = answer_sync(question)
    flush()

    rendered = render(load(Path(trace_file)))
    cited = [c.source.split("/")[-1] for c in citations]
    print(f"Q: {question}")
    print(f"cited: {cited}\n")
    print(rendered)

    if "--write" in sys.argv:
        target = ROOT / "docs" / "TRACE.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# Captured trace\n\n"
            "Generated by `TRACE_EXPORTER=file python -m app.trace_tree --demo --write`.\n"
            "Regenerate and diff to check it is current.\n\n"
            "The models are warmed before the measured call: the first answer pays ~2.5s\n"
            "to load the cross-encoder, which would otherwise dominate the tree and make\n"
            "`rag.rerank` look 20x more expensive than it is in steady state.\n\n"
            f"Question: _{question}_\n\n"
            f"Cited: {', '.join(cited)}\n\n"
            "```\n" + rendered + "\n```\n"
        )
        print(f"\nwrote {target.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=str(ROOT / "data" / "trace.jsonl"))
    parser.add_argument("--demo", action="store_true", help="run one traced /ask, then render")
    parser.add_argument("--write", action="store_true", help="also write docs/TRACE.md")
    args = parser.parse_args()
    if args.demo:
        return demo()
    print(render(load(Path(args.path))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
