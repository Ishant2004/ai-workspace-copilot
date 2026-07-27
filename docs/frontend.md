# Frontend

React + TypeScript + Tailwind (built with Vite). A single-page chat UI.

## Files

| File | Responsibility |
| ---- | -------------- |
| `index.html` | HTML entry point; mounts the React app into `#root`. |
| `src/main.tsx` | React bootstrap. |
| `src/App.tsx` | The whole chat UI: message list, input box, send logic. |
| `src/services/api.ts` | Calls `POST /api/chat` and parses the SSE stream. |
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
