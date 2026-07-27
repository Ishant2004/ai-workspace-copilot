"""Prompt templates.

Keeping prompts in one place (instead of scattered f-strings) makes them easy
to read, tweak, and reason about — prompt wording is a real lever on quality.
"""


def build_rag_system_prompt(context_blocks: list[str]) -> str:
    """Build the system instruction that grounds the model in retrieved docs.

    The rules matter:
      - "only from the context" is what makes this RAG rather than plain chat —
        it stops the model from answering out of its own memory.
      - citing [#id] lets the user trace every claim back to a source.
      - an explicit "say you don't know" clause reduces hallucination when the
        retrieved context doesn't actually contain the answer.
    """
    if context_blocks:
        context = "\n\n".join(context_blocks)
    else:
        context = "(no relevant documents were found)"

    return (
        "You are a helpful assistant answering questions about the user's "
        "documents.\n"
        "Answer using ONLY the context below. If the answer is not contained "
        "in the context, say you don't know based on the available documents — "
        "do not use outside knowledge.\n"
        "Cite the documents you used with their id in square brackets, e.g. "
        "[#3].\n\n"
        "=== CONTEXT ===\n"
        f"{context}\n"
        "=== END CONTEXT ==="
    )


def format_context_block(doc_id: int, title: str, text: str) -> str:
    """Format one retrieved document for inclusion in the prompt context."""
    header = f"[#{doc_id}] {title}" if title else f"[#{doc_id}]"
    return f"{header}\n{text}"
