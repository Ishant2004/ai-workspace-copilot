"""Text chunking (Phase 5).

An embedding is a single fixed-length vector, so it can only represent a limited
amount of text well. A whole PDF embedded as one vector would be a blurry
average of everything — useless for retrieval. Instead we split the text into
smaller chunks and embed each one; search then finds the specific chunk that
answers a question.

This is a deliberately simple character-based splitter with overlap. Phase 6
replaces it with smarter, boundary-aware chunking.
"""


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of ~`size` characters that overlap by `overlap`.

    The overlap means a sentence sitting on a chunk boundary still appears whole
    in at least one chunk, so it stays retrievable.
    """
    text = text.strip()
    if not text:
        return []
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(text):
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks
