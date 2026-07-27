# Backend

FastAPI application that receives chat requests and streams LLM replies.

## Files

| File | Responsibility |
| ---- | -------------- |
| `main.py` | Creates the FastAPI app, wires CORS, mounts routers, exposes `/health`. |
| `config.py` | Loads settings from environment / `.env` (API key, model, CORS). |
| `models.py` | Pydantic schemas (`Message`, `ChatRequest`) — the API contract. |
| `api/chat.py` | The `POST /chat` endpoint. Streams the reply as SSE. |
| `services/gemini.py` | Wrapper around the Gemini SDK. Converts messages and streams tokens. |

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
