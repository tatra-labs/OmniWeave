"""The WAL valve: the baseline transform, the parked-barrier chop, the futility latch, `fold_now`.

Implements 07-store-and-retrieval.md section 10.5 (:2796-2846), which the plan says is *"ported
whole from codegraph, with all eight properties and its verified constants"*. Every constant below
is transcribed from the printed block at 07:2801-2806; every rule below is one of the four
subtleties at 07:2808-2842, each of which the plan calls *"a rule and not a detail"*.

**Why a valve exists at all, in codegraph's measured numbers** (07:2810-2820, reproduced because a
governor whose cost nobody remembers gets deleted): default autocheckpointing was **~95% of all
disk I/O** during a bulk index; a bulk index on 150-IOPS storage went from **19+ min to 45 s** when
deferred; unbounded deferral produced a **5.9 GB WAL against a ~340 MB database**; the first
post-parse read against a multi-GB WAL was a **>60 s main-thread block** ending in a watchdog
SIGKILL; the worst WAL observed under a pinned reader *with the valve running* was **22 GB, then
exit 137**; and the worst leaked WAL across repeatedly-killed sessions with no heal-on-open was
**25.6 GB**.

## Subtlety 1, and it is the whole point: the trigger cannot be WAL FILE SIZE

07:2808-2814, quoted because the sentence is the specification:

> A WAL file's size never shrinks; after a full backfill the writer's next commit restarts the WAL
> from the top and recycles frames inside the same file, so a size-triggered valve fires forever
> once the file passes its threshold -- measured at ~9 min per 160 files. The valve tracks
> `wal_baseline_bytes`, refreshed whenever a checkpoint reports `log == checkpointed`, and triggers
> on **growth beyond that baseline**.

`MonotoneBaseline` is that transform, **named and reusable rather than an inline subtraction**,
because the plan immediately generalises it: *"Any governor built on a monotone-non-decreasing
observable needs this transform; omniweave has the same shape in three more places -- index size vs
live blocks, CAS size vs live entries, `work` rows vs pending."* Those are the three, and each is
another wave's:

1. **index size vs live blocks** -- `ow store stats`' `page_count` / `freelist_count` pair (07:211).
   The file never shrinks on its own under `auto_vacuum = INCREMENTAL`, so "the index is too big" is
   a claim about growth past what the live blocks justify, not about bytes.
2. **CAS size vs live entries** -- `blobs.sweep(live=...)`. A CAS directory's size is monotone until
   a sweep runs, so the sweep trigger is growth past the last swept baseline.
3. **`work` rows vs pending** -- the queue table grows with every unit ever run
   (`work_done` is "the compaction archive", `0004_runtime.sql:143`), so queue pressure is pending
   rows against a baseline, never `count(*)`.

**The file cap is the one threshold that may read the raw size, and subtlety 1 is why it is
allowed to.** `FILE_CAP_MULTIPLIER` fires on `wal_file_bytes` itself, not on growth -- and that is
sound precisely because its action is a TRUNCATE, which *removes the condition it fired on*. A
governor may read a monotone observable directly exactly when its remedy makes the observable go
down; soft and hard read growth because a PASSIVE checkpoint leaves the file exactly as large as it
found it.

## Subtlety 2: one in-flight pass is not enough, and the pause is not a failure

07:2815-2818. Every concurrent PASSIVE pass is stale by the time it finishes; with the writer
parked the next pass covers everything and the WAL wraps on the following commit. **The pause is
the disk's honest catch-up cost, and it is the correct terminal mode rather than a failure** --
which is why `ValveAction.PAUSE` is an outcome this module reports with no error attached, and why
`MAX_PAUSED_BACKFILL_PASSES = 20` bounds the passes rather than the wall time.

## Subtlety 3: TRUNCATE only at a parked barrier

07:2819-2822: *"A truncate checkpoint against an active writer wins the lock race and then blocks
that writer for its whole backfill -- past the writer's 5 s `busy_timeout`, failing the index with
'database is locked'. The chop happens only where the writer is provably parked, awaiting the
promise the valve returns."* The 5 s is `CONN_PRAGMAS`' `busy_timeout = 5000` (07:169), so the
failure is not hypothetical arithmetic: a truncate whose backfill exceeds five seconds fails the
writer.

"Provably parked" is made a seam: `WalValve` takes a `park` barrier, every TRUNCATE below runs
inside it, and `checkpoint_at_barrier()` REFUSES without one. A valve constructed with no barrier
therefore **skips the chop and records a give-up**, naming subtlety 3 -- it does not chop hopefully,
and the give-up is what feeds the futility latch.

## Subtlety 4: the futility latch

07:2838-2842 and 08-runtime.md section 8.4: **two consecutive give-ups arm a 60 s cooldown, during
which the valve degrades to un-valved, with an `armed` log line and a heartbeat** (ST16, I9). The
reason is not conservatism, it is a measurement: *"the mitigation made things strictly worse than
no mitigation -- a worker thread and a fresh connection per pass at every boundary turned a pinned
resolution phase from slow into OOM-killed, at an envelope the pre-valve build survived."*
I9 states the invariant in general: *"a repair or governor loop cannot make things worse than not
running"* (08:2634).

Two details of the latch that are decisions, not obvious readings:

* **Consecutive.** 08:2440 writes "2 **consecutive** give-ups", so any pass that folds resets the
  count. A valve that gave up once an hour is working, not futile.
* **The third call degrades, it does not retry.** While `armed(now_ms)` is true `pump()` performs no
  checkpoint at all, calls `heartbeat()` so the watchdog keeps turning, and returns
  `ValveAction.DEGRADED`. After the cooldown elapses it re-arms itself for another attempt: 08:2440
  says "disable for 60 s", which is a window and not a death sentence.

## `fold_now()` -- the phase-boundary fold, the fourth maintenance operation

07:2844-2846: *"`foldNow()` backfills the whole WAL off-thread, awaited, between bulk phases --
after parsing, before the first resolution read."* 07:212 is its row in the maintenance table, and
its bound is **phase boundaries only**, "so the next phase never pages a bulk-write-sized WAL on
the main thread".

**Off-thread is the caller's thread pool, not this module's.** 07:203-205 gives the runtime the
window and this document the operations, and INV-3 keeps a loop out of core, so `submit` is a
`Callable` the runtime supplies -- `ThreadPoolExecutor.submit` in the runtime, `run_inline` here,
which returns an already-completed `concurrent.futures.Future`. `fold_now()` calls `.result()` on
whatever comes back, which is the "awaited" half. The spelling is `fold_now`, not the plan's
`foldNow`: the plan's identifier is transcribed from codegraph's TypeScript and every Python
identifier in this repository is snake_case; `FOLD_NOW_PLAN_NAME` records the original.

**It folds with FULL and not TRUNCATE.** A phase boundary is a point where the writer happens to
be idle, not a point where it is *provably parked*, and subtlety 3 restricts the chop to the
latter. `checkpoint_at_barrier()` is the entry point for a caller that can prove the park.

## Where a number lives

The seven constants come from 07:2801-2806 and 07:2806's two config comments, their only definition
site. They are **not** in `omniweave_core.limits`, which holds "every `MAX_*` ceiling in the
framework, the one `MIN_SQLITE` floor" -- ceilings a tenant clamps DOWN. That includes
`MAX_PAUSED_BACKFILL_PASSES`, whose `MAX_` spelling makes it look like a `limits.py` name and which
is nonetheless absent from charter section 6.10's list of named maxima and from `limits.py`'s
`__all__`: it is a loop bound inside one governor, not a declared framework ceiling, and a copy in
`limits.py` would be INV-21's second home for one fact. Recorded as a finding rather than acted on;
if `limits.py`'s owner adopts it, this module must RE-EXPORT and never re-declare.

`[store] wal_valve_mb` and `[store] wal_heal_mb` are real config keys (`config.py:720-721`), and
`soft_valve_mb()` implements `wal_valve_mb = 0 => clamp(db_bytes / 4, 256 MB, 2 GB)` -- 07:2806 and
08:2441's "proportional thresholds" row, whose reason is that *"a flat resource threshold is wrong
at both ends: 256 MB cost 111 s of folding on a kernel-scale index"*.

## No ambient anything

`pump()`, `heal_at_open()` and the latch all take `now_ms` from the caller: `time.time`,
`datetime.now` and `time.perf_counter` are banned in library code (02-architecture.md:392,
`tools/gate_semgrep.py`) and a governor that read its own clock could not be tested for a 60 s
cooldown without sleeping 60 s. No `asyncio` (INV-3), no threads, no `sqlite3.connect` -- the
connection and the executor both arrive as arguments.

Stdlib only (INV-2 / G1). `import sqlite3` is legal here and needs no `noqa`: ruff's TID251
per-file-ignore covers `store/*.py`. Inside one of the nine LAZY subpackages, so
`import omniweave_core` must not reach it -- G17.

Tier T-INTERNAL. 07 section 10.5 is the specification.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, TypeVar

from omniweave_core.errors import StoreError

__all__ = [
    "BYTES_PER_MB",
    "CHECK_INTERVAL_MS",
    "DEFAULT_WAL_HEAL_MB",
    "DEFAULT_WAL_VALVE_MB",
    "FILE_CAP_MULTIPLIER",
    "FOLD_NOW_PLAN_NAME",
    "FUTILITY_COOLDOWN_MS",
    "FUTILITY_GIVE_UPS",
    "HARD_CAP_MULTIPLIER",
    "MAX_PAUSED_BACKFILL_PASSES",
    "PROPORTIONAL_DIVISOR",
    "VALVE_MB_CEILING",
    "WAL_BASELINE_KEY",
    "CheckpointMode",
    "CheckpointResult",
    "FutilityLatch",
    "MonotoneBaseline",
    "Thresholds",
    "ValveAction",
    "ValveOutcome",
    "WalValve",
    "checkpoint",
    "decide",
    "heal_at_open",
    "run_inline",
    "soft_valve_mb",
    "wal_file_bytes",
]

_T = TypeVar("_T")

Submit = Callable[[Callable[[], _T]], "Future[_T]"]
"""How this module reaches another thread: the runtime's `ThreadPoolExecutor.submit`, or nothing.

Typed as a plain callable rather than as `Executor` so a caller may pass a bare function, and so
this module imports no thread machinery of its own. `run_inline` is the identity implementation.
"""

Park = Callable[[], AbstractContextManager[None]]
"""A barrier that PROVES the writer is parked for the duration of the context (subtlety 3).

The valve never constructs one: parking a writer means holding whatever lock or queue gate the
runtime uses (`store.write`, 07:3115), and that is not a store-boundary concept.
"""


# ---------------------------------------------------------------------------
# The verified constants. 07-store-and-retrieval.md:2801-2806, their only definition site.
# ---------------------------------------------------------------------------

DEFAULT_WAL_VALVE_MB: Final = 256
"""Soft threshold: growth past this triggers an off-thread PASSIVE checkpoint (07:2801)."""

HARD_CAP_MULTIPLIER: Final = 2
"""Hard threshold: growth past 2x soft PAUSES the writer (07:2802). Subtlety 2's terminal mode."""

FILE_CAP_MULTIPLIER: Final = 4
"""File threshold: a WAL FILE past 4x soft pauses AND truncates (07:2803).

The one threshold read off the raw monotone observable, and legitimately so: its remedy is the
TRUNCATE, which is what makes the observable go down. See subtlety 1 in the module docstring.
"""

MAX_PAUSED_BACKFILL_PASSES: Final = 20
"""How many PASSIVE passes a paused barrier makes before giving up (07:2804).

codegraph's comment on the same constant is the reason: *"give up (a pinned reader could stall
forever)"* (`_plan/_notes/mine-graph.md:2366`). A pinned reader is not something a checkpoint can
fix, which is why exceeding this is a give-up feeding the futility latch and not an error.
"""

CHECK_INTERVAL_MS: Final = 2000
"""The timer cadence the runtime calls `pump()` on (07:2805). Transcribed, never read here.

This module has no timer: 07:203-205 gives the runtime the schedule. The constant lives here
because 07:2805 prints it inside the valve's own block, and the runtime imports it rather than
writing 2000 a second time.
"""

DEFAULT_WAL_HEAL_MB: Final = 64
"""`[store] wal_heal_mb = 64` -- "heal an oversized WAL at every open" (07:2806, `config.py:721`).

64 MB and not the soft threshold, because the failure it addresses is different: **25.6 GB** of WAL
leaked across repeatedly-SIGKILLed sessions with no heal-on-open (07:2820). At open there is no
writer to lose a lock race with, so this is the one TRUNCATE that needs no barrier of its own.
"""

VALVE_MB_CEILING: Final = 2048
"""The 2 GB ceiling of `clamp(db_bytes / 4, 256 MB, 2 GB)` (07:2806, 08-runtime.md:2441)."""

PROPORTIONAL_DIVISOR: Final = 4
"""The `/ 4` of `clamp(db_bytes / 4, ...)` (07:2806).

08:2441 gives the reason a proportional threshold is used at all: *"a flat resource threshold is
wrong at both ends: 256 MB cost 111 s of folding on a kernel-scale index."*
"""

BYTES_PER_MB: Final = 1 << 20
"""The unit the plan's `_MB` names are in. Binary, matching `wal.bulk_index_peak_bytes`'s GiB."""

FUTILITY_GIVE_UPS: Final = 2
"""Two CONSECUTIVE give-ups arm the latch (07:2838, 08-runtime.md:2440)."""

FUTILITY_COOLDOWN_MS: Final = 60_000
"""The 60 s cooldown the armed latch disables the valve for (07:2838, 08-runtime.md:2440)."""

WAL_BASELINE_KEY: Final = "wal_baseline_bytes"
"""`index_state.wal_baseline_bytes` -- 07:697 lists it among `index_state`'s eleven keys.

The valve keeps the baseline in memory and this key is where a caller PERSISTS it across opens.
Persisting is the caller's choice and not this module's: a fresh process's baseline of 0 makes the
first observation look like pure growth, which errs toward checkpointing and never away from it.
"""

FOLD_NOW_PLAN_NAME: Final = "foldNow"
"""The plan's own spelling of `fold_now` (07:212, 07:2844), kept so a grep for it lands here."""


# ---------------------------------------------------------------------------
# The transform. The reusable thing subtlety 1 asks for.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonotoneBaseline:
    """`growth = observed - baseline`, over an observable that never goes down on its own.

    **The transform every governor over a monotone-non-decreasing observable needs** (07:2812-2813).
    Three methods, and the reason each exists is a distinct failure:

    * `growth()` -- the number a threshold is compared against. Never negative: a governor that saw
      negative pressure would treat a reset as headroom it can spend.
    * `reclaimed()` -- move the baseline UP to the current observation, and only on a **proof** that
      the observable's backing store was reclaimed. For the WAL that proof is a checkpoint result
      with `log == checkpointed` (07:2812). Refreshing on anything weaker is how a size-triggered
      valve fires forever: the file stays large, so without this the growth term never falls
      back under the threshold and every tick re-triggers -- **~9 min per 160 files**, measured
      (07:2811).
    * `followed()` -- move the baseline DOWN when the observation itself fell below it. The
      observable is monotone *between resets*, and a TRUNCATE is a reset; a baseline left above the
      new floor would measure growth from a point that no longer exists and under-report forever,
      which is the mirror-image failure of the one above.

    Frozen, so a baseline is a value a caller can log, persist and compare rather than a mutable
    cell whose history is gone.
    """

    baseline: int = 0

    def growth(self, observed: int) -> int:
        """How far past the baseline the observation is. Zero, never negative."""
        return max(0, observed - self.baseline)

    def reclaimed(self, observed: int) -> MonotoneBaseline:
        """The baseline refreshed to `observed`, on proof that the backing store was reclaimed."""
        return MonotoneBaseline(baseline=observed)

    def followed(self, observed: int) -> MonotoneBaseline:
        """This baseline, lowered to `observed` when the observable was reset beneath it."""
        return self if observed >= self.baseline else MonotoneBaseline(baseline=observed)


# ---------------------------------------------------------------------------
# Thresholds and the decision. Pure, so the governor's algebra is testable without a database.
# ---------------------------------------------------------------------------


def soft_valve_mb(db_bytes: int, configured_mb: int = 0) -> int:
    """`[store] wal_valve_mb`, or `clamp(db_bytes / 4, 256 MB, 2 GB)` when it is 0 (07:2806).

    A configured value wins outright: 07:2806 makes 0 the sentinel for "derive it", so a tenant that
    names a number has named the number. The derived form exists because a flat threshold is wrong
    at both ends -- 08:2441 measured **111 s of folding** at a flat 256 MB on a kernel-scale index.
    """
    if configured_mb > 0:
        return configured_mb
    proportional = db_bytes // PROPORTIONAL_DIVISOR // BYTES_PER_MB
    return min(VALVE_MB_CEILING, max(DEFAULT_WAL_VALVE_MB, proportional))


@dataclass(frozen=True, slots=True)
class Thresholds:
    """The three thresholds of 07:2801-2803, in bytes, derived from one soft value.

    Derived rather than declared three times over: `HARD_CAP_MULTIPLIER` and `FILE_CAP_MULTIPLIER`
    are multipliers in the plan's own printing, so a hard cap that is not exactly twice the soft one
    is not a configuration, it is a bug.
    """

    soft_bytes: int
    hard_bytes: int
    file_bytes: int

    @classmethod
    def of(cls, *, soft_mb: int) -> Thresholds:
        """The three thresholds for a soft threshold in MB."""
        soft = soft_mb * BYTES_PER_MB
        return cls(
            soft_bytes=soft,
            hard_bytes=soft * HARD_CAP_MULTIPLIER,
            file_bytes=soft * FILE_CAP_MULTIPLIER,
        )

    @classmethod
    def for_store(cls, *, db_bytes: int, configured_mb: int = 0) -> Thresholds:
        """The thresholds for a store of `db_bytes`, honouring `[store] wal_valve_mb`."""
        return cls.of(soft_mb=soft_valve_mb(db_bytes, configured_mb))


class ValveAction(StrEnum):
    """What one `pump()` decided. Four actions and a degraded state; no other outcome exists."""

    NONE = "none"
    """Growth is under the soft threshold. The valve is a no-op, which is its normal state."""

    PASSIVE = "passive"
    """Growth past soft: one off-thread PASSIVE checkpoint (07:2801)."""

    PAUSE = "pause"
    """Growth past 2x soft: park the writer and backfill until the WAL wraps (07:2802).

    Not a failure. Subtlety 2: "the pause is the disk's honest catch-up cost, and it is the correct
    terminal mode rather than a failure" (07:2817-2818).
    """

    PAUSE_AND_TRUNCATE = "pause_and_truncate"
    """The WAL FILE is past 4x soft: pause, backfill, and chop the file (07:2803)."""

    DEGRADED = "degraded"
    """The futility latch is armed: no checkpoint at all, un-valved behaviour (07:2838, ST16)."""


def decide(*, growth_bytes: int, file_bytes: int, thresholds: Thresholds) -> ValveAction:
    """The governor's whole decision, as a pure function of two numbers and three thresholds.

    **The order of the tests is the order of severity**, and the file cap is first because it is the
    only condition whose remedy shrinks the file: a WAL past 4x soft has to be chopped whatever the
    growth term says, since growth is measured from a baseline that a huge file makes meaningless.

    Soft and hard read **growth**, never the file size -- subtlety 1, and the reason this module
    exists in the shape it does.
    """
    if file_bytes > thresholds.file_bytes:
        return ValveAction.PAUSE_AND_TRUNCATE
    if growth_bytes > thresholds.hard_bytes:
        return ValveAction.PAUSE
    if growth_bytes > thresholds.soft_bytes:
        return ValveAction.PASSIVE
    return ValveAction.NONE


# ---------------------------------------------------------------------------
# Talking to SQLite: the checkpoint pragma and the WAL sidecar's size.
# ---------------------------------------------------------------------------


class CheckpointMode(StrEnum):
    """The four `PRAGMA wal_checkpoint` modes. `TRUNCATE` is barrier-only (subtlety 3)."""

    PASSIVE = "PASSIVE"
    FULL = "FULL"
    RESTART = "RESTART"
    TRUNCATE = "TRUNCATE"


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    """`PRAGMA wal_checkpoint`'s three columns: `(busy, log, checkpointed)`."""

    mode: CheckpointMode
    busy: int
    log: int
    checkpointed: int

    @property
    def folded(self) -> bool:
        """`log == checkpointed`: **the one proof that refreshes the baseline** (07:2812).

        Both must be non-negative. SQLite returns `(1, -1, -1)` when the database is not in WAL mode
        or the checkpoint could not start, and `-1 == -1` would otherwise read as a fold and move
        the baseline on the strength of a failure -- the exact mistake subtlety 1 is about, arrived
        at from the other direction.
        """
        return self.log >= 0 and self.log == self.checkpointed


def checkpoint(conn: sqlite3.Connection, mode: CheckpointMode) -> CheckpointResult:
    """Run one `PRAGMA wal_checkpoint(<mode>)` and return its three columns.

    `mode` is interpolated because a PRAGMA argument is a keyword, not a bindable value, and it is
    safe to interpolate because `CheckpointMode` is a closed enum of four literals.
    """
    row = conn.execute(f"PRAGMA wal_checkpoint({mode.value})").fetchone()
    if row is None:  # pragma: no cover - SQLite always returns the row; belt for a custom build
        return CheckpointResult(mode=mode, busy=1, log=-1, checkpointed=-1)
    return CheckpointResult(mode=mode, busy=int(row[0]), log=int(row[1]), checkpointed=int(row[2]))


def wal_file_bytes(db_path: Path) -> int:
    """The size of the `-wal` sidecar, or 0 when there is none.

    The suffix is appended to the whole filename and not substituted for its extension: SQLite's
    sidecars are `<db>-wal` and `<db>-shm`, so `index.owstore` has `index.owstore-wal`. A
    `with_suffix` here would look for `index-wal` and report 0 forever.
    """
    sidecar = db_path.parent / (db_path.name + "-wal")
    return sidecar.stat().st_size if sidecar.is_file() else 0


def run_inline(job: Callable[[], _T]) -> Future[_T]:
    """The identity `Submit`: run `job` now and hand back an already-completed `Future`.

    The default, so a valve is usable with no executor at all, and the shape of the seam: the
    runtime passes `ThreadPoolExecutor.submit` and nothing in this module changes. INV-3 keeps a
    loop out of core and 07:203-205 keeps the schedule out of this document, so "off-thread" is a
    property of what the caller passes here, not of anything below.
    """
    future: Future[_T] = Future()
    if not future.set_running_or_notify_cancel():  # pragma: no cover - a fresh Future never fails
        raise StoreError("a fresh Future refused to start", fix="ow doctor")
    try:
        future.set_result(job())
    except BaseException as error:  # the Future is the only channel a Submit has for it
        future.set_exception(error)
    return future


# ---------------------------------------------------------------------------
# Subtlety 4: the futility latch.
# ---------------------------------------------------------------------------


class FutilityLatch:
    """Two consecutive give-ups arm a 60 s cooldown; while armed the governor is un-valved.

    ST16 (07:3250) states the property -- *"A governor that cannot help gets out of the way"* -- and
    I9 (08:2634) generalises it: *"a repair or governor loop cannot make things worse than not
    running."* The measurement behind it is 07:2840-2842: the mitigation "made things strictly worse
    than no mitigation", turning a pinned resolution phase from slow into OOM-killed at an envelope
    the pre-valve build survived.

    **Give-ups must be consecutive** (08:2440's word). `folded()` resets the count, because a valve
    that gives up once and then works is not futile -- latching on two give-ups an hour apart would
    disable a governor that is doing its job.

    Mutable on purpose, unlike everything else in this module: a latch IS a piece of state that
    outlives one decision, and hiding that behind a frozen value would only move it to the caller.
    """

    __slots__ = ("_armed_at_ms", "_consecutive", "_heartbeat", "_log")

    def __init__(
        self,
        *,
        log: Callable[[str], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        self._consecutive = 0
        self._armed_at_ms: int | None = None
        self._log = log
        self._heartbeat = heartbeat

    @property
    def consecutive_give_ups(self) -> int:
        """Give-ups since the last fold. Latches at `FUTILITY_GIVE_UPS`."""
        return self._consecutive

    def armed(self, now_ms: int) -> bool:
        """True while the cooldown is running. Disarms itself when it elapses.

        Elapsing rather than staying armed forever is 08:2440's "disable for 60 s": the latch buys
        the un-valved build a window, it does not delete the governor. When it disarms, the
        consecutive count resets -- the next attempt starts from zero, so a single give-up after a
        cooldown does not immediately re-arm.
        """
        if self._armed_at_ms is None:
            return False
        if now_ms - self._armed_at_ms < FUTILITY_COOLDOWN_MS:
            if self._heartbeat is not None:
                self._heartbeat()
            return True
        self._armed_at_ms = None
        self._consecutive = 0
        if self._log is not None:
            self._log("wal valve: futility cooldown elapsed, re-arming the governor")
        return False

    def gave_up(self, now_ms: int) -> bool:
        """Record a give-up. Returns True when this one armed the latch.

        The `armed` LOG LINE ST16 requires is emitted here, exactly once per arming, and it names
        the cooldown so an operator reading it knows how long the store runs un-valved.
        """
        self._consecutive += 1
        if self._consecutive < FUTILITY_GIVE_UPS or self._armed_at_ms is not None:
            return False
        self._armed_at_ms = now_ms
        if self._log is not None:
            self._log(
                f"wal valve: armed after {self._consecutive} consecutive give-ups; "
                f"degrading to un-valved for {FUTILITY_COOLDOWN_MS} ms (ST16, I9)"
            )
        return True

    def folded(self) -> None:
        """Record a pass that folded the WAL. Clears the consecutive count (08:2440)."""
        self._consecutive = 0


# ---------------------------------------------------------------------------
# The valve.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValveOutcome:
    """Everything one `pump()` did, so a caller can log it without asking the valve questions."""

    action: ValveAction
    growth_bytes: int
    file_bytes: int
    baseline_bytes: int
    passes: int
    folded: bool
    truncated: bool
    gave_up: bool
    armed: bool


class WalValve:
    """The governor. One `pump()` per `CHECK_INTERVAL_MS` tick, from the runtime.

    Holds three pieces of state and nothing else: the `MonotoneBaseline` (subtlety 1), the
    `FutilityLatch` (subtlety 4), and the seams it was handed -- a checkpointer, an optional park
    barrier (subtlety 3) and a `Submit` (`fold_now`). It never opens a connection, never reads a
    clock and never starts a thread.

    `checkpointer` is a callable rather than a connection because a paused backfill in codegraph ran
    on "a fresh connection per pass" (07:2841), and whether this deployment does that, reuses one
    connection or runs the pragma on the writer's own connection is the runtime's decision. It is
    also what makes every rule below testable against a counting fake instead of a saturated disk.
    """

    __slots__ = ("_baseline", "_checkpointer", "_latch", "_log", "_park", "_submit", "_thresholds")

    def __init__(
        self,
        *,
        thresholds: Thresholds,
        checkpointer: Callable[[CheckpointMode], CheckpointResult],
        park: Park | None = None,
        submit: Submit = run_inline,
        baseline: MonotoneBaseline | None = None,
        log: Callable[[str], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        self._thresholds = thresholds
        self._checkpointer = checkpointer
        self._park = park
        self._submit = submit
        self._baseline = MonotoneBaseline() if baseline is None else baseline
        self._latch = FutilityLatch(log=log, heartbeat=heartbeat)
        self._log = log

    @property
    def baseline(self) -> MonotoneBaseline:
        """The current baseline. Persist it under `WAL_BASELINE_KEY` if you want it to survive."""
        return self._baseline

    @property
    def latch(self) -> FutilityLatch:
        """The futility latch, exposed so `ow doctor` can report an armed governor."""
        return self._latch

    @property
    def thresholds(self) -> Thresholds:
        """The three thresholds this valve was built with."""
        return self._thresholds

    def pump(self, *, wal_file_bytes: int, now_ms: int) -> ValveOutcome:
        """One tick. Observe, decide, act, and report -- the only entry point on the hot path.

        The order inside is not arbitrary:

        1. **The latch first.** While armed, no checkpoint is issued at all -- not even a PASSIVE
           one. That is what "degrade to un-valved" means, and issuing a cheap pass anyway would
           re-create the cost the latch exists to remove.
        2. **The baseline FOLLOWS a downward reset before growth is computed.** A TRUNCATE (ours or
           a heal-at-open's) shrinks the file below the baseline, and growth measured from the old
           one would be 0 forever.
        3. **Decide, then act.** `decide()` is pure, so the governor's algebra is asserted without a
           database.
        """
        if self._latch.armed(now_ms):
            return ValveOutcome(
                action=ValveAction.DEGRADED,
                growth_bytes=self._baseline.growth(wal_file_bytes),
                file_bytes=wal_file_bytes,
                baseline_bytes=self._baseline.baseline,
                passes=0,
                folded=False,
                truncated=False,
                gave_up=False,
                armed=True,
            )
        self._baseline = self._baseline.followed(wal_file_bytes)
        growth = self._baseline.growth(wal_file_bytes)
        action = decide(growth_bytes=growth, file_bytes=wal_file_bytes, thresholds=self._thresholds)
        if action is ValveAction.NONE:
            return self._outcome(action, growth, wal_file_bytes, passes=0, folded=False)
        if action is ValveAction.PASSIVE:
            return self._single_pass(growth, wal_file_bytes)
        return self._barrier(action, growth, wal_file_bytes, now_ms)

    def _outcome(
        self,
        action: ValveAction,
        growth: int,
        file_bytes: int,
        *,
        passes: int,
        folded: bool,
        truncated: bool = False,
        gave_up: bool = False,
    ) -> ValveOutcome:
        """One `ValveOutcome`, with the baseline read after any refresh this tick made."""
        return ValveOutcome(
            action=action,
            growth_bytes=growth,
            file_bytes=file_bytes,
            baseline_bytes=self._baseline.baseline,
            passes=passes,
            folded=folded,
            truncated=truncated,
            gave_up=gave_up,
            armed=False,
        )

    def _run(self, mode: CheckpointMode, file_bytes: int) -> CheckpointResult:
        """One checkpoint through `Submit`, awaited, refreshing the baseline on a fold.

        `.result()` is the "awaited" of 07:2844 and of the promise subtlety 3 says the writer waits
        on. Refreshing the baseline ONLY on `folded` is subtlety 1's rule; the refresh uses the
        file size observed for THIS tick rather than re-reading it, so the baseline and the growth
        term the caller was told about describe the same instant.
        """
        result = self._submit(lambda: self._checkpointer(mode)).result()
        if result.folded:
            self._baseline = self._baseline.reclaimed(file_bytes)
            self._latch.folded()
        return result

    def _single_pass(self, growth: int, file_bytes: int) -> ValveOutcome:
        """The soft path: one PASSIVE checkpoint, off-thread, awaited.

        A pass that does not fold is **not** a give-up. Subtlety 2 says every concurrent PASSIVE
        pass is stale by the time it finishes, so a partial fold under an active writer is the
        expected case; escalation to the hard cap is what the next tick's growth term is for.
        """
        result = self._run(CheckpointMode.PASSIVE, file_bytes)
        return self._outcome(
            ValveAction.PASSIVE, growth, file_bytes, passes=1, folded=result.folded
        )

    def _barrier(
        self, action: ValveAction, growth: int, file_bytes: int, now_ms: int
    ) -> ValveOutcome:
        """The hard and file paths: park the writer, backfill, and chop only if truly parked.

        Up to `MAX_PAUSED_BACKFILL_PASSES` PASSIVE passes, stopping the moment one folds -- subtlety
        2's "with the writer parked the next pass covers everything". Running out of passes is a
        **give-up**, not an error: a pinned reader cannot be fixed by another pass (07:2804's own
        comment), and the futility latch is what a store does about it.

        **The TRUNCATE happens only inside the barrier** (subtlety 3). With no barrier the chop is
        skipped and the tick is recorded as a give-up naming that fact, because a truncate against
        an active writer wins the lock race and then fails that writer past its 5 s `busy_timeout`
        with "database is locked" -- strictly worse than the oversized file it was fixing.
        """
        if self._park is None:
            if self._log is not None:
                self._log(
                    f"wal valve: {action.value} needs a park barrier and this valve has none, so "
                    f"no pass is issued and no chop is attempted "
                    f"(07-store-and-retrieval.md:2815-2822: an unparked pass is stale before it "
                    f"finishes, and an unparked chop fails the writer)"
                )
            self._latch.gave_up(now_ms)
            return self._outcome(action, growth, file_bytes, passes=0, folded=False, gave_up=True)
        with self._park():
            passes = 0
            folded = False
            while passes < MAX_PAUSED_BACKFILL_PASSES:
                passes += 1
                if self._run(CheckpointMode.PASSIVE, file_bytes).folded:
                    folded = True
                    break
            truncated = False
            if action is ValveAction.PAUSE_AND_TRUNCATE:
                self._run(CheckpointMode.TRUNCATE, file_bytes)
                truncated = True
        if not folded and not truncated:
            self._latch.gave_up(now_ms)
            return self._outcome(
                action, growth, file_bytes, passes=passes, folded=False, gave_up=True
            )
        return self._outcome(
            action, growth, file_bytes, passes=passes, folded=folded, truncated=truncated
        )

    def fold_now(self, *, wal_file_bytes: int) -> CheckpointResult:
        """`foldNow()` -- the fourth maintenance operation: the whole WAL, off-thread, awaited.

        07:212 and 07:2844-2846. Its bound is **phase boundaries only** -- after parsing, before the
        first resolution read -- "so the next phase never pages a bulk-write-sized WAL on the main
        thread".

        **FULL and not TRUNCATE.** A phase boundary is a point where the writer is idle, not one
        where it is *provably* parked, and subtlety 3 restricts the chop to the latter.
        `checkpoint_at_barrier()` is for a caller that can prove it.

        The latch is deliberately NOT consulted: a fold is a bounded, caller-scheduled operation at
        a boundary the caller chose, not a governor deciding on its own to spend IO, and I9's
        invariant is about loops that cannot help. It does FEED the latch, through `_run`'s
        `folded()` reset.
        """
        return self._run(CheckpointMode.FULL, wal_file_bytes)

    def checkpoint_at_barrier(
        self, *, wal_file_bytes: int, mode: CheckpointMode = CheckpointMode.TRUNCATE
    ) -> CheckpointResult:
        """A checkpoint inside the park barrier, for a caller that can prove the writer is parked.

        This is the only way to reach `TRUNCATE` other than the file cap, and it **refuses** without
        a barrier rather than running hopefully -- subtlety 3 is a rule, and a truncate against an
        active writer fails that writer past its 5 s `busy_timeout`.
        """
        if self._park is None:
            raise StoreError(
                f"a {mode.value} checkpoint needs a park barrier: a truncate against an active "
                f"writer wins the lock race and then blocks that writer past its 5 s busy_timeout, "
                f"failing it with 'database is locked' (07-store-and-retrieval.md:2819-2822)",
                fix="pass park= when constructing the WalValve",
            )
        with self._park():
            return self._run(mode, wal_file_bytes)


def heal_at_open(
    *,
    file_bytes: int,
    checkpointer: Callable[[CheckpointMode], CheckpointResult],
    heal_mb: int = DEFAULT_WAL_HEAL_MB,
) -> CheckpointResult | None:
    """`[store] wal_heal_mb` -- chop an oversized WAL at every open, or `None` when it is fine.

    07:2806 prints the knob and 07:2820 is the number that earns it: **25.6 GB** of WAL leaked
    across repeatedly-SIGKILLed sessions with no heal-on-open. 02-architecture.md:724 row 6 puts
    "heal-on-open" in the store's open sequence.

    **This is the one TRUNCATE that needs no park barrier**, and it is not an exception to subtlety
    3 -- it satisfies it. Subtlety 3's hazard is a chop that wins the lock race against an *active*
    writer; at open there is no writer on this connection yet, so the barrier is the open itself. A
    concurrent writer in another process is a different matter, and it is `store.write` that
    excludes that one (07:3115), not this function.

    `file_bytes` is passed in rather than read here so the caller can use one observation for the
    heal decision and for the valve's initial baseline.
    """
    if file_bytes <= heal_mb * BYTES_PER_MB:
        return None
    return checkpointer(CheckpointMode.TRUNCATE)
