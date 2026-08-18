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
| `api/upload.py` | `POST /upload` — multi-format ingestion (PDF/DOCX/MD/TXT/HTML) (Phases 5, 26). |
| `api/ingest.py` | `POST /ingest/url` — fetch a web page and ingest it (Phase 26). |
| `services/extract.py` | Per-format text extraction (DOCX, HTML→text, URL fetch) (Phase 26). |
| `services/ingest.py` | Shared pipeline: chunk → contextualise → embed → store (Phase 26). |
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
| `services/context.py` | Contextual retrieval: model-written context line per chunk before embedding (Phase 22). |
| `services/cache.py` | In-memory LRU/TTL caches: embeddings, retrieval, responses + hit/miss stats (Phase 24). |
| `services/ratelimit.py` | In-process per-key fixed-window rate limiter (Phase 29). |
| `services/audit.py` | Audit log: record + list security events (Phase 29). |
| `services/guard.py` | Heuristic prompt-injection detector for retrieved content (Phase 29). |
| `services/workspace.py` | Per-user code workspace root + path confinement (Phase 32). |
| `services/editor.py` | Code edits: propose (diff, staged) → apply/discard (Phase 33). |
| `services/skills.py` | Skill playbooks: discover, load (`use_skill`), catalogue (Phase 35). |
| `api/workspace.py` | Select the workspace; review/apply/discard staged edits. |
| `api/skills.py` | `GET /skills`, `GET /skills/{name}`. |
| `skills/*.md` | Reusable task playbooks (frontmatter + steps + context pointers). |
| `services/feedback.py` | 👍/👎 feedback store: rate answers, satisfaction stats, export negatives (Phase 23). |
| `api/feedback.py` | `POST /feedback`, `GET /feedback/stats`, `GET /feedback/export`. |
| `eval/export_feedback.py` | CLI: turn thumbs-down feedback into golden-set candidates. |
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
  `get_current_time`, `search_documents`, `web_search` (live web),
  `fetch_url` (read a page), `analyze_csv` (tabular data).

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
- `POST /threads/{id}/chat` — body `{ content, mode, regenerate? }` where `mode`
  is `chat` | `rag` | `agent` | `plan` | `team`. Normally persists the user
  message; when `regenerate` is true (Phase 28) it instead drops the last
  assistant answer and re-answers the existing last question in place (no
  duplicate turn). Replays the last `history_window` messages, then:
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
  - `code` (Phase 34): a coding agent — the ReAct loop with the workspace tools
    (list/read/search + write/edit) and a higher step budget (`code_max_steps`);
    it reads relevant files and *proposes* edits (staged diffs) to review/apply.
  Every mode ends with a `trace` event (Phase 20): the turn's timed spans +
  token estimate. The assistant reply is persisted; new threads are auto-titled.
- `GET /threads/{id}/traces` → recent per-turn traces for the thread
  (`[{id, mode, total_ms, spans, tokens, created_at}]`), owner-scoped.
- `GET /profile` → durable facts with ids (`{facts: [{id, fact}]}`).
  `DELETE /profile` clears all; `DELETE /profile/{fact_id}` forgets one (Phase 25).
- `POST /auth/refresh` → a fresh token for a still-valid one (sliding session).
  `GET /audit` → this user's recent security events. `/auth/signup` + `/auth/login`
  are rate-limited per client IP (Phase 29).
- `GET /workspace` → the directory code tools operate on (`{root}`, may be null).
  `POST /workspace` — select that directory (`{path}`); validated as an existing
  dir (and inside `WORKSPACE_ALLOWED_BASE` if set). Phase 32.
- `GET /workspace/browse?path=` → subfolders of a directory (`{current, parent,
  dirs}`) so the UI can offer a **click-through folder picker** (the browser can't
  provide absolute paths, so the backend lists the server's directories). Confined
  to `WORKSPACE_ALLOWED_BASE` when set; opens at the home dir otherwise.
- `GET /workspace/edits` → staged code edits (diffs) awaiting approval;
  `POST /workspace/edits/apply` writes them all (confined + audited);
  `POST /workspace/edits/discard` throws them away. Phase 33.
- `GET /skills` → available skill playbooks (name, description, when_to_use);
  `GET /skills/{name}` → the full skill (with steps + context body). Phase 35.
- `POST /threads/{id}/attach` — attach a file (multipart `file`) to *one chat*;
  its content is RAG-usable in that chat only (Phase 30). Rate-limited + size-capped.
  `GET /threads/{id}/attachments` lists them; `DELETE /threads/{id}/attachments/{filename}`
  removes one; deleting the thread removes all of them.
- `POST /feedback` — rate an answer (`{thread_id?, question, answer, rating, note?}`,
  `rating` ∈ `up`/`down`); upserts by (user, thread, answer) so re-rating doesn't
  double-count. `GET /feedback/stats` → `{up, down, total, satisfaction_rate}`.
  `GET /feedback/export` → thumbs-down cases (golden-set candidates). All
  owner-scoped.

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
Ingest a document. Multipart form field `file`; supported: **PDF, DOCX, Markdown,
plain text, HTML** (Phase 26).
Response:
```json
{ "filename": "handbook.pdf", "pages": 2, "chunks_stored": 12, "total_documents": 12 }
```
`api/upload.py` dispatches on extension via `services/extract.extract_file`
(PDF → one segment per page; other formats → a single segment), then the shared
`services/ingest.ingest_segments` runs the pipeline: `recursive_chunk` per
segment → *(Phase 22, optional)* `context.contextualize_all` → `embed_texts`
(batched) → `db.insert_documents`. Each chunk carries `metadata` =
`{source, filename, page, chunk_index, uploaded_at}` (plus `context` when
contextual retrieval is on). Returns 400 for unsupported types or files with no
extractable text (e.g. scanned PDFs).

### `POST /ingest/url`
Ingest a web page. Body `{ url }`. Fetches the page (`urllib`, bounded size +
timeout), extracts visible text with a stdlib HTML parser (scripts/styles
stripped, `<title>` captured), then runs the same `ingest_segments` pipeline with
`source: "url"` and the page URL recorded in `metadata.source_url`. Same response
shape as `/upload`. 400 on fetch/parse failure or empty content.

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
PYTHONPATH="$(pwd)" .venv/bin/python -m eval.run_eval --compare-context  # raw vs contextual
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

### Contextual retrieval (Phase 22)

A chunk pulled from a long document loses what it's *about* ("It increased 3%" —
of what?). `services/context.py` asks the model for a one-sentence context that
situates each chunk in its document; the upload pipeline embeds that
context-prepended text but **stores the original chunk** (so citations and
keyword search stay clean, only the vector sees the context). It's opt-in via
`CONTEXTUAL_RETRIEVAL` (default off — it's one LLM call *per chunk* at ingestion,
slow on the free tier) with a `CONTEXTUAL_MAX_CHUNKS` cap, and falls back to a
heuristic (`"From <title>."`) if the call fails, so ingestion never breaks.

`eval/compare_contextual()` (`--compare-context`) proves the effect: over a
chunked handbook whose passages are ambiguous alone (two sections both starting
"The annual allowance is N days…"), it embeds the chunks raw vs contextualized
and compares **vector** hit@1. Measured **50% → 75% (+25%)** in one run. Honest
caveat: context quality varies — in that run the model labelled the sick-leave
chunk "annual leave", so that question stayed a miss; the technique helps on
average, it isn't magic.

### Feedback loop (Phase 23)

Offline evals score a *fixed* set; real users hit cases we never wrote down.
`services/feedback.py` lets them rate each answer 👍/👎 (with an optional note),
stored with the question + answer text so a row is self-contained. Two payoffs: a
live **satisfaction rate** (`GET /feedback/stats`), and a **flywheel** —
`eval/export_feedback.py` turns thumbs-down cases (the answers the system got
wrong) into golden-set *candidates* (question + downvoted answer + note; a human
fills in the expected doc/fact, since that's the judgment the eval depends on).
Ratings upsert by (user, thread, answer) so re-clicking or adding a note updates
the row instead of inflating the counts.

### Caching (Phase 24)

`services/cache.py` provides two in-memory primitives (an `LRUCache` and a
`TTLCache`, both thread-safe with hit/miss stats) and three caches:

- **embeddings** (LRU, keyed by content hash + dim): identical text always embeds
  to the same vector, so this is never stale — it wraps `gemini.embed_text`, so
  query variants (Phase 21) and repeated questions skip the embed API. No TTL.
- **retrieval** (TTL, keyed by user/mode/k/query **+ a per-user version**):
  wraps `run_search` / `multi_query_search`. Every document write
  (`insert`/`update`/`delete` in `db.py`) calls `cache.bump_user_version`, so a
  cached result can never outlive the data it came from; the TTL is a backstop.
- **responses** (TTL + version): the stateless `/rag/chat` answer, keyed by the
  whole request. Safe because identical input ⇒ identical output; the stream is
  buffered on the first call and replayed on a hit.

`GET /cache/stats` returns hit/miss/size/hit_rate per cache, making the win
observable. Real Gemini *prompt* caching (`CachedContent`) needs a large minimum
token count and isn't reliable on the free tier, so we cache what's safe and
useful instead of adding fragile context-cache code. `embed_texts` (bulk
ingestion of new content) is intentionally not cached — it rarely sees repeats.

### Semantic memory + management (Phase 25)

Phase 13 injected the *entire* profile into every system prompt — fine for a few
facts, wasteful and diluting as it grows. Now `user_facts` carries an `embedding`
per fact, and `profile.relevant_preamble(user_id, message)` injects only the
**top-k facts relevant to the current message** (embed the message → cosine
search over the user's facts). Small profiles (≤ k) skip the ranking and its
embed call entirely and just return everything — cheaper and identical in effect.
Legacy facts from before this phase (NULL embedding) are back-filled lazily the
first time a large profile is read. Management: `GET /profile` now returns facts
with ids and `DELETE /profile/{fact_id}` forgets one, so the UI can show a
per-fact ✕. `preamble()` (all facts) is kept for any non-message-scoped caller.

### More tools (Phase 27)

Two agent tools that go deeper than a search snippet (`services/tools.py`):

- **`fetch_url(url)`** — fetches a page (reusing `extract.fetch_url`) and returns
  its readable text, truncated. Composes with `web_search`: search → pick a
  result → fetch → read → answer.
- **`analyze_csv(csv_text)`** — parses small CSV with the stdlib `csv` module and
  returns columns, row count, per-numeric-column aggregates (sum/mean/min/max),
  and sample rows. Deterministic (no code execution), so the model answers
  tabular questions from *computed* numbers, not guesses.

Both are registered in the local tool registry (declarations + `_FUNCTIONS`) and
exposed via the MCP server, so the in-app agent, plain chat (tool-aware), and
external MCP clients all get them. Verified: an agent given pasted sales CSV
called `analyze_csv` and answered "total revenue is 4,000".

### Workspace + read-only code tools (Phase 32)

The start of the code-editing track — read-only and safety-first.
`services/workspace.py` is the **confinement spine**: the user selects a workspace
directory (`POST /workspace`, stored per user), and `resolve(user_id, rel_path)`
maps any path *inside* that root, rejecting escapes (`..`, absolute paths, symlink
escape) via `os.path.realpath` + a prefix check. It's the single chokepoint every
file operation must pass through. Three tools go through it — `list_dir`,
`read_file` (size-capped, UTF-8 only), and `search_code` (bounded walk skipping
`.git`/`node_modules`/… ) — routed in `dispatch` with the caller's `user_id` (like
`search_documents`) and exposed via MCP. **No write capability in this phase.**
Verified: after selecting a workspace, the tools list/read/search real files, and
every path-escape attempt (`../etc/passwd`, absolute paths, an outside file) is
rejected. A configured root must be inside `WORKSPACE_ALLOWED_BASE` when that
fence is set.

### Code-editing tools (Phase 33)

Write capability, added only after confinement was proven — and never silent.
`services/editor.py` implements **propose → review → apply**: `write_file` and
`edit_file` (exact-match snippet replace, which must match exactly once) compute
the resulting content plus a **unified diff** and *stage* it in an in-memory
buffer; nothing touches disk. `GET /workspace/edits` returns the pending diffs;
`POST /workspace/edits/apply` writes them (re-resolving each path through
`workspace.resolve` at apply time and audit-logging every write); `.../discard`
drops them. Content is size-capped, paths are confined at both propose and apply
time, and the tools are user-scoped in `dispatch`. Verified end-to-end: a proposed
edit returns a diff and writes nothing until applied; applying updates the files
and logs `code.edit_applied`; edits outside the workspace are rejected and never
staged; ambiguous/missing snippets are refused; discard clears the buffer. (No
editing over MCP — MCP clients have no approval step, so it stays read-only.)

### Coding agent — `code` mode (Phase 34)

`code` mode runs the ReAct loop (`run_tool_loop`) with the workspace tools and a
coding-focused prompt (`build_code_system_prompt`): explore with
`list_dir`/`search_code`, `read_file` before editing, then propose edits with
`edit_file`/`write_file` — which stage diffs, not silent writes. It gets a higher
tool-step budget (`code_max_steps`, default 12) because it explores more than a
normal agent turn. Each read/edit surfaces as a tool event + trace span. Verified
end-to-end: given "change greet to return 'hi there'", the agent listed the dir,
read the file, called `edit_file` (staged), summarised the proposal without
claiming it was applied, and a subsequent apply wrote it to disk.

Note: if the user has an external filesystem MCP server configured, the agent may
also use its tools; those are governed by *that server's* own sandbox, not our
workspace confinement — our native code tools remain confined via
`workspace.resolve`.

### Skills framework (Phase 35)

A skill is a Markdown playbook in `backend/skills/` — frontmatter (`name`,
`description`, `when_to_use`) plus a body of ordered **steps** and **context**
pointers (which files to read, which conventions to follow). `services/skills.py`
discovers them (frontmatter parsed by hand, no YAML dep), and `catalog()` injects
a one-line-per-skill list into the agent/code prompts so the model knows what
exists. The `use_skill(name)` tool loads a skill's body into the agent's working
context, so it starts a recurring task already informed instead of rebuilding
understanding each time. `GET /skills` / `GET /skills/{name}` expose them; the
tool is also available over MCP. Verified: the agent, asked how to add a tool,
called `use_skill("add-a-tool")` and answered with the playbook's steps. The
initial library is authored in Phase 36.

### Security hardening (Phase 29)

- **Rate limiting** (`services/ratelimit.py`) — a thread-safe in-process
  fixed-window counter (no Redis needed on one process). The `rate_limited_user_id`
  dependency guards expensive endpoints (chat, upload, ingest) per user; auth
  endpoints are limited per client IP. Over the limit → **429**.
- **Input caps** — messages over `MAX_MESSAGE_CHARS` and uploads over
  `MAX_UPLOAD_BYTES` are rejected with **413** before touching the model or DB.
- **Prompt-injection guardrails** — the RAG system prompt now explicitly says the
  context is untrusted *data*, never instructions; `services/guard.py` also
  heuristically flags retrieved chunks that look injected ("ignore previous
  instructions", "system prompt", …) and records a `rag.injection_flagged` audit
  event. Detection-only (heuristics have false positives) — the prompt is the
  real defence.
- **Audit log** (`services/audit.py`) — signups, logins (incl. failures),
  uploads, URL ingests, and injection flags are written to an `audit_log` table;
  `GET /audit` returns the user's own events. Best-effort (never breaks the
  action).
- **Token refresh** — `POST /auth/refresh` exchanges a still-valid token for a
  fresh one (sliding session). Honest scope note: a production system would use a
  separate, server-side revocable refresh token; this is the lightweight version
  for a $0 single service.
