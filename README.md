# AI Workspace Copilot

Building an end-to-end AI assistant (RAG, tools, agents, MCP) from first
principles on a **$0 budget** — one feature at a time.

This is a learning project: instead of many small demos, we keep improving a
single application until it resembles a production AI copilot.

## Status

| Phase | Feature | Status |
| ----- | ------- | ------ |
| 0 | ChatGPT-style streaming chat (Gemini) | ✅ Done |
| 1 | Tokenization inspector | ⏳ Planned |
| 2 | Embedding service | ⏳ Planned |
| 3+ | Vector DB, RAG, tools, agents, MCP… | ⏳ Planned |

See [`plan.md`](plan.md) for the full roadmap.

## Tech stack (free tier)

- **Frontend:** React + TypeScript + Tailwind (Vite)
- **Backend:** FastAPI (Python)
- **LLM:** Google Gemini (AI Studio free tier)

## Quick start

You need a free Gemini API key: https://aistudio.google.com/apikey

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # paste your GEMINI_API_KEY into .env
.venv/bin/uvicorn main:app --reload
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Documentation

- [docs/architecture.md](docs/architecture.md) — big-picture mental map
- [docs/backend.md](docs/backend.md) — backend internals
- [docs/frontend.md](docs/frontend.md) — frontend internals

Docs are updated on every phase.
