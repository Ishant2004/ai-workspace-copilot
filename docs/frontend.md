# Frontend

React + TypeScript + Tailwind (built with Vite). A single-page chat UI.

## Files

| File | Responsibility |
| ---- | -------------- |
| `index.html` | HTML entry point; mounts the React app into `#root`. |
| `src/main.tsx` | React bootstrap. |
| `src/App.tsx` | App shell: header + tabs (Chat / Token Inspector / Embeddings). |
| `src/components/Chat.tsx` | The chat UI: message list, input box, send logic. |
| `src/components/TokenInspector.tsx` | Phase 1: live token metrics for typed text. |
| `src/components/EmbedInspector.tsx` | Phase 2: embeds text and visualises the vector. |
| `src/services/api.ts` | Calls `/api/chat` (SSE), `/api/tokenize`, `/api/embed`. |
| `src/index.css` | Imports Tailwind. |
| `vite.config.ts` | Dev server + proxy (`/api` → backend on :8000). |

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
