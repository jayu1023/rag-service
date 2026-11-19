"""Prompt assembly, streaming answer, inline citations.

Two deliberate choices:
1. Context is budgeted in tokens, not "top 5 chunks". A fixed k with variable
   chunk sizes is how prompts silently overflow in production.
2. With no OPENAI_API_KEY the service still answers -- extractively, from the
   top chunks. An interviewer cloning the repo gets a working /ask without
   paying for anything, and the degraded path is explicit rather than a 500.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from .config import settings
from .models import Citation, Hit
from .retrieve import retrieve

CONTEXT_TOKEN_BUDGET = 2400

SYSTEM_PROMPT = (
    "You answer strictly from the numbered sources provided. "
    "Cite every claim with inline markers like [1] or [2][3]. "
    "If the sources do not contain the answer, say exactly: "
    "'The provided sources do not answer that.' Never use outside knowledge."
)


def build_context(hits: list[Hit]) -> tuple[str, list[Citation]]:
    from .ingest import count_tokens

    blocks: list[str] = []
    citations: list[Citation] = []
    used = 0

    for n, hit in enumerate(hits, start=1):
        block = f"[{n}] source={hit.chunk.source} chunk={hit.chunk.ordinal}\n{hit.chunk.text}"
        cost = count_tokens(block)
        if used + cost > CONTEXT_TOKEN_BUDGET and blocks:
            break
        blocks.append(block)
        citations.append(
            Citation(n=n, source=hit.chunk.source, chunk_id=hit.chunk.id, score=round(hit.score, 4))
        )
        used += cost

    return "\n\n".join(blocks), citations


def build_messages(question: str, context: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"},
    ]


def _extractive(question: str, hits: list[Hit], citations: list[Citation]) -> str:
    """No-LLM fallback: return the best passages verbatim with their markers."""
    if not hits:
        return "The provided sources do not answer that."
    lines = ["(no LLM configured — returning retrieved passages verbatim)"]
    for citation, hit in zip(citations, hits):
        snippet = " ".join(hit.chunk.text.split())[:600]
        lines.append(f"[{citation.n}] {snippet}")
    return "\n\n".join(lines)


def answer_sync(question: str, **kw) -> tuple[str, list[Citation]]:
    hits = retrieve(question, **kw)
    context, citations = build_context(hits)
    cfg = settings()

    if not cfg.openai_api_key:
        return _extractive(question, hits[: len(citations)], citations), citations

    from openai import OpenAI

    resp = OpenAI(api_key=cfg.openai_api_key).chat.completions.create(
        model=cfg.answer_model,
        messages=build_messages(question, context),
        temperature=0.0,
    )
    return resp.choices[0].message.content or "", citations


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_stream(question: str, **kw) -> AsyncIterator[str]:
    """SSE: `sources` first, then `token`*, then `done`.

    Sources are emitted before the first token on purpose -- the client can
    render citation chips while the model is still generating, and a user can
    see what the answer is grounded in even if generation fails midway.
    """
    hits = retrieve(question, **kw)
    context, citations = build_context(hits)
    yield _sse("sources", {"citations": [c.model_dump() for c in citations]})

    cfg = settings()
    if not cfg.openai_api_key:
        yield _sse("token", {"text": _extractive(question, hits[: len(citations)], citations)})
        yield _sse("done", {"reason": "no_llm"})
        return

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=cfg.openai_api_key)
    try:
        stream = await client.chat.completions.create(
            model=cfg.answer_model,
            messages=build_messages(question, context),
            temperature=0.0,
            stream=True,
        )
        async for part in stream:
            delta = part.choices[0].delta.content
            if delta:
                yield _sse("token", {"text": delta})
        yield _sse("done", {"reason": "stop"})
    except Exception as exc:  # surface failures in-band; the client already has sources
        yield _sse("error", {"message": str(exc)})
