"""`ow hooks check` over the install receipt: which commands it probes, and when it fails.

**The sharpest test is `test_a_hook_the_receipt_records_and_the_file_lost_is_a_failure`.** A probe
that silently skipped an event the user deleted from `settings.json` would pass a host whose hook
is gone, which is the silent failure 10:2083 says this verb exists to catch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave.install import verbs
from omniweave.install.engine import HostEnv
from omniweave.install.hookrules import owned_event
from omniweave.install.types import InstallOptions
from omniweave_core.host.subproc import Captured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PID = 4242
#  A real interpreter: the engine resolves an absolute head by stat, so a made-up one fails.
LAUNCH = (sys.executable, "-m", "omniweave")


class _Clock:
    def wall_ns(self) -> int:
        return 0

    def monotonic_ns(self) -> int:
        return 0


def _env(tmp: Path, *, root: Path | None = None) -> HostEnv:
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    return HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=LAUNCH,
        project_root=root,
        windows=True,
        which=lambda _name: None,
        lock_wait_ms=0,
    )


class _Runner:
    """Records every argv it is handed and answers each as a hook that exited 0 in silence."""

    def __init__(self) -> None:
        self.argv: list[tuple[str, ...]] = []

    def __call__(
        self, argv: Sequence[str], stdin: bytes, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> Captured:
        del stdin, cwd, env, timeout
        self.argv.append(tuple(argv))
        return Captured(0, b"", b"")


def _environ() -> dict[str, str]:
    return {"PATH": ""}


def _install(env: HostEnv, hooks: str = "steer") -> None:
    opts = InstallOptions(hooks=hooks, skills="none")  # type: ignore[arg-type]
    outcome = verbs.install("claude-code", "global", opts, env, yes=True)
    assert outcome.exit_code == verbs.OK, outcome.lines


def test_no_receipt_row_is_a_check_that_checked_nothing(tmp_path: Path) -> None:
    runner = _Runner()
    outcome = verbs.hooks_check(
        _env(tmp_path), environ=_environ(), runner=runner, scratch=tmp_path / "s"
    )
    assert outcome.exit_code == verbs.USAGE
    assert outcome.lines[0].startswith("no installed hook to check: the install receipt records")
    assert runner.argv == []


def test_the_commands_probed_are_the_ones_in_the_file_the_receipt_names(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _install(env)
    runner = _Runner()
    outcome = verbs.hooks_check(env, environ=_environ(), runner=runner, scratch=tmp_path / "s")
    assert outcome.exit_code == verbs.OK, outcome.lines
    assert outcome.lines[0] == "claude-code global  ~/.claude/settings.json"
    settings = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_bytes())
    installed = {
        hook["command"]
        for rules in settings["hooks"].values()
        for rule in rules
        for hook in rule["hooks"]
        if owned_event(hook["command"])
    }
    assert len(runner.argv) == len(installed) == 6
    assert all(argv[1:3] == ("-m", "omniweave") for argv in runner.argv)


def test_a_hook_the_receipt_records_and_the_file_lost_is_a_failure(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _install(env, hooks="context")
    path = tmp_path / "home" / ".claude" / "settings.json"
    document = json.loads(path.read_bytes())
    document["hooks"]["PreCompact"] = []
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    runner = _Runner()
    outcome = verbs.hooks_check(env, environ=_environ(), runner=runner, scratch=tmp_path / "s")
    assert outcome.exit_code == verbs.USAGE
    assert (
        "PreCompact        recorded by the receipt and not in ~/.claude/settings.json"
        in outcome.lines
    )
    assert len(runner.argv) == 4


def test_the_projects_stores_are_watched_for_sidecars(tmp_path: Path) -> None:
    """10:2081: *"no store WAL sidecar was created by the call"* -- over the project's stores."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "omniweave.toml").write_bytes(
        b'[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    )
    env = _env(tmp_path, root=project)
    _install(env)
    outcome = verbs.hooks_check(env, environ=_environ(), runner=_Runner(), scratch=tmp_path / "s")
    assert outcome.exit_code == verbs.OK, outcome.lines
    assert not any("no store watched" in line for line in outcome.lines)
    without = verbs.hooks_check(
        _env(tmp_path / "other"), environ=_environ(), runner=_Runner(), scratch=tmp_path / "t"
    )
    assert without.exit_code == verbs.USAGE


def test_a_local_install_is_checked_beside_the_global_one(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    env = _env(tmp_path, root=project)
    _install(env)
    opts = InstallOptions(hooks="context", skills="none")
    assert verbs.install("claude-code", "local", opts, env, yes=True).exit_code == verbs.OK
    runner = _Runner()
    outcome = verbs.hooks_check(env, environ=_environ(), runner=runner, scratch=tmp_path / "s")
    assert outcome.exit_code == verbs.OK, outcome.lines
    headers = [line for line in outcome.lines if line.startswith("claude-code ")]
    assert headers == [
        "claude-code global  ~/.claude/settings.json",
        f"claude-code local  {project.as_posix()}/.claude/settings.json",
    ]
    assert len(runner.argv) == 6 + 5
