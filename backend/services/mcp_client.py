"""External MCP client (Phase 15).

Phase 14 made *us* an MCP server. This is the mirror image: our agent becomes an
MCP *client* that connects to third-party MCP servers (filesystem, GitHub,
Postgres, …), discovers their tools at runtime, and calls them — so the agent's
toolbox grows without us hand-writing each integration. That's the whole promise
of MCP: tools are discovered, not hard-coded.

Servers are declared in `backend/mcp_servers.json` (see mcp_servers.example.json).
Each tool is exposed to the agent under a namespaced name `"<server>__<tool>"`
so names from different servers never collide.

The MCP SDK is async, but our agent loop is synchronous, so we bridge with
`asyncio.run` and connect per operation (spawn the server, do one thing, close).
That's simpler than holding long-lived sessions and fine for this scale.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("uvicorn.error")

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "mcp_servers.json"

# Cache of discovered tools: namespaced_name -> {server, tool, description, schema}
_tools_cache: dict[str, dict] | None = None


def _load_servers() -> list[dict]:
    """Read the configured external servers (empty if no config file)."""
    if not _CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return data.get("servers", [])
    except Exception as exc:
        logger.warning("Could not read mcp_servers.json: %s", exc)
        return []


def _params(server: dict) -> StdioServerParameters:
    # Pass our full environment so `npx`/`node`/etc. resolve on PATH.
    env = {**os.environ, **server.get("env", {})}
    return StdioServerParameters(
        command=server["command"], args=server.get("args", []), env=env
    )


async def _list_tools(server: dict) -> list:
    async with stdio_client(_params(server)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return (await session.list_tools()).tools


async def _call(server: dict, tool: str, args: dict) -> str:
    async with stdio_client(_params(server)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            # Flatten the returned content blocks to plain text.
            parts = [c.text for c in result.content if getattr(c, "text", None)]
            return "\n".join(parts) if parts else "(no text content)"


def discover(refresh: bool = False) -> dict[str, dict]:
    """Connect to every configured server and return their tools, namespaced.

    Cached after the first call (rediscovery spawns subprocesses); pass
    refresh=True to rebuild.
    """
    global _tools_cache
    if _tools_cache is not None and not refresh:
        return _tools_cache

    discovered: dict[str, dict] = {}
    for server in _load_servers():
        name = server["name"]
        try:
            for tool in asyncio.run(_list_tools(server)):
                discovered[f"{name}__{tool.name}"] = {
                    "server": server,
                    "tool": tool.name,
                    "description": tool.description or "",
                    "schema": tool.inputSchema or {"type": "object"},
                }
        except Exception as exc:
            logger.warning("MCP server %r discovery failed: %s", name, exc)
    _tools_cache = discovered
    return discovered


def call_tool(namespaced_name: str, args: dict) -> str:
    """Call an external tool by its namespaced name."""
    entry = discover().get(namespaced_name)
    if entry is None:
        return f"Unknown external tool: {namespaced_name}"
    try:
        return asyncio.run(_call(entry["server"], entry["tool"], args))
    except Exception as exc:
        return f"External tool {namespaced_name} failed: {exc}"
