Here is the clean, raw Markdown for you to copy and paste directly into your editor or notes:

```markdown
# AI Engineering Roadmap Project ($0 Free Tier Edition)

# Build an End-to-End AI Workspace Copilot From Scratch

> **Goal:** Build one project that teaches every major AI engineering concept from first principles on a **$0 budget** using completely free cloud services and local open-source tools:
>
> - Tokenization
> - Embeddings
> - Vector Databases
> - RAG
> - Tool Calling
> - AI Agents
> - Memory
> - MCP (Model Context Protocol)
> - Connectors
> - Production Deployment ($0 Hosted)

Instead of creating many small projects, we will continuously improve **one application** until it resembles a production AI assistant like ChatGPT Enterprise, Notion AI, Cursor, or GitHub Copilot Workspace — without spending anything.

---

# Final Architecture ($0 Tech Stack)

```text
                         React Frontend (Vercel)
                                   │
                                   ▼
                     FastAPI Backend Gateway (Render / Koyeb)
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
     RAG Service             Agent Service              MCP Server
          │                        │                        │
          ▼                        ▼                        ▼
    pgvector DB               Tool Executor             AI Clients
   (Neon / Supabase)               │              (Cursor / Claude Desktop)
          │                        ▼
          ▼              GitHub / SQL / Local Files
 Cloudflare R2 Storage

```

---

# Free-Tier Tech Stack

| Component | Tech / Provider | Free Tier Details & Limits |
| --- | --- | --- |
| **Frontend Host** | **Vercel** / Netlify | Unlimited deployments, fast global CDN, seamless GitHub CI/CD. |
| **Backend Host** | **Render** / Koyeb | Free Web Service (FastAPI container). Ping via UptimeRobot to avoid cold starts. |
| **LLM Engine** | **Google Gemini API** (AI Studio) | Gemini Flash models with generous free limits (up to 15 RPM / 1M TPM). |
| **Embeddings** | **Google Gemini Embeddings** / Hugging Face | `text-embedding-004` (free) or Hugging Face Feature Extraction API (`all-MiniLM-L6-v2`). |
| **Vector DB** | **Neon Postgres** (`pgvector`) | **0.5 GB storage**, full Postgres + vector extensions out of the box. |
| **Reranker** | **FlashRank** (Local Python) | Ultra-lightweight, runs in-memory on CPU inside FastAPI container without API costs. |
| **File Storage** | **Cloudflare R2** | **10 GB/month free storage** with zero egress fees for uploaded PDFs and files. |
| **Cache & Queue** | **Upstash Redis** | **10,000 commands/day free** for session memory and rate limiting. |
| **MCP Engine** | **Python MCP SDK** | Open-source protocol standard running inside your FastAPI process. |

---

# Folder Structure

```text
ai-workspace-copilot/

frontend/               # React + TypeScript + Tailwind CSS (Hosted on Vercel)
    src/
        components/
        hooks/
        services/

backend/                # FastAPI Application (Hosted on Render / Koyeb)
    api/                # Endpoints (Chat, Embed, Upload, MCP)
    rag/                # Chunking, Vector Search, Hybrid Search, Reranking
    embeddings/         # Gemini / Hugging Face API wrappers
    agents/             # ReAct Loop, Planning, State Engine
    tools/              # SQL, Filesystem, GitHub tools
    mcp/                # MCP Server & Client connectors
    services/           # Memory, DB connections, R2 storage
    db/                 # SQLAlchemy models & migrations
    models/             # Pydantic schemas
    prompts/            # System & RAG prompt templates

docker/                 # Dockerfile & Docker Compose for local dev
docs/

```

---

# PHASE 0: Build a ChatGPT Clone

## Goal

Build a basic AI chatbot using free LLM APIs. No RAG, no agents, no vector DB.

## Free Implementation

* **Backend:** FastAPI endpoint `POST /chat`.
* **LLM:** Call **Google Gemini** using official Python SDK.
* **Frontend:** React + Tailwind with streaming responses (`StreamingResponse` / EventSource SSE).

## Concepts Learned

* API Calling & Rate Limits
* Server-Sent Events (SSE) Streaming
* Chat Completion Schema & Message History

---

# PHASE 1: Understand Tokenization

## Goal

Add a Token Inspector in the UI to measure token usage, costs, and context bounds.

## Free Implementation

* Use local tokenizers like `tiktoken` or Gemini's native `count_tokens` method in Python.
* Calculate costs based on Gemini's free tier quotas and standard paid tier baseline comparisons.

## Display Metrics

* Character count, Word count, Exact Token count, Estimated cost ($0 on Free Tier), Context Window % used.

---

# PHASE 2: Build an Embedding Service

## Goal

Create `POST /embed` to turn text strings into numeric vector representations.

## Free Implementation

* Option A: Call **Gemini Embeddings** (`text-embedding-004`).
* Option B: Use **Hugging Face Inference API** (Free) with model `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).

```json
// POST /embed
{ "text": "I love AI" }

// Response
{ "embedding": [-0.014, 0.082, 0.003, ...] }

```

---

# PHASE 3: Build Your Own Vector Database

## Goal

Setup a PostgreSQL instance with `pgvector` for vector storage and semantic search.

## Free Implementation

* **Cloud DB:** Spin up a free **Neon Postgres** instance (0.5 GB).
* Enable extension: `CREATE EXTENSION IF NOT EXISTS vector;`
* **Search Endpoint:** `POST /search` using Cosine Similarity (`<=>` operator).

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    text TEXT,
    embedding vector(384)
);

```

---

# PHASE 4: Build RAG (Retrieval-Augmented Generation)

## Goal

Ground LLM responses in custom retrieved context.

## Flow

`User Question` ➔ `Embed Query` ➔ `pgvector Cosine Search` ➔ `Top K Chunks` ➔ `Construct Grounded Prompt` ➔ `Gemini LLM` ➔ `Stream Answer`

---

# PHASE 5: PDF Upload & Document Ingestion

## Goal

Build `POST /upload` pipeline to parse and index user PDFs.

## Free Implementation

* **Storage:** Upload raw PDF files to **Cloudflare R2** (10 GB Free).
* **Text Extraction:** Use `pypdf` or `pdfplumber` in Python.
* Extract ➔ Chunk ➔ Generate Embeddings ➔ Insert into Neon Postgres.

---

# PHASE 6: Advanced Chunking & Metadata

## Goal

Improve retrieval accuracy with contextual chunking strategies.

## Implementation

* **Chunking:** Implement Recursive Character Chunking and Token-aware Chunking with overlap (e.g., 500 chars / 50 overlap).
* **Metadata Storage:** Store `filename`, `page_number`, `source_url`, and `timestamp` in JSONB columns.

---

# PHASE 7: Hybrid Search

## Goal

Combine Full-Text Keyword Search (BM25 style) with Semantic Vector Search.

## Free Implementation

* Use Postgres native `tsvector` and `tsquery` alongside `pgvector`.
* Merge results using **Reciprocal Rank Fusion (RRF)** directly in Python or SQL.

---

# PHASE 8: Add a Reranker

## Goal

Filter top 20 retrieved candidates down to the top 5 most relevant chunks.

## Free Implementation

* Use **FlashRank** (`pip install flashrank`) locally in Python.
* Runs an ultra-fast cross-encoder model in-memory on CPU without consuming memory or incurring API fees.

---

# PHASE 9: Conversation Memory & State

## Goal

Manage short-term conversation context and long-term user preferences.

## Free Implementation

* **Cache:** Use **Upstash Redis** (Free 10k ops/day) for session state and sliding message windows.
* **Persistent Memory:** Store chat threads in Neon Postgres.

---

# PHASE 10: Tool Calling (Function Calling)

## Goal

Enable Gemini to execute structured backend functions.

## Implementation

Define Python functions with JSON Schemas (`search_documents`, `execute_sql`, `read_file`, `get_weather`).

1. Send prompt + tool declarations to Gemini.
2. Gemini returns `function_call`.
3. FastAPI executes local code and returns `function_response` to Gemini.

---

# PHASE 11: AI Agent & ReAct Loop

## Goal

Build an autonomous agent loop that handles multi-step reasoning.

## Implementation

* Implement a custom Python `while` loop implementing the **ReAct** (Reason + Act) pattern.
* Dynamically select tools, observe execution results, and repeat until the final answer is constructed.

---

# PHASE 12: Planning & Task Execution

## Goal

Break down complex user prompts into structured execution subtasks.

## Implementation

* Agent generates a structured JSON plan (e.g., `[Step 1: SQL Query, Step 2: File Read, Step 3: Summarize]`).
* Execute workflow graph sequentially with error handling and retries.

---

# PHASE 13: Long-Term User Profile Memory

## Goal

Extract and persist user facts across multiple conversations.

## Implementation

* Background task extracts user preferences (e.g., coding preferences, workplace role) from messages.
* Save to a `user_profiles` table in Neon Postgres and inject into the system prompt.

---

# PHASE 14: Build an MCP Server

## Goal

Expose your backend tools as a standardized Model Context Protocol (MCP) server.

## Free Implementation

* Use the official `mcp` Python SDK to create an MCP server over SSE / Stdlib.
* Expose your RAG pipeline, SQL tools, and file readers so external clients (**Cursor**, **Claude Desktop**) can connect.

---

# PHASE 15: Connect External MCP Servers

## Goal

Connect your AI Copilot agent to external third-party MCP tools.

## Implementation

* Integrate open-source MCP connectors: **GitHub MCP**, **PostgreSQL MCP**, **Filesystem MCP**.
* Discover external tools dynamically and make them accessible to your ReAct agent loop.

---

# PHASE 16: Multi-Agent System Architecture

## Goal

Orchestrate specialized sub-agents with individual system prompts.

```text
Planner Agent ──► Retriever Agent ──► SQL / Coding Agent ──► Reviewer Agent

```

## Implementation

Write lightweight coordinator logic in Python to route tasks between specialized agent roles without overhead.

---

# PHASE 17: Production-Ready Deployment ($0 Budget)

## Goal

Deploy the entire stack securely with monitoring, rate limiting, and zero host cost.

## Deployment Strategy

1. **Frontend:** Deploy React app to **Vercel** with custom environment variables.
2. **Backend:** Containerize FastAPI using `Dockerfile` and deploy as a Web Service on **Render** or **Koyeb**.
3. **Database:** Host on **Neon Postgres** + **Cloudflare R2** + **Upstash Redis**.
4. **Keep-Alive:** Set up a free **UptimeRobot** monitor to ping the `/health` endpoint every 10 minutes to eliminate Render cold starts.
5. **CI/CD:** Automated builds via **GitHub Actions** on every push to `main`.

---

# Summary of Learning Milestones

* ✅ Manual Token Counting & Context Tracking
* ✅ Embedding Pipelines & Dimensions
* ✅ Vector Indexing with `pgvector`
* ✅ Grounded RAG & PDF Processing
* ✅ Hybrid Keyword + Semantic Search
* ✅ In-Memory CPU Reranking
* ✅ Tool Calling & Custom ReAct Agent Loops
* ✅ Multi-Step Workflow Planning
* ✅ MCP Server & External MCP Connectors
* ✅ Multi-Agent Communication
* ✅ Full Cloud Deployment on $0 Infrastructure

```

```