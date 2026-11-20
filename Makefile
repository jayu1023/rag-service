VENV ?= .venv
PY   := $(VENV)/bin/python

.PHONY: help venv install dev evals sweep test fmt up down ingest ask trace metrics wandb langsmith clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t24

venv: ## create a python 3.12 venv (needs uv)
	uv venv -p 3.12 $(VENV)

install: ## install dev dependencies into the venv
	uv pip install --python $(PY) -r requirements-dev.txt

dev: ## run the api locally with reload (embedded qdrant)
	$(VENV)/bin/uvicorn app.main:app --reload --port 8000

ingest: ## index data/corpus into the local embedded store
	curl -sS -X POST localhost:8000/ingest \
		-H 'content-type: application/json' \
		-d '{"paths":["data/corpus"],"reset":true}' | python3 -m json.tool

ask: ## stream an answer: make ask Q="your question"
	curl -N -X POST localhost:8000/ask \
		-H 'content-type: application/json' \
		-d "$$(python3 -c 'import json,os;print(json.dumps({"question":os.environ["Q"]}))')"

evals: ## retrieval + answer metrics on the default config
	$(PY) evals/run_evals.py

sweep: ## full chunk-size / retrieval ablation
	$(PY) evals/run_evals.py --sweep --json-out data/sweep.json

trace: ## run one traced /ask and render the span tree (writes docs/TRACE.md)
	TRACE_EXPORTER=file $(PY) -m app.trace_tree --demo --write

metrics: ## render the MLflow run history (writes docs/METRICS.md)
	$(PY) evals/mlflow_history.py --write

wandb: ## log the sweep to W&B offline (no account needed) and verify it
	$(PY) evals/run_evals.py --sweep --wandb
	$(PY) evals/wandb_check.py

langsmith: ## verify the LangSmith OTLP export — needs YOUR LANGSMITH_API_KEY
	$(PY) evals/langsmith_check.py

mlflow-ui: ## browse the metric history interactively
	$(VENV)/bin/mlflow ui --backend-store-uri ./mlruns

test: ## unit + api tests
	$(PY) -m pytest

up: ## docker compose up (api + qdrant + postgres)
	docker compose up --build

down:
	docker compose down -v

clean:
	rm -rf data/qdrant data/evalruns data/sweep.json data/trace.jsonl .pytest_cache mlruns wandb
