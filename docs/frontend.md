# Frontend

React + TypeScript + Tailwind (built with Vite). A single-page chat UI.

## Files

| File | Responsibility |
| ---- | -------------- |
| `index.html` | HTML entry point; mounts the React app into `#root`. |
| `src/main.tsx` | React bootstrap. |
| `src/App.tsx` | App shell: header + tabs. Keeps all tabs mounted (see below). |
| `src/components/Chat.tsx` | Chat UI + RAG toggle and sources strip (Phases 0 & 4). |
| `src/components/TokenInspector.tsx` | Phase 1: live token metrics for typed text. |
| `src/components/EmbedInspector.tsx` | Phase 2: embeds text and visualises the vector. |
| `src/components/VectorSearch.tsx` | Phases 3 & 5: add/upload docs + semantic search. |
| `src/services/api.ts` | Calls chat, tokenize, embed, documents, search. |
| `src/index.css` | Imports Tailwind. |
| `vite.config.ts` | Dev server + proxy (`/api` → backend on :8000). |

## Tab state persistence

All four tab components stay **mounted** for the whole session. `App.tsx`
renders each inside a `TabPanel` that hides the inactive ones with `hidden`
(`display:none`) instead of removing them from the tree.

Why: React keeps a component's state only while it's mounted. The earlier
version rendered `{tab === "chat" && <Chat />}`, which unmounted the previous
tab on every switch — so your chat history, typed text, and search results were
thrown away. Keeping the components mounted preserves all of that; switching
tabs just toggles visibility.

## How streaming works on the client

The browser's built-in `EventSource` only does GET requests, but we need to
POST the message history. So `services/api.ts` uses `fetch()` and reads the
response body as a stream:

1. Read raw bytes from `response.body.getReader()`.
2. Decode to text and accumulate in a buffer.
3. Split on the blank line (`\n\n`) that separates SSE events.
4. Parse each `data: {...}` payload and call the right handler
   (`onChunk`, `onDone`, `onError`).

`App.tsx` reacts to those handlers by appending text to the last (assistant)
message in React state, so the bubble fills in live.

## Token Inspector (Phase 1)

`TokenInspector.tsx` counts characters and words instantly in the browser, but
the exact **token** count must come from the model's tokenizer. To avoid one
API call per keystroke, it **debounces**: it waits ~600ms after you stop typing,
then calls `POST /api/tokenize`. A pending call is cancelled if you type again.

## Embeddings viewer (Phase 2)

`EmbedInspector.tsx` sends text to `POST /api/embed` (debounced) and renders the
returned vector two ways:

- a **bar strip** (blue = positive, red = negative, height = magnitude), and
- a **number grid** where each value is a chip showing its dimension index,
  the signed value, and a subtle magnitude fill — so the vector is scannable
  rather than a wall of digits.

A segmented toggle chooses how many of the 768 values to show (12 / 28 / 52 /
100); both views react to it. The goal is intuition — seeing that "meaning" is
just a long list of numbers.

## Vector Search (Phase 3)

`VectorSearch.tsx` is one screen with three parts:
- **Add / edit a document** → the same form does both. `POST /api/documents`
  when adding; clicking *Edit* on a stored doc loads it into the form and the
  button becomes *Save changes* (`PUT /api/documents/{id}`), with *Cancel* to
  exit edit mode.
- **Stored documents** → a list of everything in the DB (`GET /api/documents`),
  each row with *Edit* and *Delete* (`DELETE /api/documents/{id}`) buttons.
- **Search** → `POST /api/search`, rendering each hit with a colour-coded
  similarity badge (green ≥70%, amber ≥50%, grey below).

The list is the source of truth for the doc count badge; it refreshes on load
and after every add/edit/delete. If the DB isn't reachable it shows a friendly
hint about `DATABASE_URL`.

**Upload a PDF (Phase 5):** a file input sends the chosen PDF to `POST
/api/upload` as multipart form data (`uploadPdf` in `api.ts`). On success it
shows how many chunks were stored and refreshes the list — the new chunks appear
as `filename · pN · chunk i/n` documents.

**Metadata badges (Phase 6):** stored documents and search results render a
small `MetaLine` — a `filename` and `p.N` badge — read from each item's
`metadata` (source, filename, page). It renders nothing for rows without useful
metadata.

## RAG in the Chat tab (Phase 4)

The Chat tab has a checkbox: **"Ground answers in my documents (RAG)"**. When
off, sending calls `streamChat` (`/api/chat`). When on, it calls `streamRag`
(`/api/rag/chat`), which additionally receives a `sources` event.

Both share one SSE reader (`streamSse` in `api.ts`); the only difference is the
URL and the optional `onSources` handler. Messages are stored as
`DisplayMessage` (a `Message` plus an optional `sources` array); only
`{role, content}` is sent to the backend. RAG answers render a small "Sources:"
strip of `[#id] title` chips beneath the bubble.

## The `/api` proxy

In development the frontend runs on port 5173 and the backend on 8000. Vite
proxies any request starting with `/api` to the backend (stripping the `/api`
prefix). This means frontend code uses relative URLs and we sidestep CORS
locally.

## Running locally

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 (make sure the backend is running too).
