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
| 12 | Planning & task execution | ✅ Done |
| 13 | Long-term user profile memory | ✅ Done |
| 14 | MCP server | ✅ Done |
| 15 | External MCP connectors | ✅ Done |
| 16 | Multi-agent system | ✅ Done |
| 17 | Production deployment ($0) | ✅ Done |
| — | Live web search (DuckDuckGo), in agent + chat | ✅ Done |

🎉 All 17 phases complete, plus live web search — the agent can now pull current
info (weather, news, GitHub, prices) off the live web via DuckDuckGo (no API key).

### Part 2 — from demo to production-grade ([`plan2.md`](plan2.md))

| Phase | Feature | Status |
| ----- | ------- | ------ |
| 18 | Evaluation harness (retrieval + answer metrics) | ✅ Done |
| 19 | LLM-as-judge + regression gate | ✅ Done |
| 20 | Observability & tracing | ✅ Done |
| 21 | Query rewriting & multi-query retrieval | ✅ Done |
| 22 | Contextual retrieval | ✅ Done |
| 23 | Feedback loop | ✅ Done |
| 24 | Caching (embedding / retrieval / response) | ✅ Done |
| 25 | Semantic memory + management UI | ✅ Done |
| 26 | More ingestion formats (DOCX/MD/HTML/URL) | ✅ Done |
| 27 | More tools (URL fetch, CSV) | ⬜ Planned |
| 28 | UX polish | ⬜ Planned |
| 29 | Security hardening | ⬜ Planned |

**Run the eval** (from `backend/`):

```bash
PYTHONPATH="$(pwd)" .venv/bin/python -m eval.run_eval
```

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
- [docs/mcp.md](docs/mcp.md) — MCP server + how to connect Claude Desktop / Cursor
- [docs/deployment.md](docs/deployment.md) — deploy to Vercel + Render ($0)

Docs are updated on every phase.
