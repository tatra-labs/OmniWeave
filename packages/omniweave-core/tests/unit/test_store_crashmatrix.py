"""`store/crashmatrix.py` -- the harness half of `ow test crash-matrix` and of G21.

W2.9 is 16-roadmap.md:422: *"SIGKILL at **every** statement boundary in `Store.complete()`;
G21's three-random-point CI job"*, priced at *"~40 statement boundaries at a scripted
kill-and-verify cycle each; DataFlow's eight checkpoint failure modes are the fixture list"*. What
that buys is named at 17-risks.md:861 -- the matrix is *"the only evidence that INV-17's 'commit
together' claim is real"* -- so the assertions this file makes about the HARNESS matter as much as
the ones the harness makes about the store.

**THE TEST THIS FILE EXISTS FOR IS `test_the_matrix_goes_red_when_completes_transaction_is_split`.**
A crash matrix that cannot fail is worse than none: it would report forty green cycles over a
store whose participants commit separately, which is the exact claim it exists to check. That test
injects a `complete()` split into two transactions -- through the `kill` seam, never by editing
`store/queue.py` -- and asserts the matrix names the divergence.

Two more properties are here because a harness can be quietly hollow in two other ways:

* **Every boundary is reached.** `_Tracer.seen` is compared against the enumeration, per boundary,
  so a boundary that was skipped is a failure rather than a cycle that ran faster. 11-repo-layout.md
  section 6.8 asks this of every check that discovers its own inputs.
* **The comparison is live.** `test_the_comparison_sees_one_changed_character_of_one_block` mutates
  one block's text after a converged run and asserts the fingerprint diverges ON THE EXPORT. Both
  sides of the matrix's equality come from stores, so the equality has to be shown capable of
  being false.

**No `import sqlite3` here, and none is needed.** Four assertions read or write columns the store
boundary does not expose -- `work.status` and `work.cache_key` between a kill and a resume, `dep`'s
row count, and two deliberate corruptions of a `block` row -- and all four go through
`omniweave_core.store.sqlite`'s own `connect()` and `connect_readonly()`. TID251 (INV-17) is
therefore not tripped and ST1 holds by construction: `sqlite3.connect` appears in one module and
this is not it.

Specified in 16-roadmap.md:422 and :436-445, 17-risks.md:861, 13-quality.md:252,
07-store-and-retrieval.md:2730-2733, :2807 and 01-principles.md:1092.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave_core.errors import StoreError
from omniweave_core.store import crashmatrix as cm
from omniweave_core.store import sqlite as ow
from omniweave_core.store.queue import COMPLETE_PARTICIPANTS, SqliteStore

NOW_NS = 1_757_400_000_000_000_000
"""A fixed wall clock, as in `test_store_integration.py`: every store clock is injected."""

NOW_MS = 1 << 62
"""Past any lease the harness mints, so `resume()`'s reap sweeps what a crash left claimed."""

FIRST = cm.SCENARIOS[0]
"""One scenario, for the tests that need only one. `non_atomic_write`'s, and `free`."""

BILLED = next(s for s in cm.SCENARIOS if s.cost_class == "billed_api")
"""`no_fsync`'s scenario: the one that commits at `synchronous = FULL` (ST14, 07:2736)."""


# ---------------------------------------------------------------------------------------------
# The fixture list
# ---------------------------------------------------------------------------------------------


def test_the_fixture_list_is_dataflows_eight_checkpoint_failure_modes() -> None:
    """Eight, and the count is the plan's own number at four sites.

    01-principles.md:1092, 08-runtime.md:2175, 16-roadmap.md:422 and 17-risks.md:861 all say
    *"eight documented failure modes"*. `_plan/_notes/mine-runtime.md:580-620` is the only site
    that enumerates them, and `CHECKPOINT_FAILURE_MODES` transcribes that enumeration -- see the
    tuple's own docstring for the defect and the ruling.
    """
    assert len(cm.CHECKPOINT_FAILURE_MODES) == 8
    ids = [mode.id for mode in cm.CHECKPOINT_FAILURE_MODES]
    assert len(set(ids)) == 8, f"two modes share an id: {ids}"
    assert ids == [
        "non_atomic_write",
        "no_fsync",
        "written_per_batch",
        "lies_for_lazy_storage",
        "arbitrary_checkpoint_location",
        "no_plan_identity",
        "no_input_identity",
        "inverted_default_ergonomics",
    ]


@pytest.mark.parametrize("mode", cm.CHECKPOINT_FAILURE_MODES, ids=lambda m: m.id)
def test_every_failure_mode_names_a_defect_a_refusal_and_an_assertion(
    mode: cm.CheckpointFailureMode,
) -> None:
    """A fixture with no assertion is a paragraph, which is what 16:422 asked for fixtures over."""
    assert mode.dataflow.strip()
    assert mode.refusal.strip()
    assert mode.asserts.strip()


def test_there_is_one_scenario_per_failure_mode_and_one_of_them_is_billed() -> None:
    """The eight fixtures ARE the eight modes, and ST14 has a fixture of its own.

    `no_fsync`'s refusal is 07:2736's *"`synchronous = FULL` is set **before** `BEGIN`"*, so its
    scenario is the `billed_api` one -- `DURABLE_COST_CLASSES` is that single class -- and the
    other seven ride the general `NORMAL` case.
    """
    assert [s.mode for s in cm.SCENARIOS] == [m.id for m in cm.CHECKPOINT_FAILURE_MODES]
    billed = [s.mode for s in cm.SCENARIOS if s.cost_class == "billed_api"]
    assert billed == ["no_fsync"]
    assert len({s.part for s in cm.SCENARIOS}) == 8, "work_identity needs eight distinct parts"


# ---------------------------------------------------------------------------------------------
# The boundary enumeration
# ---------------------------------------------------------------------------------------------


def test_the_matrix_is_forty_statement_boundaries_over_eight_fixtures() -> None:
    """16-roadmap.md:422's "~40", arrived at from its own two numbers rather than chosen.

    Eight fixtures, three statements each (`work_transition` plus two `dep_insert`s), and
    `complete_boundaries()` is `len(plan) + 2`. Eight times five is forty. The count is written
    down here because a scenario losing a dep would otherwise shrink the matrix silently.
    """
    assert len(cm.matrix_boundaries()) == 40
    assert all(len(cm.boundaries_of(s)) == 5 for s in cm.SCENARIOS)


def test_each_scenarios_boundaries_are_its_plan_plus_begin_and_commit() -> None:
    """The names come from `queue.complete_boundaries()`, never from parsing `queue.py`.

    `Statement`'s own docstring is why: *"a crash matrix that had to find those by parsing this
    module's source would break on any edit to it."*
    """
    assert cm.boundaries_of(FIRST) == (
        "after:begin",
        "after:work_transition/work_update",
        "after:dep_rows/dep_insert[0]",
        "after:dep_rows/dep_insert[1]",
        "after:commit",
    )
    assert cm.boundaries_of(FIRST)[0] == cm.AFTER_BEGIN
    assert cm.boundaries_of(FIRST)[-1] == cm.AFTER_COMMIT


def test_the_plan_is_built_without_ever_reaching_a_connection() -> None:
    """`complete_plan()` is documented PURE, and `_NoThread` turns that into a runtime check.

    The participants come out in `COMPLETE_PARTICIPANTS` order, which is 07:2730-2733's order and
    02-architecture.md:487's: the `work` transition before the `dep` rows, so a crash between them
    is a boundary with a name.
    """
    plan = cm.plan_of(FIRST)
    assert [statement.participant for statement in plan] == [
        "work_transition",
        "dep_rows",
        "dep_rows",
    ]
    order = list(COMPLETE_PARTICIPANTS)
    seen = [order.index(statement.participant) for statement in plan]
    assert seen == sorted(seen), "a plan is emitted in COMPLETE_PARTICIPANTS order"


# ---------------------------------------------------------------------------------------------
# The three points: deterministic, and written down
# ---------------------------------------------------------------------------------------------


def test_the_three_pr_points_are_the_same_three_on_every_run() -> None:
    """G21's *"kill-9 at three points"*, drawn by blake2b and therefore reproducible.

    11-repo-layout.md:2185 is the rule as a lint message: *"Sampling is blake2b. Determinism is a
    gate, not a habit."* A `random.sample` would satisfy "three points" and make a CI failure
    impossible to reproduce locally, which is the whole reason the plan spells the mechanism.
    """
    assert cm.kill_points() == cm.kill_points()
    assert len(cm.kill_points()) == cm.PR_POINTS == 3


def test_the_three_pr_points_are_written_down_so_a_reported_failure_is_reproducible() -> None:
    """The drawn three, as literals. A change to the sampler has to be a deliberate edit here.

    This is the value pinned where a mutation cannot move it: both sides of every other assertion
    in this file come from the harness, and a draw asserted only against itself agrees with any
    sampler at all.
    """
    assert cm.kill_points() == (
        ("non_atomic_write", "after:work_transition/work_update"),
        ("no_plan_identity", "after:begin"),
        ("no_input_identity", "after:dep_rows/dep_insert[0]"),
    )


def test_a_different_salt_draws_a_different_three() -> None:
    """`--salt` is what a reviewer varies to widen the PR sample; it has to actually change it."""
    assert cm.kill_points(salt=b"ow-crash-2") != cm.kill_points(salt=cm.MATRIX_SALT)


def test_the_draw_is_a_subset_of_the_matrix_and_is_in_matrix_order() -> None:
    """A report reads left to right; the digest decides membership and not order."""
    population = cm.matrix_boundaries()
    drawn = cm.kill_points()
    assert set(drawn) <= set(population)
    assert [population.index(point) for point in drawn] == sorted(
        population.index(point) for point in drawn
    )


@pytest.mark.parametrize("count", [0, -1, 41])
def test_a_draw_the_matrix_cannot_satisfy_is_refused_rather_than_shortened(count: int) -> None:
    """A gate that says "three points" and silently ran two is section 6.8's unfalsifiable check."""
    with pytest.raises(StoreError):
        cm.kill_points(count=count)


# ---------------------------------------------------------------------------------------------
# Every boundary is actually reached
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> tuple[Path, Path]:
    """A seeded fixture store and its CAS: four migrations, eight enqueued `work` rows."""
    path = tmp_path / "index.owstore"
    cas = tmp_path / "cas"
    cm.seed(path, cas, now_ns=NOW_NS)
    return path, cas


def test_an_uninterrupted_run_stands_on_every_boundary_it_enumerated(
    store: tuple[Path, Path],
) -> None:
    """`len(plan) + 2` boundaries enumerated, `len(plan) + 2` boundaries walked.

    The guard against a silently hollow matrix: the tracer is armed on the store thread and the
    run reports what it saw, so a boundary the transaction never stood on cannot be reported as
    killed at.
    """
    path, cas = store
    seen: list[str] = []
    report = cm.run_scenario(path, cas, FIRST, on_boundary=seen.append)
    assert tuple(seen) == cm.boundaries_of(FIRST)
    assert report.reached == cm.boundaries_of(FIRST)
    assert report.completed and not report.superseded


@pytest.mark.parametrize("index", range(5))
def test_a_kill_stands_on_every_boundary_up_to_the_one_it_died_on_and_no_further(
    store: tuple[Path, Path], index: int
) -> None:
    """A kill at boundary `i` has walked exactly `i + 1` boundaries.

    A rollback is not one of them: `_transact` issues one on any raise and the tracer skips it,
    because counting it would make the run claim a boundary the transaction never stood on.
    """
    path, cas = store
    boundaries = cm.boundaries_of(FIRST)
    report = cm.simulate_kill_at(path, cas, FIRST, boundaries[index])
    assert report.killed_at == boundaries[index]
    if boundaries[index] == cm.AFTER_COMMIT:
        assert report.reached == boundaries
    else:
        assert report.reached == boundaries[: index + 1]


def test_a_boundary_no_scenario_has_is_refused(store: tuple[Path, Path]) -> None:
    """Killing at a name the enumeration does not hold is a typo, not a cycle that passed."""
    path, cas = store
    with pytest.raises(StoreError):
        cm.simulate_kill_at(path, cas, FIRST, "after:reservation_commit/nope")


# ---------------------------------------------------------------------------------------------
# What a kill leaves behind. The five modes with a store-level assertion.
# ---------------------------------------------------------------------------------------------


def _work(path: Path, part: str) -> tuple[str, str, int]:
    """`(status, cache_key, attempts_total)` for one `work` row. Raw columns; see the docstring."""
    connection = ow.connect_readonly(path)
    try:
        row = connection.execute(
            "SELECT status, cache_key, attempts_total FROM work WHERE unit_part = ?", (part,)
        ).fetchone()
    finally:
        connection.close()
    return str(row[0]), str(row[1]), int(row[2])


def _deps(path: Path) -> int:
    connection = ow.connect_readonly(path)
    try:
        return int(connection.execute("SELECT count(*) FROM dep").fetchone()[0])
    finally:
        connection.close()


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_a_kill_before_the_commit_leaves_the_transition_and_its_dep_rows_both_absent(
    store: tuple[Path, Path], index: int
) -> None:
    """`lies_for_lazy_storage`'s assertion, and the one 07:2730-2733 is actually about.

    DataFlow's checkpoint is written after `run()` returns and claims durability its storage never
    delivered, so resume skips work that was never done. Here the `work` transition and the rows
    it certifies are in ONE transaction: a kill at ANY boundary before the commit -- including the
    boundary AFTER the transition statement and BEFORE the first `dep` insert -- leaves the row
    still `claimed`, still carrying the placeholder `cache_key` the enqueue wrote, and leaves no
    `dep` row at all.
    """
    path, cas = store
    boundary = cm.boundaries_of(FIRST)[index]
    cm.simulate_kill_at(path, cas, FIRST, boundary)
    status, cache_key, attempts = _work(path, FIRST.part)
    assert status == "claimed", f"a kill at {boundary} left status {status}"
    assert cache_key == "planned", "the completion's cache_key committed without the transition"
    assert attempts == 1, "the claim cost one attempt and the crash cost nothing else"
    assert _deps(path) == 0, f"a kill at {boundary} left a dep row without its transition"


def test_a_kill_after_the_commit_loses_nothing(store: tuple[Path, Path]) -> None:
    """The other side of the same sentence: past `COMMIT`, every participant's rows are present.

    A matrix that only proved "nothing committed early" would be satisfied by a `complete()` that
    never commits at all.
    """
    path, cas = store
    cm.simulate_kill_at(path, cas, FIRST, cm.AFTER_COMMIT)
    status, cache_key, _attempts = _work(path, FIRST.part)
    assert status == "done"
    assert cache_key == cm.FIXTURE_CACHE_KEY
    assert _deps(path) == len(FIRST.deps)


def test_a_crashed_store_still_passes_integrity_check_and_foreign_key_check(
    store: tuple[Path, Path],
) -> None:
    """`non_atomic_write`'s assertion: there is no torn record to recover from.

    DataFlow's crash leaves a checkpoint that `map(int, "".split(","))` cannot read and that only
    a human deleting the file can clear (mine-runtime.md:582-586). A crash here leaves a store
    SQLite itself calls sound.
    """
    path, cas = store
    cm.simulate_kill_at(path, cas, FIRST, "after:dep_rows/dep_insert[0]")
    assert cm._integrity(path) == "ok"


def test_the_store_directory_gains_no_sidecar_checkpoint(tmp_path: Path) -> None:
    """`arbitrary_checkpoint_location`'s assertion. The store file is the only durable record.

    DataFlow puts its checkpoint in `op_nodes_list[1].storage` -- the first operator's cache
    directory -- and shares one counter across mixed storages. Here the converged directory holds
    exactly what the uninterrupted one holds, which is what makes `Fingerprint.sidecars` a
    comparison rather than a shrug.
    """
    base = tmp_path / "base"
    base.mkdir()
    clean = cm.baseline(base, now_ns=NOW_NS)
    cycle = tmp_path / "cycle"
    cycle.mkdir()
    result = cm.verify_boundary(
        cycle,
        FIRST.mode,
        "after:work_transition/work_update",
        now_ns=NOW_NS,
        now_ms=NOW_MS,
        baseline=clean,
    )
    assert result.ok, result.differences
    assert clean.sidecars == ("cas", "index.owstore")


def test_resume_gives_back_the_attempt_a_power_cut_cost(store: tuple[Path, Path]) -> None:
    """08:121-122: *"a power cut is not an attempt"*, and `attempts_total` is in the fingerprint.

    The claim increments, the reap decrements, the re-claim increments: an interrupted unit that
    converges shows the same one attempt as a unit that never crashed. A `reap_expired_leases`
    that forgot to decrement is a one-line regression and this is the assertion that sees it.
    """
    path, cas = store
    cm.simulate_kill_at(path, cas, FIRST, "after:dep_rows/dep_insert[0]")
    assert _work(path, FIRST.part)[2] == 1
    report = cm.resume(path, cas, now_ms=NOW_MS, scenarios=(FIRST,))
    assert report.reaped == 1
    assert report.reran == (FIRST.mode,)
    status, cache_key, attempts = _work(path, FIRST.part)
    assert (status, cache_key, attempts) == ("done", cm.FIXTURE_CACHE_KEY, 1)


def test_resume_is_idempotent_on_a_store_that_never_crashed(store: tuple[Path, Path]) -> None:
    """`inverted_default_ergonomics`'s assertion: recovery is re-running the ordinary command.

    01-principles.md:1092: *"the `work` table's claimable set **is** the checkpoint."* There is no
    resume mode to combine wrongly, and on a converged store the reap sweeps nothing and nothing
    re-runs.
    """
    path, cas = store
    cm.run_scenario(path, cas, FIRST)
    first = cm.resume(path, cas, now_ms=NOW_MS, scenarios=(FIRST,))
    second = cm.resume(path, cas, now_ms=NOW_MS, scenarios=(FIRST,))
    assert first.reaped == 0 and first.reran == ()
    assert second.reaped == 0 and second.reran == ()


def test_the_derive_step_is_skipped_when_the_page_is_already_present(
    store: tuple[Path, Path],
) -> None:
    """`no_input_identity`'s assertion. Resume subtracts what is done; it does not replay a plan.

    The first scenario derives the fixture page and every later one finds it present. A `derive()`
    that re-ran unconditionally would mint a second generation of the same input and the `.owdoc`
    export would stop matching -- which is DataFlow's *"positional slices of a different file"*
    with the polarity reversed.
    """
    path, cas = store
    assert cm.run_scenario(path, cas, cm.SCENARIOS[0]).derived is True
    assert cm.run_scenario(path, cas, cm.SCENARIOS[1]).derived is False
    cm.simulate_kill_at(path, cas, cm.SCENARIOS[2], "after:begin")
    assert cm.run_scenario(path, cas, cm.SCENARIOS[2]).derived is False


def test_one_transaction_per_unit_however_wide_the_plan(store: tuple[Path, Path]) -> None:
    """`written_per_batch`'s assertion: one commit per unit, not one write per statement.

    DataFlow opens, truncates, writes and closes its checkpoint once per batch, unbounded. Here
    the whole plan sits between one `BEGIN IMMEDIATE` and one `COMMIT`, which is what the tracer's
    own arithmetic asserts: it indexes only inside the SECOND `BEGIN` it sees and runs out of
    boundaries exactly at the commit.
    """
    path, cas = store
    seen: list[str] = []
    cm.run_scenario(path, cas, FIRST, on_boundary=seen.append)
    assert seen.count(cm.AFTER_BEGIN) == 1, "a second BEGIN would mean a second transaction"
    assert seen[-1] == cm.AFTER_COMMIT
    assert len(seen) == len(cm.plan_of(FIRST)) + 2


def test_the_billed_scenario_converges_exactly_as_the_free_one_does(tmp_path: Path) -> None:
    """`no_fsync`'s assertion. ST14 changes the pragma, not the outcome.

    07:2735-2740 sets `synchronous = FULL` before `BEGIN` for a `billed_api` unit. That is a
    durability decision about power loss; atomicity is the same transaction either way, and this
    is the cycle that says so.
    """
    base = tmp_path / "base"
    base.mkdir()
    clean = cm.baseline(base, now_ns=NOW_NS)
    cycle = tmp_path / "cycle"
    cycle.mkdir()
    result = cm.verify_boundary(
        cycle,
        BILLED.mode,
        "after:work_transition/work_update",
        now_ns=NOW_NS,
        now_ms=NOW_MS,
        baseline=clean,
    )
    assert result.ok, result.differences


# ---------------------------------------------------------------------------------------------
# The comparison: byte-for-byte on the `.owdoc` export
# ---------------------------------------------------------------------------------------------


def test_two_uninterrupted_runs_export_byte_identical_owdocs(tmp_path: Path) -> None:
    """The baseline is reproducible, in two directories, or nothing below means anything.

    16-roadmap.md:437 makes *"byte for byte in the `.owdoc` export"* the comparison. An archive
    that varied between two identical runs -- a clock, a pid, a dict order -- would make every
    cycle red and the matrix useless; `FIXTURE_WORKER` and `NOW_NS` are constants for exactly
    this reason.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    left = cm.baseline(first, now_ns=NOW_NS)
    right = cm.baseline(second, now_ns=NOW_NS)
    assert left.differences(right) == ()
    assert (first / "baseline.owdoc").read_bytes() == (second / "baseline.owdoc").read_bytes()


def test_the_comparison_sees_one_changed_character_of_one_block(tmp_path: Path) -> None:
    """THE PROOF THAT THE EXPORT HALF CAN FAIL, and it names the export rather than the rows.

    A byte comparison whose two sides are two archives of two stores is only worth something if a
    difference in a store reaches the archive. One `UPDATE block SET text` -- a deliberate
    corruption, through `ow.connect()` and never `sqlite3.connect` -- has to show up as an `owdoc`
    difference and NOT as a `work` or `dep` one, because a change to L2 is invisible to the
    runtime tables and that split is the reason `Fingerprint` carries both.
    """
    root = tmp_path / "one"
    root.mkdir()
    clean = cm.baseline(root, now_ns=NOW_NS)
    connection = ow.connect(root / "index.owstore")
    try:
        connection.execute("UPDATE block SET text = 'the FIRST paragraph' WHERE text IS NOT NULL")
        connection.commit()
    finally:
        connection.close()
    corrupted = cm.fingerprint(root / "index.owstore", root / "after.owdoc")
    differences = corrupted.differences(clean)
    assert differences, "a changed block reached neither the export nor the fingerprint"
    assert any(difference.startswith("owdoc ") for difference in differences), differences
    assert not any(difference.startswith("work ") for difference in differences), differences


def test_the_narrow_export_source_refuses_a_column_it_would_silently_drop(tmp_path: Path) -> None:
    """The projection is narrow BY DESIGN, and it raises rather than exporting a thinner archive.

    `archive.owdoc.ExportSource`'s own docstring homes the general implementation in P4's `Doc`
    (03:2584-2606). Until then this reads the columns the fixture writes; a block that grew a quad
    would otherwise compare equal on a column neither archive carried, which is a test that cannot
    fail.
    """
    root = tmp_path / "one"
    root.mkdir()
    cm.baseline(root, now_ns=NOW_NS)
    connection = ow.connect(root / "index.owstore")
    try:
        connection.execute("UPDATE block SET quad = X'00' WHERE parent_id IS NOT NULL")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StoreError, match="does not project"):
        cm.owdoc_bytes(root / "index.owstore", root / "after.owdoc")


# ---------------------------------------------------------------------------------------------
# The whole matrix, and the injection that proves it can go red
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory: pytest.TempPathFactory) -> cm.Fingerprint:
    """One uninterrupted run, shared by every cycle below: it is the right-hand side of G21."""
    root = tmp_path_factory.mktemp("crash-baseline")
    return cm.baseline(root, now_ns=NOW_NS)


@pytest.mark.parametrize(
    ("mode", "boundary"), cm.matrix_boundaries(), ids=lambda v: str(v).replace("/", ".")
)
def test_every_statement_boundary_converges_to_the_uninterrupted_run(
    tmp_path: Path, clean_run: cm.Fingerprint, mode: str, boundary: str
) -> None:
    """W2.9, forty times: *"SIGKILL at **every** statement boundary in `Store.complete()`"*.

    The kill here is `simulate_kill_at`, the in-process model -- `crashmatrix.py`'s docstring
    argues why a `Connection.interrupt()` from inside the trace callback leaves the same store a
    pre-COMMIT SIGKILL leaves, and `tools/gate_crash.py` runs the same forty cycles with a real
    signal. The library suite pays the fast one so the whole matrix is in every PR's unit run;
    G21 pays the real one.
    """
    result = cm.verify_boundary(
        tmp_path, mode, boundary, now_ns=NOW_NS, now_ms=NOW_MS, baseline=clean_run
    )
    assert result.ok, f"{result.label}: integrity={result.integrity} {result.differences}"
    assert result.reached, "the cycle reported standing on no boundary at all"


def _split_transaction_kill(
    path: Path, cas: Path, scenario: cm.Scenario, boundary: str
) -> cm.RunReport:
    """A `complete()` whose participants commit SEPARATELY, dying between the two transactions.

    The injection, and it is deliberately not an edit to `store/queue.py`. `SqliteStore`'s
    `dep_rows` `Contribution` is a constructor seam, so a store built WITHOUT it completes the
    `work` transition in one transaction and this function then dies before the `dep` rows are
    ever written -- which is precisely the shape 07:2730-2733 forbids: *"one unit's derived rows,
    its `work` transition, its `dep` rows ... together or not at all."*

    A resume cannot recover it, and that is the point: the row is `done`, so the claimable set --
    which IS the checkpoint (01-principles.md:1092) -- says there is nothing to do, and the `dep`
    rows are gone for good. This is DataFlow failure mode 4 reproduced inside omniweave, and the
    matrix has to report it.
    """
    with cm.reopen(path) as thread:
        producer = thread.run(
            ow.Unit(name="split.producer", run=cm._producer_id, cost_class="free")
        )
        cm.derive(thread, cas, scenario, producer_id=int(producer))
        store = SqliteStore(thread)  # no dep_rows contribution: the transition commits alone.
        rows = store.claim(
            batch=1,
            gen=cm.FIXTURE_GEN,
            worker=cm.FIXTURE_WORKER,
            lease_ms=cm.FIXTURE_LEASE_MS,
        )
        wanted = [row for row in rows if row.unit_part == scenario.part]
        store.complete(wanted[0].id, cm.FIXTURE_GEN, cm._result(scenario))
    return cm.RunReport(scenario.mode, False, True, False, (), boundary)


def test_the_matrix_goes_red_when_completes_transaction_is_split_in_two(
    tmp_path: Path, clean_run: cm.Fingerprint
) -> None:
    """THE TEST THIS FILE EXISTS FOR. A crash matrix that cannot fail is worse than none.

    17-risks.md:861 calls the matrix *"the only evidence that INV-17's 'commit together' claim is
    real"*. Evidence that cannot come out negative is not evidence, so a real non-atomicity is
    injected through the `kill` seam and the matrix is required to name it.

    The divergence is asserted to be the `dep` table's, specifically: a store that committed the
    `work` transition alone has a `done` row and no `dep` rows, so `Fingerprint.tables['dep']`
    differs while the `.owdoc` export -- which carries L2 only -- does not. That is also the
    reason `Fingerprint` compares more than the archive: 07:2730-2733 names five participants and
    the archive can see one.
    """
    result = cm.verify_boundary(
        tmp_path,
        FIRST.mode,
        "after:work_transition/work_update",
        now_ns=NOW_NS,
        now_ms=NOW_MS,
        baseline=clean_run,
        kill=_split_transaction_kill,
    )
    assert not result.ok, "a complete() split into two transactions was reported as converged"
    assert any(difference.startswith("dep ") for difference in result.differences), (
        result.differences
    )


def test_the_matrix_reports_every_cycle_it_ran_and_not_only_the_failures(
    tmp_path: Path,
) -> None:
    """`crash_matrix()` is `ow test crash-matrix`: a report, not a boolean.

    Two cycles over one fixture, so the assertion is on the shape rather than on the clock: every
    point asked for comes back as a `BoundaryResult`, in the order it was run, and `ok` is the
    conjunction.
    """
    points = cm.matrix_boundaries((FIRST,))[:2]
    report = cm.crash_matrix(tmp_path, now_ns=NOW_NS, now_ms=NOW_MS, points=points)
    assert [(r.mode, r.boundary) for r in report.results] == list(points)
    assert report.ok and report.failures == ()
    assert report.baseline.owdoc


# ---------------------------------------------------------------------------------------------
# Heal-on-open
# ---------------------------------------------------------------------------------------------


def test_reopen_records_the_wal_it_found_and_carries_the_threshold_through(
    store: tuple[Path, Path],
) -> None:
    """`reopen()` is the heal-on-open seam (07:2807); this asserts the seam, not the heal.

    **The heal itself cannot be shown from inside one process, and that is a fact about SQLite
    rather than a gap here.** A `wal_checkpoint(TRUNCATE)` requires every other connection to be
    gone, and a WAL only survives its writer if that writer did NOT close -- a clean close
    checkpoints and deletes the sidecar. So a process that still holds the connection that made
    the WAL oversized gets `SQLITE_BUSY`, which `heal_wal` swallows by design (*"a failed heal is
    a missed optimisation and a raised one would fail an open on a healthy store"*). The real
    assertion therefore needs a real killed process and lives in
    `tests/unit/test_gate_crash.py::test_a_reopen_after_a_real_kill_heals_an_oversized_wal`,
    which is also the shape 07:181-183 measured: **25.6 GB** of leaked WAL across
    repeatedly-SIGKILLed sessions.

    What is asserted here is that `reopen()` reads the sidecar before it opens and hands the
    threshold to `heal_wal` unchanged, so the gate's assertion has something to be about.
    """
    path, _cas = store
    cm.run_scenario(path, _cas, FIRST)
    opened = cm.reopen(path, wal_heal_mb=1)
    assert opened.wal_heal_mb == 1
    assert opened.wal_before == ow.wal_bytes(path)
    with opened:
        pass
    assert opened.reclaimed == 0, "a store with no oversized WAL has nothing to reclaim"
