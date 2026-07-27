"""PDF upload & ingestion endpoint (Phase 5).

The ingestion pipeline, end to end:

    PDF bytes -> extract text (pypdf) -> split into overlapping chunks
              -> embed all chunks (batched) -> store each chunk as a document row

After this, the uploaded PDF's content is immediately searchable (Phase 3) and
usable as grounding for RAG answers (Phase 4) — the chunks are just documents
like any other.
"""

from fastapi import APIRouter, HTTPException, UploadFile

from config import settings
from models import UploadResponse
from services import db
from services.chunking import chunk_text
from services.gemini import embed_texts
from services.pdf import extract_text

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile) -> UploadResponse:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file")

    pdf_bytes = await file.read()

    # 1. Extract text from the PDF.
    try:
        text, pages = extract_text(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}")

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="No extractable text found (the PDF may be scanned images).",
        )

    # 2. Split into overlapping chunks.
    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)

    # 3. Embed every chunk in one batched call.
    embeddings = embed_texts(chunks)

    # 4. Store each chunk as a document, titled by file + chunk position.
    filename = file.filename or "upload.pdf"
    rows = [
        (f"{filename} · chunk {i + 1}/{len(chunks)}", chunk, embedding)
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    stored = db.insert_documents(rows)

    return UploadResponse(
        filename=filename,
        pages=pages,
        chunks_stored=stored,
        total_documents=db.count_documents(),
    )
