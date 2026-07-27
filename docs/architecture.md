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
