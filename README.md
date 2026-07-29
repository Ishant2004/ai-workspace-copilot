# AI Workspace Copilot

Building an end-to-end AI assistant (RAG, tools, agents, MCP) from first
principles on a **$0 budget** — one feature at a time.

This is a learning project: instead of many small demos, we keep improving a
single application until it resembles a production AI copilot.

## Status

| Phase | Feature | Status |
| ----- | ------- | ------ |
| 0 | ChatGPT-style streaming chat (Gemini) | ✅ Done |
| 1 | Tokenization inspector | ✅ Done |
| 2 | Embedding service | ✅ Done |
| 3 | Vector DB (pgvector) | ✅ Done |
| 4 | RAG (grounded answers) | ✅ Done |
| 5 | PDF upload & ingestion | ✅ Done |
| 6 | Advanced chunking & metadata | ✅ Done |
| 7 | Hybrid search (keyword + vector) | ✅ Done |
| 8 | Reranker (cross-encoder) | ✅ Done |
| 9 | Conversation memory & threads | ✅ Done |
| 10 | Tool calling (function calling) | ✅ Done |
| 11 | ReAct agent (in chat) | ✅ Done |
| 12+ | Planning, multi-agent, MCP… | ⏳ Planned |

See [`plan.md`](plan.md) for the full roadmap.

## Tech stack (free tier)

- **Frontend:** React + TypeScript + Tailwind (Vite)
- **Backend:** FastAPI (Python)
- **LLM & embeddings:** Google Gemini (AI Studio free tier)
- **Vector DB:** Neon Postgres + `pgvector` (free tier)
- **Reranker:** FlashRank cross-encoder (local, CPU, no API)

## Quick start

You need two free accounts:
- Gemini API key: https://aistudio.google.com/apikey
- Neon Postgres connection string (for Phase 3+): https://neon.tech

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # paste your GEMINI_API_KEY and DATABASE_URL into .env
.venv/bin/uvicorn main:app --reload
```

The `documents` table and `pgvector` extension are created automatically on
first startup. Without `DATABASE_URL`, the app still runs — only Vector Search
is disabled.

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
