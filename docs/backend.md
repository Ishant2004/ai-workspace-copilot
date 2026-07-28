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
| `api/embed.py` | The `POST /embed` endpoint (Phase 2 embedding service). |
| `api/documents.py` | Document CRUD + `POST /search` (Phase 3). |
| `api/rag.py` | `POST /rag/chat` — grounded, cited streaming chat (Phase 4). |
| `api/upload.py` | `POST /upload` — PDF ingestion pipeline (Phase 5). |
| `prompts.py` | Prompt templates (the RAG grounding system prompt). |
| `services/gemini.py` | Gemini SDK: chat, tokens, single + batch embeddings. |
| `services/db.py` | Vector DB access: init, insert, cosine + keyword search. |
| `services/search.py` | Search strategies: vector / keyword / hybrid (RRF). |
| `services/rerank.py` | Cross-encoder reranking with FlashRank (Phase 8). |
| `services/pdf.py` | Extract text from PDF bytes, per page (pypdf). |
| `services/chunking.py` | Recursive boundary-aware chunking with overlap. |

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

### `POST /embed`
Request body:
```json
{ "text": "some text to embed" }
```
Response:
```json
{
  "model": "gemini-embedding-001",
  "dimension": 768,
  "embedding": [-0.0385, 0.026, 0.0029, "…768 floats total"]
}
```
- The vector is **normalized to unit length** in `services/gemini.py`. Google
  recommends this when truncating the embedding to fewer than 3072 dims, and
  unit vectors make cosine similarity a plain dot product later.
- Model and dimension are configurable in `config.py` /`.env`
  (`gemini_embed_model`, `gemini_embed_dim`). **Do not change the dimension
  after storing documents** — old and new vectors would be incomparable.

### `POST /documents`
Store a document. Body: `{ "text": "...", "title": "optional" }`.
Response: `{ "id": 1, "title": "...", "total_documents": 1 }`.
The backend embeds the text and inserts it into the `documents` table.

### `GET /documents`
List all stored documents (id, title, text) newest-first. The raw embedding is
omitted — it's large and the UI never needs it just to list records.

### `PUT /documents/{id}`
Update a document. Body: same as POST. The backend **re-embeds** the new text
so the stored vector stays consistent with the text. Returns 404 if the id
doesn't exist.

### `DELETE /documents/{id}`
Delete a document. Response: `{ "id": 1, "deleted": true, "total_documents": 0 }`.
Returns 404 if the id doesn't exist.

### `POST /search`
Search. Body: `{ "query": "...", "k": 5, "mode": "hybrid", "rerank": false }`.
`mode` is `vector` | `keyword` | `hybrid` (default `hybrid`, Phase 7).
`rerank` (Phase 8) retrieves `rerank_candidates` (20) then trims to k with a
cross-encoder; each hit then carries a `rerank_score`.
Response:
```json
{
  "query": "...", "mode": "hybrid",
  "results": [
    { "id": 1, "title": "...", "text": "...", "similarity": 0.72,
      "metadata": {...}, "matched_by": ["vector", "keyword"], "rrf_score": 0.0328 }
  ]
}
```
- `similarity` is cosine similarity (`1 - cosine_distance`); `0.0` for
  keyword-only hits.
- `matched_by` lists which retrievers surfaced the hit.
- `rrf_score` is the fused rank score (hybrid mode only).
- Dispatch lives in `services/search.py`; keyword search uses the `text_search`
  tsvector column added in `init_db`.

### `GET /documents/count`
Returns `{ "total_documents": N }`. Used by the UI badge.

> Requires `DATABASE_URL` (a Neon Postgres URL). The table + `vector` extension
> are created automatically on startup. Embedding dimension must match
> `GEMINI_EMBED_DIM` and must not change once documents are stored.

### `POST /rag/chat`
Grounded chat. Body: `{ "messages": [...], "k": 4 }`.
Response: an SSE stream. The first event lists the retrieved sources, then the
answer streams as chunks:
- `{"type": "sources", "sources": [{"id":1,"title":"...","similarity":0.74}]}`
- `{"type": "chunk", "content": "..."}` … `{"type": "done"}`
- `{"type": "error", "content": "..."}` on failure.

Flow: embed the last user message → `db.search` top-k → `prompts` build a system
instruction containing that context → `stream_chat(messages, system_prompt)`.
The `system_instruction` support was added to `services/gemini.py` for this.

### `POST /upload`
Ingest a PDF. Multipart form field `file` (a `.pdf`).
Response:
```json
{ "filename": "handbook.pdf", "pages": 2, "chunks_stored": 12, "total_documents": 12 }
```
Pipeline (Phase 6): `services/pdf.extract_pages` (per page) →
`services/chunking.recursive_chunk` per page (`chunk_size`/`chunk_overlap` from
config) → `services/gemini.embed_texts` (batched) → `db.insert_documents`
(bulk, with metadata). Each chunk becomes a normal document row carrying
`metadata` = `{source, filename, page, chunk_index, uploaded_at}`, so it's
immediately searchable and RAG-usable and traceable to a page. Returns 400 for
non-PDFs or PDFs with no extractable text (e.g. scanned images).

### Metadata (Phase 6)
`documents` has a `metadata JSONB` column. Search and list responses include a
`metadata` object per row. Manually-added documents get
`{source: "manual", created_at}`; PDF chunks get the fields above. The column is
added idempotently on startup (`ADD COLUMN IF NOT EXISTS`), so existing
databases upgrade without data loss.

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
