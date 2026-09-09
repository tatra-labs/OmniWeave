"""`store/walvalve.py` -- the baseline transform, the barrier, the latch, `fold_now`.

Specified by 07-store-and-retrieval.md section 10.5 (:2796-2846). The four subtleties there are
"each a rule and not a detail", and each has its own block of tests below.

**The load-bearing test in this file is `test_the_valve_fires_once_over_a_checkpointed_wal`.** It
feeds the valve a WAL size sequence that rises, gets checkpointed with the FILE SIZE UNCHANGED --
which is how a real WAL behaves, because "a WAL file's size never shrinks" (07:2808) -- and then
rises again, and asserts the valve fires ONCE. Its companion,
`test_a_size_triggered_valve_would_have_fired_on_every_observation`, computes what a plain threshold
would have done on the identical sequence, which is what makes the first test able to fail: a test
that only fed a rising sequence cannot tell the transform from a plain threshold, and the plan
measured the difference at **~9 min per 160 files** (07:2811).

`import sqlite3` is here for two tests only -- that `PRAGMA wal_checkpoint` really returns the three
columns `CheckpointResult` names, and that the sidecar a real WAL creates is `<db>-wal` and not
`<stem>-wal`. Both are claims about SQLite that no amount of reading source can settle, and the
second one is a bug this file caught. INV-17's ruff half carries no `per-file-ignores` row for
tests, so the `noqa` is the narrowest form of the exemption; `tests/unit/test_migration_0001.py` is
the house form.
"""

from __future__ import annotations

import contextlib
import inspect
import re
import sqlite3  # noqa: TID251
from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import StoreError
from omniweave_core.store import walvalve as w

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator
    from pathlib import Path

    from conftest import PlanDocs

STORE_DOC = "07-store-and-retrieval.md"
MB = w.BYTES_PER_MB
SOFT = w.Thresholds.of(soft_mb=w.DEFAULT_WAL_VALVE_MB)


class Checkpointer:
    """A fake `PRAGMA wal_checkpoint`, recording every mode it was asked for.

    `folds` decides whether each call reports `log == checkpointed`. A list is used rather than a
    flag so a test can script "the first three passes do nothing, the fourth folds", which is
    subtlety 2's shape.
    """

    def __init__(self, *, folds: bool = True, script: list[bool] | None = None) -> None:
        self.modes: list[w.CheckpointMode] = []
        self._folds = folds
        self._script = script

    def __call__(self, mode: w.CheckpointMode) -> w.CheckpointResult:
        self.modes.append(mode)
        if self._script is not None:
            folds = self._script.pop(0) if self._script else False
        else:
            folds = self._folds
        return w.CheckpointResult(mode=mode, busy=0, log=100, checkpointed=100 if folds else 7)

    @property
    def calls(self) -> int:
        return len(self.modes)


@contextlib.contextmanager
def _recording_park(log: list[str]) -> Iterator[None]:
    log.append("parked")
    try:
        yield
    finally:
        log.append("released")


# ---------------------------------------------------------------------------
# The constants are the ones the plan prints.
# ---------------------------------------------------------------------------

PRINTED = {
    "DEFAULT_WAL_VALVE_MB": w.DEFAULT_WAL_VALVE_MB,
    "HARD_CAP_MULTIPLIER": w.HARD_CAP_MULTIPLIER,
    "FILE_CAP_MULTIPLIER": w.FILE_CAP_MULTIPLIER,
    "MAX_PAUSED_BACKFILL_PASSES": w.MAX_PAUSED_BACKFILL_PASSES,
    "CHECK_INTERVAL_MS": w.CHECK_INTERVAL_MS,
}


def test_every_constant_matches_the_python_fence_the_plan_prints(plan: PlanDocs) -> None:
    """07:2800-2807 is a ```python fence; the five assignments in it are read, not retyped."""
    plan.require()
    fences = [f for f in plan.fences(STORE_DOC, "python") if "DEFAULT_WAL_VALVE_MB" in f]
    assert len(fences) == 1, "07 section 10.5's constants fence moved or was duplicated"
    printed = dict(re.findall(r"^(\w+)\s*=\s*(\d+)", fences[0], flags=re.MULTILINE))
    assert set(printed) == set(PRINTED), sorted(set(printed) ^ set(PRINTED))
    for name, value in PRINTED.items():
        assert int(printed[name]) == value, name


def test_the_two_config_comments_are_the_ones_the_fence_carries(plan: PlanDocs) -> None:
    plan.require()
    text = plan.text(STORE_DOC)
    assert "wal_valve_mb = 0  =>  clamp(db_bytes / 4, 256 MB, 2 GB)".replace("=>", "⇒") in text
    assert "wal_heal_mb  = 64 ⇒  heal an oversized WAL at every open" in text
    assert w.DEFAULT_WAL_HEAL_MB == 64
    assert w.VALVE_MB_CEILING == 2048
    assert w.PROPORTIONAL_DIVISOR == 4


def test_the_futility_latch_numbers_are_the_ones_two_documents_agree_on(plan: PlanDocs) -> None:
    """07:2838 and 08-runtime.md:2440 both print "2 ... give-ups" and "60 s"."""
    plan.require()
    assert plan.grep(r"Two give-ups .{0,4} 60 s cooldown", documents=(STORE_DOC,))
    assert plan.grep(r"2 consecutive give-ups", documents=("08-runtime.md",))
    assert w.FUTILITY_GIVE_UPS == 2
    assert w.FUTILITY_COOLDOWN_MS == 60_000


def test_the_module_reads_no_ambient_clock_and_starts_no_thread() -> None:
    """A governor that read its own clock could not be tested for a 60 s cooldown without one."""
    body = inspect.getsource(w).split('"""', 2)[2]
    for banned in ("import time", "import asyncio", "import threading", "sqlite3.connect"):
        assert banned not in body, banned


# ---------------------------------------------------------------------------
# Subtlety 1 -- the baseline transform. The whole point of the valve.
# ---------------------------------------------------------------------------

RISE_CHECKPOINT_RISE = (100, 300, 300, 320, 400, 500)
"""MB observations: below soft, past soft, **checkpointed with the file unchanged**, then rising.

The third entry repeats the second on purpose. That is what a real WAL does: a checkpoint folds the
frames back into the database and the writer recycles them inside the same file, so the size a
governor can observe does not move (07:2808-2810). Every later entry is above the soft threshold in
absolute terms and inside it in growth terms.
"""


def test_the_valve_fires_once_over_a_checkpointed_wal() -> None:
    """Subtlety 1 (07:2808-2814): the trigger is GROWTH beyond a refreshed baseline."""
    checkpointer = Checkpointer(folds=True)
    valve = w.WalValve(thresholds=SOFT, checkpointer=checkpointer)
    actions = [
        valve.pump(wal_file_bytes=size * MB, now_ms=tick * w.CHECK_INTERVAL_MS).action
        for tick, size in enumerate(RISE_CHECKPOINT_RISE)
    ]
    assert actions.count(w.ValveAction.PASSIVE) == 1, actions
    assert actions[1] is w.ValveAction.PASSIVE
    assert all(a is w.ValveAction.NONE for a in actions[2:]), actions
    assert checkpointer.calls == 1
    assert valve.baseline.baseline == 300 * MB


def test_a_size_triggered_valve_would_have_fired_on_every_observation() -> None:
    """The contrast that makes the test above able to fail.

    Without the transform the valve is a plain threshold on a monotone observable, and 07:2811
    measured what that costs: ~9 min per 160 files. Five of the six observations are past the soft
    threshold in absolute terms; exactly one of them is past it in growth terms.
    """
    naive = sum(size * MB > SOFT.soft_bytes for size in RISE_CHECKPOINT_RISE)
    assert naive == 5, "the fixture no longer distinguishes the transform from a threshold"


def test_the_baseline_refreshes_only_on_log_equals_checkpointed() -> None:
    """07:2812 -- "refreshed whenever a checkpoint reports `log == checkpointed`"."""
    valve = w.WalValve(thresholds=SOFT, checkpointer=Checkpointer(folds=False))
    valve.pump(wal_file_bytes=300 * MB, now_ms=0)
    assert valve.baseline.baseline == 0, "a partial fold is not a proof of reclamation"
    folding = w.WalValve(thresholds=SOFT, checkpointer=Checkpointer(folds=True))
    folding.pump(wal_file_bytes=300 * MB, now_ms=0)
    assert folding.baseline.baseline == 300 * MB


def test_a_checkpoint_that_could_not_start_is_not_a_fold() -> None:
    """SQLite answers `(1, -1, -1)` outside WAL mode, and `-1 == -1` must not read as a fold."""
    stalled = w.CheckpointResult(mode=w.CheckpointMode.PASSIVE, busy=1, log=-1, checkpointed=-1)
    assert stalled.folded is False
    assert (
        w.CheckpointResult(mode=w.CheckpointMode.PASSIVE, busy=0, log=0, checkpointed=0).folded
        is True
    )


@pytest.mark.parametrize(
    ("baseline", "observed", "expected"),
    [(0, 0, 0), (0, 100, 100), (100, 100, 0), (100, 40, 0), (100, 250, 150)],
)
def test_growth_is_the_distance_above_the_baseline_and_never_negative(
    baseline: int, observed: int, expected: int
) -> None:
    assert w.MonotoneBaseline(baseline=baseline).growth(observed) == expected


def test_the_baseline_follows_the_observable_down_after_a_reset() -> None:
    """A TRUNCATE resets the file; a baseline left above the new floor under-reports forever."""
    high = w.MonotoneBaseline(baseline=1000)
    assert high.followed(10).baseline == 10
    assert high.followed(2000).baseline == 1000, "growth is not a reset"
    assert high.reclaimed(2000).baseline == 2000


def test_a_truncated_wal_starts_measuring_growth_from_the_new_floor() -> None:
    checkpointer = Checkpointer(folds=True)
    valve = w.WalValve(
        thresholds=SOFT, checkpointer=checkpointer, baseline=w.MonotoneBaseline(baseline=900 * MB)
    )
    valve.pump(wal_file_bytes=1 * MB, now_ms=0)
    assert valve.baseline.baseline == 1 * MB
    assert valve.pump(wal_file_bytes=300 * MB, now_ms=2000).action is w.ValveAction.PASSIVE


def test_the_transform_names_the_three_other_places_the_plan_points_at() -> None:
    """07:2812-2813 generalises the transform, and the docstring has to carry the generalisation."""
    doc = w.__doc__ or ""
    assert "index size vs live blocks" in doc
    assert "CAS size vs live entries" in doc
    assert "`work` rows vs pending" in doc


# ---------------------------------------------------------------------------
# The thresholds and the pure decision.
# ---------------------------------------------------------------------------


def test_the_three_thresholds_are_exact_multiples_of_the_soft_one() -> None:
    assert SOFT.soft_bytes == w.DEFAULT_WAL_VALVE_MB * MB
    assert SOFT.hard_bytes == SOFT.soft_bytes * w.HARD_CAP_MULTIPLIER
    assert SOFT.file_bytes == SOFT.soft_bytes * w.FILE_CAP_MULTIPLIER


@pytest.mark.parametrize(
    ("db_mb", "configured", "expected"),
    [(10, 0, 256), (4096, 0, 1024), (40_000, 0, 2048), (40_000, 300, 300), (10, 64, 64)],
)
def test_soft_valve_mb_clamps_a_quarter_of_the_database_between_256_and_2048(
    db_mb: int, configured: int, expected: int
) -> None:
    """07:2806 -- `wal_valve_mb = 0` means `clamp(db_bytes / 4, 256 MB, 2 GB)`."""
    assert w.soft_valve_mb(db_mb * MB, configured) == expected


def test_thresholds_for_store_uses_the_clamp() -> None:
    assert w.Thresholds.for_store(db_bytes=40_000 * MB).soft_bytes == 2048 * MB
    assert w.Thresholds.for_store(db_bytes=40_000 * MB, configured_mb=256).soft_bytes == 256 * MB


@pytest.mark.parametrize(
    ("growth_mb", "file_mb", "expected"),
    [
        (0, 0, w.ValveAction.NONE),
        (256, 256, w.ValveAction.NONE),
        (257, 257, w.ValveAction.PASSIVE),
        (512, 512, w.ValveAction.PASSIVE),
        (513, 513, w.ValveAction.PAUSE),
        (513, 1024, w.ValveAction.PAUSE),
        (0, 1025, w.ValveAction.PAUSE_AND_TRUNCATE),
        (2000, 1025, w.ValveAction.PAUSE_AND_TRUNCATE),
    ],
)
def test_decide_is_the_three_thresholds_and_nothing_else(
    growth_mb: int, file_mb: int, expected: w.ValveAction
) -> None:
    """Each threshold is strictly greater, and the file cap reads the RAW size (subtlety 1)."""
    assert (
        w.decide(growth_bytes=growth_mb * MB, file_bytes=file_mb * MB, thresholds=SOFT) is expected
    )


def test_the_file_cap_fires_on_a_huge_file_with_no_growth_at_all() -> None:
    """The one threshold allowed to read the monotone observable, because its remedy shrinks it."""
    assert (
        w.decide(growth_bytes=0, file_bytes=SOFT.file_bytes + 1, thresholds=SOFT)
        is w.ValveAction.PAUSE_AND_TRUNCATE
    )


# ---------------------------------------------------------------------------
# Subtlety 2 -- the pause is the terminal mode, and one pass is not enough.
# ---------------------------------------------------------------------------


def test_a_soft_pass_that_does_not_fold_is_not_a_give_up() -> None:
    """07:2815-2816 -- every concurrent PASSIVE pass is stale by the time it finishes."""
    valve = w.WalValve(thresholds=SOFT, checkpointer=Checkpointer(folds=False))
    outcome = valve.pump(wal_file_bytes=300 * MB, now_ms=0)
    assert outcome.action is w.ValveAction.PASSIVE
    assert outcome.passes == 1
    assert outcome.folded is False
    assert outcome.gave_up is False
    assert valve.latch.consecutive_give_ups == 0


def test_the_paused_backfill_is_bounded_by_max_paused_backfill_passes() -> None:
    parked: list[str] = []
    checkpointer = Checkpointer(folds=False)
    valve = w.WalValve(
        thresholds=SOFT,
        checkpointer=checkpointer,
        park=lambda: _recording_park(parked),
    )
    outcome = valve.pump(wal_file_bytes=600 * MB, now_ms=0)
    assert outcome.action is w.ValveAction.PAUSE
    assert outcome.passes == w.MAX_PAUSED_BACKFILL_PASSES
    assert outcome.gave_up is True
    assert parked == ["parked", "released"]
    assert checkpointer.modes == [w.CheckpointMode.PASSIVE] * w.MAX_PAUSED_BACKFILL_PASSES


def test_a_paused_pass_that_folds_stops_early() -> None:
    """ "With the writer parked the next pass covers everything" (07:2816-2817)."""
    parked: list[str] = []
    checkpointer = Checkpointer(script=[False, False, True])
    valve = w.WalValve(
        thresholds=SOFT, checkpointer=checkpointer, park=lambda: _recording_park(parked)
    )
    outcome = valve.pump(wal_file_bytes=600 * MB, now_ms=0)
    assert outcome.passes == 3
    assert outcome.folded is True
    assert outcome.gave_up is False


# ---------------------------------------------------------------------------
# Subtlety 3 -- TRUNCATE only at a parked barrier.
# ---------------------------------------------------------------------------


def test_the_truncate_happens_inside_the_barrier_and_only_there() -> None:
    """07:2819-2822 -- an unparked chop wins the lock race and then fails the writer."""
    order: list[str] = []
    checkpointer = Checkpointer(folds=True)

    @contextlib.contextmanager
    def park() -> Iterator[None]:
        order.append("parked")
        try:
            yield
        finally:
            order.append("released")

    def recording(mode: w.CheckpointMode) -> w.CheckpointResult:
        order.append(mode.value)
        return checkpointer(mode)

    valve = w.WalValve(thresholds=SOFT, checkpointer=recording, park=park)
    outcome = valve.pump(wal_file_bytes=(SOFT.file_bytes // MB + 1) * MB, now_ms=0)
    assert outcome.action is w.ValveAction.PAUSE_AND_TRUNCATE
    assert outcome.truncated is True
    assert order[0] == "parked"
    assert order[-1] == "released"
    assert order.index("TRUNCATE") < order.index("released")


def test_without_a_barrier_the_chop_is_skipped_and_the_tick_is_a_give_up() -> None:
    lines: list[str] = []
    checkpointer = Checkpointer(folds=True)
    valve = w.WalValve(thresholds=SOFT, checkpointer=checkpointer, log=lines.append)
    outcome = valve.pump(wal_file_bytes=5000 * MB, now_ms=0)
    assert outcome.action is w.ValveAction.PAUSE_AND_TRUNCATE
    assert outcome.truncated is False
    assert outcome.gave_up is True
    assert checkpointer.modes == [], "no checkpoint at all without a barrier"
    assert any("park barrier" in line for line in lines)


def test_checkpoint_at_barrier_refuses_without_a_park() -> None:
    valve = w.WalValve(thresholds=SOFT, checkpointer=Checkpointer())
    with pytest.raises(StoreError, match="park barrier"):
        valve.checkpoint_at_barrier(wal_file_bytes=1)


def test_checkpoint_at_barrier_truncates_inside_the_park() -> None:
    parked: list[str] = []
    checkpointer = Checkpointer(folds=True)
    valve = w.WalValve(
        thresholds=SOFT, checkpointer=checkpointer, park=lambda: _recording_park(parked)
    )
    result = valve.checkpoint_at_barrier(wal_file_bytes=999)
    assert result.mode is w.CheckpointMode.TRUNCATE
    assert parked == ["parked", "released"]
    assert valve.baseline.baseline == 999


# ---------------------------------------------------------------------------
# Subtlety 4 -- the futility latch.
# ---------------------------------------------------------------------------


def _giving_up_valve(log: list[str], beats: list[int]) -> w.WalValve:
    """A valve with no barrier, so every hard-or-file tick is a give-up (subtlety 3)."""
    return w.WalValve(
        thresholds=SOFT,
        checkpointer=Checkpointer(folds=False),
        log=log.append,
        heartbeat=lambda: beats.append(1),
    )


def test_two_give_ups_arm_the_cooldown_and_the_third_call_degrades() -> None:
    """07:2838 / 08-runtime.md:2440 -- and the third call must not retry."""
    lines: list[str] = []
    beats: list[int] = []
    valve = _giving_up_valve(lines, beats)
    first = valve.pump(wal_file_bytes=5000 * MB, now_ms=0)
    second = valve.pump(wal_file_bytes=5000 * MB, now_ms=2000)
    third = valve.pump(wal_file_bytes=5000 * MB, now_ms=4000)
    assert (first.gave_up, second.gave_up) == (True, True)
    assert valve.latch.consecutive_give_ups == w.FUTILITY_GIVE_UPS
    assert third.action is w.ValveAction.DEGRADED
    assert third.armed is True
    assert third.gave_up is False, "a degraded tick does not spend another give-up"
    assert beats == [1], "the heartbeat turns while the governor is out of the way"


def test_the_armed_log_line_is_emitted_once_and_names_the_cooldown() -> None:
    lines: list[str] = []
    beats: list[int] = []
    valve = _giving_up_valve(lines, beats)
    for tick in range(4):
        valve.pump(wal_file_bytes=5000 * MB, now_ms=tick * 2000)
    armed = [line for line in lines if line.startswith("wal valve: armed")]
    assert len(armed) == 1
    assert str(w.FUTILITY_COOLDOWN_MS) in armed[0]
    assert "ST16" in armed[0]


def test_no_checkpoint_is_issued_while_the_latch_is_armed() -> None:
    """ "Degrade to un-valved" means no IO at all, not a cheaper pass."""
    checkpointer = Checkpointer(folds=False)
    parked: list[str] = []
    valve = w.WalValve(
        thresholds=SOFT, checkpointer=checkpointer, park=lambda: _recording_park(parked)
    )
    valve.pump(wal_file_bytes=600 * MB, now_ms=0)
    valve.pump(wal_file_bytes=600 * MB, now_ms=2000)
    before = checkpointer.calls
    assert valve.pump(wal_file_bytes=600 * MB, now_ms=4000).action is w.ValveAction.DEGRADED
    assert checkpointer.calls == before


def test_the_cooldown_elapses_and_the_governor_re_arms() -> None:
    """08:2440 says "disable for 60 s", which is a window and not a death sentence."""
    lines: list[str] = []
    beats: list[int] = []
    valve = _giving_up_valve(lines, beats)
    valve.pump(wal_file_bytes=5000 * MB, now_ms=0)
    valve.pump(wal_file_bytes=5000 * MB, now_ms=2000)
    assert valve.pump(wal_file_bytes=5000 * MB, now_ms=2000).armed is True
    after = valve.pump(wal_file_bytes=5000 * MB, now_ms=2000 + w.FUTILITY_COOLDOWN_MS)
    assert after.armed is False
    assert after.action is w.ValveAction.PAUSE_AND_TRUNCATE
    assert valve.latch.consecutive_give_ups == 1, "the count restarts after a cooldown"


def test_give_ups_must_be_consecutive_to_arm_the_latch() -> None:
    """08:2440's word is "consecutive": a valve that gives up and then works is not futile."""
    latch = w.FutilityLatch()
    assert latch.gave_up(0) is False
    latch.folded()
    assert latch.gave_up(1000) is False, "the fold reset the count"
    assert latch.armed(1000) is False
    assert latch.gave_up(2000) is True


def test_a_fold_between_give_ups_keeps_the_valve_running() -> None:
    checkpointer = Checkpointer(script=[False] * w.MAX_PAUSED_BACKFILL_PASSES + [True])
    parked: list[str] = []
    valve = w.WalValve(
        thresholds=SOFT, checkpointer=checkpointer, park=lambda: _recording_park(parked)
    )
    assert valve.pump(wal_file_bytes=600 * MB, now_ms=0).gave_up is True
    assert valve.pump(wal_file_bytes=600 * MB, now_ms=2000).folded is True
    assert valve.latch.consecutive_give_ups == 0


# ---------------------------------------------------------------------------
# `fold_now` -- the fourth maintenance operation.
# ---------------------------------------------------------------------------


def test_fold_now_is_a_full_checkpoint_and_never_a_truncate() -> None:
    """07:2844 -- a phase boundary is idle, not provably parked; subtlety 3 keeps the chop out."""
    checkpointer = Checkpointer(folds=True)
    valve = w.WalValve(thresholds=SOFT, checkpointer=checkpointer)
    result = valve.fold_now(wal_file_bytes=42)
    assert result.mode is w.CheckpointMode.FULL
    assert checkpointer.modes == [w.CheckpointMode.FULL]
    assert valve.baseline.baseline == 42


def test_fold_now_goes_through_submit_and_awaits_it() -> None:
    """ "off-thread, awaited" (07:2844): the seam is `Submit`, and the await is `.result()`."""
    submitted: list[object] = []

    def submit(job):  # type: ignore[no-untyped-def]
        submitted.append(job)
        return w.run_inline(job)

    valve = w.WalValve(thresholds=SOFT, checkpointer=Checkpointer(), submit=submit)
    valve.fold_now(wal_file_bytes=1)
    assert len(submitted) == 1


def test_run_inline_returns_a_completed_future_and_propagates_a_raise() -> None:
    assert w.run_inline(lambda: 7).result() == 7
    failing = w.run_inline(lambda: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ValueError, match="boom"):
        failing.result()


def test_the_plan_spelling_of_fold_now_is_recorded() -> None:
    assert w.FOLD_NOW_PLAN_NAME == "foldNow"
    assert hasattr(w.WalValve, "fold_now")


# ---------------------------------------------------------------------------
# Heal on open.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_mb", "expected"), [(0, None), (64, None), (65, w.CheckpointMode.TRUNCATE)]
)
def test_heal_at_open_truncates_only_above_wal_heal_mb(
    file_mb: int, expected: w.CheckpointMode | None
) -> None:
    """07:2806 -- and 07:2820's **25.6 GB** of leaked WAL is why the knob exists at all."""
    checkpointer = Checkpointer(folds=True)
    result = heal = w.heal_at_open(file_bytes=file_mb * MB, checkpointer=checkpointer)
    assert (None if heal is None else result.mode) is expected
    assert checkpointer.modes == ([] if expected is None else [expected])


# ---------------------------------------------------------------------------
# The two claims about SQLite itself.
# ---------------------------------------------------------------------------


def _wal_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t(x BLOB)")
    conn.executemany("INSERT INTO t(x) VALUES(?)", [(b"a" * 4000,) for _ in range(400)])
    conn.commit()
    return conn


def test_wal_checkpoint_returns_the_three_columns_checkpoint_result_names(
    tmp_path: Path,
) -> None:
    path = tmp_path / "index.owstore"
    conn = _wal_db(path)
    try:
        result = w.checkpoint(conn, w.CheckpointMode.PASSIVE)
        assert result.mode is w.CheckpointMode.PASSIVE
        assert result.busy == 0
        assert result.log >= 0
        assert result.folded is True
    finally:
        conn.close()


def test_wal_file_bytes_names_the_dash_wal_sidecar(tmp_path: Path) -> None:
    """`index.owstore-wal`, not `index-wal`: a `with_suffix` here would report 0 forever."""
    path = tmp_path / "index.owstore"
    conn = _wal_db(path)
    try:
        assert (tmp_path / "index.owstore-wal").is_file()
        assert w.wal_file_bytes(path) > 0
        assert w.wal_file_bytes(tmp_path / "absent.owstore") == 0
    finally:
        conn.close()


def test_a_truncate_against_a_real_wal_shrinks_the_file_the_valve_observes(
    tmp_path: Path,
) -> None:
    """The file cap's remedy really does make its monotone observable go down."""
    path = tmp_path / "index.owstore"
    conn = _wal_db(path)
    try:
        before = w.wal_file_bytes(path)
        assert before > 0
        assert w.checkpoint(conn, w.CheckpointMode.TRUNCATE).folded is True
        assert w.wal_file_bytes(path) < before
    finally:
        conn.close()


def test_a_passive_checkpoint_leaves_the_file_exactly_as_large_as_it_found_it(
    tmp_path: Path,
) -> None:
    """Subtlety 1's premise, measured rather than quoted: this is why soft reads GROWTH."""
    path = tmp_path / "index.owstore"
    conn = _wal_db(path)
    try:
        before = w.wal_file_bytes(path)
        assert w.checkpoint(conn, w.CheckpointMode.PASSIVE).folded is True
        assert w.wal_file_bytes(path) == before
    finally:
        conn.close()
