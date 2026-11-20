# MLflow metric history

Every eval run logs its parameters and metrics to MLflow, so a regression is
visible across runs rather than only in the last console output.

Regenerate with:

```bash
python evals/run_evals.py --sweep --mlflow
python evals/mlflow_history.py --write
```

`rag-service-retrieval` — 7 runs:

```
| run                    |       hit@1 |       hit@3 |       hit@5 |       MRR@5 | recall@cand |    faithful |      p50 ms |      chunks |
|------------------------|-------------|-------------|-------------|-------------|-------------|-------------|-------------|-------------|
| chunk512_hybrid_rr     |       0.950 |       1.000 |       1.000 |       0.967 |       1.000 |       0.965 |         143 |          22 |
| chunk512_dense_rr      |       0.950 |       1.000 |       1.000 |       0.967 |       1.000 |       0.965 |         142 |          22 |
| chunk512_hybrid_norr   |       0.900 |       1.000 |       1.000 |       0.950 |       1.000 |       0.965 |           9 |          22 |
| chunk192_hybrid_rr     |       0.950 |       1.000 |       1.000 |       0.975 |       1.000 |       0.963 |         105 |          51 |
| chunk192_dense_norr    |       0.900 |       1.000 |       1.000 |       0.942 |       1.000 |       0.962 |           9 |          51 |
| chunk192_hybrid_norr   |       0.900 |       1.000 |       1.000 |       0.950 |       1.000 |       0.963 |           9 |          51 |
| chunk1024_hybrid_rr    |       0.950 |       1.000 |       1.000 |       0.967 |       1.000 |       0.965 |         142 |          22 |
```

Browse it interactively with `mlflow ui --backend-store-uri ./mlruns`.
