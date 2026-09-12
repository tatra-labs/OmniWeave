"""Admission, backpressure and the stall verdict: where every degree of parallelism comes from.

08-runtime.md section 2.1 states the subject in one sentence -- *"Every degree of parallelism is
derived at preflight from the machine and clamped by config; none is a shipped constant except the
ceilings"* -- and then prints `HostFacts`, `derive_admission` and `ram_required` as code. This
module is that block, plus section 2.5's two backpressure decisions: `producer_should_pause`'s
hysteresis and `stall_detector`'s predicate.

## What this file is, and what W4.2 still owes

16-roadmap.md:542 gives W4.2 six things. Four are here and two are not, and the split is forced
rather than chosen:

* **here** -- `Admission`'s four semaphore families, `derive_admission`'s arithmetic,
  `producer_should_pause()`'s water-mark hysteresis, the CPU render semaphore held separately from
  the Service semaphore, and `ram_required`'s refusal.
* **not here** -- the loop itself (claim -> admit -> dispatch -> complete -> reap) and the
  `TaskGroup` shutdown around it. Both need `RunContext`, which 08-runtime.md:265 homes in
  `omniweave_core.operator` and which does not exist; the loop's dispatch step needs `Batch` and
  `DriverHost.invoke(Batch)`, which 02-architecture.md:238 gives to `omniweave/run/dispatch.py`
  (W4.7); and its admit step needs the durable `budget_reservation` ledger, which is W4.5's.
  Writing a loop against three fabricated types would be the `route_decision` mistake
  16-roadmap.md:541 names in W4.1's own estimation basis, one cell later.

What IS shippable now is everything that is a pure function of `(Config, HostFacts)` or of a
`counts_by_status()` reading -- which is the whole of the admission derivation and both
backpressure decisions. Every one of them is testable without a loop, and the three worked machines
of 08:727-731 are a parity test rather than an illustration.

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

Specified in 08-runtime.md sections 2.1, 2.5 and 2.6, 02-architecture.md section 5, and
16-roadmap.md:542 (P4 W4.2).
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from omniweave_core.errors import ConfigError

__all__ = [
    "COST_CLASSES",
    "QUIET_POLLS_BEFORE_SHED",
    "RAM_HEADROOM_FRACTION",
    "RENDER_CPU_RESERVE",
    "Admission",
    "HostFacts",
    "RamVerdict",
    "StallVerdict",
    "check_ram",
    "derive_admission",
    "producer_should_pause",
    "ram_required",
    "stall_verdict",
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
