"""The official MCP client against the real server, in a child process, over real pipes. T3.

Every other test of this distribution drives the transport and the dispatcher with doubles, which
proves they agree with each other and with the plan. This one proves they agree with **the other
end**: `mcp.ClientSession`, the reference implementation of what a host does, spawning the server
the way 10:2563's `claude mcp add ... -- ow serve --mcp` would, and walking the lifecycle a host
walks -- `initialize`, `notifications/initialized`, `tools/list`, `ping`, `tools/call`.

**It spawns, so it is T3** (13 section 2.7): `tests/conform/`, and its own CI step. The spawn is
the SDK's own `stdio_client`, so this file imports no `subprocess`.

**What the child is, since `ow serve` cannot be it.** D369: the CLI may not import this
distribution, so there is no `ow serve --mcp` to launch. The child is the four lines a launcher
will be -- `McpDispatcher.create()`, `stdio.pipes()`, `stdio.serve()` -- with step 5's three values
passed in, which is D382's boundary drawn where it falls.

**It runs on Windows by construction.** D385 is a server that starts on Windows, answers nothing
and reports nothing; a reference client timing out here is that defect coming back, and
`fail_after` turns it into a failure rather than a hang.
"""

from __future__ import annotations

import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from omniweave_core.contract import RELEASE
from omniweave_serve import listing
from omniweave_serve.dispatch import uncallable
from omniweave_serve.stdio import METHOD_NOT_FOUND, PROTOCOL_VERSION, SERVER_NAME

pytestmark = pytest.mark.conform

DEADLINE_S = 60

CHILD = """
import asyncio, sys
from omniweave_serve.dispatch import McpDispatcher, Surface
from omniweave_serve.stdio import pipes, serve
profile, small, resolves = sys.argv[1], sys.argv[2] == "1", sys.argv[3] == "1"
surface = Surface(profile=profile, compact=small, corpus_resolves=resolves)
dispatcher = McpDispatcher.create(surface)
lines, sink = pipes()
asyncio.run(serve(lines, sink, dispatcher))
"""


def _server(profile: str, *, small: bool, resolves: bool) -> StdioServerParameters:
    flags = ["1" if small else "0", "1" if resolves else "0"]
    return StdioServerParameters(command=sys.executable, args=["-c", CHILD, profile, *flags])


@pytest.mark.parametrize("resolves", [True, False])
def test_the_reference_client_completes_the_lifecycle_against_the_server(*, resolves: bool) -> None:
    seen: dict[str, object] = {}

    async def session() -> None:
        params = _server("default", small=True, resolves=resolves)
        with anyio.fail_after(DEADLINE_S):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                init = await client.initialize()
                seen["version"] = init.protocolVersion
                seen["server"] = (init.serverInfo.name, init.serverInfo.version)
                seen["list_changed"] = (
                    init.capabilities.tools and init.capabilities.tools.listChanged
                )
                seen["instructions"] = init.instructions
                listed = await client.list_tools()
                seen["tools"] = [tool.model_dump(exclude_none=True) for tool in listed.tools]
                seen["cursor"] = listed.nextCursor
                await client.send_ping()
                with pytest.raises(McpError) as refused:
                    await client.call_tool("ow_query", {"query": "what is indexed"})
                seen["call"] = refused.value.error

    anyio.run(session)

    assert seen["version"] == PROTOCOL_VERSION
    assert seen["server"] == (SERVER_NAME, RELEASE)
    assert seen["list_changed"] is False
    assert seen["instructions"] == listing.instructions("default", corpus_resolves=resolves)
    expected = listing.tools_list("default", compact=True, corpus_resolves=resolves)
    assert seen["tools"] == list(expected), "the client parsed exactly the listing's objects"
    assert seen["cursor"] is None
    error = seen["call"]
    assert getattr(error, "code", None) == METHOD_NOT_FOUND
    assert getattr(error, "data", None) == {"owed": uncallable()[0]}
