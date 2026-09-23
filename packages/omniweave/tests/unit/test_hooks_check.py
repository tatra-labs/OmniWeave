"""`ow hooks check`'s engine in-process: fixtures, resolution, five judgements, the scratch project.

**The sharpest test is `test_a_probe_never_writes_outside_its_scratch_project`.** 10:2088 says a
scratch `$OMNIWEAVE_HOME` makes the check unable to mutate the deployment, and 10:1893 puts every
file a hook writes beside `omniweave.toml` instead -- so this asserts where the probe's cwd is, and
that the kill switch and home the child sees are the scratch ones. D437.

Nothing here spawns: the runner is a fake that records what it was handed. The same engine against
real children is `tests/conform/test_hooks_process.py`.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks import check as module
from omniweave.hooks.check import (
    FAIL,
    NOT_RESOLVABLE,
    OK,
    UNPROVEN,
    check,
    fixture,
    judge,
    probe,
    render,
    resolve,
    scratch_project,
    sidecars,
    split,
    unchecked,
)
from omniweave.hooks.envelope import EVENTS, SELF_DEADLINE_MS, Advice, emission
from omniweave.hooks.main import WORDS, main
from omniweave_core.host.subproc import Captured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conftest import PlanDocs

REPO = Path(__file__).resolve().parents[4]
EXE = "C:/tools/ow.exe"
INTERPRETER = Path(sys.executable).as_posix()


class _Clock:
    """Each reading advances by `step_ms`, so a probe's wall time is exactly one step."""

    def __init__(self, step_ms: int = 50) -> None:
        self._now = 0
        self._step = step_ms * 1_000_000

    def monotonic_ns(self) -> int:
        self._now += self._step
        return self._now

    def wall_ns(self) -> int:
        return self._now


class _Runner:
    """Records every call and answers with one canned `Captured`."""

    def __init__(self, answer: Captured | None = None) -> None:
        self.answer = answer or Captured(0)
        self.calls: list[tuple[tuple[str, ...], bytes, Path, dict[str, str], float]] = []

    def __call__(
        self, argv: Sequence[str], stdin: bytes, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> Captured:
        self.calls.append((tuple(argv), stdin, cwd, dict(env), timeout))
        return self.answer


def _exists(_path: Path) -> bool:
    return True


def _commands() -> dict[str, str]:
    """A real absolute executable, quoted and forward-slashed, so resolution runs for real."""
    return {event: f"'{INTERPRETER}' hook {word}" for word, event in WORDS.items()}


def _check(
    tmp_path: Path,
    runner: _Runner,
    *,
    env: Mapping[str, str] | None = None,
    commands: Mapping[str, str] | None = None,
    step_ms: int = 50,
    watch: Sequence[Path] = (),
) -> module.Report:
    return check(
        _commands() if commands is None else commands,
        runner=runner,
        clock=_Clock(step_ms),
        path="C:/bin",
        scratch=tmp_path,
        env={} if env is None else env,
        watch=watch,
    )


# ---------------------------------------------------------------------------------------------
# Fixtures. D436.
# ---------------------------------------------------------------------------------------------


def test_every_event_has_a_fixture_naming_itself() -> None:
    for word, event in WORDS.items():
        payload = json.loads(fixture(word))
        assert payload["hook_event_name"] == event
        assert payload["session_id"]


def test_the_fixtures_are_the_files_the_handlers_are_fed(tmp_path: Path) -> None:
    """10:2086's one-copy rule: the probe's payload is what the handler is driven with here."""
    import io  # noqa: PLC0415

    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text("", encoding="utf-8")
    for word in WORDS:
        outcome = main(
            [word],
            stdin=io.BytesIO(fixture(word)),
            stdout=io.BytesIO(),
            env={},
            clock=_Clock(),
            cwd=tmp_path,
            tty=False,
            pid=1,
        )
        assert outcome.failed == "", word
        assert not outcome.counters[0].endswith(("noop-failure", "noop-event")), word


def test_the_plan_puts_the_fixtures_in_a_tree_no_artefact_ships(plan: PlanDocs) -> None:
    """D436: 10:2086 says `tests/fixtures/hooks/`; the wheel ships `src/omniweave`, sdist `src`."""
    plan.require()
    assert "tests/fixtures/hooks/<event>.json" in plan.text("10-interfaces.md")
    build = tomllib.loads((REPO / "packages/omniweave/pyproject.toml").read_text("utf-8"))
    targets = build["tool"]["hatch"]["build"]["targets"]
    assert targets["wheel"]["packages"] == ["src/omniweave"]
    assert "tests" not in targets["sdist"]["include"]
    assert (REPO / "packages/omniweave/src/omniweave/hooks/fixtures").is_dir()


# ---------------------------------------------------------------------------------------------
# Resolution. D439, and the three bugs 10:2083 names.
# ---------------------------------------------------------------------------------------------


def test_a_posix_split_eats_unquoted_backslashes() -> None:
    assert split("C:\\x\\ow.exe hook session-end") == ("C:xow.exe", "hook", "session-end")
    assert split("C:\\x\\ow.exe hook", posix=False) == ("C:\\x\\ow.exe", "hook")


def test_the_backslash_bug_is_named_as_itself_and_not_as_a_path_problem() -> None:
    found = resolve("C:\\tools\\ow.exe hook session-end", path="C:/bin", exists=_exists)

    assert not found.ok()
    assert "consumed the backslashes" in found.reason
    assert "C:toolsow.exe" in found.reason


def test_a_quoted_forward_slash_path_survives_the_same_shell() -> None:
    found = resolve("'C:/Program Files/ow/ow.exe' hook x", path="", exists=_exists)

    assert found.ok()
    assert found.argv == ("C:/Program Files/ow/ow.exe", "hook", "x")


def test_a_windows_split_keeps_the_backslashes() -> None:
    found = resolve("C:\\tools\\ow.exe hook x", path="", posix=False, exists=_exists)

    assert found.ok()
    assert found.executable == "C:\\tools\\ow.exe"


def test_a_stale_absolute_path_is_not_resolvable() -> None:
    """The `pipx reinstall` case: the path was right once."""
    found = resolve(f"{EXE} hook x", path="", exists=lambda _p: False)

    assert not found.ok()
    assert found.reason == f"{EXE} does not exist"


@pytest.mark.parametrize("head", ["./ow", "bin/ow", "..\\ow.exe"])
def test_a_relative_path_is_refused_without_being_looked_up(head: str) -> None:
    looked: list[str] = []

    def _which(name: str, path: str) -> str | None:
        looked.append(name)
        return path

    found = resolve(f"{head} hook x", path="C:/bin", posix=False, which=_which)

    assert not found.ok()
    assert "would resolve in the cwd" in found.reason
    assert looked == []


def test_a_bare_name_that_resolves_is_still_flagged_host_path() -> None:
    """D439: found on this PATH, which is not the host's."""
    found = resolve("ow hook x", path="C:/bin", which=lambda _n, _p: "C:/bin/ow.exe")

    assert found.ok()
    assert found.host_path
    assert found.argv == ("C:/bin/ow.exe", "hook", "x")


def test_a_bare_name_is_searched_on_the_path_given_and_no_other() -> None:
    seen: list[str] = []

    def _which(_name: str, path: str) -> str | None:
        seen.append(path)
        return None

    found = resolve("ow hook x", path="/minimal", which=_which)

    assert seen == ["/minimal"]
    assert found.reason == "ow is not on PATH"
    assert found.host_path


@pytest.mark.parametrize("command", ["", "   ", "'unbalanced", 'ow "x'])
def test_an_unparseable_command_is_not_resolvable(command: str) -> None:
    assert resolve(command, path="").reason == "empty or unparseable command string"


# ---------------------------------------------------------------------------------------------
# The five judgements. 10:2079.
# ---------------------------------------------------------------------------------------------


def _status(results: tuple[module.Judged, ...]) -> dict[str, str]:
    return {item.name: item.status for item in results}


def test_a_real_emission_from_each_speaking_event_passes() -> None:
    for event, spec in EVENTS.items():
        if not spec.speaks():
            continue
        out = emission(event, Advice(text="hello")).encode()
        assert set(_status(judge(event, returncode=0, stdout=out, wall_ms=90)).values()) == {OK}


def test_the_deny_channel_is_allowed_on_pretooluse_and_nowhere_else() -> None:
    deny = emission("PreToolUse", Advice(text="no", deny=True)).encode()
    forged = deny.replace(b"PreToolUse", b"UserPromptSubmit")

    assert _status(judge("PreToolUse", returncode=0, stdout=deny, wall_ms=1))["channel"] == OK
    judged = _status(judge("UserPromptSubmit", returncode=0, stdout=forged, wall_ms=1))
    assert judged["channel"] == FAIL


def test_a_silent_channel_event_passes() -> None:
    """18:2994 prints `(silent)` for `UserPromptSubmit`: saying nothing is a correct answer."""
    judged = _status(judge("UserPromptSubmit", returncode=0, stdout=b"", wall_ms=1))

    assert judged["json"] == judged["channel"] == OK


def test_a_channel_less_event_that_prints_fails() -> None:
    """10:1926's jcodemunch bug: a briefing written into a field nobody reads."""
    out = b'{"hookSpecificOutput":{"hookEventName":"PreCompact","additionalContext":"x"}}'

    judged = _status(judge("PreCompact", returncode=0, stdout=out, wall_ms=1))

    assert judged["json"] == judged["channel"] == FAIL


@pytest.mark.parametrize(
    ("stdout", "failing"),
    [
        (b"not json", "json"),
        (b"[1]", "channel"),
        (b'{"hookSpecificOutput": {"hookEventName": "SessionEnd"}}', "channel"),
        (b'{"additionalContext": "top-level is the user-facing field"}', "channel"),
    ],
)
def test_stdout_that_is_not_this_events_channel_fails(stdout: bytes, failing: str) -> None:
    assert _status(judge("SessionStart", returncode=0, stdout=stdout, wall_ms=1))[failing] == FAIL


@pytest.mark.parametrize("returncode", [1, 2, -11, None])
def test_anything_but_exit_0_fails(returncode: int | None) -> None:
    assert (
        _status(judge("SessionEnd", returncode=returncode, stdout=b"", wall_ms=1))["exit"] == FAIL
    )


def test_the_deadline_is_proven_at_or_under_400_and_unproven_above() -> None:
    """D438: spawn-inclusive time bounds the in-process time from above, and only from above."""
    at = _status(judge("SessionEnd", returncode=0, stdout=b"", wall_ms=SELF_DEADLINE_MS))
    over = _status(judge("SessionEnd", returncode=0, stdout=b"", wall_ms=SELF_DEADLINE_MS + 1))

    assert at["deadline"] == OK
    assert over["deadline"] == UNPROVEN


def test_a_created_sidecar_fails() -> None:
    judged = judge("SessionStart", returncode=0, stdout=b"", wall_ms=1, created=["s.db-wal"])

    assert _status(judged)["sidecars"] == FAIL


def test_sidecars_finds_wal_and_shm_beside_each_watched_store(tmp_path: Path) -> None:
    store = tmp_path / "corpus.db"
    store.write_bytes(b"")
    assert sidecars([store]) == frozenset()

    (tmp_path / "corpus.db-wal").write_bytes(b"")
    (tmp_path / "corpus.db-shm").write_bytes(b"")

    assert sidecars([store]) == {str(store) + "-wal", str(store) + "-shm"}


# ---------------------------------------------------------------------------------------------
# The probe and the report. D437.
# ---------------------------------------------------------------------------------------------


def test_a_probe_never_writes_outside_its_scratch_project(tmp_path: Path) -> None:
    runner = _Runner()

    _check(tmp_path / "scratch", runner, env={"OMNIWEAVE_HOME": "/real/home", "HOME": "/h"})

    project, home = tmp_path / "scratch" / "project", tmp_path / "scratch" / "home"
    for _argv, _stdin, cwd, env, _timeout in runner.calls:
        assert cwd == project
        assert env["OMNIWEAVE_HOME"] == str(home)
        assert env["PATH"] == "C:/bin"
        assert env["HOME"] == "/h"
    assert (project / "omniweave.toml").is_file()
    assert (project / ".git").is_dir()


def test_the_kill_switch_is_stripped_from_the_child_and_reported(tmp_path: Path) -> None:
    """Inherited, `OMNIWEAVE_HOOK=0` would make every probe pass on hooks that are off."""
    runner = _Runner()

    report = _check(tmp_path, runner, env={"OMNIWEAVE_HOOK": "0"})

    assert all("OMNIWEAVE_HOOK" not in call[3] for call in runner.calls)
    assert any("OMNIWEAVE_HOOK is set" in note for note in report.notes)


def test_each_probe_is_fed_its_own_events_fixture(tmp_path: Path) -> None:
    runner = _Runner()

    _check(tmp_path, runner)

    for argv, stdin, *_rest in runner.calls:
        assert stdin == fixture(argv[-1])


def test_probes_run_in_the_handler_tables_order_whatever_the_mapping_order(tmp_path: Path) -> None:
    runner = _Runner()
    reversed_commands = dict(reversed(list(_commands().items())))

    report = _check(tmp_path, runner, commands=reversed_commands)

    assert [item.event for item in report.probes] == list(EVENTS)


def test_an_unresolvable_command_is_never_executed(tmp_path: Path) -> None:
    runner = _Runner()

    found = probe(
        "SessionEnd",
        "./ow hook session-end",
        runner=runner,
        clock=_Clock(),
        path="",
        cwd=tmp_path,
        env={},
    )

    assert runner.calls == []
    assert found.status() == FAIL
    assert NOT_RESOLVABLE in render(module.Report((found,)))


def test_a_spawn_that_fails_after_resolving_is_ow_a_030_too(tmp_path: Path) -> None:
    """10:2082 reports OW-A-030 *"when the spawn fails"*, not only when resolution does."""
    report = _check(tmp_path, _Runner(Captured(None, failed="PermissionError")))

    assert report.exit_code() == 1
    text = render(report)
    assert f"{NOT_RESOLVABLE} · resolved but the spawn failed: PermissionError" in text
    assert "PATH searched: C:/bin" in text


def test_a_timeout_is_a_failure_and_not_a_resolution_problem(tmp_path: Path) -> None:
    report = _check(tmp_path, _Runner(Captured(None, failed="TimeoutExpired")))

    assert report.exit_code() == 1
    assert "killed after 10 s" in render(report)
    assert NOT_RESOLVABLE not in render(report)


def test_a_probe_that_creates_a_sidecar_fails_the_report(tmp_path: Path) -> None:
    store = tmp_path / "corpus.db"
    store.write_bytes(b"")

    class _Opens(_Runner):
        def __call__(self, *args: Any, **kwargs: Any) -> Captured:
            (tmp_path / "corpus.db-wal").write_bytes(b"")
            return super().__call__(*args, **kwargs)

    report = _check(tmp_path / "s", _Opens(), watch=[store])

    assert report.exit_code() == 1
    assert "sidecars fail" in render(report)


def test_no_watched_store_is_reported_as_a_vacuous_assertion(tmp_path: Path) -> None:
    report = _check(tmp_path, _Runner())

    assert any("vacuous" in note for note in report.notes)


def test_exit_code_is_0_when_all_pass_and_when_only_the_deadline_is_unproven(
    tmp_path: Path,
) -> None:
    assert _check(tmp_path / "a", _Runner(), step_ms=50).exit_code() == 0
    slow = _check(tmp_path / "b", _Runner(), step_ms=SELF_DEADLINE_MS + 1)
    assert slow.exit_code() == 0
    assert {item.status() for item in slow.probes} == {UNPROVEN}
    assert _check(tmp_path / "c", _Runner(Captured(1))).exit_code() == 1


# ---------------------------------------------------------------------------------------------
# Rendering: 18:2991-2997's table.
# ---------------------------------------------------------------------------------------------

_ROW = re.compile(r"^(\w+)\s+(\S.*?)\s+resolved · exit 0 ·\s+\d+ ms( \(silent\))?$")


def test_a_passing_row_has_the_shape_of_the_plans_rows(plan: PlanDocs, tmp_path: Path) -> None:
    plan.require()
    printed = [
        line
        for line in plan.text("18-api-sketch.md").split("\n")
        if line.split(" ", 1)[0] in EVENTS and "resolved" in line
    ]
    assert len(printed) == 5
    assert all(_ROW.match(line) for line in printed)

    ours = render(_check(tmp_path, _Runner())).split("\n")[: len(EVENTS)]

    assert all(_ROW.match(line) for line in ours), ours


def test_a_silent_channel_event_is_marked_silent_and_a_channel_less_one_is_not(
    tmp_path: Path,
) -> None:
    rows = {
        line.split(" ", 1)[0]: line
        for line in render(_check(tmp_path, _Runner())).split("\n")
        if line.split(" ", 1)[0] in EVENTS
    }

    assert rows["UserPromptSubmit"].endswith("(silent)")
    assert not rows["SessionEnd"].endswith("(silent)")


def test_nothing_ran_is_not_reported_as_zero_proven(tmp_path: Path) -> None:
    probes = tuple(
        probe(e, "./ow hook x", runner=_Runner(), clock=_Clock(), path="", cwd=tmp_path, env={})
        for e in EVENTS
    )
    text = render(module.Report(probes))

    assert "proven" not in text
    assert f"{len(EVENTS)} of {len(EVENTS)} did not run" in text


def test_the_summary_names_the_parse_used() -> None:
    assert "POSIX shell" in render(module.Report(posix=True))
    assert "Windows" in render(module.Report(posix=False))


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_symbol_is_ow_a_030_in_the_code_registry() -> None:
    codes = tomllib.loads((REPO / "codes.toml").read_text("utf-8"))["code"]

    assert {row["symbol"]: row["numeric"] for row in codes}[NOT_RESOLVABLE] == "OW-A-030"


def test_the_module_imports_no_subprocess() -> None:
    import ast  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) if node.module}

    assert "subprocess" not in names


def test_the_scratch_project_is_idempotent(tmp_path: Path) -> None:
    first = scratch_project(tmp_path)

    assert scratch_project(tmp_path) == first


def test_the_unchecked_list_names_what_this_check_runs_against() -> None:
    stated = unchecked()

    assert len(stated) == 6
    for entry in ("D436", "D437", "D438", "D439", "D440"):
        assert any(entry in item for item in stated), entry
