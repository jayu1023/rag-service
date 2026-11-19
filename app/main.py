"""HTTP surface: POST /ingest, POST /ask (SSE), GET /health."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .answer import answer_stream, answer_sync
from .config import settings
from .embed import embed_and_upsert, store
from .ingest import SUPPORTED, chunk_file, iter_files
from .models import AskRequest, AskResponse, IngestRequest, IngestResponse
from .retrieve import refresh_bm25

log = logging.getLogger("rag")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store().ensure()
    refresh_bm25()  # survive a restart with the index already populated
    yield


app = FastAPI(title="RAG Document Intelligence Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    cfg = settings()
    return {
        "status": "ok",
        "backend": cfg.vector_backend,
        "embed_model": cfg.embed_model,
        "chunks": store().count(),
        "rerank": cfg.rerank_enabled,
    }


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    if not req.paths:
        raise HTTPException(status_code=422, detail="paths must not be empty")

    store().ensure(reset=req.reset)

    files = iter_files(req.paths)
    skipped = [
        p for p in req.paths if not Path(p).exists() or (Path(p).is_file() and Path(p).suffix.lower() not in SUPPORTED)
    ]
    if not files:
        raise HTTPException(status_code=422, detail=f"no ingestable files in {req.paths}")

    total = 0
    for path in files:
        total += embed_and_upsert(chunk_file(path))
        log.info("ingested %s", path)

    refresh_bm25()
    return IngestResponse(documents=len(files), chunks=total, skipped=skipped)


@app.post("/ask")
async def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    return StreamingResponse(
        answer_stream(req.question, top_k=req.top_k, hybrid=req.hybrid, use_rerank=req.rerank),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ask/sync", response_model=AskResponse)
def ask_sync(req: AskRequest) -> AskResponse:
    """Non-streaming twin of /ask. Exists for evals and for curl."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    text, citations = answer_sync(
        req.question, top_k=req.top_k, hybrid=req.hybrid, use_rerank=req.rerank
    )
    return AskResponse(answer=text, citations=citations)
