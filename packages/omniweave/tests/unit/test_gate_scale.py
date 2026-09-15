"""`tools/gate_scale.py` -- G22's runner, over a roster small enough to run in a unit suite.

`tools/gates.toml`'s G22 row is the specification: *"scale: 100k roster, RSS <= 600 MB, >= 2,000
transitions/s"*, `jobs = []`, `pr = false`, `nightly_note = "**nightly only**"`, `release = true`.
It is the one row in the register with no PR cell, so **nothing in CI runs this gate** -- which
makes this file the only place its mechanism is checked before a release, and the reason every
assertion below is about a mechanism rather than about a number.

**No test here runs a 100,000-unit roster.** The real gate measures ~2.5 minutes at that size on
the machine that landed it; a unit suite that paid it is a unit suite people skip. What these tests
run is the same code path at 40 to 300 units, where the three bounds still resolve, the producer
still pauses if the water marks are lowered, and every refusal still fires. The SCALE is the
nightly cell's; the MACHINERY is here.

The two things that would make G22 useless are both asserted directly, because both are silent:

1. **A green verdict over a run that did not finish.** A partial drain has a wall time and a
   completion count and therefore a transitions/s, and it is a number about nothing. `main()`
   returns `EXIT_NOT_RUN`, never `EXIT_CLEAN`.
2. **A bound that cannot fail.** Each of the three is asserted in both directions against a
   hand-built `Measured`, so a `<=` that was silently a `<` or an `ok` hard-coded True is a red
   test rather than a green gate.

Specified in 00-vision.md:730 (V10-7), 11-repo-layout.md sections 6.4, 6.5 and 6.8,
12-performance.md sections 3.4 and 4.1 and rows B22 and G22, and 16-roadmap.md:550 and :578.
"""

from __future__ import annotations

import asyncio  # noqa: TID251 -- a test that drives the loop; the ban scopes packages/*/src.
import importlib.util
import sys
import tomllib
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from omniweave_core import config as configmod
from omniweave_core.errors import ConfigError, StoreError
from omniweave_core.store import sqlite as ow


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_scale.py"
REGISTER = REPO_ROOT / "tools" / "gates.toml"

# The gate is a script in `tools/`, not a distribution, so there is no package to import it from.
# `spec_from_file_location` loads it by path -- the mechanism `test_gate_crash.py` and
# `test_gate_incremental.py` already use, and for the same reasons: not `importlib.import_module`,
# which is banned outside `host/`, and not a `sys.path` mutation, which leaks into every later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_gate_scale", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repository.
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)

SMALL = 40
"""Units per run in this file. Large enough that the claimer makes several passes and the sampler
takes more than one reading; small enough that a test is a second and not a minute."""


def _run(argv: list[str]) -> tuple[int, str]:
    """The gate, with its report captured. Nothing here writes to the real stdout."""
    buffer = StringIO()
    code = gate.main(argv, out=buffer)
    return code, buffer.getvalue()


def _config(root: Path) -> Any:
    """Built-in defaults, resolved against an empty environment and an empty directory.

    `load()` walks up for an `omniweave.toml` and stops at a `.git` directory or the root, so a
    `tmp_path` has none and every value is rung 0's. That is deliberate: a gate that inherited this
    repository's own config would measure a developer's overrides."""
    return configmod.load(cwd=root, env={})


def _measure(
    root: Path,
    *,
    count: int = SMALL,
    widths: tuple[int, ...] = (),
    depths: tuple[int, ...] = (),
) -> Any:
    """One real scale run at `count` units. Both diagnostics default OFF, and that is deliberate.

    `claim_depths()` seeds `max(depths)` rows -- 50,000 at the shipped defaults -- and then claims
    them one at a time at a cost this file exists to have measured. Paying that per test would make
    the suite minutes long to re-measure a number the gate already prints.
    """
    return asyncio.run(
        gate.run_scale(root, count=count, config=_config(root), widths=widths, depths=depths)
    )


def _returns(measured: object) -> Any:
    """A stand-in for `run_scale` that yields `measured`. It is a COROUTINE FUNCTION on purpose.

    `main()` calls `asyncio.run(run_scale(...))`, so a plain lambda substituted for it raises
    `ValueError: a coroutine was expected` from inside `asyncio` -- which the gate then reports as
    `DID NOT RUN`, and the test passes for the wrong reason. Every report test below patches with
    this, so the thing under test is the report and not the substitution.
    """

    async def stand_in(*_args: object, **_kwargs: object) -> object:
        return measured

    return stand_in


# ---------------------------------------------------------------------------------------------
# 1. The run: a real store, a real loop, and every row completed
# ---------------------------------------------------------------------------------------------


def test_a_run_drains_every_row_it_enqueued_through_the_real_supervisor(tmp_path: Path) -> None:
    """The whole mechanism, end to end. If this passes, only the SIZE separates it from G22.

    `completed == roster` is the load-bearing half: `Store.complete()` returns `False` for
    supersession and the Supervisor counts that separately, so a run that claimed forty rows and
    completed thirty-eight would still have a wall time and still produce a transitions/s.
    """
    measured = _measure(tmp_path)
    assert measured.status == "done"
    assert measured.claimed == SMALL
    assert measured.completed == SMALL
    assert measured.superseded == 0
    assert measured.abandoned == 0
    assert measured.crashed == 0
    assert measured.drain_s > 0


def test_every_work_row_is_an_op_identify_row_and_none_of_them_carries_a_driver(
    tmp_path: Path,
) -> None:
    """What the gate enqueues is `expand`'s statement and not a fabricated one.

    `work`'s three paired CHECKs make `operator LIKE 'op.%'` equivalent to a NULL `decision_id`,
    a NULL `driver` and a NULL `dispatch_key`; reading them back is how this file knows the rows
    came from `IDENTIFY_INSERT_SQL` rather than from a fixture that happened to insert.
    """
    _measure(tmp_path)
    connection = ow.connect(tmp_path / "index.owstore")
    try:
        rows = connection.execute(
            "SELECT operator, driver, dispatch_key, decision_id, status, cost_class FROM work"
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == SMALL
    assert {row[0] for row in rows} == {"op.identify"}
    assert {row[1] for row in rows} == {None}, "an op.* row has no driver"
    assert {row[2] for row in rows} == {None}, "and therefore no dispatch_key -- D191's premise"
    assert {row[3] for row in rows} == {None}
    assert {row[4] for row in rows} == {"done"}
    assert {row[5] for row in rows} == {"free"}


def test_the_roster_is_written_as_discovered_units_one_per_work_row(tmp_path: Path) -> None:
    """A `work` row references `unit(unit_uri)`, so the roster is not optional scaffolding."""
    _measure(tmp_path)
    connection = ow.connect(tmp_path / "index.owstore")
    try:
        units = connection.execute("SELECT state, connector, part_count FROM unit").fetchall()
    finally:
        connection.close()
    assert len(units) == SMALL
    assert {row[0] for row in units} == {"discovered"}
    assert {row[1] for row in units} == {"fs"}
    assert {row[2] for row in units} == {None}, "nothing here identifies; part_count stays NULL"


def test_the_store_carries_all_four_migrations_and_a_short_one_is_refused(tmp_path: Path) -> None:
    """`build()` asserts the shipped set rather than trusting it. See `SHIPPED_MIGRATIONS`."""
    assert gate.SHIPPED_MIGRATIONS == 4
    gate.build(tmp_path)
    with pytest.raises(StoreError, match="migrations"):
        gate.build(tmp_path)  # the second call finds four applied and applies none


# ---------------------------------------------------------------------------------------------
# 2. The three bounds, each asserted in both directions
# ---------------------------------------------------------------------------------------------


def _fake(**overrides: object) -> Any:
    """A `Measured` whose three bounds all hold, so a test can break exactly one of them."""
    base = {
        "roster": 100_000,
        "roster_s": 1.0,
        "enqueue_s": 1.0,
        "drain_s": 10.0,
        "status": "done",
        "claimed": 100_000,
        "completed": 100_000,
        "superseded": 0,
        "abandoned": 0,
        "crashed": 0,
        "batches": 100_000,
        "reaped": 0,
        "lag_breach_ms": 0,
        "pauses": 2,
        "enqueued": 50_176,
        "peak_rss": 100 * 1024 * 1024,
        "rss_source": "a test",
        "peak_claimable": 50_000,
        "samples": 40,
        "emits": 800_000,
        "high_water": 50_000,
        "low_water": 25_000,
        "plan_batch": 512,
        "claim_width": 8,
        "claim_ms_per_row": 0.01,
        "claim_s": 1.0,
        "complete_ms": 0.1,
        "workers": {"free": 4},
        "inflight": {"free": 32},
        "claim_batch": {"free": 256, "local_compute": 32, "billed_api": 8},
        "cpus": 8,
    }
    base.update(overrides)
    return gate.Measured(**base)  # type: ignore[arg-type]


def test_a_clean_measurement_holds_all_three_bounds() -> None:
    """10,000/s, 100 MiB, 50,000 claimable. The baseline every test below perturbs."""
    checks = gate.verdict(_fake())
    assert [check.name for check in checks] == [
        "peak claimable",
        "supervisor peak RSS",
        "work transitions/s",
    ]
    assert all(check.ok for check in checks)


@pytest.mark.parametrize(
    ("field", "value", "failing"),
    [
        ("peak_claimable", 50_513, "peak claimable"),
        ("peak_rss", 601 * 1024 * 1024, "supervisor peak RSS"),
        ("drain_s", 60.0, "work transitions/s"),
    ],
)
def test_each_bound_fails_on_its_own_quantity_and_on_no_other(
    field: str, value: object, failing: str
) -> None:
    """One breach, one red check. A bound that reddened its neighbours would be unreadable."""
    checks = gate.verdict(_fake(**{field: value}))
    assert [check.name for check in checks if not check.ok] == [failing]


def test_the_claimable_bound_is_the_water_mark_plus_one_producer_transaction(
    tmp_path: Path,
) -> None:
    """D194: 05:1196 commits 512 rows per transaction and 08:889 checks the pause AFTER a commit.

    So the claimable set stands above `queue_high_water` for as long as one commit takes, on every
    correct run, and a gate asserting the literal `<=` would be red for a reason that is not a
    defect in the runtime. The relaxed bound is the arithmetic; `--strict` is the literal reading.
    """
    del tmp_path
    at_the_edge = _fake(peak_claimable=50_511)
    assert all(check.ok for check in gate.verdict(at_the_edge))
    assert not gate.verdict(at_the_edge, strict=True)[0].ok
    over_by_one_transaction = _fake(peak_claimable=50_513)
    assert not gate.verdict(over_by_one_transaction)[0].ok


def test_strict_names_no_relaxation_in_its_note_and_the_default_names_the_knob() -> None:
    """The concession is measurable, so it has to be legible: which bound was asserted, and why."""
    relaxed = gate.verdict(_fake())[0]
    strict = gate.verdict(_fake(), strict=True)[0]
    assert relaxed.bound == 50_512
    assert "plan_batch" in relaxed.note and "D194" in relaxed.note
    assert strict.bound == 50_000
    assert strict.note == ""


def test_an_rss_of_zero_is_a_failure_and_not_a_pass(tmp_path: Path) -> None:
    """`peak_rss_bytes` never raises: it returns `(None, why)`, and the sampler keeps its zero.

    A `0 <= 600 MB` that read as green would turn the one bound a platform can silently fail to
    measure into the one bound that always passes -- on darwin, where `host/subproc.py` records the
    shortfall in as many words. The check is `0 < observed <= ceiling` for exactly that.
    """
    del tmp_path
    assert not gate.verdict(_fake(peak_rss=0))[1].ok


# ---------------------------------------------------------------------------------------------
# 3. The refusals: a number over a run that did not happen is worse than no number
# ---------------------------------------------------------------------------------------------


def test_a_roster_of_zero_units_did_not_run(tmp_path: Path) -> None:
    del tmp_path
    code, output = _run(["--roster", "0"])
    assert code == gate.EXIT_NOT_RUN
    assert "not a roster" in output
    assert "G22 ok" not in output


def test_a_partial_drain_is_exit_two_and_never_a_verdict(tmp_path: Path, monkeypatch) -> None:
    """THE CASE THIS GATE EXISTS TO GET RIGHT.

    A run the stall detector withdrew has a completion count and a wall time, so it has a
    transitions/s -- and that number is about a run that stopped, not about a scheduler. G22 has
    `release = true`, so a green here is a release proceeding on a measurement of nothing.
    """
    short = _fake(status="partial", completed=99_000)
    monkeypatch.setattr(gate, "run_scale", _returns(short))
    code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert code == gate.EXIT_NOT_RUN
    assert "ended 'partial'" in output
    assert "99,000 of 100,000" in output
    assert "G22 ok" not in output and "G22 FAIL" not in output


def test_a_complete_run_that_breaches_a_bound_is_exit_one_and_names_which(
    tmp_path: Path, monkeypatch
) -> None:
    """Exit 1 and exit 2 are different answers, and CI needs the difference. See the docstring."""
    monkeypatch.setattr(gate, "run_scale", _returns(_fake(drain_s=60.0)))
    code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert code == gate.EXIT_FAIL
    assert "G22 FAIL" in output
    assert "work transitions/s" in output
    assert "DID NOT RUN" not in output


def test_a_run_that_holds_every_bound_is_exit_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "run_scale", _returns(_fake()))
    code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert code == gate.EXIT_CLEAN
    assert "G22 ok  3 bound(s) held." in output


def test_a_malformed_claim_batch_table_is_a_config_error_naming_the_knob() -> None:
    """`supervisor._table` refuses the same shape; this refuses it in the same words."""

    class Flat:
        def get(self, key: str) -> object:
            assert key == "runtime.claim.batch"
            return 256

    with pytest.raises(ConfigError, match=r"\[runtime.claim\] batch is int"):
        gate._claim_batch(Flat())


# ---------------------------------------------------------------------------------------------
# 4. The producer, the pause, and the sampler
# ---------------------------------------------------------------------------------------------


def test_the_producer_pauses_at_the_high_water_mark_and_resumes_at_the_low_one(
    tmp_path: Path,
) -> None:
    """The hysteresis, exercised. 08:880 makes the `expander` a producer of the claimable set.

    The shipped marks are 50,000 / 25,000 and this run is forty rows, so the config is overridden
    rather than the roster grown: what is under test is that `PauseGate` reaches `enqueue`'s
    post-commit check at all, and a 100,000-row run to prove it would be the nightly cell.

    **The bound asserted is the exact one `verdict()` asserts**, `high_water + plan_batch`, and
    it is asserted HERE at marks small enough that an off-by-one-transaction error is visible: at
    8/4/4 the bound is 12 and an extra batch is 16. At the shipped 50000/25000/512 the same error
    is 0.5% and reads as noise, which is how it survived the first 100,000-row run.
    """
    config = _Marks(_config(tmp_path), high=8, low=4, plan_batch=4)
    measured: Any = asyncio.run(
        gate.run_scale(tmp_path, count=SMALL, config=config, widths=(), depths=())
    )
    assert measured.status == "done"
    assert measured.completed == SMALL
    assert measured.pauses >= 1, "forty rows past a high-water mark of eight must pause"
    assert measured.peak_claimable <= 8 + 4, "one transaction past the mark, and not two"
    assert measured.peak_claimable < SMALL, "without backpressure all forty would be claimable"


def test_a_producer_that_starts_paused_asks_before_it_writes() -> None:
    """THE ORDERING BUG THE 100,000-ROW RUN FOUND, pinned so it cannot come back.

    `run_scale` runs the first enqueue pass before the loop opens, so the producer task it then
    starts is ALREADY paused. `enqueue` checks the pause after a commit and never before one, so a
    task that enqueued first wrote a whole `plan_batch` unasked -- and the claimable set stood at
    `high_water + 2 x plan_batch` before anything had the chance to say no.

    Asserted on `_Producer.stream` directly rather than through a run, because through a run it is
    a 0.5% discrepancy at the shipped marks, and 0.5% is what it looked like the first time.
    """
    calls: list[str] = []

    class Spy(gate._Producer):  # type: ignore[misc, name-defined]
        """`stream()` unchanged, with its two thread-bound calls recorded in order.

        A subclass rather than a patched attribute: `_Producer` has `__slots__`, so an assignment
        to `pass_once` raises -- which is the class doing its job, not an obstacle to route around.
        """

        def __init__(self) -> None:
            self._gate = self._ask  # type: ignore[assignment]
            self.written = 0
            self.paused = 0
            self.asks = 0

        def _ask(self) -> bool:
            self.asks += 1
            calls.append("ask")
            return self.asks < 2  # paused on the first ask, resumed on the second

        def pass_once(self) -> bool:
            calls.append("write")
            return False  # the roster is exhausted; one pass is all this needs

    asyncio.run(Spy().stream(lambda: False))

    assert calls, "stream() did nothing at all"
    assert calls[0] == "ask", f"the producer wrote before it asked: {calls}"
    assert "write" in calls
    assert calls.index("write") > calls.index("ask")


def test_a_paused_producer_still_finishes_the_roster(tmp_path: Path) -> None:
    """08:889: *"Backpressure pauses at a safe boundary and never drops."* Not one row fewer."""
    config = _Marks(_config(tmp_path), high=8, low=4, plan_batch=4)
    measured: Any = asyncio.run(
        gate.run_scale(tmp_path, count=SMALL, config=config, widths=(), depths=())
    )
    connection = ow.connect(tmp_path / "index.owstore")
    try:
        (written,) = connection.execute("SELECT count(*) FROM work").fetchone()
    finally:
        connection.close()
    assert written == SMALL
    assert measured.completed == SMALL


class _Marks:
    """A `Config` with three keys overridden. Not a fake: every other key is the real resolution.

    `Config` is frozen with no `replace` and no `copy(update=...)` on purpose -- *"a call-site
    override is an argument to an `Action` and never reaches this object"* -- so a test that needs
    different water marks wraps rather than mutates, and the wrapper's narrowness is the point: it
    forwards `subkeys` and `config_digest` to the real object and overrides exactly three `get`s.
    """

    def __init__(self, inner: object, *, high: int, low: int, plan_batch: int) -> None:
        self._inner = inner
        self._overrides = {
            "runtime.queue_high_water": high,
            "runtime.queue_low_water": low,
            "runtime.plan_batch": plan_batch,
        }

    def get(self, key: str) -> object:
        if key in self._overrides:
            return self._overrides[key]
        return self._inner.get(key)  # type: ignore[attr-defined]

    def subkeys(self, prefix: str) -> tuple[str, ...]:
        return self._inner.subkeys(prefix)  # type: ignore[attr-defined]

    @property
    def config_digest(self) -> str:
        return self._inner.config_digest  # type: ignore[attr-defined]

    @property
    def semantic_digest(self) -> str:
        return self._inner.semantic_digest  # type: ignore[attr-defined]


def test_the_sampler_reads_rss_and_claimable_without_a_thread(tmp_path: Path) -> None:
    """`sample()` is public so this can take one reading rather than racing a daemon.

    The RSS source string is asserted non-empty rather than matched: it is per-platform by
    construction (`K32GetProcessMemoryInfo` here, `/proc/<pid>/statm` on Linux, a stated shortfall
    on darwin) and a test that pinned one would fail on the other two.
    """
    del tmp_path
    sampler = gate.Sampler(lambda: 17)
    sampler.sample()
    sampler.sample()
    assert sampler.samples == 2
    assert sampler.peak_claimable == 17
    assert sampler.rss_source
    assert sampler.peak_rss > 0, "this platform can read its own RSS; see the docstring"


def test_the_sampler_keeps_the_peak_and_never_the_latest(tmp_path: Path) -> None:
    """A gauge that fell back would erase the only evidence the water mark was ever crossed."""
    del tmp_path
    readings = iter([90_000, 10, 10])
    sampler = gate.Sampler(lambda: next(readings))
    for _ in range(3):
        sampler.sample()
    assert sampler.peak_claimable == 90_000


def test_the_sampler_does_not_shadow_threads_own_stop(tmp_path: Path) -> None:
    """`threading.Thread._stop` is a real method `join()` calls. Shadowing it breaks every join.

    Asserted rather than commented because the failure is a `TypeError` raised from inside the
    standard library, a hundred lines from the assignment that caused it.
    """
    del tmp_path
    sampler = gate.Sampler(lambda: 0)
    assert callable(sampler._stop), "Thread._stop must still be the method Thread defines"


def test_the_claimable_set_is_pending_plus_failed_transient_and_excludes_deferred() -> None:
    """`CLAIM_SQL`'s own predicate, and 08:127-131's. A deferred row waits on the sweeper.

    Counting `deferred` would let a stalled budget read as a full queue and pause the producer for
    the rest of the run -- backpressure applied to work that backpressure cannot release.
    """
    counts = {"pending": 5, "failed_transient": 2, "deferred": 900, "claimed": 3, "done": 40}
    assert gate._claimable(counts) == 7
    assert gate._claimable({}) == 0


# ---------------------------------------------------------------------------------------------
# 5. The diagnostic, and the fixture it is confined to
# ---------------------------------------------------------------------------------------------


def test_the_claim_width_table_measures_one_row_per_width_and_costs_less_as_it_widens(
    tmp_path: Path,
) -> None:
    """D190 and D191 in one table: the same statement, four widths, four costs per row.

    The ORDER is asserted and the absolute numbers are not: a unit suite on a shared runner cannot
    pin a millisecond, and what the gate claims is that the claim's cost is a per-STATEMENT
    overhead amortised over the rows it returns -- which is a monotone relationship, and which
    is what makes `width 1` the finding.
    """
    measured = _measure(tmp_path, count=SMALL, widths=(1, 8, 64))
    assert [width.width for width in measured.widths] == [1, 8, 64]
    for width in measured.widths:
        assert width.rows == gate.WIDTH_PROBE_ROWS
        assert width.calls == -(-gate.WIDTH_PROBE_ROWS // width.width) + 1, "plus the empty claim"
        assert width.ms_per_row > 0
    costs = [width.ms_per_row for width in measured.widths]
    assert costs == sorted(costs, reverse=True), "a wider claim costs LESS per row, always"


def test_the_queue_depth_table_shows_a_claim_reading_the_whole_claimable_set(
    tmp_path: Path,
) -> None:
    """D190, measured: a claim costs O(claimable), not O(batch), and the plan gives it 0.45 ms.

    `work_claimable`'s leading column is `cost_class` and the shipped four-parameter `claim` does
    not constrain it, so `EXPLAIN QUERY PLAN` reads `SCAN work USING INDEX work_claimable` plus
    `USE TEMP B-TREE FOR ORDER BY` -- twice, once for the `head` CTE and once for the `picked`
    subquery. What that predicts is a claim cost that RISES with the depth, and rises roughly
    linearly, which is what the two assertions below are.

    The depths here are two orders of magnitude below the shipped `queue_high_water = 50,000`,
    because a unit test that seeded fifty thousand rows would pay the very cost it is asserting.
    The gate's own defaults are the real ones; this asserts the SHAPE.
    """
    depths = gate.claim_depths(tmp_path, depths=(250, 2_000), claims=40)
    assert [depth.claimable for depth in depths] == [2_000, 250], "deepest first"
    for depth in depths:
        assert depth.claims == 40
        assert depth.rows == 40, "one row per claim: a NULL dispatch_key batches alone"
        assert depth.ms_per_claim > 0
    deep, shallow = depths
    assert deep.ms_per_claim > shallow.ms_per_claim, "a deeper queue costs MORE per claim"


def test_the_depth_probe_uses_its_own_store_and_never_the_verdicts(tmp_path: Path) -> None:
    """The verdict's store is drained by the time this runs; re-seeding it would put the depth
    probe's rows where the width probe then claims. One file each, one `StoreThread` each --
    INV-17 is one Connection per THREAD, which two threads over two files do not violate."""
    gate.claim_depths(tmp_path, depths=(100,), claims=5)
    assert (tmp_path / "depth.owstore").is_file()
    assert not (tmp_path / "index.owstore").exists(), "the verdict's store is not touched"


def test_an_empty_depth_list_seeds_nothing_at_all(tmp_path: Path) -> None:
    """`--no-diagnostic`'s other half. 50,000 rows is not a cost to pay by accident."""
    assert gate.claim_depths(tmp_path, depths=()) == ()
    assert not (tmp_path / "depth.owstore").exists()


def test_the_shipped_depths_bracket_the_water_mark_the_backpressure_targets() -> None:
    """The deepest probe IS `queue_high_water`, because that is where a long run actually sits.

    08:880 pauses the producer at 50,000 claimable and resumes it at 25,000, so a 100,000-row run
    spends nearly all of its time between those two -- and a diagnostic measured at 1,000 would
    report a claim cost the run never pays."""
    assert max(gate.DEPTH_PROBE_DEPTHS) == 50_000
    assert tuple(sorted(gate.DEPTH_PROBE_DEPTHS)) == gate.DEPTH_PROBE_DEPTHS


def test_an_empty_width_list_runs_no_diagnostic_and_writes_no_fixture_rows(
    tmp_path: Path,
) -> None:
    """`--no-diagnostic`'s path. The fixture's routed rows must not exist when nobody asked."""
    measured = _measure(tmp_path, widths=())
    assert measured.widths == ()
    connection = ow.connect(tmp_path / "index.owstore")
    try:
        (routed,) = connection.execute(
            "SELECT count(*) FROM work WHERE dispatch_key IS NOT NULL"
        ).fetchone()
        (decisions,) = connection.execute("SELECT count(*) FROM route_decision").fetchone()
    finally:
        connection.close()
    assert routed == 0
    assert decisions == 0


def test_the_diagnostics_fixture_rows_never_touch_the_verdicts_rows(tmp_path: Path) -> None:
    """The reset between widths is `WHERE dispatch_key IS NOT NULL`, so it cannot reach an op row.

    The verdict is measured before the diagnostic runs, but "measured first" is a sequencing
    argument and this is a structural one: even a diagnostic that ran twice, or first, could not
    hand an `op.identify` row back to `pending`.
    """
    measured = _measure(tmp_path, widths=(8,))
    assert measured.completed == SMALL
    connection = ow.connect(tmp_path / "index.owstore")
    try:
        rows = connection.execute(
            "SELECT status, count(*) FROM work WHERE operator = 'op.identify' GROUP BY status"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [("done", SMALL)]


def test_the_width_note_resolves_every_printed_width_to_a_knob_or_a_defect() -> None:
    """A number in a report that names no knob is a number a reader cannot act on."""
    measured = _fake()
    assert "D191" in gate._width_note(gate.Width(1, 1, 1, 1.0), measured)
    assert "D192" in gate._width_note(gate.Width(8, 1, 1, 1.0), measured)
    assert "local_compute" in gate._width_note(gate.Width(32, 1, 1, 1.0), measured)
    assert "free" in gate._width_note(gate.Width(256, 1, 1, 1.0), measured)
    assert gate._width_note(gate.Width(7, 1, 1, 1.0), measured) == ""


# ---------------------------------------------------------------------------------------------
# 6. The report, and what it refuses to leave out
# ---------------------------------------------------------------------------------------------


def test_the_report_names_every_absence_and_who_owns_it(tmp_path: Path, monkeypatch) -> None:
    """G19's `--smoke` rule, applied here: never a silent pass. Three absences, three owners."""
    monkeypatch.setattr(gate, "run_scale", _returns(_fake()))
    _code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert "NOT CHECKED BY THIS RUN" in output
    assert output.count("owner: ") == len(gate.NOT_CHECKED)
    for expected in ("746,400 planner rows", "8 events", "ow-bench-1", "second process"):
        assert expected in output, expected
    assert len(gate.NOT_CHECKED) == 4


def test_the_report_says_what_fraction_of_the_priced_corpus_it_ran(
    tmp_path: Path, monkeypatch
) -> None:
    """One work row per unit is 1/8.464 of 12-performance.md section 3.4's 846,400."""
    monkeypatch.setattr(gate, "run_scale", _returns(_fake()))
    _code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert "ONE work row per unit" in output
    assert "8.464x" in output
    assert pytest.approx(846_400 / 100_000) == gate.PLANNED_ROWS_PER_UNIT


def test_the_report_prints_the_machine_it_measured_on(tmp_path: Path, monkeypatch) -> None:
    """08:661: *"recorded in the run manifest, so a performance number is attributable to a
    machine."* There is no manifest here, so the report is where the derivation lands."""
    monkeypatch.setattr(gate, "run_scale", _returns(_fake()))
    _code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert "8 cpus" in output
    assert "queue_high_water 50,000 / queue_low_water 25,000" in output
    assert "_next_width() asks for 8" in output


def test_the_split_is_printed_on_a_green_run_too(tmp_path: Path, monkeypatch) -> None:
    """B22 is a Budget, not a diagnostic: its two components are a number every run owes."""
    monkeypatch.setattr(gate, "run_scale", _returns(_fake()))
    code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert code == gate.EXIT_CLEAN
    assert "Store.claim" in output and "Store.complete" in output
    assert "B22 budgets the whole of it at 0.45 ms" in output
    assert "QUEUED" in output, "both figures are latencies; the report must say so"


def test_the_report_renders_both_diagnostic_tables(tmp_path: Path, monkeypatch) -> None:
    """The formatting path a 100,000-row run reaches only at the very end, rendered here in a ms.

    A `KeyError` or a bad format spec in `_split_lines` would otherwise surface after twenty-five
    minutes of measurement, with the measurement lost. Both tables are populated, including the
    `queue_high_water` marker, which only appears when a probed depth reaches the mark.
    """
    measured = _fake(
        depths=(
            gate.Depth(claimable=50_000, claims=100, rows=100, seconds=1.19),
            gate.Depth(claimable=10_000, claims=100, rows=100, seconds=0.24),
            gate.Depth(claimable=1_000, claims=100, rows=100, seconds=0.033),
        ),
        widths=(
            gate.Width(width=1, calls=2_049, rows=2_048, seconds=0.84),
            gate.Width(width=8, calls=257, rows=2_048, seconds=0.13),
            gate.Width(width=32, calls=65, rows=2_048, seconds=0.05),
            gate.Width(width=256, calls=9, rows=2_048, seconds=0.02),
        ),
    )
    monkeypatch.setattr(gate, "run_scale", _returns(measured))
    _code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    assert "CLAIM_SQL is O(n), not O(batch)" in output
    assert "USE TEMP B-TREE FOR ORDER BY" in output
    assert "n =  50,000" in output
    assert "<- queue_high_water" in output
    assert output.count("<- queue_high_water") == 1, "only the depth that reaches the mark"
    assert "us per row waiting" in output
    assert "width  256" in output
    assert [line for line in output.splitlines() if len(line) > 100] == []


def test_no_report_line_is_wider_than_a_terminal(tmp_path: Path, monkeypatch) -> None:
    """A report that wraps in a CI log is a report nobody reads to the end."""
    monkeypatch.setattr(gate, "run_scale", _returns(_fake(peak_claimable=99_999, drain_s=90.0)))
    _code, output = _run(["--roster", "100000", "--root", str(tmp_path)])
    too_wide = [line for line in output.splitlines() if len(line) > 100]
    assert too_wide == []


# ---------------------------------------------------------------------------------------------
# 7. The register, and the one row with no PR cell
# ---------------------------------------------------------------------------------------------


def _row() -> dict[str, object]:
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    for row in register["gate"]:
        if row["id"] == "G22":
            return row
    message = "tools/gates.toml carries no G22 row"
    raise AssertionError(message)


def test_the_register_names_this_script_as_g22s_runner_and_no_longer_plans_it() -> None:
    """`test_gates_register.py` forces the move in both directions; this is the G22 half of it."""
    row = _row()
    assert row["runner"] == ["tools/gate_scale.py"]
    assert "runner_planned" not in row
    assert TOOL_PATH.is_file()


def test_g22_still_has_no_pr_cell_after_its_runner_landed() -> None:
    """The row that landing a script must NOT change. Section 6.4 is explicit and it is the only
    row in the register the sentence is true of, so a `jobs` list here would be invisible in
    twenty-eight other green rows."""
    row = _row()
    assert row["jobs"] == []
    assert row["pr"] is False
    assert "budget_s" not in row, "section 6.4 prints an em dash; there is no number to invent"
    assert row["nightly"] is True
    assert row["release"] is True


def test_the_bounds_in_this_script_are_the_bounds_the_register_asserts() -> None:
    """The register's assertion cell is prose; these three constants are what runs. They agree."""
    assertion = str(_row()["assertion"])
    assert "100k roster" in assertion
    assert gate.ROSTER == 100_000
    assert "600 MB" in assertion
    assert gate.RSS_CEILING_BYTES == 600 * 1024 * 1024
    assert "2,000 transitions/s" in assertion
    assert gate.TRANSITIONS_PER_S == 2_000


def test_nothing_in_ci_runs_this_gate_and_that_is_the_register_speaking() -> None:
    """Section 6.4: G22 *"is deliberately absent from `ci-ok`'s required set."* Asserted against
    the workflow, because the absence is what makes a red G22 a release matter and not a merge
    one -- and an accidental step here would quietly make it both."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv run tools/gate_scale.py" not in workflow
    assert "gate_scale" in workflow, "its absence is DOCUMENTED there, which is not the same thing"


def test_the_gate_is_not_a_second_home_for_a_bound_the_register_already_carries() -> None:
    """`replace()` on a frozen `Measured` is how a test perturbs one number; asserted so the
    dataclass stays frozen. A mutable `Measured` would let the report and the verdict disagree."""
    measured: Any = _fake()
    assert replace(measured, drain_s=50.0).transitions_per_s == 2_000.0
    with pytest.raises((AttributeError, TypeError)):
        measured.drain_s = 1.0  # type: ignore[misc]
