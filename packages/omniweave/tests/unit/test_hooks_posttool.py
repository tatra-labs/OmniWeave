"""`PostToolUse`: the queue, the lease, the break, and an `argv[0]` test the plan gets wrong.

**The sharpest test here is `test_the_plans_own_isabs_accepts_a_path_this_rule_exists_to_reject`.**
10:2068 names `os.path.isabs` as the check that keeps an untrusted cwd out of the spawn, and on
Windows that function returns `True` for `\\ow.exe` and `/usr/bin/ow` -- both of which resolve
against the *current drive*, which is the cwd. The module uses `Path.is_absolute()` instead and the
test pins the disagreement so the reason cannot be lost. D425.

Nothing here spawns anything: `spawn` is a callable this suite supplies, which is the same seam that
keeps `subprocess` -- `TID251`-banned in this package -- out of the module.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks.envelope import EVENTS, emission
from omniweave.hooks.posttool import (
    CREATE_NO_WINDOW,
    DETACHED_PROCESS,
    LEASE_NAME,
    LEASE_TTL_MS,
    Lease,
    break_lease,
    command,
    edited_path,
    handler,
    queue_key,
    read_lease,
    release_lease,
    run_posttool,
    spawn_kwargs,
    take_lease,
    uncoalesced,
)
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR, journal_paths, read

if TYPE_CHECKING:
    from collections.abc import Sequence

KEY = "abc123"
EDIT: dict[str, Any] = {"tool_input": {"file_path": "docs/policy.md"}}


def _now() -> int:
    return time.time_ns()


def _store(tmp_path: Path) -> Path:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    return root


class Spawns:
    """A spawn that records its argv and can be told to fail."""

    def __init__(self, *, works: bool = True) -> None:
        self._works = works
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> bool:
        self.calls.append(tuple(argv))
        return self._works


# ---------------------------------------------------------------------------------------------
# The self-invocation rule. 10:2065, and the place the plan is wrong.
# ---------------------------------------------------------------------------------------------


def test_an_absolute_argv0_is_used_directly() -> None:
    assert command("C:/tools/ow.exe") == ("C:/tools/ow.exe", "ingest")


@pytest.mark.parametrize("argv0", ["ow", "./ow", "", "bin/ow", "..\\ow.exe"])
def test_a_relative_argv0_falls_back_to_the_interpreter(argv0: str) -> None:
    """10:2068: a relative `argv[0]` is re-resolved against the untrusted repository."""
    assert command(argv0, executable="/py") == ("/py", "-m", "omniweave", "ingest")


def test_the_fallback_uses_this_interpreter_and_needs_no_path_lookup() -> None:
    assert command("ow") == (sys.executable, "-m", "omniweave", "ingest")
    assert Path(sys.executable).is_absolute()


def test_a_relative_argv0_is_never_resolved_against_the_cwd(tmp_path: Path) -> None:
    """A file named `ow` in the checked-out repository must never become the thing we execute."""
    (tmp_path / "ow").write_text("#!/bin/sh\necho pwned\n", encoding="utf-8")
    here = Path.cwd()
    os.chdir(tmp_path)
    try:
        argv = command("ow")
    finally:
        os.chdir(here)

    assert str(tmp_path) not in " ".join(argv)


@pytest.mark.skipif(sys.platform != "win32", reason="the divergence is a Windows path rule")
def test_the_plans_own_isabs_accepts_a_path_this_rule_exists_to_reject() -> None:
    """D425. `os.path.isabs` calls two drive-relative forms absolute; both resolve against the cwd.

    10:2068 names `os.path.isabs` by name. On Windows it returns `True` for a path with a root and
    no drive, which Windows resolves against the drive of the *current directory* -- the untrusted
    repository the rule is about. `Path.is_absolute()` returns `False` for exactly those.
    """
    drive_relative = (chr(92) + "ow.exe", "/usr/bin/ow")

    for candidate in drive_relative:
        #  PTH117 wants `Path.is_absolute()`; calling the plan's function is the point here.
        assert os.path.isabs(candidate) is True  # noqa: PTH117
        assert Path(candidate).is_absolute() is False
        assert command(candidate)[0] != candidate  # the module rejects what the plan would accept

    for genuine in (
        "C:" + chr(92) + "tools" + chr(92) + "ow.exe",
        chr(92) * 2 + "srv" + chr(92) + "s" + chr(92) + "ow.exe",
    ):
        assert os.path.isabs(genuine) is True  # noqa: PTH117
        assert Path(genuine).is_absolute() is True
        assert command(genuine)[0] == genuine


def test_the_detach_flags_are_subprocesss_own() -> None:
    """The integers are spelled in the module because `subprocess` is banned there, not here."""
    if sys.platform == "win32":
        assert DETACHED_PROCESS == subprocess.DETACHED_PROCESS
        assert CREATE_NO_WINDOW == subprocess.CREATE_NO_WINDOW
        assert spawn_kwargs() == {"creationflags": DETACHED_PROCESS | CREATE_NO_WINDOW}
    else:
        assert spawn_kwargs() == {"start_new_session": True}


# ---------------------------------------------------------------------------------------------
# The lease. 10:2058.
# ---------------------------------------------------------------------------------------------


def test_the_lease_body_is_the_plans_three_fields(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()

    assert take_lease(root, pid=41, at_ns=now)

    body = json.loads((root / LEASE_NAME).read_text(encoding="utf-8"))
    assert body == {"pid": 41, "at_ns": now, "ttl_ms": 30_000}
    assert LEASE_TTL_MS == 30_000


def test_only_one_of_two_claims_succeeds(tmp_path: Path) -> None:
    """10:2060: *exactly one of N simultaneous hook processes creates it and spawns the child.*"""
    root = _store(tmp_path)

    assert take_lease(root, pid=1, at_ns=_now()) is True
    assert take_lease(root, pid=2, at_ns=_now()) is False


def test_a_lease_is_read_back_as_it_was_written(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    take_lease(root, pid=7, at_ns=now, ttl_ms=500)

    assert read_lease(root) == Lease(pid=7, at_ns=now, ttl_ms=500)


def test_a_missing_lease_reads_as_none(tmp_path: Path) -> None:
    assert read_lease(_store(tmp_path)) is None


def test_an_unparseable_lease_reads_as_absent_rather_than_held(tmp_path: Path) -> None:
    """A corrupt byte must not stop ingestion forever on an event with no channel to report it."""
    root = _store(tmp_path)
    (root / LEASE_NAME).write_text("{not json", encoding="utf-8")

    assert read_lease(root) is None


def test_expiry_is_measured_against_the_leases_own_ttl() -> None:
    now = _now()
    lease = Lease(pid=1, at_ns=now, ttl_ms=30_000)

    assert lease.expired(now + 29_000 * 1_000_000) is False
    assert lease.expired(now + 31_000 * 1_000_000) is True


def test_a_malformed_ttl_never_expires() -> None:
    """The safe reading of a malformed lease is *somebody may be draining*."""
    assert Lease(pid=1, at_ns=0, ttl_ms=0).expired(_now()) is False
    assert Lease(pid=1, at_ns=0, ttl_ms=-1).expired(_now()) is False


def test_an_unexpired_lease_is_not_broken(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    take_lease(root, pid=1, at_ns=now)

    assert break_lease(root, now_ns=now + 1_000) is False
    assert (root / LEASE_NAME).is_file()


def test_an_expired_lease_is_broken_so_the_next_claim_can_win(tmp_path: Path) -> None:
    """10:2062: *a killed child cannot wedge ingestion.*"""
    root = _store(tmp_path)
    now = _now()
    take_lease(root, pid=1, at_ns=now)
    later = now + 31_000 * 1_000_000

    assert break_lease(root, now_ns=later) is True
    assert take_lease(root, pid=2, at_ns=later) is True


def test_breaking_when_there_is_no_lease_is_false(tmp_path: Path) -> None:
    assert break_lease(_store(tmp_path), now_ns=_now()) is False


def test_the_child_releases_the_lease(tmp_path: Path) -> None:
    root = _store(tmp_path)
    take_lease(root, pid=1, at_ns=_now())

    assert release_lease(root) is True
    assert read_lease(root) is None


def test_releasing_a_lease_that_is_already_gone_is_not_an_error(tmp_path: Path) -> None:
    assert release_lease(_store(tmp_path)) is True


# ---------------------------------------------------------------------------------------------
# Coalescing. 10:2052.
# ---------------------------------------------------------------------------------------------


def test_the_first_edit_of_a_burst_spawns_and_the_rest_do_not(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    spawn = Spawns()

    first = run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=1, spawn=spawn)
    second = run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=2, spawn=spawn)
    third = run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=3, spawn=spawn)

    assert first.counter == "drained"
    assert second.counter == third.counter == "enqueued"
    assert len(spawn.calls) == 1


def test_every_edit_of_a_burst_is_enqueued_even_when_it_does_not_spawn(tmp_path: Path) -> None:
    """The append comes first: losing the claim must cost nothing but the spawn."""
    root = _store(tmp_path)
    now = _now()
    spawn = Spawns()

    for index in range(4):
        run_posttool(
            {"tool_input": {"file_path": f"a{index}.md"}},
            root=root,
            key=KEY,
            now_ns=now,
            pid=index,
            spawn=spawn,
        )

    queued = read(root, queue_key(KEY), now_ns=now)
    assert [record["path"] for record in queued.records] == ["a0.md", "a1.md", "a2.md", "a3.md"]


def test_a_burst_after_the_ttl_breaks_the_lease_and_drains_again(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    spawn = Spawns()
    run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=1, spawn=spawn)

    later = run_posttool(
        EDIT, root=root, key=KEY, now_ns=now + 31_000 * 1_000_000, pid=2, spawn=spawn
    )

    assert later.counter == "drained-after-break"
    assert len(spawn.calls) == 2


def test_a_failed_spawn_releases_the_lease_so_the_next_edit_can_try(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    broken, working = Spawns(works=False), Spawns()

    first = run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=1, spawn=broken)
    second = run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=2, spawn=working)

    assert first.counter == "noop-spawn-failed"
    assert second.counter == "drained"
    assert len(working.calls) == 1


def test_no_spawn_at_all_is_a_counter_and_not_a_wedged_lease(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_posttool(EDIT, root=root, key=KEY, now_ns=_now(), pid=1, spawn=None)

    assert advice.counter == "noop-spawn-failed"
    assert read_lease(root) is None


def test_the_spawn_receives_the_ingest_command(tmp_path: Path) -> None:
    """`argv0` must be absolute *for this platform*: `/opt/bin/ow` is drive-relative here."""
    root = _store(tmp_path)
    spawn = Spawns()
    absolute = "C:" + chr(92) + "tools" + chr(92) + "ow.exe" if sys.platform == "win32" else "/o/ow"

    run_posttool(EDIT, root=root, key=KEY, now_ns=_now(), pid=1, spawn=spawn, argv0=absolute)

    assert spawn.calls == [(absolute, "ingest")]


def test_the_queue_is_json_lines_that_can_report_their_own_losses(tmp_path: Path) -> None:
    """D421: `.pending` is appended by N processes, which is what D400 measured."""
    root = _store(tmp_path)
    now = _now()
    run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=1, spawn=Spawns())

    line = journal_paths(root, queue_key(KEY))[0].read_bytes().splitlines()[0]
    record = json.loads(line)

    assert record["path"] == "docs/policy.md"
    assert record["kind"] == "edited"
    assert {"pid", "seq", "at_ns"} <= set(record)


# ---------------------------------------------------------------------------------------------
# The payload. D423.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_input": {"file_path": "a.md"}},
        {"tool_input": {"path": "a.md"}},
        {"tool_input": {"filePath": "a.md"}},
        {"tool_input": {"notebook_path": "a.md"}},
        {"file_path": "a.md"},
    ],
)
def test_the_edited_path_is_found_under_any_of_the_spellings(payload: dict[str, Any]) -> None:
    """The plan names `trigger` and `session_id` where it needs them and never names this one."""
    assert edited_path(payload) == "a.md"


def test_tool_input_wins_over_the_top_level() -> None:
    assert edited_path({"tool_input": {"file_path": "inner.md"}, "file_path": "outer.md"}) == (
        "inner.md"
    )


@pytest.mark.parametrize(
    "payload",
    [{}, {"tool_input": {}}, {"tool_input": {"file_path": "  "}}, {"tool_input": "a.md"}],
)
def test_a_payload_with_no_usable_path_enqueues_nothing(payload: dict[str, Any]) -> None:
    assert edited_path(payload) == ""


def test_a_list_of_paths_is_not_enqueued_as_its_repr() -> None:
    """`str(["a.md"])` in the queue is a line `ow ingest` cannot use."""
    assert edited_path({"tool_input": {"file_path": ["a.md", "b.md"]}}) == ""


def test_no_path_means_no_write_at_all(tmp_path: Path) -> None:
    root = _store(tmp_path)
    spawn = Spawns()

    advice = run_posttool({}, root=root, key=KEY, now_ns=_now(), pid=1, spawn=spawn)

    assert advice.counter == "noop-no-path"
    assert list(root.iterdir()) == []
    assert spawn.calls == []


def test_a_deployment_with_nowhere_to_queue_says_so(tmp_path: Path) -> None:
    assert run_posttool(EDIT, root=None, key="", now_ns=_now(), pid=1).counter == "noop-no-key"
    assert (
        run_posttool(EDIT, root=_store(tmp_path), key="", now_ns=_now(), pid=1).counter
        == "noop-no-key"
    )


# ---------------------------------------------------------------------------------------------
# Under the envelope.
# ---------------------------------------------------------------------------------------------


def test_this_event_has_no_channel_so_nothing_is_ever_emitted(tmp_path: Path) -> None:
    root = _store(tmp_path)
    advice = run_posttool(EDIT, root=root, key=KEY, now_ns=_now(), pid=1, spawn=Spawns())

    assert EVENTS["PostToolUse"].cap == 0
    assert advice.text == ""
    assert emission("PostToolUse", advice) == ""


def test_the_handler_binds_its_seams(tmp_path: Path) -> None:
    root = _store(tmp_path)
    spawn = Spawns()
    now = _now()
    bound = handler(root, key_of=lambda _: KEY, now_ns=lambda: now, pid=9, spawn=spawn)

    assert bound(EDIT).counter == "drained"
    assert read_lease(root) == Lease(pid=9, at_ns=now, ttl_ms=LEASE_TTL_MS)


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_module_imports_no_subprocess_and_no_core() -> None:
    import ast  # noqa: PLC0415

    import omniweave.hooks.posttool as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) if node.module}

    assert "subprocess" not in names
    assert not [name for name in names if name.startswith("omniweave_core")]


def test_the_uncoalesced_list_names_the_six_readings_this_enqueue_runs_against() -> None:
    stated = uncoalesced()

    assert len(stated) == 6
    assert any("D421" in item for item in stated)
    assert any("D425" in item for item in stated)
