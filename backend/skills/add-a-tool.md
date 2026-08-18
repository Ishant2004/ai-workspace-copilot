---
name: add-a-tool
description: Add a new agent tool end to end (declaration, function, dispatch, MCP, prompt, test).
when_to_use: When the user wants to give the agent a new capability or tool.
---
# Steps
1. Implement the tool function in `backend/services/tools.py` (or a helper module
   it imports). Keep it deterministic and return a short string.
2. Add a `types.FunctionDeclaration` for it to the `_DECLARATIONS` list (name,
   description, JSON-schema parameters).
3. Register it: add it to `_FUNCTIONS` (no user context) or `_CODE_TOOLS`
   (workspace tools that need `user_id`); `dispatch` routes the rest.
4. Mention it in the relevant prompt(s) in `backend/prompts.py`
   (`build_agent_system_prompt` / `build_chat_system_prompt`).
5. Expose it over MCP in `backend/mcp_server.py` if external clients should get it.
6. Test it: call `tools.dispatch("<name>", {...}, user_id)` and, if useful, drive
   the agent (`tools.run_tool_loop`) to confirm the model calls it.
7. Update `README.md` and `docs/backend.md` (tool list).

# Context
- backend/services/tools.py — the tool registry, `_DECLARATIONS`, `_FUNCTIONS`,
  `_CODE_TOOLS`, and `dispatch`.
- backend/prompts.py — where tools are described to the model.
- backend/mcp_server.py — expose the tool to external MCP clients.
- Convention: follow `process.md` — build one feature, test it, update docs.
