"""End-to-end: launch the server over stdio against the fake Resolve module."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FAKE = os.path.join(os.path.dirname(__file__), "fake_resolve")


def test_stdio_roundtrip():
    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "davinci_resolve_mcp"],
            env={**os.environ, "RESOLVE_SCRIPT_API": FAKE},
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as client:
                await client.initialize()
                tools = {t.name for t in (await client.list_tools()).tools}
                assert {"resolve_status", "stabilize_item", "resolve_call", "start_rendering"} <= tools
                status = await client.call_tool("resolve_status", {})
                assert not status.isError
                assert json.loads(status.content[0].text)["studio"] is True
                err = await client.call_tool("list_media", {})
                assert err.isError and "No project" in err.content[0].text
    asyncio.run(run())
