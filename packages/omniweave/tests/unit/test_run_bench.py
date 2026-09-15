"""`omniweave.run.bench` -- the closed set of thirteen subjects and the one that runs.

12-performance.md section 7.1 names this module and fixes its shape: *"the registry is one function
per subject in `packages/omniweave/src/omniweave/run/bench.py`, so adding a subject is one function
plus one row in the closed set."* Two properties follow and both are asserted here:

1. **The set is closed and this file is the closure.** Section 7.1 states its own cardinality --
   *"The thirteen above are the complete set"* -- so a fourteenth subject is a plan edit. A registry
   that could grow without one is a registry nobody can read the plan against.
2. **A subject either runs or names what is in the way.** `blocked_by` is not a TODO; it is the
   thing that has to land first. A subject that claimed to run and returned nothing would be the
   `--warn-only` 11-repo-layout.md section 6.8 refuses, wearing a different hat.

**No test here runs a million units.** Section 7.1 asks for 1M and `tools/ow_bench.py`'s default is
20,000 for a measured reason; these tests run 40 to 300, where every mechanism resolves and the
suite stays a suite.

Specified in 12-performance.md sections 1.2, 7.1, 7.2 and 7.4 and rows B22 and F8,
08-runtime.md:2715, and 16-roadmap.md:550 (P4 W4.10).
"""

from __future__ import annotations

import asyncio  # noqa: TID251 -- a test that drives the loop; the ban scopes packages/*/src.
import math
import re
from pathlib import Path
from typing import Any

import pytest
from omniweave.run import bench
from omniweave.run import supervisor as sup
from omniweave_core import config as configmod
from omniweave_core.clock import SystemClock
from omniweave_core.errors import ConfigError, StoreError
from omniweave_core.store import sqlite as ow

SMALL = 40
"""Units per run here. Enough that the claimer makes several passes; small enough to be a second."""

QUIET_TAIL = sup.QUIET_POLLS_BEFORE_SHED + 1
"""Empty claims the claimer issues before it decides the run is over. 08:915 requires two cycles.

Imported rather than written as `3`: it is the Supervisor's constant, and a test that transcribed
it would pass on the day the Supervisor changed it and the bench's counts moved."""

PLAN_SECTION_7_1 = (
    "pacer",
    "cold",
    "scheduler",
    "inproc",
    "parse",
    "route",
    "service",
    "embed",
    "query",
    "encoding",
    "incremental",
    "compile",
    "rss",
)
"""Section 7.1's table, in its own order. Pinned as a literal: see this file's docstring."""


def _config(root: Path) -> Any:
    """Built-in defaults against an empty environment and a directory with no `omniweave.toml`."""
    return configmod.load(cwd=root, env={})


def _run(root: Path, *, units: int = SMALL, storage: str = "unknown") -> Any:
    return asyncio.run(bench.scheduler(root, units=units, config=_config(root), storage=storage))


# ---------------------------------------------------------------------------------------------
# 1. The closed set
# ---------------------------------------------------------------------------------------------


def test_the_registry_is_section_7_1s_thirteen_rows_in_section_7_1s_order() -> None:
    """A fourteenth subject is a plan edit, so a fourteenth row must be a red test first."""
    assert tuple(bench.SUBJECTS) == PLAN_SECTION_7_1
    assert len(bench.SUBJECTS) == 13


def test_every_subject_names_itself_and_carries_all_three_of_its_cells() -> None:
    """`measures`, `fixture` and `writes` are transcribed, not summarised. Empty is a paraphrase."""
    for name, subject in bench.SUBJECTS.items():
        assert subject.name == name
        assert subject.measures.strip()
        assert subject.fixture.strip()
        assert subject.writes.strip()


def test_exactly_one_subject_runs_and_it_is_the_one_with_no_blocker() -> None:
    """`runnable` is derived from `blocked_by` and from nothing else, in both directions."""
    assert bench.runnable() == ("scheduler",)
    for subject in bench.SUBJECTS.values():
        assert subject.runnable == (not subject.blocked_by)
    assert bench.SUBJECTS["scheduler"].blocked_by == ""


def test_every_blocked_subject_names_what_is_in_the_way() -> None:
    """A `blocked_by` that said "not yet" would be the thing this field exists instead of."""
    vague = {"todo", "later", "not yet", "tbd", "wip"}
    for name, subject in bench.SUBJECTS.items():
        if subject.runnable:
            continue
        assert len(subject.blocked_by) > 30, f"{name}: {subject.blocked_by!r}"
        assert subject.blocked_by.lower() not in vague, name


def test_the_charter_four_are_the_four_the_roadmap_gives_this_cell() -> None:
    """16-roadmap.md:550: `ow bench scheduler | inproc | service | rss`. Three are blocked."""
    assert bench.CHARTER_FOUR == ("scheduler", "inproc", "service", "rss")
    assert set(bench.CHARTER_FOUR) <= set(bench.SUBJECTS)
    blocked = [n for n in bench.CHARTER_FOUR if not bench.SUBJECTS[n].runnable]
    assert blocked == ["inproc", "service", "rss"]


def test_rss_is_blocked_on_the_clause_it_is_blocked_on_and_says_which() -> None:
    """Two of its three clauses ARE measured elsewhere, which is why the third has to be named.

    A reader who knows `tools/measure_store.py` measures `rss.gen5000p_peak_bytes` and
    `tools/gate_scale.py` measures supervisor RSS would otherwise read this row's absence as an
    oversight rather than as the 4M-cell sheet having neither a fixture nor a reader.
    """
    blocked_by = bench.SUBJECTS["rss"].blocked_by
    assert "4M-cell" in blocked_by
    assert "measure_store.py" in blocked_by
    assert "gate_scale.py" in blocked_by


def test_publication_says_where_a_number_does_not_go() -> None:
    """Section 7.4's `eval_perf` row and `eval/results/**.json` tree; neither exists. INV-19."""
    assert "eval_perf" in bench.PUBLICATION
    assert "eval/results" in bench.PUBLICATION


def test_the_storage_media_are_section_7_1s_three_plus_an_honest_default() -> None:
    """*"on {NVMe, spinning disk, SMB}"*, and `unknown`, because nothing here can detect one."""
    assert bench.STORAGE_MEDIA == ("nvme", "spinning", "smb", "unknown")


# ---------------------------------------------------------------------------------------------
# 2. Percentiles: nearest rank, and every value it returns was observed
# ---------------------------------------------------------------------------------------------


def test_the_percentile_is_nearest_rank_and_returns_an_observed_value() -> None:
    """The property F8's trigger needs: "p95 > 1 ms" names a claim that really took that long."""
    samples = [float(n) for n in range(1, 101)]  # 1..100, already sorted
    assert bench.percentile(samples, 0.50) == 50.0
    assert bench.percentile(samples, 0.95) == 95.0
    assert bench.percentile(samples, 0.99) == 99.0
    assert bench.percentile(samples, 1.0) == 100.0
    for quantile in (0.01, 0.37, 0.5, 0.95, 0.99, 1.0):
        assert bench.percentile(samples, quantile) in samples


def test_an_empty_sample_is_nan_and_not_zero() -> None:
    """Zero is a measurement. A percentile of nothing is not one."""
    assert math.isnan(bench.percentile([], 0.5))


def test_a_quantile_outside_zero_to_one_is_refused() -> None:
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="quantile"):
            bench.percentile([1.0], bad)


def test_a_series_sorts_once_and_reports_what_inv_19_needs_beside_the_percentiles() -> None:
    """`n` is one of INV-19's five and the cheapest of them to lose."""
    series = bench.Series.of("s", [5.0, 1.0, 3.0, 2.0, 4.0])
    assert list(series.sorted_samples) == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert series.n == 5
    assert series.p50 == 3.0
    assert series.worst == 5.0
    assert series.mean == 3.0
    assert series.total == 15.0


def test_an_empty_series_is_nan_throughout_and_never_raises() -> None:
    """A bench that crashed while reporting a run that measured nothing would lose the run."""
    empty = bench.Series.of("s", [])
    assert empty.n == 0
    for value in (empty.p50, empty.p95, empty.p99, empty.mean, empty.worst):
        assert math.isnan(value)
    assert empty.total == 0.0


# ---------------------------------------------------------------------------------------------
# 3. The run
# ---------------------------------------------------------------------------------------------


def test_a_run_drains_every_unit_and_keeps_one_sample_per_call(tmp_path: Path) -> None:
    """The whole mechanism. `claim.n` and `commit.n` are the point: samples, not sums."""
    result = _run(tmp_path)
    assert result.status == "done"
    assert result.completed == SMALL
    assert result.commit.n == SMALL, "one sample per completion"
    assert result.claim.n >= 1
    assert result.claim_rows == SMALL
    assert result.drain_s > 0


def test_every_op_identify_row_pays_a_whole_claim_statement(tmp_path: Path) -> None:
    """D191, measured directly: `CLAIM_SQL`'s LIMIT collapses to 1 for a NULL dispatch_key.

    Stated as "every row cost its own statement" rather than as `rows_per_claim == 1.00`, because
    the claimer also issues EMPTY claims -- `QUIET_POLLS_BEFORE_SHED + 1` of them -- before it
    decides the run is over, and those are statements that returned nothing. At 100,000 units they
    are three in a hundred thousand and the ratio reads 1.00; at forty they are three in
    forty-three and it reads 0.93. The ratio is the honest one to REPORT and the wrong one to
    assert a mechanism with.
    """
    result = _run(tmp_path)
    assert result.claim_rows == SMALL, "every unit was claimed"
    empty = result.claim.n - result.claim_rows
    assert 0 <= empty <= QUIET_TAIL, f"{result.claim.n} claims for {SMALL} rows"
    assert result.rows_per_claim <= 1.0, "a claim never returned two rows"


def test_the_store_carries_only_op_identify_rows_and_none_has_a_driver(tmp_path: Path) -> None:
    """What the harness enqueues is `expand`'s statement and not a fabricated one."""
    _run(tmp_path)
    connection = ow.connect(tmp_path / "index.owstore")
    try:
        rows = connection.execute(
            "SELECT operator, driver, dispatch_key, status FROM work"
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == SMALL
    assert {row[0] for row in rows} == {"op.identify"}
    assert {row[1] for row in rows} == {None}
    assert {row[2] for row in rows} == {None}, "D191's premise"
    assert {row[3] for row in rows} == {"done"}


def test_the_total_is_wall_and_not_the_sum_of_two_overlapping_means(tmp_path: Path) -> None:
    """One claimer against `sum(max_workers)` committers: adding the means double-counts.

    Asserted rather than commented because the two ARE addable if nothing overlaps, and a reader
    checking the arithmetic would otherwise conclude the report was wrong.
    """
    result = _run(tmp_path, units=200)
    naive = result.claim.mean + result.commit.mean
    assert result.ms_per_transition > 0
    assert not math.isclose(result.ms_per_transition, naive, rel_tol=1e-9)


def test_a_run_of_no_units_is_refused_before_a_store_is_built(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a bench"):
        asyncio.run(bench.scheduler(tmp_path, units=0, config=_config(tmp_path)))
    assert not (tmp_path / "index.owstore").exists()


def test_a_storage_label_outside_the_closed_set_is_refused(tmp_path: Path) -> None:
    """`--storage` is a label, and a label nothing recognises is worse than `unknown`."""
    with pytest.raises(ValueError, match="storage is one of"):
        asyncio.run(bench.scheduler(tmp_path, units=SMALL, config=_config(tmp_path), storage="ssd"))


def test_the_storage_label_is_carried_and_never_guessed(tmp_path: Path) -> None:
    result = _run(tmp_path, storage="spinning")
    assert result.storage == "spinning"


def test_a_malformed_claim_batch_table_is_a_config_error_naming_the_knob() -> None:
    class Flat:
        def get(self, key: str) -> object:
            assert key == "runtime.claim.batch"
            return 256

    with pytest.raises(ConfigError, match=r"\[runtime.claim\] batch is int"):
        bench.claim_batch_of(Flat())


def test_a_short_store_is_refused_rather_than_measured(tmp_path: Path) -> None:
    """`open_store` asserts the shipped four. A store with no `work_claimable` index would be
    measured as an index scan and reported as a scheduler."""
    assert bench.SHIPPED_MIGRATIONS == 4
    bench.open_store(tmp_path)
    with pytest.raises(StoreError, match="migrations"):
        bench.open_store(tmp_path)


# ---------------------------------------------------------------------------------------------
# 4. The corpus, and the identity the claim records
# ---------------------------------------------------------------------------------------------


def test_the_roster_is_a_generator_and_holds_nothing(tmp_path: Path) -> None:
    """12-performance.md section 3.4 prices 100,000 roster rows at 22 MB IN THE STORE. A harness
    that built the list first would put those megabytes into a number about the loop."""
    del tmp_path
    rows = bench.synthetic_roster(3, generation=7)
    assert not isinstance(rows, (list, tuple))
    materialised = list(rows)
    assert [row.unit_uri for row in materialised] == [
        "file:///scale/000000.bin",
        "file:///scale/000001.bin",
        "file:///scale/000002.bin",
    ]
    assert {row.last_seen_gen for row in materialised} == {7}
    assert {row.state for row in materialised} == {"discovered"}


def test_every_identify_row_differs_only_in_the_unit_it_names() -> None:
    """`expand.row_params` chooses every other column, which is what makes it the real statement."""
    rows = list(bench.identify_rows(3))
    assert len(rows) == 3
    assert {row["unit_uri"] for row in rows} == {
        "file:///scale/000000.bin",
        "file:///scale/000001.bin",
        "file:///scale/000002.bin",
    }
    for row in rows:
        assert row["operator"] == "op.identify"
        assert row["cache_key"] == bench.CACHE_KEY


def test_the_worker_identity_is_the_three_components_the_reaper_reads() -> None:
    """08:465's `claimed_by`. The third component is what stops a recycled pid looking alive."""
    identity = bench.worker_identity()
    assert re.fullmatch(r"[^:]+:\d+:[0-9.]+", identity), identity
    assert identity.split(":")[1] == str(__import__("os").getpid())


def test_the_no_op_operator_answers_for_every_row_and_claims_nothing_a_driver_may_not(
    tmp_path: Path,
) -> None:
    """08:238 lists what a driver may not claim. This one claims `OK` and a `UnitRef`.

    `len(results) == len(rows)` is I24 and the Supervisor raises on a short answer, so a no-op that
    answered for fewer rows would leave claimed rows to their lease rather than failing loudly.
    """
    del tmp_path

    class Row:
        unit_uri = "file:///scale/000000.bin"
        unit_part = ""
        operator = "op.identify"
        op_version = 1

    class Batch:
        rows = (Row(), Row(), Row())

    results = bench.no_op(Batch())
    assert len(results) == 3
    for result in results:
        assert str(result.outcome) == "ok"
        assert result.cache_key == bench.CACHE_KEY
        assert result.produced == ()
        assert result.degradations == ()
        assert result.failure_class is None


def test_the_claimable_set_is_pending_plus_failed_transient_and_excludes_deferred() -> None:
    """`CLAIM_SQL`'s own predicate. Counting `deferred` would let a stalled budget read as a full
    queue and pause the producer for the rest of the run."""
    counts = {"pending": 5, "failed_transient": 2, "deferred": 900, "claimed": 3, "done": 40}
    assert bench.claimable(counts) == 7
    assert bench.claimable({}) == 0


def test_the_samples_clock_is_injected_and_the_injection_is_what_is_read() -> None:
    """G8 bans `time.perf_counter` in library code, and the ban is not the only reason.

    `time.monotonic_ns()` -- which the ban itself prescribes for durations -- resolves to
    **15.6 ms on Windows**, coarser than every claim this class measures. `SystemClock` substitutes
    `perf_counter_ns` there and records the choice in `ClockFacts`, so the compliant spelling is
    also the only one that can see a one-millisecond claim on six of the nine test-matrix cells. A
    rewrite to a bare `time.monotonic_ns()` would pass the gate and destroy the measurement.

    Asserted with a fake clock, which is the other thing injection buys: the sample is then exactly
    the difference the clock reports, with no real time in it at all.
    """
    readings = iter([1_000_000, 4_500_000, 10_000_000, 12_000_000])

    class Ticking:
        def monotonic_ns(self) -> int:
            return next(readings)

        def wall_ns(self) -> int:  # pragma: no cover -- unread by Samples
            return 0

    class Inner:
        def claim(self, *_a: object) -> tuple[()]:
            return ()

        def complete(self, *_a: object) -> bool:
            return True

    samples = bench.Samples(Inner(), clock=Ticking())  # type: ignore[arg-type]
    samples.claim(1, 1, "w", 1)
    samples.complete(1, 1, object())
    assert list(samples.claims) == [3.5], "4.5 ms - 1.0 ms, in milliseconds"
    assert list(samples.commits) == [2.0]


def test_the_shipped_clock_resolves_finely_enough_to_see_a_millisecond() -> None:
    """`SystemClock` is what `scheduler()` defaults to, and its resolution is the measurement.

    `clock.py` chooses `perf_counter_ns` wherever `monotonic_ns` is coarse and records which in
    `ClockFacts`. A clock whose resolution exceeded B22's 0.45 ms budget would make every figure in
    this bench a multiple of its own tick.
    """
    clock = SystemClock()
    assert clock.facts.resolution_ns < 450_000, clock.facts


def test_a_producer_that_starts_paused_asks_before_it_writes() -> None:
    """The ordering a 100,000-row run found in `tools/gate_scale.py`'s copy of this class.

    `scheduler()` runs the first enqueue pass before the loop opens, so the task it then starts is
    ALREADY paused. `enqueue` checks the pause after a commit and never before one, so a task that
    enqueued first wrote a whole `plan_batch` unasked.
    """
    calls: list[str] = []

    class Spy(bench.Producing):
        def __init__(self) -> None:
            self._gate = self._ask  # type: ignore[assignment]
            self.written = 0
            self.paused = 0
            self.asks = 0

        def _ask(self) -> bool:
            self.asks += 1
            calls.append("ask")
            return self.asks < 2

        def pass_once(self) -> bool:
            calls.append("write")
            return False

    asyncio.run(Spy().stream(lambda: False))
    assert calls[0] == "ask", f"the producer wrote before it asked: {calls}"
    assert calls.index("write") > calls.index("ask")
