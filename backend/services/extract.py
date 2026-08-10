"""Multi-format text extraction (Phase 26).

Phase 5 ingested PDFs; this generalises the *front* of the pipeline so DOCX,
Markdown, plain text, HTML, and pasted URLs can all feed the same chunk → embed →
store flow. Each extractor just turns bytes (or a URL) into plain text; the
shared ingestion pipeline (services/ingest.py) takes it from there.

We keep dependencies light: HTML is parsed with the stdlib `html.parser` (strip
scripts/styles, collect text) and URLs are fetched with `urllib` — no bs4, no
extra HTTP client. It won't win a readability contest, but it reliably turns a
page into searchable text.
"""

import io
import urllib.request
from html.parser import HTMLParser

from docx import Document

from services import pdf

# Only fetch/parse a bounded amount so a huge page can't blow up memory.
_MAX_FETCH_BYTES = 5_000_000
_FETCH_TIMEOUT = 15


class _HTMLTextExtractor(HTMLParser):
    """Collect visible text, skipping <script>/<style> and grabbing the title."""

    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self._chunks.append(text)

    def text(self) -> str:
        return "\n".join(self._chunks)


def html_to_text(html: str) -> tuple[str, str]:
    """Return (text, title) extracted from an HTML string."""
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.text(), parser.title


def extract_docx(data: bytes) -> str:
    """Extract text from a .docx file's paragraphs."""
    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch a web page and return (text, title). Raises on network errors."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    req = urllib.request.Request(url, headers={"User-Agent": "AIWorkspaceCopilot/1.0"})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
        raw = resp.read(_MAX_FETCH_BYTES)
    html = raw.decode("utf-8", errors="ignore")
    text, title = html_to_text(html)
    return text, (title or url)


# Extensions we can turn into text (URL ingestion is a separate endpoint).
SUPPORTED_EXTS = {"pdf", "docx", "md", "markdown", "txt", "html", "htm"}


def extract_file(filename: str, data: bytes) -> list[str]:
    """Turn an uploaded file into a list of text "segments" for the pipeline.

    PDFs return one segment per page (preserving page numbers); everything else
    is a single segment. Raises ValueError for unsupported extensions.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        return pdf.extract_pages(data)
    if ext == "docx":
        return [extract_docx(data)]
    if ext in ("md", "markdown", "txt"):
        return [data.decode("utf-8", errors="ignore")]
    if ext in ("html", "htm"):
        text, _ = html_to_text(data.decode("utf-8", errors="ignore"))
        return [text]
    raise ValueError(f"Unsupported file type: .{ext or '?'}")
