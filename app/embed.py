"""Embedding + the vector-store protocol with two backends.

Two backends exist because they answer different questions in an interview:
Qdrant is what you reach for when retrieval is the product (HNSW tuning, payload
filters, quantisation); pgvector is what you reach for when the vectors are one
column of an existing relational product and you do not want a second datastore.
The protocol keeps the rest of the app from caring.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Protocol

from .config import settings
from .models import Chunk

BATCH = 64


# --------------------------------------------------------------------------- #
# embedders
# --------------------------------------------------------------------------- #
class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]: ...


class LocalEmbedder:
    """sentence-transformers. Default so the repo runs with no API key."""

    def __init__(self, model_name: str, dim: int) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = dim

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=BATCH,
            normalize_embeddings=True,  # cosine == dot product once normalised
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]


class OpenAIEmbedder:
    def __init__(self, model_name: str, dim: int, api_key: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model_name
        self.dim = dim

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            resp = self._client.embeddings.create(model=self._model, input=texts[i : i + BATCH])
            out.extend(d.embedding for d in resp.data)
        return out


@lru_cache
def embedder() -> Embedder:
    cfg = settings()
    if cfg.embed_provider == "openai":
        if not cfg.openai_api_key:
            raise RuntimeError("EMBED_PROVIDER=openai but OPENAI_API_KEY is empty")
        return OpenAIEmbedder(cfg.embed_model, cfg.embed_dim, cfg.openai_api_key)
    return LocalEmbedder(cfg.embed_model, cfg.embed_dim)


# --------------------------------------------------------------------------- #
# vector stores
# --------------------------------------------------------------------------- #
class VectorStore(Protocol):
    def ensure(self, *, reset: bool = False) -> None: ...
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(self, vector: list[float], limit: int) -> list[tuple[Chunk, float]]: ...
    def all_chunks(self) -> list[Chunk]: ...
    def count(self) -> int: ...


def _uuid_for(chunk_id: str) -> str:
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class QdrantStore:
    def __init__(self) -> None:
        from qdrant_client import QdrantClient

        cfg = settings()
        # Embedded mode by default: `git clone && make evals` must work with no Docker.
        self._client = (
            QdrantClient(url=cfg.qdrant_url) if cfg.qdrant_url else QdrantClient(path=cfg.qdrant_path)
        )
        self._name = cfg.qdrant_collection
        self._dim = cfg.embed_dim

    def ensure(self, *, reset: bool = False) -> None:
        from qdrant_client.models import Distance, HnswConfigDiff, VectorParams

        exists = self._client.collection_exists(self._name)
        if exists and reset:
            self._client.delete_collection(self._name)
            exists = False
        if not exists:
            self._client.create_collection(
                collection_name=self._name,
                vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
                # m=16 / ef_construct=128 are Qdrant defaults; stated explicitly so the
                # recall-vs-build-cost trade-off is a visible decision, not a default.
                hnsw_config=HnswConfigDiff(m=16, ef_construct=128),
            )

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(id=_uuid_for(c.id), vector=v, payload=c.model_dump())
            for c, v in zip(chunks, vectors)
        ]
        for i in range(0, len(points), 256):
            self._client.upsert(collection_name=self._name, points=points[i : i + 256])

    def search(self, vector: list[float], limit: int) -> list[tuple[Chunk, float]]:
        res = self._client.query_points(
            collection_name=self._name, query=vector, limit=limit, with_payload=True
        ).points
        return [(Chunk(**p.payload), float(p.score)) for p in res]

    def all_chunks(self) -> list[Chunk]:
        out: list[Chunk] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._name, limit=512, offset=offset, with_payload=True
            )
            out.extend(Chunk(**p.payload) for p in points)
            if offset is None:
                break
        return out

    def count(self) -> int:
        return self._client.count(collection_name=self._name).count


class PgVectorStore:
    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS chunks (
        id           TEXT PRIMARY KEY,
        doc_id       TEXT NOT NULL,
        source       TEXT NOT NULL,
        ordinal      INT  NOT NULL,
        text         TEXT NOT NULL,
        token_count  INT  NOT NULL,
        embedding    VECTOR(%(dim)s) NOT NULL
    );
    CREATE INDEX IF NOT EXISTS chunks_embedding_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 128);
    CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON chunks (doc_id);
    """

    def __init__(self) -> None:
        import psycopg
        from pgvector.psycopg import register_vector

        cfg = settings()
        self._conn = psycopg.connect(cfg.postgres_dsn, autocommit=True)
        register_vector(self._conn)
        self._dim = cfg.embed_dim

    def ensure(self, *, reset: bool = False) -> None:
        with self._conn.cursor() as cur:
            if reset:
                cur.execute("DROP TABLE IF EXISTS chunks")
            cur.execute(self.DDL % {"dim": self._dim})

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        import numpy as np

        rows = [
            (c.id, c.doc_id, c.source, c.ordinal, c.text, c.token_count, np.array(v, dtype=np.float32))
            for c, v in zip(chunks, vectors)
        ]
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (id, doc_id, source, ordinal, text, token_count, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    text = EXCLUDED.text,
                    token_count = EXCLUDED.token_count,
                    embedding = EXCLUDED.embedding
                """,
                rows,
            )

    def search(self, vector: list[float], limit: int) -> list[tuple[Chunk, float]]:
        import numpy as np

        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, doc_id, source, ordinal, text, token_count,
                       1 - (embedding <=> %s) AS score
                FROM chunks
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (np.array(vector, dtype=np.float32), np.array(vector, dtype=np.float32), limit),
            )
            return [
                (
                    Chunk(id=r[0], doc_id=r[1], source=r[2], ordinal=r[3], text=r[4], token_count=r[5]),
                    float(r[6]),
                )
                for r in cur.fetchall()
            ]

    def all_chunks(self) -> list[Chunk]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT id, doc_id, source, ordinal, text, token_count FROM chunks")
            return [
                Chunk(id=r[0], doc_id=r[1], source=r[2], ordinal=r[3], text=r[4], token_count=r[5])
                for r in cur.fetchall()
            ]

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks")
            return int(cur.fetchone()[0])


@lru_cache
def store() -> VectorStore:
    return PgVectorStore() if settings().vector_backend == "pgvector" else QdrantStore()


def embed_and_upsert(chunks: Iterable[Chunk]) -> int:
    chunks = list(chunks)
    if not chunks:
        return 0
    vectors = embedder().encode([c.text for c in chunks])
    store().upsert(chunks, vectors)
    return len(chunks)
