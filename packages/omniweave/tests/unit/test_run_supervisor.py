"""Admission, backpressure and the stall verdict — against the three machines the plan works.

08-runtime.md section 2.1 does something unusual: it prints the derivation as code AND then works
it on three machines, in a table, with `ram_required` computed longhand for each. That table
(08:727-731) is the best test in the section, because it is the plan committing to an answer rather
than to an algorithm — and the third row is a REFUSAL, which is the only row that proves the
refusal is not decorative.

So `MACHINES` below transcribes all three and `test_the_three_worked_machines_derive_what_the_plan
_prints` asserts every cell: `render_sem`, the three worker counts, the three in-flight counts,
`ram_required` to the megabyte, and `ow doctor --runtime`'s verdict. A derivation that changed one
clamp would fail on the machine that clamp was written for.

## What is under test

Everything W4.2 owes, in two halves. The first is the derivation and the two backpressure
decisions -- pure functions of `(Config, HostFacts)` or of a `counts_by_status()` reading, tested
against the plan's own three machines. The second is the loop, and it is tested with **no SQLite,
no driver host and no event loop of its own**: `FakeQueue` is `Store`'s four methods over a list of
scripted claims, the `Dispatcher` is a function that returns `StepResult`s, and `asyncio.run` is
the only loop in the file. What that buys is that every assertion here is about the Supervisor's
decisions rather than about a store's timing.

The `Config` is a real one, loaded from the shipped `omniweave.toml.example` -- not a stub with
three keys. `derive_admission` reads four config keys and `LoopTimings.of` reads six, and a stub
would let all ten drift from the register that G18 gates.

Specified in 08-runtime.md sections 1.2, 2.1, 2.5, 2.6 and 8, 02-architecture.md sections 5.1 and
5.3, and 16-roadmap.md:542.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, cast

import pytest
from omniweave.run.supervisor import (
    COST_CLASSES,
    CRASH_DEGRADATION_KIND,
    LAG_DEGRADATION_KIND,
    QUIET_POLLS_BEFORE_SHED,
    RAM_HEADROOM_FRACTION,
    RENDER_CPU_RESERVE,
    Admission,
    HostFacts,
    LoopTimings,
    PauseGate,
    RunReport,
    Supervisor,
    check_ram,
    derive_admission,
    producer_should_pause,
    ram_required,
    stall_verdict,
)
from omniweave.run.supervisor import _ClassGate as ClassGate
from omniweave_core.config import KEYS, load
from omniweave_core.errors import ConfigError, StoreError
from omniweave_core.model.records import Producer
from omniweave_core.observe.degradation import DEGRADATION_KINDS
from omniweave_core.operator import (
    AdmissionView,
    CancelReason,
    CancelToken,
    Outcome,
    Roots,
    RunContext,
    StepResult,
)
from omniweave_core.work import WorkRow
from omniweave_ports.types import FailureClass, UnitRef

REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "omniweave.toml.example"
SUPERVISOR = Path(__file__).resolve().parents[2] / "src/omniweave/run/supervisor.py"

MB = 1_048_576
GB = 1024 * MB


@pytest.fixture(scope="session")
def cfg(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The shipped example, loaded. The defaults under test are `omniweave.toml.example`'s.

    08:713-714 names them — `[drivers] max_workers` at `{free = 4, local_compute = 4,
    billed_api = 8}` and `[budget] max_inflight` at `{free = 32, local_compute = 4,
    billed_api = 2}` — and the worked table is computed from those, so a test that supplied its
    own would be checking arithmetic against numbers the plan never used.
    """
    assert EXAMPLE.is_file(), EXAMPLE
    # `cwd` and `env` are keyword-only because `os.getcwd()` is semgrep-banned and the env is
    # injected for the same reason the Clock is (02 section 8.4 decision (e)). An empty scratch
    # cwd keeps the project-file walk from finding a real `omniweave.toml` above this checkout.
    return load(cwd=tmp_path_factory.mktemp("cfg"), env={}, explicit=EXAMPLE)


def sem_value(semaphore: asyncio.BoundedSemaphore) -> int:
    """A `BoundedSemaphore`'s initial value, read without acquiring it.

    `_value` is private and there is no public reader; acquiring to count would need a running
    loop and would leave the semaphore drained. The alternative — trusting the constructor — is
    what makes a clamp untested, so the private read is taken deliberately and in one place.
    """
    return semaphore._value


# ---------------------------------------------------------------------------
# the three worked machines — 08:727-731
# ---------------------------------------------------------------------------


class Machine(NamedTuple):
    """One row of 08:727-731, transcribed cell for cell."""

    name: str
    cpus: int
    ram_bytes: int
    render: int
    workers: tuple[int, int, int]
    inflight: tuple[int, int, int]
    required_mb: int
    verdict: str


# `memory_mb` is 08:717-723's roster: the per-class MAXIMUM of the enabled drivers' declared
# `[isolation] memory_mb`. 450 is `parse.pdf.pdfium`'s and the free class's maximum; 1,800 is
# `embed.local.bge`'s; 260 is `derive.entity.llm`'s. The plan's own arithmetic on the next line
# reads `workers[free]x450 + workers[local]x1800 + workers[billed]x260`.
ROSTER_MEMORY_MB = {"free": 450, "local_compute": 1_800, "billed_api": 260}

MACHINES = [
    Machine("4-core laptop, 16 GB", 4, 16 * GB, 2, (3, 2, 8), (32, 2, 2), 7_030, "ok"),
    Machine("16-core workstation, 64 GB", 16, 64 * GB, 14, (4, 4, 8), (32, 4, 2), 11_080, "ok"),
    Machine("8-core container, 4 GB cgroup", 8, 4 * GB, 6, (4, 4, 8), (32, 4, 2), 11_080, "refuse"),
]


@pytest.mark.parametrize("machine", MACHINES, ids=lambda m: m.name)
def test_the_three_worked_machines_derive_what_the_plan_prints(machine: Machine, cfg: Any) -> None:
    """08:727-731, every cell. The plan committed to answers and this is the collection of them.

    The megabyte totals are the plan's own longhand: 3x450 + 2x1800 + 8x260 = 7,030 MB on the
    laptop and 4x450 + 4x1800 + 8x260 = 11,080 MB on the other two. 08:729-731 rounds those to
    "7.0 GB" and "11.1 GB" in its prose; the exact products are asserted here, because a rounding
    is not a number a derivation can be checked against.
    """
    host = HostFacts(cpus=machine.cpus, ram_bytes=machine.ram_bytes, free_disk_bytes=100 * GB)
    admission = derive_admission(cfg, host)

    assert sem_value(admission.render_sem) == machine.render
    workers = tuple(sem_value(admission.worker_sem[name]) for name in COST_CLASSES)
    inflight = tuple(sem_value(admission.class_sem[name]) for name in COST_CLASSES)
    assert workers == machine.workers
    assert inflight == machine.inflight

    required = ram_required(dict(zip(COST_CLASSES, workers, strict=True)), ROSTER_MEMORY_MB)
    assert required == machine.required_mb * MB
    assert check_ram(required, host).verdict == machine.verdict


def test_the_container_row_refuses_and_names_the_knob() -> None:
    """08:733-737 is the whole argument for a refusal rather than a clamp.

    *"`os.process_cpu_count()` sees eight CPUs while the cgroup memory limit admits at most one
    local_compute worker, and a silent clamp would have made an operator's `max_workers = 4` a lie
    recorded nowhere."* The message has to name `[drivers] max_workers`, because 08:735-737 prints
    the operator's fix as an edit to that key — and a refusal that does not say what to change is
    one the operator routes around.
    """
    host = HostFacts(cpus=8, ram_bytes=4 * GB, free_disk_bytes=100 * GB)
    verdict = check_ram(11_080 * MB, host)
    assert verdict.refuses
    assert "[drivers] max_workers" in verdict.detail
    assert "3276" in verdict.detail or "3277" in verdict.detail  # 0.8 x 4 GB, in MB


def test_the_operators_own_fix_makes_the_container_row_fit() -> None:
    """08:736-737 prints the fix and its arithmetic: `{free = 2, local_compute = 1, billed_api =
    2}` gives 2x450 + 1x1800 + 2x260 = 3,220 MB — *"at the limit, and the operator's own
    decision."*"""
    host = HostFacts(cpus=8, ram_bytes=4 * GB, free_disk_bytes=100 * GB)
    required = ram_required({"free": 2, "local_compute": 1, "billed_api": 2}, ROSTER_MEMORY_MB)
    assert required == 3_220 * MB
    assert not check_ram(required, host).refuses


# ---------------------------------------------------------------------------
# the derivation's clamps, one at a time
# ---------------------------------------------------------------------------


def test_the_render_semaphore_is_olmocrs_cpus_minus_two(cfg: Any) -> None:
    """08:672-677, olmocr `pipeline.py:87` verbatim. `max(1, ...)` keeps a 1-core box alive."""
    assert RENDER_CPU_RESERVE == 2
    for cpus, expected in ((1, 1), (2, 1), (3, 1), (4, 2), (16, 14)):
        host = HostFacts(cpus=cpus, ram_bytes=64 * GB, free_disk_bytes=GB)
        assert sem_value(derive_admission(cfg, host).render_sem) == expected


def test_billed_api_workers_are_not_clamped_by_cpu_count(cfg: Any) -> None:
    """08:685 marks that row `# IO-bound` and applies no CPU clamp: eight in-flight HTTP calls do
    not need eight cores. The other two classes are clamped and the contrast is the assertion."""
    host = HostFacts(cpus=1, ram_bytes=64 * GB, free_disk_bytes=GB)
    admission = derive_admission(cfg, host)
    assert sem_value(admission.worker_sem["billed_api"]) == 8
    assert sem_value(admission.worker_sem["free"]) == 1
    assert sem_value(admission.worker_sem["local_compute"]) == 1


def test_local_compute_inflight_is_clamped_by_the_render_semaphore(cfg: Any) -> None:
    """08:691. A local-compute unit that rasterises cannot outrun the rasteriser, so admitting
    more units than render slots buys queueing and nothing else.

    `free` is deliberately NOT clamped this way: a free parse does not rasterise, and 32 in flight
    against a 2-slot renderer is the shipped default on a 4-core laptop.
    """
    host = HostFacts(cpus=4, ram_bytes=16 * GB, free_disk_bytes=GB)
    admission = derive_admission(cfg, host)
    assert sem_value(admission.class_sem["local_compute"]) == 2 == sem_value(admission.render_sem)
    assert sem_value(admission.class_sem["free"]) == 32


def test_the_four_families_are_four_and_the_render_one_is_not_a_service_one(cfg: Any) -> None:
    """08:674-676 — *"at 10.7 MB per rendered 192-DPI page, one shared semaphore renders faster
    than it evicts."* olmocr holds two `BoundedSemaphore`s at `pipeline.py:87-88` for this."""
    host = HostFacts(cpus=8, ram_bytes=32 * GB, free_disk_bytes=GB)
    admission = derive_admission(cfg, host)
    assert set(admission.class_sem) == set(admission.worker_sem) == set(COST_CLASSES)
    assert isinstance(admission.render_sem, asyncio.BoundedSemaphore)
    assert admission.render_sem not in admission.service_sem.values()


def test_every_service_semaphore_opens_at_zero(cfg: Any) -> None:
    """08:697 — `{n: asyncio.BoundedSemaphore(0) for n in cfg.services}`, refilled per section 3.4.

    Zero and not a guess: a semaphore opened at a number would let the first batch through before
    the model server has said how much it can take.
    """
    host = HostFacts(cpus=8, ram_bytes=32 * GB, free_disk_bytes=GB)
    admission = derive_admission(cfg, host)
    assert all(sem_value(sem) == 0 for sem in admission.service_sem.values())


def test_a_cost_class_missing_from_a_config_table_is_refused(cfg: Any) -> None:
    """Not a default. `billed_api` is 2 units in flight against `free`'s 32, an order of
    magnitude apart, so inventing one would silently admit thirty times the intended concurrency
    against a paid provider."""

    class Partial:
        def get(self, key: str) -> object:
            if key == "drivers.max_workers":
                return {"free": 4, "local_compute": 4}
            return cfg.get(key)

        def subkeys(self, prefix: str) -> tuple[str, ...]:
            return cfg.subkeys(prefix)

    host = HostFacts(cpus=8, ram_bytes=32 * GB, free_disk_bytes=GB)
    with pytest.raises(ConfigError, match="billed_api"):
        derive_admission(Partial(), host)


def test_the_admission_derivation_reads_no_auto_parallel_ceiling() -> None:
    """08:702 scopes `MAX_AUTO_PARALLEL` to the model server's `refill_target`.

    A ceiling applied in two places is a ceiling nobody can reason about, so its absence from this
    module is asserted rather than left to be noticed — the import would be the easy mistake, and
    96 is large enough that the clamp would never fire on any machine a test runs on.
    """
    path = Path(__file__).resolve().parents[2] / "src/omniweave/run/supervisor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "MAX_AUTO_PARALLEL" not in imported


# ---------------------------------------------------------------------------
# hysteresis — 08:880, :884-887
# ---------------------------------------------------------------------------


def admission_of(high: int, low: int) -> Admission:
    return Admission(
        class_sem={},
        worker_sem={},
        render_sem=asyncio.BoundedSemaphore(1),
        high_water=high,
        low_water=low,
    )


def test_the_water_marks_are_the_shipped_fifty_and_twenty_five_thousand(cfg: Any) -> None:
    host = HostFacts(cpus=8, ram_bytes=32 * GB, free_disk_bytes=GB)
    admission = derive_admission(cfg, host)
    assert (admission.high_water, admission.low_water) == (50_000, 25_000)


@pytest.mark.parametrize(
    ("claimable", "paused", "expected"),
    [
        (0, False, False),
        (49_999, False, False),
        (50_000, False, False),  # strictly above, so the mark itself does not pause
        (50_001, False, True),
        (50_001, True, True),
        (30_000, True, True),  # between the marks: whatever it already was
        (30_000, False, False),
        (25_001, True, True),
        (25_000, True, False),  # at the low mark, a paused producer resumes
        (0, True, False),
    ],
)
def test_the_producer_pauses_high_and_resumes_low(
    claimable: int, paused: bool, expected: bool
) -> None:
    """Two thresholds and a memory. Between the marks the answer is whatever it already was, which
    is the entire mechanism — 08:884 names the alternative's cost: *"A single threshold makes the
    producer oscillate at the boundary and turns `plan.pause`/`plan.resume` into noise."*"""
    assert producer_should_pause(claimable, admission_of(50_000, 25_000), paused=paused) is expected


def test_one_pause_drains_the_gap_the_plan_names() -> None:
    """08:885-886: *"the 2:1 gap means one pause drains 25,000 rows before discovery resumes."*"""
    admission = admission_of(50_000, 25_000)
    assert admission.high_water - admission.low_water == 25_000
    assert producer_should_pause(50_001, admission, paused=False)
    assert producer_should_pause(25_001, admission, paused=True)
    assert not producer_should_pause(25_000, admission, paused=True)


def test_one_threshold_is_refused_at_construction() -> None:
    """`low >= high` is not hysteresis, and a producer built on it oscillates by construction."""
    with pytest.raises(ConfigError, match="hysteresis"):
        admission_of(1_000, 1_000)
    with pytest.raises(ConfigError, match="hysteresis"):
        admission_of(1_000, 2_000)


# ---------------------------------------------------------------------------
# the stall that looks like health — 08:892-916
# ---------------------------------------------------------------------------

STALLED = {"pending": 50_000, "claimed": 0, "deferred": 12_000}


def test_a_full_claimable_set_with_nothing_running_sheds_after_two_polls() -> None:
    """08:892-897's failure: *"Nothing drains, nothing fails, no event fires."*

    15-observability.md section R2 records the symptom exactly — *"work rows are `deferred`, which
    is an `Outcome`, not a failure, so nothing is red"* — and 08:897 gives the answer: *"A loop
    that spins here for six hours is worse than one that stops, so it stops."*
    """
    verdict = stall_verdict(
        STALLED, completions_since_last_poll=0, swept=0, consecutive_quiet_polls=2
    )
    assert verdict.stalled
    assert "50000 claimable" in verdict.reason
    assert verdict.degradation_kind == "budget"


def test_one_quiet_poll_is_not_enough() -> None:
    """08:915 — *"Two poll cycles are required before the run ends."*"""
    assert QUIET_POLLS_BEFORE_SHED == 2
    assert not stall_verdict(
        STALLED, completions_since_last_poll=0, swept=0, consecutive_quiet_polls=1
    ).stalled


def test_a_single_slow_document_cannot_trip_it() -> None:
    """08:916 — the other half of the guard: *"`claimed == 0` is part of the predicate."*

    One 200-page document takes longer than `stall_poll_ms` to parse and commits nothing while it
    runs. Without the `claimed` conjunct that is indistinguishable from a stall, and the run would
    end in the middle of the only unit it had.
    """
    running = {"pending": 50_000, "claimed": 1}
    verdict = stall_verdict(
        running, completions_since_last_poll=0, swept=0, consecutive_quiet_polls=9
    )
    assert not verdict.stalled
    assert "claimed" in verdict.reason


def test_a_completion_or_a_sweep_resets_it() -> None:
    """Either one means the run is moving, and a moving run is not stalled however slowly."""
    for kwargs in (
        {"completions_since_last_poll": 1, "swept": 0},
        {"completions_since_last_poll": 0, "swept": 3},
    ):
        assert not stall_verdict(STALLED, consecutive_quiet_polls=9, **kwargs).stalled  # type: ignore[arg-type]


def test_an_empty_queue_is_not_a_stall() -> None:
    """Nothing claimable is a finished run, not a blocked one. Shedding here would turn every
    successful `ow ingest` into `run.status = 'partial'`."""
    done = {"done": 100_000, "deferred": 0}
    assert not stall_verdict(
        done, completions_since_last_poll=0, swept=0, consecutive_quiet_polls=9
    ).stalled


def test_a_queue_of_only_deferred_rows_is_not_claimable() -> None:
    """`deferred` is absent from the claim predicate (08:133-136), so it is not claimable — but it
    is exactly the state 08:892-894 describes, so the count is reported in the reason."""
    only_deferred = {"deferred": 50_000, "claimed": 0}
    verdict = stall_verdict(
        only_deferred, completions_since_last_poll=0, swept=0, consecutive_quiet_polls=9
    )
    assert not verdict.stalled
    assert "nothing is claimable" in verdict.reason


def test_failed_transient_rows_count_as_claimable() -> None:
    """The claim predicate is `status IN ('pending','failed_transient')`, so both are work this
    loop could take — and a queue of nothing but retryable failures that never retry is a stall."""
    retryable = {"failed_transient": 8, "claimed": 0}
    assert stall_verdict(
        retryable, completions_since_last_poll=0, swept=0, consecutive_quiet_polls=2
    ).stalled


def test_the_degradation_kind_comes_from_the_closed_set() -> None:
    """08:906-910: *"This document adds no `Degradation.kind` member."* `budget` when the dominant
    blocker is a denial, `quarantine` when it is a quarantined driver — both already exist."""
    quarantined = stall_verdict(
        STALLED,
        completions_since_last_poll=0,
        swept=0,
        consecutive_quiet_polls=2,
        dominant_blocker="quarantine",
    )
    assert quarantined.degradation_kind == "quarantine"


# ---------------------------------------------------------------------------
# host facts
# ---------------------------------------------------------------------------


def test_host_facts_measures_this_machine(tmp_path: Path) -> None:
    """The one function here that touches the environment, run against a real directory."""
    facts = HostFacts.measure(tmp_path)
    assert facts.cpus >= 1
    assert facts.free_disk_bytes > 0
    assert facts.ram_bytes >= 0
    assert facts.gpus == ()


def test_an_unknown_ram_reading_is_not_an_ok_verdict() -> None:
    """`_ram_bytes` returns 0 where the platform will not answer — Windows has no `os.sysconf`.

    Reading that as "it fits" would make 08:703's refusal vacuous on exactly the platform where
    the measurement was hardest, so `unknown` is a third verdict and `refuses` is false for it:
    a doctor that cannot measure must say so rather than pass or fail.
    """
    unknown = check_ram(99 * GB, HostFacts(cpus=4, ram_bytes=0, free_disk_bytes=GB))
    assert unknown.verdict == "unknown"
    assert not unknown.refuses
    assert "does not report physical RAM" in unknown.detail


def test_the_headroom_fraction_is_the_plans_zero_point_eight() -> None:
    assert RAM_HEADROOM_FRACTION == 0.8
    host = HostFacts(cpus=4, ram_bytes=10 * GB, free_disk_bytes=GB)
    assert not check_ram(8 * GB, host).refuses
    assert check_ram(8 * GB + 1, host).refuses


# ---------------------------------------------------------------------------
# The seam core names, checked from the side that can see both types
# ---------------------------------------------------------------------------


def test_the_derived_admission_satisfies_the_view_core_declares(cfg) -> None:
    """`RunContext.admission` is typed `AdmissionView`, and this is the only place both exist.

    `omniweave_core/operator.py` cannot import `Admission`: `tools/layers.toml` gives
    `omniweave_core` exactly `["omniweave_ports"]`, and `Admission`'s four families are
    `asyncio.BoundedSemaphore` instances, which `pyproject.toml` bans from core outright --
    *"INV-3: omniweave/run/ only. Core must not import a loop."* So core declares the two water
    marks it can name and this distribution, which imports both, is where the structural claim is
    checked. Without this test the narrowing is an assertion in a docstring.

    The check is `isinstance` and not an attribute scan because `AdmissionView` is
    `runtime_checkable` for exactly this: a seam should be able to assert what it was handed.
    """
    admission = derive_admission(cfg, HostFacts(cpus=8, ram_bytes=64 * GB, free_disk_bytes=GB))

    assert isinstance(admission, AdmissionView)
    assert admission.high_water == 50_000
    assert admission.low_water == 25_000

    # And the narrowing is real: the four families are NOT on the view, which is what keeps
    # `asyncio` out of `omniweave_core`'s annotations.
    assert set(AdmissionView.__annotations__) == {"high_water", "low_water"}
    families = {"class_sem", "worker_sem", "render_sem", "service_sem"}
    assert families <= {field.name for field in dataclasses.fields(admission)}


# ---------------------------------------------------------------------------
# W4.2's second half: the loop. 16-roadmap.md:542, 02-architecture.md:71
# ---------------------------------------------------------------------------


class FakeClock:
    """Real readings, injected. The loop reads `wall_ns` for the reaper and `monotonic_ns` for lag.

    Not a frozen clock: two of the four watchers measure an interval, and a clock that never moved
    would make `_lag_monitor` compute a negative lag and `_every` a cadence of nothing. What the
    injection buys here is 08:281-283's ban -- the module never calls `time` itself.
    """

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def wall_ns(self) -> int:
        return time.time_ns()


def work_row(row_id: int, *, cost_class: str = "free", key: str | None = "d" * 16) -> WorkRow:
    """One claimed row. The six fields the loop reads are the point; the rest satisfy the CHECK."""
    return WorkRow(
        id=row_id,
        unit_uri=f"file:///u{row_id}",
        unit_part="",
        operator="parse.pdf",
        op_version=1,
        cache_key="a" * 64,
        decision_id=None,
        sequence_id=None,
        driver="parse.pdf.pdfium",
        cost_class=cost_class,
        dispatch_key=key,
        service=None,
        staged_gen=None,
        status="claimed",
        failure_class=None,
        failure_message=None,
        retry_after=None,
        attempts_total=1,
        attempts_today=1,
        last_attempt_at=None,
        stale_since=None,
        claimed_by="host:1:2",
        claimed_gen=7,
        lease_expires=None,
        cost_micros=0,
        queued_ms=0,
        ran_ms=0,
        peak_rss_bytes=0,
        priority=0,
    )


def step_result(row: WorkRow, outcome: Outcome = Outcome.OK, **kwargs: object) -> StepResult:
    """A `StepResult` for one row -- the two fields a `WorkRow` cannot supply are the point.

    `unit` needs `content_sha256` and `byte_len` off the `unit` table and `identity` needs a
    `Producer`; neither is on a `WorkRow`, which is exactly why `Supervisor._abandon` cannot
    synthesise one for a row it claimed and never dispatched.
    """
    return StepResult(
        outcome=outcome,
        unit=UnitRef(uri=row.unit_uri, part=row.unit_part, content_sha256="b" * 64, byte_len=10),
        identity=Producer(
            operator=row.operator, op_version=row.op_version, code_fingerprint="f" * 64
        ),
        cache_key="a" * 64,
        **kwargs,  # type: ignore[arg-type]
    )


class FakeQueue:
    """`Store`'s four methods over a list of scripted claims. No SQLite anywhere in this file."""

    def __init__(
        self,
        claims: Sequence[Sequence[WorkRow]] = (),
        *,
        counts: Mapping[str, int] | None = None,
        superseded: frozenset[int] = frozenset(),
        reaps: int = 0,
    ) -> None:
        self.claims = [list(rows) for rows in claims]
        self.completed: list[tuple[int, int, str]] = []
        self.widths: list[int] = []
        self.reaped = 0
        self._counts = dict(counts or {})
        self._superseded = superseded
        self._reaps = reaps

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]:  # noqa: ARG002
        self.widths.append(batch)
        return self.claims.pop(0) if self.claims else []

    def complete(self, row_id: int, gen: int, result: StepResult) -> bool:
        self.completed.append((row_id, gen, str(result.outcome)))
        return row_id not in self._superseded

    def reap_expired_leases(self, now_ms: int) -> int:  # noqa: ARG002
        self.reaped += 1
        return self._reaps

    def counts_by_status(self) -> Mapping[str, int]:
        return dict(self._counts)


def loop_admission(*, inflight: int = 8, workers: int = 2) -> Admission:
    """One cost class, because the loop takes its family from the batch and not from a config."""
    return Admission(
        class_sem={"free": asyncio.BoundedSemaphore(inflight)},
        worker_sem={"free": asyncio.BoundedSemaphore(workers)},
        render_sem=asyncio.BoundedSemaphore(1),
        workers={"free": workers},
        inflight={"free": inflight},
    )


def loop_timings(**overrides: int) -> LoopTimings:
    """Fast cadences, so a watcher's tick is a test's tick and not a thirty-second wait."""
    values = {
        "lease_ms": 120_000,
        "lease_extend_ms": 60_000,
        "stall_poll_ms": 20,
        "deferred_sweep_ms": 10,
        "shutdown_grace_ms": 200,
        "loop_lag_max_ms": 250,
    }
    values.update(overrides)
    return LoopTimings(**values)  # type: ignore[arg-type]


def run_context(cancel: CancelToken, admission: Admission) -> RunContext:
    """A real `RunContext`. `limits`, `services` and `budget` are unread by the loop and are stubs.

    Not a fake context type: `RunContext` is frozen with `slots=True`, so every field must be
    supplied, and supplying them is what keeps this test honest about which five the loop reads --
    `generation`, `cancel`, `clock`, and nothing else.
    """
    return RunContext(
        run_id="r_0000000000000000000000000",
        generation=7,
        trigger="cli",
        roots=Roots(source=Path(), output=Path(), cache=Path()),
        config_digest="c" * 64,
        semantic_digest="s" * 64,
        policy_digest="p" * 64,
        pricebook_digest="b" * 64,
        catalog_digest="k" * 64,
        limits=cast("Any", object()),
        admission=cast("Any", admission),
        services=cast("Any", object()),
        budget=cast("Any", object()),
        cancel=cancel,
        clock=cast("Any", FakeClock()),
        events=cast("Any", object()),
    )


class Harness(NamedTuple):
    """One assembled Supervisor and the two things a test asserts against."""

    supervisor: Supervisor
    queue: FakeQueue
    events: list[tuple[str, Mapping[str, object]]]


def harness(
    queue: FakeQueue,
    *,
    dispatch: Any = None,
    admission: Admission | None = None,
    timings: LoopTimings | None = None,
    claim_batch: Mapping[str, int] | None = None,
    sweep: Any = None,
    worker: str = "host:1:2",
) -> Harness:
    events: list[tuple[str, Mapping[str, object]]] = []
    adm = admission if admission is not None else loop_admission()
    cancel = CancelToken("run", "r_0000000000000000000000000", cast("Any", FakeClock()))

    def emit(*, kind: object, fields: Mapping[str, object]) -> None:
        events.append((str(kind), dict(fields)))

    def answer(batch: Any) -> Sequence[StepResult]:
        return [step_result(row) for row in batch.rows]

    kwargs: dict[str, Any] = {}
    if sweep is not None:
        kwargs["sweep"] = sweep
    supervisor = Supervisor(
        run_context(cancel, adm),
        queue=cast("Any", queue),
        dispatch=dispatch if dispatch is not None else answer,
        admission=adm,
        timings=timings if timings is not None else loop_timings(),
        worker=worker,
        claim_batch=claim_batch or {"free": 256, "local_compute": 32, "billed_api": 8},
        emit=emit,
        **kwargs,
    )
    return Harness(supervisor, queue, events)


def kinds(events: Sequence[tuple[str, Mapping[str, object]]]) -> list[str]:
    return [kind for kind, _ in events]


def drive_sync(coro_fn: Any) -> Any:
    """`asyncio.run` over a zero-argument coroutine function. Named, because four tests use it."""
    return asyncio.run(coro_fn())


def drive_report(built: Harness) -> tuple[RunReport, FakeQueue, list[Any]]:
    """Run a harness and hand back all three of its observables."""
    report = asyncio.run(built.supervisor.run())
    return report, built.queue, built.events


def sleepy(ms: int) -> Any:
    """A dispatcher that takes `ms` to answer, so a watcher cadence is exercised against work.

    `time.sleep` and not `asyncio.sleep`: the `Dispatcher` is synchronous by contract and the loop
    calls it through `asyncio.to_thread`, so a blocking sleep here is what a real driver call is.
    """

    def dispatch(batch: Any) -> Sequence[StepResult]:
        time.sleep(ms / 1000)
        return [step_result(row) for row in batch.rows]

    return dispatch


# -- claim -> admit -> dispatch -> complete -> reap --------------------------


def test_the_loop_claims_dispatches_and_completes_every_row() -> None:
    """The five steps, end to end, with no SQLite and no driver. 16-roadmap.md:542."""
    queue = FakeQueue([[work_row(1), work_row(2)], [work_row(3)]])
    supervisor, _, events = harness(queue)

    report = asyncio.run(supervisor.run())

    assert report.status == "done"
    assert (report.claimed, report.batches, report.completed) == (3, 2, 3)
    assert [row_id for row_id, _, _ in queue.completed] == [1, 2, 3]
    assert {gen for _, gen, _ in queue.completed} == {7}, "the run's generation, on every commit"
    assert kinds(events).count("work.claim") == 3
    assert kinds(events).count("work.complete") == 3


def test_one_transition_per_unit_and_the_batch_is_invisible() -> None:
    """I24, as 08:782-784 states the test: a batch of 32 is 32 transitions and 32 events.

    *"One `RESULT` frame per unit, one `work` transition per unit, one spend row per unit, one
    `unit` span per unit"* -- so a batch that produced 31 of anything would have become visible in
    the work table, and no event this loop emits carries a batch identity.
    """
    rows = [work_row(index) for index in range(1, 33)]
    queue = FakeQueue([rows])
    supervisor, _, events = harness(queue, admission=loop_admission(inflight=32, workers=1))

    report = asyncio.run(supervisor.run())

    assert report.batches == 1, "one dispatch_key, one batch"
    assert len(queue.completed) == 32
    assert kinds(events).count("work.complete") == 32
    assert not any("invoke_id" in fields for _, fields in events)
    assert not any("batch_index" in fields for _, fields in events)


def test_a_dispatcher_that_answers_for_fewer_rows_is_refused() -> None:
    """A short answer leaves a claimed row to its lease, which is the batch becoming visible."""

    def short(batch: Any) -> Sequence[StepResult]:
        return [step_result(batch.rows[0])]

    queue = FakeQueue([[work_row(1), work_row(2)]])
    supervisor, _, events = harness(queue, dispatch=short)

    report = asyncio.run(supervisor.run())

    assert queue.completed == [], "nothing is committed from a mis-paired answer"
    assert report.crashed == 2, "the refusal is a RouteError, and one crash costs one batch"
    message = next(fields["message"] for kind, fields in events if kind == "run.degraded")
    assert "RouteError" in str(message)


def test_a_batch_that_mixes_cost_classes_is_refused() -> None:
    """`rows[0].cost_class` on a mixed batch admits billed units against the free semaphore."""
    rows = [work_row(1), work_row(2, cost_class="billed_api")]
    queue = FakeQueue([rows])
    supervisor, _, events = harness(queue)

    report = asyncio.run(supervisor.run())

    assert report.completed == 0
    assert report.crashed == 2
    message = str(next(fields["message"] for kind, fields in events if kind == "run.degraded"))
    assert "RouteError" in message


def test_a_superseded_completion_is_counted_and_never_raised() -> None:
    """08:2486: `False` means one thing -- the commit predicate matched zero rows."""
    queue = FakeQueue([[work_row(1), work_row(2)]], superseded=frozenset({2}))
    supervisor, _, events = harness(queue)

    report = asyncio.run(supervisor.run())

    assert (report.completed, report.superseded) == (1, 1)
    cancels = [fields for kind, fields in events if kind == "work.cancel"]
    assert cancels == [{"work_id": 2, "generation": 7}], "08:2413's work.cancel{work_id, gen}"


def test_a_dispatcher_that_raises_costs_one_batch_and_not_the_run() -> None:
    """02:653: *"a worker_loop catches BaseException and NEVER propagates, so one crash costs one
    unit."*"""
    calls: list[int] = []

    def flaky(batch: Any) -> Sequence[StepResult]:
        calls.append(batch.size)
        if batch.rows[0].id == 1:
            raise RuntimeError("the driver host went away")
        return [step_result(row) for row in batch.rows]

    queue = FakeQueue([[work_row(1)], [work_row(2)]])
    supervisor, _, events = harness(queue, dispatch=flaky)

    report = asyncio.run(supervisor.run())

    assert report.status == "done", "one batch died; the run did not"
    assert (report.crashed, report.completed) == (1, 1)
    assert calls == [1, 1], "the second batch still ran"
    degraded = [fields for kind, fields in events if kind == "run.degraded"]
    assert degraded[0]["degradation_kind"] == CRASH_DEGRADATION_KIND
    assert "RuntimeError" in str(degraded[0]["message"])


def test_a_worker_loop_does_not_swallow_its_own_cancellation() -> None:
    """The one qualification `Supervisor`'s docstring makes to 02:653's sentence.

    `asyncio.CancelledError` inherits from `BaseException`, so a `worker_loop` that literally
    caught `BaseException` and never propagated would swallow the cancellation its own `TaskGroup`
    shuts down with. The run would hang at exactly the moment the structure exists for, which is
    what this asserts by hanging the whole test if the re-raise is removed.
    """
    started = asyncio.Event()

    async def drive() -> RunReport:
        queue = FakeQueue([[work_row(index)] for index in range(1, 40)])
        supervisor, _, _ = harness(queue, dispatch=sleepy(5))
        running = asyncio.create_task(supervisor.run())
        await asyncio.sleep(0.01)
        started.set()
        supervisor.interrupt()
        return await asyncio.wait_for(running, timeout=10)

    report = drive_sync(drive)

    assert started.is_set()
    assert report.status == "interrupted"


# -- what ends a run --------------------------------------------------------


def test_an_interrupt_leaves_interrupted_and_abandons_to_the_lease_reaper() -> None:
    """08 section 1.2: `cancelled` and a reap are the same three effects, so the reaper is enough.

    `Supervisor._abandon` carries the argument: a `StepResult` needs `content_sha256`, `byte_len`
    and a `Producer`, and a `WorkRow` carries none of the three, so the Supervisor cannot write
    08:2409's `StepResult(outcome=CANCELLED)` for a row it never dispatched. What it can do is
    leave it, which reaches the same `pending`-with-`attempts_total`-decremented state.
    """

    async def drive() -> tuple[RunReport, list[tuple[str, Mapping[str, object]]]]:
        loop = asyncio.get_running_loop()
        held: dict[str, Supervisor] = {}

        def interrupting(batch: Any) -> Sequence[StepResult]:
            # From a worker THREAD, so through the loop: `interrupt()` wakes an `asyncio.Event`,
            # and `loop.add_signal_handler` is what guarantees the loop thread in production.
            loop.call_soon_threadsafe(held["it"].interrupt)
            time.sleep(0.03)
            return [step_result(row) for row in batch.rows]

        queue = FakeQueue([[work_row(index)] for index in range(1, 12)])
        supervisor, _, events = harness(
            queue, dispatch=interrupting, admission=loop_admission(workers=1)
        )
        held["it"] = supervisor
        report = await asyncio.wait_for(supervisor.run(), timeout=10)
        assert supervisor.interrupt() is False, "the second finds a latch already present"
        return report, events

    report, events = drive_sync(drive)

    assert report.status == "interrupted"
    assert report.cancelled is CancelReason.INTERRUPT
    assert report.abandoned >= 1, "the inbox bounds the exposure; the reaper takes these rows"
    assert kinds(events).count("work.cancel") == report.abandoned


def test_the_stall_detector_sheds_the_run_as_partial() -> None:
    """08:892-897's failure: a full claimable set with nothing admissible. Nothing is red."""
    counts = {
        "pending": 50_000,
        "claimed": 0,
        "deferred": 2_900,
        "done": 0,
        "failed_transient": 0,
        "failed_permanent": 0,
    }
    queue = FakeQueue([], counts=counts)
    supervisor, _, events = harness(
        queue, timings=loop_timings(stall_poll_ms=5, deferred_sweep_ms=400)
    )

    report = asyncio.run(supervisor.run())

    assert report.status == "partial", "08:906 -- a partial run is a result and not an error"
    assert report.stalled and report.cancelled is CancelReason.SHED
    assert report.polls >= QUIET_POLLS_BEFORE_SHED
    assert [record.kind for record in report.degradations] == ["budget"]
    assert "run.degraded" in kinds(events)


def test_a_stall_with_no_deferred_rows_is_a_quarantine() -> None:
    """08:906-910's other member. The two are what `counts_by_status()` can tell apart."""
    counts = {
        "pending": 12,
        "claimed": 0,
        "deferred": 0,
        "done": 0,
        "failed_transient": 0,
        "failed_permanent": 0,
    }
    supervisor, _, _ = harness(
        FakeQueue([], counts=counts),
        timings=loop_timings(stall_poll_ms=5, deferred_sweep_ms=400),
    )

    report = asyncio.run(supervisor.run())

    assert report.stalled
    assert [record.kind for record in report.degradations] == ["quarantine"]


def test_both_degradation_kinds_this_module_uses_are_in_the_closed_twenty_seven() -> None:
    """15's rule: *"extended by literal, never re-invented per layer."* This module adds none."""
    assert LAG_DEGRADATION_KIND in DEGRADATION_KINDS
    assert CRASH_DEGRADATION_KIND in DEGRADATION_KINDS
    assert len(DEGRADATION_KINDS) == 27


def test_the_report_status_comes_from_the_cause_and_not_from_a_count() -> None:
    """A run full of failures is still `done`: a failed unit is a `work` row, not a run status."""
    queue = FakeQueue([[work_row(1)]])

    def failing(batch: Any) -> Sequence[StepResult]:
        return [
            step_result(row, Outcome.FAILED_PERMANENT, failure_class=FailureClass.DRIVER_BUG)
            for row in batch.rows
        ]

    report = asyncio.run(harness(queue, dispatch=failing).supervisor.run())

    assert report.status == "done"
    assert report.completed == 1
    assert queue.completed == [(1, 7, "failed_permanent")]


def test_a_budget_denial_emits_work_defer_beside_work_complete() -> None:
    """08:695: `DEFERRED_BUDGET` is *"NOT a failure"*, and it has its own event.

    **`retry_after` is zero and no shipped type can make it anything else.** `work.defer` declares
    the field (`tools/events.toml`), 08 section 1.2's table gives a `deferred` row *"the sweeper's
    backoff"*, and 08:167 gives its arithmetic -- `min(60_000 x 2^(n-1), 1_800_000)` over the
    in-run defer streak. But `StepResult.__post_init__` refuses `retry_after_ms` on every outcome
    but `failed_transient`, and `SqliteStore.complete_plan` binds `:retry_after` from that same
    field, so the number has no channel from the denial to the row. Filed; the zero is emitted
    rather than invented, and the refusal is asserted below so the gap cannot close silently.
    """
    queue = FakeQueue([[work_row(1)]])

    def denied(batch: Any) -> Sequence[StepResult]:
        return [
            step_result(row, Outcome.DEFERRED_BUDGET, deferred_dim="micros") for row in batch.rows
        ]

    _, _, events = drive_report(harness(queue, dispatch=denied))

    assert kinds(events).count("work.complete") == 1, "a defer is a completion, not a failure"
    defer = next(fields for kind, fields in events if kind == "work.defer")
    assert defer == {"work_id": 1, "dim": "micros", "retry_after": 0}

    with pytest.raises(ValueError, match="meaningful only for failed_transient"):
        step_result(
            work_row(1), Outcome.DEFERRED_BUDGET, deferred_dim="micros", retry_after_ms=60_000
        )


# -- one Supervisor per process ---------------------------------------------


def test_a_second_supervisor_in_one_process_is_refused_before_the_loop_opens() -> None:
    """02:727, startup step 9: *"an assertion, not a convention."*"""
    counts = {
        "pending": 9,
        "claimed": 0,
        "deferred": 0,
        "done": 0,
        "failed_transient": 0,
        "failed_permanent": 0,
    }

    async def drive() -> str:
        first = harness(
            FakeQueue([], counts=counts),
            timings=loop_timings(stall_poll_ms=4_000, deferred_sweep_ms=200),
            worker="host:1:1",
        ).supervisor
        running = asyncio.create_task(first.run())
        await asyncio.sleep(0.01)
        second = harness(FakeQueue([]), worker="host:1:2").supervisor
        with pytest.raises(StoreError) as caught:
            await second.run()
        await asyncio.wait_for(running, timeout=10)
        return str(caught.value)

    message = drive_sync(drive)

    assert "host:1:1" in message, "the refusal names the holder"
    assert "one Supervisor per process" in message


def test_the_exclusion_is_released_so_a_later_run_is_admitted() -> None:
    """A latch that did not release would make the second `ow ingest` in one process impossible."""
    first = asyncio.run(harness(FakeQueue([[work_row(1)]])).supervisor.run())
    second = asyncio.run(harness(FakeQueue([[work_row(2)]])).supervisor.run())

    assert (first.completed, second.completed) == (1, 1)


# -- the claim width --------------------------------------------------------


def test_the_claim_asks_for_the_narrowest_class_because_it_cannot_name_one() -> None:
    """`Store.claim` takes no cost class, so 256 free rows could come back as 256 billed ones."""
    queue = FakeQueue([[work_row(1)]])
    supervisor, _, _ = harness(
        queue, claim_batch={"free": 256, "local_compute": 32, "billed_api": 8}
    )

    asyncio.run(supervisor.run())

    assert set(queue.widths) == {8}, "billed_api's 8, not free's 256"


# -- the reaper and the sweeper ---------------------------------------------


def test_a_sweep_in_flight_when_the_reaper_is_cancelled_is_still_counted() -> None:
    """D606. A sweep runs in a thread, and the store commits it whether or not the task awaiting it
    survives. Cancelling the reaper mid-sweep dropped that sweep's count: the rows were reaped and
    the report said they were not. `test_the_reaper_sweeps_and_its_count_reaches_the_report` below
    caught it once in a loaded run as 20 against 24; this makes the race happen every time."""
    started, release = threading.Event(), threading.Event()

    class Blocking(FakeQueue):
        def reap_expired_leases(self, now_ms: int) -> int:
            started.set()
            release.wait(5)
            return super().reap_expired_leases(now_ms)

    queue = Blocking(reaps=4)
    supervisor, _, _ = harness(queue, timings=loop_timings(lease_extend_ms=5))

    async def scenario() -> None:
        reaper = asyncio.create_task(supervisor._reaper())
        await asyncio.to_thread(started.wait, 5)
        reaper.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await reaper

    asyncio.run(scenario())
    assert queue.reaped == 1
    assert supervisor._reaped == 4, "the sweep ran in the store; its rows are the report's"


def test_the_reaper_sweeps_and_its_count_reaches_the_report() -> None:
    """07:59's `reap_expired_leases(now_ms)`, on `LoopTimings`' cadence argument."""
    counts = {
        "pending": 3,
        "claimed": 0,
        "deferred": 1,
        "done": 0,
        "failed_transient": 0,
        "failed_permanent": 0,
    }
    queue = FakeQueue([[work_row(index)] for index in range(1, 7)], counts=counts, reaps=4)
    supervisor, _, _ = harness(
        queue,
        dispatch=sleepy(10),
        timings=loop_timings(stall_poll_ms=4_000, lease_extend_ms=5),
    )

    report = asyncio.run(supervisor.run())

    assert queue.reaped >= 1, "the reaper swept on its own cadence while the loop drained"
    assert report.reaped == queue.reaped * 4


def test_the_default_sweeper_is_disclosed_rather_than_reported_as_a_zero() -> None:
    """`Sweeper`'s argument: an absent sweeper and an empty one are the same stall input."""
    report = asyncio.run(harness(FakeQueue([[work_row(1)]])).supervisor.run())

    assert report.swept == 0
    assert report.sweeper_wired is False
    assert report.complete is False


def test_a_wired_sweeper_is_called_and_its_count_is_reported() -> None:
    """The seam W4.5's ledger fills. What it returns is `stall_verdict`'s fourth conjunct."""
    calls: list[int] = []

    def sweep(now_ms: int) -> int:
        calls.append(now_ms)
        return 2

    counts = {
        "pending": 5,
        "claimed": 0,
        "deferred": 5,
        "done": 0,
        "failed_transient": 0,
        "failed_permanent": 0,
    }
    supervisor, _, _ = harness(
        FakeQueue([[work_row(index)] for index in range(1, 7)], counts=counts),
        dispatch=sleepy(10),
        timings=loop_timings(stall_poll_ms=4_000, deferred_sweep_ms=5),
        sweep=sweep,
    )

    report = asyncio.run(supervisor.run())

    assert calls, "the backstop poll ran"
    assert report.swept == 2 * len(calls)
    assert report.sweeper_wired is True and report.complete is True
    assert report.stalled is False, "a sweeper that returns rows is not a quiet poll"


# -- LoopTimings and the three keys it declares -----------------------------


def test_the_three_keys_08_introduces_are_declared_where_their_reader_is(cfg: Any) -> None:
    """D137 and D149: the cell that reads a key is the cell that declares it.

    08-runtime.md:2598-2606 introduces `shutdown_grace_ms`, `deferred_sweep_ms` and
    `stall_poll_ms` under *"New keys this document introduces"*, and until W4.2's loop none of the
    three was in `omniweave_core.config.KEYS`, `omniweave.toml.example` or the axis register --
    so `Config.get("runtime.stall_poll_ms")` raised and no `OMNIWEAVE_*` twin existed.
    """
    for name, default in (
        ("runtime.shutdown_grace_ms", 5000),
        ("runtime.deferred_sweep_ms", 5000),
        ("runtime.stall_poll_ms", 30000),
    ):
        assert cfg.get(name) == default
        key = KEYS[name]
        assert key.axis == "operational", "08:2598 -- each `operational` by section 4.3's rule"
        assert key.env == "OMNIWEAVE_" + name.upper().replace(".", "_")


def test_loop_timings_reads_the_six_keys_from_the_shipped_example(cfg: Any) -> None:
    """`of()` is the only place the six names are spelled, so this is the whole mapping."""
    timings = LoopTimings.of(cfg)

    assert timings == LoopTimings(
        lease_ms=120_000,
        lease_extend_ms=60_000,
        stall_poll_ms=30_000,
        deferred_sweep_ms=5_000,
        shutdown_grace_ms=5_000,
        loop_lag_max_ms=250,
    )


def test_loop_timings_carries_no_defaults_at_all() -> None:
    """A default here is the second home that declaring the key in `config.py` exists to stop."""
    for field_ in dataclasses.fields(LoopTimings):
        assert field_.default is dataclasses.MISSING, field_.name
        assert field_.default_factory is dataclasses.MISSING, field_.name


@pytest.mark.parametrize(
    "name", ["lease_ms", "lease_extend_ms", "stall_poll_ms", "deferred_sweep_ms"]
)
def test_a_cadence_of_zero_is_a_config_error_naming_the_knob(name: str) -> None:
    """A zero cadence is a spin and a negative one is a wait that never ends."""
    values = {
        "lease_ms": 1,
        "lease_extend_ms": 1,
        "stall_poll_ms": 1,
        "deferred_sweep_ms": 1,
        "shutdown_grace_ms": 1,
        "loop_lag_max_ms": 1,
    }
    values[name] = 0
    with pytest.raises(ConfigError) as caught:
        LoopTimings(**values)  # type: ignore[arg-type]
    assert name in str(caught.value)
    assert name in caught.value.fix


# -- the class gate: units, not batches -------------------------------------


def test_a_batch_takes_one_permit_per_unit_because_the_family_counts_units() -> None:
    """08:687: *"These count UNITS, not processes: one worker process may hold a Batch of 256."*"""

    async def check() -> tuple[int, int]:
        sem = asyncio.BoundedSemaphore(8)
        gate = ClassGate(sem, 8)
        async with gate.hold(5) as taken:
            free_inside = sem._value  # the only way to read a semaphore's slack
        return taken, free_inside

    taken, free_inside = asyncio.run(check())

    assert taken == 5
    assert free_inside == 3, "five of eight permits were held, not one"


def test_the_permit_count_is_clamped_to_the_bound_the_shipped_defaults_exceed() -> None:
    """`[runtime.claim] batch.free = 256` against `[budget] max_inflight.free = 32`.

    A literal permit-per-unit acquisition could never be satisfied by its own configuration: the
    first free batch would wait for 256 permits against a semaphore that can issue 32. The clamp
    says the truthful thing instead -- a batch at or above the bound saturates its class.
    """

    async def check() -> int:
        gate = ClassGate(asyncio.BoundedSemaphore(32), 32)
        async with gate.hold(256) as taken:
            return taken

    assert asyncio.run(check()) == 32


def test_two_batches_cannot_deadlock_on_a_partial_acquisition() -> None:
    """Two batches of 20 against a bound of 32 can hold 16 each and wait forever without the turn.

    The turn lock is what makes the holder the only coroutine that waits for permits while holding
    permits; every other holder is running and will release. Without it this test hangs.
    """

    async def check() -> list[str]:
        order: list[str] = []
        gate = ClassGate(asyncio.BoundedSemaphore(32), 32)

        async def take(name: str) -> None:
            async with gate.hold(20):
                order.append(name)
                await asyncio.sleep(0)

        await asyncio.wait_for(asyncio.gather(take("a"), take("b")), timeout=5)
        return order

    assert sorted(asyncio.run(check())) == ["a", "b"]


# -- the pause gate ---------------------------------------------------------


def test_the_pause_gate_emits_on_the_transition_and_not_on_every_poll() -> None:
    """08:884-886: a single threshold *"turns `plan.pause`/`plan.resume` into noise"*."""
    events: list[tuple[str, Mapping[str, object]]] = []
    claimable = [10, 60_000, 60_000, 40_000, 20_000, 20_000]

    def emit(*, kind: object, fields: Mapping[str, object]) -> None:
        events.append((str(kind), dict(fields)))

    gate = PauseGate(
        lambda: claimable.pop(0), admission=admission_of(50_000, 25_000), emit=cast("Any", emit)
    )
    answers = [gate() for _ in range(6)]

    assert answers == [False, True, True, True, False, False]
    assert kinds(events) == ["plan.pause", "plan.resume"], "two crossings, two events"
    assert gate.paused is False


def test_each_pause_event_names_the_threshold_it_crossed() -> None:
    """08:885's 2:1 gap *"is only legible if each event names the threshold it answers to"*."""
    events: list[tuple[str, Mapping[str, object]]] = []
    claimable = [60_000, 20_000]

    def emit(*, kind: object, fields: Mapping[str, object]) -> None:
        events.append((str(kind), dict(fields)))

    gate = PauseGate(
        lambda: claimable.pop(0), admission=admission_of(50_000, 25_000), emit=cast("Any", emit)
    )
    gate()
    gate()

    assert events[0] == ("plan.pause", {"claimable": 60_000, "high_water": 50_000})
    assert events[1] == ("plan.resume", {"claimable": 20_000, "low_water": 25_000})


def test_the_supervisor_hands_the_producer_a_gate_carrying_this_runs_hysteresis() -> None:
    """`discover.Backpressure.pause`'s docstring: the state *"lives on the Supervisor across
    calls"*."""
    supervisor, _, _ = harness(FakeQueue([]))
    gate = supervisor.pause_gate(lambda: 60_000)

    assert gate() is True
    assert gate.paused is True
    assert isinstance(gate, PauseGate)


# -- the derivation keeps what it derived -----------------------------------


def test_the_derivation_records_the_integers_it_derived(cfg: Any) -> None:
    """A `BoundedSemaphore` will not say what it was built with, and three callers need to know."""
    host = HostFacts(cpus=16, ram_bytes=64 * GB, free_disk_bytes=GB)
    admission = derive_admission(cfg, host)

    assert dict(admission.workers) == {"free": 4, "local_compute": 4, "billed_api": 8}
    assert dict(admission.inflight) == {"free": 32, "local_compute": 4, "billed_api": 2}
    memory_mb = {"free": 450, "local_compute": 1800, "billed_api": 260}
    assert ram_required(admission.workers, memory_mb) == 11_080 * MB  # 08:730 workstation
    assert set(admission.workers) == set(COST_CLASSES)


# -- the render slot --------------------------------------------------------


def test_render_takes_the_cpu_semaphore_and_never_the_service_one() -> None:
    """08:674-676: *"at 10.7 MB per rendered 192-DPI page, one shared semaphore renders faster
    than it evicts."*"""
    admission = loop_admission()
    supervisor, _, _ = harness(FakeQueue([]), admission=admission)

    async def check() -> int:
        async with supervisor.render():
            return admission.render_sem._value  # reading the slack IS the test

    assert asyncio.run(check()) == 0, "the one render slot was held"


# -- the two deferred imports -----------------------------------------------


def test_importing_the_package_loads_neither_the_dispatcher_nor_the_operator_module() -> None:
    """`run/__init__.py`'s cost argument, asserted from the side that can break it.

    *"Re-exporting its names would make `from omniweave.run import Admission` -- which is a pure
    arithmetic over `(Config, HostFacts)` -- pay for a driver host."* The loop landing in the same
    module can defeat that from the other side, so the two expensive imports are function-scoped.
    A subprocess, because this test session has already imported both.
    """
    probe = (
        "import sys, omniweave.run;"
        "print(','.join(m for m in "
        "('omniweave.run.dispatch','omniweave_core.operator','omniweave_core.host.subproc') "
        "if m in sys.modules))"
    )
    done = subprocess.run(  # noqa: S603 -- this interpreter, a literal argv, no shell.
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert done.stdout.strip() == "", f"loaded eagerly: {done.stdout.strip()}"


def test_the_module_scope_import_set_is_exactly_the_cheap_ones() -> None:
    """The other half of the same claim: what IS at module scope, and no more.

    `omniweave_core.events` (~5 ms) and `omniweave_core.observe.degradation` (~2 ms) are taken
    eagerly and the module docstring says so with the numbers; `omniweave_core.errors` is free.
    Everything else a loop needs is either `TYPE_CHECKING`-only or function-scoped.
    """
    tree = ast.parse(SUPERVISOR.read_text(encoding="utf-8"), filename=str(SUPERVISOR))
    eager = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert eager == {
        "__future__",
        "collections.abc",
        "contextlib",
        "dataclasses",
        "pathlib",
        "types",
        "typing",
        "omniweave_core.errors",
        "omniweave_core.events",
        "omniweave_core.observe.degradation",
    }


def test_the_only_mutable_module_state_is_the_process_latch() -> None:
    """08:291 bans module globals in `omniweave/run/`, and `_Exclusion` is the one exception.

    The ban's three recorded bugs are first-caller-wins caches that made a second run see the first
    run's data. This object holds no run's data: its entire job is to refuse the second run. The
    test is that nothing else at module scope is mutable, so the exception stays one.
    """
    module = sys.modules[Supervisor.__module__]
    mutable = {
        name: value
        for name, value in vars(module).items()
        if not name.startswith("__")
        and isinstance(value, (list, dict, set))
        and not isinstance(value, type)
    }

    assert mutable == {}, mutable
    assert type(module._ONE_PER_PROCESS).__name__ == "_Exclusion"
