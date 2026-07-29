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


def build_agent_system_prompt() -> str:
    """System instruction for the ReAct agent (Phase 11).

    Unlike RAG (which forces one retrieval), the agent *decides* what to do:
    reason about the request, call whatever tools help, observe the results, and
    repeat until it can answer. The prompt nudges that behaviour and tells it
    which tool fits which job.
    """
    return (
        "You are a helpful assistant that can use tools to answer questions.\n"
        "Think about what the user needs, then call tools as required:\n"
        "- search_documents: for anything about the user's own documents, "
        "notes, or uploaded files.\n"
        "- calculate: for arithmetic.\n"
        "- get_current_time: for the current date/time.\n"
        "You may call tools multiple times, using earlier results to decide "
        "the next step. When you have enough information, reply with a clear, "
        "concise final answer. If tools can't help, answer from your own "
        "knowledge and say so."
    )
