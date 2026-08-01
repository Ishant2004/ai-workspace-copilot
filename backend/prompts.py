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
        "- web_search: for current or real-world info not in the user's docs — "
        "weather, news, GitHub, prices, live facts.\n"
        "- calculate: for arithmetic.\n"
        "- get_current_time: for the current date/time.\n"
        "You may call tools multiple times, using earlier results to decide "
        "the next step. When you have enough information, reply with a clear, "
        "concise final answer. If tools can't help, answer from your own "
        "knowledge and say so."
    )


def build_chat_system_prompt() -> str:
    """System instruction for plain chat, which can now use tools when helpful.

    Chat stays conversational — it answers directly most of the time — but it may
    quietly reach for a tool when the question needs live or computed facts:
    `web_search` for anything current (weather, news, prices, GitHub…),
    `search_documents` for the user's own files, `calculate`, `get_current_time`.
    """
    return (
        "You are a helpful conversational assistant. Answer directly from your "
        "own knowledge when you can. When a question needs live or real-world "
        "information you can't be sure of — weather, news, prices, current "
        "events, GitHub, etc. — use the web_search tool. Use search_documents "
        "for the user's own uploaded files, calculate for arithmetic, and "
        "get_current_time for the current date/time. Keep replies natural and "
        "concise."
    )


def build_planner_prompt(goal: str) -> str:
    """Ask the model to break a goal into a short ordered list of subtasks.

    Planning up front (vs. the reactive agent) helps with complex, multi-part
    requests: the model commits to a strategy, then each step is executed and
    checked independently. We keep plans short so simple goals don't balloon.
    """
    return (
        "Break the user's goal into a short ordered list of concrete subtasks "
        "(at most 5). Each subtask should be a single, self-contained action, "
        "phrased so it can be executed on its own. Tools available during "
        "execution: search_documents, web_search, calculate, get_current_time. "
        "If the goal "
        "is simple, a single step is fine.\n\n"
        f"GOAL: {goal}"
    )


def build_step_prompt(goal: str, task: str, prior: list[str]) -> str:
    """Prompt for executing one plan step, given the goal and prior results."""
    context = "\n".join(prior) if prior else "(none yet)"
    return (
        f"Overall goal: {goal}\n\n"
        f"Results of previous steps:\n{context}\n\n"
        f"Now do this step and report just its result: {task}"
    )


def build_synthesis_prompt(goal: str, step_results: list[str]) -> str:
    """Prompt to write the final answer from all executed step results."""
    joined = "\n".join(step_results)
    return (
        f"The user's goal was: {goal}\n\n"
        f"Here are the results of the steps taken:\n{joined}\n\n"
        "Write a clear, concise final answer to the user's goal using these "
        "results."
    )


# --- Multi-agent team prompts (Phase 16) -----------------------------------
# Each sub-agent has its own focused role. Specialization + a fresh, narrow
# prompt per step tends to beat one prompt trying to do everything at once.


def build_team_planner_prompt(goal: str) -> str:
    return (
        "You are the PLANNER on a small team answering a user's goal. Outline a "
        "brief approach — 2 to 4 short bullet points — describing how to answer "
        "it and what information is needed. Do not answer the goal yet.\n\n"
        f"GOAL: {goal}"
    )


def build_solver_prompt(goal: str, plan: str, context: str) -> str:
    return (
        "You are the SOLVER on a small team. Using the plan and the retrieved "
        "context below, write a complete draft answer to the user's goal. Rely "
        "on the context where relevant; if it doesn't cover something, use your "
        "own knowledge.\n\n"
        f"GOAL: {goal}\n\n"
        f"PLAN:\n{plan}\n\n"
        f"RETRIEVED CONTEXT:\n{context or '(no documents found)'}"
    )


def build_reviewer_prompt(goal: str, draft: str, context: str) -> str:
    return (
        "You are the REVIEWER on a small team. Improve the draft answer below: "
        "fix any inaccuracies (check it against the retrieved context), make "
        "sure it fully and directly answers the goal, and keep it clear and "
        "concise. Output ONLY the final, improved answer for the user.\n\n"
        f"GOAL: {goal}\n\n"
        f"RETRIEVED CONTEXT:\n{context or '(no documents found)'}\n\n"
        f"DRAFT ANSWER:\n{draft}"
    )
