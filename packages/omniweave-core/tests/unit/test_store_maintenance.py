"""`store/maintenance.py` -- four operations, two verbs, `repair`'s four steps, bulk windows.

Specified by 07-store-and-retrieval.md section 2.2 (:201-229) and section 10.6 (:2847-2866). Every
test below serves one of six obligations:

1. **The five bounds are the plan's numbers**, asserted against `_plan/` rather than against a
   transcription of it, so an edit to either side is a failure.
2. **The inline `PRAGMA optimize` fallback is a STRICT SUBSET of the off-thread list** (07:209's
   "never the same list run inline"). Asserted as the relation, and asserted again by proving the
   constructor REFUSES a non-strict narrowing -- two literals that happen to differ would pass a
   weaker test and drift on the next edit.
3. **FTS `'optimize'` is unreachable from the maintenance window** (07:214-216). Asserted twice: by
   walking this module's own AST call graph, and by calling the guard.
4. **A bulk window drops only what 07:2848-2855 allows.** The UNIQUE indexes stay in
   `sqlite_master` and a duplicate insert still fails DURING the window -- which is the property
   07:2855 says dropping them would destroy.
5. **The marker is committed before the first DDL** (07:2858). Asserted by killing the process at
   the first DDL statement and reading the marker back on a fresh connection.
6. **`repair` is four steps in order and clears the marker last** (07:220-228).

# WHY `import sqlite3` IS HERE AT ALL

INV-17 bans it outside `omniweave_core/store/`, and every claim in this module is about what SQLite
actually does: that a `'merge'` command row costs exactly one `total_changes` when there is nothing
to merge, that `DROP INDEX` leaves the UNIQUE indexes in `sqlite_master`, that a marker written and
committed before a `DROP` survives a raise inside the DDL loop, that `VACUUM INTO` accepts a bound
parameter, and that `PRAGMA freelist_count` crosses a quarter of `page_count` after 3,000 deleted
8 KB rows. None of those is readable from source. The semgrep half of the ban scopes every rule to
`packages/*/src/**` and so already exempts a test; ruff's half carries no `per-file-ignores` row for
tests, so the `noqa` is the narrowest available form of the exemption -- one line, in one file, with
the reason attached. `tests/unit/test_migration_0001.py` is the house form this follows.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3  # noqa: TID251
from typing import TYPE_CHECKING, Any

import pytest
from conftest import migration_files
from omniweave_core.errors import StoreError
from omniweave_core.store import NO_JOB_DOCS
from omniweave_core.store import maintenance as m
from omniweave_core.store import sqlite as ow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from conftest import PlanDocs

STORE_DOC = "07-store-and-retrieval.md"

CREATE_PRAGMAS = ("page_size = 8192", "auto_vacuum = INCREMENTAL")
"""07:173 -- CREATE time only. `auto_vacuum` is what gives operation 3 anything to reclaim."""

CONN_PRAGMAS = ("busy_timeout = 5000", "foreign_keys = ON", "journal_mode = WAL")
"""The head of 07:168-171's list -- the three these tests actually depend on, in that order."""


def _open(path: Path) -> sqlite3.Connection:
    """A connection with the shipped migrations applied, in the order the prefixes fix."""
    fresh = not path.exists()
    conn = sqlite3.connect(path)
    if fresh:
        for pragma in CREATE_PRAGMAS:
            conn.execute(f"PRAGMA {pragma}")
    for pragma in CONN_PRAGMAS:
        conn.execute(f"PRAGMA {pragma}")
    if fresh:
        for migration in migration_files():
            conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO index_state(k, v) VALUES(?, ?)", (m.FTS_STATE_KEY, "ok"))
        conn.commit()
    return conn


@pytest.fixture
def store(tmp_path: Path) -> sqlite3.Connection:
    """A real `.owstore` in `tmp_path`, migrated, WAL, `auto_vacuum = INCREMENTAL`."""
    return _open(tmp_path / "index.owstore")


# ---------------------------------------------------------------------------
# Obligation 1 -- the five bounds are the plan's.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("literal", "value"),
    [
        ("`PRAGMA analysis_limit = 1000`", m.ANALYSIS_LIMIT),
        ("`MERGE_PAGES = 64`", m.MERGE_PAGES),
        ("`MERGE_STEPS = 16`", m.MERGE_STEPS),
        ("`FREE_PAGES_PER_STEP = 2048`", m.FREE_PAGES_PER_STEP),
        ("`freelist_count / page_count > 0.25`", m.FREELIST_RATIO_TRIGGER),
    ],
)
def test_every_bound_is_printed_in_the_plan_row_it_came_from(
    plan: PlanDocs, literal: str, value: object
) -> None:
    plan.require()
    text = plan.text(STORE_DOC)
    assert literal in text, f"{literal} is no longer in {STORE_DOC}"
    assert str(value) in literal, f"{value!r} is not the number {literal} prints"


def test_the_merge_statement_is_the_one_the_plan_prints(plan: PlanDocs) -> None:
    plan.require()
    printed = "INSERT INTO block_fts(block_fts, rank) VALUES('merge', MERGE_PAGES)"
    assert printed in plan.text(STORE_DOC)
    assert m.FTS_MERGE_TABLES == ("block_fts",), "07:210's statement names exactly one table"
    assert m.FTS_MERGE == "merge"


def test_the_four_operations_all_run_off_the_query_path(plan: PlanDocs) -> None:
    """07:203-205 -- the runtime owns the WINDOW; the statements and bounds are 07's."""
    plan.require()
    assert plan.grep(r"off the query path", documents=(STORE_DOC,)), "07:203's phrase is gone"
    assert plan.grep(r"owns the$", documents=(STORE_DOC,)), "07:204's 'the runtime owns' is gone"
    assert plan.grep(
        r"^window; the operations, their statements and their bounds are this document's\)",
        documents=(STORE_DOC,),
    ), "07:205's division of labour is gone"
    source = inspect.getsource(m)
    for scheduler in ("threading", "asyncio", "sched"):
        assert f"import {scheduler}" not in source, f"{scheduler} would make this module schedule"


# ---------------------------------------------------------------------------
# Obligation 2 -- the inline fallback is provably a strict subset.
# ---------------------------------------------------------------------------


def test_the_inline_optimize_fallback_is_a_strict_subset_of_the_off_thread_list() -> None:
    """07:209 -- "a strictly smaller inline fallback, never the same list run inline"."""
    off = m.OPTIMIZE_OFFTHREAD
    inline = m.OPTIMIZE_INLINE
    assert inline.optimizations < off.optimizations, "not a PROPER subset"
    assert inline.optimizations != off.optimizations
    assert inline.optimizations, "an empty fallback would not be a fallback"
    assert inline.analysis_limit < off.analysis_limit
    assert off.covers(inline)
    assert not inline.covers(off)
    assert inline.statements() != off.statements()


def test_the_off_thread_plan_emits_the_two_statements_the_plan_row_prints() -> None:
    assert m.OPTIMIZE_OFFTHREAD.statements() == (
        f"PRAGMA analysis_limit = {m.ANALYSIS_LIMIT}",
        "PRAGMA optimize",
    )


def test_narrowed_refuses_a_narrowing_that_is_not_strictly_smaller() -> None:
    """The relation is enforced at CONSTRUCTION, so editing a constant cannot break it silently."""
    off = m.OPTIMIZE_OFFTHREAD
    with pytest.raises(StoreError, match="strictly smaller"):
        off.narrowed(keep=off.optimizations, analysis_limit=off.analysis_limit)
    with pytest.raises(StoreError, match="strictly smaller"):
        off.narrowed(keep=off.optimizations | {1 << 20}, analysis_limit=off.analysis_limit)
    with pytest.raises(StoreError, match="strictly smaller"):
        off.narrowed(
            keep=frozenset({m.OPTIMIZE_ANALYZE_MAYBE_BENEFIT}),
            analysis_limit=off.analysis_limit + 1,
        )


def test_planner_statistics_issues_the_plan_it_reports(store: sqlite3.Connection) -> None:
    full = m.planner_statistics(store)
    assert full.plan is m.OPTIMIZE_OFFTHREAD
    assert full.statements == m.OPTIMIZE_OFFTHREAD.statements()
    fallback = m.planner_statistics(store, inline=True)
    assert fallback.plan is m.OPTIMIZE_INLINE
    assert fallback.inline is True
    assert set(fallback.plan.optimizations) < set(full.plan.optimizations)


# ---------------------------------------------------------------------------
# Obligation 3 -- FTS 'optimize' cannot be reached from the window.
# ---------------------------------------------------------------------------


def _call_graph() -> dict[str, set[str]]:
    """Every module-level function and method of `maintenance`, to the names it calls.

    Names, not objects: a call graph over an `ast` tree is what survives a module that has not been
    imported by the caller, and the question -- "can this function reach that one" -- is a property
    of the source, not of a live object.
    """
    tree = ast.parse(inspect.getsource(m))
    graph: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        called: set[str] = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                if isinstance(inner.func, ast.Name):
                    called.add(inner.func.id)
                elif isinstance(inner.func, ast.Attribute):
                    called.add(inner.func.attr)
        graph[node.name] = called
    return graph


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    """Every function name reachable from `start`, transitively."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        for callee in graph.get(name, ()):
            if callee not in seen:
                seen.add(callee)
                stack.append(callee)
    return seen


def test_fts_optimize_is_unreachable_from_the_maintenance_window() -> None:
    """07:214-216 -- "never in the maintenance window and never on an interactive path"."""
    graph = _call_graph()
    assert "_fts_optimize" in graph, "the guarded function was renamed; update this test"
    reach = _reachable(graph, "maintenance_window")
    assert "_fts_optimize" not in reach
    for operation in ("planner_statistics", "fts_merge", "reclaim_free_pages", "open_bulk_window"):
        assert "_fts_optimize" not in _reachable(graph, operation), operation


def test_compact_is_the_only_caller_of_the_fts_optimize_emitter() -> None:
    graph = _call_graph()
    callers = {name for name, calls in graph.items() if "_fts_optimize" in calls}
    assert callers == {"compact"}


def test_the_fts_optimize_literal_appears_in_exactly_one_function() -> None:
    """A second emitter would make the call-graph test above prove nothing."""
    tree = ast.parse(inspect.getsource(m))
    emitters = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and "VALUES('optimize')" in str(inner.value):
                emitters.add(node.name)
    assert emitters == {"_fts_optimize"}


def test_the_fts_command_guard_refuses_optimize_whatever_the_caller_passes(
    store: sqlite3.Connection,
) -> None:
    """The guard catches the case a call graph cannot: a command computed at runtime."""
    computed = "opti" + "mize"
    with pytest.raises(StoreError, match="O\\(index\\)"):
        m._fts_command(store, "block_fts", computed)
    with pytest.raises(StoreError, match="not an FTS5 table"):
        m._fts_command(store, "doc", m.FTS_MERGE, m.MERGE_PAGES)


# ---------------------------------------------------------------------------
# Operation 2 -- the merge, its bound, and its early exit.
# ---------------------------------------------------------------------------


def _fill_fts(conn: sqlite3.Connection, rows: int) -> None:
    """`rows` one-row commits into `block_fts` directly, with `automerge` off.

    Direct, not through `block`: the sync triggers need a whole `doc`/`block` graph and the property
    under test is FTS5's segment accounting, not the triggers'. `automerge = 0` is what makes the
    segments pile up so a `'merge'` step has real work -- the state 07:210 says an incrementally
    written index reaches on its own.
    """
    conn.execute("INSERT INTO block_fts(block_fts, rank) VALUES('automerge', 0)")
    conn.commit()
    for n in range(rows):
        conn.execute(
            "INSERT INTO block_fts(rowid, text) VALUES(?, ?)",
            (n + 1, f"alpha{n} beta{n % 7} gamma delta epsilon zeta eta theta"),
        )
        conn.commit()


def test_fts_merge_never_exceeds_merge_steps(store: sqlite3.Connection) -> None:
    _fill_fts(store, 400)
    report = m.fts_merge(store, steps=3)
    assert report.step_count <= 3
    assert set(report.steps) == {"block_fts"}
    assert report.pages == m.MERGE_PAGES


def test_fts_merge_stops_early_when_there_is_nothing_left_to_merge(
    store: sqlite3.Connection,
) -> None:
    """The early exit is the difference between a bounded window and a fixed 16-step cost."""
    _fill_fts(store, 400)
    first = m.fts_merge(store)
    assert first.step_count >= 1
    settled = m.fts_merge(store)
    assert settled.step_count == 1, "a fully merged index costs one probing step, not MERGE_STEPS"
    assert settled.exhausted is True


def test_fts_merge_reports_a_budget_it_ran_out_of(store: sqlite3.Connection) -> None:
    _fill_fts(store, 400)
    assert m.fts_merge(store, tables=("block_fts", "head_fts"), steps=1).exhausted is False


# ---------------------------------------------------------------------------
# Operation 3 -- the quarter-free trigger.
# ---------------------------------------------------------------------------


def test_incremental_vacuum_does_not_run_below_the_ratio(store: sqlite3.Connection) -> None:
    report = m.reclaim_free_pages(store)
    assert report.freelist_count == 0
    assert report.ratio == 0.0
    assert report.triggered is False
    assert report.pages_requested == 0


def test_incremental_vacuum_runs_only_above_a_quarter_free(store: sqlite3.Connection) -> None:
    """07:211 -- `freelist_count / page_count > 0.25`, strictly greater."""
    store.execute("CREATE TABLE t_free(x BLOB)")
    store.executemany("INSERT INTO t_free(x) VALUES(?)", [(b"a" * 7000,) for _ in range(3000)])
    store.commit()
    store.execute("DELETE FROM t_free")
    store.commit()
    pages = store.execute("PRAGMA page_count").fetchone()[0]
    free = store.execute("PRAGMA freelist_count").fetchone()[0]
    assert free / pages > m.FREELIST_RATIO_TRIGGER, "the fixture did not build a big freelist"
    report = m.reclaim_free_pages(store)
    assert report.triggered is True
    assert report.pages_requested == m.FREE_PAGES_PER_STEP
    assert report.freelist_after < report.freelist_count
    assert store.execute("PRAGMA page_count").fetchone()[0] < pages


class _FixedPragmas:
    """A connection proxy answering `page_count` and `freelist_count` with chosen numbers.

    The `>` of `freelist_count / page_count > 0.25` is only observable AT the boundary, and a real
    database cannot be driven to exactly a quarter free on demand. Everything else forwards, so the
    statement `reclaim_free_pages` issues is still the real one.
    """

    def __init__(self, conn: sqlite3.Connection, *, page_count: int, freelist: int) -> None:
        self._conn = conn
        self._answers = {"PRAGMA page_count": page_count, "PRAGMA freelist_count": freelist}
        self.statements: list[str] = []

    def execute(self, sql: str, *args: Any) -> Any:
        self.statements.append(sql)
        if sql in self._answers:
            return self._conn.execute("SELECT ?", (self._answers[sql],))
        return self._conn.execute(sql, *args)


@pytest.mark.parametrize(("freelist", "expected"), [(250, False), (251, True)])
def test_a_quarter_exactly_is_not_a_trigger(
    store: sqlite3.Connection, freelist: int, expected: bool
) -> None:
    """`> 0.25`, never `>= 0.25`: 250/1000 is exactly a quarter and must not run (07:211)."""
    proxy = _FixedPragmas(store, page_count=1000, freelist=freelist)
    report = m.reclaim_free_pages(proxy)  # type: ignore[arg-type]
    assert report.triggered is expected
    ran = any(s.startswith("PRAGMA incremental_vacuum") for s in proxy.statements)
    assert ran is expected


def test_the_ratio_is_strictly_greater_and_not_greater_or_equal() -> None:
    """A quarter exactly is NOT a trigger, which is the only observable half of `>` versus `>=`."""
    assert m.FREELIST_RATIO_TRIGGER == 0.25
    source = inspect.getsource(m.reclaim_free_pages)
    assert "ratio > FREELIST_RATIO_TRIGGER" in source
    assert ">=" not in source


def test_the_window_runs_the_three_operations_and_reports_the_fold(
    store: sqlite3.Connection,
) -> None:
    folds: list[int] = []
    report = m.maintenance_window(store, fold=lambda: folds.append(1))
    assert report.statistics.plan is m.OPTIMIZE_OFFTHREAD
    assert report.merge.step_count >= 1
    assert report.reclaim.triggered is False
    assert report.folded is True
    assert folds == [1]
    assert m.maintenance_window(store).folded is False


# ---------------------------------------------------------------------------
# The shipped schema, read by name.
# ---------------------------------------------------------------------------


def _is_fts_shadow(name: str) -> bool:
    """True for an FTS5 shadow table (`block_fts_data`, `head_fts_idx`, ...).

    FTS5 creates its shadow tables as ordinary `CREATE TABLE`s in `sqlite_master`, so they appear in
    a `type = 'table'` scan and appear in no migration. Excluding them by the `<fts table>_` prefix
    is derived from `fts_table_names()` and needs no list of suffixes: FTS5 owns that namespace, so
    a new suffix in a future SQLite is excluded too.
    """
    return any(name.startswith(f"{table}_") for table in m.fts_table_names())


def test_the_parser_agrees_with_sqlite_master_in_both_directions(
    store: sqlite3.Connection,
) -> None:
    """The proof that reading DDL out of `schema/` by name is not a guess about the SQL."""
    for kinds, sql_type in (
        (("index",), "index"),
        (("trigger",), "trigger"),
        (("view",), "view"),
        (("table", "virtual_table"), "table"),
    ):
        parsed = {n for n, o in m.shipped_schema().items() if o.kind in kinds}
        live = {
            str(row[0])
            for row in store.execute(
                "SELECT name FROM sqlite_master WHERE type = ? AND sql IS NOT NULL", (sql_type,)
            )
            if not str(row[0]).startswith("sqlite_")
            and not (sql_type == "table" and _is_fts_shadow(str(row[0])))
        }
        assert parsed == live, f"{sql_type}: {sorted(parsed ^ live)}"


def test_the_unique_and_secondary_index_sets_partition_the_indexes() -> None:
    unique = set(m.unique_index_names())
    secondary = set(m.secondary_index_names())
    assert unique & secondary == set()
    assert unique | secondary == set(m.index_names())
    assert unique and secondary


def test_unique_is_read_off_the_ddl_and_not_off_the_name() -> None:
    """A rename cannot move an index between the two sets, which is what 07:2854 depends on."""
    for name in m.unique_index_names():
        assert m.shipped_schema()[name].sql.upper().startswith("CREATE UNIQUE INDEX")
    for name in m.secondary_index_names():
        assert not m.shipped_schema()[name].sql.upper().startswith("CREATE UNIQUE INDEX")


def test_the_fts_triggers_are_the_nine_that_write_an_fts_table_and_no_others() -> None:
    """`work_no_live_delete` and `route_decision_monotone` are triggers and are never dropped."""
    assert m.fts_table_names() == ("block_fts", "block_tri", "head_fts")
    triggers = set(m.fts_trigger_names())
    assert len(triggers) == 9
    assert "work_no_live_delete" not in triggers
    assert "route_decision_monotone" not in triggers
    for table in m.fts_table_names():
        assert {f"{table}_ai", f"{table}_ad", f"{table}_au"} <= triggers


def test_object_ddl_raises_hard_on_a_missing_name() -> None:
    """07:2850 -- "read from `schema/` by name, with a hard raise on a miss"."""
    with pytest.raises(StoreError, match="no DDL for"):
        m.object_ddl("index_that_never_existed")
    with pytest.raises(StoreError, match="subtly different"):
        m.index_ddl("index_that_never_existed")


def test_index_ddl_refuses_to_recreate_a_trigger_as_an_index() -> None:
    with pytest.raises(StoreError, match="is a trigger"):
        m.index_ddl("block_fts_ai")


# ---------------------------------------------------------------------------
# Bulk windows. 07 section 10.6.
# ---------------------------------------------------------------------------


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
        )
    }


def _triggers(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }


def test_a_bulk_window_drops_the_non_unique_secondary_indexes_and_the_fts_triggers(
    store: sqlite3.Connection,
) -> None:
    window = m.open_bulk_window(store, now_ns=1, owner="test")
    assert set(window.dropped_indexes) == set(m.secondary_index_names())
    assert set(window.dropped_triggers) == set(m.fts_trigger_names())
    assert _indexes(store) & set(m.secondary_index_names()) == set()
    assert _triggers(store) & set(m.fts_trigger_names()) == set()


def test_a_bulk_window_leaves_every_unique_index_in_sqlite_master(
    store: sqlite3.Connection,
) -> None:
    """07:2854-2855 -- the UNIQUE identity index is never dropped."""
    m.open_bulk_window(store, now_ns=1, owner="test")
    assert set(m.unique_index_names()) <= _indexes(store)


def test_a_bulk_window_leaves_the_non_fts_triggers_in_place(store: sqlite3.Connection) -> None:
    m.open_bulk_window(store, now_ns=1, owner="test")
    assert {"work_no_live_delete", "route_decision_monotone"} <= _triggers(store)


def test_a_duplicate_insert_still_fails_during_a_bulk_window(store: sqlite3.Connection) -> None:
    """This is the property 07:2855 says dropping the UNIQUE index would destroy."""
    m.open_bulk_window(store, now_ns=1, owner="test")
    columns = "(k, v, computed_ns)"
    store.execute(f"INSERT INTO stat {columns} VALUES('live_blocks', 1, 1)")
    store.execute("INSERT INTO index_state(k, v) VALUES('corpus_id', 'c')")
    store.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store.execute("INSERT INTO index_state(k, v) VALUES('corpus_id', 'other')")
    store.rollback()
    producer = (
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    store.execute(producer)
    store.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store.execute(producer)
    store.rollback()
    assert "producer_identity" in _indexes(store)


def test_the_marker_and_the_pessimistic_fts_state_are_written_before_the_window(
    store: sqlite3.Connection,
) -> None:
    window = m.open_bulk_window(store, now_ns=1_700_000_000_000_000_000, owner="ow ingest")
    assert m.bulk_window_marker(store) == window.marker
    assert "owner=ow ingest" in window.marker
    assert m._get_index_state(store, m.FTS_STATE_KEY) == m.FTS_STATE_BUILDING


class _KilledError(Exception):
    """Stands in for the SIGKILL 07:2860 says a bulk-window test must assert against."""


class _KillOnFirstDdl:
    """A connection proxy that raises on the first DDL statement, and forwards everything else.

    This is how "the marker is written **before the first DDL**" (07:2858) is asserted rather than
    assumed: if the marker were written in the same uncommitted transaction as the first
    `DROP INDEX`, it would vanish with the raise and a fresh connection would see a clean store --
    which is the crash ST13 exists to make visible.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.ddl_attempts = 0

    def execute(self, sql: str, *args: Any) -> Any:
        if sql.lstrip().upper().startswith(("DROP ", "CREATE ")):
            self.ddl_attempts += 1
            raise _KilledError(sql)
        return self._conn.execute(sql, *args)

    def commit(self) -> None:
        self._conn.commit()

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction


def test_the_marker_survives_a_kill_at_the_very_first_ddl_statement(tmp_path: Path) -> None:
    path = tmp_path / "index.owstore"
    conn = _open(path)
    proxy = _KillOnFirstDdl(conn)
    with pytest.raises(_KilledError):
        m.open_bulk_window(proxy, now_ns=42, owner="killed")  # type: ignore[arg-type]
    assert proxy.ddl_attempts == 1
    conn.close()

    reopened = _open(path)
    assert m.bulk_window_marker(reopened) is not None
    assert m._get_index_state(reopened, m.FTS_STATE_KEY) == m.FTS_STATE_BUILDING
    with pytest.raises(StoreError) as raised:
        m.refuse_if_bulk_window_open(reopened)
    assert "OW-S-031" in str(raised.value)
    assert raised.value.fix == "ow store repair"
    assert raised.value.code() == m.BULK_WINDOW_OPEN_SYMBOL
    reopened.close()


def test_a_clean_store_is_not_refused(store: sqlite3.Connection) -> None:
    assert m.bulk_window_marker(store) is None
    m.refuse_if_bulk_window_open(store)


def test_close_bulk_window_restores_every_dropped_object_and_clears_the_marker(
    store: sqlite3.Connection,
) -> None:
    before_index, before_trigger = _indexes(store), _triggers(store)
    window = m.open_bulk_window(store, now_ns=1, owner="test")
    steps: list[str] = []
    m.close_bulk_window(store, window, on_step=steps.append)
    assert _indexes(store) == before_index
    assert _triggers(store) == before_trigger
    assert m.bulk_window_marker(store) is None
    assert m._get_index_state(store, m.FTS_STATE_KEY) == m.FTS_STATE_OK
    assert set(steps) >= set(window.dropped_indexes)


def test_a_bulk_window_scoped_to_one_table_drops_only_that_table_s_indexes(
    store: sqlite3.Connection,
) -> None:
    window = m.open_bulk_window(store, now_ns=1, owner="test", tables=("rel",))
    assert set(window.dropped_indexes) == {"rel_dst", "rel_src"}
    assert window.dropped_triggers == ()
    assert window.fts_tables == ()
    assert m._get_index_state(store, m.FTS_STATE_KEY) == m.FTS_STATE_OK
    m.close_bulk_window(store, window)
    assert {"rel_dst", "rel_src"} <= _indexes(store)


def test_on_step_is_called_at_the_top_of_each_body(store: sqlite3.Connection) -> None:
    """07:2861 -- the runtime's yield and watchdog heartbeat hang here."""
    seen: list[str] = []
    window = m.open_bulk_window(store, now_ns=1, owner="test", on_step=seen.append)
    assert seen == [*window.dropped_indexes, *window.dropped_triggers]


# ---------------------------------------------------------------------------
# `ow store backup` and `ow store compact`.
# ---------------------------------------------------------------------------


def test_backup_is_vacuum_into_and_produces_a_readable_database(
    store: sqlite3.Connection, tmp_path: Path
) -> None:
    dest = tmp_path / "backup.owstore"
    report = m.backup(store, dest)
    assert report.path == str(dest)
    assert report.byte_len > 0
    assert dest.is_file()
    copy = sqlite3.connect(dest)
    try:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert set(m.index_names()) <= {
            str(row[0])
            for row in copy.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            )
        }
    finally:
        copy.close()


def test_backup_does_not_leave_a_wal_the_destination_needs(
    store: sqlite3.Connection, tmp_path: Path
) -> None:
    """07:216-217 -- "atomic, no torn WAL". `VACUUM INTO` writes a complete database."""
    dest = tmp_path / "backup.owstore"
    m.backup(store, dest)
    assert not (tmp_path / "backup.owstore-wal").exists()


def test_compact_vacuums_optimizes_every_fts_table_and_integrity_checks(
    store: sqlite3.Connection,
) -> None:
    _fill_fts(store, 200)
    report = m.compact(store)
    assert report.fts_optimized == m.fts_table_names()
    assert report.integrity == ("ok",)
    assert report.intact is True
    assert report.page_count_after > 0


def test_compact_refuses_a_table_that_is_not_an_fts_table(store: sqlite3.Connection) -> None:
    with pytest.raises(StoreError, match="not an FTS5 table"):
        m.compact(store, tables=("doc",))


@pytest.mark.parametrize("verb", ["backup", "compact", "repair", "open_bulk_window"])
def test_a_maintenance_verb_refuses_an_open_transaction(
    store: sqlite3.Connection, tmp_path: Path, verb: str
) -> None:
    """A verb that commits the caller's transaction commits work the caller had not finished."""
    store.execute("INSERT INTO index_state(k, v) VALUES('corpus_id', 'c')")
    assert store.in_transaction
    calls = {
        "backup": lambda: m.backup(store, tmp_path / "b.owstore"),
        "compact": lambda: m.compact(store),
        "repair": lambda: m.repair(store, now_ns=1),
        "open_bulk_window": lambda: m.open_bulk_window(store, now_ns=1, owner="t"),
    }
    with pytest.raises(StoreError, match="no open transaction"):
        calls[verb]()


# ---------------------------------------------------------------------------
# `ow store repair` -- four steps, in order.
# ---------------------------------------------------------------------------


def test_repair_runs_exactly_four_steps_in_order_and_clears_the_marker_last(
    store: sqlite3.Connection,
) -> None:
    """07:220-228 -- "exactly four steps, in order" and "only then" is the marker cleared."""
    report = m.repair(store, now_ns=99)
    assert report.steps == (
        "recreate_indexes",
        "rebuild_fts",
        "checks",
        "rederive_stat",
        "clear_bulk_window",
    )
    assert report.steps[-1] == "clear_bulk_window"
    assert report.integrity == ("ok",)
    assert report.foreign_key_violations == 0
    assert report.stat_written == {"live_blocks": 0, "live_segments": 0, "docs": 0}
    assert store.execute("SELECT computed_ns FROM stat WHERE k = 'live_blocks'").fetchone() == (99,)


def test_repair_recreates_a_missing_index_from_the_shipped_ddl(
    store: sqlite3.Connection,
) -> None:
    store.execute("DROP INDEX block_kind")
    store.commit()
    assert "block_kind" not in _indexes(store)
    report = m.repair(store, now_ns=1)
    assert report.recreated_indexes == ("block_kind",)
    assert "block_kind" in _indexes(store)
    live = store.execute("SELECT sql FROM sqlite_master WHERE name = 'block_kind'").fetchone()[0]
    assert live == m.index_ddl("block_kind")


def test_repair_raises_hard_when_a_named_index_has_no_shipped_ddl(
    store: sqlite3.Connection,
) -> None:
    """07:221's "hard raise on a miss", reachable because `names` is the register's seam."""
    with pytest.raises(StoreError, match="no DDL for"):
        m.repair(store, now_ns=1, names=("index_the_register_invented",))


def test_repair_closes_the_bulk_window_a_killed_process_left_open(
    store: sqlite3.Connection,
) -> None:
    window = m.open_bulk_window(store, now_ns=1, owner="killed")
    assert m.bulk_window_marker(store) is not None
    report = m.repair(store, now_ns=2)
    assert report.bulk_window_cleared is True
    assert set(window.dropped_indexes) <= _indexes(store)
    assert report.fts_rebuilt == m.fts_table_names()
    assert m.bulk_window_marker(store) is None
    m.refuse_if_bulk_window_open(store)


def test_repair_does_not_rebuild_an_fts_index_already_marked_ok(
    store: sqlite3.Connection,
) -> None:
    """`'rebuild'` is O(index); `fts_state` says whether it is needed at all (07:424-431)."""
    assert m._get_index_state(store, m.FTS_STATE_KEY) == m.FTS_STATE_OK
    assert m.repair(store, now_ns=1).fts_rebuilt == ()


class _ForeignKeyViolation:
    """A connection proxy whose `foreign_key_check` reports one row and which forwards the rest.

    A synthetic violation and not a real one, deliberately: every foreign key in the shipped schema
    is `ON DELETE CASCADE` on a NOT NULL column, so producing a real orphan means writing rows with
    `foreign_keys = OFF` and then asserting against the shape of somebody else's table. What is
    under test is `repair`'s DISPOSITION -- stop at step 3, never run step 4, never clear the marker
    -- and the disposition is the same whichever row `foreign_key_check` returns.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.statements: list[str] = []

    def execute(self, sql: str, *args: Any) -> Any:
        self.statements.append(sql)
        if sql == "PRAGMA foreign_key_check":
            return self._conn.execute("SELECT 'block', 1, 'doc', 0")
        return self._conn.execute(sql, *args)

    def commit(self) -> None:
        self._conn.commit()

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction


def test_repair_stops_at_step_three_and_leaves_the_marker_open(
    store: sqlite3.Connection,
) -> None:
    m.open_bulk_window(store, now_ns=1, owner="killed")
    proxy = _ForeignKeyViolation(store)
    with pytest.raises(StoreError, match="stopped at step 3"):
        m.repair(proxy, now_ns=2)  # type: ignore[arg-type]
    assert not any(s.startswith("INSERT INTO stat") for s in proxy.statements)
    assert m.bulk_window_marker(store) is not None
    with pytest.raises(StoreError, match="OW-S-031"):
        m.refuse_if_bulk_window_open(store)


def test_the_stat_keys_repair_cannot_write_are_named_with_their_reason() -> None:
    """DEFECT 4 is closed and `per_kind` is not: one key left, for a different reason.

    W6.8 gave `NO_JOB_DOCS` its home in `omniweave_core.store`, so `docs` moved from the deferred
    map to `_STAT_SQL`. `per_kind` stays deferred because nothing in the plan fixes its key
    spelling, which no home for a predicate can fix.
    """
    assert set(m._STAT_DEFERRED) == {"per_kind"}
    assert "key spelling" in m._STAT_DEFERRED["per_kind"]
    assert set(m._STAT_SQL) == {"live_blocks", "live_segments", "docs"}
    assert set(m._STAT_SQL) & set(m._STAT_DEFERRED) == set()


def test_docs_counts_through_the_one_no_job_docs_home() -> None:
    """07:761 -- a job document *"would inflate the corpus size an operator reads"*.

    Asserted against the shared constant and not against a copy of the predicate: the whole point
    of the home is that this statement and `corpus_card`'s are the same six characters.
    """
    assert NO_JOB_DOCS in m._STAT_SQL["docs"]


def test_live_is_read_off_the_head_views_and_not_re_derived() -> None:
    """`gen = doc.gen AND state = 0` has one home, and it is the view (`0001_init.sql:328`)."""
    for key in ("live_blocks", "live_segments"):
        assert "_head" in m._STAT_SQL[key]
        assert "state" not in m._STAT_SQL[key]


def test_rederive_stat_is_one_home_and_repair_step_four_is_a_caller(
    store: sqlite3.Connection,
) -> None:
    """W4.6 extracted step 4 so `op.converge` and `repair()` share it rather than transcribe it.

    07:721 gives `stat` two writers -- *"(`op.converge`) and by `ow index stats`"* -- and `repair()`
    is the third in practice. Three transcriptions of `live_blocks` would be three definitions of
    "live", which is exactly what `_STAT_SQL`'s docstring says the head views exist to prevent.
    """
    written = m.rederive_stat(store, now_ns=1_700_000_000_000_000_000)
    assert set(written) == set(m._STAT_SQL)
    # It does not commit: the caller owns the transaction, which is how `op.converge` gets the
    # re-derivation into the same commit as the work transitions it just made.
    assert store.in_transaction
    store.commit()
    report = m.repair(store, now_ns=1_700_000_000_000_000_001)
    assert set(report.stat_written) == set(written)
    assert report.stat_written == written


def test_the_stat_upsert_is_the_ddls_three_columns() -> None:
    assert "INSERT INTO stat(k, v, computed_ns)" in m.STAT_UPSERT_SQL
    assert "ON CONFLICT(k) DO UPDATE" in m.STAT_UPSERT_SQL


def test_the_thread_level_helper_runs_one_free_unit(tmp_path: Path) -> None:
    """`op.converge` holds a `StoreThread` and cannot name a `Connection`: G8 bans the import."""
    path = tmp_path / "threaded.owstore"
    _open(path).close()
    seen: list[ow.Unit] = []
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        real = thread.run

        def spy(unit: ow.Unit) -> object:
            seen.append(unit)
            return real(unit)

        thread.run = spy  # type: ignore[method-assign]
        written = m.rederive_stat_on(thread, now_ns=1_700_000_000_000_000_000)
    assert set(written) == set(m._STAT_SQL)
    assert [unit.name for unit in seen] == ["maintenance.rederive_stat"]
    assert seen[0].cost_class == "free"
