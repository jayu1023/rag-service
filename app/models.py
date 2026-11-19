"""Wire + internal types. Kept in one file because they are all small."""

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str
    doc_id: str
    source: str
    ordinal: int
    text: str
    token_count: int


class Hit(BaseModel):
    chunk: Chunk
    dense_score: float = 0.0
    bm25_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float | None = None

    @property
    def score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.fused_score


class IngestRequest(BaseModel):
    paths: list[str] = Field(
        default_factory=list,
        description="Files or directories to ingest (.pdf, .md, .txt).",
    )
    reset: bool = Field(default=False, description="Drop the collection first.")


class IngestResponse(BaseModel):
    documents: int
    chunks: int
    skipped: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    n: int
    source: str
    chunk_id: str
    score: float


class AskRequest(BaseModel):
    question: str
    top_k: int | None = None
    rerank: bool | None = None
    hybrid: bool = True


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
