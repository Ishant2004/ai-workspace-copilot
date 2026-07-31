# Architecture & Mental Map

This document is the "big picture" of the AI Workspace Copilot. It grows one
phase at a time. Read it top-to-bottom to understand how the pieces fit.

## What we are building

One application that we keep improving until it behaves like a production AI
assistant (RAG, tools, agents, MCP), built entirely on free-tier services.

## The mental model

Think of the system as a request flowing left-to-right:

```
Browser (React)  ──HTTP/SSE──►  FastAPI backend  ──►  Gemini LLM
```

- The **frontend** is a dumb terminal: it collects user input, shows replies,
  and knows nothing about how answers are produced.
- The **backend** is the brain. Today it only forwards messages to Gemini.
  Over the coming phases it will gain RAG, tools, memory, and agents.
- The **LLM (Gemini)** is stateless. It has no memory of past turns — we resend
  the whole conversation on every request. Everything "smart" we add later is
  really about *what context we choose to feed the LLM*.

## Phases implemented so far

| Phase | Feature | Status |
| ----- | ------- | ------ |
| 0 | ChatGPT-style streaming chat | ✅ Done |
| 1 | Token inspector | ✅ Done |
| 2 | Embedding service | ✅ Done |
| 3 | Vector database (pgvector) | ✅ Done |
| 4 | RAG (grounded answers) | ✅ Done |
| 5 | PDF upload & ingestion | ✅ Done |
| 6 | Advanced chunking & metadata | ✅ Done |
| 7 | Hybrid search (keyword + vector, RRF) | ✅ Done |
| 8 | Reranker (cross-encoder) | ✅ Done |
| 9 | Conversation memory & threads | ✅ Done |
| 10 | Tool calling (function calling) | ✅ Done |
| 11 | ReAct agent (in chat) | ✅ Done |
| 12 | Planning & task execution | ✅ Done |
| 13 | Long-term user profile memory | ✅ Done |
| 14 | MCP server | ✅ Done |
| 15 | External MCP connectors | ✅ Done |
| 16 | Multi-agent system | ✅ Done |

## Current data flow (Phase 0)

```
1. User types a message in the React UI.
2. Frontend sends the FULL message history to POST /api/chat.
3. Backend converts messages to Gemini's format and opens a streaming call.
4. Gemini emits the answer token-by-token.
5. Backend wraps each token as a Server-Sent Event (SSE) and streams it back.
6. Frontend appends each token to the on-screen assistant bubble in real time.
```

## Phase 1: why tokens matter

LLMs don't read characters or words — they read **tokens** (sub-word chunks).
Every context-window limit and every price is measured in tokens. The Token
Inspector makes this visible: type text and see its exact token count (from the
model's own tokenizer), how much of the context window it uses, and what it
would cost. This is the mental foundation for everything that follows — RAG,
memory, and agents are all about *choosing which tokens to spend*.

Flow: `UI textarea` ➔ (debounced) `POST /api/tokenize` ➔ `Gemini count_tokens`
➔ metrics rendered as cards. Character/word counts are computed instantly in
the browser; only the exact token count needs the backend.

## Phase 2: embeddings

An **embedding** maps text to a fixed-length vector of numbers (768 dims here)
such that similar meanings produce vectors pointing in similar directions.
Measuring the angle between two vectors (cosine similarity) tells you how
related two pieces of text are — regardless of exact wording.

We verified this: "The cat sat on the mat" is much closer to "A kitten is
resting on a rug" (0.73) than to "Quarterly revenue grew 12%" (0.53).

This is the engine of semantic search. In the next phases we will store these
vectors in a database (Phase 3) and use them to retrieve relevant context for
the LLM (RAG, Phase 4).

Flow: `UI textarea` ➔ (debounced) `POST /api/embed` ➔ `Gemini embed_content`
➔ vector normalized to unit length ➔ rendered as bars.

Key choice: **dimension is fixed by config** (`GEMINI_EMBED_DIM`, default 768).
Every document must be embedded with the same model and dimension, or the
vectors are not comparable. This value becomes the pgvector column size in
Phase 3.

## Phase 3: the vector database

We now have somewhere to *keep* embeddings and search them. It's Postgres (free
Neon instance) with the `pgvector` extension. One table:

```
documents(id, title, text, embedding vector(768), created_at)
```

Full CRUD plus search:
- **Store** (`POST /documents`): embed the text, insert the row.
- **List** (`GET /documents`): all documents (without the raw vectors).
- **Update** (`PUT /documents/{id}`): re-embed the new text and replace the row
  — the stored vector always matches the stored text.
- **Delete** (`DELETE /documents/{id}`): remove a document.
- **Search** (`POST /search`): embed the query, then ask Postgres for the rows
  whose `embedding` is nearest to the query vector using the cosine-distance
  operator `<=>`. We return `1 - distance` as a 0..1 similarity score.

Verified live: the query "Can I get my money back if I don't like the product?"
ranked a "Refund policy" document (69%) above an unrelated "Shipping" document
(53%) — despite sharing **no keywords** with it. That is the payoff of vector
search: it matches meaning, not words.

Two implementation gotchas worth remembering (both handled in `services/db.py`):
1. `register_vector` needs the extension to already exist, so `init_db` creates
   the extension on a connection with the adapter *off*, then everything else
   uses it *on*.
2. A Python list is sent to Postgres as a `float8[]`, which has no `<=>`
   operator — so the query casts the parameter with `::vector`.

The database is initialised automatically on backend startup (see the
`lifespan` handler in `main.py`). If `DATABASE_URL` is unset, the app still runs
— only `/documents` and `/search` are unavailable.

## Phase 4: RAG (Retrieval-Augmented Generation)

This is where the pieces click together. Plain chat (Phase 0) answers from the
model's own memory — it can't know anything about *your* documents, and it may
confidently make things up. RAG fixes both by grounding the answer in retrieved
documents:

```
question ─► embed (Phase 2) ─► vector search top-k (Phase 3)
        ─► build grounded prompt (prompts.py) ─► Gemini (Phase 0 streaming)
        ─► stream answer with [#id] citations
```

The grounding lives entirely in the **prompt**: we put the retrieved documents
into a system instruction that says "answer using ONLY this context, cite by
[#id], and if it's not here say you don't know." The model itself is unchanged —
RAG is a *context* technique, not a *model* technique. This is the single most
important idea in the whole roadmap: making the model smarter is mostly about
choosing what to put in its context.

The `/rag/chat` endpoint streams the same SSE as `/chat`, with one extra event
first: a `sources` event listing the retrieved documents, so the UI can show
exactly what the answer was based on. In the Chat tab a checkbox toggles RAG on;
answers then show a "Sources" strip beneath them.

Verified: with three HR-policy documents stored, "How many vacation days do I
get, and can I work from home?" produced a two-part answer citing both the PTO
and Remote-Work docs ([#1], [#2]); an off-topic question ("stock price today?")
correctly returned "I don't know based on the available documents."

> The public Gemini free tier intermittently returns `503 UNAVAILABLE` ("high
> demand"). Our streaming surfaces that as an error event rather than hanging.
> It is transient — retrying succeeds.

## Phase 5: PDF upload & ingestion

Until now documents were pasted in by hand. Phase 5 lets you drop in a whole PDF
and have it become searchable. The ingestion pipeline (`api/upload.py`):

```
PDF bytes ─► extract text (pypdf) ─► split into overlapping chunks
         ─► embed all chunks in one batched call ─► store each chunk as a document
```

Why **chunk** at all? An embedding is a single fixed-length vector, so it can
only capture a limited span of text well. A whole PDF embedded as one vector
would be a blurry average — useless for retrieval. Splitting into ~800-char
chunks (with 100-char overlap so boundary sentences aren't lost) means search
can pinpoint the exact passage that answers a question. Each chunk is stored as
an ordinary document row (`filename · chunk i/n`), so it's instantly usable by
Phase 3 search and Phase 4 RAG with no extra code.

Why **batch** the embeddings? One API round-trip for all chunks instead of one
per chunk — far faster and easier on rate limits (`embed_texts` in
`services/gemini.py`).

Verified: uploading a 1-page handbook PDF produced 2 chunks, and a query about
"parental leave" retrieved the correct chunk.

> Not done yet (optional): the plan also stores the *raw* PDF file in Cloudflare
> R2. That's just blob storage of the original and needs another free signup, so
> it's deferred — the searchable content already lives in Postgres.

## Phase 6: advanced chunking & metadata

Phase 5's chunker cut blindly every N characters, which can slice a sentence — or
a word — in half. Phase 6 makes retrieval better in two ways:

**Recursive (boundary-aware) chunking** (`services/chunking.py`). Instead of a
hard cut, we try to break on natural boundaries first — paragraphs (`\n\n`),
then lines, then sentences (`. `), then spaces — only falling back to a
character cut when nothing fits, with overlap carried between chunks. Chunks
stay semantically whole, so their embeddings (and retrieval) are cleaner.

**Metadata** (a JSONB `metadata` column on `documents`). Every chunk now records
where it came from: `source` (`pdf`/`manual`), `filename`, `page`,
`chunk_index`, and a timestamp. Because PDFs are now extracted **per page**,
each chunk knows its page number. Metadata rides along through search and the
list API, and the UI shows a small `filename` / `p.N` badge on each result —
so an answer can be traced back to a specific page of a specific file.

The column is added with `ADD COLUMN IF NOT EXISTS ... DEFAULT '{}'`, so existing
databases upgrade in place without losing data.

Verified: a 2-page PDF produced 12 chunks tagged `page: 1` / `page: 2`; a query
about "laptop encryption" retrieved a page-2 chunk, and the UI rendered the
`twopage.pdf` / `p.2` badges.

> Raw-file storage (Cloudflare R2) and OCR for scanned PDFs were prototyped but
> rolled back to keep the diff focused; they can be re-added later. The
> searchable content lives in Postgres regardless.

## Phase 7: hybrid search

Vector search matches *meaning* but can miss exact terms — names, codes, rare
words that don't embed well (e.g. an error code `ERR-4021`). Keyword search
(Postgres full-text) matches *words* but is blind to synonyms and paraphrasing.
Hybrid search runs both and fuses them, getting the best of each.

- **Keyword** (`db.keyword_search`): a generated `text_search tsvector` column
  (from title+text, GIN-indexed) matched with `websearch_to_tsquery` and scored
  by `ts_rank`.
- **Vector** (`db.search`): the Phase 3 cosine search.
- **Fusion — Reciprocal Rank Fusion** (`services/search.py`): pull the top ~20
  from each retriever, then score every document by `sum(1 / (k + rank))` across
  the lists (k=60). RRF uses only *ranks*, not the raw scores (which live on
  incomparable scales), so no normalization is needed. A document ranked well by
  either retriever surfaces; one ranked well by *both* wins.

`POST /search` takes a `mode` of `vector` | `keyword` | `hybrid` (default
hybrid). Each hit reports `matched_by` (which retrievers found it) and, for
hybrid, an `rrf_score`. The Vector Search tab has a mode toggle and shows a
`vector` / `keyword` badge on each result.

Verified: `mode=keyword` for "ERR-4021" returned only the exact-match doc;
`mode=hybrid` for "expired token" ranked the doc matched by **both** retrievers
first (RRF ≈ 0.033, cosine 72%) above vector-only matches.

## Phase 8: reranking

Retrieval (any mode above) is a **bi-encoder**: it embeds the query and each
document *separately* and compares the vectors. That's fast (documents are
pre-embedded) but approximate — it's good at "roughly about the same thing", weak
at fine ordering. A **cross-encoder** instead reads the query and a candidate
*together* and outputs a single relevance score. Much more accurate, but too slow
to run over the whole corpus.

The standard two-stage pattern: **retrieve ~20 cheap candidates, then rerank them
down to the best few.** We use **FlashRank** (`services/rerank.py`) — a small
cross-encoder (`ms-marco-MiniLM-L-12-v2`, ~34MB) that runs in-memory on CPU via
ONNX, no GPU or API. The model loads lazily on first use.

`POST /search` takes `rerank: true`; `run_search` then pulls
`rerank_candidates` (20) via the chosen mode and trims to k with the
cross-encoder. Each hit gains a `rerank_score`. The Vector Search tab has a
"Rerank" checkbox and shows the score as a badge.

Verified: for "how do I get a refund for an unused item?", retrieval returned
five docs with *clustered* cosine scores (0.81 / 0.62 / 0.58 / 0.56 / 0.49) —
close enough that the ordering is shaky. The reranker scored the true answer
(Return policy) **0.98** and every distractor **~0.00**: a far sharper, more
confident ranking. That precision boost is the whole point of stage-two
reranking.

## Phase 9: conversation memory & threads

The LLM is **stateless** — it only knows what's in the prompt. Everything that
feels like "memory" is something *we* store and replay. Until now the frontend
held the conversation in React state and resent it each turn; refresh the page
and it was gone. Phase 9 makes conversations durable.

Two Postgres tables (`services/threads.py`):

```
threads(id, title, created_at)
messages(id, thread_id → threads, role, content, created_at)
```

The flow changes: the frontend now sends only the **new** message to
`POST /threads/{id}/chat`. The backend:
1. saves the user message (so it survives even if generation fails),
2. auto-titles a new thread from its first message,
3. replays a **sliding window** — the most recent `history_window` (20)
   messages — to the model, so the prompt (and cost) stays bounded no matter how
   long the conversation grows,
4. streams the reply, then saves the assistant message.

Reloading a thread (`GET /threads/{id}/messages`) reconstructs the whole
conversation. The Chat tab now has a sidebar: new chat, switch between past
conversations, delete (cascade removes its messages). RAG still works per-turn
via the `rag` flag, which retrieves with hybrid search and grounds the answer.

Verified: threads persist across restarts; the sliding window returns only the
last N messages oldest-first; the sidebar lists/loads/deletes conversations; and
a "what is my name?" follow-up was answered correctly from earlier turns —
memory recall working.

> The optional Upstash Redis cache from the plan is deferred: Postgres already
> gives durable history, and the sliding window needs no external cache. Redis
> would be a latency optimization for very high traffic.

## Phase 10: tool calling (function calling)

An LLM only emits text — it can't fetch live data or compute. **Tool calling**
bridges that: we give the model a list of tool *declarations* (name,
description, JSON-schema arguments); when it needs one, it replies with a
structured `function_call` instead of prose. We run the real Python function and
hand the result back, and the model continues with that knowledge.

The loop is written explicitly (rather than the SDK's automatic function
calling) so the mechanics are visible (`services/tools.py`):

```
prompt + tool declarations ─► model
   ├─ returns function_call(s) ─► we execute ─► return results ─► (repeat)
   └─ returns text ─► final answer
```

Three tools ship: `calculate` (safe arithmetic via an AST evaluator — never
`eval`), `get_current_time`, and `search_documents` (runs Phase 7 hybrid search
over the knowledge base). A `MAX_STEPS` cap prevents runaway loops.

`POST /tools/chat` streams the *whole* process as SSE — `tool_call`,
`tool_result`, then the final answer — and the Tools tab renders it as a
timeline. Verified: "What is 128 * 47?" → model calls
`calculate({"expression":"128 * 47"})` → result `6016` → answer "128 * 47 =
6,016"; and "what is the office wifi password?" → model calls
`search_documents` → answers from the retrieved chunk.

This is the foundation of the next phase: an **agent** is just this loop plus
reasoning about *which* tools to call and *when* to stop.

## Phase 11: the ReAct agent (in the chat)

Phase 10 proved the mechanics in a throwaway tab. Phase 11 makes it a real
feature: the agent lives **inside the chat**, with full conversation history,
and the tool loop *is* the agent's reasoning cycle — **Re**ason → **Act** (call
a tool) → observe the result → repeat until it can answer.

The Chat tab now has a three-way mode selector:

- **Chat** — plain conversation.
- **RAG** — always retrieve documents and ground the answer (Phase 4).
- **Agent** — the model *decides* what to do: it may call `search_documents`,
  `calculate`, `get_current_time`, chain several calls, and then answer. An
  agent system prompt (`prompts.build_agent_system_prompt`) tells it which tool
  fits which job.

`POST /threads/{id}/chat` gained a `mode` field. In agent mode the endpoint runs
`tools.run_tool_loop` over the thread's recent history and streams the same
`tool_call` / `tool_result` events (rendered inline as amber step cards) before
the final answer; both the question and answer are persisted like any turn.

Verified end-to-end in the UI: "What is the monthly membership cost? Look it up
and compute it." → the agent called `search_documents` (found "annual fee 240,
billed monthly"), then `calculate("240 / 12")` → 20, then answered "$20.00 …
dividing the annual fee of $240 by 12 months." Two different tools, chosen and
chained autonomously, inside a persisted conversation.

> The difference from RAG: RAG *always* retrieves and is told to answer only
> from documents. The agent retrieves *only if it decides to*, and can combine
> retrieval with computation or other tools — a strict superset of behaviours.

## Phase 12: planning & task execution

The Phase 11 agent is *reactive* — it picks the next tool one step at a time,
which can wander on complex, multi-part goals. A **plan-and-execute** agent
(`services/planner.py`) instead commits to a strategy first:

1. **Plan** — the model returns an explicit, ordered list of subtasks as JSON
   (forced with a `response_schema`, so parsing is reliable).
2. **Execute** — each subtask is run by the Phase 11 tool agent, with prior
   results fed forward and **retries** (`MAX_RETRIES`) around transient model
   errors. Each step reports its own result.
3. **Synthesize** — the model writes the final answer from all step results.

This is the fourth chat **mode** ("Plan"). `POST /threads/{id}/chat` streams the
plan (`plan` event), each step's boundary and tools (`step_start`, `tool_call`,
`tool_result`, `step_result`), then the final `answer`. The UI renders a numbered
plan card where each step fills in its tools and result as it runs.

Verified: "Find the Pro plan price per seat, then compute the annual cost for a
team of 8." → planned two steps → step 1 `search_documents` ("$30/seat/mo") →
step 2 `calculate("30 * 8 * 12")` = 2880 → answer "$2,880 annual for a team of
8." The plan made the two-part strategy explicit before executing it.

> Reactive (Phase 11) vs. plan-first (Phase 12) are complementary: reactive is
> lighter for simple asks; planning shines when a request has clear sequential
> parts. Both reuse the same tools.

## Phase 13: long-term user profile memory

Phase 9 gives *per-conversation* memory (a thread's messages). Phase 13 adds
memory that spans *every* conversation: durable facts about the user — name,
role, preferences — kept in a `user_facts` table (`services/profile.py`).

- **Learn** — after each user turn, a fire-and-forget background thread asks the
  model to extract durable facts (ignoring one-off questions) as JSON and stores
  the new ones (`fact` is UNIQUE, so duplicates are ignored). It's best-effort
  with retries and never blocks or breaks the chat.
- **Remember** — every new turn injects those facts as a `preamble()` at the top
  of the system prompt (for chat / RAG / agent modes), so the assistant knows
  the user in any thread.

`GET /profile` lists the facts; `DELETE /profile` forgets them. The Chat sidebar
shows a **Memory** panel of the current facts with a **Forget** button.

Verified: telling the assistant "I'm Rajat, a backend engineer who prefers
Python…" stored four facts, and a brand-new conversation answered "What's my
name?" with "Your name is Rajat, and you prefer Python" — recall across threads.
The Memory panel renders the facts and Forget clears them.

> Server-side robustness added alongside this phase: a hard `gemini_request_timeout`
> (default 60s) on the Gemini client so a hung call fails fast instead of
> blocking forever — the complement to the client-side Stop button.

## Phase 14: MCP server

So far the tools (Phases 10–12) served *our* agent. **MCP (Model Context
Protocol)** is an open standard that lets *other* AI apps — Claude Desktop,
Cursor — discover and call tools over a common wire protocol. Phase 14 exposes
our capabilities through it.

`backend/mcp_server.py` (built with the `mcp` SDK's `FastMCP`) publishes three
tools — `search_documents`, `calculate`, `get_current_time` — over **stdio**,
the transport those clients use to launch and talk to a local server. Crucially,
the MCP tools call the *same* `services/tools.py` functions the in-app agent
uses: one implementation, two front doors.

To make it launchable from anywhere (a client sets an arbitrary working
directory), `config.py` now resolves `.env` by absolute path.

Verified with an MCP stdio client: it listed all three tools, `calculate("6*7")`
returned `42`, and `search_documents("wifi password")` returned a stored chunk
via real embeddings + pgvector. See [mcp.md](mcp.md) for Claude Desktop / Cursor
connection config.

## Phase 15: connecting external MCP servers

Phase 14 exposed our tools *to* the world; Phase 15 pulls the world's tools *in*.
Our agent becomes an MCP **client**: it connects to third-party MCP servers
(filesystem, GitHub, Postgres, …), **discovers their tools at runtime**, and adds
them to the same agent loop — no per-integration code. That's MCP's payoff:
tools are discovered, not hard-wired.

- **Config**: `backend/mcp_servers.json` lists servers to launch (command, args,
  env). See `mcp_servers.example.json`. If absent, the feature is simply dormant.
- **Discovery** (`services/mcp_client.py`): connect to each server over stdio,
  `list_tools`, and expose each under a namespaced name `"<server>__<tool>"`
  (so names never collide). Cached after first use.
- **Schema bridge** (`services/tools.py`): each external tool's JSON-Schema is
  converted to Gemini's `Schema` so the model can call it like any local tool.
- **Dispatch**: unknown (non-local) tool names route to `mcp_client.call_tool`,
  which connects and invokes the real server.

The async MCP SDK is bridged to our synchronous agent loop with `asyncio.run`
(connect-per-operation) — simple and adequate at this scale.

`GET /mcp/tools` lists the discovered external tools.

Verified: with the official filesystem MCP server configured (`npx
@modelcontextprotocol/server-filesystem` over a sandbox dir), discovery returned
14 tools, the agent's declaration set grew from 3 → 17, and a direct call to
`filesystem__read_text_file` returned the sandbox file's contents ("Secret code:
OWL-7788"). (The live LLM-picks-the-tool demo was blocked by intermittent model
504s, but the integration path is identical to the verified local-tool agent.)

## Phase 16: multi-agent system

Phases 11–12 were a single agent. Phase 16 uses a small **team of specialists**,
each with its own narrow role and system prompt, wired together by a lightweight
Python **coordinator** (`services/coordinator.py`) — no framework:

```
Planner  → outlines the approach
Retriever → gathers relevant context (hybrid search over the KB)
Solver   → drafts an answer from the plan + context
Reviewer → checks and polishes it into the final answer
```

Each stage's output feeds the next. Splitting one big task into focused,
single-purpose prompts generally beats a do-everything prompt, and it makes the
reasoning visible: the Chat tab's new **Team** mode streams each agent's
contribution (`agent_start` / `agent_message` events) as its own card, then the
Reviewer's polished output as the final answer.

Verified end-to-end (backend + UI): with an "Onboarding" doc stored, the goal
"What should a new hire expect in their first week?" ran all four roles in order —
Retriever found the Onboarding doc — and the Reviewer produced a grounded final
answer ("receive your laptop on day one… complete security training…").

> This reuses everything built so far: the Retriever is Phase 7 hybrid search,
> the sub-agents are Phase 0 generation with role prompts, and the whole thing
> persists as a normal thread (Phase 9). Composition, not new machinery.

## Why streaming (SSE)?

A full LLM answer can take several seconds. Streaming shows the first words
almost immediately, so the UI feels alive instead of frozen. We use SSE (a
one-way server→client stream over plain HTTP) because it is simpler than
WebSockets and perfectly suited to "server pushes text as it's ready".

## Repo layout

```
backend/     FastAPI app (the brain)
  api/       HTTP endpoints
  services/  Integrations with external systems (Gemini today)
  config.py  All environment-driven settings
  models.py  Pydantic request/response schemas
frontend/    React + TypeScript + Tailwind (the UI)
  src/services/  Client-side API calls
docs/        These documents
```

See [backend.md](backend.md) and [frontend.md](frontend.md) for details.
