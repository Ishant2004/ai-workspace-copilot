"""Shared ingestion pipeline (Phase 26).

Every source — PDF, DOCX, Markdown, HTML, a pasted URL — becomes the same thing:
a list of text "segments" (one per PDF page, or a single segment otherwise). This
module owns the common back half of ingestion so the format endpoints stay tiny:

    segments -> chunk each (boundary-aware, overlap)
             -> optionally contextualise (Phase 22)
             -> embed (batched)
             -> store as document rows with provenance metadata

Extracting this from the PDF-only upload path (Phase 5) means new formats get
chunking, contextual retrieval, and metadata for free.
"""

from datetime import datetime, timezone

from config import settings
from services import context, db
from services.chunking import recursive_chunk
from services.gemini import embed_texts


def ingest_segments(
    user_id: int,
    filename: str,
    source: str,
    segments: list[str],
    extra_meta: dict | None = None,
    thread_id: int | None = None,
) -> int:
    """Chunk → (contextualise) → embed → store. Returns the number of chunks stored.

    `source` records provenance (pdf/docx/markdown/html/url); `extra_meta` is
    merged into every chunk's metadata (e.g. the source URL). `thread_id` scopes
    the chunks to one chat as an attachment (Phase 30); NULL = global KB.
    """
    uploaded_at = datetime.now(timezone.utc).isoformat()
    base_meta = {"source": source, "filename": filename, "uploaded_at": uploaded_at}
    if extra_meta:
        base_meta.update(extra_meta)

    # 1. Chunk each segment, remembering which segment ("page") each chunk is on.
    chunk_texts: list[str] = []
    chunk_meta: list[dict] = []
    for page_no, segment in enumerate(segments, start=1):
        for piece in recursive_chunk(
            segment, settings.chunk_size, settings.chunk_overlap
        ):
            chunk_texts.append(piece)
            chunk_meta.append({**base_meta, "page": page_no})

    if not chunk_texts:
        return 0

    # 2. Optionally contextualise each chunk (Phase 22): embed the chunk with a
    #    model-written context line, but store the original text.
    contexts: list[str | None] = [None] * len(chunk_texts)
    if (
        settings.contextual_retrieval
        and len(chunk_texts) <= settings.contextual_max_chunks
    ):
        full_text = "\n\n".join(chunk_texts)
        contexts = context.contextualize_all(filename, full_text, chunk_texts)
        embed_input = [
            context.contextual_text(ctx, text)
            for ctx, text in zip(contexts, chunk_texts)
        ]
    else:
        embed_input = chunk_texts

    # 3. Embed every chunk in one batched call.
    embeddings = embed_texts(embed_input)

    # 4. Store each chunk as a document with its metadata.
    total = len(chunk_texts)
    rows = []
    for i, (text, embedding, meta, ctx) in enumerate(
        zip(chunk_texts, embeddings, chunk_meta, contexts)
    ):
        meta = {**meta, "chunk_index": i}
        if ctx:
            meta["context"] = ctx
        title = f"{filename} · p{meta['page']} · chunk {i + 1}/{total}"
        rows.append((title, text, embedding, meta))
    return db.insert_documents(user_id, rows, thread_id=thread_id)
