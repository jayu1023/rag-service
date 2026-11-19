# Explainer — RAG Document Intelligence Service

A plain-language walkthrough of what this project is, what every piece does, and why
each decision went the way it did. If the README is the repo's front door, this is the
guided tour. No prior RAG knowledge assumed.

---

## 1. The problem this solves

An LLM knows what was in its training data. It does not know your company handbook,
your contracts, or last Tuesday's incident report. Three ways to fix that:

| Approach | What it costs | When it is right |
|---|---|---|
| Put everything in the prompt | Hits the context limit; you pay for every token on every request; the model's attention degrades over long contexts | Small, stable document set |
| Fine-tune the model on your documents | Expensive, slow, has to be redone when documents change, and teaches *style* far better than it teaches *facts* | Changing behaviour and format, not injecting knowledge |
| **Retrieval-Augmented Generation (RAG)** | A retrieval system to build and maintain | Large or changing document sets where answers must be **attributable** |

RAG is simple in outline: when a question arrives, **find the few passages most likely
to contain the answer**, put only those in the prompt, and tell the model to answer from
them and cite them. The model does not need to have memorised anything. Update a
document and the answer changes on the next request.

The expensive half of RAG is the retrieval, not the generation. An LLM given the right
three paragraphs will almost always answer well. An LLM given the wrong three paragraphs
will answer confidently and wrongly. **So this project is mostly a retrieval project**,
and that is where all the measurement is pointed.

---

## 2. The two phases

### Phase A — Indexing (`POST /ingest`, offline, slow)

```
document → normalize → chunk → embed → store (+ BM25 index)
```

### Phase B — Answering (`POST /ask`, online, must be fast)

```
question → embed → dense search ─┐
                                  ├─ RRF fuse → re-rank → top 5 → prompt → stream answer + citations
           question → BM25 search ┘
```

Everything in Phase A is paid once per document. Everything in Phase B is paid on every
request. That asymmetry drives most of the design: do expensive work at index time, and
be very careful about what you add to the request path. The cross-encoder re-ranker is
the one deliberate exception, and §7 is about why.

---

## 3. Chunking — `app/ingest.py`

### Why chunk at all?

Two hard reasons. The embedding model has a maximum input length (512 tokens for
MiniLM — longer input is silently truncated, so the tail of a long document would never
be searchable). And retrieval granularity *is* chunk size: if a whole 40-page PDF is one
chunk, "relevant" means "this PDF is relevant", which is not an answer.

### Why tokens and not characters?

A token is roughly 4 characters of English — but roughly 1 character of Gujarati, and
something else again for JSON or code. Every limit downstream (embedding input, LLM
context, the bill) is counted in tokens. Chunk by characters and your chunk size drifts
with the content. `tiktoken` counts the same unit the model counts.

### How this chunker works

1. **Normalize** — line endings, collapse runs of spaces, collapse 3+ newlines to 2
   (paragraph boundaries survive; noise does not).
2. **Split on paragraph boundaries** (`\n\n`). Paragraphs are the author's own semantic
   units — free structure, so use it.
3. **Pack paragraphs** into a chunk until adding the next one would exceed 512 tokens.
4. **When a chunk closes, carry overlap**: take the last whole sentences that fit in 64
   tokens and make them the opening of the next chunk.
5. **A single paragraph over 512 tokens** gets hard-split on token boundaries. Last
   resort, but losing text is worse than an ugly boundary.

Two consequences worth internalising:

- **512 is a ceiling, not a target.** A 200-token document is one 200-token chunk. Nothing
  is padded. This is why the bundled 22-document corpus produces exactly 22 chunks at 512
  — chunk count is a property of the documents.
- **Overlap is sentence-aligned.** Fixed-window overlap cuts mid-clause and produces
  chunks that open with "…below 99.5%, or if the store rating", which embeds to noise.
  `_overlap_tail()` walks backwards sentence by sentence until the 64-token budget is
  spent.

### Why overlap exists

A fact that straddles a boundary would otherwise be half-present in two chunks and
whole in neither. Overlap guarantees it is complete in at least one. The cost is index
size and duplicate hits — ~12% more chunks at 64/512.

### The size trade-off, concretely

**Too small (say 64 tokens):** "Promotion is halted if the crash-free session rate drops
below 99.5%." Halted for *what*? The surrounding paragraph said "Android releases go out
at 5% for 24 hours…". Alone, this chunk matches almost no real question.

**Too large (say 2048 tokens):** one embedding vector has to represent the whole chunk.
It is an average. One relevant sentence among forty gets diluted until the vector points
at a vague topical centroid instead of the fact. And retrieval precision becomes prompt
cost: top-5 × 2048 tokens is ~10k tokens of context per request, most of it never read.

512 with 64 overlap is a defensible default for prose. **The repo ships a sweep instead
of a claim** precisely because the right answer depends on your document length
distribution — and on this corpus, 512 vs 1024 is measurably identical, because every
document already fits in one chunk.

---

## 4. Embeddings — `app/embed.py`

An embedding turns text into a list of numbers (384 of them here) positioned so that
**texts meaning similar things land near each other**. "How do I roll back?" and "What is
the procedure for reverting a release?" share almost no words but land close together.
That is the whole reason dense retrieval beats keyword search on paraphrases.

Default model: `all-MiniLM-L6-v2` — 384 dimensions, ~22M parameters, runs on CPU, no API
key, no per-request cost. A larger model would score better on benchmarks; this one makes
the repo runnable by anyone who clones it, and the architecture is the point, not the
leaderboard. `EMBED_PROVIDER=openai` swaps in OpenAI embeddings via one interface.

Vectors are **normalized to unit length** at encode time, which makes cosine similarity
and dot product the same operation. One less thing to get wrong when switching backends.

### Two storage backends, one protocol

`VectorStore` is a `Protocol` with five methods. Two implementations:

**Qdrant** — purpose-built vector database. Choose it when retrieval *is* the product:
payload filtering, quantization, explicit index control, horizontal scale. Runs embedded
(a local directory, zero infrastructure) or as a server. The repo defaults to embedded so
tests and evals need no Docker.

**pgvector** — a Postgres extension. Choose it when the vectors are one more column on a
system that already has a Postgres, and operating a second datastore is not worth it. You
trade some vector-specific features for transactions, joins and one backup story.

Both configure HNSW explicitly as `m=16, ef_construct=128`:

- **HNSW** is a navigable small-world graph. Search enters at the top layer and greedily
  hops toward the query, descending layers. It is approximate — it can miss a true nearest
  neighbour — and in exchange it is logarithmic instead of linear.
- **`m`** = edges per node. Higher → better recall, more memory, slower build.
- **`ef_construct`** = how many candidates are considered when linking a new node during
  build. Higher → better graph quality and recall, slower build, **no effect on query
  speed**.
- **`ef`** (query time) = candidate list during search. The actual recall/latency dial in
  production.

HNSW's trade is memory for latency: the graph lives in RAM. IVF (inverted file) instead
clusters vectors and searches only the nearest few clusters — much less memory, needs a
*trained* centroid set, and `nprobe` (clusters searched) becomes the recall knob.
Rule of thumb: HNSW when latency matters and the index fits in RAM; IVF when it does not.

---

## 5. Why keyword search did not go away — `app/retrieve.py`

Dense retrieval is weak exactly where it should be strong-looking. Ask for
`max_memory_usage` or error code `E4021` or a customer name the embedding model never saw
in training, and the vector lands in a vague neighbourhood of similar-looking strings.
BM25 just matches the token.

**BM25** scores a document by term overlap with the query, weighting rare terms more
(a term in every document carries no information) and dampening term frequency (ten
occurrences is not ten times as relevant) with a length normalisation so long documents
do not win by default.

So the system runs both. Dense catches paraphrases; BM25 catches exact strings and
unseen vocabulary.

### Fusing them: why RRF and not a weighted score sum

Cosine similarity is bounded in `[-1, 1]`. BM25 is an unbounded sum whose scale depends
on corpus statistics. `0.6 × cosine + 0.4 × bm25` looks principled and is not: as the
corpus grows, BM25's typical magnitude moves and the effective weight drifts. You tuned
a number that quietly changed meaning.

**Reciprocal Rank Fusion** throws the scores away and uses only ranks:

```
score(chunk) = α × 1/(60 + dense_rank) + (1−α) × 1/(60 + bm25_rank)
```

Ranks are already comparable, so `α = 0.6` means "dense gets 60% of the vote" and keeps
meaning that at any corpus size. The constant 60 is from the original RRF paper; it damps
the top ranks so rank 1 does not dominate rank 2 outright.

**What RRF costs:** margins. A chunk that won dense retrieval by a landslide and one that
squeaked in both land at rank 1 and look identical. Which is the setup for the next piece.

---

## 6. Re-ranking — the expensive step that earns its place

Everything so far used a **bi-encoder**: the query is embedded, each chunk was embedded
earlier, and similarity is compared between two vectors that *never saw each other*. That
independence is what makes it fast — chunk vectors are precomputed and indexed.

A **cross-encoder** takes `(query, chunk)` as one concatenated sequence and runs full
attention across both. Every query token can attend to every chunk token. It is strictly
more informative, and strictly impossible to precompute — you must run the model once per
(query, chunk) pair, at query time.

So the pattern is a funnel:

```
51 chunks  ──bi-encoder (indexed, ~ms)──▶  30 candidates  ──cross-encoder (30 forward passes)──▶  top 5
```

**`CANDIDATE_K = 30` is the ceiling on everything downstream.** A re-ranker can only
reorder what retrieval already handed it. This is why the eval reports `recall@cand`
separately: if the gold document is not in the 30, no re-ranker recovers it. Precision is
tunable; recall at the candidate stage is a hard wall.

Measured on this corpus: **hit@1 0.90 → 0.95, MRR 0.950 → 0.967, p50 9 ms → 143 ms.**
One question in twenty improves; every request gets ~15x slower. That is a product
decision, not a retrieval one — hence `RERANK_ENABLED` as a flag and a per-request
override on `/ask`.

---

## 7. Answering — `app/answer.py`

### Context assembly is budgeted in tokens, not chunks

"Take the top 5" with variable chunk sizes is how prompts overflow in production. Chunks
are added while a 2400-token budget holds, and **the citation list is built in the same
loop**, so the numbered markers in the prompt can never disagree with the citations
returned to the client. A desync there means an answer citing `[4]` when the client was
only told about three sources.

One deliberate exception: if a single chunk exceeds the whole budget it is still
included. A too-long prompt beats an answer with no context.

### The prompt

Three instructions, each earning its place:

1. **Answer strictly from the numbered sources** — the actual grounding constraint.
2. **Cite every claim with `[n]`** — citations are what make the answer auditable; an
   unverifiable answer is not much better than a web search.
3. **Say exactly "The provided sources do not answer that" when they do not** — an exact
   string, so abstention is machine-detectable and can be measured as a rate.

`temperature = 0.0`. There is nothing creative about reading a handbook, and determinism
makes the eval reproducible.

### Streaming, and why `sources` is sent first

SSE event order is `sources` → `token`* → `done`:

```
event: sources
data: {"citations":[{"n":1,"source":"14-incident-comms.md",...}]}

event: token
data: {"text":"Every 30 minutes"}
...
event: done
```

Sources go out **before the first token** on purpose. The client renders citation chips
immediately, so the user sees what the answer will be grounded in while it is still
generating — and if generation dies halfway, they still have the sources. Errors are
emitted as an in-band `error` event rather than as a torn connection, because the client
already has a half-rendered answer on screen and needs to know why it stopped.

### The no-key fallback

With no `OPENAI_API_KEY`, `/ask` returns the retrieved passages verbatim with their
citation markers, labelled as such. Someone cloning the repo gets a working endpoint for
free, and the degraded mode is explicit instead of a 500. The cost of being honest about
this: the `kw_match` metric in the README measures that fallback, not an LLM, and the
README says so.

---

## 8. Evaluation — `evals/run_evals.py`

### Why the corpus is fictional

Ask a model a question about Kubernetes and it may answer from pretraining without
reading anything you retrieved. Then your eval is measuring the model's memory, not your
retrieval. A fictional company handbook makes that impossible: **every fact in the corpus
exists only in the corpus**.

### Why near-twin documents

Eight pairs of documents answer the same question differently —
`02-deployment` (backend rollback: 5 minutes) vs `13-mobile-release-policy` (no mobile
rollback at all); `05-data-retention` (hot storage: 90 days) vs `16-warehouse-retention`
(warehouse raw: 180 days); `03-oncall` vs `14-incident-comms`; five more.

Without twins, retrieval only has to find the right *topic* — easy, and the eval cannot
distinguish a good system from a mediocre one. With twins, a plausible, specific failure
becomes visible and scored. It works: question `q03` (backend rollback target) retrieves
the *mobile* policy at rank 1 in every configuration. That is the single most useful line
the eval prints, because it names a concrete thing to fix.

### The metrics, and what each is worth

| Metric | What it measures | Honest limit |
|---|---|---|
| **hit@1** | gold document ranked first | the tracked metric here; on 20 questions, one question = 5pp |
| hit@3 / hit@5 | gold document in the top 3 / 5 | **saturated at 1.00 — measures nothing on 22 documents** |
| **MRR@5** | 1/rank of the first gold chunk, averaged | rewards ranking, so it moves when hit@k cannot |
| recall@cand | gold in the pre-rerank candidate set | the ceiling; if this is not 1.00, re-ranking cannot save you |
| kw_match | answer contains the expected fact | here it describes the extractive fallback, not an LLM |
| faithful | share of answer content words present in context | a **proxy**: catches drift off-source, misses a fluent wrong answer |

Labels are gold **documents**, not gold chunks, so hit-rate is forgiving by design.

### The ablation sweep

Seven configurations: 192 / 512 / 1024-token chunks × hybrid vs dense-only × re-rank vs
not. Each one **re-indexes from scratch** — chunk size changes what is in the index, so
reusing a warm store would compare a new query path against a stale index. Every
`lru_cache` in the app is cleared between configs for the same reason.

The sweep is in the repo because "512 tokens with 64 overlap" is worth nothing as an
assertion and something as a measurement. It also surfaced two findings worth more than
a good score:

- **512 vs 1024 is identical on this corpus** — both produce one chunk per document,
  because the documents are short. The setting only matters relative to your document
  length distribution.
- **BM25 adds almost nothing here** (MRR 0.950 hybrid vs 0.942 dense-only) — the questions
  are paraphrases, which is dense retrieval's home turf. Keeping the lexical half is a
  bet about production traffic, not a win this eval shows.

### The eval as a CI gate

`run_evals.py` exits non-zero if hit@1 drops below 0.60, and CI runs it on every pull
request. With 20 questions it is a smoke test, not a benchmark — its job is to catch the
day someone changes the chunker and retrieval quietly falls over.

### Evaluating RAG without human labels

1. **Synthetic question generation** — an LLM writes a question from each chunk; check that
   the chunk comes back for its own question. Free labels, scales to the whole corpus.
2. **Negative controls** — ask things the corpus cannot answer, measure the abstention
   rate. A system that never abstains is hallucinating. Zero labels needed.
3. **LLM-as-judge for groundedness** — score each answer sentence against the retrieved
   context. Correlates acceptably with humans on groundedness, much less so on
   helpfulness. Needs a periodic human audit of the judge itself.
4. **Production signals** — citation click-through, rephrasing rate, thumbs-down per
   thousand. Noisy, but measured on real intent.

---

## 9. What this project deliberately does not do

| Missing | Why it is missing | What adding it looks like |
|---|---|---|
| Auth / rate limiting | out of scope for a retrieval reference | API key middleware; per-tenant token bucket |
| Multi-tenancy | the hard part is pushing the filter *into* the vector query, not after it | `tenant_id` in the Qdrant payload filter; RLS for pgvector |
| Incremental re-index | the corpus is small enough to rebuild | content hash per chunk; upsert only what changed |
| Sparse vectors in Qdrant | in-process BM25 is fine to ~10⁵ chunks | Qdrant native sparse vectors; retires `rank_bm25` |
| LLM-as-judge | needs an API key and a human-audited sample | a judge prompt + agreement check against ~50 human labels |
| Verified `docker compose up` | no Docker on the author's machine | run it; it is written and unverified, and the README says so |

The last row is the pattern: **the gap is stated, not hidden.** A reviewer who finds an
unstated gap stops trusting the stated numbers too.

---

## 10. Reading the code in 15 minutes

Follow the data, in this order:

1. `app/config.py` — every tunable in one place. Read it first; it is the map.
2. `app/ingest.py` → `chunk_text()` — the packing loop and `_overlap_tail()`.
3. `app/embed.py` → the `VectorStore` protocol, then `QdrantStore`.
4. `app/retrieve.py` → `fuse()` (10 lines, the whole hybrid idea), then `retrieve()`.
5. `app/answer.py` → `build_context()` (budget + citations in one loop), then
   `answer_stream()`.
6. `app/main.py` — thin by design; the endpoints only wire the pieces together.
7. `evals/run_evals.py` → `evaluate()`, and `SWEEP` at the bottom.

Then run `make evals` and read the "gold not ranked first" list. That list is the project's
actual state of the art.
