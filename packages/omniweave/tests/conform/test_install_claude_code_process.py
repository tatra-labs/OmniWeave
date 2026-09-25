"""The claude-code host's two commands, read back from the files it wrote and run as the host would.

The MCP entry is spawned as the argv it is -- `command` then `args`, no shell -- which is how a host
starts a stdio server, so the space and the parentheses in this machine's interpreter path must
survive unquoted and forward-slashed (D460). It starts, and since W7.3p it answers `initialize`:
`ow serve --mcp` runs step 5 and reaches the server through its entry point. Until then this file
asserted the dispatcher's exit-70 refusal and held the handshake as a strict xfail, and the xfail
turning into a pass is what closed D460. The hooks are handed to W7.4j's `ow hooks check` as real
children, as W7.5d's conform test did for the mode alone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave.hooks.check import check, render
from omniweave.hooks.envelope import EVENTS
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.engine import HostEnv
from omniweave.install.hookrules import launcher, owned_event, owned_pairs
from omniweave.install.types import InstallOptions
from omniweave_core.clock import SystemClock
from omniweave_core.host.subproc import Captured, run_captured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.conform

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "conform", "version": "0"},
    },
}


def _installed(tmp_path: Path) -> Path:
    launch = launcher()
    assert isinstance(launch, tuple), launch
    home = tmp_path / "home"
    home.mkdir()
    env = HostEnv(
        omniweave_home=tmp_path / "owhome",
        user_home=home,
        clock=SystemClock(),
        pid=os.getpid(),
        launch=launch,
        lock_wait_ms=0,
    )
    result = ClaudeCode(env).install("global", InstallOptions(hooks="steer", skills="none"))
    assert not result.refused, result.refused
    assert {one.action for one in result.actions} <= {"created", "updated"}, result.actions
    return home


def _env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}


def _serve(home: Path, tmp_path: Path) -> Captured:
    entry = json.loads((home / ".claude.json").read_bytes())["mcpServers"]["omniweave"]
    argv = [entry["command"], *entry["args"]]
    line = (json.dumps(_INITIALIZE) + "\n").encode()
    return run_captured(argv, stdin=line, cwd=str(tmp_path), env=_env(), timeout_s=60)


def test_the_mcp_entry_answers_initialize(tmp_path: Path) -> None:
    child = _serve(_installed(tmp_path), tmp_path)
    first = child.stdout.split(b"\n", 1)[0]
    assert first, child
    reply = json.loads(first)
    assert reply["id"] == 1
    assert "result" in reply
    #  The host asked for 2025-06-18, which this build does not carry, and is answered with the
    #  revision it does rather than refused. The server exits 0 when the host closes stdin.
    assert reply["result"]["protocolVersion"] == "2025-03-26"
    assert reply["result"]["serverInfo"]["name"] == "omniweave"
    assert child.returncode == 0, child
    assert child.stdout.count(b"\n") == 1, "one request, one frame, and nothing else on stdout"


def _runner(
    argv: Sequence[str], stdin: bytes, cwd: Path, env: Mapping[str, str], timeout: float
) -> Captured:
    return run_captured(argv, stdin=stdin, cwd=str(cwd), env=env, timeout_s=timeout)


def test_the_hosts_hooks_pass_the_check_as_real_children(tmp_path: Path) -> None:
    home = _installed(tmp_path)
    document = json.loads((home / ".claude" / "settings.json").read_bytes())
    commands = {owned_event(command) or "": command for _, command in owned_pairs(document)}
    assert list(commands) == list(EVENTS)
    report = check(
        commands,
        runner=_runner,
        clock=SystemClock(),
        path=os.environ.get("PATH", ""),
        scratch=tmp_path / "scratch",
        env=_env(),
    )
    assert report.exit_code() == 0, render(report)
