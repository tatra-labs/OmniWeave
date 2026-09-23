"""`SessionEnd`: one undefined word, a sweep two other triggers already run, and a queue it drains.

**The sharpest test here is `test_a_session_end_leaves_the_journal_resume_exists_to_read`.** The
natural reading of 10:1917's *"`SessionEnd` prunes on the way out"* is *cleans up after itself*, and
that reading would delete the journal `SessionStart(source=resume)` reads when the user comes back.
The test runs both events in sequence and asserts the briefing survives. D429.

`test_flush_occurs_once_in_the_hooks_section_and_only_in_this_events_row` is the D426 claim made
checkable: the word that describes this event's job appears once in section 8 and is defined
nowhere.

Nothing spawns: `spawn` is a callable this suite supplies. Every clock reading is the real wall
clock, because the sweep compares against filesystem mtimes (D412) and a frozen clock would be
testing the sweep's ability to delete its own fixtures.
"""

from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks import posttool
from omniweave.hooks.envelope import EVENTS, Advice, emission, run, session_key
from omniweave.hooks.posttool import (
    LEASE_NAME,
    LEASE_TTL_MS,
    queue_key,
    read_lease,
    run_posttool,
    take_lease,
)
from omniweave.hooks.precompact import KINDS
from omniweave.hooks.session import (
    CONTROL_DIR,
    SESSIONS_DIR,
    SWEEP_AGE_S,
    append,
    journal_paths,
    read,
)
from omniweave.hooks.sessionend import (
    ENDED,
    QUEUE_AGE_MIN,
    UNKNOWN_REASON,
    end_reason,
    flush,
    handler,
    own_files,
    queued,
    run_sessionend,
    unflushed,
)
from omniweave.hooks.sessionstart import run_sessionstart

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from conftest import PlanDocs

SESSION: Mapping[str, Any] = {"session_id": "abc-123"}
KEY: str = session_key(SESSION)
OTHER: str = session_key({"session_id": "someone-else"})
EDIT: Mapping[str, Any] = {"tool_input": {"file_path": "docs/policy.md"}}

_NS_PER_MIN = 60 * 1_000_000_000
_DAY_NS = SWEEP_AGE_S * 1_000_000_000


def _now() -> int:
    return time.time_ns()


def _store(tmp_path: Path) -> Path:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    return root


def _enqueue(root: Path, key: str, *, at_ns: int, count: int = 1) -> None:
    for index in range(count):
        append(
            root,
            queue_key(key),
            {posttool.KIND: posttool.EDITED, "path": f"a{index}.md"},
            at_ns=at_ns,
            seq=index,
        )


def _age(path: Path, *, days: float) -> None:
    """Move a file's mtime back, which is the only clock the sweep reads."""
    then = time.time() - days * 24 * 60 * 60
    os.utime(path, (then, then))


class Spawns:
    """A spawn that records its argv and can be told to fail."""

    def __init__(self, *, works: bool = True) -> None:
        self._works = works
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> bool:
        self.calls.append(tuple(argv))
        return self._works


class _Clock:
    def __init__(self, now: int) -> None:
        self._now = now

    def monotonic_ns(self) -> int:
        return self._now

    def wall_ns(self) -> int:
        return self._now


# ---------------------------------------------------------------------------------------------
# What the plan says about this event, which is almost nothing. D426.
# ---------------------------------------------------------------------------------------------


def _section_eight(plan: PlanDocs) -> list[str]:
    plan.require()
    lines = plan.text("10-interfaces.md").split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("## 8. Hooks"))
    end = next(i for i, line in enumerate(lines) if i > start and line.startswith("## 9."))
    return lines[start:end]


def test_flush_occurs_once_in_the_hooks_section_and_only_in_this_events_row(
    plan: PlanDocs,
) -> None:
    """D426: the one word describing this event's job is used once and defined nowhere.

    `flushed` at 10:2005 is a different word about a different thing -- stdout -- and is excluded
    by the word boundary, which is the point: the plan's only other use is not this one.
    """
    hits = [line for line in _section_eight(plan) if re.search(r"\bflush\b", line)]

    assert len(hits) == 1
    assert hits[0].startswith("| `SessionEnd` |")


def test_four_events_have_a_subsection_and_this_one_has_none(plan: PlanDocs) -> None:
    headings = [line for line in _section_eight(plan) if line.startswith("### ")]

    for event in ("PreCompact", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
        assert any(f"`{event}`" in heading for heading in headings), event
    assert not [heading for heading in headings if "SessionEnd" in heading]


def test_the_only_prose_about_this_event_is_a_caveat_about_not_relying_on_it(
    plan: PlanDocs,
) -> None:
    """Three lines in section 8 name the event: the table row and a two-line pruning caveat."""
    named = [line for line in _section_eight(plan) if "SessionEnd" in line]

    assert len(named) == 3
    assert named[0].startswith("| `SessionEnd` |")
    assert "Pruning does not depend on `SessionEnd` firing." in named[1]


def test_the_240_minute_bound_is_argued_from_a_briefings_honesty(plan: PlanDocs) -> None:
    """D428: stated for *every* hook read, argued from *"this task's focus"* -- a briefing rule."""
    section = "\n".join(_section_eight(plan))

    assert "**Every hook read is age-bounded at 240 minutes**" in section
    assert "must not present days-old work as this task's focus" in section


def test_the_queue_bound_is_the_sweeps_lifetime_and_not_the_briefings() -> None:
    assert QUEUE_AGE_MIN == 24 * 60
    assert QUEUE_AGE_MIN * 60 == SWEEP_AGE_S


# ---------------------------------------------------------------------------------------------
# The reason field. D423's shape again.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"reason": "logout"}, "logout"),
        ({"reason": " clear "}, "clear"),
        ({}, UNKNOWN_REASON),
        ({"reason": ""}, UNKNOWN_REASON),
        ({"reason": "   "}, UNKNOWN_REASON),
        ({"reason": 3}, UNKNOWN_REASON),
        ({"reason": ["logout"]}, UNKNOWN_REASON),
    ],
)
def test_the_end_reason_is_a_non_empty_string_or_unknown(
    payload: Mapping[str, Any], expected: str
) -> None:
    assert end_reason(payload) == expected


def test_the_unknown_default_is_the_one_the_plan_gives_precompacts_trigger() -> None:
    from omniweave.hooks.precompact import UNKNOWN_TRIGGER  # noqa: PLC0415

    assert UNKNOWN_REASON == UNKNOWN_TRIGGER


# ---------------------------------------------------------------------------------------------
# The queue is its own file. 10:2054, and a correction to W7.4g.
# ---------------------------------------------------------------------------------------------


def test_the_queue_is_its_own_file_and_not_the_session_journal(tmp_path: Path) -> None:
    root = _store(tmp_path)

    run_posttool(EDIT, root=root, key=KEY, now_ns=_now(), pid=1, spawn=Spawns())

    journal, _ = journal_paths(root, KEY)
    queue, _ = journal_paths(root, queue_key(KEY))
    assert queue.is_file()
    assert not journal.exists()


def test_the_queue_file_carries_the_plans_pending_suffix(tmp_path: Path) -> None:
    root = _store(tmp_path)

    live, rotated = journal_paths(root, queue_key("k"))

    assert queue_key("k") == "k.pending"
    assert (live.name, rotated.name) == ("k.pending.jsonl", "k.pending.1.jsonl")


def test_the_end_record_is_not_a_kind_the_briefing_renders() -> None:
    """`render_briefing()` groups by 10:1958's four kinds, so a restored session is not told."""
    assert ENDED not in KINDS
    assert posttool.EDITED not in KINDS


# ---------------------------------------------------------------------------------------------
# Counting what is queued. D428.
# ---------------------------------------------------------------------------------------------


def test_an_empty_or_absent_queue_counts_zero(tmp_path: Path) -> None:
    root = _store(tmp_path)

    assert queued(root, KEY, now_ns=_now()) == 0
    assert queued(tmp_path / "nowhere", KEY, now_ns=_now()) == 0


def test_only_edit_records_are_counted(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now, count=3)
    append(root, queue_key(KEY), {posttool.KIND: "something-else"}, at_ns=now)

    assert queued(root, KEY, now_ns=now) == 3


def test_a_five_hour_old_edit_is_still_outstanding_work(tmp_path: Path) -> None:
    """D428: 10:1884's 240 minutes would hide it; the file still holds it for 19 more hours."""
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now - 300 * _NS_PER_MIN)

    assert queued(root, KEY, now_ns=now) == 1
    assert queued(root, KEY, now_ns=now, max_age_min=240) == 0


def test_an_edit_older_than_the_sweep_is_not_counted(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now - _DAY_NS - _NS_PER_MIN)

    assert queued(root, KEY, now_ns=now) == 0


def test_a_torn_queue_line_is_skipped_and_never_raises(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now, count=2)
    live, _ = journal_paths(root, queue_key(KEY))
    with live.open("ab") as handle:
        handle.write(b'{"kind":"edited","pa')

    assert queued(root, KEY, now_ns=now) == 2


def test_own_files_are_both_generations_of_the_journal_and_the_queue(tmp_path: Path) -> None:
    assert own_files(_store(tmp_path), KEY) == {
        f"{KEY}.jsonl",
        f"{KEY}.1.jsonl",
        f"{KEY}.pending.jsonl",
        f"{KEY}.pending.1.jsonl",
    }


# ---------------------------------------------------------------------------------------------
# The flush. 10:1856's first word, read as "drain what is queued".
# ---------------------------------------------------------------------------------------------


def test_nothing_queued_is_quiet_and_takes_no_lease(tmp_path: Path) -> None:
    root = _store(tmp_path)
    spawn = Spawns()

    tier = flush(root, KEY, now_ns=_now(), pid=1, spawn=spawn)

    assert tier == "quiet"
    assert spawn.calls == []
    assert read_lease(root) is None


def test_queued_work_spawns_one_drain_and_holds_the_lease(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)
    spawn = Spawns()

    tier = flush(root, KEY, now_ns=now, pid=7, spawn=spawn)

    assert tier == "flushed"
    assert len(spawn.calls) == 1
    lease = read_lease(root)
    assert lease is not None
    assert lease.pid == 7


def test_a_live_lease_means_someone_is_draining_and_this_stands_down(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)
    assert take_lease(root, pid=99, at_ns=now)
    spawn = Spawns()

    tier = flush(root, KEY, now_ns=now, pid=1, spawn=spawn)

    assert tier == "noop-lease-held"
    assert spawn.calls == []
    lease = read_lease(root)
    assert lease is not None
    assert lease.pid == 99


def test_an_expired_lease_is_broken_and_the_queue_drained(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)
    assert take_lease(root, pid=99, at_ns=now - (LEASE_TTL_MS + 1_000) * 1_000_000)
    spawn = Spawns()

    tier = flush(root, KEY, now_ns=now, pid=1, spawn=spawn)

    assert tier == "flushed"
    lease = read_lease(root)
    assert lease is not None
    assert lease.pid == 1


def test_a_failed_spawn_releases_the_lease(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)

    tier = flush(root, KEY, now_ns=now, pid=1, spawn=Spawns(works=False))

    assert tier == "noop-spawn-failed"
    assert not (root / LEASE_NAME).exists()


def test_no_spawn_at_all_releases_the_lease(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)

    tier = flush(root, KEY, now_ns=now, pid=1, spawn=None)

    assert tier == "noop-spawn-failed"
    assert read_lease(root) is None


def test_the_drain_is_posttools_command_and_honours_the_argv0_rule(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)
    spawn = Spawns()

    flush(root, KEY, now_ns=now, pid=1, spawn=spawn, argv0="ow")

    assert spawn.calls == [posttool.command("ow")]
    assert spawn.calls[0][-1] == "ingest"


def test_a_crashed_sessions_queue_is_not_drained_by_another_sessions_end(tmp_path: Path) -> None:
    """D427, pinned as current behaviour rather than endorsed.

    Session A's host died with an edit queued and no lease taken. Session B ends cleanly. Nothing
    in B's flush reads A's queue, so A's edit waits for a drain that nothing will spawn -- and the
    sweep deletes it at 24 h. A drain that enumerates `*.pending.jsonl` is the fix, and it belongs
    to `ow ingest`, not to this handler.
    """
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, OTHER, at_ns=now)
    spawn = Spawns()

    tier = flush(root, KEY, now_ns=now, pid=1, spawn=spawn)

    assert tier == "quiet"
    assert spawn.calls == []
    assert queued(root, OTHER, now_ns=now) == 1


# ---------------------------------------------------------------------------------------------
# The handler: journal, flush, prune -- in that order.
# ---------------------------------------------------------------------------------------------


def test_the_end_is_journalled_with_its_reason(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()

    run_sessionend({**SESSION, "reason": "logout"}, root=root, key=KEY, now_ns=now, pid=1)

    records = read(root, KEY, now_ns=now).records
    assert [(r["kind"], r["reason"]) for r in records] == [(ENDED, "logout")]


def test_the_end_record_never_enters_the_queue(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()

    advice = run_sessionend(SESSION, root=root, key=KEY, now_ns=now, pid=1, spawn=Spawns())

    assert advice.counter == "quiet"
    assert not journal_paths(root, queue_key(KEY))[0].exists()


def test_a_session_with_queued_edits_is_flushed_on_the_way_out(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now, count=2)
    spawn = Spawns()

    advice = run_sessionend(SESSION, root=root, key=KEY, now_ns=now, pid=1, spawn=spawn)

    assert advice.counter == "flushed"
    assert len(spawn.calls) == 1


def test_an_edit_then_an_end_inside_one_ttl_spawns_one_drain_and_not_two(tmp_path: Path) -> None:
    """10:2060's one-drain-per-burst holds across the two events that can spawn."""
    root = _store(tmp_path)
    now = _now()
    spawn = Spawns()

    run_posttool(EDIT, root=root, key=KEY, now_ns=now, pid=1, spawn=spawn)
    advice = run_sessionend(SESSION, root=root, key=KEY, now_ns=now, pid=2, spawn=spawn)

    assert advice.counter == "noop-lease-held"
    assert len(spawn.calls) == 1


def test_the_prune_removes_another_sessions_day_old_files(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    append(root, OTHER, {"kind": "corpus"}, at_ns=now)
    stale, _ = journal_paths(root, OTHER)
    _age(stale, days=2)

    run_sessionend(SESSION, root=root, key=KEY, now_ns=now, pid=1)

    assert not stale.exists()


def test_the_prune_keeps_this_sessions_own_files_however_old(tmp_path: Path) -> None:
    """D429 made structural: the queue the drain is reading and the journal `resume` will read."""
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)
    queue, _ = journal_paths(root, queue_key(KEY))
    _age(queue, days=2)
    spawn = Spawns()

    advice = run_sessionend(SESSION, root=root, key=KEY, now_ns=now, pid=1, spawn=spawn)

    assert advice.counter == "flushed"
    assert queue.exists()


def test_no_session_identity_still_prunes(tmp_path: Path) -> None:
    """10:1917: pruning must not depend on this event -- nor, therefore, on a `session_id`."""
    root = _store(tmp_path)
    now = _now()
    append(root, OTHER, {"kind": "corpus"}, at_ns=now)
    stale, _ = journal_paths(root, OTHER)
    _age(stale, days=2)

    advice = run_sessionend({}, root=root, key="", now_ns=now, pid=1)

    assert advice.counter == "noop-no-key"
    assert not stale.exists()
    assert sorted(path.name for path in root.iterdir()) == []


def test_swept_false_leaves_old_files_alone(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    append(root, OTHER, {"kind": "corpus"}, at_ns=now)
    stale, _ = journal_paths(root, OTHER)
    _age(stale, days=2)

    run_sessionend(SESSION, root=root, key=KEY, now_ns=now, pid=1, swept=False)

    assert stale.exists()


def test_no_sessions_directory_is_a_quiet_exit(tmp_path: Path) -> None:
    advice = run_sessionend(SESSION, root=None, key=KEY, now_ns=_now(), pid=1)

    assert advice.counter == "noop-no-key"
    assert list(tmp_path.iterdir()) == []


def test_a_session_end_leaves_the_journal_resume_exists_to_read(tmp_path: Path) -> None:
    """D429. `SessionEnd` fires at exit; `SessionStart(source=resume)` fires when the user returns.

    A handler that read *"prunes on the way out"* as *cleans up after itself* would pass every other
    test in this file and make this briefing empty -- which is the normal state of a new session,
    so nothing would look wrong.
    """
    root = _store(tmp_path)
    now = _now()
    for index, record in enumerate(
        (
            {"kind": "corpus", "corpus": "handbook", "version": 41, "stale": 0},
            {"kind": "cite", "corpus": "handbook", "ref": "d7#412"},
        )
    ):
        append(root, KEY, record, at_ns=now - 1, seq=index)

    run_sessionend({**SESSION, "reason": "logout"}, root=root, key=KEY, now_ns=now, pid=1)
    advice = run_sessionstart(
        {**SESSION, "source": "resume"},
        root=root,
        wall_ns=_now(),
        verify=frozenset,
    )

    assert "restored on resume" in advice.text
    assert "d7#412" in advice.text


def test_the_bound_handler_derives_the_key_from_the_payload(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)
    spawn = Spawns()

    bound = handler(root, key_of=session_key, now_ns=_now, pid=3, spawn=spawn)

    assert bound(SESSION).counter == "flushed"
    assert bound({}).counter == "noop-no-key"


# ---------------------------------------------------------------------------------------------
# It says nothing.
# ---------------------------------------------------------------------------------------------


def test_the_event_has_no_channel_whatever_it_is_handed() -> None:
    assert EVENTS["SessionEnd"].cap == 0
    assert emission("SessionEnd", Advice(text="goodbye")) == ""
    assert emission("SessionEnd", Advice(text="no", deny=True)) == ""


def test_under_the_envelope_it_is_a_counter_and_an_exit_zero(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()
    _enqueue(root, KEY, at_ns=now)

    outcome = run(
        "SessionEnd",
        SESSION,
        handler(root, key_of=session_key, now_ns=_now, pid=1, spawn=Spawns()),
        clock=_Clock(now),
        env={},
    )

    assert outcome.stdout == ""
    assert outcome.counters == ("ow-hook-end-flushed",)
    assert outcome.exit_code() == 0
    assert outcome.after_emit is None


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_module_imports_no_subprocess_and_no_core() -> None:
    import ast  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    import omniweave.hooks.sessionend as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) if node.module}

    assert "subprocess" not in names
    assert not [name for name in names if name.startswith("omniweave_core")]


def test_there_is_one_lease_implementation_and_this_module_borrows_it() -> None:
    import omniweave.hooks.sessionend as module  # noqa: PLC0415

    assert module.break_lease is posttool.break_lease
    assert module.take_lease is posttool.take_lease
    assert module.release_lease is posttool.release_lease
    assert module.command is posttool.command


def test_the_unflushed_list_names_the_five_readings_this_handler_runs_against() -> None:
    stated = unflushed()

    assert len(stated) == 5
    for entry in ("D426", "D427", "D428", "D429", "D423"):
        assert any(entry in item for item in stated), entry
