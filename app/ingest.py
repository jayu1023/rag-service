"""Loading + chunking.

Chunking is token-based, not character-based, because the downstream budget that
actually matters (embedding model max_seq_len, LLM context) is counted in tokens.
Splitting on characters makes chunk size drift with language and code density --
Gujarati text and JSON blobs tokenize very differently per character.

Strategy: split on paragraph boundaries first, then pack paragraphs into
token-bounded windows with overlap. Overlap is carried as whole trailing
sentences so a chunk never starts mid-sentence.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import tiktoken

from .config import settings
from .models import Chunk

SUPPORTED = {".md", ".txt", ".pdf"}
_ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def load_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    return path.read_text(encoding="utf-8", errors="replace")


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _overlap_tail(text: str, budget: int) -> str:
    """Last whole sentences of `text` fitting in `budget` tokens."""
    if budget <= 0:
        return ""
    sentences = _SENT_SPLIT.split(text)
    tail: list[str] = []
    used = 0
    for sentence in reversed(sentences):
        cost = count_tokens(sentence)
        if used + cost > budget:
            break
        tail.insert(0, sentence)
        used += cost
    return " ".join(tail)


def _hard_split(block: str, limit: int) -> list[str]:
    """Split a single oversized block on token boundaries (last resort)."""
    ids = _ENC.encode(block)
    return [_ENC.decode(ids[i : i + limit]) for i in range(0, len(ids), limit)]


def chunk_text(
    text: str,
    *,
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[str]:
    cfg = settings()
    max_tokens = max_tokens or cfg.chunk_tokens
    overlap_tokens = cfg.chunk_overlap_tokens if overlap_tokens is None else overlap_tokens
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    blocks: list[str] = []
    for raw in normalize(text).split("\n\n"):
        block = raw.strip()
        if not block:
            continue
        if count_tokens(block) > max_tokens:
            blocks.extend(_hard_split(block, max_tokens))
        else:
            blocks.append(block)

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for block in blocks:
        cost = count_tokens(block)
        if current and current_tokens + cost > max_tokens:
            body = "\n\n".join(current)
            chunks.append(body)
            carry = _overlap_tail(body, overlap_tokens)
            current = [carry] if carry else []
            current_tokens = count_tokens(carry) if carry else 0
        current.append(block)
        current_tokens += cost

    if current:
        body = "\n\n".join(current).strip()
        if body:
            chunks.append(body)
    return chunks


def doc_id_for(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16]


def chunk_id_for(doc_id: str, ordinal: int) -> str:
    return f"{doc_id}:{ordinal}"


def iter_files(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED))
        elif p.is_file():
            found.append(p)
    return found


def chunk_file(path: Path) -> list[Chunk]:
    doc_id = doc_id_for(path)
    body = load_text(path)
    out: list[Chunk] = []
    for ordinal, piece in enumerate(chunk_text(body)):
        out.append(
            Chunk(
                id=chunk_id_for(doc_id, ordinal),
                doc_id=doc_id,
                source=str(path),
                ordinal=ordinal,
                text=piece,
                token_count=count_tokens(piece),
            )
        )
    return out
