#!/usr/bin/env python
"""Render the MLflow run history as a table for the README.

    python evals/run_evals.py --sweep --mlflow     # produce the runs
    python evals/mlflow_history.py                 # render them
    python evals/mlflow_history.py --write         # also write docs/METRICS.md

Why a rendered table and not a screenshot of the MLflow UI: it is diffable, it
needs no image host, and anyone can regenerate it and check it matches. The
point of logging to MLflow is that a metric *history* exists and a regression
is visible across runs -- a screenshot shows one moment and proves nothing
about the history.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COLUMNS = [
    ("hit_rate_at_1", "hit@1"),
    ("hit_rate_at_3", "hit@3"),
    ("hit_rate_at_5", "hit@5"),
    ("mrr_at_5", "MRR@5"),
    ("recall_at_candidates", "recall@cand"),
    ("faithfulness_proxy", "faithful"),
    ("p50_latency_ms", "p50 ms"),
    ("chunks_indexed", "chunks"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="rag-service-retrieval")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    import mlflow

    mlflow.set_tracking_uri(f"file://{ROOT / 'mlruns'}")
    experiment = mlflow.get_experiment_by_name(args.experiment)
    if experiment is None:
        raise SystemExit(
            f"no MLflow experiment {args.experiment!r} — "
            "run: python evals/run_evals.py --sweep --mlflow"
        )

    runs = mlflow.search_runs(
        experiment_ids=[experiment.experiment_id], order_by=["attributes.start_time ASC"]
    )
    if runs.empty:
        raise SystemExit("experiment exists but has no runs")

    header = f"| {'run':<22} | " + " | ".join(f"{label:>11}" for _, label in COLUMNS) + " |"
    divider = f"|{'-' * 24}|" + "|".join("-" * 13 for _ in COLUMNS) + "|"
    lines = [header, divider]

    for _, row in runs.iterrows():
        name = str(row.get("tags.mlflow.runName", "?"))[:22]
        cells = []
        for key, _ in COLUMNS:
            value = row.get(f"metrics.{key}")
            if value is None or value != value:  # NaN
                cells.append(f"{'—':>11}")
            elif key in {"p50_latency_ms", "chunks_indexed"}:
                cells.append(f"{value:>11.0f}")
            else:
                cells.append(f"{value:>11.3f}")
        lines.append(f"| {name:<22} | " + " | ".join(cells) + " |")

    table = "\n".join(lines)
    print(f"experiment: {args.experiment}   runs: {len(runs)}\n")
    print(table)

    if args.write:
        target = ROOT / "docs" / "METRICS.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# MLflow metric history\n\n"
            "Every eval run logs its parameters and metrics to MLflow, so a regression is\n"
            "visible across runs rather than only in the last console output.\n\n"
            "Regenerate with:\n\n"
            "```bash\n"
            "python evals/run_evals.py --sweep --mlflow\n"
            "python evals/mlflow_history.py --write\n"
            "```\n\n"
            f"`{args.experiment}` — {len(runs)} runs:\n\n"
            "```\n" + table + "\n```\n\n"
            "Browse it interactively with `mlflow ui --backend-store-uri ./mlruns`.\n"
        )
        print(f"\nwrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
