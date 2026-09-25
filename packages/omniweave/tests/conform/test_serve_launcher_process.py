"""The official MCP client against `python -m omniweave serve --mcp`, run as a host runs it.

`omniweave_serve`'s own T3 test spawns the server with its three values already decided. This one
spawns the CLI, so step 5 runs in the child from a real `omniweave.toml`, and the values cross
the entry-point boundary before the server starts. What the client reads back is therefore the
configuration's decision: variant A and an optional `corpus` when a default corpus is declared,
variant B and a required `corpus` when none is (10:525, 10:871, D381).

**It spawns, so it is T3** (13 section 2.7). The spawn is the SDK's `stdio_client`, so this file
imports no `subprocess`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from omniweave_serve import listing

pytestmark = pytest.mark.conform

DEADLINE_S = 60
HANDBOOK = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'


def _session(cwd: Path, argv: list[str]) -> dict[str, object]:
    seen: dict[str, object] = {}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "omniweave", "serve", *argv],
        env={"OMNIWEAVE_HOME": str(cwd / "owhome")},
        cwd=cwd,
    )

    async def talk() -> None:
        with anyio.fail_after(DEADLINE_S):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                init = await client.initialize()
                seen["instructions"] = init.instructions
                listed = await client.list_tools()
                seen["tools"] = [tool.model_dump(exclude_none=True) for tool in listed.tools]

    anyio.run(talk)
    return seen


@pytest.mark.parametrize("declared", [True, False])
def test_step_5_in_the_child_decides_what_the_client_reads(
    tmp_path: Path, *, declared: bool
) -> None:
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n' if declared else ""
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    seen = _session(tmp_path, ["--mcp"])
    assert seen["instructions"] == listing.instructions("default", corpus_resolves=declared)
    expected = listing.tools_list("default", compact=True, corpus_resolves=declared)
    assert seen["tools"] == list(expected)
    query = next(tool for tool in expected if tool["name"] == "ow_query")
    assert ("corpus" in query["inputSchema"]["required"]) is not declared


def test_the_profile_flag_reaches_the_server(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text("", encoding="utf-8")
    seen = _session(tmp_path, ["--mcp", "--profile", "full"])
    assert seen["instructions"] == listing.instructions("full", corpus_resolves=False)
