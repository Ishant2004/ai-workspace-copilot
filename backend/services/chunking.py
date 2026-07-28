"""Text chunking (Phase 5, upgraded in Phase 6).

An embedding is a single fixed-length vector, so it can only represent a limited
amount of text well. A whole document embedded as one vector would be a blurry
average of everything — useless for retrieval. Instead we split the text into
smaller chunks and embed each one; search then finds the specific chunk that
answers a question.

Phase 6 replaces the naive fixed-window splitter with **recursive character
chunking**: instead of cutting blindly every N characters (which can slice a
sentence — or a word — in half), we try to break on natural boundaries first
(paragraphs, then lines, then sentences, then spaces), only falling back to a
hard character cut when nothing else fits. This keeps chunks semantically
coherent, which makes their embeddings — and therefore retrieval — better.
"""

# Boundaries to try, from coarsest to finest. The empty string is the last
# resort: split between individual characters.
_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def recursive_chunk(text: str, size: int, overlap: int) -> list[str]:
    """Split text into ~`size`-char chunks, preferring natural boundaries.

    Adjacent chunks overlap by ~`overlap` characters so a sentence sitting on a
    boundary still appears whole in at least one chunk.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    return _split(text.strip(), size, overlap, _SEPARATORS)


def _split(text: str, size: int, overlap: int, separators: list[str]) -> list[str]:
    if len(text) <= size:
        return [text] if text.strip() else []

    # Pick the first separator that actually occurs (or the char-level fallback).
    separator = separators[-1]
    remaining = separators[-1:]
    for i, sep in enumerate(separators):
        if sep == "" or sep in text:
            separator = sep
            remaining = separators[i + 1 :] or [""]
            break

    # Break into pieces, keeping the separator attached so we don't lose it.
    if separator == "":
        pieces = list(text)
    else:
        parts = text.split(separator)
        pieces = [p + separator for p in parts[:-1]] + [parts[-1]]

    # Greedily merge pieces up to `size`; recurse into any piece still too big.
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if len(piece) > size:
            if current.strip():
                chunks.append(current.strip())
            current = ""
            chunks.extend(_split(piece, size, overlap, remaining))
        elif len(current) + len(piece) <= size:
            current += piece
        else:
            if current.strip():
                chunks.append(current.strip())
            # Seed the next chunk with the tail of this one, for overlap.
            tail = current[-overlap:] if overlap else ""
            current = tail + piece
    if current.strip():
        chunks.append(current.strip())
    return chunks
