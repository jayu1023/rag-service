# Interview Guide — RAG Document Intelligence Service

How to present this project and survive the follow-ups. Written for an AI Engineer loop.

**The one rule:** this repo's advantage is not its score — the score is 0.95 hit@1 on
twenty questions, which is nothing. Its advantage is that **every number is measured,
every limitation is written down, and every default has a reason.** That is rare, and it
is the thing to lean on. The moment you oversell it, you are competing on score and you
lose.

---

## 1. The 60-second version

> "It's a document question-answering service — FastAPI, hybrid retrieval, streamed
> answers with inline citations. You POST documents, it chunks them on token boundaries,
> embeds them into Qdrant, and keeps a BM25 index alongside. On a question it runs both
> retrievers, fuses them with reciprocal rank fusion, re-ranks the top 30 with a
> cross-encoder, and streams the answer over SSE — sources first, then tokens, so the UI
> can show citations while it's still generating.
>
> The part I'd actually want to talk about is the eval harness. It's 20 questions over a
> fictional 22-document corpus, and eight of those documents are deliberate near-twins
> that answer the same question differently — so retrieving the wrong one is a scored
> failure, not something the eval can't see. It's what let me measure the re-ranker
> instead of assuming it: hit@1 went from 0.90 to 0.95 and MRR from 0.950 to 0.967, at
> 9 milliseconds to 143. And it told me two things I didn't expect, which I'm happy to
> get into."

Then stop. The last sentence is bait, and a good interviewer always takes it.

### The two unexpected findings — have these ready

**1. 512 vs 1024-token chunks made no measurable difference on this corpus.**
Because the documents are short enough to each fit in one chunk either way. Chunk size
only matters relative to your document length distribution — which is exactly why the
repo ships a sweep instead of a claim.

**2. BM25 added almost nothing** (MRR 0.950 hybrid vs 0.942 dense-only).
Because the eval questions are paraphrases, which is dense retrieval's home turf. Keeping
the lexical half is a bet about production traffic — users pasting error codes and exact
identifiers — not a win this eval demonstrates.

Volunteering a result that undercuts your own design reads as confidence, and it is the
fastest way to establish that your other numbers are real.

---

## 2. The demo, in order

Four minutes, no slides:

1. `make evals` — the metric table and the "gold not ranked first" list.
2. **Open `q03` in `evals/questions.yaml`**: "What is the rollback target for a backend
   production release?" It retrieves `13-mobile-release-policy.md` at rank 1 in *every*
   configuration. Show the failure before anyone finds it.
3. `make ask Q="How often is the status page updated during a Sev-1?"` — the SSE stream,
   `sources` arriving before the first token.
4. `evals/run_evals.py --sweep` output — or the table in the README if time is short.

**Lead with the failure in step 2.** A candidate who shows you their worst case first is
making a claim about their relationship with their own numbers, and it changes how the
rest of the conversation goes.

---

## 3. The questions you will get, and how to answer them

Each answer: the direct answer first, then the reason, then the limit. Never the reverse.

### "Why that chunk size and overlap? What breaks if you double it?"

> "512 tokens with 64 overlap, and 512 is a ceiling rather than a target — the chunker
> packs whole paragraphs up to the limit, so a short document stays one chunk.
>
> It's token-based, not character-based, because every budget downstream is in tokens —
> the embedding model's max sequence length, the LLM context, the bill. Characters per
> token swings a lot between English prose, Gujarati, and JSON, so character chunking
> means your chunk size drifts with the content.
>
> Too small and a chunk loses the context that makes it mean anything — 'promotion is
> halted below 99.5%' is useless without the paragraph that says what's being promoted.
> Too large and the embedding becomes an average: one relevant sentence in forty gets
> diluted until the vector points at a topical centroid instead of the fact. Plus top-5
> at 2000 tokens is 10k tokens of prompt per request.
>
> What breaks at 1024 on *my* corpus: nothing, measurably — identical metrics, because
> these documents already fit in one chunk. On long PDFs it inverts and you start losing
> precision. Which is why I shipped the sweep instead of the number."

### "Dense vs hybrid retrieval — when does BM25 still win?"

> "Exact strings. Error codes, config keys like `max_memory_usage`, SKUs, customer names,
> anything the user copy-pasted out of the document. Dense embeddings map those into a
> vague neighbourhood of similar-looking tokens; BM25 just matches. It also wins on
> vocabulary the embedding model never saw in training — a product name that shipped
> after the model's cutoff has no useful vector.
>
> On my eval it adds almost nothing — 0.950 MRR hybrid vs 0.942 dense-only — because I
> wrote the questions as paraphrases. That's a flaw in my question set, not evidence
> against BM25. In production I'd expect a meaningful chunk of traffic to be exact-match,
> and I'd measure it by bucketing queries by whether they contain a rare token and
> reporting the two buckets separately."

### "Why RRF instead of blending the scores?"

> "Because the scores aren't on the same scale and never will be. Cosine is bounded in
> [-1, 1]; BM25 is an unbounded sum that depends on corpus statistics. If you write
> `0.6 × cosine + 0.4 × bm25`, that weight silently changes meaning as the corpus grows —
> you tuned a number that drifted out from under you.
>
> RRF only consumes ranks, so alpha means 'dense gets 60% of the vote' and keeps meaning
> that. The cost is that you throw away margins — a landslide win and a photo finish both
> look like rank 1. Which is exactly why the cross-encoder runs after fusion: RRF picks
> the candidate set, the cross-encoder picks the order."

### "What does the re-ranker buy you, and is it worth it?"

> "hit@1 0.90 to 0.95, MRR 0.950 to 0.967, and p50 from 9 milliseconds to 143. So one
> question in twenty moves to rank 1, and every request gets about 15x slower on the
> retrieval leg.
>
> Whether that's worth it depends on what's downstream. If an LLM reads the top 5 anyway,
> re-ranking buys you less — the right chunk was already in the prompt. If you're showing
> a single answer, or you're tight on prompt budget and want top-2 instead of top-5, it's
> clearly worth it. It's a flag and a per-request override for that reason.
>
> And honestly: on 20 questions, 0.90 to 0.95 *is* one question. I'd call it a direction,
> not a measurement, until the eval set is 10x bigger."

**Follow-up you should expect — "why does a cross-encoder work better at all?"**

> "The bi-encoder embeds the query and the chunk separately — they never see each other,
> which is what lets you precompute and index the chunk vectors. The cross-encoder reads
> the pair as one sequence with full attention across both, so query tokens can attend to
> chunk tokens. Strictly more informative, and strictly not precomputable — you run it
> once per pair at query time. That's the whole trade, and it's why the funnel shape
> exists: cheap model to narrow, expensive model to order."

### "HNSW vs IVF — what do `ef_construct` and `m` cost you?"

> "`m` is edges per node in the graph. Higher m: better recall, more memory, slower build.
> `ef_construct` is how many candidates get considered when linking a new node at build
> time — higher means a better-quality graph and better recall, slower index build, and
> *no* effect on query latency. The query-time dial is `ef`, the candidate list during
> search, and that's the one you actually tune against a recall target in production.
>
> I set m=16 and ef_construct=128 explicitly in both backends. They're the defaults, but
> I wrote them down so the trade-off is a visible decision instead of an accident.
>
> HNSW versus IVF is memory versus simplicity. HNSW keeps a graph in RAM and gives you
> very low latency with no training step. IVF clusters the vectors and only searches the
> nearest few clusters — much less memory, but it needs a trained centroid set, it gets
> worse if your distribution shifts away from the training sample, and `nprobe` becomes
> the recall knob. Rule of thumb I'd use: HNSW while the index fits in RAM and latency
> matters; IVF, or IVF-PQ, when it doesn't."

### "How do you measure a RAG system without human labels?"

> "Four things, roughly in order of cost.
>
> First, retrieval has free labels. Generate a question from each chunk with an LLM and
> check whether that chunk comes back for its own question. No humans, scales to the whole
> corpus. It over-rewards lexical overlap because the question is derived from the chunk's
> own words, so you prompt for paraphrase.
>
> Second, negative controls — ask things the corpus provably can't answer and measure the
> abstention rate. A system that never says 'the sources don't answer that' is
> hallucinating, and this catches it with zero labels. That's why my prompt specifies an
> exact abstention string: it makes abstention machine-detectable.
>
> Third, LLM-as-judge for groundedness — score each answer sentence against the retrieved
> context. It correlates acceptably with humans on groundedness, much less so on
> helpfulness, and you have to audit the judge against a human sample periodically or
> you're just measuring one model's preferences.
>
> Fourth, production signals — citation click-through, how often users rephrase, thumbs-down
> per thousand. Noisy per event, but it's the only measurement taken on real intent.
>
> In this repo I only have the cheap version: a lexical-overlap proxy I deliberately don't
> call faithfulness, because it catches an answer drifting off-source but not a fluent
> wrong answer assembled from the right words."

### "Where do you put a guardrail — prompt, output parser, or a separate classifier?"

> "All three, at different costs, and the question is what failure you're buying down.
>
> The prompt is free and the weakest — 'answer only from the sources' shifts the
> distribution, it doesn't bound it. Worth doing, never worth trusting.
>
> The output parser is where I'd put anything with a checkable shape: does the answer cite
> at least one source, do the citation numbers exist, does structured output validate
> against the schema. Cheap, deterministic, and it catches the failure that matters most
> here — an uncited claim.
>
> A separate classifier pass is for things you can't check structurally: PII leakage,
> prompt injection in the retrieved documents, toxicity. It costs a model call and
> latency, so it's reserved for high-stakes paths.
>
> The one I'd add to this repo first is the cheapest and it's missing: reject any answer
> that makes a claim with no citation marker. That's a parser rule, and it closes the
> actual failure mode of a RAG system."

**Likely follow-up — "prompt injection in the documents?"**

> "Yes, and that's the RAG-specific one people miss. Retrieved text is untrusted input
> that you're pasting into your own prompt. If a document says 'ignore previous
> instructions', you've handed the attacker the prompt. Mitigations: delimit and label
> retrieved content as data, never let the retrieved text sit in the system message,
> don't give the answering model tools it could be talked into calling, and scan at
> ingest time. In this repo the sources are delimited and numbered but I haven't
> implemented injection scanning — it's not in the code and I wouldn't claim it."

### "What actually drives LLM cost, and which lever did you pull first?"

> "In a RAG system, input tokens — and specifically the retrieved context, which is
> typically the large majority of the prompt. Output is usually a few hundred tokens;
> context is thousands, on every single request.
>
> So the first lever is always the same: retrieve fewer, better chunks. That's the reason
> the re-ranker is worth its latency — if re-ranking lets you go from top-5 to top-3 at
> the same answer quality, you cut prompt cost ~40% with no quality loss. Better retrieval
> is a cost lever before it's a quality lever.
>
> Second, I budget the context in tokens rather than taking 'the top 5'. With variable
> chunk sizes, top-5 means your prompt cost is whatever the chunker happened to produce.
>
> After that: cache embeddings for repeated queries, route easy questions to a smaller
> model, and use prompt caching for the system prompt. I haven't implemented the routing
> or the caching here, and I'd want a quality measurement in place before adding either —
> cost optimisations are how you quietly ship a regression."

### "Qdrant and pgvector — why both? Isn't that over-engineering?"

> "It's two implementations of one five-method protocol, so it's maybe 80 lines of extra
> code, and it reflects a real decision I'd make differently in different jobs.
>
> Qdrant when retrieval is the product — payload filtering, quantization, explicit index
> control, horizontal scale. pgvector when the vectors are one more column on a product
> that already runs Postgres and a second datastore isn't worth the operational surface.
> At small scale pgvector is almost always the right answer and people reach for a vector
> database because it's the interesting choice.
>
> Honest caveat: the pgvector backend is written but I haven't run it against a live
> Postgres, because I don't have Docker on this machine. All the numbers come from Qdrant.
> That's in the README."

### "Your hit@5 is 1.00. What does that tell me?"

The question you most want. Do not get defensive.

> "Nothing at all, and that's in the README. With 22 documents, the gold document is
> almost always in any top-5 — hit@5 and hit@3 are saturated and can't regress, so they
> can't measure anything. hit@1 and MRR are the metrics I track, and the CI gate is on
> hit@1.
>
> It's also why I built the twin documents — eight pairs that answer the same question
> differently. Without them, retrieval only has to find the right topic, which is easy.
> With them, there's a plausible specific failure to score, and it caught one: q03 asks
> for the backend rollback target and gets the mobile release policy at rank 1 in every
> configuration.
>
> To make hit@5 mean something I'd need a corpus two orders of magnitude bigger, and I'd
> get there with synthetic question generation rather than by hand-writing 2000 questions."

### "Why is hit@1 only 0.95? What's the failing question?"

> "q03: 'What is the rollback target for a backend production release?' It returns
> `13-mobile-release-policy.md` at rank 1 and the correct `02-deployment.md` at rank 2 or 3.
>
> The cause is that the mobile document *talks about* the backend rollback target — it has
> the sentence 'this asymmetry with the backend five-minute rollback target is the main
> reason risky changes are gated server-side.' So the mobile chunk genuinely is about
> backend rollback. It's a chunk-level topical match that's wrong at the document level.
>
> Three fixes, in the order I'd try them: prepend the document title to each chunk before
> embedding, so 'Mobile Release Policy' is in the vector and the model can tell the two
> apart — cheapest and usually effective. Second, a smaller chunk size, so the
> cross-reference sentence isn't packed in with the whole mobile policy. Third, if these
> documents had real metadata, filter by document type before retrieval instead of hoping
> the embedding sorts it out.
>
> I haven't fixed it. I'd rather show a 0.95 with a diagnosed failure than tune until it's
> 1.00 on twenty questions."

### "What would you do differently if this had real traffic?"

> "In order:
>
> Multi-tenancy first, and specifically pushing the tenant filter *into* the vector query
> rather than filtering results after. Post-filtering silently shrinks your top-k and
> leaks timing information.
>
> Then incremental indexing. Right now `/ingest` re-embeds everything you point it at. It
> needs a content hash per chunk so a one-line document edit doesn't re-embed the corpus.
>
> Then abstention measurement in production, because that's the metric that tells you the
> system is lying, and it's the one the offline eval can't give you.
>
> Then the BM25 index moves out of process — it's an in-memory `rank_bm25` index rebuilt
> on every ingest, which is fine to maybe 10⁵ chunks and then becomes the bottleneck. The
> fix is Qdrant's native sparse vectors, so the lexical half lives in the engine that
> already holds the text.
>
> And auth and rate limiting, which are simply absent."

### "Walk me through what happens on a single request."

> "`POST /ask` with a question. It's validated — blank question is a 422. The question
> gets embedded with the same MiniLM model that indexed the corpus, which matters:
> different models on the two sides and the vectors aren't comparable.
>
> Dense search in Qdrant returns 30 candidates by cosine. BM25 returns up to 30 by term
> overlap. Those two ranked lists get fused with weighted RRF into one ordered list. The
> top 30 of that go to the cross-encoder, which scores each (question, chunk) pair and
> reorders. Top 5 survive.
>
> Context assembly walks those 5 adding chunks while a 2400-token budget holds, building
> the numbered citation list in the same loop so the markers in the prompt can't disagree
> with the citations I return. The `sources` SSE event goes out immediately. Then the LLM
> call streams and each delta becomes a `token` event, then `done`.
>
> If there's no API key, the token event carries the retrieved passages verbatim with a
> label saying so. If the LLM call throws, it becomes an `error` event rather than a
> dropped connection — the client already has a half-rendered answer and needs to know
> why it stopped."

---

## 4. Questions where the honest answer is "I didn't"

Do not bluff these. Interviewers probe exactly here, and one confident wrong answer
devalues everything true you said earlier.

| Question | Answer |
|---|---|
| "Did you run it in Docker?" | "No — the compose file and Dockerfile are written, two-stage, model weights baked in, non-root, but I don't have Docker on this machine and I haven't run it. It's flagged as unverified in the README. Everything else — the tests, the eval numbers, the embedded-Qdrant path — I ran." |
| "Have you served real traffic?" | "No. No auth, no rate limiting, no multi-tenancy, no load test. It's a reference implementation with a measurement harness, not a production system." |
| "What's your p95 under load?" | "I haven't load-tested it. What I have is single-request p50 from the eval: 9ms without the re-ranker, 143ms with. I'd expect the cross-encoder to be the bottleneck under concurrency since it's synchronous CPU work in the request path — first thing I'd measure, and the fix is a batch queue or GPU." |
| "Which embedding model is best?" | "I didn't benchmark models — I picked MiniLM so the repo runs on anyone's laptop with no API key. If I were choosing for production I'd start from MTEB for the shortlist and then re-measure on my own eval set, because MTEB rank and performance on your corpus come apart regularly." |
| "Is the faithfulness metric real?" | "No, and I named it a proxy in the code for that reason. It's lexical overlap between the answer and the context. It catches an answer wandering off-source; it does not catch a fluent wrong answer built from the right words. That needs an LLM judge or humans." |
| "Did you test pgvector?" | "Implemented, not exercised against a live Postgres — same Docker reason. All numbers are Qdrant." |

**The framing that makes this work:** "Here's what I measured, here's what I didn't, and
here's which one I'd do first." Interviewers are not looking for a complete system from a
side project. They are checking whether you know the difference between what you verified
and what you assumed.

---

## 5. If they ask you to extend it live

Likely prompts and the shape of a good answer. Say the approach out loud before coding.

**"Add conversational follow-ups."**
The problem is that "what about on iOS?" has no retrievable content on its own. Rewrite
the query against the conversation history into a standalone question before retrieval —
one cheap LLM call. Do not just concatenate the history into the search string; it
pollutes the embedding with the previous topic.

**"Return which part of the chunk the answer came from."**
Sentence-level offsets. Keep character spans on the chunk through assembly, and have the
model cite sentence IDs instead of chunk IDs. Or post-hoc: align the answer's sentences
back to the context by embedding similarity. The first is more accurate, the second needs
no prompt change.

**"Support 10 million documents."**
Four things change. Embedding becomes a batch pipeline, not a request handler. The
in-process BM25 index is immediately impossible — sparse vectors in the engine. Qdrant
needs sharding and probably scalar quantization to keep the graph in RAM. And the eval set
has to grow with it, because hit@5 on 20 questions tells you nothing about 10M documents.

**"Cut the cost in half."**
Measure where the tokens go first — almost certainly retrieved context. Then: re-rank
harder so top-3 does the job of top-5; prompt-cache the system message; route easy
questions to a smaller model with a confidence check. Each one needs the eval run before
and after, because every cost lever is a potential quality regression.

**"Make it answer 'I don't know' more reliably."**
Three layers. A score floor — if the best re-rank score is below a threshold, don't call
the LLM at all. The exact-string abstention instruction that's already in the prompt. And
a parser rule that rejects an answer with no citation marker. Then measure the abstention
rate on a negative control set, because the failure mode of adding abstention is a system
that abstains on answerable questions.

---

## 6. Where this sits on your résumé

**Claims this repo makes defensible:** RAG, chunking strategies, re-ranking, embeddings,
semantic search, hybrid retrieval, Qdrant, pgvector, LLM evaluation, FastAPI, SSE
streaming, Docker (written, not run — say so), MLflow (eval runs log to it).

**Claims it does not back.** Do not let it imply these: LangGraph, multi-agent, function
calling, MCP, guardrails, fine-tuning, LoRA, PEFT. Those are P1 and P2 in
`PENDING_PROJECTS.md`. If a job description leads with agents, this project is your
retrieval answer and you need the agent backend separately.

**The three sentences to have ready when someone opens your GitHub:**

1. "The eval harness is the part I'd point at — twenty questions over a fictional corpus
   with deliberate near-duplicate documents, so retrieval failures are visible and scored."
2. "The re-ranker number is measured, not assumed: hit@1 0.90 to 0.95 for 9ms to 143ms."
3. "The README says what I didn't verify, including that I never ran the compose file."

---

## 7. The mindset

The strongest thing about this project is not any single technical decision. It is that
it demonstrates the habit interviewers are actually screening for: **you measured, you
reported what the measurement was worth, and you named the failure you hadn't fixed.**

Most candidate RAG projects present a number with no eval behind it. A few present an
eval. Almost none present an eval and then explain why their own headline metric is
meaningless. That last move is what makes a senior-sounding engineer, and it is free —
it costs nothing but the willingness to say "hit@5 is 1.00 and it measures nothing."

Two things to avoid:

- **Don't oversell the score.** 0.95 on 20 questions is a smoke test. Say that before they
  do.
- **Don't apologise for scope.** It is a reference implementation with a measurement
  harness, built on purpose. "It's just a side project" invites them to discount it; "it's
  a retrieval reference with an eval gate, and here's what it doesn't do" does not.
