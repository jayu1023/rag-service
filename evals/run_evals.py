"""Retrieval + answer evaluation over evals/questions.yaml.

Run:
    python evals/run_evals.py                      # default config
    python evals/run_evals.py --sweep              # chunk-size / retrieval ablation
    python evals/run_evals.py --mlflow             # also log to MLflow

What is measured, and what each number is honestly worth:

  hit@1/3/5    fraction of questions where the gold document appears in the top-n
               returned chunks. hit@5 saturates on a 22-document corpus, so hit@1
               is the number that actually moves -- see README "What the numbers
               are worth".
  mrr@k        1/rank of the first gold chunk, averaged. Rewards ranking, not just
               presence -- the metric that actually moves when you add a re-ranker.
  recall@cand  same as hit_rate but over the pre-rerank candidate set. This is the
               ceiling: a re-ranker can never recover a document retrieval missed.
  kw_match     fraction of questions whose generated answer contains the expected
               keywords. Objective, but only covers answers with a hard fact in them.
  faithful     lexical-overlap proxy: share of content words in the answer that also
               appear in the retrieved context. It catches an answer drifting off the
               sources. It does NOT catch a fluent wrong answer assembled from
               correct words -- that needs an LLM judge or human labels, which is
               exactly why it is reported as a proxy and not as "faithfulness".

Labels here are gold *documents*, not gold chunks, so hit-rate is forgiving by
design: any chunk of the right document counts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "data" / "corpus"
QUESTIONS = Path(__file__).parent / "questions.yaml"

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "to", "was", "were",
    "with", "what", "which", "who", "how", "when", "why", "does", "do", "not", "no",
    "if", "any", "this", "there", "than", "then", "after", "before", "must", "may",
}


@dataclass
class Config:
    name: str
    chunk_tokens: int = 512
    chunk_overlap_tokens: int = 64
    hybrid: bool = True
    rerank: bool = True
    hybrid_alpha: float = 0.6
    candidate_k: int = 30
    top_k: int = 5


@dataclass
class Result:
    config: str
    n: int
    hit_1: float
    hit_3: float
    hit_rate: float
    mrr: float
    recall_candidates: float
    kw_match: float
    faithful: float
    p50_latency_ms: float
    chunks_indexed: int
    per_question: list[dict] = field(default_factory=list)


def load_questions() -> list[dict]:
    import yaml

    data = yaml.safe_load(QUESTIONS.read_text())
    return data["questions"]


def apply_config(cfg: Config, workdir: Path) -> None:
    """Rebuild the whole app state under a given config.

    Env is mutated and every lru_cache in the app is dropped, because chunk size
    changes what is in the index -- reusing a warm store across configs would
    silently compare a new query path against an old index.
    """
    os.environ["CHUNK_TOKENS"] = str(cfg.chunk_tokens)
    os.environ["CHUNK_OVERLAP_TOKENS"] = str(cfg.chunk_overlap_tokens)
    os.environ["HYBRID_ALPHA"] = str(cfg.hybrid_alpha)
    os.environ["CANDIDATE_K"] = str(cfg.candidate_k)
    os.environ["TOP_K"] = str(cfg.top_k)
    os.environ["RERANK_ENABLED"] = "true" if cfg.rerank else "false"
    os.environ["QDRANT_PATH"] = str(workdir / f"qdrant-{cfg.name}")
    os.environ["QDRANT_COLLECTION"] = f"eval_{cfg.name}"

    from app import config as config_mod
    from app import embed as embed_mod
    from app import retrieve as retrieve_mod

    config_mod.settings.cache_clear()
    embed_mod.store.cache_clear()
    retrieve_mod.bm25.cache_clear()


def index_corpus() -> int:
    from app.embed import embed_and_upsert, store
    from app.ingest import chunk_file, iter_files
    from app.retrieve import refresh_bm25

    store().ensure(reset=True)
    total = 0
    for path in iter_files([str(CORPUS)]):
        total += embed_and_upsert(chunk_file(path))
    refresh_bm25()
    return total


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9.\-]{2,}", text.lower()) if w not in STOPWORDS}


def faithfulness_proxy(answer: str, context: str) -> float:
    answer_words = content_words(answer)
    if not answer_words:
        return 0.0
    context_words = content_words(context)
    return len(answer_words & context_words) / len(answer_words)


def evaluate(cfg: Config, questions: list[dict], workdir: Path) -> Result:
    apply_config(cfg, workdir)
    chunks_indexed = index_corpus()

    from app.answer import answer_sync, build_context
    from app.retrieve import retrieve

    hits_at_1: list[int] = []
    hits_at_3: list[int] = []
    hits_at_k: list[int] = []
    reciprocal_ranks: list[float] = []
    recall_candidates: list[int] = []
    kw_matches: list[int] = []
    faithfuls: list[float] = []
    latencies: list[float] = []
    rows: list[dict] = []

    for q in questions:
        gold = q["source"]
        started = time.perf_counter()

        # Candidate-set recall measured without the re-ranker: it is the ceiling.
        candidates = retrieve(
            q["question"], top_k=cfg.candidate_k, hybrid=cfg.hybrid, use_rerank=False
        )
        ranked = retrieve(
            q["question"], top_k=cfg.top_k, hybrid=cfg.hybrid, use_rerank=cfg.rerank
        )
        latencies.append((time.perf_counter() - started) * 1000)

        def is_gold(hit) -> bool:
            return Path(hit.chunk.source).name == gold

        rank = next((i for i, h in enumerate(ranked) if is_gold(h)), None)
        hits_at_1.append(int(rank == 0))
        hits_at_3.append(int(rank is not None and rank < 3))
        hits_at_k.append(int(rank is not None))
        reciprocal_ranks.append(1.0 / (rank + 1) if rank is not None else 0.0)
        recall_candidates.append(int(any(is_gold(h) for h in candidates)))

        answer, citations = answer_sync(
            q["question"], top_k=cfg.top_k, hybrid=cfg.hybrid, use_rerank=cfg.rerank
        )
        context, _ = build_context(ranked)
        keywords = q.get("answer_keywords") or []
        kw_hit = int(any(str(k).lower() in answer.lower() for k in keywords)) if keywords else 0
        kw_matches.append(kw_hit)
        faithfuls.append(faithfulness_proxy(answer, context))

        rows.append(
            {
                "id": q["id"],
                "kind": q.get("kind", "-"),
                "gold": gold,
                "rank": (rank + 1) if rank is not None else None,
                "in_candidates": bool(recall_candidates[-1]),
                "kw_match": bool(kw_hit),
                "top_source": Path(ranked[0].chunk.source).name if ranked else None,
                "citations": [c.source for c in citations],
            }
        )

    n = len(questions)
    return Result(
        config=cfg.name,
        n=n,
        hit_1=sum(hits_at_1) / n,
        hit_3=sum(hits_at_3) / n,
        hit_rate=sum(hits_at_k) / n,
        mrr=sum(reciprocal_ranks) / n,
        recall_candidates=sum(recall_candidates) / n,
        kw_match=sum(kw_matches) / n,
        faithful=statistics.mean(faithfuls) if faithfuls else 0.0,
        p50_latency_ms=statistics.median(latencies),
        chunks_indexed=chunks_indexed,
        per_question=rows,
    )


def print_table(results: list[Result], top_k: int) -> None:
    header = (
        f"{'config':<22}{'chunks':>7}{'  hit@1':>8}{'  hit@3':>8}{f'  hit@{top_k}':>8}"
        f"{f'  mrr@{top_k}':>9}{'  recall@cand':>13}{'  kw_match':>10}{'  faith':>8}{'  p50_ms':>9}"
    )
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.config:<22}{r.chunks_indexed:>7}{r.hit_1:>8.2f}{r.hit_3:>8.2f}"
            f"{r.hit_rate:>8.2f}{r.mrr:>9.3f}{r.recall_candidates:>13.2f}"
            f"{r.kw_match:>10.2f}{r.faithful:>8.2f}{r.p50_latency_ms:>9.0f}"
        )
    print()


def print_misses(result: Result) -> None:
    misses = [r for r in result.per_question if r["rank"] != 1]
    if not misses:
        print(f"[{result.config}] gold document ranked first on every question")
        return
    print(f"[{result.config}] gold not ranked first ({len(misses)}/{result.n}):")
    for row in misses:
        rank = row["rank"] if row["rank"] is not None else "miss"
        print(
            f"  {row['id']:<4} ({row['kind']:<8}) rank={rank:<5} wanted {row['gold']:<28} "
            f"top was {row['top_source']}"
        )
    print()


SWEEP = [
    Config("chunk512_hybrid_rr"),
    Config("chunk512_dense_rr", hybrid=False),
    Config("chunk512_hybrid_norr", rerank=False),
    Config("chunk192_hybrid_rr", chunk_tokens=192, chunk_overlap_tokens=32),
    Config("chunk192_dense_norr", chunk_tokens=192, chunk_overlap_tokens=32, hybrid=False, rerank=False),
    Config("chunk192_hybrid_norr", chunk_tokens=192, chunk_overlap_tokens=32, rerank=False),
    Config("chunk1024_hybrid_rr", chunk_tokens=1024, chunk_overlap_tokens=128),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", action="store_true", help="run the full ablation")
    parser.add_argument("--mlflow", action="store_true", help="log runs to MLflow")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    questions = load_questions()
    workdir = ROOT / "data" / "evalruns"
    workdir.mkdir(parents=True, exist_ok=True)

    configs = SWEEP if args.sweep else [Config("default", top_k=args.top_k)]
    for cfg in configs:
        cfg.top_k = args.top_k

    results: list[Result] = []
    for cfg in configs:
        print(f"==> {cfg.name}", flush=True)
        results.append(evaluate(cfg, questions, workdir))

    print_table(results, args.top_k)
    for r in results:
        print_misses(r)

    if args.json_out:
        args.json_out.write_text(
            json.dumps([r.__dict__ for r in results], indent=2, default=str)
        )
        print(f"wrote {args.json_out}")

    if args.mlflow:
        import mlflow

        mlflow.set_experiment("rag-service-retrieval")
        for cfg, r in zip(configs, results):
            with mlflow.start_run(run_name=cfg.name):
                mlflow.log_params(cfg.__dict__)
                mlflow.log_metrics(
                    {
                        "hit_rate_at_1": r.hit_1,
                        "hit_rate_at_3": r.hit_3,
                        f"hit_rate_at_{args.top_k}": r.hit_rate,
                        f"mrr_at_{args.top_k}": r.mrr,
                        "recall_at_candidates": r.recall_candidates,
                        "kw_match": r.kw_match,
                        "faithfulness_proxy": r.faithful,
                        "p50_latency_ms": r.p50_latency_ms,
                        "chunks_indexed": r.chunks_indexed,
                    }
                )
        print("logged to MLflow (./mlruns)")

    # Non-zero exit if the headline metric collapses, so this can gate CI.
    # hit@1, not hit@5: hit@5 cannot regress on a corpus this small.
    return 0 if results[0].hit_1 >= 0.6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
