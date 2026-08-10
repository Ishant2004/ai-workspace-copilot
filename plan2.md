# AI Workspace Copilot — Part 2: From Demo to Production-Grade

Part 1 (Phases 0–17, plus live web search) built a working end-to-end AI
assistant: streaming chat, RAG over pgvector, hybrid search + reranking, agents,
planning, memory, MCP, multi-agent, per-user auth, and a $0 deployment.

**Part 2 is about the things that separate a demo from a system you can trust:**
measuring quality, seeing what the model actually did, making retrieval better on
purpose (not by luck), and hardening for real users.

We keep the same rules as Part 1: **one feature at a time → test it → then it's
pushed to GitHub**, first-principles functional code, docs updated each phase, all
on the **$0 free tier**.

---

## Guiding themes

| Theme | Why it matters |
| ----- | -------------- |
| **Measure before you improve** | You can't tune RAG you can't score. Evals come first. |
| **See what happened** | Traces turn "it felt slow / wrong" into a number you can act on. |
| **Improve retrieval on purpose** | Query rewriting + contextual chunks are the biggest quality levers. |
| **Close the loop** | User feedback feeds the eval set, so the system keeps getting measured. |
| **Make it cheap & safe** | Caching cuts cost/latency; guardrails make multi-tenant real. |

---

## Roadmap at a glance

| Phase | Feature | Theme |
| ----- | ------- | ----- |
| 18 | Evaluation harness (golden set, retrieval + answer metrics) | Measure |
| 19 | LLM-as-judge + regression gate | Measure |
| 20 | Observability & tracing (per-turn: tools, retrieval, latency, tokens) | See |
| 21 | Query rewriting & multi-query retrieval | Retrieval |
| 22 | Contextual retrieval (chunk-level context headers) | Retrieval |
| 23 | Feedback loop (thumbs up/down → eval set) | Close the loop |
| 24 | Caching (prompt cache, embedding cache, response cache) | Cheap |
| 25 | Semantic memory retrieval + memory management UI | Personalization |
| 26 | More ingestion formats (DOCX, Markdown, HTML, URL) | Data |
| 27 | More tools (URL fetch + summarize, CSV analysis) | Capability |
| 28 | UX polish (markdown/code rendering, message actions, doc manager) | UX |
| 29 | Security hardening (rate limits, input caps, injection guardrails, audit log) | Safe |

---

# PHASE 18: Evaluation Harness

## Goal
Score the RAG pipeline objectively so every later change can be judged
better/worse instead of "feels fine."

## Implementation
- A **golden dataset** (`backend/eval/golden.json`): a small known corpus of
  documents + a set of questions, each tagged with the document it should
  retrieve and substrings the answer must contain.
- A **harness** (`backend/eval/harness.py`) that seeds the corpus under a
  dedicated eval user, then for each question measures:
  - **Retrieval:** did the expected document appear in the top-k? (hit@k)
  - **Answer:** does the generated answer contain the expected facts? (accuracy)
  - **Latency** per question.
- A **CLI runner** (`python -m eval.run_eval`) that prints a metrics table and
  writes a timestamped JSON report to `backend/eval/reports/`.

## Concepts learned
Golden datasets, hit@k / recall, grounded-answer accuracy, regression baselines.

---

# PHASE 19: LLM-as-Judge & Regression Gate

## Goal
Grade answer *quality* (faithfulness, relevance) beyond simple substring checks,
and turn the eval into a pass/fail gate.

## Implementation
- A **judge** that scores each answer 1–5 on faithfulness (grounded in retrieved
  context) and relevance (answers the question), with a one-line rationale.
- Aggregate scores added to the Phase 18 report.
- A **threshold gate**: the runner exits non-zero if scores drop below a
  baseline — wired into CI so a bad change can't merge.

## Concepts learned
LLM-as-judge, rubric prompts, quality gates, CI-enforced regression testing.

---

# PHASE 20: Observability & Tracing

## Goal
See exactly what each turn did: which tools ran, what was retrieved, how long it
took, how many tokens it used.

## Implementation
- A lightweight **trace collector** that records per-turn spans (retrieval, each
  tool call, model call) with latency + token counts, stored in a `traces` table.
- SSE `trace` events surfaced to the UI, plus a `GET /traces` endpoint.
- A simple **Traces tab** (or per-message expander) showing the timeline.

## Concepts learned
Spans/traces, latency attribution, token accounting, production debugging.

---

# PHASE 21: Query Rewriting & Multi-Query Retrieval

## Goal
Improve recall on vague or conversational questions before retrieval runs.

## Implementation
- **Query rewriting:** rephrase the user's question into a standalone search
  query (resolving pronouns from history).
- **Multi-query:** generate 2–3 paraphrases, retrieve for each, and fuse with
  RRF (reusing the Phase 7 fusion).
- Measured against Phase 18 to prove the gain.

## Concepts learned
Query transformation, multi-query fusion, retrieval recall vs. precision.

---

# PHASE 22: Contextual Retrieval

## Goal
Make each chunk self-describing so embeddings capture what the chunk is *about*,
not just its raw words (Anthropic's "contextual retrieval").

## Implementation
- At ingestion, prepend a short model-generated context line to each chunk
  (e.g., "From the 2024 PTO policy: …") before embedding.
- Store both the raw and contextualized text.
- Re-run Phase 18 to quantify the hit-rate improvement.

## Concepts learned
Chunk contextualization, embedding what-vs-words, ingestion-time enrichment.

---

# PHASE 23: Feedback Loop

## Goal
Capture real user judgments and feed them back into evaluation.

## Implementation
- Thumbs up/down + optional note on each assistant message → `feedback` table.
- An export that turns thumbs-down cases into new golden-set candidates.
- A tiny stats view: satisfaction rate over time.

## Concepts learned
Human feedback capture, data flywheel, eval-set growth from production.

---

# PHASE 24: Caching (Cost & Latency)

## Goal
Stop paying (in time and quota) for work already done.

## Implementation (as built)
- **Embedding cache** — content-hash → vector (LRU). Deterministic, so never
  stale; query variants and repeated questions skip the embed API.
- **Retrieval cache** — (user, mode, k, query) → hits, short TTL **plus** a
  per-user version stamped in the key that every document write bumps, so a
  cached result can never outlive its data.
- **Response cache** — the stateless `/rag/chat` answer, keyed by the whole
  request (safe: identical input → identical output), TTL + version invalidated.
- `GET /cache/stats` exposes hit/miss per cache so the win is observable.

> Note: real Gemini *prompt* caching (explicit `CachedContent`) needs a large
> minimum token count and isn't reliable on the free tier, so we cache what's
> both safe and useful (embeddings, retrieval, responses) instead of adding
> fragile context-cache code.

## Concepts learned
Content-addressed caching, LRU vs TTL, version-based invalidation, observability.

---

# PHASE 25: Semantic Memory Retrieval + Management UI

## Goal
Inject only the *relevant* user facts per turn, and let users control memory.

## Implementation
- Embed stored profile facts; retrieve the top-k relevant to the current message
  instead of injecting all of them.
- A **memory panel** to view/edit/delete remembered facts.

## Concepts learned
Retrieval over memory, relevance-gated personalization, user data control.

---

# PHASE 26: More Ingestion Formats

## Goal
Ingest more than PDFs.

## Implementation
- Parsers for **DOCX**, **Markdown**, **HTML**, and **paste-a-URL** (fetch +
  extract main content), all feeding the existing chunk → embed → store pipeline.

## Concepts learned
Format-agnostic ingestion, HTML main-content extraction, unified pipelines.

---

# PHASE 27: More Tools

## Goal
Give the agent deeper reach than a search-result snippet.

## Implementation
- **URL fetch + summarize:** read a page the web search found and extract the
  answer.
- **CSV/table analysis:** load a small uploaded CSV and answer questions over it.

## Concepts learned
Tool composition (search → fetch → read), structured data tools.

---

# PHASE 28: UX Polish

## Goal
Make the app feel finished.

## Implementation
- **Markdown + code rendering** with syntax highlighting in answers.
- **Message actions:** copy, regenerate, edit-and-resend.
- **Document manager view:** browse, search, and delete uploaded docs + metadata.

## Concepts learned
Rich rendering, conversational affordances, content management UX.

---

# PHASE 29: Security Hardening

## Goal
Make the multi-tenant system safe to expose.

## Implementation
- **Rate limiting** per user (Upstash Redis or in-process token bucket).
- **Input size caps** on messages and uploads.
- **Prompt-injection guardrails** on ingested/retrieved content.
- **Refresh tokens / rotation** and an **audit log** of auth + data events.

## Concepts learned
Rate limiting, abuse prevention, injection defense, token lifecycle, auditing.

---

## Summary of Part 2 milestones

- ✅ Objective RAG evaluation (retrieval + answer metrics)
- ✅ LLM-as-judge quality gate in CI
- ✅ Per-turn tracing & token accounting
- ✅ Query rewriting + multi-query retrieval
- ✅ Contextual retrieval at ingestion
- ✅ User feedback flywheel
- ✅ Embedding / retrieval / response caching
- ✅ Semantic memory + memory controls
- ⬜ Multi-format ingestion
- ⬜ Deeper tools (URL fetch, CSV)
- ⬜ Polished, production-feel UX
- ⬜ Rate limiting, guardrails, audit logging
