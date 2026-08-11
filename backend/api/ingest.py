"""URL ingestion endpoint (Phase 26).

  POST /ingest/url  — fetch a web page, extract its text, and index it.

Paste a link and its content becomes searchable / RAG-usable like any other
document. The URL is supplied by the authenticated user (their own action), and
the source URL is recorded in each chunk's metadata for provenance.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import rate_limited_user_id
from models import UploadResponse, UrlIngestRequest
from services import audit, db, extract, ingest

router = APIRouter()


@router.post("/ingest/url", response_model=UploadResponse)
def ingest_url(
    body: UrlIngestRequest, user_id: int = Depends(rate_limited_user_id)
) -> UploadResponse:
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="A URL is required.")

    try:
        text, title = extract.fetch_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {exc}")

    if not text.strip():
        raise HTTPException(
            status_code=400, detail="No readable text found at that URL."
        )

    stored = ingest.ingest_segments(
        user_id, title, "url", [text], extra_meta={"source_url": url}
    )
    if stored == 0:
        raise HTTPException(status_code=400, detail="No readable text found.")

    audit.log("url.ingest", user_id, {"url": url, "chunks": stored})
    return UploadResponse(
        filename=title,
        pages=1,
        chunks_stored=stored,
        total_documents=db.count_documents(user_id),
    )
