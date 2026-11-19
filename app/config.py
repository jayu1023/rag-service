"""Single source of truth for runtime config. Everything is env-overridable."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # embeddings
    embed_provider: Literal["local", "openai"] = "local"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: int = 384

    # vector store
    vector_backend: Literal["qdrant", "pgvector"] = "qdrant"
    qdrant_path: str = "./data/qdrant"
    qdrant_url: str | None = None
    qdrant_collection: str = "documents"
    postgres_dsn: str = "postgresql://rag:rag@localhost:5432/rag"

    # chunking — see README "Chunking decisions" for why these numbers
    chunk_tokens: int = 512
    chunk_overlap_tokens: int = 64

    # retrieval
    top_k: int = 5
    candidate_k: int = 30
    hybrid_alpha: float = 0.6
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # answering
    openai_api_key: str | None = None
    answer_model: str = "gpt-4o-mini"


@lru_cache
def settings() -> Settings:
    return Settings()
