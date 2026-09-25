"""The one asyncio loop, and the derivation of every degree of parallelism it is allowed to spend.

02-architecture.md:71 names this file twice in two lines -- *"ONE asyncio loop: claim -> admit ->
dispatch -> complete -> reap; TaskGroup for STRUCTURED SHUTDOWN ONLY"* -- and section 2.1 of
08-runtime.md gives it everything the loop is bounded by.

Section 2.1 states that second subject in one sentence -- *"Every degree of parallelism is derived
at preflight from the machine and clamped by config; none is a shipped constant except the
ceilings"* -- and then prints `HostFacts`, `derive_admission` and `ram_required` as code. This
module is that block, plus section 2.5's two backpressure decisions -- `producer_should_pause`'s
hysteresis and `stall_detector`'s predicate -- plus the loop that holds all of them.

## What this file is

16-roadmap.md:542 gives W4.2 six things and all six are here. They landed in two cells, and the
order was forced rather than chosen.

**The first half shipped alone** because the loop needs three types that did not exist: `RunContext`
(08-runtime.md:265, `omniweave_core.operator`), `Batch` and `DriverHost.invoke(Batch)`
(02-architecture.md:238, `omniweave/run/dispatch.py`, W4.7), and the durable `budget_reservation`
ledger (W4.5). Writing a loop against three fabricated types would have been the `route_decision`
mistake 16-roadmap.md:541 names in W4.1's own estimation basis, one cell later. What was shippable
was everything that is a pure function of `(Config, HostFacts)` or of a `counts_by_status()`
reading -- the whole of the admission derivation and both backpressure decisions -- and the three
worked machines of 08:727-731 are a parity test on it rather than an illustration.

**The second half is section 6**: one asyncio loop, one `TaskGroup` for structured shutdown, four
watchers and a fixed set of `worker_loop`s. `Supervisor`'s docstring is its argument.

## Two imports are deferred, and the numbers are why

`omniweave/run/__init__.py` re-exports this module's arithmetic, and its own docstring makes a cost
argument about doing so: *"Re-exporting its names would make `from omniweave.run import Admission`
-- which is a pure arithmetic over `(Config, HostFacts)` -- pay for a driver host."* A loop in the
same module can defeat that from the other side, so the two that cost are imported at function
scope and the two that do not are not. Marginal cost of each, measured after `import omniweave.run`
on this workspace's interpreter:

| module | marginal | where |
|---|---|---|
| `omniweave_core.operator` | ~39 ms | function scope -- `CancelReason`, `Outcome`, the entropy |
| `omniweave.run.dispatch` | ~16 ms | function scope -- `form_batches`, `new_invoke_id` |
| `omniweave_core.events` | ~5 ms | module scope |
| `omniweave_core.observe.degradation` | ~2 ms | module scope |

Deferring the two keeps `from omniweave.run import Admission` at what it cost before the loop
landed; deferring the other two would be four more `noqa`s for 7 ms. `RunContext`, `StepResult`,
`Store`, `WorkRow`, `Batch` and `DegradationKind` are annotations only, so they are
`TYPE_CHECKING`-only and cost nothing at all.

## The four semaphore families, and why they are four

| family | bounds | unit |
|---|---|---|
| `class_sem` | `[budget] max_inflight` | **units** in flight per cost class |
| `worker_sem` | `[drivers] max_workers` | worker **processes** per cost class |
| `render_sem` | `max(1, cpus - 2)` | concurrent CPU rasterisations, process-wide |
| `service_sem` | refilled per section 3.4 | in-flight requests per model Service |

`class_sem` and `worker_sem` count different things and 08:689 is explicit: *"These count UNITS,
not processes: one worker process may hold a Batch of 256."* Collapsing them would make a batch of
256 look like 256 workers.

**`render_sem` is not `service_sem`, and olmocr is the receipt.** `pipeline.py:87-88` holds two
`asyncio.BoundedSemaphore`s and pushes CPU render through `asyncio.to_thread` at `:112`; 08:674-676
gives the number behind keeping them apart: *"at 10.7 MB per rendered 192-DPI page, one shared
semaphore renders faster than it evicts."* A page rasterised while the GPU queue is full is 10.7 MB
of resident memory waiting for a slot.

**`BILLED_API` is deliberately absent from the family that matters** (08:739-743). Its real
admission is the durable `budget_reservation` ledger, *"because two scheduler processes each
holding an in-memory semaphore of 2 show the provider 4"*. `class_sem[BILLED_API]` still exists and
still bounds this process; it is simply not the authority, and this module says so rather than
letting a reader infer a guarantee from a semaphore that cannot give one.

## RAM is a refusal, not a clamp

`ram_required` returns bytes and decides nothing; `check_ram` turns it into the verdict
`ow doctor --runtime` prints. 08:703-705 is the reason it is not a clamp: *"A silent clamp would
hide the fact that the chosen driver roster does not fit the machine."* The container row of
08:731 is the whole argument -- `os.process_cpu_count()` sees eight CPUs inside a 4 GB cgroup, the
derivation admits four `local_compute` workers, and 11.1 GB of declared `memory_mb` does not fit.
A clamp would have made an operator's `max_workers = 4` a lie recorded nowhere.

## The stall that looks like health

08:892-897 names the failure hysteresis alone does not cover: a full claimable set with nothing
admissible. Fifty thousand rows, every one of them `billed_api` against an exhausted cap or owned
by a quarantined driver. *"Nothing drains, nothing fails, no event fires"*, and
15-observability.md section R2 records the symptom exactly -- *"work rows are `deferred`, which is
an `Outcome`, not a failure, so nothing is red."*

`stall_verdict()` is that predicate as a pure function over two polls. Four conjuncts, and each one
is load-bearing: claimable > 0 (there is work), claimed == 0 (nothing is running), no completion
since the previous poll, and the sweeper returned nothing. 08:915-916 requires **two** poll cycles
and the `claimed == 0` conjunct together, *"so a single slow 200-page document cannot trip it"*.

Specified in 08-runtime.md sections 1.2, 2.1, 2.5, 2.6 and 8, 02-architecture.md sections 5.1, 5.3
and 5.4, and 16-roadmap.md:542 (P4 W4.2).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import socket
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, Protocol, cast

from omniweave_core.errors import ConfigError, RouteError, StoreError
from omniweave_core.events import EventKind
from omniweave_core.observe.degradation import Degradation

if TYPE_CHECKING:
    from omniweave_core.observe.degradation import DegradationKind
    from omniweave_core.operator import CancelReason, RunContext, StepResult
    from omniweave_core.store import Store
    from omniweave_core.work import WorkRow

    from omniweave.run.dispatch import Batch

__all__ = [
    "COST_CLASSES",
    "CRASH_DEGRADATION_KIND",
    "LAG_DEGRADATION_KIND",
    "LOOP_LAG_SAMPLE_MS",
    "QUIET_POLLS_BEFORE_SHED",
    "RAM_HEADROOM_FRACTION",
    "RENDER_CPU_RESERVE",
    "Admission",
    "Dispatcher",
    "HostFacts",
    "LoopTimings",
    "PauseGate",
    "RamVerdict",
    "RunReport",
    "StallVerdict",
    "Supervisor",
    "Sweeper",
    "check_ram",
    "claim_batch_of",
    "derive_admission",
    "no_emit",
    "no_sweep",
    "producer_should_pause",
    "ram_required",
    "stall_verdict",
    "worker_identity",
]

COST_CLASSES: Final[tuple[str, ...]] = ("free", "local_compute", "billed_api")
"""The three, in `omniweave_ports.types.CostClass`'s own order.

Strings rather than the enum for the same reason `store/queue.py` keeps `OUTCOMES` as a tuple: the
config keys `[drivers] max_workers` and `[budget] max_inflight` are inline tables whose KEYS are
these three spellings, `Config.get` returns them as a `Mapping[str, object]`, and a derivation that
converted to the enum and back would be two conversions around an arithmetic. A `StrEnum` member
compares and hashes equal to its value, so a caller holding `CostClass.FREE` indexes these mappings
without a cast."""

RENDER_CPU_RESERVE: Final = 2
"""`render = max(1, cpus - 2)`. olmocr `pipeline.py:87`, adopted verbatim (08:672-677).

Two, not one and not a fraction: the loop itself needs a CPU and so does the store thread, and both
are doing work that a rasteriser starving them would make slower overall. `max(1, ...)` is what
keeps a single-core container rendering at all rather than dividing by zero into a deadlock."""

QUIET_POLLS_BEFORE_SHED: Final = 2
"""08:915: *"Two poll cycles are required before the run ends."*

Named rather than written into the comparison because it is one half of a pair -- the other half
is the `claimed == 0` conjunct -- and 08:916 gives what the pair buys: *"so a single slow 200-page
document cannot trip it."* One poll would end a run whose only unit is a document that takes
longer than `stall_poll_ms` to parse."""

RAM_HEADROOM_FRACTION: Final = 0.8
"""`ow doctor --runtime` REFUSES above 0.8x `host.ram_bytes` (08:703-705).

The fifth of the machine this leaves is not a safety margin for the drivers -- their declared
`[isolation] memory_mb` is already in `ram_required`'s sum. It is the page cache, the store's WAL,
the interpreter and whatever else the operator is running, none of which appear in any card."""


@dataclass(frozen=True, slots=True)
class HostFacts:
    """The machine, measured ONCE at preflight. 08:659-667, field for field.

    08:661-662 gives the reason it is a recorded value rather than a set of calls made where they
    are needed: *"Measured ONCE at preflight and recorded in the run manifest, so a performance
    number is attributable to a machine."* A derivation that called `os.process_cpu_count()` twice
    could produce two different admissions in one run, and the manifest would record neither.
    """

    cpus: int
    ram_bytes: int
    free_disk_bytes: int
    gpus: tuple[tuple[str, int], ...] = ()
    is_container: bool = False

    @classmethod
    def measure(cls, cache_root: Path) -> HostFacts:
        """Read the machine. The only function in this module that touches the environment.

        The CPU count is `_cpus()`'s three-rung ladder rather than one call; its docstring carries
        the reason, which is that the function 08:663 names does not exist on two of the three
        Pythons this workspace supports.

        **`gpus` is empty here and that is a scope boundary, not a stub.** Enumerating devices
        means importing a vendor runtime, and 02-architecture.md makes the model server (seam S3,
        W4.9) the only component allowed to do that. A caller that has the facts supplies them;
        `derive_admission` reads no GPU field, because none of the four semaphore families is
        sized from one -- `service_sem` is refilled from a Service's measured capacity (08
        section 3.4) and not from VRAM.
        """
        usage = shutil.disk_usage(cache_root)
        return cls(
            cpus=_cpus(),
            ram_bytes=_ram_bytes(),
            free_disk_bytes=usage.free,
            gpus=(),
            is_container=_is_container(),
        )


def _cpus() -> int:
    """The CPUs this PROCESS may use. A three-rung ladder, and the ladder is a defect report.

    08:663 prescribes one call: `cpus: int  # os.process_cpu_count() -- respects cgroup +
    affinity`. **`os.process_cpu_count()` was added in Python 3.13**, and this workspace's floor
    is 3.11 -- `target-version = "py311"`, and the `test` matrix runs 3.11, 3.12 and 3.13
    (11-repo-layout.md section 6.2). On two of the three cells the prescribed call raises
    `AttributeError`, which would make the Supervisor unconstructible there. Filed; the ladder is
    what ships meanwhile, and it preserves the intent rather than the spelling:

    1. `os.process_cpu_count()` -- 3.13+, and 08:663's own answer where it exists.
    2. `len(os.sched_getaffinity(0))` -- Linux on 3.11/3.12, which is the affinity half exactly.
       It is what `process_cpu_count` itself calls on Linux, so rung 2 and rung 1 agree.
    3. `os.cpu_count()` -- macOS and Windows on 3.11/3.12, where neither of the first two exists.
       This rung does NOT respect affinity, and saying so is the point: a run pinned to two cores
       on a 3.12 macOS box derives the box's count and over-admits. The manifest records
       `HostFacts` so the number is at least attributable.

    **No rung reads a cgroup quota, including 08:663's own.** `os.process_cpu_count()` respects
    `sched_setaffinity`, not `cpu.max`; the container row of 08:731 is built on that -- it says
    `os.process_cpu_count()` sees eight CPUs inside a 4 GB container, and it is the RAM refusal
    rather than the CPU derivation that catches it. The comment in the plan reads "cgroup +
    affinity" and only the second is true of the function it names. Filed with the version gap.
    """
    process_cpu_count = getattr(os, "process_cpu_count", None)
    if process_cpu_count is not None:
        return max(1, process_cpu_count() or 1)
    sched_getaffinity = getattr(os, "sched_getaffinity", None)
    if sched_getaffinity is not None:
        return max(1, len(sched_getaffinity(0)))
    return max(1, os.cpu_count() or 1)


def _ram_bytes() -> int:
    """Physical RAM, or 0 when the platform will not say.

    `os.sysconf` carries it on Linux and macOS and does not exist on Windows, where the answer
    needs `ctypes` into `GlobalMemoryStatusEx`. Zero rather than a guess: `check_ram` reads a zero
    as "unknown" and reports that it could not decide, which is a different answer from "it fits".
    A fabricated number here would make the refusal 08:703 asks for either vacuous or wrong.
    """
    sysconf = getattr(os, "sysconf", None)
    if sysconf is None:  # Windows: the answer needs ctypes into GlobalMemoryStatusEx.
        return 0
    try:
        pages = sysconf("SC_PHYS_PAGES")
        page_size = sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return 0
    return int(pages) * int(page_size) if pages > 0 and page_size > 0 else 0


def _is_container() -> bool:
    """A cgroup v2 memory limit, or the marker file every container runtime leaves.

    It is recorded rather than acted on: nothing in `derive_admission` branches on it. What it is
    for is the manifest, so that 08:731's container row -- eight visible CPUs inside a 4 GB limit
    -- is legible in a performance report rather than inferred from a ratio.
    """
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


@dataclass(frozen=True, slots=True)
class Admission:
    """The four semaphore families and the two water marks. 08:693-700's constructor call.

    Frozen: the derivation runs once at preflight and the semaphores are the ones the loop holds
    for the rest of the run. Rebinding a family mid-run would leave coroutines waiting on a
    semaphore nothing releases, which is a hang rather than a mis-tuning.
    """

    class_sem: Mapping[str, asyncio.BoundedSemaphore]
    worker_sem: Mapping[str, asyncio.BoundedSemaphore]
    render_sem: asyncio.BoundedSemaphore
    service_sem: Mapping[str, asyncio.BoundedSemaphore] = field(default_factory=dict)
    high_water: int = 50_000
    low_water: int = 25_000
    workers: Mapping[str, int] = field(default_factory=dict)
    """The derived `[drivers] max_workers` per class -- the integers `worker_sem` was built from.

    A `BoundedSemaphore` will not say what it was constructed with (`_value` is private and moves),
    and three callers need the number rather than the permit: `ram_required()` multiplies it by the
    roster's declared `memory_mb`, the manifest records it because 08:661 makes `HostFacts`
    *"recorded in the run manifest, so a performance number is attributable to a machine"* and a
    derivation nobody can read is half of that, and the loop sizes its fixed worker set from the
    sum. Keeping it is what stops each of the three from re-deriving it and disagreeing."""
    inflight: Mapping[str, int] = field(default_factory=dict)
    """The derived `[budget] max_inflight` per class -- the integers `class_sem` was built from.

    `_ClassGate` needs it and cannot ask the semaphore: 08:687 makes this family count UNITS, so a
    batch takes as many permits as it has rows, and the clamp that keeps that from waiting forever
    is `min(rows, bound)`. A gate that guessed the bound would either deadlock or under-admit."""

    def __post_init__(self) -> None:
        if self.low_water >= self.high_water:
            raise ConfigError(
                f"queue_low_water ({self.low_water}) must be below queue_high_water "
                f"({self.high_water}): one threshold is not hysteresis",
                fix="set [runtime] queue_low_water to about half of queue_high_water",
            )


def _table(cfg: object, key: str) -> Mapping[str, int]:
    """One inline-table config key as `{cost_class: int}`, with every class present.

    A missing class is a `ConfigError` and not a default, because the three defaults differ by an
    order of magnitude (`billed_api` is 2 units in flight against `free`'s 32) and inventing one
    here would silently admit thirty times the intended concurrency against a paid provider.
    """
    raw = cfg.get(key)  # type: ignore[attr-defined]
    if not isinstance(raw, Mapping):
        raise ConfigError(
            f"[{key}] is {type(raw).__name__} and must be a table keyed by cost class",
            fix=f"set {key} = {{ free = .., local_compute = .., billed_api = .. }}",
        )
    missing = [name for name in COST_CLASSES if name not in raw]
    if missing:
        raise ConfigError(
            f"[{key}] names no value for {', '.join(missing)}",
            fix=f"give {key} a row for every one of {', '.join(COST_CLASSES)}",
        )
    return {name: int(raw[name]) for name in COST_CLASSES}  # type: ignore[arg-type]


def derive_admission(cfg: object, host: HostFacts) -> Admission:
    """08:669-700, arithmetic for arithmetic. Pure: it reads `cfg` and `host` and nothing else.

    Three clamps and one that is deliberately absent:

    * `render = max(1, cpus - 2)` -- olmocr's, adopted verbatim.
    * `workers[free] = min(cfg, max(1, cpus - 1))` and
      `workers[local_compute] = min(cfg, max(1, cpus // 2))`. `billed_api` is **not** clamped by
      CPU count, because it is IO-bound: eight in-flight HTTP calls do not need eight cores.
    * `inflight[local_compute] = min(cfg, render)`. A local-compute unit that renders cannot
      outrun the rasteriser, so admitting more units than render slots buys queueing and nothing
      else. `free` and `billed_api` are not clamped this way -- a free parse does not rasterise.

    `omniweave_core.limits.MAX_AUTO_PARALLEL` bounds nothing here, and its ABSENCE is asserted
    rather than left to be noticed: 08:702 scopes that ceiling to the model server's
    `refill_target`, and a ceiling applied in two places is a ceiling nobody can reason about.
    """
    cpus = max(1, host.cpus)
    render = max(1, cpus - RENDER_CPU_RESERVE)

    configured_workers = _table(cfg, "drivers.max_workers")
    workers = {
        "free": min(configured_workers["free"], max(1, cpus - 1)),
        "local_compute": min(configured_workers["local_compute"], max(1, cpus // 2)),
        # IO-bound: 08:685 marks this row `# IO-bound` and applies no CPU clamp.
        "billed_api": configured_workers["billed_api"],
    }

    inflight = dict(_table(cfg, "budget.max_inflight"))
    inflight["local_compute"] = min(inflight["local_compute"], render)

    services = cfg.subkeys("services") if hasattr(cfg, "subkeys") else ()  # type: ignore[attr-defined]
    return Admission(
        class_sem={name: asyncio.BoundedSemaphore(inflight[name]) for name in COST_CLASSES},
        worker_sem={name: asyncio.BoundedSemaphore(workers[name]) for name in COST_CLASSES},
        render_sem=asyncio.BoundedSemaphore(render),
        workers=MappingProxyType(dict(workers)),
        inflight=MappingProxyType({name: inflight[name] for name in COST_CLASSES}),
        # Zero, and refilled per 08 section 3.4 from the Service's own measured capacity. A
        # semaphore opened at a guess would let the first batch through before the server has
        # said how much it can take.
        service_sem={name: asyncio.BoundedSemaphore(0) for name in services},
        high_water=int(cfg.get("runtime.queue_high_water")),  # type: ignore[attr-defined]
        low_water=int(cfg.get("runtime.queue_low_water")),  # type: ignore[attr-defined]
    )


def ram_required(workers: Mapping[str, int], memory_mb: Mapping[str, int]) -> int:
    """08:702-709. Summed over the three classes, `workers[c] * max(memory_mb)`, in BYTES.

    `memory_mb` is the per-class MAXIMUM of the enabled roster's declared `[isolation] memory_mb`,
    not its sum and not its mean: a worker process runs one driver at a time, so a class's worst
    case is its heaviest member, and a class with no enabled driver contributes zero.

    The catalog is a parameter rather than a lookup because this function is arithmetic and the
    roster is a decision. 08:707 writes it as `catalog.enabled_in(c)`; `Catalog` is the driver
    system's and the projection a caller passes is one dict comprehension over it.
    """
    total_mb = sum(workers[name] * memory_mb.get(name, 0) for name in COST_CLASSES)
    return total_mb * 1_048_576


@dataclass(frozen=True, slots=True)
class RamVerdict:
    """What `ow doctor --runtime` prints. Three states, and `unknown` is one of them."""

    verdict: str
    required_bytes: int
    ceiling_bytes: int
    detail: str

    @property
    def refuses(self) -> bool:
        return self.verdict == "refuse"


def check_ram(required_bytes: int, host: HostFacts) -> RamVerdict:
    """Above `0.8 * host.ram_bytes` this REFUSES, naming `[drivers] max_workers`.

    08:703-705: *"RAM is a REFUSAL, not a clamp ... A silent clamp would hide the fact that the
    chosen driver roster does not fit the machine."* The message names the knob because 08:735-737
    prints the operator's fix as an edit to that key, arithmetic included -- and a refusal whose
    message does not say what to change is a refusal the operator works around by raising a
    different number.

    A `ram_bytes` of zero is `unknown` and never `ok`: `_ram_bytes` returns zero where the
    platform will not answer, and reading that as "it fits" would make the refusal vacuous on
    exactly the platform where it was hardest to measure.
    """
    if host.ram_bytes <= 0:
        return RamVerdict(
            verdict="unknown",
            required_bytes=required_bytes,
            ceiling_bytes=0,
            detail=(
                "this platform does not report physical RAM through os.sysconf, so the "
                f"{required_bytes // 1_048_576} MB the enabled roster declares could not be "
                "checked against it"
            ),
        )
    ceiling = int(host.ram_bytes * RAM_HEADROOM_FRACTION)
    if required_bytes > ceiling:
        return RamVerdict(
            verdict="refuse",
            required_bytes=required_bytes,
            ceiling_bytes=ceiling,
            detail=(
                f"the enabled driver roster declares {required_bytes // 1_048_576} MB across its "
                f"worker processes, over {RAM_HEADROOM_FRACTION:.0%} of this machine's "
                f"{host.ram_bytes // 1_048_576} MB ({ceiling // 1_048_576} MB). Lower "
                f"[drivers] max_workers"
            ),
        )
    return RamVerdict(
        verdict="ok",
        required_bytes=required_bytes,
        ceiling_bytes=ceiling,
        detail=(
            f"{required_bytes // 1_048_576} MB required against a {ceiling // 1_048_576} MB ceiling"
        ),
    )


def producer_should_pause(claimable: int, admission: Admission, *, paused: bool) -> bool:
    """The water-mark hysteresis. 08:880 and :884-887.

    Two thresholds and not one, and `paused` is what makes it hysteresis rather than a comparison:
    a paused producer resumes only below `low_water`, and a running one pauses only above
    `high_water`. Between them the answer is *whatever it already was*, which is the entire
    mechanism.

    08:884-886 gives the failure a single threshold has: *"A single threshold makes the producer
    oscillate at the boundary and turns `plan.pause`/`plan.resume` into noise; the 2:1 gap means
    one pause drains 25,000 rows before discovery resumes."* The events are the observable cost --
    an operator watching a run flap between two states learns nothing from either.

    **It pauses; it never drops.** 08:875-876: *"none of them drops work except the event queue,
    which drops by design and says so."* The `enumerate` generator is simply not pulled, which is
    also why 08:886-887 makes a connector that buffers its whole enumeration in `__init__` a
    failure of the `acquire` conformance suite: such a connector has already done the work this
    would have deferred.
    """
    if paused:
        return claimable > admission.low_water
    return claimable > admission.high_water


@dataclass(frozen=True, slots=True)
class StallVerdict:
    """`stall_detector`'s answer for one poll. 08:899-916.

    `stalled` is the verdict; `blocker` is the dominant reason and is what selects the
    `Degradation.kind` the run ends with. 08:906-910 is explicit that the set is closed and this
    document adds nothing to it: `"budget"` when the dominant blocker is a denial, following
    05-ingest-and-routing.md section 6.4's precedent of reusing `budget` for a cost-class clamp
    rather than inventing a member, and `"quarantine"` when it is a quarantined driver.
    """

    stalled: bool
    reason: str
    blocker: str = ""

    @property
    def degradation_kind(self) -> str:
        return self.blocker


def stall_verdict(
    counts: Mapping[str, int],
    *,
    completions_since_last_poll: int,
    swept: int,
    consecutive_quiet_polls: int,
    dominant_blocker: str = "budget",
) -> StallVerdict:
    """Four conjuncts and a two-poll requirement. Pure, so it is testable without a clock.

    08:901-903 gives the predicate: *"if `counts_by_status()` shows claimable > 0 and claimed == 0
    and no `work.complete` has committed since the previous poll, and `deferred_sweeper` returned
    nothing, the run ends."* 08:915-916 adds the guard: *"Two poll cycles are required before the
    run ends, and `claimed == 0` is part of the predicate, so a single slow 200-page document
    cannot trip it."*

    `claimable` is `pending + failed_transient` -- the claim predicate's own two statuses, which is
    what makes "claimable > 0" mean "there is work this loop could take" rather than "there are
    rows". A queue of nothing but `deferred` rows is NOT claimable and is exactly the state
    08:892-894 describes, which is why `deferred` is counted separately and reported in `reason`.
    """
    claimable = counts.get("pending", 0) + counts.get("failed_transient", 0)
    claimed = counts.get("claimed", 0)
    deferred = counts.get("deferred", 0)
    quiet = completions_since_last_poll == 0 and swept == 0

    if not quiet:
        return StallVerdict(False, "work is still committing")
    if claimed > 0:
        return StallVerdict(False, f"{claimed} row(s) are claimed and may still be running")
    if claimable == 0:
        return StallVerdict(False, "nothing is claimable, so there is nothing to be stalled on")
    if consecutive_quiet_polls < QUIET_POLLS_BEFORE_SHED:
        return StallVerdict(
            False,
            f"quiet for {consecutive_quiet_polls} poll(s); {QUIET_POLLS_BEFORE_SHED} "
            f"are required "
            f"so one slow 200-page document cannot trip this",
        )
    return StallVerdict(
        True,
        f"{claimable} claimable row(s), none claimed, nothing committed or swept for "
        f"{consecutive_quiet_polls} polls, {deferred} deferred",
        blocker=dominant_blocker,
    )


# =============================================================================================
# 6. The loop -- claim -> admit -> dispatch -> complete -> reap
# =============================================================================================

LOOP_LAG_SAMPLE_MS: Final = 100
"""`lag_monitor` samples at 100 ms. 02-architecture.md:753, and it is prose rather than a key.

The threshold it compares against IS a key (`[runtime] loop_lag_max_ms = 250`); the cadence is not,
in either document. 100 ms against a 250 ms threshold is two and a half samples per breach window,
which is the smallest ratio that can see one -- and it is the same cadence `subproc.py` already
samples RSS at, for the stated reason that *"the supervisor loop already wakes at that rate"*
(04-driver-system.md:1769). A key here would be a knob whose only correct value is a function of
another key."""

LAG_DEGRADATION_KIND: Final[DegradationKind] = "store_busy"
"""Which of the twenty-seven a `loop_lag_max_ms` breach is. 02-architecture.md:753 chooses it.

The closed `DegradationKind` set has no `loop_lag` member and this module adds none -- 15's rule is
*"extended by literal, never re-invented per layer"*. What 02:753 supplies instead is a cause:
*"A multi-minute commit is the one thing that trips it, which is why F29 (a sub-page commit
boundary) is a written open question rather than a hope."* The store holding the loop is
`store_busy`, and the message names `[runtime] loop_lag_max_ms` so the record reads as a lag breach
rather than as a lock timeout."""

CRASH_DEGRADATION_KIND: Final[DegradationKind] = "driver_unavailable"
"""What a `Dispatcher` that RAISED is recorded as. Also one of the twenty-seven, for the same rule.

There is no `driver_bug` member and this module does not add one; `FailureClass.DRIVER_BUG` is the
per-unit taxonomy and is written on a `work` row by whoever produced a `StepResult`, which is
exactly what a raising dispatcher did not do. What is true at the run level is that the batch got no
answer out of its driver, which is `driver_unavailable` -- and the message carries the exception
type, because 15's rule 1 is that the prose says what happened."""


class Dispatcher(Protocol):
    """A `Batch` in, one `StepResult` per row out, in batch order. The loop's dispatch step.

    **The loop does not call `DriverHost.invoke()` and must not.** 08-runtime.md:827 makes
    `omniweave/run/pipeline.py` *"the **only** caller of `DriverHost.invoke()`, semgrep-enforced"*,
    so what the Supervisor holds is the tail of that middleware chain: `with_events` wrapping
    `with_cache` wrapping `with_budget` wrapping the rest, with `dispatch.fan_out()` turning one
    `InvokeReport` into per-unit answers. Everything between a `Batch` and a `StepResult` -- the
    `unit` roster read `dispatch.invocation_units()` needs, the operator that fixes the cache layer,
    the deadline and the budget ceiling -- is on the other side of this Protocol.

    **One `StepResult` per row, and the width is checked rather than trusted.** I24 is the reason:
    *"One `RESULT` frame per unit, one `work` transition per unit, one spend row per unit, one
    `unit` span per unit"* (08:780). A dispatcher that answered for 31 of 32 rows would leave one
    row `claimed` until its lease expired, and the batch would have become visible in the work table
    -- which is exactly what I24 forbids. `fan_out()` already guarantees the width on the host side;
    this Protocol is where the Supervisor stops taking that on trust.

    **Synchronous, and called through `asyncio.to_thread`.** 02-architecture.md:644 puts the loop's
    parallelism in *"IO plus its `to_thread` executor"*; the middleware chain is ordinary blocking
    code (`pipeline.py` imports `threading` and `time`, not `asyncio`), and a chain that had to be
    awaited would put an event loop inside the layer that talks to a `subproc` worker over a pipe.
    """

    def __call__(self, batch: Batch, /) -> Sequence[StepResult]: ...


class Sweeper(Protocol):
    """`deferred_sweeper`'s one call: return `deferred` rows to `pending`, and say how many.

    08:139-141 makes it *"an ordinary TaskGroup task"* in this module, and 08:143-172 gives it four
    rules -- edge-triggered on budget release, every denied dimension must have headroom,
    05-ingest-and-routing.md section 6.4's sibling clause, and a durable
    `min(60_000 x 2^(n-1), 1_800_000)` backoff on the defer streak.

    **None of the four is implemented here, and the seam is why.** Rule 2 needs the per-dimension
    headroom SQL of 08 section 7.3 evaluated against each row's *denied* dimensions; rule 3 needs to
    know whether a sibling reservation for the same `scope_key` is still `held`; rule 4 needs an
    in-run defer streak per `scope_key`. The first is `omniweave_core.budget.HEADROOM_SQL` and
    exists; the other two need a `work` column and a run-scoped counter that do not. So this module
    takes the sweeper as a dependency, `no_sweep` is the honest default, and
    `RunReport.sweeper_wired` DISCLOSES which one ran rather than reporting a zero that could mean
    either.

    That disclosure is load-bearing and not bookkeeping: `stall_verdict()`'s fourth conjunct is
    *"`deferred_sweeper` returned nothing"* (08:902), so a sweeper that is absent and a sweeper that
    found nothing to return are the same input to the predicate that ENDS THE RUN. A run shed on a
    stall whose fourth conjunct was satisfied by an unimplemented sweeper is a run that stopped for
    a reason nobody can check, which is why the report says so.
    """

    def sweep(self, now_ms: int, /) -> int: ...


def no_sweep(_now_ms: int, /) -> int:
    """The default sweep: zero rows, always. See `Sweeper` for what is not built.

    A function rather than a class, because the constructor takes the bound method and not the
    object. It returns 0 and touches nothing: a sweeper that opened a transaction to return the same
    zero would be one `BEGIN IMMEDIATE` per `deferred_sweep_ms` for an answer it already knows.
    """
    return 0


def no_emit(**_fields: object) -> None:
    """The default sink: events are diagnostic and droppable, and a run with none is still a run.

    `discover.py`, `expand.py` and `converge.py` all take `emit` as an injected
    `Callable[..., object] | None` and this module takes the same shape, for the same reason: the
    `TraceSink` on `RunContext` is typed `emit(e: Event) -> None` over a built envelope, and the
    run modules emit by `(kind, fields)` and let their caller build it. One named no-op beats an
    `if self._emit is not None` at every one of the seven emission sites.
    """


@dataclass(frozen=True, slots=True)
class LoopTimings:
    """The six cadences the loop runs on. Every one of them a config key, none of them a constant.

    **No defaults, and that is D149's ruling applied to its own cell.** Three of these six --
    `[runtime] shutdown_grace_ms`, `deferred_sweep_ms` and `stall_poll_ms` -- are keys
    08-runtime.md:2598-2606 introduces under *"New keys this document introduces"* and which reached
    neither `omniweave_core.config.KEYS` nor `omniweave.toml.example` until this cell. The tempting
    local fix was *"a module-level constant transcribed from 08:2606"*, and 02 section 8.4 forbids
    it: a number that is not in `KEYS` has no axis, no `OMNIWEAVE_*` twin, and 08 section 4.3 treats
    an unclassified key as `semantic` -- which would put a scheduling cadence into every cache key
    in the corpus. So the three are declared in `config.py` as `operational`, and this dataclass
    takes no defaults at all: a default here would be the second home the declaration exists to
    prevent, and `of()` is the one function that knows the six key names.

    `lease_extend_ms` is here for its cadence and not for its mechanism. The one extension a live
    holder gets is `lease_reaper`'s liveness decision (08:462-470) and `Store.reap_expired_leases()`
    does not make it -- `REAP_SQL`'s own docstring records that boundary. What this module uses the
    number for is how often the reaper sweeps, which is the interval at which a lease's disposition
    can change and therefore the only non-arbitrary number available.
    """

    lease_ms: int
    lease_extend_ms: int
    stall_poll_ms: int
    deferred_sweep_ms: int
    shutdown_grace_ms: int
    loop_lag_max_ms: int

    def __post_init__(self) -> None:
        for name in ("lease_ms", "lease_extend_ms", "stall_poll_ms", "deferred_sweep_ms"):
            value = getattr(self, name)
            if value <= 0:
                raise ConfigError(
                    f"[runtime] {name} is {value}; a cadence of zero is a spin and a negative one "
                    f"is a wait that never ends",
                    fix=f"set [runtime] {name} to a positive number of milliseconds",
                )

    @classmethod
    def of(cls, cfg: object) -> LoopTimings:
        """The six `[runtime]` keys, read once. The only place their names are spelled."""
        get = cfg.get  # type: ignore[attr-defined]
        return cls(
            lease_ms=int(get("runtime.lease_ms")),
            lease_extend_ms=int(get("runtime.lease_extend_ms")),
            stall_poll_ms=int(get("runtime.stall_poll_ms")),
            deferred_sweep_ms=int(get("runtime.deferred_sweep_ms")),
            shutdown_grace_ms=int(get("runtime.shutdown_grace_ms")),
            loop_lag_max_ms=int(get("runtime.loop_lag_max_ms")),
        )


class PauseGate:
    """`discover.Backpressure.pause`, holding the hysteresis state discover.py says lives here.

    `discover.py`'s own docstring names this arrangement: *"the predicate is
    `supervisor.producer_should_pause(claimable, admission, paused=...)` and carries the caller's
    hysteresis state across calls ... a second copy of a two-threshold rule is how `plan.pause` and
    `plan.resume` start disagreeing about which threshold they crossed."* So the predicate is that
    function, unchanged, and what this class adds is the one boolean it needs and the producer does
    not own -- plus the two events, emitted on the TRANSITION and never on every poll.

    **It is not on the loop's own path.** The producer holds it and calls it between roster batches;
    the Supervisor never consults it, because a loop that paused itself at the high-water mark would
    stop draining the very queue the pause exists to drain.
    """

    __slots__ = ("_admission", "_claimable", "_emit", "_paused")

    def __init__(
        self,
        claimable: Callable[[], int],
        *,
        admission: Admission,
        emit: Callable[..., object] = no_emit,
    ) -> None:
        self._claimable = claimable
        self._admission = admission
        self._emit = emit
        self._paused = False

    @property
    def paused(self) -> bool:
        """The latched state -- `discover()`'s `resumed=` argument on the next pass."""
        return self._paused

    def __call__(self) -> bool:
        """True iff the producer should stop pulling its `enumerate` generator.

        08:875-876: *"none of them drops work except the event queue, which drops by design and
        says so."* A True here is a generator that is not pulled, never a row that is discarded.
        """
        claimable = self._claimable()
        paused = producer_should_pause(claimable, self._admission, paused=self._paused)
        if paused != self._paused:
            self._paused = paused
            self._announce(claimable, paused=paused)
        return paused

    def _announce(self, claimable: int, *, paused: bool) -> None:
        """One event per crossing, each naming the threshold IT crossed. 08:885 requires that."""
        if paused:
            self._emit(
                kind=EventKind.PLAN_PAUSE,
                fields={"claimable": claimable, "high_water": self._admission.high_water},
            )
        else:
            self._emit(
                kind=EventKind.PLAN_RESUME,
                fields={"claimable": claimable, "low_water": self._admission.low_water},
            )


class _ClassGate:
    """`class_sem[c]`, acquired N permits at a time without a deadlock. 08:686-689's "UNITS".

    08:687 writes the family's unit of account beside its constructor: *"These count UNITS, not
    processes: one worker process may hold a Batch of 256."* So a batch of `n` rows takes `n`
    permits and not one -- and that is the whole reason this class exists, because taking `n`
    permits from an `asyncio.BoundedSemaphore` one `await` at a time is a textbook
    partial-acquisition deadlock: two batches of 20 against a bound of 32 can hold 16 each and wait
    forever.

    **A per-class turn lock makes it safe with no new primitive.** Only one acquirer per class may
    be mid-acquisition; everyone else waits for the turn rather than for a permit. The holder of the
    turn is then the only coroutine that holds permits while waiting for permits, and every other
    holder is running and will release -- so there is no cycle. A `Condition` with a predicate would
    be the general answer; this is four lines and needs no second wait queue.

    **`want` is clamped to the bound, and the clamp is a defect report.** The shipped defaults make
    `[runtime.claim] batch.free = 256` exceed `[budget] max_inflight.free = 32` by a factor of
    eight, so a literal permit-per-unit acquisition could never be satisfied by its own
    configuration: the first free batch would wait for 256 permits against a semaphore that can
    issue 32, forever. The clamp says the truthful thing instead -- a batch at or above the bound
    SATURATES its class, no second batch of that class runs beside it -- and turns an impossible
    wait into that fact. Filed.
    """

    __slots__ = ("_bound", "_sem", "_turn")

    def __init__(self, sem: asyncio.BoundedSemaphore, bound: int) -> None:
        self._sem = sem
        self._bound = max(1, bound)
        self._turn = asyncio.Lock()

    @property
    def bound(self) -> int:
        """The derived `[budget] max_inflight` for this class, which `want()` clamps to."""
        return self._bound

    def want(self, units: int) -> int:
        """How many permits a batch of `units` rows takes: `units`, clamped to the bound."""
        return max(1, min(units, self._bound))

    @asynccontextmanager
    async def hold(self, units: int) -> AsyncIterator[int]:
        """Hold `want(units)` permits for the body. Releases every one of them on any exit."""
        want = self.want(units)
        async with self._turn:
            for _ in range(want):
                await self._sem.acquire()
        try:
            yield want
        finally:
            for _ in range(want):
                self._sem.release()


@dataclass(frozen=True, slots=True)
class RunReport:
    """What one `Supervisor.run()` did, and the one thing it could not do.

    `status` is 08:365-371's, drawn from the cancellation cause rather than from a count:
    `interrupt` leaves `interrupted`, `shed` leaves `partial` (08:906 -- *"the run ends with
    `run.status = 'partial'`"*), and no cancellation at all leaves `done`. A run with failures in it
    is still `done`: 08:911 is explicit that *"`ow ingest` still exits 0, because a partial run is a
    result and not an error"*, and a failed unit is a `work` row, not a run status.

    `superseded` counts `Store.complete()` returning `False`, which means one thing only (08:2486):
    the commit predicate matched zero rows. `abandoned` counts rows claimed and never dispatched
    because a cancellation latched first -- `Supervisor._abandon` carries why they are left to the
    lease reaper rather than completed as `CANCELLED`.

    `sweeper_wired` is a disclosure and not a statistic; `Sweeper`'s docstring is the argument.
    """

    status: Literal["done", "partial", "interrupted"]
    claimed: int = 0
    batches: int = 0
    completed: int = 0
    superseded: int = 0
    abandoned: int = 0
    crashed: int = 0
    reaped: int = 0
    swept: int = 0
    polls: int = 0
    stall: StallVerdict | None = None
    cancelled: CancelReason | None = None
    lag_breach_ms: int = 0
    sweeper_wired: bool = False
    degradations: tuple[Degradation, ...] = ()

    @property
    def stalled(self) -> bool:
        """Whether `stall_detector` ended this run. `status == 'partial'` is the same fact."""
        return self.stall is not None and self.stall.stalled

    @property
    def complete(self) -> bool:
        """Whether every answer this report carries came from a mechanism that is built.

        False when the sweeper was the default, for `Sweeper`'s reason: the stall predicate's fourth
        conjunct cannot be told apart from an unimplemented sweeper's zero.
        """
        return self.sweeper_wired


class _Exclusion:
    """One Supervisor per process, as an assertion. 02-architecture.md:727, startup step 9.

    *"a second concurrent `run()` in one process is refused with `StoreError` before the loop opens:
    one Supervisor per process is an assertion, not a convention."* Before the loop opens is the
    load-bearing half -- a second `run()` that got as far as claiming would hold two sets of leases
    under one `claimed_by`, and the reaper's liveness test could not tell them apart.

    **This is module state, and 08:291's ban does not reach it.** The ban is *"no module globals in
    `omniweave/run/`: `ctx` is per-run"*, and the three bugs behind it are first-caller-wins caches
    that made a second run see the first run's data (graphify's `_stat_index`, graphrag's
    `Factory.__new__` singleton, jcodemunch's `_repo_states`). This object holds no run's data and
    is not per-run: it is a property OF THE PROCESS, and its entire job is to refuse the second run
    rather than to serve it the first one's state. A per-run object could not express it at all.

    `threading.Lock` rather than an asyncio primitive because the scope is the process and not the
    loop: an embedder running two Supervisors on two event loops in two threads is precisely the
    case a loop-bound lock would miss.
    """

    __slots__ = ("_gate", "_holder")

    def __init__(self) -> None:
        self._gate = threading.Lock()
        self._holder = ""

    @contextmanager
    def claim(self, holder: str) -> Iterator[None]:
        """Hold the process for `holder`, or refuse with `StoreError` naming the one that has it."""
        if not self._gate.acquire(blocking=False):
            raise StoreError(
                f"a Supervisor is already running in this process (claimed by {self._holder!r}): "
                f"one Supervisor per process is an assertion, not a convention",
                fix="run the second ingest in its own process, or await the first run()",
            )
        self._holder = holder
        try:
            yield
        finally:
            self._holder = ""
            self._gate.release()


_ONE_PER_PROCESS: Final = _Exclusion()
"""The process-wide latch. See `_Exclusion` for why this is not the module global 08:291 bans."""

_STOP: Final = object()
"""The inbox sentinel: one per worker, put once the claimer has stopped claiming.

A sentinel rather than a poll, because the alternative -- a worker that wakes on a timer to ask
whether the run is over -- is scheduling work for a question the claimer already knows the answer
to, at the cadence the lag monitor is watching."""


class Supervisor:
    """The one asyncio loop: claim -> admit -> dispatch -> complete -> reap. 16-roadmap.md:542.

    ## The five steps, and where each one actually is

    | step | here | and where the rest of it is |
    |---|---|---|
    | claim | `_claimer`, one `Store.claim` per pass | the statement is `store/queue.py`'s |
    | admit | `_ClassGate` + `worker_sem` | the DURABLE half is `with_budget`'s |
    | dispatch | `_serve`, awaiting a `Dispatcher` in a thread | the chain is `pipeline.py`'s |
    | complete | `_commit`, one `Store.complete` per row | five participants, one transaction |
    | reap | `_reaper`, on the `lease_extend_ms` cadence | the two statements are the store's |

    **The admit step is the semaphores and NOT the ledger, and the split is 08:739-743's.**
    `class_sem[BILLED_API]` *"still exists and still bounds this process's own concurrency; it is
    simply not the authority"* -- the authority is the durable `budget_reservation` ledger, because
    *"two scheduler processes each holding an in-memory semaphore of 2 show the provider 4"*. The
    ledger is reached through `with_budget`, which is INSIDE the `Dispatcher`, so a budget denial
    arrives back here as `Outcome.DEFERRED_BUDGET` on a `StepResult` and not as a decision this
    class made. A loop that admitted against the ledger itself would be a fourth enforcement site,
    and 08 section 7.2 is titled *"three sites, and only three"*.

    ## `TaskGroup` for structured shutdown only

    02-architecture.md:653 writes the constraint beside the diagram: *"TaskGroup for STRUCTURED
    SHUTDOWN ONLY; a worker_loop catches BaseException and NEVER propagates, so one crash costs one
    unit."* Both halves are here, and the second needs one qualification the sentence does not make.

    The group holds a FIXED set of long-lived tasks -- `worker_loop` x N, plus the four watchers --
    created once and never one per unit of work. Batches reach the workers through a bounded inbox
    whose bound is the worker count, because a claimer that ran further ahead than that would be
    holding leases on rows no worker can start. A group that spawned a task per batch would be a
    scheduler with an unbounded task set, and the `Admission` families would be bounding something
    the group had already admitted.

    **`_worker_loop` catches `BaseException` and re-raises `CancelledError`, which the plan's
    sentence reads as a contradiction.** `asyncio.CancelledError` has inherited from `BaseException`
    since 3.8, so a `worker_loop` that literally *"catches BaseException and NEVER propagates"*
    would swallow the cancellation its own `TaskGroup` shuts down with -- the loop would hang on
    Ctrl-C at exactly the moment the structure exists for. The rule the sentence means is *one crash
    costs one unit*, and that is what is implemented: everything a batch can raise is converted into
    one recorded degradation over that batch's rows, and the one exception is the exception that is
    not a crash. Filed.

    ## What ends a run, and the three answers are not interchangeable

    The claimer runs out of claimable rows with an empty inbox, which is `done`. `stall_detector`
    withdraws the run, which latches `CancelReason.SHED` and leaves `partial` -- 08:892-897's
    full-claimable-set-with-nothing-admissible. Or `interrupt()` latches `CancelReason.INTERRUPT`
    and leaves `interrupted`.

    **`interrupt()` is a method and not a signal handler.** 08:2390 says *"SIGINT -> the loop's
    signal handler sets ctx.cancel"*, and `signal.signal` is a process-global mutation that a
    library called from an SDK embedder, a hook child and an MCP server may not make on its own. So
    the semantics live here -- including 08:414-419's two-interrupt sequence, which is the boolean
    `CancelToken.cancel()` already returns -- and the process that owns the process installs the
    handler.

    ## Three things this loop does not do

    **It never holds document bytes** (I31): a `StepResult` carries `ArtifactRef`s and a `UnitRef`,
    and the bytes are the worker's and the CAS's.

    **It never rasterises.** `render()` is the bounded entry the raster step takes
    (02-architecture.md:653's RENDER THREADS), and the reason it is exposed rather than used here is
    08:674-676: that semaphore is process-wide and is NOT `service_sem`, so the caller that renders
    takes it and the loop that dispatches does not.

    **It completes only what the dispatcher answered for.** See `_abandon`.

    Specified in 08-runtime.md sections 1.2, 2.1, 2.5 and 8, 02-architecture.md sections 5.1 and
    5.3, and 16-roadmap.md:542 (P4 W4.2).
    """

    __slots__ = (
        "_abandoned",
        "_admission",
        "_batches",
        "_claimed",
        "_closing",
        "_completed",
        "_crashed",
        "_ctx",
        "_dispatch",
        "_emit",
        "_gates",
        "_inbox",
        "_lag_breach_ms",
        "_mint",
        "_polls",
        "_queue",
        "_reaped",
        "_stall",
        "_start_batch",
        "_superseded",
        "_sweep",
        "_swept",
        "_timings",
        "_worker",
        "_workers",
    )

    def __init__(
        self,
        ctx: RunContext,
        *,
        queue: Store,
        dispatch: Dispatcher,
        admission: Admission,
        timings: LoopTimings,
        worker: str,
        claim_batch: Mapping[str, int],
        sweep: Callable[[int], int] = no_sweep,
        emit: Callable[..., object] = no_emit,
        mint: Callable[[], str] | None = None,
    ) -> None:
        """`worker` is `'<host>:<pid>:<process_create_time>'` -- 08:465's `claimed_by`.

        The three components are the reaper's liveness test and the third is load-bearing: *"the
        third component is what stops a recycled pid from looking alive (jcodemunch #450 observed
        two-week-old lock rows resolving to a Chrome renderer and an AMD service)"*. It is a
        parameter rather than computed here because `omniweave_core.locks` already owns that
        string's construction, and a second speller of an identity is a second identity.

        `claim_batch` is `[runtime.claim] batch`, per cost class and already clamped by the card
        where the caller knows it (`dispatch.start_batch()`). `_next_width` says why the claim reads
        the narrowest of the three rather than the one it is about to get.
        """
        self._ctx = ctx
        self._queue = queue
        self._dispatch = dispatch
        self._admission = admission
        self._timings = timings
        self._worker = worker
        self._start_batch = dict(claim_batch)
        self._sweep = sweep
        self._emit = emit
        self._mint = mint if mint is not None else _default_mint(ctx)
        self._gates: Mapping[str, _ClassGate] = {
            name: _ClassGate(sem, admission.inflight.get(name, 1))
            for name, sem in admission.class_sem.items()
        }
        self._workers = max(1, sum(admission.workers.values()))
        self._inbox: asyncio.Queue[object] = asyncio.Queue(maxsize=self._workers)
        self._closing = asyncio.Event()
        self._claimed = 0
        self._batches = 0
        self._completed = 0
        self._superseded = 0
        self._abandoned = 0
        self._crashed = 0
        self._reaped = 0
        self._swept = 0
        self._polls = 0
        self._lag_breach_ms = 0
        self._stall: StallVerdict | None = None

    # -- the public surface --------------------------------------------------------------------

    def interrupt(self) -> bool:
        """Latch `CancelReason.INTERRUPT`. True iff THIS call latched -- 08:414-419's sequence.

        *"The first Ctrl-C latches and returns `True`; the second finds a latch already present,
        returns `False`, and the handler exits the process without waiting -- which is safe because
        the claimable set **is** the checkpoint."* The handler is the caller's; the class docstring
        carries why a library may not install one.

        **Call this on the loop's own thread.** `loop.add_signal_handler()` guarantees that and
        `signal.signal()` does not, which is the second reason the handler is the caller's rather
        than this class's: the latch itself is thread-safe by construction (`CancelToken`'s
        `_latch` is a list, *"so the SIGINT handler cannot deadlock against a worker"*), but the
        `asyncio.Event` woken beside it is not, and a set from a foreign thread is a data race on
        the loop rather than an error anybody sees.
        """
        from omniweave_core.operator import CancelReason  # noqa: PLC0415

        self._closing.set()
        return self._ctx.cancel.cancel(CancelReason.INTERRUPT)

    def pause_gate(self, claimable: Callable[[], int]) -> PauseGate:
        """The producer's `Backpressure.pause`, holding this run's hysteresis. See `PauseGate`."""
        return PauseGate(claimable, admission=self._admission, emit=self._emit)

    @asynccontextmanager
    async def render(self) -> AsyncIterator[None]:
        """One CPU rasterisation slot, `max(1, cpus - 2)` of them. olmocr `pipeline.py:87`.

        Exposed and not used: the loop does not rasterise, and 08:674-676 is why the slot is
        separate from the Service's -- *"at 10.7 MB per rendered 192-DPI page, one shared semaphore
        renders faster than it evicts."* A page rasterised while the GPU queue is full is 10.7 MB of
        resident memory waiting for a slot, so the render step takes THIS semaphore around its
        `asyncio.to_thread` and the inference step takes `service_sem`.
        """
        async with self._admission.render_sem:
            yield

    async def run(self) -> RunReport:
        """Open the loop, drain the queue, report. One per process -- see `_Exclusion`."""
        with _ONE_PER_PROCESS.claim(self._worker):
            return await self._run()

    # -- the loop ------------------------------------------------------------------------------

    async def _run(self) -> RunReport:
        """The `TaskGroup`. Watchers and workers are its children; the claimer is its body.

        **The sentinels are `await`ed and not `put_nowait`ed**, and the inbox is bounded, so the
        distinction is a real one: on a cancel the claimer stops with up to `worker_count` batches
        still queued and a `put_nowait` raises `QueueFull` into the `TaskGroup` -- turning a Ctrl-C
        into an `ExceptionGroup`. It cannot block forever either, because a worker only returns on
        a sentinel: every one of them is still consuming, and a cancelled one abandons what it
        takes without dispatching it.
        """
        async with asyncio.TaskGroup() as group:
            watchers = (
                group.create_task(self._reaper(), name="lease_reaper"),
                group.create_task(self._deferred_sweeper(), name="deferred_sweeper"),
                group.create_task(self._stall_detector(), name="stall_detector"),
                group.create_task(self._lag_monitor(), name="lag_monitor"),
            )
            workers = tuple(
                group.create_task(self._worker_loop(), name=f"worker_loop.{index}")
                for index in range(self._workers)
            )
            try:
                await self._claimer()
            finally:
                self._closing.set()
                for _ in workers:
                    await self._inbox.put(_STOP)
                await self._await_workers(workers)
                for task in (*watchers, *workers):
                    task.cancel()
        return self._report()

    async def _await_workers(self, workers: Sequence[asyncio.Task[None]]) -> None:
        """Wait for the workers: unbounded on the ordinary path, `shutdown_grace_ms` on a cancel.

        08:2404's grace is a CANCELLATION budget and nothing else: *"if the worker has not returned
        within `[runtime] shutdown_grace_ms = 5000`, the host sends `SHUTDOWN{grace_ms}`; then
        SIGTERM; then SIGKILL at +5 s."* Applying it to the ordinary drain would abandon a
        legitimate 90-second page parse five seconds in, which is the mistake 08:2372 names about
        single timeouts -- *"a driver that renders a page for 90 s with no output is not chatty."*
        """
        if not workers:
            return
        timeout = self._timings.shutdown_grace_ms / 1000 if self._ctx.cancel.cancelled() else None
        await asyncio.wait(workers, timeout=timeout)

    async def _claimer(self) -> None:
        """claim -> form_batches -> the inbox. Returns when there is nothing left to claim.

        **The cancel check is at the loop TOP**, which is 08:349's rule for every one of them:
        *"checked at every loop top by the Supervisor, by each `worker_loop`, and by the driver
        through `DriverIO.cancelled()`."* A claim issued after a cancellation latched is a lease
        taken on a row nobody will run.

        **An empty claim does not end the run on its own.** `deferred` rows are not claimable
        (08:127-131: the claim predicate is `status IN ('pending','failed_transient')`), so an empty
        claim with 2,900 deferred rows waiting on the sweeper is a pause and not an end -- and a
        batch still being served can still produce a `failed_transient` row for the next pass. So
        the end needs the same two conditions the stall detector needs: the inbox empty, and
        `QUIET_POLLS_BEFORE_SHED` consecutive empty claims.
        """
        from omniweave.run.dispatch import form_batches  # noqa: PLC0415

        empty = 0
        while not self._ctx.cancel.cancelled() and not self._closing.is_set():
            rows = await asyncio.to_thread(
                self._queue.claim,
                self._next_width(),
                self._ctx.generation,
                self._worker,
                self._timings.lease_ms,
            )
            if not rows:
                empty += 1
                if self._inbox.empty() and empty > QUIET_POLLS_BEFORE_SHED:
                    return
                await self._settle()
                continue
            empty = 0
            self._claimed += len(rows)
            self._announce_claim(rows)
            for batch in form_batches(rows, mint=self._mint):
                self._batches += 1
                await self._inbox.put(batch)

    def _next_width(self) -> int:
        """How many rows the next claim asks for: the NARROWEST class, because a claim names none.

        `Store.claim(batch, gen, worker, lease_ms)` takes no cost class -- the charter's
        four-parameter form is what ships, and `store/__init__.py`'s `Store` docstring records the
        disagreement with 08:2478's wider print. So the width cannot be chosen for the class that is
        about to come back, and the only safe choice is the smallest configured one: asking for 256
        because `free` allows it, and getting 256 `billed_api` rows because those happened to be the
        highest-priority, would take 256 leases for a class bounded at two units in flight.
        """
        return max(1, min(self._start_batch.values(), default=1))

    async def _settle(self) -> None:
        """One quiet pass: wait a sweep interval, or until the run closes, whichever comes first."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                self._closing.wait(), timeout=self._timings.deferred_sweep_ms / 1000
            )

    async def _worker_loop(self) -> None:
        """One long-lived worker. Catches everything a batch can raise; re-raises cancellation.

        The class docstring carries the argument for the one exception. What it protects is 02:653's
        rule that *"one crash costs one unit"*: a `Dispatcher` that raised would otherwise take the
        whole `TaskGroup` down and leave every other claimed row to its lease.
        """
        while True:
            item = await self._inbox.get()
            if item is _STOP:
                return
            batch = cast("Batch", item)
            if self._ctx.cancel.cancelled():
                self._abandon(batch)
                continue
            try:
                await self._serve(batch)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # 02:653; see the class docstring.
                self._crash(batch, exc)

    async def _serve(self, batch: Batch) -> None:
        """admit -> dispatch, for one batch, then `_commit`. The only place all three meet.

        **The two families are taken in one fixed order, class before worker.** Two semaphores
        acquired in two orders is a deadlock, and this is the order the plan lists them in
        (08:693-695, 02:674-676). It is also the order that cannot cycle: a batch holding a worker
        permit already has its units and is running, so it will release.

        The cancel check is after the gates because acquiring can take arbitrarily long -- a Ctrl-C
        while a `local_compute` batch waits behind four in-flight units must not then spend
        GPU-seconds on it.
        """
        cost_class = self._cost_class(batch)
        gate = self._gates.get(cost_class)
        worker_sem = self._admission.worker_sem.get(cost_class)
        if gate is None or worker_sem is None:
            raise ConfigError(
                f"batch {batch.invoke_id} is cost class {cost_class!r}, which has no semaphore "
                f"family; the derivation covers {sorted(self._gates)}",
                fix="derive the Admission from a Config whose [budget] max_inflight names it",
            )
        async with gate.hold(batch.size), worker_sem:
            if self._ctx.cancel.cancelled():
                self._abandon(batch)
                return
            results = await asyncio.to_thread(self._dispatch, batch)
        await self._commit(batch, results)

    async def _commit(self, batch: Batch, results: Sequence[StepResult]) -> None:
        """One `Store.complete()` per row. I24's width is checked here, not assumed.

        One transaction per unit, which is INV-17's -- 08:919 makes the commit *"the ingest
        throughput ceiling"* and says so rather than batching it away. A `False` is SUPERSEDED and
        nothing else (08:2486), so it is counted rather than raised: the row moved out from under
        this generation, which is what a second run starting mid-flight looks like, and 08:2413
        records it as `work.cancel{work_id, generation}`.
        """
        if len(results) != batch.size:
            raise RouteError(
                f"invoke {batch.invoke_id} carried {batch.size} rows and the dispatcher answered "
                f"for {len(results)}; one work transition per unit is I24, so a short answer "
                f"leaves a claimed row to its lease",
                fix="build the answer with dispatch.fan_out(), which answers for every unit",
            )
        for row, result in zip(batch.rows, results, strict=True):
            committed = await asyncio.to_thread(
                self._queue.complete, row.id, self._ctx.generation, result
            )
            if committed:
                self._completed += 1
                self._announce_complete(row, result)
            else:
                self._superseded += 1
                self._announce_superseded(row)

    def _cost_class(self, batch: Batch) -> str:
        """The batch's class, refusing a batch that carries two.

        A `dispatch_key` is `sha256(driver_id‖config_digest‖isolation)` and a driver has one cost
        class, so a coherent batch is single-class by construction and `form_batches` gives every
        NULL-key row a batch of its own. This checks rather than trusts it, because the consequence
        is silent: `rows[0].cost_class` on a mixed batch would admit `billed_api` units against the
        `free` semaphore and bill a provider under a bound that was never meant for it.
        """
        classes = {row.cost_class for row in batch.rows}
        if len(classes) != 1:
            raise RouteError(
                f"invoke {batch.invoke_id} mixes cost classes {sorted(classes)}; a dispatch_key is "
                f"one driver and a driver has one class, so admission has no family to take",
                fix="form batches with dispatch.form_batches(), one dispatch_key at a time",
            )
        return classes.pop()

    def _abandon(self, batch: Batch) -> None:
        """A claimed batch a cancellation reached first. Left to the lease reaper, deliberately.

        08:2409 asks the Supervisor for *"`StepResult(outcome=CANCELLED)` for every claimed row"*,
        and the Supervisor cannot build one. `StepResult` requires `unit: UnitRef` -- which carries
        `content_sha256` and `byte_len` off the `unit` table -- and `identity: OperatorIdentity`,
        and a `WorkRow` carries neither. Everything else it needs IS on the row (`cache_key`,
        `operator`, `op_version`); those two are not, and fabricating a digest to satisfy a
        dataclass would put an invented content hash into the one column the cache reads.

        **The reaper is the same transition, which is why leaving them is correct and not a leak.**
        08 section 1.2's table gives `cancelled` three effects -- status becomes `pending`,
        `attempts_total` is decremented, the reservation is released -- and 08:121-122 gives the
        reaper the same three on the same rule: *"the lease reaper decrements on the same rule as
        `CANCELLED` -- a power cut is not an attempt."* The end state is identical; the only
        difference is latency, bounded by `lease_ms`.

        **And the exposure is bounded by the inbox, not by the queue.** The claimer stops at its own
        loop top, so the rows that can be in this state are the ones in flight plus at most
        `worker_count` batches -- never the 331,455 rows of 08:501's resume case. Filed.
        """
        self._abandoned += len(batch.rows)
        for row in batch.rows:
            self._emit(
                kind=EventKind.WORK_CANCEL,
                fields={"work_id": row.id, "generation": self._ctx.generation},
            )

    def _crash(self, batch: Batch, exc: BaseException) -> None:
        """A `Dispatcher` that raised. Counted, reported, and NOT propagated. 02:653.

        The rows stay `claimed` and the reaper returns them, for `_abandon`'s reason: there is no
        `StepResult` to write, and here there is not even a reply to read one out of. What this does
        write is the diagnosis -- `run.degraded` naming the exception type -- because the
        alternative is a batch that disappears into a lease timeout with nothing recorded anywhere.
        """
        self._crashed += len(batch.rows)
        self._emit(
            kind=EventKind.RUN_DEGRADED,
            fields={
                "degradation_kind": CRASH_DEGRADATION_KIND,
                "message": (
                    f"the dispatcher raised {type(exc).__name__} for invoke {batch.invoke_id}; "
                    f"its {len(batch.rows)} row(s) return through the lease reaper"
                ),
            },
        )

    # -- the four watchers ---------------------------------------------------------------------

    async def _reaper(self) -> None:
        """`lease_reaper`, on the `lease_extend_ms` cadence. 08:462-470.

        The cadence is `LoopTimings`' argument: no key names a reaper interval, and the interval at
        which a lease's disposition can change is `lease_extend_ms`. Holder liveness and the one
        extension a live holder gets are NOT here -- `REAP_SQL`'s own docstring records that
        boundary -- and this call is the sweep the store does expose.
        """
        async for _ in self._every(self._timings.lease_extend_ms):
            now_ms = self._ctx.clock.wall_ns() // 1_000_000
            self._reaped += await asyncio.to_thread(self._queue.reap_expired_leases, now_ms)

    async def _deferred_sweeper(self) -> None:
        """08:139's *"an ordinary TaskGroup task"*, at `[runtime] deferred_sweep_ms`.

        08:147 calls the poll *"a backstop, because a `run`-scoped `wall_ms` cap frees nothing and
        still needs a terminal answer"* -- the mechanism proper is edge-triggered on every
        `budget.commit` and `budget.release` that lowers a held sum. What runs here is the backstop;
        `Sweeper` says what is not built and `RunReport.sweeper_wired` discloses it.
        """
        async for _ in self._every(self._timings.deferred_sweep_ms):
            now_ms = self._ctx.clock.wall_ns() // 1_000_000
            self._swept += await asyncio.to_thread(self._sweep, now_ms)

    async def _stall_detector(self) -> None:
        """Every `stall_poll_ms`: two quiet polls with claimable rows and nothing claimed end it.

        The predicate is `stall_verdict()`'s and is not restated. What this adds is the two readings
        it takes a difference of: completions since the previous poll, and what the sweeper returned
        since the previous poll. 08:915 requires two cycles *"so a single slow 200-page document
        cannot trip it"*, and the counter is reset by any pass that is not quiet.

        On a verdict, `CancelReason.SHED` -- *"the Supervisor withdrew the run"* -- and the run ends
        `partial` with a `Degradation` drawn from the existing closed set (08:906-910).
        """
        quiet = 0
        completed = self._completed
        swept = self._swept
        async for _ in self._every(self._timings.stall_poll_ms):
            counts = await asyncio.to_thread(self._queue.counts_by_status)
            self._polls += 1
            since = self._completed - completed
            returned = self._swept - swept
            completed, swept = self._completed, self._swept
            quiet = quiet + 1 if since == 0 and returned == 0 else 0
            verdict = stall_verdict(
                counts,
                completions_since_last_poll=since,
                swept=returned,
                consecutive_quiet_polls=quiet,
                dominant_blocker=_blocker(counts),
            )
            if verdict.stalled:
                self._stall = verdict
                self._shed(verdict)
                return

    async def _lag_monitor(self) -> None:
        """Samples at `LOOP_LAG_SAMPLE_MS` against `[runtime] loop_lag_max_ms`. One-way. 02:753.

        The measurement is the only honest one available from inside the loop: sleep a known
        interval and see how much longer than that it took to be scheduled again. The excess IS the
        lag, because nothing else can delay a timer callback on an otherwise idle loop.

        **One-way.** 02:753 says *"a **one-way** `degrade()`"*, so what is kept is the WORST breach
        seen and never the latest sample: a loop that recovered still spent that time blocked, and a
        gauge that fell back to zero would erase the only evidence that F29 is a real risk.
        """
        interval = LOOP_LAG_SAMPLE_MS / 1000
        clock = self._ctx.clock
        while not self._closing.is_set():
            before = clock.monotonic_ns()
            await asyncio.sleep(interval)
            lag_ms = (clock.monotonic_ns() - before) // 1_000_000 - LOOP_LAG_SAMPLE_MS
            if lag_ms > self._timings.loop_lag_max_ms and lag_ms > self._lag_breach_ms:
                self._lag_breach_ms = int(lag_ms)

    async def _every(self, period_ms: int) -> AsyncIterator[None]:
        """Tick every `period_ms`, and stop the moment the run closes. Never a bare `sleep`.

        A watcher that slept the whole period would hold the `TaskGroup` open for up to
        `stall_poll_ms = 30000` after the last row committed, which an operator reads as a hang.
        Waiting on the closing event instead makes the cancel path immediate and costs the ordinary
        path one `wait_for` per tick.
        """
        period = period_ms / 1000
        while True:
            try:
                await asyncio.wait_for(self._closing.wait(), timeout=period)
            except TimeoutError:
                yield
                continue
            return

    # -- reporting -----------------------------------------------------------------------------

    def _shed(self, verdict: StallVerdict) -> None:
        """Latch `SHED` and say why, in the words of the knob that would unblock it (08:911)."""
        from omniweave_core.operator import CancelReason  # noqa: PLC0415

        self._ctx.cancel.cancel(CancelReason.SHED, detail=verdict.reason)
        self._closing.set()
        self._emit(
            kind=EventKind.RUN_DEGRADED,
            fields={"degradation_kind": verdict.degradation_kind, "message": verdict.reason},
        )

    def _announce_claim(self, rows: Sequence[WorkRow]) -> None:
        """`work.claim` per ROW. I24: a batch is invisible everywhere but the `call` span."""
        for row in rows:
            self._emit(
                kind=EventKind.WORK_CLAIM,
                fields={
                    "work_id": row.id,
                    "batch_size": len(rows),
                    "claimed_gen": self._ctx.generation,
                    "lease_ms": self._timings.lease_ms,
                },
            )

    def _announce_complete(self, row: WorkRow, result: StepResult) -> None:
        """`work.complete`, plus `work.defer` when the outcome was a budget denial (08:695).

        **`work.defer`'s `retry_after` is always zero here, and that is a reported gap.** The event
        declares the field, 08 section 1.2's table gives a `deferred` row *"the sweeper's backoff"*,
        and 08:167 gives its arithmetic -- `min(60_000 x 2^(n-1), 1_800_000)` over the in-run defer
        streak. But `StepResult.__post_init__` refuses `retry_after_ms` on every outcome except
        `failed_transient`, and `SqliteStore.complete_plan` binds `:retry_after` from that same
        field, so nothing carries the number from the denial to the row or to this event. Zero is
        emitted because the alternative is inventing a backoff nobody will honour. Filed.
        """
        from omniweave_core.operator import Outcome  # noqa: PLC0415

        metrics = result.metrics
        self._emit(
            kind=EventKind.WORK_COMPLETE,
            fields={
                "work_id": row.id,
                "outcome": str(result.outcome),
                "rows_written": metrics.rows_written,
                "micros": metrics.micros,
                "was_cache_hit": metrics.was_cache_hit,
            },
        )
        if result.outcome is Outcome.DEFERRED_BUDGET:
            self._emit(
                kind=EventKind.WORK_DEFER,
                fields={
                    "work_id": row.id,
                    "dim": result.deferred_dim or "",
                    "retry_after": result.retry_after_ms or 0,
                },
            )

    def _announce_superseded(self, row: WorkRow) -> None:
        """08:2413: a late result *"is recorded as `work.cancel{work_id, generation}`"*."""
        self._emit(
            kind=EventKind.WORK_CANCEL,
            fields={"work_id": row.id, "generation": self._ctx.generation},
        )

    def _report(self) -> RunReport:
        """The run's answer. `status` comes from the cancellation cause, never from a count."""
        from omniweave_core.operator import CancelReason  # noqa: PLC0415

        cause = self._ctx.cancel.cause()
        reason = cause.reason if cause is not None else None
        status: Literal["done", "partial", "interrupted"] = "done"
        if reason is CancelReason.INTERRUPT:
            status = "interrupted"
        elif reason is not None:
            status = "partial"
        return RunReport(
            status=status,
            claimed=self._claimed,
            batches=self._batches,
            completed=self._completed,
            superseded=self._superseded,
            abandoned=self._abandoned,
            crashed=self._crashed,
            reaped=self._reaped,
            swept=self._swept,
            polls=self._polls,
            stall=self._stall,
            cancelled=reason,
            lag_breach_ms=self._lag_breach_ms,
            sweeper_wired=self._sweep is not no_sweep,
            degradations=self._degradations(),
        )

    def _degradations(self) -> tuple[Degradation, ...]:
        """At most two, both from the closed twenty-seven and neither invented here."""
        records: list[Degradation] = []
        if self._stall is not None and self._stall.stalled:
            records.append(
                Degradation(
                    kind=cast("DegradationKind", self._stall.degradation_kind),
                    message=self._stall.reason,
                )
            )
        if self._lag_breach_ms:
            records.append(
                Degradation(
                    kind=LAG_DEGRADATION_KIND,
                    message=(
                        f"the loop was blocked for {self._lag_breach_ms} ms against "
                        f"[runtime] loop_lag_max_ms = {self._timings.loop_lag_max_ms}"
                    ),
                    knob="runtime.loop_lag_max_ms",
                )
            )
        return tuple(records)


def _blocker(counts: Mapping[str, int]) -> str:
    """Which `Degradation.kind` a stall is. 08:906-910's two, and this module adds no third.

    *"`kind="budget"` when the dominant blocker is a denial ... `kind="quarantine"` when it is a
    quarantined driver."* Six integers cannot tell those apart on their own, so the answer is the
    one the queue's shape does support: `deferred` is the status a budget denial writes (08 section
    1.2's transition table), so any `deferred` row makes the denial the dominant blocker, and a
    claimable set with none of them is a quarantine.
    """
    return "budget" if counts.get("deferred", 0) > 0 else "quarantine"


def _default_mint(ctx: RunContext) -> Callable[[], str]:
    """`dispatch.new_invoke_id`, closed over this run's injected clock. 08:281-283's ban.

    `form_batches(rows, mint=...)`'s own docstring prescribes the call: *"the caller passes
    `lambda: new_invoke_id(ctx.clock, os.urandom(ULID_ENTROPY_BYTES))`"*. It is a default rather
    than a hard-coded body so that a cassette replay can supply a deterministic minter.
    """
    from omniweave_core.operator import ULID_ENTROPY_BYTES  # noqa: PLC0415

    from omniweave.run.dispatch import new_invoke_id  # noqa: PLC0415

    return lambda: new_invoke_id(ctx.clock, os.urandom(ULID_ENTROPY_BYTES))


def worker_identity() -> str:
    """`'<host>:<pid>:<process_create_time>'` -- 08:490's `claimed_by`, composed from its parts.

    Moved here from `run/bench.py` in W7.3w, which re-exports it: `ow ingest` is the second
    caller that builds a `Supervisor`, and a production verb importing a benchmark harness for
    one identity string would make the harness a dependency of every ingest.

    `Supervisor.__init__` takes this as a parameter *"because `omniweave_core.locks` already owns
    that string's construction"*. What `locks` exports is the third component
    (`process_create_time(pid)`) and the triple as a dataclass; the colon-joined spelling the `work`
    table stores has no function anywhere, so this composes it from the parts rather than inventing
    a third source for an identity.
    """
    from omniweave_core.locks import process_create_time  # noqa: PLC0415 -- the claimer's only

    created, _source = process_create_time(os.getpid())
    return f"{socket.gethostname()}:{os.getpid()}:{created}"


def claim_batch_of(config: object) -> Mapping[str, int]:
    """`[runtime.claim] batch` as `{cost_class: int}`. Refuses a shape `_next_width` cannot read.

    Moved here from `run/bench.py` with `worker_identity()`, for the same reason.
    """
    raw = config.get("runtime.claim.batch")  # type: ignore[attr-defined]
    if not isinstance(raw, Mapping):
        raise ConfigError(
            f"[runtime.claim] batch is {type(raw).__name__} and must be a table keyed by cost "
            f"class; supervisor.py's `_table` refuses the same shape for the same reason",
            fix="set runtime.claim.batch = { free = .., local_compute = .., billed_api = .. }",
        )
    return {str(name): int(value) for name, value in raw.items()}  # type: ignore[call-overload]
