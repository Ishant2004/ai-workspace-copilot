# Backend

FastAPI application that receives chat requests and streams LLM replies.

## Files

| File | Responsibility |
| ---- | -------------- |
| `main.py` | Creates the FastAPI app, wires CORS, mounts routers, exposes `/health`. |
| `config.py` | Loads settings from environment / `.env` (API key, model, CORS). |
| `models.py` | Pydantic schemas (`Message`, `ChatRequest`) — the API contract. |
| `api/chat.py` | The `POST /chat` endpoint. Streams the reply as SSE. |
| `api/tokens.py` | The `POST /tokenize` endpoint (Phase 1 token inspector). |
| `api/embed.py` | The `POST /embed` endpoint (Phase 2 embedding service). |
| `api/documents.py` | Document CRUD + `POST /search` (Phase 3). |
| `api/rag.py` | `POST /rag/chat` — grounded, cited streaming chat (Phase 4). |
| `api/threads.py` | Conversation CRUD + persisted streaming chat (Phase 9). |
| `api/tools.py` | `GET /tools`, `POST /tools/chat` — standalone function-call demo (Phase 10). |
| `api/profile.py` | `GET /profile`, `DELETE /profile` — long-term user memory (Phase 13). |
| `mcp_server.py` | Standalone MCP server exposing tools over stdio (Phase 14). |
| `api/auth.py` | `/auth/signup`, `/auth/login`, `/auth/me` — email/password + JWT. |
| `api/deps.py` | `current_user_id` dependency (decodes the Bearer token). |
| `services/auth.py` | bcrypt password hashing + JWT create/decode; users table. |
| `api/upload.py` | `POST /upload` — PDF ingestion pipeline (Phase 5). |
| `prompts.py` | Prompt templates (the RAG grounding system prompt). |
| `services/gemini.py` | Gemini SDK: chat, tokens, single + batch embeddings. |
| `services/db.py` | Vector DB access: init, insert, cosine + keyword search. |
| `services/search.py` | Search strategies: vector / keyword / hybrid (RRF). |
| `services/rerank.py` | Cross-encoder reranking with FlashRank (Phase 8). |
| `services/threads.py` | Conversation persistence: threads/messages, sliding window. |
| `services/tools.py` | Tool registry + the tool-call loop (backs the agent, Phases 10–11). |
| `services/web.py` | Live web search via DuckDuckGo (`ddgs`) — no API key. |
| `services/planner.py` | Plan-and-execute agent: plan → execute (retries) → synthesize (Phase 12). |
| `services/coordinator.py` | Multi-agent team: planner→retriever→solver→reviewer (Phase 16). |
| `services/profile.py` | Long-term user memory: extract facts + system-prompt preamble (Phase 13). |
| `services/mcp_client.py` | Connect to external MCP servers; discover + call their tools (Phase 15). |
| `services/pdf.py` | Extract text from PDF bytes, per page (pypdf). |
| `services/chunking.py` | Recursive boundary-aware chunking with overlap. |
| `services/tracing.py` | Per-turn trace: timed spans + token estimate, persisted (Phase 20). |
| `services/rewrite.py` | Query rewriting: expand a question into standalone/paraphrased queries (Phase 21). |
| `eval/harness.py` | Evaluation harness: seed golden corpus, score retrieval + answers (Phase 18). |
| `eval/judge.py` | LLM-as-judge: grades faithfulness + relevance 1–5 (Phase 19). |
| `eval/run_eval.py` | CLI runner + regression gate — prints metrics, writes a report, fails on regression. |
| `eval/golden.json` | Golden dataset: known corpus + questions with expected docs/facts. |

## Endpoints

### `GET /health`
Returns `{"status": "ok"}`. Used for uptime pings and quick checks.

### `POST /chat`
Request body:
```json
{ "messages": [ { "role": "user", "content": "Hello" } ] }
```
Response: an SSE stream (`text/event-stream`). Each event is a JSON object:
- `{"type": "chunk", "content": "..."}` — a piece of the answer.
- `{"type": "done"}` — the answer is complete.
- `{"type": "error", "content": "..."}` — something failed.

### `POST /tokenize`
Request body:
```json
{ "text": "some text to measure" }
```
Response:
```json
{
  "model": "gemini-2.5-flash",
  "characters": 20,
  "words": 4,
  "tokens": 5,
  "context_window": 1048576,
  "context_used_percent": 0.000477,
  "estimated_cost_usd": 0.0,
  "reference_cost_usd": 0.0000015
}
```
- `tokens` comes from Gemini's real tokenizer (`count_tokens`), so it is exact
  for the configured model.
- `estimated_cost_usd` is always `0.0` (free tier). `reference_cost_usd` shows
  what the same tokens would cost at paid-tier pricing, for intuition.
- Context window and paid-tier price are configurable in `config.py`
  (`gemini_context_window`, `gemini_input_price_per_1m`).

### `POST /embed`
Request body:
```json
{ "text": "some text to embed" }
```
Response:
```json
{
  "model": "gemini-embedding-001",
  "dimension": 768,
  "embedding": [-0.0385, 0.026, 0.0029, "…768 floats total"]
}
```
- The vector is **normalized to unit length** in `services/gemini.py`. Google
  recommends this when truncating the embedding to fewer than 3072 dims, and
  unit vectors make cosine similarity a plain dot product later.
- Model and dimension are configurable in `config.py` /`.env`
  (`gemini_embed_model`, `gemini_embed_dim`). **Do not change the dimension
  after storing documents** — old and new vectors would be incomparable.

### `POST /documents`
Store a document. Body: `{ "text": "...", "title": "optional" }`.
Response: `{ "id": 1, "title": "...", "total_documents": 1 }`.
The backend embeds the text and inserts it into the `documents` table.

### `GET /documents`
List all stored documents (id, title, text) newest-first. The raw embedding is
omitted — it's large and the UI never needs it just to list records.

### `PUT /documents/{id}`
Update a document. Body: same as POST. The backend **re-embeds** the new text
so the stored vector stays consistent with the text. Returns 404 if the id
doesn't exist.

### `DELETE /documents/{id}`
Delete a document. Response: `{ "id": 1, "deleted": true, "total_documents": 0 }`.
Returns 404 if the id doesn't exist.

### `POST /search`
Search. Body: `{ "query": "...", "k": 5, "mode": "hybrid", "rerank": false }`.
`mode` is `vector` | `keyword` | `hybrid` (default `hybrid`, Phase 7).
`rerank` (Phase 8) retrieves `rerank_candidates` (20) then trims to k with a
cross-encoder; each hit then carries a `rerank_score`.
Response:
```json
{
  "query": "...", "mode": "hybrid",
  "results": [
    { "id": 1, "title": "...", "text": "...", "similarity": 0.72,
      "metadata": {...}, "matched_by": ["vector", "keyword"], "rrf_score": 0.0328 }
  ]
}
```
- `similarity` is cosine similarity (`1 - cosine_distance`); `0.0` for
  keyword-only hits.
- `matched_by` lists which retrievers surfaced the hit.
- `rrf_score` is the fused rank score (hybrid mode only).
- Dispatch lives in `services/search.py`; keyword search uses the `text_search`
  tsvector column added in `init_db`.

### `GET /documents/count`
Returns `{ "total_documents": N }`. Used by the UI badge.

### Tool calling (Phase 10)
- `GET /tools` → `{ tools: [{name, description}] }` for the UI.
- `POST /tools/chat` — body `{ message }`. Runs the tool-call loop and streams
  SSE events: `tool_call` `{name, args}`, `tool_result` `{name, result}`,
  `chunk` (final answer), `done`, `error`. Tools: `calculate`,
  `get_current_time`, `search_documents`, `web_search` (live web).

### External MCP tools (Phase 15)
- `GET /mcp/tools?refresh=false` → external tools discovered from the servers in
  `mcp_servers.json`, namespaced `"<server>__<tool>"`. These are merged into the
  agent's tool set automatically (`tools.all_declarations()`), and calls to them
  dispatch through `services/mcp_client.py`.

### User profile (Phase 13)
- `GET /profile` → `{ "facts": ["Name is Rajat", ...] }`.
- `DELETE /profile` → clears all facts.
Facts are extracted in the background after each user turn and injected into the
system prompt on every turn (chat/RAG/agent). A hard `gemini_request_timeout`
(config, default 60s) caps every model call.

### Conversation threads (Phase 9)
- `POST /threads` → create a conversation `{ id, title, message_count }`.
- `GET /threads` → list conversations (most recently active first).
- `GET /threads/{id}/messages` → full history `[{role, content}]`.
- `DELETE /threads/{id}` → delete (messages cascade).
- `POST /threads/{id}/chat` — body `{ content, mode }` where `mode` is
  `chat` | `rag` | `agent` | `plan`. Persists the user message, replays the last
  `history_window` messages, then:
  - `chat`: conversational streamed reply that can quietly call tools
    (`web_search`, `search_documents`, `calculate`, …) when a question needs
    live or computed facts — surfacing `tool_call` / `tool_result` events;
  - `rag`: retrieves docs, emits a `sources` event, grounds the answer (no tools);
  - `agent` (Phase 11): runs the tool loop, emitting `tool_call` / `tool_result`
    events before the streamed answer;
  - `plan` (Phase 12): emits a `plan`, then `step_start` / `tool_call` /
    `tool_result` / `step_result` per step, then the synthesized `answer`.
  - `team` (Phase 16): emits `agent_start` / `agent_message` per sub-agent
    (Planner, Retriever, Solver, Reviewer), then the final `answer`.
  Every mode ends with a `trace` event (Phase 20): the turn's timed spans +
  token estimate. The assistant reply is persisted; new threads are auto-titled.
- `GET /threads/{id}/traces` → recent per-turn traces for the thread
  (`[{id, mode, total_ms, spans, tokens, created_at}]`), owner-scoped.

> Requires `DATABASE_URL` (a Neon Postgres URL). The table + `vector` extension
> are created automatically on startup. Embedding dimension must match
> `GEMINI_EMBED_DIM` and must not change once documents are stored.

### `POST /rag/chat`
Grounded chat. Body: `{ "messages": [...], "k": 4 }`.
Response: an SSE stream. The first event lists the retrieved sources, then the
answer streams as chunks:
- `{"type": "sources", "sources": [{"id":1,"title":"...","similarity":0.74}]}`
- `{"type": "chunk", "content": "..."}` … `{"type": "done"}`
- `{"type": "error", "content": "..."}` on failure.

Flow: embed the last user message → `db.search` top-k → `prompts` build a system
instruction containing that context → `stream_chat(messages, system_prompt)`.
The `system_instruction` support was added to `services/gemini.py` for this.

### `POST /upload`
Ingest a PDF. Multipart form field `file` (a `.pdf`).
Response:
```json
{ "filename": "handbook.pdf", "pages": 2, "chunks_stored": 12, "total_documents": 12 }
```
Pipeline (Phase 6): `services/pdf.extract_pages` (per page) →
`services/chunking.recursive_chunk` per page (`chunk_size`/`chunk_overlap` from
config) → `services/gemini.embed_texts` (batched) → `db.insert_documents`
(bulk, with metadata). Each chunk becomes a normal document row carrying
`metadata` = `{source, filename, page, chunk_index, uploaded_at}`, so it's
immediately searchable and RAG-usable and traceable to a page. Returns 400 for
non-PDFs or PDFs with no extractable text (e.g. scanned images).

### Metadata (Phase 6)
`documents` has a `metadata JSONB` column. Search and list responses include a
`metadata` object per row. Manually-added documents get
`{source: "manual", created_at}`; PDF chunks get the fields above. The column is
added idempotently on startup (`ADD COLUMN IF NOT EXISTS`), so existing
databases upgrade without data loss.

## Key design decisions

- **Stateless LLM, full history each call.** The backend does not store
  conversations yet; the frontend sends the whole history every request. This
  keeps Phase 0 trivial and mirrors how the LLM actually works.
- **Gemini isolated in one file.** Only `services/gemini.py` imports the SDK.
  If we swap providers later, nothing else changes.
- **Roles are translated.** Our schema uses `assistant`; Gemini calls it
  `model`. The translation happens in `services/gemini.py`.

## Running locally

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then paste your GEMINI_API_KEY
.venv/bin/uvicorn main:app --reload
```

Backend serves on http://localhost:8000 (docs at `/docs`).

> Note: this project currently requires modern package versions because the
> local Python is 3.14, which only has wheels for recent releases.

## Evaluation (Phase 18)

We measure RAG quality objectively so later changes can be judged, not guessed.

- `eval/golden.json` — a small known corpus plus questions, each tagged with the
  document it *should* retrieve and substrings the answer *must* contain.
- `eval/harness.py` — seeds that corpus under a dedicated **eval user**
  (`EVAL_USER_ID = -1`, negative so it can never collide with a real account),
  then for each question measures **retrieval hit@k** (did the expected doc show
  up in top-k?), **answer accuracy** (does the answer contain the expected
  facts?), and **latency**. It runs the *real* RAG path (hybrid retrieval + the
  RAG system prompt), so it scores what users actually get.
- `eval/run_eval.py` — CLI: prints a per-question table and headline metrics, and
  writes a timestamped JSON report to `eval/reports/` (git-ignored) for
  run-to-run comparison.

```bash
cd backend
PYTHONPATH="$(pwd)" .venv/bin/python -m eval.run_eval            # full, judge on
PYTHONPATH="$(pwd)" .venv/bin/python -m eval.run_eval --no-judge # faster
PYTHONPATH="$(pwd)" .venv/bin/python -m eval.run_eval --compare  # single vs multi-query
```

Baseline on the seeded corpus: retrieval hit@4 **100%**, answer accuracy
**100%**, ~3s/question. This baseline is what Phases 21–22 (query rewriting,
contextual retrieval) must beat to prove they help.

### LLM-as-judge + regression gate (Phase 19)

Substring checks tell you a fact is *present*; they can't tell you the answer is
*grounded* (not hallucinated) or actually *addresses* the question. `eval/judge.py`
adds a second model call that grades each answer **1–5 on faithfulness and
relevance** (with a one-line rationale), using structured JSON output so we get
clean numbers. Averages land in the report.

`run_eval.py` then acts as a **regression gate**: it exits non-zero if any metric
falls below a threshold, so a bad change fails the run. Defaults: retrieval ≥
0.8, answer ≥ 0.8, faithfulness ≥ 4.0, relevance ≥ 4.0 — overridable via
`EVAL_MIN_RETRIEVAL`, `EVAL_MIN_ANSWER`, `EVAL_MIN_FAITHFULNESS`,
`EVAL_MIN_RELEVANCE`. `check_gate(report, judge)` is a pure function (unit-tested
without API calls). Baseline judged run: faithfulness **5.0/5**, relevance
**5.0/5**, gate **PASSED**.

CI runs this gate (`.github/workflows/ci.yml`, `eval-gate` job) when the repo has
`DATABASE_URL` + `GEMINI_API_KEY` secrets set, and skips cleanly otherwise. Note
the free tier caps at ~15 requests/min and a judged run makes 2 calls/question,
so the harness uses long backoffs to ride out 429 cooldowns.

### Query rewriting & multi-query retrieval (Phase 21)

A raw user message is often a poor search query — it leans on pronouns ("how many
can I carry over?") and uses different words than the documents.
`services/rewrite.py` expands it into a few **standalone, paraphrased queries**
(the original made self-contained using conversation history, plus vocabulary
variants). `services/search.py:multi_query_search` retrieves both ways (vector +
keyword) for each variant and fuses everything in one **RRF** pass (the fusion is
now a reusable `_fuse` over any number of ranked lists — same math as hybrid,
more lists). `search_expanded()` combines the two and is what RAG uses; it honours
`RETRIEVAL_MULTI_QUERY` (on by default) and `REWRITE_VARIANTS` (default 3), and
costs one extra LLM call per RAG turn.

`eval/compare_retrieval()` isolates the effect: it measures **retrieval hit@k
only** (no generation) for single-query vs multi-query over a corpus that
includes confusable same-topic distractors (`eval/golden_hard.json` — e.g. Sick
Leave vs PTO, Contractor vs Remote Work). At the selective k=1, single-query
hybrid misses ambiguous questions that multi-query recovers: a measured lift of
**75% → 88% (+12%)** in one run (rewriting is stochastic, so the delta varies run
to run but stays positive). `evaluate()` itself still uses single-query hybrid as
the stable retrieval floor; `compare` is where the Phase 21 gain is shown.
