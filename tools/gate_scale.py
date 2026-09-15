"""G22: a 100,000-unit roster through one Supervisor, and the three numbers that are its verdict.

`tools/gates.toml`'s G22 row is the specification and this is its runner. The assertion cell reads
*"scale: 100k roster, RSS <= 600 MB, >= 2,000 transitions/s"*, and the row is the one row in the
register with `jobs = []` and `pr = false`: section 6.4 of 11-repo-layout.md says G22 *"is a nightly
100k-roster scale run with no PR cell, so it blocks the **release** (checklist step 11) and is
deliberately absent from `ci-ok`'s required set."* 16-roadmap.md:578 spells the invocation:
`uv run tools/gate_scale.py --roster 100000`.

00-vision.md:730 is the acceptance criterion in full (V10-7):

> Scale: a nightly **100k-roster** run with peak claimable <= `queue_high_water`, supervisor RSS
> <= **600 MB**, and >= **2,000** work transitions/s

and 12-performance.md:1677 says what the three catch together: *"the scheduler's per-unit overhead
and the supervisor's memory independence, at a scale a unit test cannot reach."*

## It is a real run, and this is what "real" covers

One process, one `asyncio` loop, one `StoreThread` over one `.owstore` with all four migrations
applied. The roster is written by `omniweave_core.acquire.write_roster`, the work rows by
`omniweave.run.expand.enqueue` -- *"the one `work` INSERT in the framework that is not the
planner's"* -- and the producer is gated by `Supervisor.pause_gate()`, which holds 08:880's
`queue_high_water` / `queue_low_water` hysteresis. The queue is `store.queue.SqliteStore`, so every
claim is `CLAIM_SQL` under `BEGIN IMMEDIATE` and every completion is a real transaction.

**What is synthetic is the operator and nothing else.** The dispatcher returns `Outcome.OK` for
every row without doing work, which is 12-performance.md:1470's own instrument -- *"`ow bench
scheduler`: 1M synthetic units with a no-op operator"* -- and it is the only way to measure
scheduler overhead rather than a parser. 12-performance.md:569 names the shape this produces as a
real corpus shape and not a contrivance: *"fixed-cost amplification: 100k one-byte files ... nothing
caps it, and nothing should -- the work is real."*

## One work row per unit, and the 846,400 this does not run

12-performance.md section 3.4 decomposes a 100,000-document ingest into **846,400** `work` rows:
100,000 `op.identify` + 430,000 parse + 116,400 escalation + 200,000 derive/embed. This gate runs
the first line and not the other three, because the other three are the **planner's** rows and
`omniweave/plan/` is not built (16-roadmap.md:541, W4.1). `op.identify` is the row every unit gets
from the shipped code with no planner at all, and 08:619 makes it the row that *"is what
**creates** the part rows the queue then drains"* -- so it is the head of that decomposition
rather than a sample of it.

The consequence is stated rather than left to be discovered: **a green G22 here is a statement about
100,000 transitions, and the corpus the plan prices is 8.5x that.** The report prints the figure.

## Two diagnostics, because a failing verdict is a number nobody can act on

A run that reports only "84 transitions/s" has found something and named nothing. So the gate
measures the claim from both sides, and the two tables compose into one sentence.

**`claim_depths()` -- what one claim COSTS, against a claimable set of n.** `work_claimable`'s
leading column is `cost_class` and the shipped four-parameter `claim` does not constrain it, so the
index cannot be seeked: `EXPLAIN QUERY PLAN` shows `SCAN work USING INDEX work_claimable` plus
`USE TEMP B-TREE FOR ORDER BY`, **twice** -- once for the `head` CTE and once for the `picked`
subquery. A claim is therefore O(claimable), not O(batch), and the cost is paid AT the depth
`[runtime] queue_high_water` holds the queue at. D190.

**`claim_widths()` -- what one claim BUYS for that cost.** `op.identify` carries
`dispatch_key IS NULL`, and `CLAIM_SQL`'s `LIMIT` subquery collapses to `1` for a NULL head
(`0004_runtime.sql:104-105`, *"A NULL BATCHES ALONE"*, enforced at the claim). So each of the
100,000 rows pays a whole scan for one row. D191. And `Supervisor._next_width()` asks for
`min([runtime.claim] batch)` -- 8, which is `billed_api`'s -- because the narrow `claim` takes no
cost class, so even rows that CAN batch amortise the scan over 8 and not over `free`'s 256. D192.

## Two bounds the plan states and one the plan's own producer cannot hold

`peak claimable <= queue_high_water` is V10-7's wording, and 05:1196 makes the producer commit
**512 rows per transaction** and check the pause *after* a commit and never mid-batch -- 08:889:
*"Backpressure pauses at a safe boundary and never drops."* So the claimable set overshoots the high
water mark by up to `plan_batch - 1` rows, structurally, on every run. The gate asserts
`high_water + plan_batch` and PRINTS the literal reading beside it; `--strict` asserts the literal
one, which keeps V10-7's sentence runnable rather than assumed. That is `gate_incremental.py`'s
arrangement for the same class of finding, and D194 carries the argument.

## Exit codes

0 every bound held, 1 a bound was breached, 2 the gate did not run (a bad argument, a workspace that
could not be made, a run that ended `partial` or `interrupted` and therefore measured nothing). 1
and 2 are distinguished because CI treats both as failure and a human needs to know which.

Specified in 00-vision.md:730 (V10-7), 11-repo-layout.md sections 6.4 and 6.5, 12-performance.md
sections 3.4, 4.1 and 8.4 and rows B22 and G22, 08-runtime.md sections 2.5 and 8, and
16-roadmap.md:550 and :578.
"""

from __future__ import annotations

import argparse
import asyncio  # noqa: TID251 -- gate harness; see the module docstring's last section.
import contextlib
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave.run import bench, expand
from omniweave.run import supervisor as sup
from omniweave_core import acquire, locks
from omniweave_core import config as configmod
from omniweave_core.host.subproc import peak_rss_bytes
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.queue import SqliteStore

if TYPE_CHECKING:  # pragma: no cover -- annotations only.
    from omniweave_core.work import WorkRow

__all__ = [
    "CACHE_KEY",
    "DEPTH_PROBE_CLAIMS",
    "DEPTH_PROBE_DEPTHS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "NOW_NS",
    "PLANNED_ROWS_PER_UNIT",
    "PRODUCER_POLL_MS",
    "ROSTER",
    "RSS_CEILING_BYTES",
    "SAMPLE_MS",
    "SHIPPED_MIGRATIONS",
    "SWEEP_MS",
    "TRANSITIONS_PER_S",
    "URI_FORMAT",
    "WIDTH_PROBE_ROWS",
    "WIDTH_PROBE_WIDTHS",
    "Check",
    "Depth",
    "Measured",
    "Sampler",
    "Timed",
    "Width",
    "build",
    "claim_depths",
    "claim_widths",
    "identify_rows",
    "main",
    "no_op",
    "roster",
    "run_scale",
    "verdict",
    "worker_identity",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

ROSTER: Final = 100_000
"""The roster size 16-roadmap.md:578 and V10-7 both name. `--roster` overrides it for a probe run;
the gate's own step line passes it explicitly so the default and the invocation cannot drift."""

RSS_CEILING_BYTES: Final = 600 * 1024 * 1024
"""12-performance.md:588: the supervisor's resident-set ceiling, *"I31 plus G22's nightly
100k-roster run"*. Binary megabytes, because that is what an RSS reader reports."""

TRANSITIONS_PER_S: Final = 2_000
"""V10-7's floor, which 12-performance.md:153 cross-checks against B22: *"the charter's `<= 0.5
ms/unit` runtime overhead, cross-checked against G22's `>= 2,000 transitions/s` = 0.5
ms/transition."* The two are one number read from two ends."""

PLANNED_ROWS_PER_UNIT: Final = 8.464
"""846,400 `work` rows for 100,000 units -- 12-performance.md section 3.4's own decomposition.

Carried as a number so the report can say what this gate's 100,000 transitions are a fraction OF,
rather than leaving a reader to assume a roster and a queue are the same size. It multiplies
nothing: the gate runs the `op.identify` line and the other three lines are the planner's."""

SAMPLE_MS: Final = 250
"""The RSS and claimable sampling cadence. `host/subproc.py:1218-1221` fixes it: Windows reports a
true `PeakWorkingSetSize` and procfs reports the CURRENT resident set, *"so a Linux sampler needs
the 250 ms cadence to approximate what Windows gives for free."* Sampling on both platforms and
taking the maximum is correct on both; only one of them needs it."""

DEPTH_PROBE_DEPTHS: Final = (1_000, 10_000, 50_000)
DEPTH_PROBE_CLAIMS: Final = 100
"""The queue-depth diagnostic: what ONE claim costs with `n` rows claimable, for three `n`.

The three are chosen against the knob: **50,000** is `[runtime] queue_high_water` itself -- the
depth the plan's own backpressure holds the queue AT, so it is where every long run spends its time
and not a pathological one -- **10,000** is a fifth of it, and **1,000** is where a unit test lives.
Claiming down from the largest gives all three from one seeded store, because a claimed row leaves
`work_claimable`'s partial index and the depth falls with it."""

WIDTH_PROBE_ROWS: Final = 2_048
WIDTH_PROBE_WIDTHS: Final = (1, 8, 32, 256)
"""The claim-width diagnostic: 2,048 rows carrying a `dispatch_key`, claimed at four widths.

The four are chosen, not swept: **1** is what `CLAIM_SQL` gives a NULL `dispatch_key` whatever is
asked for, **8** is what `Supervisor._next_width()` asks for (`min([runtime.claim] batch)`, which
`billed_api` sets), **32** is `local_compute`'s, and **256** is `free`'s -- the width the config
declares for the class this gate's rows are in and which no claim ever asks for. Each number in the
printed table is therefore a knob a reader can find."""

_UNIT_SQL: Final = (
    "INSERT INTO unit(unit_uri, connector, state, size, mtime_ns, indexed_at_ns, derived,"
    " trust_class, last_seen_gen) VALUES(:uri,'fs','discovered',1,0,0,'{}','internal',1)"
)

_EVIDENCE_SQL: Final = (
    "INSERT OR IGNORE INTO route_evidence(evidence_digest, payload, first_seen_at)"
    " VALUES('ev', X'00', 1)"
)

_DECISION_SQL: Final = """
INSERT INTO route_decision(decision_id, content_sha256, unit_part, lane, rung,
  policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class,
  rule_id, rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros,
  admission, generation, decided_at)
VALUES(:decision_id,'c0',:part,'parse',1,'pd','pb','hd','rd','drv','free','r1','gate_scale:1','sk',
  'ev','{}',0,0,'admitted',1,1)
"""

_KEYED_WORK_SQL: Final = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key,
                 decision_id, driver, cost_class, dispatch_key, status)
VALUES(:uri, :part, 'parse.pdf', 1, 'planned', :decision_id, 'drv', 'free', :dk, 'pending')
"""

_RESET_SQL: Final = (
    "UPDATE work SET status='pending', claimed_by=NULL, claimed_gen=NULL,"
    " lease_expires=NULL, attempts_total=0 WHERE dispatch_key IS NOT NULL"
)

_DISPATCH_KEY: Final = "d" * 16

# THE FOUR STATEMENTS ABOVE ARE A FIXTURE, NOT A PLANNER.
#
# `omniweave_core/store/crashmatrix.py:707-713` takes exactly this reading for exactly this reason
# and says so in the same words: writing a routed `work` row is the planner's job, the planner is
# 16-roadmap.md:541's, and a gate that needs routed rows to claim has to write them itself until
# that lands. They are confined to `claim_widths()`, they produce rows the DIAGNOSTIC claims and the
# VERDICT never touches, and they are deleted the day `omniweave/plan/` ships. The verdict's own
# rows come from `expand.enqueue`, which is real.


# =============================================================================================
# 1. The harness, which is `omniweave.run.bench`'s and not this file's
# =============================================================================================

# 12-performance.md section 7.1 homes the corpus, the operator and the loop driver in
# `packages/omniweave/src/omniweave/run/bench.py` -- *"the registry is one function per subject"*.
# This gate is a gate over that harness, the way `tools/gate_crash.py` is a gate over
# `store/crashmatrix.py`: the names below are BOUND, never re-implemented, because a second corpus
# generator is a corpus that can drift from the bench's while both claim to measure one loop.
CACHE_KEY: Final = bench.CACHE_KEY
NOW_NS: Final = bench.NOW_NS
PRODUCER_POLL_MS: Final = bench.PRODUCER_POLL_MS
SHIPPED_MIGRATIONS: Final = bench.SHIPPED_MIGRATIONS
SWEEP_MS: Final = bench.SWEEP_MS
URI_FORMAT: Final = bench.URI_FORMAT

build = bench.open_store
identify_rows = bench.identify_rows
no_op = bench.no_op
roster = bench.synthetic_roster
worker_identity = bench.worker_identity
_claim_batch = bench.claim_batch_of
_claimable = bench.claimable
_Producer = bench.Producing
_context = bench.run_context


# =============================================================================================
# 3. The measurement: what the store cost, what the process held, and how deep the queue got
# =============================================================================================


class Timed:
    """`Store`'s four methods, each one timed and counted. The split a red verdict needs.

    Structural, like `SqliteStore` itself: no inheritance edge, four methods, never widened. It adds
    no behaviour -- every call is forwarded unchanged -- and the reason it exists at all is that
    "743 transitions/s" and "743 transitions/s, of which 94% is `Store.claim`" are different
    findings, and only the second one names a mechanism.

    **Both figures are LATENCIES and include time queued, and that is the finding rather than a
    caveat.** INV-17 makes the store thread *"the only holder of a `Connection` in a process"*
    (07:2722), so one claim and `2 x max_workers` completions compete for one `StoreThread` queue:
    an observed `complete` of 1.2 ms against an uncontended 0.12 ms is ten units waiting, not a
    slow statement. `claim_widths()` measures the same statements with nothing else running, which
    is what makes the pair readable.

    The two also do not add up to the run, and the report does not add them: `claim` is ONE
    coroutine, so its total IS wall time, and `complete` is `sum(max_workers)` coroutines at once,
    so its total is not.
    """

    __slots__ = (
        "_inner",
        "claim_rows",
        "claim_s",
        "claims",
        "completes",
        "completes_s",
        "counts",
        "reaps",
    )

    def __init__(self, inner: SqliteStore) -> None:
        self._inner = inner
        self.claims = 0
        self.claim_rows = 0
        self.claim_s = 0.0
        self.completes = 0
        self.completes_s = 0.0
        self.reaps = 0
        self.counts = 0

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]:
        at = time.perf_counter()
        rows = self._inner.claim(batch, gen, worker, lease_ms)
        self.claim_s += time.perf_counter() - at
        self.claims += 1
        self.claim_rows += len(rows)
        return rows

    def complete(self, row_id: int, gen: int, result: object) -> bool:
        at = time.perf_counter()
        committed = self._inner.complete(row_id, gen, result)  # type: ignore[arg-type]
        self.completes_s += time.perf_counter() - at
        self.completes += 1
        return committed

    def reap_expired_leases(self, now_ms: int) -> int:
        self.reaps += 1
        return self._inner.reap_expired_leases(now_ms)

    def counts_by_status(self) -> Mapping[str, int]:
        self.counts += 1
        return self._inner.counts_by_status()

    @property
    def claim_ms_per_row(self) -> float:
        """Wall milliseconds of `Store.claim` per row it returned. B22's first component."""
        return self.claim_s * 1e3 / self.claim_rows if self.claim_rows else 0.0

    @property
    def complete_ms(self) -> float:
        """Wall milliseconds in one `Store.complete`. B22's second half, budgeted at 0.45 ms."""
        return self.completes_s * 1e3 / self.completes if self.completes else 0.0


class Sampler(threading.Thread):
    """Peak RSS and peak claimable, sampled every `SAMPLE_MS` on a daemon thread.

    Two quantities and one cadence, because they answer the same question at two scales: an RSS that
    tracks the roster and a claimable set that outruns the water mark are the same defect seen from
    the process and from the queue. `peak_rss_bytes` never raises (`host/subproc.py:1215`), so a
    sampler failure is a `None` reading and a stated source rather than a dead run.

    `claimable` reaches `counts_by_status()`, which takes `BEGIN IMMEDIATE` around a `GROUP BY`. At
    four samples a second against a store doing thousands of transactions that is under a per cent,
    and it is the only reading of the claimable set available: 07:2722 puts every query on the store
    thread, and a second connection would be INV-17.
    """

    def __init__(self, claimable: Callable[[], int], *, period_s: float = SAMPLE_MS / 1000) -> None:
        super().__init__(name="g22-sampler", daemon=True)
        self._claimable = claimable
        self._period = period_s
        # `_halt` and not `_stop`: `threading.Thread._stop` is a real method that `join()` calls
        # through `_wait_for_tstate_lock`, so an attribute of that name shadows it and every join
        # raises `TypeError: 'Event' object is not callable` -- from inside the standard library,
        # a hundred lines from the assignment that caused it.
        self._halt = threading.Event()
        self.peak_rss = 0
        self.rss_source = "not sampled"
        self.peak_claimable = 0
        self.samples = 0

    def sample(self) -> None:
        """One reading of each. Public so a test can take one without starting a thread."""
        observed, how = peak_rss_bytes(os.getpid())
        if observed is not None:
            self.peak_rss = max(self.peak_rss, observed)
        self.rss_source = how
        self.peak_claimable = max(self.peak_claimable, self._claimable())
        self.samples += 1

    def run(self) -> None:  # pragma: no cover -- the thread body; `sample()` is what tests call.
        while not self._halt.is_set():
            self.sample()
            self._halt.wait(self._period)

    def stop(self) -> None:
        """Stop and join, then take one last reading so the final peak is never missed."""
        self._halt.set()
        if self.is_alive():
            self.join(timeout=5.0)
        self.sample()


@dataclass(frozen=True, slots=True)
class Width:
    """One row of the claim-width diagnostic: what a claim of `width` rows cost per row."""

    width: int
    calls: int
    rows: int
    seconds: float
    note: str = ""

    @property
    def ms_per_row(self) -> float:
        return self.seconds * 1e3 / self.rows if self.rows else 0.0

    @property
    def ms_per_call(self) -> float:
        return self.seconds * 1e3 / self.calls if self.calls else 0.0


@dataclass(frozen=True, slots=True)
class Depth:
    """One row of the queue-depth diagnostic: what one claim cost with `claimable` rows waiting."""

    claimable: int
    claims: int
    rows: int
    seconds: float

    @property
    def ms_per_claim(self) -> float:
        return self.seconds * 1e3 / self.claims if self.claims else 0.0

    @property
    def us_per_claimable_row(self) -> float:
        """The scan rate: microseconds of claim per row waiting in the queue.

        Flat across the three depths is what a full scan looks like, and it is the number that
        turns "a claim is slow" into "a claim reads the whole claimable set." D190."""
        return self.ms_per_claim * 1e3 / self.claimable if self.claimable else 0.0


@dataclass(frozen=True, slots=True)
class Measured:
    """Everything one scale run produced. The verdict is a pure function of this."""

    roster: int
    roster_s: float
    enqueue_s: float
    """The FIRST enqueue pass only: roster start to the first pause at `queue_high_water`.

    Every later pass runs inside the drain, resumed by the `PauseGate` while the loop is claiming,
    so its time is the drain's wall clock and cannot be separated from it by a stopwatch. Reporting
    a sum of the two would be reporting a wall time twice. `written` on the producer is the count
    that covers the whole roster; this is the number for the one pass that ran alone."""
    drain_s: float
    status: str
    claimed: int
    completed: int
    superseded: int
    abandoned: int
    crashed: int
    batches: int
    reaped: int
    lag_breach_ms: int
    pauses: int
    enqueued: int
    """Rows the first enqueue pass wrote before it hit `queue_high_water`. See `enqueue_s`."""
    peak_rss: int
    rss_source: str
    peak_claimable: int
    samples: int
    emits: int
    high_water: int
    low_water: int
    plan_batch: int
    claim_width: int
    claim_ms_per_row: float
    claim_s: float
    complete_ms: float
    workers: Mapping[str, int]
    inflight: Mapping[str, int]
    claim_batch: Mapping[str, int]
    cpus: int
    widths: tuple[Width, ...] = ()
    depths: tuple[Depth, ...] = ()

    @property
    def transitions_per_s(self) -> float:
        return self.completed / self.drain_s if self.drain_s > 0 else 0.0

    @property
    def ms_per_transition(self) -> float:
        return self.drain_s * 1e3 / self.completed if self.completed else 0.0

    @property
    def emits_per_transition(self) -> float:
        """`emit` calls per completed row. B22's cell prices *"~8 events"* into its 0.45 ms."""
        return self.emits / self.completed if self.completed else 0.0

    @property
    def claim_share(self) -> float:
        """The fraction of the drain's wall time spent inside `Store.claim`.

        Meaningful precisely because the claimer is ONE coroutine: 08:2478's wider claim would take
        a cost class and could run one per class, and the narrow four-parameter form that ships
        cannot. So this number is a share of the run and not a share of some total CPU."""
        return self.claim_s / self.drain_s if self.drain_s > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Check:
    """One asserted bound, its observed value, and the line of the plan that set it."""

    name: str
    observed: float
    bound: float
    ok: bool
    unit: str
    source: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Absence:
    """Something G22 asserts that this run did not check, and who owns it. Never a silent pass."""

    what: str
    why: str
    owner: str


NOT_CHECKED: Final[tuple[Absence, ...]] = (
    Absence(
        what="the 746,400 planner rows: parse, escalation, derive and embed",
        why=(
            "12-performance.md section 3.4 decomposes a 100,000-unit roster into 846,400 work rows "
            "and this gate runs the 100,000 op.identify line. The other three lines are written by "
            "omniweave/plan/'s single routed INSERT, which is not built"
        ),
        owner="W4.1, the planner (16-roadmap.md:541)",
    ),
    Absence(
        what="the ~8 events per transition B22 prices",
        why=(
            "B22's cell is 'claim share + Store.complete() + key + ~8 events'. The loop's emit "
            "is a counter here and not a TraceSink, so the events are counted and never written. "
            "That makes every millisecond below a FLOOR rather than a measurement of B22 itself"
        ),
        owner="W4.8's event sink, wired by a run that has one",
    ),
    Absence(
        what="the machine: this is whatever ran it, and a Budget may live on only one",
        why=(
            "12-performance.md section 1 makes ow-bench-1 the one pinned machine a Budget is "
            "measured on, and section 8.3 makes a breach a conversation with a Pacer baseline "
            "behind it. There is no baseline here and nothing is compared to one, so every number "
            "below is an INDICATION -- the same standing tools/measure_store.py takes for "
            "store.bytes_per_block on a GitHub runner. What the verdict does assert is the "
            "MECHANISM: whether the three bounds resolve, and by how far"
        ),
        owner=(
            "11-repo-layout.md section 6.5's nightly ow-bench-1 cell, which ci.yml records as a "
            "real gap: there is no schedule: trigger in that file and no nightly job"
        ),
    ),
    Absence(
        what="the second process",
        why=(
            "08:739-743 makes the durable budget_reservation ledger the authority precisely "
            "because 'two scheduler processes each holding an in-memory semaphore of 2 show the "
            "provider 4'. One process cannot exercise that, and neither can it exercise two "
            "claimers racing on CLAIM_SQL's BEGIN IMMEDIATE, which is what its atomicity is FOR"
        ),
        owner="G21's crash matrix already spawns; a scale run with two claimers does not exist",
    ),
)


# =============================================================================================
# 4. The run
# =============================================================================================


async def run_scale(
    root: Path,
    *,
    count: int,
    config: object,
    generation: int = 1,
    widths: Sequence[int] = WIDTH_PROBE_WIDTHS,
    depths: Sequence[int] = DEPTH_PROBE_DEPTHS,
) -> Measured:
    """Seed the roster, stream the work rows, drain them, and return every number it produced.

    The order is the run's order and each step is measured separately, because they fail
    differently: a slow roster write is a store-side finding, a producer that never pauses is a
    hysteresis finding, and a slow drain is the scheduler finding G22 exists for.

    `widths` and `depths` select the two diagnostics independently, and each defaults to ON: the
    depth probe seeds `max(depths)` rows of its own, which at the shipped 50,000 is the one part of
    this function a caller might reasonably not want to pay for.

    **The first enqueue pass runs before the loop opens**, and that is not an optimisation. It
    pauses at `queue_high_water`, so the claimable set is at its peak before a single row is
    claimed -- which is the state V10-7's first bound is about -- and it removes a race in which the
    claimer's three quiet polls could end the run before the producer's first transaction committed.
    """
    path = build(root)
    host = sup.HostFacts.measure(root)
    admission = sup.derive_admission(config, host)
    shipped = sup.LoopTimings.of(config)
    timings = sup.LoopTimings(
        lease_ms=shipped.lease_ms,
        lease_extend_ms=shipped.lease_extend_ms,
        stall_poll_ms=shipped.stall_poll_ms,
        deferred_sweep_ms=SWEEP_MS,
        shutdown_grace_ms=shipped.shutdown_grace_ms,
        loop_lag_max_ms=shipped.loop_lag_max_ms,
    )
    claim_batch = _claim_batch(config)
    plan_batch = int(config.get("runtime.plan_batch"))  # type: ignore[attr-defined]
    events: dict[str, int] = {}

    def emit(*, kind: object, fields: Mapping[str, object] | None = None) -> None:
        """Count by kind and hold nothing at all.

        A list of 200,000 events would BE the RSS number this run is measuring, which is the whole
        reason `RunReport` carries counts and not records. The tally is reported, because B22
        prices *"~8 events"* into its 0.45 ms and the number of `emit` calls one transition
        actually makes is the only part of that this gate can check without a sink."""
        del fields
        name = str(kind)
        events[name] = events.get(name, 0) + 1

    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        at = time.perf_counter()
        acquire.write_roster(thread, roster(count, generation=generation))
        roster_s = time.perf_counter() - at

        queue = Timed(SqliteStore(thread, wait_ms=locks.BATCH_WAIT_MS))
        context = _context(config, admission, root, generation=generation)
        gate = sup.PauseGate(
            lambda: _claimable(queue.counts_by_status()), admission=admission, emit=emit
        )
        producer = _Producer(
            thread, identify_rows(count), gate=gate, emit=emit, plan_batch=plan_batch
        )

        at = time.perf_counter()
        still_going = await asyncio.to_thread(producer.pass_once)
        enqueue_s = time.perf_counter() - at
        first_pass = producer.written

        supervisor = sup.Supervisor(
            context,
            queue=queue,  # type: ignore[arg-type]
            dispatch=no_op,  # type: ignore[arg-type]
            admission=admission,
            timings=timings,
            worker=worker_identity(),
            claim_batch=claim_batch,
            emit=emit,
        )
        sampler = Sampler(lambda: _claimable(queue.counts_by_status()))
        sampler.sample()
        sampler.start()
        streaming = (
            asyncio.create_task(producer.stream(context.cancel.cancelled)) if still_going else None
        )
        at = time.perf_counter()
        report = await supervisor.run()
        drain_s = time.perf_counter() - at
        if streaming is not None:
            streaming.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await streaming
        sampler.stop()

        measured_widths = claim_widths(path, thread, widths=widths)
    measured_depths = claim_depths(root, depths=depths)

    return Measured(
        roster=count,
        roster_s=roster_s,
        enqueue_s=enqueue_s,
        drain_s=drain_s,
        status=report.status,
        claimed=report.claimed,
        completed=report.completed,
        superseded=report.superseded,
        abandoned=report.abandoned,
        crashed=report.crashed,
        batches=report.batches,
        reaped=report.reaped,
        lag_breach_ms=report.lag_breach_ms,
        pauses=producer.paused,
        enqueued=first_pass,
        peak_rss=sampler.peak_rss,
        rss_source=sampler.rss_source,
        peak_claimable=sampler.peak_claimable,
        samples=sampler.samples,
        emits=sum(events.values()),
        high_water=admission.high_water,
        low_water=admission.low_water,
        plan_batch=plan_batch,
        claim_width=max(1, min(claim_batch.values(), default=1)),
        claim_ms_per_row=queue.claim_ms_per_row,
        claim_s=queue.claim_s,
        complete_ms=queue.complete_ms,
        workers=dict(admission.workers),
        inflight=dict(admission.inflight),
        claim_batch=claim_batch,
        cpus=host.cpus,
        widths=measured_widths,
        depths=measured_depths,
    )


def claim_widths(
    path: Path, thread: ow.StoreThread, *, widths: Sequence[int] = WIDTH_PROBE_WIDTHS
) -> tuple[Width, ...]:
    """The diagnostic: what a claim costs per row at each width, over rows that CAN batch.

    It runs after the verdict's own rows are drained and over `WIDTH_PROBE_ROWS` fresh rows carrying
    a `dispatch_key`, so nothing here moves a number the verdict reads. Between widths the rows are
    reset to `pending` on a second connection -- the store thread is busy being the store, and
    `_RESET_SQL` touches only `dispatch_key IS NOT NULL`, so the fixture cannot reach an
    `op.identify` row even by accident.

    Returns one `Width` per width, in the order given. An empty `widths` returns an empty tuple,
    which is how a caller that only wants the verdict says so.
    """
    if not widths:
        return ()
    _seed_keyed(path)
    queue = SqliteStore(thread, wait_ms=locks.BATCH_WAIT_MS)
    rows: list[Width] = []
    for width in widths:
        _reset_keyed(path)
        at = time.perf_counter()
        got = calls = 0
        while True:
            claimed = queue.claim(width, 1, "gate_scale:0:0", 120_000)
            calls += 1
            if not claimed:
                break
            got += len(claimed)
        rows.append(Width(width=width, calls=calls, rows=got, seconds=time.perf_counter() - at))
    return tuple(rows)


def claim_depths(
    root: Path, *, depths: Sequence[int] = DEPTH_PROBE_DEPTHS, claims: int = DEPTH_PROBE_CLAIMS
) -> tuple[Depth, ...]:
    """The diagnostic that explains the other one: what ONE claim costs against `n` claimable rows.

    **`work_claimable`'s leading column is `cost_class` and the shipped `claim` does not constrain
    it**, so the index cannot be seeked. `EXPLAIN QUERY PLAN` on `CLAIM_SQL` reads, twice:

        MATERIALIZE head / SCAN work USING INDEX work_claimable / USE TEMP B-TREE FOR ORDER BY
        ...
        SCAN w USING INDEX work_claimable / USE TEMP B-TREE FOR ORDER BY

    -- the `head` CTE scans and sorts the whole claimable set, and the `picked` subquery scans and
    sorts it again. So a claim is O(claimable) and not O(batch), and D190 is what that costs.

    Its own store, in `root`, because the verdict's store is drained by the time this runs and
    re-seeding it would put 50,000 rows into a `work` table the width table then claims out of.
    One `StoreThread` per file is INV-17 intact: the rule is one Connection per THREAD.

    Measured from the deepest downwards: a claimed row leaves the partial index, so claiming the
    difference is how the next depth is reached. Returns one `Depth` per depth, deepest first.
    """
    if not depths:
        return ()
    ordered = sorted(depths, reverse=True)
    path = root / "depth.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
    finally:
        connection.close()
    measured: list[Depth] = []
    with ow.StoreThread(lambda: ow.connect(path), name="ow-store-depth") as thread:
        acquire.write_roster(thread, roster(ordered[0], generation=1))
        expand.enqueue(thread, identify_rows(ordered[0]))
        queue = SqliteStore(thread, wait_ms=locks.BATCH_WAIT_MS)
        standing = ordered[0]
        for depth in ordered:
            standing -= _drain_to(queue, standing - depth)
            at = time.perf_counter()
            rows = sum(len(queue.claim(1, 1, "gate_scale:0:0", 120_000)) for _ in range(claims))
            measured.append(
                Depth(
                    claimable=standing,
                    claims=claims,
                    rows=rows,
                    seconds=time.perf_counter() - at,
                )
            )
            standing -= rows
    return tuple(measured)


def _drain_to(queue: SqliteStore, count: int) -> int:
    """Claim `count` rows away, widest first. Claimed rows leave `work_claimable`'s partial index.

    Claimed and never completed: a completion is a transaction with five participants and this only
    needs the rows out of the index, which the claim's own UPDATE already does. The lease is long
    and nothing reaps here.
    """
    taken = 0
    while taken < count:
        rows = queue.claim(min(256, count - taken), 1, "gate_scale:0:0", 3_600_000)
        if not rows:
            break
        taken += len(rows)
    return taken


def _seed_keyed(path: Path) -> None:
    """`WIDTH_PROBE_ROWS` routed `work` rows under one unit. See the fixture comment above."""
    connection = ow.connect(path)
    try:
        connection.execute(_UNIT_SQL, {"uri": "file:///scale/keyed.bin"})
        connection.execute(_EVIDENCE_SQL)
        connection.executemany(
            _DECISION_SQL,
            [
                {"decision_id": f"gs_{index}", "part": f"p{index}"}
                for index in range(WIDTH_PROBE_ROWS)
            ],
        )
        connection.executemany(
            _KEYED_WORK_SQL,
            [
                {
                    "uri": "file:///scale/keyed.bin",
                    "part": f"p{index}",
                    "decision_id": f"gs_{index}",
                    "dk": _DISPATCH_KEY,
                }
                for index in range(WIDTH_PROBE_ROWS)
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _reset_keyed(path: Path) -> None:
    """Hand the diagnostic's rows back to `pending`. Only ever the rows that carry a key."""
    connection = ow.connect(path)
    try:
        connection.execute(_RESET_SQL)
        connection.commit()
    finally:
        connection.close()


# =============================================================================================
# 5. The verdict
# =============================================================================================


def verdict(measured: Measured, *, strict: bool = False) -> tuple[Check, ...]:
    """V10-7's three bounds against one run's numbers. Pure, and the only place a `<=` lives.

    The claimable bound is the one that is not V10-7's arithmetic, and `--strict` is what makes that
    visible rather than lenient: 05:1196 commits the producer at `plan_batch` rows per transaction
    and 08:889 checks the pause at a transaction boundary, so the claimable set can stand at
    `high_water + plan_batch - 1` for as long as one commit takes, on every correct run. `strict`
    asserts V10-7's literal `<= queue_high_water`, which is a bound this producer cannot hold -- and
    running it is how the concession stays a measurement instead of an assumption. D194.

    **`+ plan_batch` is exact, and it was worth being suspicious of.** A 100,000-row run reported
    50,669 against this bound and the first explanation offered for it -- that a fast drain could
    let a check read a stale count and the overshoot was really bounded by a rate gap -- was
    plausible, and wrong. The cause was `_Producer.stream` enqueueing before it asked, and with
    that fixed the bound holds exactly, in both directions, at 8/4/4 and at 500/250/64 and at the
    shipped 50000/25000/512. A bound that is off by one transaction is a bound; a bound that is off
    by an unbounded rate ratio is an excuse.
    """
    ceiling = measured.high_water if strict else measured.high_water + measured.plan_batch
    note = (
        ""
        if strict
        else (
            f"queue_high_water + [runtime] plan_batch; the producer checks the pause after a "
            f"{measured.plan_batch}-row commit and never mid-batch (05:1196, D194)"
        )
    )
    return (
        Check(
            name="peak claimable",
            observed=float(measured.peak_claimable),
            bound=float(ceiling),
            ok=measured.peak_claimable <= ceiling,
            unit="rows",
            source="00-vision.md:730 V10-7, [runtime] queue_high_water",
            note=note,
        ),
        Check(
            name="supervisor peak RSS",
            observed=measured.peak_rss / (1024 * 1024),
            bound=RSS_CEILING_BYTES / (1024 * 1024),
            ok=0 < measured.peak_rss <= RSS_CEILING_BYTES,
            unit="MiB",
            source="12-performance.md section 4.1, I31",
            note=measured.rss_source,
        ),
        Check(
            name="work transitions/s",
            observed=measured.transitions_per_s,
            bound=float(TRANSITIONS_PER_S),
            ok=measured.transitions_per_s >= TRANSITIONS_PER_S,
            unit="/s",
            source="00-vision.md:730 V10-7, cross-checked against B22's 0.45 ms",
            note=f"{measured.ms_per_transition:.3f} ms per transition",
        ),
    )


# =============================================================================================
# 6. The report
# =============================================================================================


def _mib(value: int) -> str:
    return f"{value / (1024 * 1024):,.0f} MiB"


def _machine_lines(measured: Measured) -> list[str]:
    """What the run was measured ON. 08:661: a performance number is attributable to a machine."""
    return [
        f"  machine       {measured.cpus} cpus",
        f"  derived       workers {_table(measured.workers)}",
        f"                inflight {_table(measured.inflight)}",
        f"                [runtime.claim] batch {_table(measured.claim_batch)}",
        f"                _next_width() asks for {measured.claim_width}"
        f", which is min() of that table",
        f"  water         queue_high_water {measured.high_water:,}"
        f" / queue_low_water {measured.low_water:,}"
        f", [runtime] plan_batch {measured.plan_batch}",
    ]


def _table(values: Mapping[str, int]) -> str:
    return "{" + ", ".join(f"{name}: {value}" for name, value in sorted(values.items())) + "}"


def _run_lines(measured: Measured) -> list[str]:
    return [
        f"  roster        {measured.roster:,} unit rows in {measured.roster_s:.2f} s",
        f"  enqueue       {measured.enqueued:,} op.identify rows before the first pause,"
        f" in {measured.enqueue_s:.2f} s; the producer paused {measured.pauses}x",
        "                the rest streamed INSIDE the drain, resumed at the low-water mark",
        f"  drain         {measured.completed:,} work transitions in {measured.drain_s:.2f} s"
        f" ({measured.status})",
        f"                {measured.batches:,} batches, {measured.superseded} superseded,"
        f" {measured.abandoned} abandoned, {measured.crashed} crashed,"
        f" {measured.reaped:,} reaper sweeps",
        f"                loop lag breach {measured.lag_breach_ms} ms,"
        f" {measured.samples:,} RSS/claimable samples",
        f"                {measured.emits:,} events emitted,"
        f" {measured.emits_per_transition:.1f} per transition (B22 prices ~8)",
    ]


def _split_lines(measured: Measured) -> list[str]:
    """Where one transition's milliseconds went. Printed always, red or green: B22 is a Budget."""
    workers = sum(measured.workers.values())
    lines = [
        "",
        f"WHERE ONE TRANSITION'S {measured.ms_per_transition:.3f} ms WENT",
        "  B22 budgets the whole of it at 0.45 ms. Both latencies below include time QUEUED",
        f"  on the one StoreThread INV-17 permits: 1 claimer + {workers} workers, 2 units each.",
        "",
        f"    Store.claim      {measured.claim_ms_per_row:9.4f} ms/row"
        f"  {measured.claim_s:8.1f} s = {measured.claim_share * 100:3.0f}% of the drain"
        f"  (ONE coroutine: wall)",
        f"    Store.complete   {measured.complete_ms:9.4f} ms/row"
        f"  {'':11}  {workers:3} coroutines deep: not wall",
    ]
    if measured.depths:
        lines.append("")
        lines.append("  ONE claim, against a claimable set of n. CLAIM_SQL is O(n), not O(batch):")
        lines.append(
            "  `SCAN work USING INDEX work_claimable` + `USE TEMP B-TREE FOR ORDER BY`, TWICE"
            " -- D190"
        )
        for depth in measured.depths:
            at_the_mark = depth.claimable >= measured.high_water
            lines.append(
                f"    n = {depth.claimable:>7,}   {depth.ms_per_claim:9.4f} ms/claim"
                f"   {depth.us_per_claimable_row:7.4f} us per row waiting"
                f"{'   <- queue_high_water' if at_the_mark else ''}"
            )
    if measured.widths:
        lines.append("")
        lines.append(
            f"  and what a claim BUYS for that cost, over {WIDTH_PROBE_ROWS:,} rows carrying a"
            f" dispatch_key:"
        )
        for width in measured.widths:
            lines.append(
                f"    width {width.width:>4}  {width.ms_per_row:9.4f} ms/row"
                f"  {width.calls:>5} calls at {width.ms_per_call:6.3f} ms each"
            )
            note = _width_note(width, measured)
            if note:
                lines.append(f"                 {note}")
    return lines


def _width_note(width: Width, measured: Measured) -> str:
    """Which knob each width is, so a number in the table resolves to something a reader can set."""
    if width.width == 1:
        return "what CLAIM_SQL gives a NULL dispatch_key, whatever is asked for -- D191"
    if width.width == measured.claim_width:
        return "what Supervisor._next_width() asks for: min([runtime.claim] batch) -- D192"
    for name, configured in sorted(measured.claim_batch.items()):
        if configured == width.width:
            return f"[runtime.claim] batch.{name}"
    return ""


def _absence_lines() -> list[str]:
    """One block per absence, wrapped to a terminal. A report nobody can read is not a report."""
    lines = ["", "NOT CHECKED BY THIS RUN"]
    for absence in NOT_CHECKED:
        lines.append(f"  {absence.what}")
        lines.extend(_wrapped("      why:   ", absence.why))
        lines.extend(_wrapped("      owner: ", absence.owner))
    return lines


def _wrapped(prefix: str, text: str, *, width: int = 96) -> list[str]:
    """`text` under `prefix`, continuations indented to it. No dependency, nothing ragged."""
    body = textwrap.wrap(text, width=width - len(prefix)) or [""]
    pad = " " * len(prefix)
    return [prefix + body[0], *(pad + line for line in body[1:])]


def report(measured: Measured, checks: Sequence[Check], out: TextIO, *, strict: bool) -> None:
    """The whole report: the machine, the run, the three bounds, the split, and the absences."""
    print(
        f"G22 -- {measured.roster:,}-unit roster, one work row per unit,"
        f" one supervisor, one store, one process",
        file=out,
    )
    print("", file=out)
    for line in (*_machine_lines(measured), "", *_run_lines(measured), ""):
        print(line, file=out)
    for check in checks:
        comparison = ">=" if check.unit == "/s" else "<="
        print(
            f"  {check.name:<22} {check.observed:>12,.0f} {check.unit:<5} {comparison}"
            f" {check.bound:>9,.0f} {check.unit:<5} {'ok' if check.ok else 'FAIL'}",
            file=out,
        )
        for line in _wrapped("      ", check.source):
            print(line, file=out)
        if check.note:
            for line in _wrapped("      ", check.note):
                print(line, file=out)
    for line in (*_split_lines(measured), *_absence_lines()):
        print(line, file=out)
    print("", file=out)
    breached = [check for check in checks if not check.ok]
    scale = f"{measured.completed:,} transitions is ONE work row per unit; 12-performance.md"
    scale += f" section 3.4's corpus is {PLANNED_ROWS_PER_UNIT:.3f}x that"
    if breached:
        print(f"G22 FAIL  {len(breached)} of {len(checks)} bound(s) breached:", file=out)
        for check in breached:
            print(f"          {check.name}", file=out)
    else:
        print(f"G22 ok  {len(checks)} bound(s) held{' (strict)' if strict else ''}.", file=out)
    for line in _wrapped("        ", f"{scale}."):
        print(line, file=out)


# =============================================================================================
# 7. The CLI
# =============================================================================================


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="G22: a 100k-roster scale run. Nightly only; see tools/gates.toml."
    )
    parser.add_argument(
        "--roster",
        type=int,
        default=ROSTER,
        help=f"units in the roster, one work row each (default {ROSTER})",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="where to build the store (default: a temporary directory, removed afterwards)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="assert V10-7's literal `peak claimable <= queue_high_water`; see verdict()",
    )
    parser.add_argument(
        "--no-diagnostic",
        action="store_true",
        help="skip both claim diagnostics; they are what explain a red verdict",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, out: TextIO = sys.stdout) -> int:
    """Run the gate. 0 every bound held, 1 a bound breached, 2 it did not run."""
    args = _parser().parse_args(argv)
    if args.roster < 1:
        print(
            f"DID NOT RUN: --roster is {args.roster}; a roster of no units is not a roster",
            file=out,
        )
        return EXIT_NOT_RUN

    temporary = args.root is None
    root = Path(tempfile.mkdtemp(prefix="ow-g22-")) if temporary else Path(args.root)
    try:
        config = configmod.load(cwd=root, env={})
        measured = asyncio.run(
            run_scale(
                root,
                count=args.roster,
                config=config,
                widths=() if args.no_diagnostic else WIDTH_PROBE_WIDTHS,
                depths=() if args.no_diagnostic else DEPTH_PROBE_DEPTHS,
            )
        )
    except Exception as exc:
        print(f"DID NOT RUN: {type(exc).__name__}: {exc}", file=out)
        return EXIT_NOT_RUN
    finally:
        if temporary:
            shutil.rmtree(root, ignore_errors=True)

    if measured.status != "done" or measured.completed != args.roster:
        print(
            f"DID NOT RUN: the run ended {measured.status!r} with {measured.completed:,} of "
            f"{args.roster:,} rows completed; a scale number over a partial drain is not one",
            file=out,
        )
        return EXIT_NOT_RUN

    checks = verdict(measured, strict=args.strict)
    report(measured, checks, out, strict=args.strict)
    return EXIT_CLEAN if all(check.ok for check in checks) else EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover -- the CLI entry point.
    raise SystemExit(main())
