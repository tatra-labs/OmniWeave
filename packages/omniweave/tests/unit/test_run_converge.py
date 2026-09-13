"""`op.converge`: the dep delta, the cost-class-aware requeue, the guard, and the disclosure.

Three tests are defect reports rather than behaviour checks:

`test_the_anchor_half_is_not_reported_as_clean_when_nothing_was_diffed` is **D177**. `anchor` gets
its writer at W8.2 and `bound_by` its unbind at W8.3, four phases after W4.6 schedules
`anchor_delta` — and `16-roadmap.md:32`'s FE3 names this exact mechanism as its own example of what
goes wrong. The test asserts the pass cannot report a complete convergence it did not verify.

`test_the_attribution_guard_is_named_five_times_and_specified_nowhere` is **D178**: five settled
lines carrying four distinct statements, none of which says what the guard checks.

`test_no_settled_document_names_the_guards_failure_class_or_its_override` is D178's second half: the
mining note asks for an `UNEXPLAINED_LOSS` class and an `--allow-unexplained-loss` flag, and the
settled `FailureClass` has thirteen members and the settled override list has six entries.

The load-bearing behaviour test is `test_a_billed_dependent_is_deferred_and_never_re_run`: 08:1877
is unusually blunt about the consequence, and the shipped `dispatch_policy` ladder is three lines
whose middle one depends on the trigger.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import omniweave_core.store.sqlite as ow
import pytest
from omniweave.run.converge import (
    ACCOUNTED_REASONS,
    BASELINE_UNREADABLE,
    CONVERGE_STAGE,
    DEFER_SQL,
    OP_CONVERGE,
    OP_CONVERGE_COST_CLASS,
    OP_CONVERGE_PRIORITY,
    OP_CONVERGE_VERSION,
    REQUEUE_SQL,
    UNEXPLAINED_LOSS_REASON,
    AnchorDelta,
    AnchorSource,
    Baseline,
    ConvergeReport,
    Loss,
    anchor_delta,
    anchor_deltas,
    attribution_guard,
    converge,
    requeue,
)
from omniweave.run.expand import OP_IDENTIFY_PRIORITY
from omniweave_core.deps import Change
from omniweave_core.events import EventKind, Stage
from omniweave_core.store import migrate
from omniweave_core.store.deps import SqliteDepIndex
from omniweave_ports.types import FailureClass

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from conftest import PlanDocs

NOW_NS = 1_757_400_000_000_000_000
NOW_MS = 1_757_400_000_000
URI = "file:///corpus/a.pdf"
OTHER = "file:///corpus/b.pdf"
SHA = "a" * 64
OTHER_SHA = "b" * 64

_SEED = (
    "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen)"
    " VALUES('file:///corpus/a.pdf', 'planned', 'internal', 1)",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, cost_class,"
    " status, claimed_by, claimed_gen, lease_expires)"
    " VALUES(1, 'file:///corpus/a.pdf', 'p1', 'op.converge', 1, 'k1', 'free', 'done',"
    " 'host:1:2.0', 4, 99)",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, cost_class,"
    " status) VALUES(2, 'file:///corpus/a.pdf', 'p2', 'op.converge', 1, 'k2', 'free', 'done')",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, cost_class,"
    " status) VALUES(3, 'file:///corpus/a.pdf', 'p3', 'op.cluster', 1, 'k3', 'local_compute',"
    " 'done')",
)
"""One unit and three `op.*` rows. Row 1 carries a lease so the requeue's clearing is observable."""


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        with connection:
            for statement in _SEED:
                connection.execute(statement)
    finally:
        connection.close()
    return path


@pytest.fixture
def thread(owstore: Path) -> Iterator[ow.StoreThread]:
    handle = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield handle
    finally:
        handle.close()


def write_deps(path: Path, rows: Sequence[tuple[int, str, str, str]]) -> None:
    connection = ow.connect(path)
    try:
        with connection:
            connection.executemany(
                "INSERT INTO dep(dependent_id, kind, key, digest) VALUES(?, ?, ?, ?)", rows
            )
    finally:
        connection.close()


def rows_of(path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = ow.connect(path)
    try:
        return [tuple(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


class _Anchors:
    """An `AnchorSource` over a literal map. There is no store-backed one until W8.2 (D177)."""

    def __init__(self, at: dict[tuple[str, int], frozenset[tuple[str, str]]]) -> None:
        self.at = at

    def anchors(self, doc: str, gen: int, /) -> frozenset[tuple[str, str]]:
        return self.at.get((doc, gen), frozenset())


# =============================================================================================
# 1. The operator row
# =============================================================================================


def test_the_operator_is_the_one_the_manifest_prints(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert '"operator": "op.converge", "op_version": 1, "cost_class": "free"' in text
    assert (OP_CONVERGE, OP_CONVERGE_VERSION, OP_CONVERGE_COST_CLASS) == ("op.converge", 1, "free")


def test_the_priority_is_the_one_the_table_gives_it(plan: PlanDocs) -> None:
    """08:619 puts `op.converge` and `op.identify` on one row at one number."""
    plan.require()
    row = plan.grep(r"^\| 300 \| `op\.converge`", documents=("08-runtime.md",))
    assert len(row) == 1
    assert "op.identify" in row[0].text
    assert OP_CONVERGE_PRIORITY == OP_IDENTIFY_PRIORITY == 300


def test_the_stage_is_the_closed_vocabularys_own_member() -> None:
    assert CONVERGE_STAGE is Stage.CONVERGE


def test_the_stage_closes_on_what_this_module_does(plan: PlanDocs) -> None:
    plan.require()
    row = plan.grep(r"^\| `converge` \|", documents=("15-observability.md",))
    assert len(row) == 1
    assert "the `anchor_delta` applied, dependents enqueued" in row[0].text


# =============================================================================================
# 2. `anchor_delta` -- the pure function (D177)
# =============================================================================================


def test_a_body_only_edit_leaves_the_delta_empty() -> None:
    """06:2301's common case, and the one the whole mechanism is cheap because of."""
    names = [("3.1", "figure"), ("4.2", "section")]
    delta = anchor_delta(URI, names, names)
    assert delta.empty
    assert (delta.added, delta.removed) == ((), ())


def test_a_renamed_heading_removes_one_pair_and_adds_another() -> None:
    """06:2334's matrix row *"a heading renamed"*: old `(name, section)` out, new one in."""
    delta = anchor_delta(URI, [("scope", "section")], [("purpose", "section")])
    assert delta.added == (("purpose", "section"),)
    assert delta.removed == (("scope", "section"),)


def test_a_deleted_bookmark_removes_and_adds_nothing() -> None:
    """06:2335: *"a bookmark deleted"* -> `{(name, bookmark)}` removed -> unbind, 0 rows deleted."""
    delta = anchor_delta(URI, [("intro", "identifier")], [])
    assert delta.removed == (("intro", "identifier"),)
    assert delta.added == ()


def test_a_new_document_adds_its_own_anchors() -> None:
    delta = anchor_delta(OTHER, [], [("3.2", "figure")])
    assert delta.added == (("3.2", "figure"),)
    assert not delta.empty


def test_the_delta_is_per_document_so_a_name_moving_between_two_cannot_cancel_itself() -> None:
    """06:2296 states the reason in capitals; this is the case it protects against."""
    source = _Anchors(
        {
            (URI, 1): frozenset({("3.1", "figure")}),
            (URI, 2): frozenset(),
            (OTHER, 1): frozenset(),
            (OTHER, 2): frozenset({("3.1", "figure")}),
        }
    )
    deltas = anchor_deltas([URI, OTHER], source=source, before_gen=1, after_gen=2)
    assert deltas[0].removed == (("3.1", "figure"),)
    assert deltas[1].added == (("3.1", "figure"),)
    assert sum(1 for d in deltas if not d.empty) == 2


def test_every_document_examined_gets_a_delta_even_an_empty_one() -> None:
    """ "No anchors moved" and "no document was examined" must not be the same value."""
    source = _Anchors({})
    assert len(anchor_deltas([URI, OTHER], source=source, before_gen=1, after_gen=2)) == 2


def test_the_delta_is_sorted_so_two_runs_produce_one_in_list() -> None:
    delta = anchor_delta(URI, [], [("b", "figure"), ("a", "figure")])
    assert delta.added == (("a", "figure"), ("b", "figure"))


def test_the_pairs_are_name_norm_then_akind(plan: PlanDocs) -> None:
    plan.require()
    assert plan.grep(r"\(name_norm, akind\) pairs")


def test_the_anchor_source_protocol_is_not_runtime_checkable() -> None:
    checked: AnchorSource = _Anchors({})
    assert checked.anchors(URI, 1) == frozenset()
    assert getattr(AnchorSource, "_is_runtime_protocol", False) is False


# =============================================================================================
# 3. D177 -- the disclosure
# =============================================================================================


def test_anchor_writers_arrive_four_phases_after_this_cell(plan: PlanDocs) -> None:
    """D177: W4.6 is P4; `anchor` is W8.2 and `bound_by`'s unbind is W8.3, both P8."""
    plan.require()
    rows = plan.grep(r"^\| W8\.[23] \|", documents=("16-roadmap.md",))
    assert len(rows) == 2
    assert "`anchor`, `ref_site`, `ref_unresolved`" in rows[0].text
    assert "unbind-on-`anchor_delta`-removal" in rows[1].text


def test_fe3_names_this_mechanism_in_its_own_list_of_examples(plan: PlanDocs) -> None:
    plan.require()
    fe3 = plan.grep(r"\*\*FE3\*\*", documents=("16-roadmap.md",))
    assert len(fe3) == 1
    assert "`anchor_delta` diffs two `anchor` generations" in fe3[0].text
    assert "ships as a stub that always reports clean" in fe3[0].text


def test_the_anchor_half_is_not_reported_as_clean_when_nothing_was_diffed(
    thread: ow.StoreThread,
) -> None:
    """D177's shipped answer: a pass with no `AnchorSource` discloses rather than reports clean."""
    report = converge(
        thread,
        (),
        index=SqliteDepIndex(thread),
        cost_classes=lambda _ids: {},
        trigger="cli",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
    )
    assert report.anchors_tracked is False
    assert report.anchor_deltas == ()
    assert report.complete is False


def test_a_tracked_pass_with_no_movement_is_complete(thread: ow.StoreThread) -> None:
    """The distinction the disclosure buys: zero deltas examined vs zero deltas moved."""
    report = converge(
        thread,
        (),
        index=SqliteDepIndex(thread),
        cost_classes=lambda _ids: {},
        trigger="cli",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
        anchors=([URI], _Anchors({}), 1, 2),
    )
    assert report.anchors_tracked is True
    assert report.anchors_moved == 0
    assert report.complete is True


# =============================================================================================
# 4. The dep delta and the requeue
# =============================================================================================


def test_a_free_dependent_goes_back_to_pending(owstore: Path, thread: ow.StoreThread) -> None:
    assert requeue(thread, {1: "free"}, trigger="watch", now_ms=NOW_MS) == (1, 0)
    assert rows_of(owstore, "SELECT status FROM work WHERE id = 1") == [("pending",)]


def test_the_requeue_clears_the_lease_because_the_claim_is_the_lease(
    owstore: Path, thread: ow.StoreThread
) -> None:
    """I23: a pending row still holding `claimed_by` is one the reaper reads as leased."""
    requeue(thread, {1: "free"}, trigger="cli", now_ms=NOW_MS)
    assert rows_of(
        owstore, "SELECT claimed_by, claimed_gen, lease_expires, retry_after FROM work WHERE id = 1"
    ) == [(None, None, None, None)]


def test_a_billed_dependent_is_deferred_and_never_re_run(
    owstore: Path, thread: ow.StoreThread
) -> None:
    """08:1877 -- *"a watcher that silently re-bills a VLM pass ... ends a pilot."*"""
    assert requeue(thread, {2: "billed_api"}, trigger="cli", now_ms=NOW_MS) == (0, 1)
    assert rows_of(owstore, "SELECT status, failure_class FROM work WHERE id = 2") == [
        ("deferred", None)
    ]


def test_local_compute_follows_the_trigger(owstore: Path, thread: ow.StoreThread) -> None:
    """08:1866's middle line, and the two route gates 08:1871 names are why it is the trigger."""
    assert requeue(thread, {3: "local_compute"}, trigger="watch", now_ms=NOW_MS) == (0, 1)
    assert rows_of(owstore, "SELECT status FROM work WHERE id = 3") == [("deferred",)]


def test_local_compute_under_the_cli_runs_now(owstore: Path, thread: ow.StoreThread) -> None:
    assert requeue(thread, {3: "local_compute"}, trigger="cli", now_ms=NOW_MS) == (1, 0)
    assert rows_of(owstore, "SELECT status FROM work WHERE id = 3") == [("pending",)]


def test_stale_since_is_stamped_on_the_first_transition_and_kept_across_a_reset(
    owstore: Path, thread: ow.StoreThread
) -> None:
    """08:1891: it measures how long the answer has been untrustworthy, not the attempt."""
    requeue(thread, {1: "free"}, trigger="cli", now_ms=NOW_MS)
    first = rows_of(owstore, "SELECT stale_since FROM work WHERE id = 1")
    assert first == [(NOW_MS,)]
    connection = ow.connect(owstore)
    try:
        with connection:
            connection.execute("UPDATE work SET status = 'done' WHERE id = 1")
    finally:
        connection.close()
    requeue(thread, {1: "free"}, trigger="cli", now_ms=NOW_MS + 900_000)
    assert rows_of(owstore, "SELECT stale_since FROM work WHERE id = 1") == first


def test_a_row_already_pending_is_left_alone(thread: ow.StoreThread) -> None:
    """Idempotent across two passes: re-opening a claimed row would clear a live lease."""
    requeue(thread, {1: "free"}, trigger="cli", now_ms=NOW_MS)
    assert requeue(thread, {1: "free"}, trigger="cli", now_ms=NOW_MS) == (0, 0)


def test_an_empty_dependent_set_touches_nothing(thread: ow.StoreThread) -> None:
    assert requeue(thread, {}, trigger="cli", now_ms=NOW_MS) == (0, 0)


def test_the_pass_joins_the_dep_delta_to_the_requeue(owstore: Path, thread: ow.StoreThread) -> None:
    write_deps(owstore, [(1, "unit", OTHER, SHA), (2, "unit", OTHER, SHA)])
    seen: list[dict[str, object]] = []
    report = converge(
        thread,
        (Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),),
        index=SqliteDepIndex(thread),
        cost_classes=lambda ids: dict.fromkeys(ids, "free"),
        trigger="watch",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
        emit=lambda **kwargs: seen.append(kwargs),
    )
    assert report.dependents == frozenset({1, 2})
    assert (report.requeued, report.deferred) == (2, 0)
    assert rows_of(owstore, "SELECT status FROM work WHERE id IN (1,2) ORDER BY id") == [
        ("pending",),
        ("pending",),
    ]
    assert seen[0]["kind"] is EventKind.DEP_INVALIDATE
    assert seen[0]["fields"] == {"kind": "unit", "keys": 1, "dependents": 2}


def test_the_pass_emits_nothing_for_an_empty_delta(thread: ow.StoreThread) -> None:
    seen: list[dict[str, object]] = []
    converge(
        thread,
        (),
        index=SqliteDepIndex(thread),
        cost_classes=lambda _ids: {},
        trigger="cli",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
        emit=lambda **kwargs: seen.append(kwargs),
    )
    assert seen == []


def test_the_pass_rederives_stat(owstore: Path, thread: ow.StoreThread) -> None:
    """07:721 gives `stat` two writers and this is one of them."""
    report = converge(
        thread,
        (),
        index=SqliteDepIndex(thread),
        cost_classes=lambda _ids: {},
        trigger="cli",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
    )
    assert set(report.stat) == {"live_blocks", "live_segments"}
    assert rows_of(owstore, "SELECT k, v FROM stat ORDER BY k") == [
        ("live_blocks", 0),
        ("live_segments", 0),
    ]


def test_the_two_statements_move_the_columns_the_transition_table_names() -> None:
    assert "status = 'pending'" in REQUEUE_SQL
    assert "COALESCE(stale_since, :now_ms)" in REQUEUE_SQL
    assert "COALESCE(stale_since, :now_ms)" in DEFER_SQL
    assert "failure_class = NULL" in DEFER_SQL


# =============================================================================================
# 5. The attribution guard (D178)
# =============================================================================================


def test_the_attribution_guard_is_named_five_times_and_specified_nowhere(
    plan: PlanDocs,
) -> None:
    """D178. Five lines, four distinct statements, no section, no pseudocode, no flag."""
    plan.require()
    settled = [
        hit for hit in plan.grep(r"attribution guard") if not hit.document.startswith("_notes/")
    ]
    assert {hit.document for hit in settled} == {
        "02-architecture.md",
        "07-store-and-retrieval.md",
        "16-roadmap.md",
        "README.md",
        "glossary.md",
    }
    trees = ("02-architecture.md", "README.md")
    tree = {hit.text.strip() for hit in settled if hit.document in trees}
    assert len(tree) == 1, "README's module tree is a verbatim copy of 02's, so four statements"
    assert len(settled) == 5, "a settled document started specifying it; D178 can close"
    settled_docs = tuple(d for d in plan.documents() if not d.startswith("_notes/"))
    assert not plan.grep(r"accounted iff|rows_before\(", documents=settled_docs)


def test_no_settled_document_names_the_guards_failure_class_or_its_override(
    plan: PlanDocs,
) -> None:
    """D178's second half: the note asks for two things the settled vocabulary does not have."""
    plan.require()
    settled_docs = tuple(d for d in plan.documents() if not d.startswith("_notes/"))
    assert not plan.grep(r"UNEXPLAINED_LOSS|allow-unexplained-loss", documents=settled_docs)
    assert plan.grep(r"allow-unexplained-loss"), "the mining note is where the guard is specified"
    assert len(FailureClass) == 13
    assert not any(member.value == "unexplained_loss" for member in FailureClass)


def test_a_re_derived_unit_accounts_for_its_own_loss() -> None:
    found = attribution_guard(
        {(URI, "derive.entity"): 3},
        baseline=Baseline.of({(URI, "derive.entity"): 7}),
        reasons={URI: "rederived"},
    )
    assert found == ()


def test_a_deleted_unit_accounts_for_its_loss() -> None:
    found = attribution_guard(
        {}, baseline=Baseline.of({(URI, "derive.entity"): 7}), reasons={URI: "deleted"}
    )
    assert found == ()


def test_a_failed_unit_never_accounts_for_its_loss() -> None:
    """The starred clause: a failed operator is the most likely cause, so it is never the excuse."""
    found = attribution_guard(
        {(URI, "derive.entity"): 0},
        baseline=Baseline.of({(URI, "derive.entity"): 7}),
        reasons={URI: "failed"},
    )
    assert len(found) == 1
    assert found[0].lost == 7
    assert UNEXPLAINED_LOSS_REASON in found[0].message


def test_a_unit_with_no_recorded_reason_is_refused() -> None:
    found = attribution_guard(
        {(URI, "derive.entity"): 1}, baseline=Baseline.of({(URI, "derive.entity"): 7}), reasons={}
    )
    assert len(found) == 1
    assert "none recorded" in found[0].message


def test_the_guard_is_per_owner_so_an_equal_size_swap_is_caught() -> None:
    """I4: a free re-extraction must not silently delete an LLM pass's billable rows."""
    before = {(URI, "derive.ast"): 5, (URI, "derive.entity.llm"): 5}
    after = {(URI, "derive.ast"): 10, (URI, "derive.entity.llm"): 0}
    found = attribution_guard(after, baseline=Baseline.of(before), reasons={URI: "rederived"})
    assert found == (), "a re-derivation by the owner accounts for its own loss"
    found = attribution_guard(after, baseline=Baseline.of(before), reasons={})
    assert [loss.owner for loss in found] == ["derive.entity.llm"]


def test_a_growing_unit_is_never_a_loss() -> None:
    found = attribution_guard(
        {(URI, "derive.ast"): 9}, baseline=Baseline.of({(URI, "derive.ast"): 2}), reasons={}
    )
    assert found == ()


def test_an_absent_baseline_refuses_nothing() -> None:
    """There was no previous run, so nothing was lost. Distinct from unreadable."""
    assert attribution_guard({(URI, "x"): 0}, baseline=Baseline.none(), reasons={}) == ()


def test_an_unreadable_baseline_refuses_everything() -> None:
    """The fail-closed rule: `except Exception: return {}` is the failure this prevents."""
    found = attribution_guard(
        {(URI, "derive.ast"): 4}, baseline=Baseline.unreadable(), reasons={URI: "rederived"}
    )
    assert len(found) == 1
    assert found[0].reason == BASELINE_UNREADABLE


def test_the_override_accepts_a_shrink_and_never_an_unreadable_baseline() -> None:
    """*"force means 'accept a shrink', not 'clobber an unreadable graph'"* -- graphify's own scope.

    An operator who waves a loss through has looked at a loss. An unreadable baseline is the case
    where nobody saw anything, so there is nothing for them to have accepted -- and an override that
    silenced it would be *"an off switch"* rather than an override.
    """
    found = attribution_guard(
        {(URI, "derive.ast"): 4},
        baseline=Baseline.unreadable(),
        reasons={URI: "rederived"},
        allow=True,
    )
    assert len(found) == 1
    assert found[0].reason == BASELINE_UNREADABLE


def test_the_three_baseline_states_are_distinguishable() -> None:
    """`if not baseline:` is unrepresentable, which is the point of the tagged type."""
    assert {Baseline.of({}).state, Baseline.none().state, Baseline.unreadable().state} == {
        "known",
        "absent",
        "unreadable",
    }


def test_the_override_is_named_and_scoped_not_a_force() -> None:
    found = attribution_guard(
        {(URI, "derive.ast"): 0},
        baseline=Baseline.of({(URI, "derive.ast"): 7}),
        reasons={URI: "failed"},
        allow=True,
    )
    assert found == ()


def test_the_accounted_reasons_are_the_notes_three() -> None:
    assert ACCOUNTED_REASONS == ("rederived", "deleted", "out_of_scope")
    assert "failed" not in ACCOUNTED_REASONS


def test_a_loss_reports_what_it_lost() -> None:
    loss = Loss(unit_uri=URI, owner="derive.ast", before=9, after=4, reason="rederived")
    assert (loss.lost, loss.accounted) == (5, True)


def test_the_guard_reaches_the_report_and_makes_it_incomplete(thread: ow.StoreThread) -> None:
    report = converge(
        thread,
        (),
        index=SqliteDepIndex(thread),
        cost_classes=lambda _ids: {},
        trigger="cli",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
        anchors=([URI], _Anchors({}), 1, 2),
        guard=({}, Baseline.of({(URI, "derive.ast"): 3}), {}),
    )
    assert len(report.unexplained) == 1
    assert report.complete is False


def test_the_override_reaches_the_pass(thread: ow.StoreThread) -> None:
    report = converge(
        thread,
        (),
        index=SqliteDepIndex(thread),
        cost_classes=lambda _ids: {},
        trigger="cli",
        now_ms=NOW_MS,
        now_ns=NOW_NS,
        anchors=([URI], _Anchors({}), 1, 2),
        guard=({}, Baseline.of({(URI, "derive.ast"): 3}), {}),
        allow_unexplained_loss=True,
    )
    assert report.unexplained == ()
    assert report.complete is True


# =============================================================================================
# 6. What the plan says this pass is for
# =============================================================================================


def test_the_pass_must_ship_before_the_watcher(plan: PlanDocs) -> None:
    plan.require()
    hits = plan.grep(r"must ship \*\*before\*\* the watcher|\*\*must ship before the watcher\*\*")
    assert hits, "08 and 07 both state the ordering constraint this cell exists to honour"


def test_the_watcher_does_not_exist_in_v1(plan: PlanDocs) -> None:
    plan.require()
    assert plan.grep(r"`ow watch` does not exist", documents=("16-roadmap.md",))


def test_the_five_jobs_are_the_ones_07_lists(plan: PlanDocs) -> None:
    plan.require()
    joined = " ".join(plan.lines("07-store-and-retrieval.md"))
    sentence = re.search(
        r"The \*\*converge pass\*\* \(`op\.converge`\) is the run-final step that (.{0,220})",
        joined,
    )
    assert sentence is not None
    for job in ("anchor_delta", "dep` reverse index", "re-derives `stat`", "attribution guard"):
        assert job in sentence.group(1)


def test_the_report_names_both_halves_and_refuses_to_average_them() -> None:
    report = ConvergeReport(
        dependents=frozenset(),
        requeued=0,
        deferred=0,
        anchors_tracked=False,
        anchor_deltas=(AnchorDelta(doc=URI, added=(), removed=()),),
        unexplained=(),
        stat={},
    )
    assert report.complete is False
    assert report.anchors_moved == 0
