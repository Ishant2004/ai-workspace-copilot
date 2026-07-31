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

from fastapi import APIRouter, Depends, HTTPException

from api.deps import current_user_id
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
from services.search import run_search

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/documents", response_model=DocumentResponse)
def add_document(
    request: DocumentRequest, user_id: int = Depends(current_user_id)
) -> DocumentResponse:
    # Embed the text with the SAME model/dimension used for queries, then store.
    embedding = embed_text(request.text)
    metadata = {"source": "manual", "created_at": _now()}
    doc_id = db.insert_document(
        user_id, request.title, request.text, embedding, metadata
    )
    return DocumentResponse(
        id=doc_id,
        title=request.title,
        total_documents=db.count_documents(user_id),
    )


@router.get("/documents", response_model=list[DocumentItem])
def list_documents(user_id: int = Depends(current_user_id)) -> list[DocumentItem]:
    return [DocumentItem(**d) for d in db.list_documents(user_id)]


@router.put("/documents/{doc_id}", response_model=DocumentResponse)
def update_document(
    doc_id: int,
    request: DocumentRequest,
    user_id: int = Depends(current_user_id),
) -> DocumentResponse:
    # The text may have changed, so we must re-embed to keep the stored vector
    # consistent with the stored text.
    embedding = embed_text(request.text)
    updated = db.update_document(
        user_id, doc_id, request.title, request.text, embedding
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return DocumentResponse(
        id=doc_id,
        title=request.title,
        total_documents=db.count_documents(user_id),
    )


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
def delete_document(
    doc_id: int, user_id: int = Depends(current_user_id)
) -> DeleteResponse:
    deleted = db.delete_document(user_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return DeleteResponse(
        id=doc_id,
        deleted=True,
        total_documents=db.count_documents(user_id),
    )


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest, user_id: int = Depends(current_user_id)
) -> SearchResponse:
    # Phase 7: run the chosen strategy (vector / keyword / hybrid) over the
    # user's own documents.
    hits = run_search(
        user_id, request.query, request.k, request.mode, request.rerank
    )
    return SearchResponse(
        query=request.query,
        mode=request.mode,
        results=[SearchHit(**h) for h in hits],
    )


@router.get("/documents/count")
def documents_count(user_id: int = Depends(current_user_id)) -> dict:
    return {"total_documents": db.count_documents(user_id)}
