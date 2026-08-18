---
name: add-an-mcp-server-tool
description: Expose a capability to external MCP clients (Claude Desktop, Cursor) via the MCP server.
when_to_use: When a tool should be usable from external MCP clients, not just the in-app agent.
---
# Steps
1. Ensure the underlying function exists in `backend/services/tools.py` (see the
   add-a-tool skill) — the MCP server should call it, keeping one source of truth.
2. In `backend/mcp_server.py`, add an `@mcp.tool()` function that delegates to the
   `tools.*` function. Its docstring is what MCP clients display, so make it clear.
3. If the tool needs the owner's data or workspace, scope it to `_MCP_USER_ID`
   (like `search_documents` / `list_dir`) and return a helpful message when it's
   unset.
4. Test: launch the server (`.venv/bin/python mcp_server.py`) or use the MCP
   client discovery, and confirm the tool appears and calls through.
5. Update `docs/mcp.md` (the exposed-tools table).

# Context
- backend/mcp_server.py — FastMCP server; `@mcp.tool()` functions; `_MCP_USER_ID`.
- backend/services/tools.py — shared tool implementations (single source of truth).
- docs/mcp.md — the tools table + client setup instructions.
