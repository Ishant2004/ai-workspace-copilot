"""PDF text extraction (Phase 5; per-page in Phase 6).

We need the raw text out of a PDF so we can chunk and embed it. `pypdf` does
this locally with no API calls. Scanned/image-only PDFs won't yield text — the
caller falls back to OCR (see services/gemini.ocr_pdf).

Phase 6 extracts text **per page** so each chunk can record which page it came
from (stored in the document's metadata).
"""

import io

from pypdf import PdfReader


def extract_pages(pdf_bytes: bytes) -> list[str]:
    """Return a list of page texts (index 0 = page 1)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Return (full_text, page_count) — pages joined with blank lines."""
    pages = extract_pages(pdf_bytes)
    full_text = "\n\n".join(p for p in pages if p)
    return full_text, len(pages)
