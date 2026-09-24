"""The commands `json-hook-rules` writes, read back from the file and run by `ow hooks check`.

10:2078: *"Verifying a hook by reading settings.json proves nothing."* So this does both halves:
install the six hooks into a scratch `settings.json` with this machine's own launcher -- which is
the interpreter, because there is no `ow` to resolve (D456), and whose path has a space and
parentheses (D457) -- then take the command strings out of the file as a host would and hand them
to W7.4j's engine, which splits them the way a POSIX shell would and runs each as a real child.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave.hooks.check import check, render
from omniweave.hooks.envelope import EVENTS
from omniweave.install.hookrules import desired, launcher, owned_event, owned_pairs
from omniweave.install.modes import Site, set_hooks
from omniweave.install.types import HOOK_SETS
from omniweave_core.clock import SystemClock
from omniweave_core.host.subproc import Captured, run_captured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.conform


def _runner(
    argv: Sequence[str], stdin: bytes, cwd: Path, env: Mapping[str, str], timeout: float
) -> Captured:
    return run_captured(argv, stdin=stdin, cwd=str(cwd), env=env, timeout_s=timeout)


def test_the_installed_hooks_pass_the_check_as_real_children(tmp_path: Path) -> None:
    launch = launcher()
    assert isinstance(launch, tuple), launch
    home = tmp_path / "home"
    site = Site("claude-code", "global", home / ".claude" / "settings.json", home)
    applied = set_hooks(
        site,
        desired(HOOK_SETS["steer"], launch),
        previous=None,
        clock=SystemClock(),
        pid=os.getpid(),
    )
    assert applied.record is not None, applied.action

    document = json.loads(site.path.read_bytes())
    commands = {owned_event(command) or "": command for _, command in owned_pairs(document)}
    assert list(commands) == list(EVENTS)

    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    report = check(
        commands,
        runner=_runner,
        clock=SystemClock(),
        path=os.environ.get("PATH", ""),
        scratch=tmp_path / "scratch",
        env=env,
    )
    assert report.exit_code() == 0, render(report)
    assert all(item.resolution.ok() and item.returncode == 0 for item in report.probes)
