#!/usr/bin/env python
"""Verify the Weights & Biases offline runs actually contain the metrics.

    python evals/run_evals.py --sweep --wandb    # produce the runs
    python evals/wandb_check.py                  # verify them

Why this script exists: an offline W&B run writes its data to a binary
transaction log (`run-*.wandb`), not to readable JSON, so "the directory
exists" is not evidence that anything was logged. This greps the log for the
metric keys and fails loudly if any are missing.

It is also what makes the W&B claim checkable by someone who clones the repo
and has no W&B account: run the eval, run this, see the assertion pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_KEYS = [
    "hit_rate_at_1",
    "hit_rate_at_3",
    "mrr_at_5",
    "recall_at_candidates",
    "faithfulness_proxy",
    "p50_latency_ms",
    "chunks_indexed",
    "per_question",
]


def check(run_dir: Path) -> tuple[bool, list[str]]:
    logs = list(run_dir.glob("*.wandb"))
    if not logs:
        return False, ["no .wandb transaction log in the run directory"]
    raw = logs[0].read_bytes()
    missing = [key for key in EXPECTED_KEYS if key.encode() not in raw]
    return not missing, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=ROOT / "wandb")
    args = parser.parse_args()

    if not args.dir.exists():
        print(f"no {args.dir} — run: python evals/run_evals.py --wandb", file=sys.stderr)
        return 1

    runs = sorted(args.dir.glob("offline-run-*")) + sorted(args.dir.glob("run-*"))
    runs = [r for r in runs if r.is_dir()]
    if not runs:
        print(f"no run directories under {args.dir}", file=sys.stderr)
        return 1

    print(f"{len(runs)} W&B run(s) under {args.dir.relative_to(ROOT)}\n")
    failures = 0
    for run in runs:
        ok, missing = check(run)
        size = sum(f.stat().st_size for f in run.rglob("*") if f.is_file())
        status = "ok" if ok else f"MISSING {missing}"
        print(f"  {run.name:<44} {size:>8}b  {status}")
        failures += 0 if ok else 1

    print()
    if failures:
        print(f"{failures} run(s) missing expected metrics", file=sys.stderr)
        return 1
    print(f"all {len(runs)} run(s) contain every expected metric key")
    print("upload to a real W&B project with: wandb sync ./wandb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
