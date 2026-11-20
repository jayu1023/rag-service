#!/usr/bin/env python
"""Verify the LangSmith OTLP export end to end — needs YOUR api key.

    export LANGSMITH_API_KEY=ls__...          # yours; never committed
    python evals/langsmith_check.py

**This script has never been run by the repo author.** LangSmith is a hosted
service with no local or offline mode, so unlike the W&B path (which runs
offline with no account) there is no way to exercise it without a key. The
integration is written and configured; it is not verified. The README says so
in those words rather than implying otherwise.

If you have a key this is a 30-second check. It builds the OTLP exporter
directly rather than going through `app.tracing`, because a span pipeline
swallows export failures by design -- tracing must never break the request it
is tracing -- and that is exactly the wrong property for a verification
script. Here the export result is inspected and the exit code reflects it:

    0  every export accepted (HTTP 2xx)
    1  an export was rejected -- read the logged status (401/403 = key)
    2  no key set

So a passing run is evidence, not an absence of complaint.
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
            "    export LANGSMITH_API_KEY=lsv2_pt_...\n"
            "    python evals/langsmith_check.py\n",
            file=sys.stderr,
        )
        return 2

    project = os.getenv("LANGSMITH_PROJECT", "rag-service")
    endpoint = os.getenv("OTLP_ENDPOINT", ENDPOINT)
    print(f"endpoint : {endpoint}")
    print(f"project  : {project}")
    print(f"key      : {key[:9]}…{key[-4:]}  ({len(key)} chars)\n")

    # Build the exporter directly rather than going through app.tracing, so the
    # export RESULT is observable. A span pipeline swallows failures by design
    # -- tracing must never break the request it is tracing -- which is exactly
    # the wrong property for a verification script.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult

    observed: list[SpanExportResult] = []

    class Recording(OTLPSpanExporter):
        def export(self, spans):
            result = super().export(spans)
            observed.append(result)
            return result

    exporter = Recording(
        endpoint=endpoint,
        headers={"x-api-key": key, "Langsmith-Project": project},
        timeout=20,
    )
    provider = TracerProvider(resource=Resource.create({"service.name": "rag-service"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("langsmith-check")

    print("emitting one trace…")
    with tracer.start_as_current_span("rag.langsmith_check") as parent:
        parent.set_attribute("rag.source", "langsmith_check.py")
        with tracer.start_as_current_span("rag.child") as child:
            child.set_attribute("rag.ok", True)
    provider.force_flush()
    provider.shutdown()

    if not observed:
        print("\nFAIL: the exporter never ran. Nothing was sent.", file=sys.stderr)
        return 1

    failures = [r for r in observed if r is not SpanExportResult.SUCCESS]
    if failures:
        print(
            f"\nFAIL: {len(failures)}/{len(observed)} export(s) rejected.\n"
            "The OTLP exporter logs the HTTP status above. 401/403 means the key is\n"
            "wrong or lacks tracing scope; 404 means the endpoint is wrong.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\nPASS: {len(observed)}/{len(observed)} export(s) accepted (HTTP 2xx).\n"
        f"Confirm the trace 'rag.langsmith_check' appears at\n"
        f"  https://smith.langchain.com/  -> project {project!r}\n\n"
        "If you see it there, the LangSmith claim is verified FOR YOU and you can put\n"
        "it on your CV. Paste this output back and the README will be updated to match."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
