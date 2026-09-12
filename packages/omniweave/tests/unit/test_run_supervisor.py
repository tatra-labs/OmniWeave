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

## What is under test and what is not

W4.2's loop is not here and `supervisor.py`'s own docstring says why: it needs `RunContext`,
`Batch` and the budget ledger, none of which exist. What IS here is everything that is a pure
function of `(Config, HostFacts)` or of a `counts_by_status()` reading, which is the whole of the
admission derivation and both of section 2.5's backpressure decisions.

The `Config` is a real one, loaded from the shipped `omniweave.toml.example` — not a stub with
three keys. `derive_admission` reads four config keys and a stub would let all four drift from the
register that G18 gates.

Specified in 08-runtime.md sections 2.1, 2.5 and 2.6, and 16-roadmap.md:542.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from omniweave.run.supervisor import (
    COST_CLASSES,
    QUIET_POLLS_BEFORE_SHED,
    RAM_HEADROOM_FRACTION,
    RENDER_CPU_RESERVE,
    Admission,
    HostFacts,
    check_ram,
    derive_admission,
    producer_should_pause,
    ram_required,
    stall_verdict,
)
from omniweave_core.config import load
from omniweave_core.errors import ConfigError
from omniweave_core.operator import AdmissionView

REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "omniweave.toml.example"

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
