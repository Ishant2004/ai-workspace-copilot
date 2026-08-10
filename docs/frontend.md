# Frontend

React + TypeScript + Tailwind (built with Vite). A single-page chat UI.

## Files

| File | Responsibility |
| ---- | -------------- |
| `index.html` | HTML entry point; mounts the React app into `#root`. |
| `src/main.tsx` | React bootstrap. |
| `src/App.tsx` | App shell: header + tabs. Keeps all tabs mounted (see below). |
| `src/components/Chat.tsx` | Chat UI: thread sidebar, RAG toggle, sources (Phases 0/4/9). |
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

**Search modes (Phase 7):** the Search box has a `hybrid` / `vector` / `keyword`
toggle passed to `POST /api/search`. Each result shows a `vector` / `keyword`
badge (`matched_by`) so you can see which retriever(s) found it; the cosine
`% match` badge only appears when there's a vector score.

**Rerank (Phase 8):** a "Rerank" checkbox adds `rerank: true` to the request.
When on, results carry a `rerank_score`, shown as a green `rerank X.XX` badge —
the cross-encoder's confidence, usually far sharper than the cosine scores.

## Chat tab: threads + RAG (Phases 4 & 9)

The Chat tab is a two-pane layout: a **sidebar** listing conversations (with
"New chat" and per-row delete) and the conversation itself.

- Selecting a thread loads its history from `GET /api/threads/{id}/messages`.
- Sending posts only the new message to `POST /api/threads/{id}/chat`
  (`streamThreadChat`); a thread is created lazily on the first send. When the
  stream finishes, the sidebar refreshes to pick up the auto-title.
- A **Chat / RAG / Agent / Plan** mode selector sets the `mode` on the request:
  - *RAG* answers additionally receive a `sources` event → "Sources:" chip strip.
  - *Agent* (Phase 11) answers receive `tool_call` / `tool_result` events,
    rendered as amber **step cards** above the final answer.
  - *Plan* (Phase 12) answers receive a `plan` event plus per-step
    `step_start` / `tool_call` / `tool_result` / `step_result`, rendered as a
    numbered **plan card** that fills in each step's tools and result as it runs.
    (Tool events are attributed to the current step by capturing the step index
    at event time — React batches state updates, so reading it lazily would
    misattribute them.)
  - *Team* (Phase 16) answers receive `agent_start` / `agent_message` events,
    rendered as violet **role cards** (Planner, Retriever, Solver, Reviewer)
    above the final answer bubble.
  - *Every* mode ends with a `trace` event (Phase 20), rendered as a collapsible
    **`TraceView`** under the answer: "⏱ 3.1s · ~180 tok · N steps", expanding to
    a per-span timeline (retrieval, each tool call, generation) with mini bars.
  - *(Phase 23)* every assistant answer shows a **`Feedback`** control (👍/👎; a
    👎 reveals an optional note). Ratings post to `/feedback` (using the preceding
    user message as the question) and the sidebar shows a running **satisfaction
    rate** from `/feedback/stats`.

All streaming shares one SSE reader (`streamSse` in `api.ts`) with optional
`onSources` / `onTrace` handlers. Messages are stored as `DisplayMessage` (a
`Message` plus optional `sources`, `steps`, `plan`, `agents`, and `trace`).

> Note: the agent (Phase 11) reuses the SSE reader's optional `onToolCall` /
> `onToolResult` handlers. The standalone Tools tab from Phase 10 was folded
> into the chat's Agent mode and removed.

## Memory panel (Phase 13)

The chat sidebar shows a **Memory** panel: the durable facts the assistant has
learned about the user (`GET /api/profile`), with a **Forget** button
(`DELETE /api/profile`). It refreshes on load and ~1.5s after each turn (fact
extraction runs in the background server-side, so we re-fetch shortly after).

Phase 25: each fact is listed with its id and a per-fact **✕** that forgets just
that one (`DELETE /api/profile/{id}`, optimistic remove). Server-side, only the
facts *relevant* to the current message are injected into the prompt, not the
whole list — so the panel can grow without bloating every request.

## Stopping a response

The input's **Send** button becomes a red **Stop** while a response is
streaming. `send()` creates an `AbortController` and passes its `signal` through
`streamThreadChat` → `streamSse` → `fetch`. Clicking Stop aborts the request;
`streamSse` treats an abort as a graceful end (keeps whatever streamed so far,
raises no error), and a `finally` in `send()` resets the busy state. This is the
escape hatch when the model is slow or hangs.

## Mobile / responsive

The UI adapts to small screens:
- **Header tabs** sit in a horizontally-scrollable strip (`no-scrollbar`), and
  "Sign out" moves next to the title on mobile.
- The **chat sidebar** (conversations + memory) is a static column on `sm+` but a
  slide-over **drawer** on mobile, opened by a "☰ Chats" button and dismissed by
  tapping the backdrop or picking a chat.
- The **mode selector** and long rows scroll horizontally rather than overflow.

Tailwind's `sm:` breakpoint (640px) is the divider; `index.html` sets the
`viewport` meta so it scales correctly on phones.

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
