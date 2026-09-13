"""`SqliteDepIndex`: the invalidation query against a real store, and the cohort writer.

The load-bearing test is `test_the_delta_is_a_set_and_the_previous_calls_delta_is_gone`: the TEMP
table is `IF NOT EXISTS` plus `DELETE FROM` (07:1601-1603), `StoreThread` reuses one connection for
the life of the store, and a second call that saw the first call's rows would invalidate work
nothing in this pass touched.

Two properties are asserted against behaviour rather than against source text:

* **One `Unit` per call.** `dependents()` runs three statements -- clear, insert, join -- and they
  must land in one transaction, because a delta materialised in one and joined in another can be
  joined against a `dep` table that moved between them.
* **No chunking, no `IN` list.** A delta of 2,000 keys is one insert and one join; there is no
  `SQLITE_MAX_VARIABLE_NUMBER` to reach, which is what makes 12-performance.md:1400's *"ONE query on
  `dep_reverse(kind, key)`"* true at corpus scale and not only for a handful of keys.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import omniweave_core.store.sqlite as ow
import pytest
from omniweave_core.deps import Change, Dep, cohort_of, invalidate, unit_key
from omniweave_core.errors import StoreError
from omniweave_core.operator import OperatorIdentity, Outcome, StepMetrics, StepResult
from omniweave_core.store import migrate
from omniweave_core.store.deps import (
    COHORT_MEMBER_SQL,
    COHORT_UPSERT_SQL,
    SqliteDepIndex,
    cohort_statements,
    dep_rows,
)
from omniweave_core.store.queue import SqliteStore
from omniweave_ports.types import UnitRef

# `import sqlite3` is banned outside `omniweave_core/store/` by TID251 (INV-17), and this file
# takes the escape `test_store_queue.py` takes, for the same reason: the last assertion is that
# `cohort_member`'s foreign key REFUSES a member whose parent row is absent, and catching
# `Exception` would pass on a typo in the SQL -- the one outcome that test exists to rule out.
# No `sqlite3.connect` appears here; every connection comes from `omniweave_core.store.sqlite`.

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from omniweave_core.store.queue import Statement

NOW_NS = 1_757_400_000_000_000_000
URI = "file:///corpus/a.pdf"
OTHER = "file:///corpus/b.pdf"
SHA = "a" * 64
OTHER_SHA = "b" * 64
CACHE_KEY = "c" * 64

_SEED = (
    "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen)"
    " VALUES('file:///corpus/a.pdf', 'planned', 'internal', 1)",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, cost_class,"
    " status) VALUES(1, 'file:///corpus/a.pdf', '', 'op.converge', 1, 'k1', 'free', 'pending')",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, cost_class,"
    " status) VALUES(2, 'file:///corpus/a.pdf', 'p1', 'op.converge', 1, 'k2', 'free', 'pending')",
    "INSERT INTO work(id, unit_uri, unit_part, operator, op_version, cache_key, cost_class,"
    " status) VALUES(3, 'file:///corpus/a.pdf', 'p2', 'op.converge', 1, 'k3', 'free', 'pending')",
)
"""One unit and three `op.*` work rows. An `op.*` operator is the only shape that needs no
`route_decision`: `0004_runtime.sql:125-127`'s three CHECKs make `decision_id`, `driver` and
`dispatch_key` NULL together, and `dep.dependent_id` references nothing else."""


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


@pytest.fixture
def index(thread: ow.StoreThread) -> SqliteDepIndex:
    return SqliteDepIndex(thread)


def write_deps(path: Path, rows: Sequence[tuple[int, str, str, str]]) -> None:
    """Insert `dep` rows directly, so a test can set up a past the query then reads."""
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


# =============================================================================================
# 1. The query
# =============================================================================================


def test_a_changed_digest_names_its_dependent(owstore: Path, index: SqliteDepIndex) -> None:
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    delta = (Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),)
    assert index.dependents(delta) == frozenset({1})


def test_an_unchanged_digest_names_nobody(owstore: Path, index: SqliteDepIndex) -> None:
    """The delta says "this is the current value"; the query does the differing."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    assert index.dependents((Change(kind="unit", key=OTHER, new_digest=SHA),)) == frozenset()


def test_a_key_outside_the_delta_names_nobody(owstore: Path, index: SqliteDepIndex) -> None:
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    delta = (Change(kind="unit", key="file:///corpus/z.pdf", new_digest=OTHER_SHA),)
    assert index.dependents(delta) == frozenset()


def test_the_kind_is_part_of_the_join(owstore: Path, index: SqliteDepIndex) -> None:
    """`dep_reverse` is `(kind, key)`, so a `name` dep and a `unit` dep on one string are two."""
    write_deps(owstore, [(1, "name", "figure:3.1", SHA)])
    assert index.dependents((Change(kind="unit", key="figure:3.1", new_digest="z" * 64),)) == (
        frozenset()
    )
    assert index.dependents((Change(kind="name", key="figure:3.1", new_digest="z" * 64),)) == (
        frozenset({1})
    )


def test_two_deps_of_one_work_row_changing_together_return_one_id(
    owstore: Path, index: SqliteDepIndex
) -> None:
    """`DISTINCT`: the answer is a set of work rows, not a count of reasons."""
    write_deps(owstore, [(1, "unit", OTHER, SHA), (1, "name", "figure:3.1", SHA)])
    delta = (
        Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),
        Change(kind="name", key="figure:3.1", new_digest=OTHER_SHA),
    )
    assert index.dependents(delta) == frozenset({1})


def test_one_change_can_name_several_dependents(owstore: Path, index: SqliteDepIndex) -> None:
    write_deps(owstore, [(1, "unit", OTHER, SHA), (2, "unit", OTHER, SHA), (3, "unit", OTHER, SHA)])
    delta = (Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),)
    assert index.dependents(delta) == frozenset({1, 2, 3})


def test_a_deleted_key_invalidates_through_the_absent_sentinel(
    owstore: Path, index: SqliteDepIndex
) -> None:
    """D176: `ABSENT_DIGEST` is `''`, which no recorded digest can be."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    assert index.dependents((Change(kind="unit", key=OTHER, new_digest=""),)) == frozenset({1})


def test_an_empty_delta_reaches_no_statement(index: SqliteDepIndex) -> None:
    assert index.dependents(()) == frozenset()


def test_invalidate_over_the_real_index(owstore: Path, index: SqliteDepIndex) -> None:
    """The pure entry point and the store half, joined -- 02 row 20's `invalidate(delta)`."""
    write_deps(owstore, [(2, "unit", OTHER, SHA)])
    delta = (Change(kind="unit", key=unit_key(OTHER), new_digest=OTHER_SHA),)
    assert invalidate(delta, index=index) == frozenset({2})


# =============================================================================================
# 2. The TEMP table
# =============================================================================================


def test_the_delta_is_a_set_and_the_previous_calls_delta_is_gone(
    owstore: Path, index: SqliteDepIndex
) -> None:
    """`IF NOT EXISTS` plus `DELETE FROM`; the `DELETE` is what makes call two right."""
    write_deps(owstore, [(1, "unit", OTHER, SHA), (2, "name", "figure:3.1", SHA)])
    first = index.dependents((Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),))
    second = index.dependents((Change(kind="name", key="figure:3.1", new_digest=OTHER_SHA),))
    assert first == frozenset({1})
    assert second == frozenset({2})


def test_a_second_call_does_not_fail_on_the_create(owstore: Path, index: SqliteDepIndex) -> None:
    """A bare `CREATE TEMP TABLE` would raise here: `StoreThread` reuses one connection."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    delta = (Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),)
    assert index.dependents(delta) == index.dependents(delta) == frozenset({1})


def test_one_key_observed_twice_in_one_delta_keeps_the_later_observation(
    owstore: Path, index: SqliteDepIndex
) -> None:
    """`INSERT OR REPLACE` on `PRIMARY KEY (kind, key)` -- the delta is a set."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    delta = (
        Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),
        Change(kind="unit", key=OTHER, new_digest=SHA),
    )
    assert index.dependents(delta) == frozenset()


def test_a_delta_far_past_the_variable_limit_is_one_call(
    owstore: Path, index: SqliteDepIndex
) -> None:
    """No chunking and no `IN` list: 2,000 keys is one insert and one join."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    delta = [Change(kind="unit", key=f"u{n}", new_digest=OTHER_SHA) for n in range(2_000)]
    delta.append(Change(kind="unit", key=OTHER, new_digest=OTHER_SHA))
    assert index.dependents(delta) == frozenset({1})


def test_the_three_statements_are_one_unit(owstore: Path, thread: ow.StoreThread) -> None:
    """One transaction, so the delta and the join cannot see two states of `dep`."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    submitted: list[str] = []
    real = thread.run

    def spy(unit: ow.Unit) -> object:
        submitted.append(unit.name)
        return real(unit)

    thread.run = spy  # type: ignore[method-assign]
    try:
        SqliteDepIndex(thread).dependents((Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),))
    finally:
        thread.run = real  # type: ignore[method-assign]
    assert submitted == ["deps.dependents"]


def test_the_unit_is_free_so_st14_does_not_force_synchronous_full(
    owstore: Path, thread: ow.StoreThread
) -> None:
    """Nothing here writes a durable row: the TEMP table dies with the connection."""
    write_deps(owstore, [(1, "unit", OTHER, SHA)])
    seen: list[ow.Unit] = []
    real = thread.run

    def spy(unit: ow.Unit) -> object:
        seen.append(unit)
        return real(unit)

    thread.run = spy  # type: ignore[method-assign]
    try:
        SqliteDepIndex(thread).dependents((Change(kind="unit", key=OTHER, new_digest=OTHER_SHA),))
    finally:
        thread.run = real  # type: ignore[method-assign]
    assert seen[0].cost_class == "free"
    assert seen[0].durable is False


# =============================================================================================
# 3. `dep_rows()` -- the `Contribution` the participant slot waited for
# =============================================================================================


def result_of() -> StepResult:
    return StepResult(
        outcome=Outcome.OK,
        cache_key=CACHE_KEY,
        unit=UnitRef(uri=URI, part="", content_sha256=SHA, byte_len=11),
        identity=OperatorIdentity(operator="op.converge", op_version=1, code_fingerprint="t"),
        metrics=StepMetrics(queued_ms=1, ran_ms=2, micros=0, rows_written=0),
    )


def test_the_contribution_produces_one_statement_per_dep(thread: ow.StoreThread) -> None:
    deps = (Dep(kind="unit", key=OTHER, digest=SHA), Dep(kind="name", key="figure:3.1", digest=SHA))
    store = SqliteStore(thread, dep_rows=dep_rows(deps))
    plan = store.complete_plan(1, result_of())
    contributed = [s for s in plan if s.participant == "dep_rows"]
    assert len(contributed) == 2
    assert all("INSERT OR IGNORE INTO dep" in s.sql for s in contributed)


def test_the_contribution_forwards_the_allowed_key_set(thread: ow.StoreThread) -> None:
    """08:1839's subset rule is checked at both ends; only the runner knows the set."""
    deps = (Dep(kind="unit", key=OTHER, digest=SHA),)
    store = SqliteStore(thread, dep_rows=dep_rows(deps, allowed_keys=frozenset({URI})))
    with pytest.raises(StoreError, match="outside the invocation's input set"):
        store.complete_plan(1, result_of())


def test_the_dep_rows_land_in_the_same_transaction_as_the_work_transition(
    owstore: Path, thread: ow.StoreThread
) -> None:
    deps = (Dep(kind="unit", key=OTHER, digest=SHA),)
    store = SqliteStore(thread, dep_rows=dep_rows(deps))
    claimed = store.claim(1, 7, "host:1:2.0", 60_000)
    assert claimed
    assert store.complete(claimed[0].id, 7, result_of()) is True
    assert rows_of(owstore, "SELECT kind, key, digest FROM dep") == [("unit", OTHER, SHA)]


def test_a_superseded_completion_writes_no_dep_rows(owstore: Path, thread: ow.StoreThread) -> None:
    """The whole transaction rolls back, and `dep_rows` is a participant in it."""
    deps = (Dep(kind="unit", key=OTHER, digest=SHA),)
    store = SqliteStore(thread, dep_rows=dep_rows(deps))
    claimed = store.claim(1, 7, "host:1:2.0", 60_000)
    assert store.complete(claimed[0].id, 8, result_of()) is False
    assert rows_of(owstore, "SELECT kind, key, digest FROM dep") == []


# =============================================================================================
# 4. The cohort writer
# =============================================================================================


def apply(path: Path, statements: Sequence[Statement]) -> None:
    connection = ow.connect(path)
    try:
        with connection:
            for statement in statements:
                connection.execute(statement.sql, dict(statement.params))
    finally:
        connection.close()


def test_the_parent_row_precedes_its_members() -> None:
    """`foreign_keys = ON` checks an immediate FK at the DML on the child row."""
    cohort = cohort_of("corpus", [(URI, "", SHA), (OTHER, "", OTHER_SHA)])
    plan = cohort_statements(
        cohort, [(URI, "", SHA), (OTHER, "", OTHER_SHA)], built_gen=1, built_ns=2
    )
    assert plan[0].name == "cohort_upsert"
    assert [s.name for s in plan[1:]] == ["cohort_member[0]", "cohort_member[1]"]


def test_the_members_written_are_the_members_digested() -> None:
    cohort = cohort_of("corpus", [(OTHER, "", OTHER_SHA), (URI, "", SHA)])
    plan = cohort_statements(
        cohort, [(OTHER, "", OTHER_SHA), (URI, "", SHA)], built_gen=1, built_ns=2
    )
    written = [s.params["unit_uri"] for s in plan[1:]]
    assert written == sorted({URI, OTHER})


def test_a_member_count_that_disagrees_with_the_rows_is_refused() -> None:
    cohort = cohort_of("corpus", [(URI, "", SHA), (OTHER, "", OTHER_SHA)])
    with pytest.raises(StoreError, match="declares 2 members"):
        cohort_statements(cohort, [(URI, "", SHA)], built_gen=1, built_ns=2)


def test_the_cohort_round_trips_into_the_store(owstore: Path) -> None:
    members = [(URI, "", SHA), (OTHER, "p1", OTHER_SHA)]
    cohort = cohort_of("corpus", members)
    apply(owstore, cohort_statements(cohort, members, built_gen=3, built_ns=NOW_NS))
    assert rows_of(owstore, "SELECT cohort_id, name, member_count FROM cohort") == [
        (cohort.cohort_id, "corpus", 2)
    ]
    assert rows_of(owstore, "SELECT unit_uri, unit_part FROM cohort_member ORDER BY unit_uri") == [
        (URI, ""),
        (OTHER, "p1"),
    ]


def test_writing_the_same_cohort_twice_changes_nothing(owstore: Path) -> None:
    """`DO NOTHING` / `INSERT OR IGNORE`: a cohort id IS its members."""
    members = [(URI, "", SHA)]
    cohort = cohort_of("corpus", members)
    plan = cohort_statements(cohort, members, built_gen=3, built_ns=NOW_NS)
    apply(owstore, plan)
    apply(owstore, cohort_statements(cohort, members, built_gen=9, built_ns=NOW_NS + 1))
    assert rows_of(owstore, "SELECT built_gen, built_ns FROM cohort") == [(3, NOW_NS)]
    assert len(rows_of(owstore, "SELECT * FROM cohort_member")) == 1


def test_the_member_statement_conflicts_on_a_real_unique_index() -> None:
    """*"`INSERT OR IGNORE` with no UNIQUE index to conflict on is a plain `INSERT`"* (08:428)."""
    assert "INSERT OR IGNORE" in COHORT_MEMBER_SQL
    assert "ON CONFLICT(cohort_id) DO NOTHING" in COHORT_UPSERT_SQL


def test_a_member_row_without_its_parent_is_refused_by_the_foreign_key(owstore: Path) -> None:
    connection = ow.connect(owstore)
    try:
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute(
                COHORT_MEMBER_SQL,
                {
                    "cohort_id": "coh_ffffffffffffffffffffffff",
                    "unit_uri": URI,
                    "unit_part": "",
                    "content_sha256": SHA,
                },
            )
    finally:
        connection.close()
