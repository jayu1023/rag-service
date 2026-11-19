VENV ?= .venv
PY   := $(VENV)/bin/python

.PHONY: help venv install dev evals sweep test fmt up down ingest ask clean

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

test: ## unit + api tests
	$(PY) -m pytest

up: ## docker compose up (api + qdrant + postgres)
	docker compose up --build

down:
	docker compose down -v

clean:
	rm -rf data/qdrant data/evalruns data/sweep.json .pytest_cache mlruns
