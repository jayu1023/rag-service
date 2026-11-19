import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    """Point every test at a throwaway embedded Qdrant, never the dev index."""
    path = tmp_path_factory.mktemp("qdrant")
    os.environ["QDRANT_PATH"] = str(path)
    os.environ["QDRANT_COLLECTION"] = "test_documents"
    os.environ["VECTOR_BACKEND"] = "qdrant"
    os.environ.pop("QDRANT_URL", None)
    os.environ.pop("OPENAI_API_KEY", None)

    from app import config, embed, retrieve

    config.settings.cache_clear()
    embed.store.cache_clear()
    retrieve.bm25.cache_clear()
    yield


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    return ROOT / "data" / "corpus"
