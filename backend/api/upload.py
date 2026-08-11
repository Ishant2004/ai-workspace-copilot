"""Document upload & ingestion endpoint (Phase 5; multi-format in Phase 26).

Accepts a file, extracts its text (PDF, DOCX, Markdown, plain text, or HTML),
then hands off to the shared ingestion pipeline:

    file bytes -> extract text (services/extract.py, per format)
               -> chunk -> (contextualise) -> embed -> store (services/ingest.py)

So an uploaded document of any supported type becomes immediately searchable
(Phase 3) and usable as RAG grounding (Phase 4), carrying provenance metadata.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from api.deps import rate_limited_user_id
from config import settings
from models import UploadResponse
from services import audit, db, extract, ingest

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile, user_id: int = Depends(rate_limited_user_id)
) -> UploadResponse:
    filename = file.filename or "upload"
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in extract.SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {', '.join(sorted(extract.SUPPORTED_EXTS))}",
        )

    data = await file.read()
    # Phase 29: reject oversized uploads.
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.max_upload_bytes // 1_000_000} MB).",
        )

    # 1. Extract text segments for this format (PDF → per page; else one segment).
    try:
        segments = extract.extract_file(filename, data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}")

    if not any(s.strip() for s in segments):
        raise HTTPException(
            status_code=400,
            detail="No extractable text found (a scanned PDF or empty file?).",
        )

    # 2. Shared pipeline: chunk → (contextualise) → embed → store.
    stored = ingest.ingest_segments(user_id, filename, ext, segments)
    if stored == 0:
        raise HTTPException(status_code=400, detail="No extractable text found.")

    audit.log("document.upload", user_id, {"filename": filename, "chunks": stored})
    return UploadResponse(
        filename=filename,
        pages=len(segments),
        chunks_stored=stored,
        total_documents=db.count_documents(user_id),
    )
