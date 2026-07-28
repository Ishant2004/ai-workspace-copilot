"""Document storage + semantic search endpoints (Phase 3).

These sit on top of the vector DB (services/db.py). Full CRUD over documents
plus semantic search:

  POST   /documents        — embed a piece of text and store it
  GET    /documents        — list all stored documents (no raw vectors)
  PUT    /documents/{id}    — replace a document's title/text (re-embeds)
  DELETE /documents/{id}    — remove a document
  GET    /documents/count   — how many documents are stored
  POST   /search           — embed a query and return the most similar documents
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from models import (
    DeleteResponse,
    DocumentItem,
    DocumentRequest,
    DocumentResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from services import db
from services.gemini import embed_text

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/documents", response_model=DocumentResponse)
def add_document(request: DocumentRequest) -> DocumentResponse:
    # Embed the text with the SAME model/dimension used for queries, then store.
    embedding = embed_text(request.text)
    metadata = {"source": "manual", "created_at": _now()}
    doc_id = db.insert_document(
        request.title, request.text, embedding, metadata
    )
    return DocumentResponse(
        id=doc_id,
        title=request.title,
        total_documents=db.count_documents(),
    )


@router.get("/documents", response_model=list[DocumentItem])
def list_documents() -> list[DocumentItem]:
    return [DocumentItem(**d) for d in db.list_documents()]


@router.put("/documents/{doc_id}", response_model=DocumentResponse)
def update_document(doc_id: int, request: DocumentRequest) -> DocumentResponse:
    # The text may have changed, so we must re-embed to keep the stored vector
    # consistent with the stored text.
    embedding = embed_text(request.text)
    updated = db.update_document(doc_id, request.title, request.text, embedding)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return DocumentResponse(
        id=doc_id,
        title=request.title,
        total_documents=db.count_documents(),
    )


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
def delete_document(doc_id: int) -> DeleteResponse:
    deleted = db.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return DeleteResponse(
        id=doc_id,
        deleted=True,
        total_documents=db.count_documents(),
    )


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    # Embed the query into the same vector space, then let Postgres find the
    # nearest document vectors by cosine distance.
    query_embedding = embed_text(request.query)
    hits = db.search(query_embedding, request.k)
    return SearchResponse(
        query=request.query,
        results=[SearchHit(**h) for h in hits],
    )


@router.get("/documents/count")
def documents_count() -> dict:
    return {"total_documents": db.count_documents()}
