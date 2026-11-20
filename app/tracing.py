"""OpenTelemetry tracing, with an exporter you can actually read locally.

Three exporters, chosen by `TRACE_EXPORTER`:

  none    (default) -- no-op tracer. Zero overhead, zero output. Tracing that
          is on by default in a library is a nuisance, so it is opt-in.
  file    writes one JSON span per line to `TRACE_FILE`. This is the one that
          makes the trace trees in the README reproducible: no collector, no
          Docker, no account, and `python -m app.trace_tree` renders it.
  otlp    ships to any OTLP/HTTP collector (Jaeger, Tempo, Honeycomb,
          Grafana Cloud, LangSmith's OTLP endpoint) via `OTLP_ENDPOINT`.

**On LangSmith:** it accepts OTLP, so `TRACE_EXPORTER=otlp` with LangSmith's
endpoint and an `Authorization` header works. That path is **implemented and
never executed** -- no API key was used in this repo, and the README says so
rather than implying a LangSmith integration was verified.

Spans are named `rag.<phase>` so a trace reads as the pipeline, not as a stack
of function names.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult

SERVICE_NAME = "rag-service"


class JsonFileExporter(SpanExporter):
    """One JSON object per span, one span per line.

    Deliberately not OTel's own ConsoleSpanExporter: that prints a large
    multi-line blob per span, which is unreadable for a 10-span trace and
    impossible to post-process. One line per span makes `trace_tree.py` a
    20-line script.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Truncate on start so a run's trace file is that run, not an archive.
        open(self._path, "w").close()

    def export(self, spans) -> SpanExportResult:
        with open(self._path, "a", encoding="utf-8") as fh:
            for span in spans:
                fh.write(json.dumps(self._as_dict(span), default=str) + "\n")
        return SpanExportResult.SUCCESS

    @staticmethod
    def _as_dict(span: ReadableSpan) -> dict[str, Any]:
        context = span.get_span_context()
        parent = span.parent
        return {
            "name": span.name,
            "trace_id": format(context.trace_id, "032x"),
            "span_id": format(context.span_id, "016x"),
            "parent_id": format(parent.span_id, "016x") if parent else None,
            "start": span.start_time,
            "end": span.end_time,
            "duration_ms": round((span.end_time - span.start_time) / 1e6, 2),
            "status": span.status.status_code.name,
            "attributes": dict(span.attributes or {}),
        }

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


@lru_cache
def _provider() -> TracerProvider | None:
    mode = os.getenv("TRACE_EXPORTER", "none").lower()
    if mode == "none":
        return None

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))

    if mode == "file":
        # Simple, not Batch: a short script can exit before a batch flushes,
        # and a trace file that is sometimes empty is worse than a slow one.
        provider.add_span_processor(
            SimpleSpanProcessor(JsonFileExporter(os.getenv("TRACE_FILE", "./data/trace.jsonl")))
        )
    elif mode == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = os.getenv("OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
        headers = {}
        if os.getenv("OTLP_HEADERS"):
            # "k=v,k2=v2" -- the usual OTEL_EXPORTER_OTLP_HEADERS format
            headers = dict(
                part.split("=", 1) for part in os.getenv("OTLP_HEADERS", "").split(",") if "=" in part
            )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        )
    else:
        raise ValueError(f"unknown TRACE_EXPORTER: {mode!r}")

    # Also publish globally, so any third-party library that is already
    # instrumented joins the same trace. This is best-effort: OTel allows it
    # exactly once per process and logs a warning on a second attempt, which
    # is why `tracer()` below does NOT read the global back.
    if trace.get_tracer_provider().__class__.__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(provider)
    return provider


@lru_cache
def tracer():
    provider = _provider()
    if provider is None:
        # The API's no-op tracer: every `with span(...)` in the codebase costs
        # essentially nothing when tracing is off, which is why no call site
        # needs an `if tracing_enabled` guard.
        return trace.get_tracer(__name__)
    # Deliberately from OUR provider rather than `trace.get_tracer(...)`:
    # set_tracer_provider is one-shot per process, so reading the global back
    # would pin every later reconfiguration to whatever was set first. That
    # silently broke the tests before it would have silently broken a user
    # changing TRACE_FILE between runs in one process.
    return provider.get_tracer(SERVICE_NAME)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span. Attributes are set at open; use `set` on the yielded span
    for anything only known at the end (counts, scores, hit/miss)."""
    with tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


def set_attributes(current: Any, **attributes: Any) -> None:
    for key, value in attributes.items():
        if value is not None:
            current.set_attribute(key, value)


def flush() -> None:
    """Flush pending spans. Call before a short-lived process exits."""
    provider = _provider()
    if provider is not None:
        provider.force_flush()
