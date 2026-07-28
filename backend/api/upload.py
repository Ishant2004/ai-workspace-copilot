"""PDF upload & ingestion endpoint (Phase 5; metadata-aware in Phase 6).

The ingestion pipeline, end to end:

    PDF bytes -> extract text per page (pypdf)
              -> recursively chunk each page (boundary-aware, with overlap)
              -> embed all chunks (batched)
              -> store each chunk as a document row WITH metadata

Phase 6 additions:
  - recursive (boundary-aware) chunking instead of blind fixed windows
  - per-page extraction so each chunk records its source page
  - metadata (filename, page, chunk index, source, timestamp) in a JSONB column

After this, the uploaded PDF's content is immediately searchable (Phase 3) and
usable as grounding for RAG answers (Phase 4) — the chunks are documents like
any other, now carrying provenance.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile

from config import settings
from models import UploadResponse
from services import db
from services.chunking import recursive_chunk
from services.gemini import embed_texts
from services.pdf import extract_pages

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile) -> UploadResponse:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file")

    pdf_bytes = await file.read()
    filename = file.filename or "upload.pdf"

    # 1. Extract text page by page (so we can record page numbers).
    try:
        pages = extract_pages(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}")

    # 2. Chunk each page independently, remembering which page each chunk is on.
    uploaded_at = datetime.now(timezone.utc).isoformat()
    chunk_texts: list[str] = []
    chunk_meta: list[dict] = []
    for page_no, page_text in enumerate(pages, start=1):
        for piece in recursive_chunk(
            page_text, settings.chunk_size, settings.chunk_overlap
        ):
            chunk_texts.append(piece)
            chunk_meta.append(
                {
                    "source": "pdf",
                    "filename": filename,
                    "page": page_no,
                    "uploaded_at": uploaded_at,
                }
            )

    if not chunk_texts:
        raise HTTPException(
            status_code=400,
            detail="No extractable text found (the PDF may be scanned images).",
        )

    # 3. Embed every chunk in one batched call.
    embeddings = embed_texts(chunk_texts)

    # 4. Store each chunk as a document with its metadata.
    total = len(chunk_texts)
    rows = []
    for i, (text, embedding, meta) in enumerate(
        zip(chunk_texts, embeddings, chunk_meta)
    ):
        meta = {**meta, "chunk_index": i}
        title = f"{filename} · p{meta['page']} · chunk {i + 1}/{total}"
        rows.append((title, text, embedding, meta))
    stored = db.insert_documents(rows)

    return UploadResponse(
        filename=filename,
        pages=len(pages),
        chunks_stored=stored,
        total_documents=db.count_documents(),
    )
