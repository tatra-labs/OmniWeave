"""`ow bench <subject>`: the closed set of thirteen, and the one subject P4 can actually measure.

12-performance.md section 7.1 names this file and the shape it has to have:

> `bench` is the verb and the second word is a **positional subject from a closed set**, which is
> how the charter already spells it (`ow bench scheduler | inproc | service | rss`) and which avoids
> inventing CLI verbs that are nouns. The registry is one function per subject in
> `packages/omniweave/src/omniweave/run/bench.py`, so adding a subject is one function plus one row
> in the closed set.

`SUBJECTS` is that closed set, all thirteen rows of section 7.1's table transcribed. Twelve of them
carry a `blocked_by` naming what they need and do not have; `scheduler` does not, and is here.

## Why the set is here and only one function is

16-roadmap.md:550 gives W4.10 `ow bench scheduler | inproc | service | rss` -- the charter's four.
Of those four, three cannot be measured by anything in this tree today and saying which is the
point of the registry:

| subject | what it needs | where that is |
|---|---|---|
| `scheduler` | a store, a roster, a loop, a no-op operator | all four are here |
| `inproc` | `fixtures/office-200` -- and nothing else | no cell in the plan produces it |
| `service` | 2,000 rendered pages and a model server | S3 landed at W4.9; the GPU card did not |
| `rss` | the 5,000-page PDF, the 4M-cell sheet, a 100k roster | two of three exist, and see below |

`rss` is the interesting absence. Its first clause is measured today by `tools/measure_store.py`
(`rss.gen5000p_peak_bytes`, printed INFORMATIONAL by CI) and its third by `tools/gate_scale.py`
(G22's supervisor RSS, which this module's `scheduler` harness feeds). Its second -- the 4M-cell
merge-free sheet -- has neither a fixture nor a reader. A subject that measured two of its three
clauses and reported one number would be worse than one that does not exist, so it does not exist
and `blocked_by` says which clause is missing.

## What `scheduler` measures, and the one thing it measures that G22 does not

Section 7.1's row: *"p50/p95/**p99** of claim, commit and total over **1M synthetic units** with a
no-op operator, on {NVMe, spinning disk, SMB}"*, writing B22 and **F8**, *"whose fallback is
widening group commit from zero-derived-row transitions to same-operator batches."*

`tools/gate_scale.py` already drives the same loop over the same synthetic corpus and reports
**means**: one claim cost 9.164 ms averaged over a 100,000-row run. F8's trigger is not a mean --
12-performance.md:153 states it as *"p95 > 1 ms"* -- and a mean cannot answer it, because the claim
this harness measures is `O(claimable)` (D190) and the claimable set oscillates between
`queue_low_water` and `queue_high_water` for the whole run. The distribution is the finding; the
mean is the middle of it.

So this module keeps every sample and the gate keeps sums, and the two are not a duplication: they
are a distribution and a budget check over the same instrument, which is why the instrument is here
and the gate imports it.

**The percentile is nearest-rank on the sorted samples**, stated because there are several
definitions and two harnesses using two of them would report two p99s for one run. `percentile()`
carries the arithmetic.

## `--storage` is a label and not a probe

Section 7.1 asks for the measurement *"on {NVMe, spinning disk, SMB}"*. Nothing here can tell which
of those it is running on: the medium is a property of a mount, `shutil.disk_usage` does not carry
it, and a guess recorded as a fact is worse than an `unknown`. So `storage` is a caller's label with
`unknown` as its default, it is carried on the result, and three media means three invocations. The
harness makes the three distinguishable afterwards; it does not pretend to detect one.

## What this module does NOT do

**It does not publish.** Section 7.4 makes the output an `eval_perf` row feeding
`eval/results/**.json`, and neither that table nor that tree exists -- `eval/` holds `gates.toml`,
`perf.toml` and `baselines/` and no results. Publishing into a schema that has not been written
would fix its shape by accident, so `SchedulerResult` is a value the caller renders and
`PUBLICATION` records the gap.

**It does not take the bench lock.** Section 7.2's limit 3 -- *"`ow bench` takes an exclusive
`flock` on `$OMNIWEAVE_HOME/bench.lock` and a second run **refuses with exit 7**"* -- is process
policy, and `tools/ow_bench.py` is the process. `omniweave_core.locks.FileScopedLock` already
raises `StoreBusy` (whose `EXIT` is 7) naming host, pid and age, so the runner composes two things
that exist rather than this module growing a third.

Specified in 12-performance.md sections 7.1, 7.2 and 7.4 and rows B22 and F8, 08-runtime.md:2715,
and 16-roadmap.md:550 (P4 W4.10).
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import math
import os
import socket
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core import acquire, locks
from omniweave_core.clock import SystemClock
from omniweave_core.errors import ConfigError, StoreError
from omniweave_core.operator import (
    CancelToken,
    Outcome,
    Producer,
    Roots,
    RunContext,
    StepResult,
    UnitRef,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.queue import SqliteStore

from omniweave.run import expand
from omniweave.run import supervisor as sup

if TYPE_CHECKING:  # pragma: no cover -- annotations only.
    from pathlib import Path

    from omniweave_core.clock import Clock
    from omniweave_core.work import WorkRow

__all__ = [
    "CACHE_KEY",
    "CHARTER_FOUR",
    "NOW_NS",
    "PRODUCER_POLL_MS",
    "PUBLICATION",
    "SHIPPED_MIGRATIONS",
    "STORAGE_MEDIA",
    "SUBJECTS",
    "SWEEP_MS",
    "URI_FORMAT",
    "Samples",
    "SchedulerResult",
    "Series",
    "Subject",
    "claim_batch_of",
    "identify_rows",
    "no_op",
    "open_store",
    "percentile",
    "run_context",
    "runnable",
    "scheduler",
    "synthetic_roster",
    "worker_identity",
]


# =============================================================================================
# 1. The closed set
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Subject:
    """One row of 12-performance.md section 7.1's table, plus whether this tree can run it.

    `measures`, `fixture` and `writes` are the table's three cells, transcribed rather than
    summarised: a registry that paraphrased its own specification would be a second statement of
    it, and section 7.1 is the one that governs.

    `blocked_by` is empty exactly when a function in this module implements the subject. It is not
    a TODO -- it names the thing that does not exist, so a reader who wants the measurement knows
    what has to land first rather than that somebody meant to get to it.
    """

    name: str
    measures: str
    fixture: str
    writes: str
    blocked_by: str = ""

    @property
    def runnable(self) -> bool:
        """Whether `bench.<name>()` exists here. The registry's only derived fact."""
        return not self.blocked_by


def _subject(
    name: str, measures: str, fixture: str, writes: str, blocked_by: str = ""
) -> tuple[str, Subject]:
    return name, Subject(
        name=name, measures=measures, fixture=fixture, writes=writes, blocked_by=blocked_by
    )


SUBJECTS: Final[Mapping[str, Subject]] = MappingProxyType(
    dict(
        (
            _subject(
                "pacer",
                "the Pacer workload alone, N times",
                "none",
                "the Runner's baseline; a Runner change is a baseline reset",
                blocked_by="the Pacer workload itself: [pacer] runner names ow-bench-1 and "
                "nothing in this tree defines the workload it runs",
            ),
            _subject(
                "cold",
                "import omniweave_core, ow --version, ow --help, discovery over 20 dists",
                "a synthetic dist-info tree",
                "import.omniweave_core_ms, cold.ow_version_ms, cold.ow_help_ms, "
                "discovery.20dists_ms, B31",
                blocked_by="`ow` itself: three of the four clauses time a CLI that is P7's "
                "(16-roadmap.md section 10). tools/gate_coldstart.py measures the first",
            ),
            _subject(
                "scheduler",
                "p50/p95/p99 of claim, commit and total over 1M synthetic units with a no-op "
                "operator, on {NVMe, spinning disk, SMB}",
                "generated",
                "B22; F8, whose fallback is widening group commit from zero-derived-row "
                "transitions to same-operator batches. Also the fixed-cost-amplification shape "
                "of section 3.6",
            ),
            _subject(
                "inproc",
                "wall, peak RSS and GIL-held fraction at max_inproc in {1,2,4,8} against the "
                "pure-Rust path",
                "fixtures/office-200",
                "B02/B03; F2, whose fallback is the anydoc fork trigger",
                blocked_by="fixtures/office-200, and ONLY that. packages/omniweave-office ships "
                "the driver, host/inproc.py ships the seam and [runtime] max_inproc is a declared "
                "key; the 200-document corpus 12 section 7.2 names has no generator and no "
                "roadmap cell that acquires it. See D196",
            ),
            _subject(
                "parse",
                "per-part decode at each Rung, by format and producer_family",
                "fixtures/gen/gen_5000p_pdf.py plus ten real 200-page documents",
                "B04, B23, store.bytes_per_block, F1, P-Q1",
                blocked_by="a real parse driver: tools/p2_stub_parse.py writes through DocSink "
                "with no driver host, so there is no Rung to decode at",
            ),
            _subject(
                "route",
                "evaluate() throughput, FREE and LOCAL signal cost per part, the ledger growth "
                "rate, and the route_decision count per document",
                "the same",
                "B05, B06, B07, P-Q3, P-Q7",
                blocked_by="route/evidence.py, route/eval.py and route/admit.py: W5.1-W5.3",
            ),
            _subject(
                "service",
                "throughput and queue_p95_ms for 2,000 pages at max_batch in {1,4,8,16} x "
                "batch_wait_ms in {0,5,25}, and the per-request p50/p95 wall at each point",
                "2,000 rendered pages",
                "B08, B09; F7, the missing Coalescing number, and the number that closes B09",
                blocked_by="a model server and a card: seam S3 landed at W4.9 and "
                "11-repo-layout.md section 6.5 puts this on ow-gpu-1, the one cell where "
                "omniweave-vision is installed",
            ),
            _subject(
                "embed",
                "per-Segment cost at batch in {1,8,32,64}, the query-time embed path, and the "
                "vseg signature scan at 50k/100k/200k/250k",
                "fixtures/store/",
                "B18-B21, B28, VEC_BRUTE_MAX",
                blocked_by="an encoder and fixtures/store/: [retrieval] vectors is off by "
                "default and nothing in this tree embeds",
            ),
            _subject(
                "query",
                "per-Channel and end-to-end p50/p95/p99 at 10k / 1M / 10M / 20M / 30M / 50M "
                "Blocks, vectors off and on, each scale measured after an FTS5 'merge'",
                "generated stores plus fixtures/store/golden-queries.jsonl",
                "query.warm_p50_ms, B26, B27; F50, P-Q8",
                blocked_by="the retrieval Channels and the golden query set",
            ),
            _subject(
                "encoding",
                "the owrows/1 saving per encoder id, with n and a ci95, against the "
                "eval/gates.toml floor",
                "the golden query set",
                "B36; F51",
                blocked_by="the golden query set and the tier-1 encoders",
            ),
            _subject(
                "incremental",
                "the B43 shape at roster sizes {1k, 10k, 100k} by edit shape, and F55's soak: "
                "10,000 successive single-document ingests into a 1M-block store",
                "a generated roster plus the 40 scripted mutations of G19's fixture",
                "B43; F34, F55, and section 6.7's freshness-scan term",
                blocked_by="lexical p50/p95, which needs the retrieval Channels. G19's fixture "
                "and its 40 mutations landed at W4.10 and are half of what this needs",
            ),
            _subject(
                "compile",
                "per-unit and whole-artefact compile, plus Toolchain spawn, per target",
                "the 40-unit golden OUT fixture",
                "B37-B40; P-Q2",
                blocked_by="09-generation.md's compile path, which is P6",
            ),
            _subject(
                "rss",
                "peak RSS on the 5,000-page PDF and the 4M-cell sheet, and supervisor RSS on a "
                "100k roster",
                "the two pathological fixtures",
                "rss.gen5000p_peak_bytes, rss.merged4mcell_peak_bytes, G22",
                blocked_by="the 4M-cell merge-free sheet, which has neither a fixture nor a "
                "reader. Its other two clauses are measured by tools/measure_store.py and "
                "tools/gate_scale.py; see this module's docstring for why two of three is not a "
                "subject",
            ),
        )
    )
)
"""12-performance.md section 7.1's thirteen rows. The set is CLOSED and this is the closure.

Section 7.1 states its own cardinality -- *"The thirteen above are the complete set"* -- and names
the six it adds beyond the charter's four plus the three other documents reference. A fourteenth
subject is a plan edit and not a function, which is what makes this a registry rather than a
dispatch table."""

CHARTER_FOUR: Final = ("scheduler", "inproc", "service", "rss")
"""The four the charter spells and 16-roadmap.md:550 gives W4.10. One of them runs; see `SUBJECTS`.

Kept as its own tuple because the roadmap line and section 7.1's table are two different claims --
"what this cell owes" and "what the verb accepts" -- and collapsing them would make the roadmap's
scope unreadable from here."""

STORAGE_MEDIA: Final = ("nvme", "spinning", "smb", "unknown")
"""Section 7.1's `{NVMe, spinning disk, SMB}` plus the honest default. See the module docstring."""

PUBLICATION: Final = (
    "12-performance.md section 7.4 publishes a bench through an `eval_perf` row into a committed "
    "`eval/results/**.json` tree, byte-diff gated. Neither exists: `eval/` holds gates.toml, "
    "perf.toml and baselines/ and no results, and no migration creates `eval_perf`. A result is "
    "returned as a value for the caller to render, and a number printed here reaches no scoreboard."
)
"""Why `scheduler()` returns a value instead of writing one. Printed by the runner, not a comment.

INV-19 is the reason this is a constant rather than a docstring line: *"publishing a number without
`(n, ci95, method, MeasuredOn, witness)` is a rejectable defect"*, and a harness that wrote into a
schema carrying none of those would make the first row the shape of every row after it."""


def runnable() -> tuple[str, ...]:
    """The subject names this module implements today, in `SUBJECTS` order."""
    return tuple(name for name, subject in SUBJECTS.items() if subject.runnable)


# =============================================================================================
# 2. Percentiles
# =============================================================================================


def percentile(ordered: Sequence[float], quantile: float) -> float:
    """The `quantile` of an ALREADY-SORTED sample, by NEAREST RANK. Empty is `nan`.

    Nearest rank -- `ceil(q x n)`, 1-indexed, clamped -- and not a linear interpolation, stated
    here because there are at least three definitions in common use and two harnesses using two of
    them would report two p99s for one run. Nearest rank also has the property that matters for
    F8's trigger: **every value it returns is a value that was actually observed**, so "p95 > 1 ms"
    names a claim that really took that long rather than a point between two that did not.

    `ordered` is not sorted here. Sorting a million-element array inside a property that a report
    reads three times is three sorts; `Series` sorts once at construction and says so.
    """
    count = len(ordered)
    if count == 0:
        return math.nan
    if not 0.0 < quantile <= 1.0:
        raise ValueError(f"quantile is in (0, 1]; got {quantile}")
    rank = math.ceil(quantile * count)
    return ordered[min(count, max(1, rank)) - 1]


@dataclass(frozen=True, slots=True)
class Series:
    """One measured quantity's samples, sorted once, with the percentiles section 7.1 asks for.

    **Every sample is kept, and the memory is stated rather than assumed away.** A million doubles
    in an `array("d")` is 8 MB; three series is 24 MB, against a supervisor ceiling of 600 MB that
    12-performance.md section 4.1 sets for the LOOP and not for a harness measuring it. The
    alternative -- a streaming estimator -- buys back 24 MB and gives up the exactness F8's
    threshold needs, and `12 section 4.5` already names `array` as the shape this codebase reaches
    for when it wants a flat typed buffer.

    Sorted at construction because `p50`, `p95` and `p99` are three reads of one order.
    """

    name: str
    unit: str
    sorted_samples: Sequence[float]

    @classmethod
    def of(cls, name: str, samples: Sequence[float], *, unit: str = "ms") -> Series:
        """Sort once. The only constructor callers should use."""
        return cls(name=name, unit=unit, sorted_samples=sorted(samples))

    @property
    def n(self) -> int:
        return len(self.sorted_samples)

    @property
    def p50(self) -> float:
        return percentile(self.sorted_samples, 0.50)

    @property
    def p95(self) -> float:
        return percentile(self.sorted_samples, 0.95)

    @property
    def p99(self) -> float:
        return percentile(self.sorted_samples, 0.99)

    @property
    def mean(self) -> float:
        return math.fsum(self.sorted_samples) / self.n if self.n else math.nan

    @property
    def total(self) -> float:
        """The sum. `math.fsum` and not `sum`: a million partial sums of milliseconds drift."""
        return math.fsum(self.sorted_samples)

    @property
    def worst(self) -> float:
        return self.sorted_samples[-1] if self.n else math.nan


class Samples:
    """`Store`'s four methods with every call's wall time kept. The distribution G22 sums.

    Structural, like `SqliteStore` itself: no inheritance edge, four methods, never widened. It
    forwards every call unchanged; what it adds is an `array("d")` per timed method.

    **Both series are LATENCIES and include time queued.** INV-17 makes the store thread *"the only
    holder of a `Connection` in a process"* (07:2722), so one claimer and `2 x max_workers`
    completions compete for one queue. That is the property F8 is about -- its fallback is *widening
    group commit*, which is a queueing remedy -- so measuring service time instead of latency would
    measure the wrong thing.

    **The clock is INJECTED and that is not only G8's rule.** `time.perf_counter` is banned in
    library code (02:392) and `clock.py` is the one module entitled to read the machine -- but the
    reason it is entitled is the one that matters here: `time.monotonic_ns()`, which the ban itself
    prescribes for durations, resolves to **15.6 ms on Windows**, coarser than every claim this
    class measures. `SystemClock` substitutes `perf_counter_ns` there and records the choice in
    `ClockFacts`, so an injected clock is both the compliant spelling and the only one that can see
    a one-millisecond claim on six of the nine test-matrix cells.
    """

    __slots__ = ("_clock", "_inner", "claim_rows", "claims", "commits", "counts", "reaps")

    def __init__(self, inner: SqliteStore, *, clock: Clock) -> None:
        self._inner = inner
        self._clock = clock
        self.claims = array.array("d")
        self.commits = array.array("d")
        self.claim_rows = 0
        self.reaps = 0
        self.counts = 0

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]:
        at = self._clock.monotonic_ns()
        rows = self._inner.claim(batch, gen, worker, lease_ms)
        self.claims.append((self._clock.monotonic_ns() - at) / 1e6)
        self.claim_rows += len(rows)
        return rows

    def complete(self, row_id: int, gen: int, result: object) -> bool:
        at = self._clock.monotonic_ns()
        committed = self._inner.complete(row_id, gen, result)  # type: ignore[arg-type]
        self.commits.append((self._clock.monotonic_ns() - at) / 1e6)
        return committed

    def reap_expired_leases(self, now_ms: int) -> int:
        self.reaps += 1
        return self._inner.reap_expired_leases(now_ms)

    def counts_by_status(self) -> Mapping[str, int]:
        self.counts += 1
        return self._inner.counts_by_status()


# =============================================================================================
# 3. The synthetic corpus: one `unit` row and one `op.identify` row per unit
# =============================================================================================

NOW_NS: Final = 0
"""The migration ledger's timestamp. Injected because `time.time` is banned (02:392), and fixed so
two runs' ledgers are byte-identical -- which costs nothing and removes one reason a store differs.
"""

SHIPPED_MIGRATIONS: Final = 4
"""`0001`-`0004`. Asserted rather than assumed: a store one migration short would claim out of a
`work` table with no `work_claimable` partial index, and the bench would report an index scan."""

URI_FORMAT: Final = "file:///scale/{index:06d}.bin"
CACHE_KEY: Final = "c" * 64
"""`work.cache_key` for every row. Recorded, never computed: `expand.identify_key()` is the real
producer and needs a `RunContext` and a per-unit salt. A harness that computed a million real cache
keys would be measuring `cache_key()` inside a number about the scheduler."""

SWEEP_MS: Final = 250
"""`[runtime] deferred_sweep_ms` for a bench run, against the shipped 5,000.

It is also `_settle()`'s quiet-pass interval, so `QUIET_POLLS_BEFORE_SHED + 1` empty claims end the
run after ~750 ms rather than ~15 s. A bench that ended because its producer was six seconds behind
would be measuring the gap and not the loop; `scheduler()` refuses a short run rather than
reporting one."""

PRODUCER_POLL_MS: Final = 50
"""How often a paused producer re-reads the claimable set, waiting for `queue_low_water`. Small
against `SWEEP_MS`, so a resume is never what the distribution measures."""


def synthetic_roster(count: int, *, generation: int) -> Iterator[acquire.RosterRow]:
    """`count` synthetic `unit` rows in the `discovered` state, one at a time.

    A generator and not a list: 12-performance.md section 3.4 prices a 100,000-row roster at 22 MB
    IN THE STORE, and `write_roster` consuming lazily is what keeps it out of the process. A
    harness that built the list first would put those megabytes into a number about the loop.

    Every row carries the same size and stat triple, which is the one place this is unlike a
    corpus: nothing here re-walks, so the values only have to be legal. `TrustClass` has no
    "synthetic" member and one is not invented -- a fabricated value in a real column is a value
    nothing else can read.
    """
    for index in range(count):
        yield acquire.RosterRow(
            unit_uri=URI_FORMAT.format(index=index),
            cursor=None,
            stat=acquire.StatTriple(size=1024, mtime_ns=0, indexed_at_ns=0),
            trust_class=acquire.TrustClass.INTERNAL,
            last_seen_gen=generation,
        )


def identify_rows(count: int) -> Iterator[Mapping[str, object]]:
    """`count` `op.identify` parameter sets for `expand.IDENTIFY_INSERT_SQL`, one at a time.

    `expand.row_params()` builds each, so every column but the uri and the key is the operator's own
    constant and this function chooses none of them. Lazy because `enqueue()` breaks out of its loop
    on a pause and is handed the SAME iterator on the next pass: a list would need an index the
    caller maintained, and an iterator carries its own.
    """
    for index in range(count):
        yield expand.row_params(URI_FORMAT.format(index=index), CACHE_KEY)


def open_store(root: Path) -> Path:
    """Create the `.owstore` under `root`, apply the four migrations, return its path."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "index.owstore"
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        if len(applied) != SHIPPED_MIGRATIONS:
            raise StoreError(
                f"the bench fixture applied {len(applied)} migrations and the shipped set is "
                f"{SHIPPED_MIGRATIONS}",
                fix="ow store migrate",
            )
    finally:
        connection.close()
    return path


def worker_identity() -> str:
    """`'<host>:<pid>:<process_create_time>'` -- 08:465's `claimed_by`, composed from its parts.

    `Supervisor.__init__` takes this as a parameter *"because `omniweave_core.locks` already owns
    that string's construction"*. What `locks` exports is the third component
    (`process_create_time(pid)`) and the triple as a dataclass; the colon-joined spelling the `work`
    table stores has no function anywhere, so this composes it from the parts rather than inventing
    a third source for an identity.
    """
    created, _source = locks.process_create_time(os.getpid())
    return f"{socket.gethostname()}:{os.getpid()}:{created}"


def no_op(batch: object) -> Sequence[StepResult]:
    """`Outcome.OK` for every row in `batch`. 12-performance.md:1470's operator, verbatim.

    *"1M synthetic units with a no-op operator"* -- the dispatcher a scheduler measurement takes,
    because any real one would put a parser's variance into a number about the loop. It still
    builds a full `StepResult` per row: `Store.complete()` reads `outcome`, `cache_key`, `identity`
    and `metrics` off it and writes a real transition, so what is cheap here is the WORK and not
    the answer.
    """
    rows: Sequence[WorkRow] = batch.rows  # type: ignore[attr-defined]
    return [
        StepResult(
            outcome=Outcome.OK,
            unit=UnitRef(
                uri=row.unit_uri, part=row.unit_part, content_sha256="b" * 64, byte_len=1024
            ),
            identity=Producer(
                operator=row.operator, op_version=row.op_version, code_fingerprint="f" * 64
            ),
            cache_key=CACHE_KEY,
        )
        for row in rows
    ]


def run_context(
    config: object,
    admission: sup.Admission,
    root: Path,
    *,
    generation: int = 1,
    clock: Clock | None = None,
) -> RunContext:
    """A real `RunContext`: frozen, `slots=True`, every field supplied.

    Four are `None` and the type system is what makes that legible rather than sloppy: `limits`,
    `services`, `budget` and `events` are the fields the loop does not read, and plausible stubs for
    them would claim a coverage this harness does not have.

    `clock` defaults to a fresh `SystemClock` and a caller measuring durations should pass ITS OWN:
    two `SystemClock`s resolve the same source but a duration spanning both is a difference of two
    arbitrary origins, which `SystemClock`'s own docstring calls meaningless.
    """
    clock = SystemClock() if clock is None else clock
    run_id = "r_0000000000000000000000000"
    return RunContext(
        run_id=run_id,
        generation=generation,
        trigger="cli",
        roots=Roots(source=root, output=root, cache=root),
        config_digest=str(config.config_digest),  # type: ignore[attr-defined]
        semantic_digest=str(config.semantic_digest),  # type: ignore[attr-defined]
        policy_digest="p" * 64,
        pricebook_digest="b" * 64,
        catalog_digest="k" * 64,
        limits=None,  # type: ignore[arg-type]
        admission=admission,  # type: ignore[arg-type]
        services=None,  # type: ignore[arg-type]
        budget=None,  # type: ignore[arg-type]
        cancel=CancelToken("run", run_id, clock),
        clock=clock,
        events=None,  # type: ignore[arg-type]
    )


def claim_batch_of(config: object) -> Mapping[str, int]:
    """`[runtime.claim] batch` as `{cost_class: int}`. Refuses a shape `_next_width` cannot read."""
    raw = config.get("runtime.claim.batch")  # type: ignore[attr-defined]
    if not isinstance(raw, Mapping):
        raise ConfigError(
            f"[runtime.claim] batch is {type(raw).__name__} and must be a table keyed by cost "
            f"class; supervisor.py's `_table` refuses the same shape for the same reason",
            fix="set runtime.claim.batch = { free = .., local_compute = .., billed_api = .. }",
        )
    return {str(name): int(value) for name, value in raw.items()}  # type: ignore[call-overload]


def claimable(counts: Mapping[str, int]) -> int:
    """The claimable set: `pending` + `failed_transient`, which is `CLAIM_SQL`'s own predicate.

    08:127-131 and `work_claimable`'s partial index carry the same two statuses. `deferred` is
    deliberately absent: a deferred row waits on the sweeper and is not claimable, so counting it
    would let a stalled budget read as a full queue and pause the producer for the rest of the run.
    """
    return counts.get("pending", 0) + counts.get("failed_transient", 0)


class Producing:
    """`expand.enqueue` behind the `PauseGate`, resumed by polling. 08:880's `expander`.

    The real producer is pulled by a discoverer that already holds the gate between roster batches;
    this one has no discoverer, so a paused pass waits `PRODUCER_POLL_MS` and asks again. What is
    NOT re-implemented is the pause: the predicate is `PauseGate.__call__`, the boundary is
    `enqueue`'s own post-commit check, and neither is spelled twice.

    **`stream()` waits BEFORE it enqueues**, and the ordering is a defect a 100,000-row run found:
    the first pass runs before the loop opens and stops at `queue_high_water`, so a task that
    enqueued first committed another `plan_batch` rows unasked -- `enqueue` checks the pause after a
    commit, never before one -- and the claimable set stood at `high_water + 2 x plan_batch` before
    anything asked whether it should.
    """

    __slots__ = ("_emit", "_gate", "_plan_batch", "_rows", "_thread", "paused", "written")

    def __init__(
        self,
        thread: ow.StoreThread,
        rows: Iterator[Mapping[str, object]],
        *,
        gate: sup.PauseGate,
        plan_batch: int,
        emit: Callable[..., object] | None = None,
    ) -> None:
        self._thread = thread
        self._rows = rows
        self._gate = gate
        self._plan_batch = plan_batch
        self._emit = emit
        self.written = 0
        self.paused = 0

    def pass_once(self) -> bool:
        """One `enqueue` call. True iff it stopped at the high-water mark.

        `plan_batch` is PASSED and not left to `enqueue`'s default: the pause is checked between
        transactions, so the batch size IS the resolution of the water mark, and a harness that
        measured the default while reporting the configured value would be reporting a knob it had
        not used.

        `emit` is optional and `None` here: `enqueue` fires `plan.expand` per transaction, which a
        caller counting events wants and a caller measuring percentiles does not. `scheduler()`
        passes nothing; `tools/gate_scale.py` passes a counter.
        """
        written, paused = expand.enqueue(
            self._thread,
            self._rows,
            pause=self._gate,
            plan_batch=self._plan_batch,
            emit=self._emit,
        )
        self.written += written
        self.paused += 1 if paused else 0
        return paused

    async def stream(self, cancelled: Callable[[], bool]) -> None:
        """Wait while the gate says paused, then enqueue. Until the roster or the run runs out.

        The cancel check is at the loop top, 08:349's rule for every loop in the runtime: a
        producer still writing rows after the Supervisor shed the run is enqueueing work for a
        generation that has stopped claiming.
        """
        while not cancelled():
            while not cancelled() and await asyncio.to_thread(self._gate):
                await asyncio.sleep(PRODUCER_POLL_MS / 1000)
            if cancelled() or not await asyncio.to_thread(self.pass_once):
                return


# =============================================================================================
# 4. `ow bench scheduler`
# =============================================================================================


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    """What one `ow bench scheduler` run produced. A value: see `PUBLICATION`."""

    units: int
    storage: str
    completed: int
    status: str
    batches: int
    pauses: int
    roster_s: float
    enqueue_s: float
    drain_s: float
    claim: Series
    commit: Series
    claim_rows: int
    claim_width: int
    high_water: int
    low_water: int
    plan_batch: int
    workers: Mapping[str, int]
    inflight: Mapping[str, int]
    claim_batch: Mapping[str, int]
    cpus: int

    @property
    def transitions_per_s(self) -> float:
        return self.completed / self.drain_s if self.drain_s > 0 else math.nan

    @property
    def ms_per_transition(self) -> float:
        """The TOTAL of section 7.1's "claim, commit and total": one transition's wall cost.

        Wall and not `claim.mean + commit.mean`. The two overlap -- one claimer against
        `sum(max_workers)` committers -- so adding their means would double-count the overlap and
        under-count the queueing that INV-17's single store thread imposes on both.
        """
        return self.drain_s * 1e3 / self.completed if self.completed else math.nan

    @property
    def rows_per_claim(self) -> float:
        """Rows returned per claim statement issued. 1.0 means every row paid a whole one -- D191.

        The denominator counts the claimer's EMPTY claims too: it issues
        `QUIET_POLLS_BEFORE_SHED + 1` of them before deciding the run is over, and they are
        statements that returned nothing. Three of them against a million units is invisible and
        against forty is seven per cent, so this is a figure to read at scale and the mechanism it
        describes is asserted directly in `test_run_bench.py`.
        """
        return self.claim_rows / self.claim.n if self.claim.n else math.nan

    @property
    def claim_share(self) -> float:
        """The fraction of the drain's wall clock spent inside `Store.claim`.

        Meaningful because the claimer is ONE coroutine: 08:2478's wider claim would take a cost
        class and could run one per class, and the narrow four-parameter form that ships cannot. So
        this is a share of the run and not a share of some total CPU.
        """
        return (self.claim.total / 1e3) / self.drain_s if self.drain_s > 0 else math.nan


async def scheduler(
    root: Path,
    *,
    units: int,
    config: object,
    storage: str = "unknown",
    generation: int = 1,
    clock: Clock | None = None,
) -> SchedulerResult:
    """`ow bench scheduler`: drive `units` synthetic units through the loop, keep every sample.

    The run is the real one: `acquire.write_roster` for the roster, `expand.enqueue` behind
    `Supervisor.pause_gate()` for the work rows, `SqliteStore` for the queue and `Supervisor` for
    the drain. `no_op` is the operator and is the only synthetic part.

    **The first enqueue pass runs before the loop opens.** It pauses at `queue_high_water`, so the
    claimable set is at its working depth before the first claim -- which is the depth the
    distribution is about, since a claim is `O(claimable)` (D190) -- and it removes a race in which
    the claimer's three quiet polls could end the run before the producer's first transaction
    committed.

    Refuses rather than reports on a run that did not finish: a partial drain has a wall time and a
    completion count and therefore a transitions/s, and that number is about a run that stopped.

    ONE clock for the whole run -- the samples', the phase timings' and the `RunContext`'s -- so
    every duration is a difference of two readings from one origin.
    """
    if units < 1:
        raise ValueError(f"units is {units}; a bench over no units is not a bench")
    if storage not in STORAGE_MEDIA:
        raise ValueError(f"storage is one of {STORAGE_MEDIA}; got {storage!r}")

    ticking = SystemClock() if clock is None else clock
    path = open_store(root)
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
    batch_widths = claim_batch_of(config)
    plan_batch = int(config.get("runtime.plan_batch"))  # type: ignore[attr-defined]

    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        at = ticking.monotonic_ns()
        acquire.write_roster(thread, synthetic_roster(units, generation=generation))
        roster_s = (ticking.monotonic_ns() - at) / 1e9

        queue = Samples(SqliteStore(thread, wait_ms=locks.BATCH_WAIT_MS), clock=ticking)
        context = run_context(config, admission, root, generation=generation, clock=ticking)
        gate = sup.PauseGate(lambda: claimable(queue.counts_by_status()), admission=admission)
        producer = Producing(thread, identify_rows(units), gate=gate, plan_batch=plan_batch)

        at = ticking.monotonic_ns()
        still_going = await asyncio.to_thread(producer.pass_once)
        enqueue_s = (ticking.monotonic_ns() - at) / 1e9

        supervisor = sup.Supervisor(
            context,
            queue=queue,  # type: ignore[arg-type]
            dispatch=no_op,  # type: ignore[arg-type]
            admission=admission,
            timings=timings,
            worker=worker_identity(),
            claim_batch=batch_widths,
        )
        streaming = (
            asyncio.create_task(producer.stream(context.cancel.cancelled)) if still_going else None
        )
        at = ticking.monotonic_ns()
        report = await supervisor.run()
        drain_s = (ticking.monotonic_ns() - at) / 1e9
        if streaming is not None:
            streaming.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await streaming

    if report.status != "done" or report.completed != units:
        raise StoreError(
            f"the bench run ended {report.status!r} with {report.completed:,} of {units:,} rows "
            f"completed; a distribution over a partial drain is not one",
            fix="run again on a quiet machine, or lower --units",
        )

    return SchedulerResult(
        units=units,
        storage=storage,
        completed=report.completed,
        status=report.status,
        batches=report.batches,
        pauses=producer.paused,
        roster_s=roster_s,
        enqueue_s=enqueue_s,
        drain_s=drain_s,
        claim=Series.of("Store.claim", queue.claims),
        commit=Series.of("Store.complete", queue.commits),
        claim_rows=queue.claim_rows,
        claim_width=max(1, min(batch_widths.values(), default=1)),
        high_water=admission.high_water,
        low_water=admission.low_water,
        plan_batch=plan_batch,
        workers=dict(admission.workers),
        inflight=dict(admission.inflight),
        claim_batch=batch_widths,
        cpus=host.cpus,
    )
