"""PDF text extraction (Phase 5).

We only need the raw text out of a PDF so we can chunk and embed it. `pypdf`
does this locally with no API calls. Scanned/image-only PDFs won't yield text
(they'd need OCR, which is out of scope here).
"""

import io

from pypdf import PdfReader


def extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Return (full_text, page_count) from raw PDF bytes.

    Pages are joined with blank lines so the chunker sees natural breaks.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    full_text = "\n\n".join(p for p in pages if p)
    return full_text, len(reader.pages)
