"""Quick stdio probe for the JobWatch MCP server.

Usage:
    uv run python scripts/mcp_probe.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "src.mcp_server.server"],
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("TOOLS:", names)
            assert set(names) == {
                "query_recent_rows",
                "get_job_log",
                "get_last_job_metrics",
            }, f"unexpected tool set: {names}"

            r1 = await session.call_tool("query_recent_rows", {"ticker": "AAPL", "limit": 3})
            print("query_recent_rows(AAPL, 3) ->", _first_text(r1))

            r2 = await session.call_tool("get_last_job_metrics", {})
            print("get_last_job_metrics() ->", _first_text(r2))

            r3 = await session.call_tool("get_job_log", {})
            print("get_job_log() ->", _first_text(r3)[:300], "...")

            r4 = await session.call_tool("query_recent_rows", {"ticker": "NOPE", "limit": 3})
            print("query_recent_rows(NOPE, 3) ->", _first_text(r4))

    return 0


def _first_text(result) -> str:
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return text
    return json.dumps(result.model_dump() if hasattr(result, "model_dump") else str(result))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
