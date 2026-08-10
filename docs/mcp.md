# MCP Server (Phase 14)

The **Model Context Protocol (MCP)** is an open standard that lets any MCP-aware
client (Claude Desktop, Cursor, …) discover and call a server's tools. This
project ships an MCP server that exposes the same tools our own agent uses, so
external apps can search your knowledge base, do math, and get the time.

## What it exposes

`backend/mcp_server.py` (built with the official `mcp` SDK's `FastMCP`) exposes:

| Tool | Description |
| ---- | ----------- |
| `search_documents(query)` | Semantic + keyword search over your stored documents (pgvector). |
| `web_search(query)` | Live web search via DuckDuckGo (weather, news, GitHub, any current fact). |
| `fetch_url(url)` | Fetch a web page and return its readable text. |
| `analyze_csv(csv_text)` | Summarise CSV: columns, row count, numeric aggregates, sample rows. |
| `calculate(expression)` | Safe arithmetic. |
| `get_current_time()` | Current UTC time. |

These call the exact functions in `services/tools.py` that the in-app agent
uses — one source of truth, two doorways (our chat, and any MCP client).

## Transport

The server speaks MCP over **stdio** — the client launches the server as a
subprocess and talks over stdin/stdout. That's how Claude Desktop and Cursor
connect to local servers.

## Connect from Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-workspace-copilot": {
      "command": "/Users/tusharyadav/Documents/AI workspace copilot/backend/.venv/bin/python",
      "args": ["/Users/tusharyadav/Documents/AI workspace copilot/backend/mcp_server.py"]
    }
  }
}
```

Restart Claude Desktop; the tools appear in the tools menu. (Config loads
`backend/.env` by absolute path, so it works regardless of the launch
directory. `search_documents` needs `DATABASE_URL` + `GEMINI_API_KEY` set there.)

## Connect from Cursor

Add the same block to Cursor's MCP settings (Settings → MCP → Add server), using
the identical `command`/`args`.

## Test it yourself

You don't normally run the server by hand (a client launches it), but you can
verify it with a tiny stdio client:

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="backend/.venv/bin/python", args=["mcp_server.py"], cwd="backend"
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print([t.name for t in (await session.list_tools()).tools])
            print((await session.call_tool("calculate", {"expression": "6*7"})).content[0].text)

asyncio.run(main())
```

Verified output: `['search_documents', 'calculate', 'get_current_time']` and
`42`, plus `search_documents` returning a stored chunk.

---

# Connecting external MCP servers (Phase 15)

The reverse direction: our **agent connects to other people's MCP servers** and
uses their tools. Declare servers in `backend/mcp_servers.json` (copy
`mcp_servers.example.json`):

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/abs/path/to/dir"]
    }
  ]
}
```

On first use the agent connects to each server, discovers its tools, and exposes
them namespaced as `filesystem__read_text_file`, etc. — added to the agent's tool
set automatically. `GET /api/mcp/tools` lists what was discovered
(`?refresh=true` to rediscover). Add GitHub / Postgres / etc. servers the same
way; no code changes needed.

> `mcp_servers.json` is gitignored (absolute paths are machine-specific); the
> committed `mcp_servers.example.json` is the template.
