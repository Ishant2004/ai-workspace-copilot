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
| `services/gemini.py` | Wrapper around the Gemini SDK. Streams chat + counts tokens. |

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
