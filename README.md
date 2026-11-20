# RAG Document Intelligence Service

A retrieval-augmented question-answering service over your own documents. FastAPI,
hybrid retrieval (dense + BM25 fused by RRF), cross-encoder re-ranking, streamed
answers with inline citations, and a reproducible evaluation harness that will fail
CI if retrieval quality regresses.

It runs with **no Docker, no API key and no GPU** — `make install && make evals`
indexes the bundled corpus into an embedded Qdrant and prints the metric table
below. `docker compose up` gives you the production shape (Qdrant server +
Postgres/pgvector).

**Docs:** [`docs/EXPLAINER.md`](docs/EXPLAINER.md) — how every piece works and why, from
first principles. [`docs/INTERVIEW_GUIDE.md`](docs/INTERVIEW_GUIDE.md) — how to present
and defend these decisions. [`docs/TRACE.md`](docs/TRACE.md) — a real captured span tree.
[`docs/METRICS.md`](docs/METRICS.md) — the MLflow run history.

---

## Architecture

```
                    ┌─────────────────────────────────────────────┐
   POST /ingest ───▶│ ingest.py                                   │
                    │  load (.pdf/.md/.txt) → normalize →         │
                    │  token-based chunker (512 / 64 overlap)     │
                    └───────────────┬─────────────────────────────┘
                                    │ chunks
                    ┌───────────────▼─────────────────────────────┐
                    │ embed.py                                    │
                    │  all-MiniLM-L6-v2 (384-d, normalized)       │
                    │  ──▶ VectorStore protocol                   │
                    │        ├── QdrantStore   (HNSW m=16, ef=128)│
                    │        └── PgVectorStore (hnsw cosine)      │
                    └───────────────┬─────────────────────────────┘
                                    │                 ┌──────────────────┐
                                    └────────────────▶│ BM25 index       │
                                                      │ (rank_bm25)      │
                                                      └──────────────────┘

   POST /ask     ───▶ retrieve.py
                        ├─ dense search      → top 30 candidates
                        ├─ BM25 search       → top 30 candidates
                        ├─ weighted RRF fusion (alpha = 0.6 on dense)
                        └─ cross-encoder rerank (ms-marco-MiniLM-L-6-v2) → top 5
                            │
                      answer.py
                        ├─ token-budgeted context assembly (2400 tokens)
                        ├─ numbered sources → inline [n] citations
                        └─ SSE: `sources` event, then `token`*, then `done`
```

| File | Responsibility |
|---|---|
| `app/config.py` | every tunable, env-overridable, one place |
| `app/ingest.py` | loading, normalization, token-based chunking with sentence-aligned overlap |
| `app/embed.py` | embedders (local / OpenAI) + the `VectorStore` protocol and its two backends |
| `app/retrieve.py` | BM25 index, RRF fusion, cross-encoder re-ranking |
| `app/answer.py` | prompt assembly, context budgeting, SSE streaming, extractive fallback |
| `app/main.py` | `POST /ingest`, `POST /ask` (SSE), `POST /ask/sync`, `GET /health` |
| `evals/run_evals.py` | hit@k, MRR, candidate recall, keyword match, faithfulness proxy + ablation sweep |
| `app/tracing.py` | OpenTelemetry spans; file / OTLP exporters, off by default |
| `app/trace_tree.py` | renders a JSONL trace as the span tree in `docs/TRACE.md` |
| `evals/mlflow_history.py` | renders the MLflow run history into `docs/METRICS.md` |
| `evals/wandb_check.py` | verifies the W&B offline runs really contain the metrics |
| `evals/langsmith_check.py` | one-shot LangSmith OTLP check — needs your own api key |

---

## Quick start

```bash
make venv install          # python 3.12 venv (uses uv), installs deps
make evals                 # index the bundled corpus, print the metric table
make test                  # 25 unit + API tests

make dev                   # uvicorn on :8000
make ingest                # POST /ingest for data/corpus
make ask Q="What is the backend production rollback target?"
```

With Docker:

```bash
docker compose up --build  # api :8000, qdrant :6333, postgres/pgvector :5432
```

Set `OPENAI_API_KEY` in `.env` for LLM-generated answers. Without it the service
still answers — it returns the retrieved passages verbatim with their citation
markers, and says so. That keeps a clone of this repo demoable at zero cost, and
makes the degraded path explicit instead of a 500.

---

## Decisions, and why

### Chunking: 512 tokens, 64-token overlap, token-based

**Token-based, not character-based.** Every budget downstream is counted in tokens —
the embedding model's `max_seq_len`, the LLM's context window, the bill. Characters
per token swing wildly between English prose, Gujarati text and JSON blobs, so a
character-sized chunk silently changes size with the content.

**512 is a ceiling, not a target.** The chunker splits on paragraph boundaries and
*packs* paragraphs up to 512 tokens. A short document is one chunk; it is never padded
or split mid-thought. This is why the 22-document corpus below produces exactly 22
chunks at 512 and 51 at 192 — the number of chunks is a property of the documents, not
of the setting.

**Why not smaller?** A chunk has to carry enough context for the embedding to mean
something. "Promotion is halted if the crash-free rate drops below 99.5%" is useless
in isolation — halted for *what*? The paragraph above it carries "Android releases go
out at 5%…", and that is the unit a question actually matches.

**Why not larger?** Two costs. A single embedding vector averages everything in the
chunk, so a 2000-token chunk's vector is a blur — one relevant sentence gets diluted
by nineteen irrelevant ones. And retrieval precision becomes prompt cost: at top-5,
1024-token chunks mean ~5k tokens of context, most of it unread.

**What breaks if you double it to 1024?** On this corpus, measurably nothing (see the
sweep: identical metrics) — because these documents are *already* under 512 tokens, so
both settings produce one chunk per document. That is the honest answer, and it is the
reason the sweep is in the repo: the number you should ship depends on your document
length distribution, so measure it rather than copy it. On long PDFs the picture
inverts and 1024 starts losing precision.

**Overlap is 64 tokens, carried as whole trailing sentences.** Fixed-window overlap
cuts mid-sentence and produces chunks that start with half a clause, which embeds
badly. `_overlap_tail()` walks back sentence by sentence until the budget is spent.
Overlap exists for one reason: a fact that straddles a boundary should be fully present
in at least one chunk.

### Retrieval: dense + BM25, fused by weighted RRF

Cosine similarity lives in `[-1, 1]`. BM25 is an unbounded, corpus-dependent sum. Add
them and your blend weight silently changes meaning as the corpus grows. **RRF consumes
only ranks**, so `HYBRID_ALPHA=0.6` means exactly "dense gets 60% of the vote" and keeps
meaning that at 10x the documents.

The cost of RRF is that it discards score *margins* — a runaway top hit and a photo
finish look the same. That is precisely why the cross-encoder runs afterwards: RRF
decides the candidate set, the cross-encoder decides the order.

**When does BM25 still win?** Exact identifiers, error codes, rare proper nouns, and
anything the user typed verbatim from the document — `events.raw`, `max_memory_usage`,
a ticket ID. Dense embeddings map those to a vague neighbourhood; BM25 matches the
token. It also wins on brand-new vocabulary the embedding model never saw in training.

**On this corpus, BM25 adds almost nothing** (MRR 0.950 hybrid vs 0.942 dense-only).
Reported as measured, not inflated. The reason is that the questions were written as
paraphrases, which is dense retrieval's home turf. Keeping the lexical half is a bet
about production traffic, not a win this eval demonstrates.

### Re-ranking: over-fetch 30, re-rank, return 5

A bi-encoder embeds the query and the document *separately* — the two never see each
other. A cross-encoder reads `(query, chunk)` as one sequence with full attention
across both, which is strictly more informative and strictly more expensive (it cannot
be precomputed or indexed). So: use the cheap one to narrow 51 chunks to 30, use the
expensive one to order those 30.

`CANDIDATE_K=30` is the real ceiling on quality. **A re-ranker can only reorder what
retrieval already found** — this is why the eval reports `recall@cand` separately. If
candidate recall is 0.80, no re-ranker in the world gets you past hit@5 = 0.80.

### Vector store: two backends behind one protocol

Qdrant when retrieval *is* the product — payload filtering, quantization, explicit
HNSW control. pgvector when the vectors are one column of a system that already has a
Postgres, and a second datastore is not worth the operational surface.

HNSW is set explicitly to `m=16, ef_construct=128` in both. Those are the defaults, but
they are written down so the trade-off is a visible decision: `m` is edges per node
(memory and recall up, build and query cost up), `ef_construct` is the candidate list
size during build (recall up, index build time up, query cost unchanged). HNSW buys
low latency at high memory; IVF buys low memory at the cost of needing a trained
centroid set and a tuned `nprobe`.

### Answering

Context is budgeted in **tokens, not chunks**. "Top 5" with variable chunk sizes is how
prompts overflow in production. `sources` is emitted on the SSE stream *before* the
first token, so the client can render citation chips while generation is still running
— and a user can still see what the answer was grounded in if generation dies midway.

---

## Evaluation

```bash
make evals     # default config
make sweep     # full ablation, writes data/sweep.json

python evals/run_evals.py --mlflow   # also log params + metrics to ./mlruns
```

The corpus is 22 documents of a fictional company handbook (`data/corpus/`). It is
fictional on purpose: a model cannot answer from pretraining, so the eval measures
*retrieval*, not recall of public facts. Eight of the documents are deliberate
**near-twins** — `02-deployment` vs `13-mobile-release-policy`, `05-data-retention` vs
`16-warehouse-retention`, `03-oncall` vs `14-incident-comms`, and five more pairs. They
answer the same question differently, so retrieving the wrong one of a pair is a
plausible, scored failure rather than something the eval cannot see.

### Measured results — 20 questions, 22 documents

| config | chunks | hit@1 | hit@3 | hit@5 | MRR@5 | recall@cand | kw_match | faithful | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| 512 tok, hybrid, **+rerank** | 22 | **0.95** | 1.00 | 1.00 | **0.967** | 1.00 | 0.70 | 0.97 | 143 |
| 512 tok, dense only, +rerank | 22 | 0.95 | 1.00 | 1.00 | 0.967 | 1.00 | 0.70 | 0.97 | 145 |
| 512 tok, hybrid, **−rerank** | 22 | 0.90 | 1.00 | 1.00 | 0.950 | 1.00 | 0.70 | 0.96 | **9** |
| 192 tok, hybrid, +rerank | 51 | 0.95 | 1.00 | 1.00 | 0.975 | 1.00 | 1.00 | 0.96 | 109 |
| 192 tok, hybrid, −rerank | 51 | 0.90 | 1.00 | 1.00 | 0.950 | 1.00 | 1.00 | 0.96 | 10 |
| 192 tok, dense only, −rerank | 51 | 0.90 | 1.00 | 1.00 | 0.942 | 1.00 | 1.00 | 0.96 | 9 |
| 1024 tok, hybrid, +rerank | 22 | 0.95 | 1.00 | 1.00 | 0.967 | 1.00 | 0.70 | 0.97 | 146 |

### The one before/after number

**Adding the cross-encoder re-ranker: hit@1 0.90 → 0.95, MRR 0.950 → 0.967, at
p50 9 ms → 143 ms.**

One question in twenty moves to rank 1, and every request gets ~15x slower. At 192
tokens the MRR gain is larger (0.950 → 0.975) because there are more chunks to reorder.
Whether that trade is worth it is a product question, not a retrieval one — which is
why `RERANK_ENABLED` is a flag and `/ask` accepts a per-request `rerank` override.

### What the numbers are worth — and what they are not

Stated plainly, because a metric table with no caveats is a red flag:

- **hit@5 and hit@3 are saturated at 1.00 and measure nothing here.** With 22 documents,
  the gold document is almost always in any top-5. **hit@1 and MRR are the tracked
  metrics**, and the CI gate is on hit@1. A real system needs a corpus two orders of
  magnitude larger before hit@5 carries signal.
- **The labels are gold *documents*, not gold chunks**, so hit-rate is forgiving by
  design: any chunk of the right document counts.
- **`kw_match` 0.70 → 1.00 at the smaller chunk size is an artifact, not a win.** With
  no `OPENAI_API_KEY` the answer path returns the first 600 characters of each retrieved
  chunk; smaller chunks put the target fact inside that window more often. It says
  something about the fallback renderer and nothing about retrieval. Dropped from the
  headline for that reason.
- **`faithful` is a lexical-overlap proxy**, not faithfulness: the share of content words
  in the answer that also appear in the retrieved context. It catches an answer drifting
  off-source. It does **not** catch a fluent, wrong answer assembled from correct words.
  That needs an LLM judge or human labels.
- **Single run, no seeds or confidence intervals.** On 20 questions, one question is
  5 percentage points — the 0.90 → 0.95 difference *is* one question. Treat it as a
  direction, not a measurement.
- **20 questions is a smoke test, not a benchmark.** Its real job is regression
  detection in CI: `evals/run_evals.py` exits non-zero if hit@1 falls below 0.60.

### How you evaluate a RAG system without human labels

Four things that work, roughly in order of cost:

1. **Retrieval has free labels.** Generate a question from each chunk with an LLM, then
   check whether that chunk comes back for its own question. No humans, and it scales to
   the whole corpus.
2. **Negative controls.** Ask questions the corpus provably cannot answer and measure the
   abstention rate. A system that never says "the sources do not answer that" is
   hallucinating, and this catches it with zero labels.
3. **LLM-as-judge for groundedness**, scoring each answer sentence against the retrieved
   context. Cheap, correlates acceptably with human judgement on groundedness
   specifically — much less so on helpfulness. Needs a periodic human audit of the judge.
4. **Production signals.** Citation click-through, follow-up rephrasing rate, thumbs-down
   per thousand answers. Noisy per-event, but it is the only measurement taken on real
   traffic and real intent.

---

## Tracing, metric history and experiment tracking

Two kinds of evidence, both reproducible from the repo — **no screenshots**, because a
screenshot of a trace UI proves only that a screenshot exists. These are diffable, need no
image host, and anyone can regenerate them and check they match.

```bash
make trace      # one traced /ask, rendered as a span tree -> docs/TRACE.md
make metrics    # the MLflow run history as a table       -> docs/METRICS.md
make wandb      # log the sweep to W&B offline, then verify it
make mlflow-ui  # browse the history interactively
make langsmith  # verify the LangSmith export — needs YOUR api key
```

### A real captured trace

Tracing is **off by default** (`TRACE_EXPORTER=none`) — a service that traces whether or not
you asked is a nuisance, and the no-op tracer makes every `with span(...)` free, which is
why no call site needs an `if tracing_enabled` guard. Set `TRACE_EXPORTER=file` for a JSONL
span log, or `otlp` to ship to any collector.

```
rag.ask                  141.61ms 100.0% ████████████████████ llm=False
├─ rag.retrieve             140.30ms  99.1% ████████████████████ returned=5 top_k=5 candidate_k=30 hybrid=True rerank=True top_source=14-incident-comms.md
│  ├─ rag.embed_query            6.57ms   4.6% █                    
│  ├─ rag.search_dense           0.56ms   0.4%                      hits=22 backend=qdrant
│  ├─ rag.search_bm25            0.13ms   0.1%                      hits=22
│  ├─ rag.fuse_rrf               0.18ms   0.1%                      fused_candidates=22 alpha=0.6
│  └─ rag.rerank               132.34ms  93.5% ███████████████████  scored=22 rerank_changed_top=False
├─ rag.build_context          0.88ms   0.6%                      citations=5 context_tokens=1795
└─ rag.answer_extractive      0.06ms   0.0%                      llm=False

9 spans, 141.61ms wall clock
```

**What this is actually good for.** It independently corroborates the eval: `rag.rerank` is
94% of a ~136 ms request, which is the same story as the measured p50 of 143 ms with
re-ranking versus 9 ms without — arrived at by a different route. The
`rerank_changed_top=False` attribute answers "did this step earn its 130 ms on *this*
request?" from the trace alone, without re-running the eval.

Note the models are warmed before the measured call. The first answer pays ~2.5 s loading
the cross-encoder, which would otherwise dominate the tree and make `rag.rerank` look 20x
more expensive than it is in steady state. Cold start is a real thing to measure; it just
is not what this tree is showing.

### Metric history

Every eval run logs parameters and metrics to MLflow, so a regression is visible **across
runs** rather than only in the last console output. `docs/METRICS.md` is the rendered
history; it reproduces the sweep table above from a completely separate code path, which is
a cheap check that neither is lying.

### Weights & Biases — offline, so it is actually verifiable

```bash
python evals/run_evals.py --sweep --wandb   # 7 runs
python evals/wandb_check.py                 # verify them
```

`--wandb` defaults to `WANDB_MODE=offline`, which writes complete run directories to
`./wandb/` with **no account, no API key and no network**. That is the whole reason it is
worth having: anyone who clones this repo can reproduce it. `wandb sync ./wandb` uploads
to a real project later; `WANDB_MODE=online` with a key skips the two-step.

Each run logs the config, every metric, and a **per-question table** — the aggregate is
already in the eval table above, so the miss list is the part that makes a W&B run worth
opening.

An offline run writes to a binary transaction log, not readable JSON, so "the directory
exists" proves nothing. `evals/wandb_check.py` greps the log for every expected metric key
and fails loudly if any is missing. Verified output:

```
7 W&B run(s) under wandb

  offline-run-20261120_132526-x90lqjqa            18251b  ok
  offline-run-20261120_132527-523sz64i            17874b  ok
  offline-run-20261120_132527-57xi0yn3            17911b  ok
  offline-run-20261120_132527-tg7by6k2            17901b  ok
  offline-run-20261120_132527-vhyi7mzi            17884b  ok
  offline-run-20261120_132528-5gtnv2u5            17918b  ok
  offline-run-20261120_132528-bc7vuaxs            17871b  ok

all 7 run(s) contain every expected metric key
```

MLflow and W&B are logged side by side rather than one instead of the other, because they
answer different questions here — MLflow is the local history, W&B is the shareable one —
and both read the same `Result` objects, so they cannot disagree.

### LangSmith — verified by export, 2026-11-20

`TRACE_EXPORTER=otlp` pointed at LangSmith's OTLP endpoint with an `x-api-key` header.
Config is in `.env.example`; `evals/langsmith_check.py` is the one-command check:

```bash
export LANGSMITH_API_KEY=lsv2_...
make langsmith
```

```
PASS: 2/2 export(s) accepted (HTTP 2xx).
```

**Precisely what that verifies:** LangSmith's OTLP collector accepted both spans with a
2xx. That is the integration working — correct endpoint, correct header, correct payload
shape. It does not, by itself, prove anything about how the trace renders in their UI.

The check builds the OTLP exporter directly rather than going through `app.tracing`,
because a span pipeline **swallows export failures by design** — tracing must never break
the request it is tracing — and that is exactly the wrong property for a verification
script. Here the export result is inspected and the exit code reflects it: `0` accepted,
`1` rejected (401/403 = key, 404 = endpoint), `2` no key. A passing run is evidence, not
an absence of complaint.

**Run by the repo owner with their own key, not by the author of the code.** No key is
committed, and `.env` is gitignored. Anyone else wanting to confirm it runs the same
command with their own key — a free account covers 5,000 traces/month.

**So, precisely:** this repo makes *OpenTelemetry, tracing, observability, MLflow,
Weights & Biases and LangSmith* defensible.

---

## API

```bash
# ingest a directory or files
curl -X POST localhost:8000/ingest -H 'content-type: application/json' \
  -d '{"paths":["data/corpus"],"reset":true}'
# -> {"documents":22,"chunks":22,"skipped":[]}

# streamed answer (SSE)
curl -N -X POST localhost:8000/ask -H 'content-type: application/json' \
  -d '{"question":"How often is the status page updated during a Sev-1?"}'
# event: sources
# data: {"citations":[{"n":1,"source":"data/corpus/14-incident-comms.md",...}]}
# event: token
# data: {"text":"Every 30 minutes until resolution [1]..."}
# event: done

# non-streaming twin, for evals and curl
curl -X POST localhost:8000/ask/sync -H 'content-type: application/json' \
  -d '{"question":"...","top_k":5,"hybrid":true,"rerank":true}'

curl localhost:8000/health
# {"status":"ok","backend":"qdrant","embed_model":"...","chunks":22,"rerank":true}
```

Every knob in `.env.example` is settable per request on `/ask` where it makes sense
(`top_k`, `hybrid`, `rerank`), which is what makes the ablation sweep possible without
restarting anything.

---

## Honest status

Built as a working reference implementation, not as a system with production traffic
behind it. Specifically:

- **`docker compose up` is written but has not been run on the author's machine** (no
  Docker installed locally). The Dockerfile builds a two-stage image, bakes the model
  weights in so readiness is not a lie, and runs as a non-root user — but the compose
  path is unverified. The embedded-Qdrant path, the 25 tests and the eval numbers above
  are all verified.
- **The pgvector backend is implemented and unit-reachable but not exercised against a
  live Postgres** for the same reason. The Qdrant backend is what the numbers come from.
- **No LLM in the loop for the reported metrics** — no API key was used. `kw_match` and
  `faithful` describe the extractive fallback path.
- **No auth, no rate limiting, no multi-tenancy.** A real deployment needs all three, and
  tenant-scoped filtering at the vector-store query, not after it.
- **The OTLP path is verified only against LangSmith**, by a single `make langsmith` run
  that both spans were accepted on (HTTP 2xx, 2026-11-20). No other collector — Jaeger,
  Tempo, Honeycomb — has been tried, and the day-to-day exporter here is still `file`.
- **W&B was exercised offline only.** The 7 runs are real and verified, but nothing was
  uploaded to a W&B project — `wandb sync` was never run.
- **BM25 is an in-process index** rebuilt from the store on each ingest. Fine to ~10⁵
  chunks; past that it belongs in the engine that already holds the text (Qdrant sparse
  vectors or Postgres `tsvector`).

## Next

- Qdrant native sparse vectors to retire the in-process BM25 index
- LLM-as-judge groundedness scoring, with a human-audited sample
- Per-tenant payload filtering pushed into the vector query
- Streaming re-rank: emit the first answer token before the whole candidate set is scored

## License

BSD-3-Clause.
