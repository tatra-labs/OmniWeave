"""`python -m omniweave ingest` as a process, after `ow_add` over the official MCP client.

The drain `ow_add` and `PostToolUse` would spawn, run the way they would spawn it: a child of this
interpreter with pipes for stdio. Nothing spawns it yet (D554), so this test is the spawner, and
what it checks is what the spawned child would do -- that the roster `ow_add` wrote in one process
is walked, read and identified by another, under the `store.write` lock both now take.

**It spawns, so it is T3** (13 section 2.7).
"""

from __future__ import annotations

import json
import os
import sqlite3  # noqa: TID251 -- the assertions read the store the child wrote.
import subprocess  # noqa: TID251 -- T3 spawns the child a host would spawn; tests only.
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

pytestmark = pytest.mark.conform

DEADLINE_S = 60
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n[serve]\ndefault_corpus = "handbook"\n'
)


def _env(home: Path) -> dict[str, str]:
    """The user's environment minus the two variables that would make a child UTF-8 by accident,
    `test_hooks_process.py`'s reason: the report must be ASCII on a cp1252 pipe by itself."""
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return {**keep, "OMNIWEAVE_HOME": str(home)}


def _call(cwd: Path, name: str, arguments: dict[str, object]) -> str:
    """One `tools/call` through the official client, in a server child of its own."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "omniweave", "serve", "--mcp"],
        env={"OMNIWEAVE_HOME": str(cwd / "owhome")},
        cwd=cwd,
    )
    seen: list[str] = []

    async def talk() -> None:
        with anyio.fail_after(DEADLINE_S):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool(name, arguments)
                assert result.isError is False
                (content,) = result.content
                assert isinstance(content, TextContent)
                seen.append(content.text)

    anyio.run(talk)
    return seen[0]


def _ingest(cwd: Path, *argv: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 -- this interpreter and literals
        (sys.executable, "-m", "omniweave", "ingest", *argv),
        capture_output=True,
        cwd=cwd,
        env=_env(cwd / "owhome"),
        timeout=DEADLINE_S,
        check=False,
    )


def _states(store: Path) -> list[tuple[str, int]]:
    conn = sqlite3.connect(store)
    try:
        return conn.execute("SELECT state, count(*) FROM unit GROUP BY state").fetchall()
    finally:
        conn.close()


def test_what_ow_add_rostered_in_one_process_is_identified_by_the_next(tmp_path: Path) -> None:
    """D559 across a process boundary: the roster `ow_add` wrote carries the walked path, so the
    bare `ow ingest` a hook would spawn keys, claims and identifies every unit of it."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("Fees are payable monthly.", encoding="utf-8")
    (docs / "b.txt").write_text("Notice is thirty days.", encoding="utf-8")
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    added = json.loads(_call(tmp_path, "ow_add", {"source": "docs"}))
    assert (added["discovered"], added["queued"]) == (2, 2)
    store = tmp_path / ".omniweave" / "index.owstore"
    assert _states(store) == [("discovered", 2)]

    ran = _ingest(tmp_path)
    assert ran.returncode == 0, ran.stderr.decode("ascii", "replace")
    assert ran.stderr == b""
    lines = ran.stdout.decode("ascii").splitlines()
    assert lines[-1] == "partial  0 failed"
    assert "2 units identified" in lines[3]
    assert _states(store) == [("identified", 2)]
    assert not (store.parent / "store.write-index.owstore.lock").exists()

    #  D567: the files are rostered, read and identified and not one is parsed, so a question
    #  about them is `degraded` naming gate 5 -- it was `absent` with no gate at all.
    answer = _call(tmp_path, "ow_query", {"query": "fees payable monthly"})
    assert answer.startswith("ow/1 degraded "), answer[:120]
    assert "pending_work_in_scope" in answer
    assert "verdict.state      = degraded" in answer


def test_a_path_outside_the_roots_is_refused_by_the_process_with_exit_6(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    ran = _ingest(project, str(tmp_path))
    assert ran.returncode == 6
    assert ran.stdout == b""
    assert b"OW_PATH_OUTSIDE_ROOTS" in ran.stderr
