"""MCP server (Phase 14).

The Model Context Protocol (MCP) is a standard that lets *any* MCP-aware client
(Claude Desktop, Cursor, etc.) discover and call a server's tools. Phases 10–12
built tools for *our own* agent; this exposes the same capabilities to the
outside world through that standard, so our knowledge base and utilities become
usable from other AI apps.

We reuse the exact functions the in-app agent uses (services/tools.py), so
there's a single source of truth — the MCP server is just a second doorway to
them. It speaks MCP over **stdio**, the transport Claude Desktop and Cursor
launch and talk to.

Run standalone with:  .venv/bin/python mcp_server.py
(usually you don't run it by hand — an MCP client launches it; see docs/mcp.md.)
"""

import os

from mcp.server.fastmcp import FastMCP

from services import tools

# The server name is what clients display for this connection.
mcp = FastMCP("ai-workspace-copilot")

# The MCP server has no logged-in user, so document search is scoped to a single
# owner set via MCP_USER_ID (the numeric id of your account). Without it,
# search_documents returns nothing (it can't guess whose documents to expose).
_MCP_USER_ID = int(os.environ["MCP_USER_ID"]) if os.environ.get("MCP_USER_ID") else None


@mcp.tool()
def search_documents(query: str) -> str:
    """Search the configured owner's stored documents / knowledge base for
    information relevant to a query, returning the most similar chunks."""
    if _MCP_USER_ID is None:
        return "search_documents is disabled: set MCP_USER_ID to your user id."
    return tools.search_documents(_MCP_USER_ID, query)


@mcp.tool()
def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '3 * (4 + 5)'."""
    return tools.calculate(expression)


@mcp.tool()
def get_current_time() -> str:
    """Get the current date and time in UTC (ISO-8601)."""
    return tools.get_current_time()


if __name__ == "__main__":
    mcp.run()  # stdio transport
