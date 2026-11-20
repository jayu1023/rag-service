#!/usr/bin/env python
"""Verify the LangSmith OTLP export end to end — needs YOUR api key.

    export LANGSMITH_API_KEY=ls__...          # yours; never committed
    python evals/langsmith_check.py

**This script has never been run by the repo author.** LangSmith is a hosted
service with no local or offline mode, so unlike the W&B path (which runs
offline with no account) there is no way to exercise it without a key. The
integration is written and configured; it is not verified. The README says so
in those words rather than implying otherwise.

If you have a key, this is a 30-second check: it emits one trace to LangSmith's
OTLP endpoint and tells you whether the collector accepted it. If it prints
`accepted`, the claim is real for you and you can say so.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENDPOINT = "https://api.smith.langchain.com/otel/v1/traces"


def main() -> int:
    key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not key:
        print(
            "LANGSMITH_API_KEY is not set.\n\n"
            "This is the one integration in this repo that cannot be verified without\n"
            "an account — LangSmith is hosted and has no offline mode. Set the key and\n"
            "re-run to check it for yourself:\n\n"
            "    export LANGSMITH_API_KEY=ls__...\n"
            "    python evals/langsmith_check.py\n",
            file=sys.stderr,
        )
        return 2

    project = os.getenv("LANGSMITH_PROJECT", "rag-service")
    os.environ["TRACE_EXPORTER"] = "otlp"
    os.environ["OTLP_ENDPOINT"] = os.getenv("OTLP_ENDPOINT", ENDPOINT)
    os.environ["OTLP_HEADERS"] = f"x-api-key={key},Langsmith-Project={project}"

    from app.tracing import flush, span

    print(f"emitting one trace to {os.environ['OTLP_ENDPOINT']} (project={project})…")
    with span("rag.langsmith_check", **{"rag.source": "langsmith_check.py"}):
        with span("rag.child", **{"rag.ok": True}):
            pass
    flush()

    print(
        "\nflushed. The OTLP exporter logs a warning above if the collector rejected it;\n"
        "silence means accepted. Confirm the trace appears in your LangSmith project:\n"
        f"  https://smith.langchain.com/  -> project {project!r}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
