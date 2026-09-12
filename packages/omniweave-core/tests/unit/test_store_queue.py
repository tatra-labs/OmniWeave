"""The queue boundary, against a real `.owstore` built by the shipped migrations.

`store/queue.py` is four methods and one transaction, and almost everything that can be wrong with
it is invisible to a test that calls the methods in sequence on one thread. Four properties are the
reason this file exists rather than being a coverage exercise, and each one has a test that fails if
the property is removed:

1. **Two claimers never get the same row.** Asserted with two real `StoreThread`s over two
   connections to one file, not with two sequential calls. A claim that read its candidate set in
   one statement and wrote the lease in another would pass a sequential test and lose rows here.
2. **`complete()` is atomic across every participant it has.** A later participant is made to fail
   and *nothing* is asserted to have landed -- not the `work` transition, not the row an earlier
   participant wrote. A test that only asserted the exception would pass against a store that
   committed the first half.
3. **`False` means superseded and nothing else.** Both halves: a superseded completion returns
   `False`, and three distinct refusals raise. A boolean that meant both *"someone else won"* and
   *"your driver is wrong"* would turn a bug into a no-op (08-runtime.md:2489-2494).
4. **ST14 is asserted AT COMMIT TIME.** 07:2737 asks for the pragma value at commit, not for the
   `cost_class` that was passed in, so the assertion runs inside `Unit.on_commit` with the
   transaction still open.

Everything else here is a transcription check: `WORK_COLUMNS`, `WORK_STATUSES`, `DEP_KINDS` and the
transition table are read back out of the shipped DDL and out of `_plan/`, so a hand-typed constant
cannot drift from the schema it claims to mirror.

Specified in 07-store-and-retrieval.md sections 1.1 and 10.1-10.2, 08-runtime.md sections 1.2, 1.6
and 9.2, and charter.md:4020-4118.
"""

from __future__ import annotations

import inspect
import re
import sqlite3  # noqa: TID251 -- see below.
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from conftest import PlanDocs
from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.limits import MAX_DEPS_PER_UNIT
from omniweave_core.operator import (
    CACHE_KEY_HEX_LEN,
    OperatorIdentity,
    Outcome,
    StepMetrics,
    StepResult,
)
from omniweave_core.store import Store as StoreProtocol
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.queue import (
    COMPLETE_PARTICIPANTS,
    DEP_KINDS,
    SqliteStore,
    Statement,
    complete_boundaries,
    dep_statements,
)

# The work vocabulary moved to `omniweave_core.work` with P4 W4.1 (02-architecture.md:246), so the
# queue's own tests now reach for it there. That is the point of the move rather than a cost of it:
# an import line is where a reader learns which module owns a name.
from omniweave_core.work import (
    CLAIM_SQL,
    COMPLETE_SQL,
    COUNTS_SQL,
    DECREMENTING,
    MAX_WORK_ATTEMPTS,
    OUTCOMES,
    TRANSITIONS,
    WORK_COLUMNS,
    WORK_STATUSES,
    WorkRow,
)
from omniweave_ports.types import UnitRef

# `import sqlite3` is banned outside `omniweave_core/store/` by ruff's TID251 (INV-17), and this
# file takes the escape deliberately. It drives a REAL store: the seeding below writes `unit`,
# `route_evidence`, `route_decision`, `work`, `run` and `budget_reservation` rows through an
# `ow.connect()` connection, and two of the assertions are about which `sqlite3` exception class a
# broken participant raises. Neither can be expressed through the store boundary, which is the
# thing under test. No `sqlite3.connect` appears here -- every connection comes from
# `omniweave_core.store.sqlite`, so ST1 holds.

NOW_NS = 1_757_400_000_000_000_000
"""A fixed wall clock, as in `test_store_integration.py`: the store injects every clock it uses."""

CACHE_KEY = "a" * CACHE_KEY_HEX_LEN

UNIT = UnitRef(uri="file:///corpus/a.pdf", part="p0", content_sha256="a0", byte_len=11)
"""`StepResult.unit`. The store never reads it -- `StepResultView` names six attributes and this is
not one -- so it is a fixed value rather than a per-test one; what it proves is that these tests
build the same class `omniweave/run/` will."""

IDENTITY = OperatorIdentity(operator="parse.pdf", op_version=1, code_fingerprint="test")
"""`StepResult.identity`, which **is** `Producer` (08:1930). Also unread by the `work` transition:
`producer_id` is the derived rows' FK and those have no P2 producer."""
WORKER = "host:4321:1757400000.5"
"""`'<host>:<pid>:<process_create_time>'` -- 0004_runtime.sql:110's shape, recorded not parsed."""

FAR_FUTURE_MS = 1 << 62
"""Past any `lease_expires` this suite mints, so a reap sweeps everything that is claimed."""


# ---------------------------------------------------------------------------------------------
# Seeding a queue
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Queued:
    """One `work` row to seed, with the columns this suite varies and the DDL's defaults elsewhere.

    `operator` starting `op.` forces `decision_id`, `driver` and `dispatch_key` to NULL together --
    0004_runtime.sql:118-124's three CHECKs make the triple structural, so an `op.*` row is the only
    way to seed a NULL `dispatch_key` and the "a NULL batches alone" test has no other shape.
    """

    part: str
    operator: str = "parse.pdf"
    dispatch_key: str = "dk1"
    cost_class: str = "free"
    priority: int = 0
    status: str = "pending"
    attempts_total: int = 0
    attempts_today: int = 0
    retry_after: int | None = None


_UNIT_SQL = (
    "INSERT OR IGNORE INTO unit(unit_uri, state, trust_class, last_seen_gen) "
    "VALUES(:uri, 'planned', 'internal', 1)"
)

_EVIDENCE_SQL = (
    "INSERT OR IGNORE INTO route_evidence(evidence_digest, payload, first_seen_at) "
    "VALUES('ev', X'00', 1)"
)

_DECISION_SQL = """
INSERT INTO route_decision(
  decision_id, content_sha256, unit_part, lane, rung,
  policy_digest, pricebook_digest, hints_digest, read_set_digest,
  driver, cost_class, rule_id, rule_origin, slice_key,
  evidence_digest, est_spend, est_micros, reserved_micros,
  admission, generation, decided_at)
VALUES(:decision_id, 'c0', :unit_part, 'parse', 1,
  'pd', 'pb', 'hd', 'rd',
  'drv', :cost_class, 'r1', 'test:1', 'sk',
  'ev', '{}', 0, 0, 'admitted', 1, 1)
"""

_WORK_SQL = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key,
                 decision_id, driver, cost_class, dispatch_key, status,
                 priority, attempts_total, attempts_today, retry_after)
VALUES(:uri, :part, :operator, 1, 'seed',
       :decision_id, :driver, :cost_class, :dispatch_key, :status,
       :priority, :attempts_total, :attempts_today, :retry_after)
"""

URI = "file:///corpus/a"


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    """A real `.owstore` with all four migrations applied, closed and ready to be re-opened."""
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
    finally:
        connection.close()
    return path


def seed(path: Path, rows: Sequence[Queued]) -> tuple[int, ...]:
    """Write the `unit`, `route_decision` and `work` rows, returning the `work.id`s in order."""
    connection = ow.connect(path)
    try:
        connection.execute(_UNIT_SQL, {"uri": URI})
        connection.execute(_EVIDENCE_SQL)
        ids: list[int] = []
        for row in rows:
            is_core_only = row.operator.startswith("op.")
            decision_id = None if is_core_only else f"dec_{row.part}"
            if decision_id is not None:
                connection.execute(
                    _DECISION_SQL,
                    {
                        "decision_id": decision_id,
                        "unit_part": row.part,
                        "cost_class": row.cost_class,
                    },
                )
            cursor = connection.execute(
                _WORK_SQL,
                {
                    "uri": URI,
                    "part": row.part,
                    "operator": row.operator,
                    "decision_id": decision_id,
                    "driver": None if is_core_only else "drv",
                    "cost_class": row.cost_class,
                    "dispatch_key": None if is_core_only else row.dispatch_key,
                    "status": row.status,
                    "priority": row.priority,
                    "attempts_total": row.attempts_total,
                    "attempts_today": row.attempts_today,
                    "retry_after": row.retry_after,
                },
            )
            ids.append(int(cursor.lastrowid or 0))
        return tuple(ids)
    finally:
        connection.close()


def read_work(path: Path, row_id: int) -> dict[str, object]:
    """One `work` row as a column -> value mapping, read outside the store under test."""
    connection = ow.connect(path)
    try:
        row = connection.execute(
            f"SELECT {', '.join(WORK_COLUMNS)} FROM work WHERE id = ?",  # noqa: S608 -- a
            # constant column list from this module, and the id is bound.
            (row_id,),
        ).fetchone()
        assert row is not None, f"work row {row_id} vanished"
        return dict(zip(WORK_COLUMNS, row, strict=True))
    finally:
        connection.close()


def scalar(path: Path, sql: str, params: Sequence[object] = ()) -> object:
    """One scalar, read outside the store under test."""
    connection = ow.connect(path)
    try:
        row = connection.execute(sql, tuple(params)).fetchone()
        return None if row is None else row[0]
    finally:
        connection.close()


@pytest.fixture
def opened(owstore: Path) -> Iterator[tuple[SqliteStore, ow.StoreThread]]:
    """A `SqliteStore` over its own `StoreThread`, closed on the way out."""
    thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield SqliteStore(thread), thread
    finally:
        thread.close()


def result(outcome: str = "ok", **kwargs: object) -> StepResult:
    """A `StepResult` carrying whatever each outcome's `__post_init__` demands.

    `outcome` stays a `str` here and is coerced on the way in. The type moved to
    `omniweave_core.operator` with P4, and its field is now an `Outcome`; every call site in this
    file passes the wire value, which is what `work.TRANSITIONS` is keyed by and what the column
    stores, so coercing once here keeps those call sites reading like the table they check.
    """
    required: dict[str, object] = {"cache_key": CACHE_KEY, "unit": UNIT, "identity": IDENTITY}
    if outcome == "ok_partial":
        required["partial_reason"] = "page 3 of 4"
    if outcome == "failed_transient":
        required["retry_after_ms"] = 300_000
        required["failure_class"] = "upstream_unavailable"
    if outcome == "failed_permanent":
        required["failure_class"] = "corrupt_input"
    if outcome == "deferred_budget":
        required["deferred_dim"] = "micros"
    required.update(kwargs)
    return StepResult(outcome=Outcome(outcome), **required)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# The transcriptions -- read back out of the shipped DDL, never compared to a copy of themselves
# ---------------------------------------------------------------------------------------------


def ddl(path: Path, name: str) -> str:
    """The `CREATE TABLE` text SQLite itself stored, with `--` comments stripped.

    Comments are stripped because two phantom table names have already been produced on this
    project by greps that matched prose inside `--` comments. A CHECK domain is read off the
    statement or it is not read at all.
    """
    text = str(scalar(path, "SELECT sql FROM sqlite_master WHERE name = ?", (name,)))
    return "\n".join(line.split("--")[0] for line in text.splitlines())


def test_work_columns_are_exactly_the_columns_the_shipped_ddl_declares(owstore: Path) -> None:
    """`WORK_COLUMNS` is `work`'s column list in DDL order, and `WorkRow`'s fields match it.

    This is the test that makes `RETURNING <named columns>` safe. `RETURNING *` would put the order
    in `sqlite_master`'s hands; naming them puts it in `WORK_COLUMNS`' hands, and a migration that
    adds a column to `work` has to fail somewhere. Here.
    """
    connection = ow.connect(owstore)
    try:
        declared = tuple(row[1] for row in connection.execute("PRAGMA table_info(work)"))
    finally:
        connection.close()
    assert declared == WORK_COLUMNS
    assert tuple(field.name for field in WorkRow.__dataclass_fields__.values()) == WORK_COLUMNS


def test_work_statuses_are_exactly_the_status_check_domain(owstore: Path) -> None:
    """The six, read off `work`'s own CHECK rather than out of the plan's prose."""
    text = ddl(owstore, "work")
    match = re.search(r"status\s+TEXT NOT NULL CHECK \(status IN \(([^)]*)\)\)", text, re.S)
    assert match is not None, "work.status's CHECK moved; WORK_STATUSES cannot be verified"
    assert tuple(re.findall(r"'([a-z_]+)'", match.group(1))) == WORK_STATUSES


def test_dep_kinds_are_exactly_the_dep_check_domain(owstore: Path) -> None:
    """The six `dep.kind` values, read off `dep`'s own CHECK."""
    text = ddl(owstore, "dep")
    match = re.search(r"kind\s+TEXT NOT NULL CHECK \(kind IN \(([^)]*)\)\)", text, re.S)
    assert match is not None, "dep.kind's CHECK moved; DEP_KINDS cannot be verified"
    assert tuple(re.findall(r"'([a-z_]+)'", match.group(1))) == DEP_KINDS


def test_the_transition_table_carries_one_row_per_outcome_and_no_other() -> None:
    """Eight outcomes, eight rows, same order -- 08:179-183 makes the count a rejectable PR."""
    assert len(OUTCOMES) == 8
    assert tuple(TRANSITIONS) == OUTCOMES
    assert all(TRANSITIONS[outcome].outcome == outcome for outcome in OUTCOMES)
    assert {t.status for t in TRANSITIONS.values()} <= set(WORK_STATUSES)


def test_the_two_decrementing_outcomes_reach_the_sql_as_the_plan_prints_them() -> None:
    """`DECREMENTING` is derived from the table, and `COMPLETE_SQL` is built from `DECREMENTING`.

    08:116-119 prints `:outcome IN ('deferred_budget','cancelled')`. The point of deriving the
    IN-list rather than typing it is that a change to a `Transition` row's `decrements_attempts`
    cell reaches the statement; this asserts both that the derivation is right today and that the
    statement is what carries it.
    """
    assert DECREMENTING == ("deferred_budget", "cancelled")
    assert COMPLETE_SQL.count("IN ('deferred_budget','cancelled')") == 2


def test_max_work_attempts_is_the_number_the_charter_prints(plan: PlanDocs) -> None:
    """`attempts_total < 5` appears in the charter's claim SQL; the constant must be that 5.

    Guards the required edit reported against `limits.py`: when `MAX_WORK_ATTEMPTS` moves there,
    this test still holds it to the plan's literal.
    """
    plan.require()
    charter = plan.text("_notes/charter.md")
    assert f"attempts_total < {MAX_WORK_ATTEMPTS}" in charter
    assert f"attempts_total < {MAX_WORK_ATTEMPTS}" in CLAIM_SQL


def test_the_store_satisfies_the_frozen_four_method_protocol() -> None:
    """The four names, and `claim`/`complete` in the NARROW form 07:56-60 prints.

    `store/__init__.py` records the ruling; this asserts the implementation took the same side.
    A drift toward 08:2478-2485's wider pair shows up here as a parameter-name mismatch.
    """
    for name in ("claim", "complete", "reap_expired_leases", "counts_by_status"):
        declared = inspect.signature(getattr(StoreProtocol, name))
        implemented = inspect.signature(getattr(SqliteStore, name))
        assert list(declared.parameters) == list(implemented.parameters), name
    assert list(inspect.signature(SqliteStore.claim).parameters) == [
        "self",
        "batch",
        "gen",
        "worker",
        "lease_ms",
    ]
    assert list(inspect.signature(SqliteStore.complete).parameters) == [
        "self",
        "row_id",
        "gen",
        "result",
    ]


# ---------------------------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------------------------


def test_a_claim_writes_the_lease_the_worker_and_the_generation_in_one_statement(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """*"THE CLAIM IS THE LEASE"* (charter.md:4105, I23) -- all four columns or none of them."""
    store, _ = opened
    (row_id,) = seed(owstore, [Queued(part="p0")])
    (claimed,) = store.claim(batch=8, gen=7, worker=WORKER, lease_ms=60_000)

    assert claimed.id == row_id
    assert claimed.status == "claimed"
    assert claimed.claimed_by == WORKER
    assert claimed.claimed_gen == 7
    assert isinstance(claimed.lease_expires, int), (
        "work is STRICT: unixepoch('subsec')*1000 is a REAL and must be CAST -- STORE_NOW_MS"
    )
    assert claimed.lease_expires > 0
    assert claimed.attempts_total == 1, "the claim increments unconditionally (08:105-107)"
    assert claimed.attempts_today == 1, "recomputed from date(last_attempt_at) (08:595-597)"
    assert isinstance(claimed.last_attempt_at, int)
    assert read_work(owstore, row_id)["status"] == "claimed"


def test_two_concurrent_claimers_never_receive_the_same_row(owstore: Path) -> None:
    """The test that matters. Two `StoreThread`s, two connections, one file, one queue.

    Sequential claims cannot see this bug: a claim that selected its candidates in one statement
    and wrote the lease in another gives identical answers when nobody else is running. Two real
    threads against two real connections do not.

    The union assertion is as load-bearing as the disjointness one. A claim that deadlocked, or
    that silently returned nothing under contention, would satisfy "disjoint" perfectly.
    """
    queued = seed(owstore, [Queued(part=f"p{i}") for i in range(60)])
    harvest: dict[int, list[int]] = {0: [], 1: []}
    failures: list[BaseException] = []
    start = threading.Barrier(2)

    def drain(worker_index: int) -> None:
        thread = ow.StoreThread(lambda: ow.connect(owstore), name=f"ow-store-{worker_index}")
        thread.start()
        try:
            store = SqliteStore(thread, wait_ms=ow.BATCH_WAIT_MS)
            start.wait(timeout=10)
            while True:
                rows = store.claim(batch=3, gen=1, worker=f"h:{worker_index}:1.0", lease_ms=600_000)
                if not rows:
                    return
                harvest[worker_index].extend(row.id for row in rows)
        except BaseException as error:  # re-raised on the main thread below.
            failures.append(error)
            start.abort()
        finally:
            thread.close()

    runners = [threading.Thread(target=drain, args=(index,)) for index in (0, 1)]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join(timeout=60)
        assert not runner.is_alive(), "a claimer never finished"
    if failures:
        raise failures[0]

    first, second = harvest[0], harvest[1]
    assert len(first) == len(set(first)) and len(second) == len(set(second))
    assert not set(first) & set(second), "the same row was claimed twice"
    assert sorted(first + second) == sorted(queued), "rows were lost or duplicated"


def test_a_batch_is_coherent_on_dispatch_key(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """One claim, one `dispatch_key` -- charter.md:4083's `head` CTE is what makes it so."""
    store, _ = opened
    seed(
        owstore,
        [Queued(part=f"a{i}", dispatch_key="dk1") for i in range(3)]
        + [Queued(part=f"b{i}", dispatch_key="dk2") for i in range(3)],
    )
    rows = store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000)
    assert len({row.dispatch_key for row in rows}) == 1
    assert len(rows) == 3


def test_a_null_dispatch_key_batches_alone(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """0004_runtime.sql:104-105: *"NULL for an `op.*` row, AND A NULL BATCHES ALONE"*.

    This is the half the charter's printed `w.dispatch_key = head.dispatch_key` gets wrong twice
    over: `=` matches no NULL at all, so `op.identify` would be unclaimable, and a plain `IS` would
    batch every `op.*` row together. Both `op.*` rows here have priority 300, so the head is one of
    them whatever else is queued -- and exactly one must come back.
    """
    store, _ = opened
    seed(
        owstore,
        [
            Queued(part="i0", operator="op.identify", priority=300),
            Queued(part="i1", operator="op.identify", priority=300),
            Queued(part="p0"),
        ],
    )
    rows = store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000)
    assert len(rows) == 1, "a NULL dispatch_key must batch alone"
    assert rows[0].operator == "op.identify"
    assert rows[0].dispatch_key is None


def test_priority_survives_batching(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """08:625-627's property 1. The 300s go first even though they were queued last."""
    store, _ = opened
    seed(
        owstore,
        [Queued(part=f"low{i}", dispatch_key="dk_low", priority=0) for i in range(2)]
        + [Queued(part=f"hi{i}", dispatch_key="dk_hi", priority=200) for i in range(2)],
    )
    rows = store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000)
    assert {row.priority for row in rows} == {200}
    assert [row.priority for row in rows] == sorted((row.priority for row in rows), reverse=True)


def test_a_row_at_the_attempt_ceiling_is_not_claimable(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """`attempts_total < 5` is a clause in the claim predicate (08:107, I7)."""
    store, _ = opened
    seed(
        owstore,
        [
            Queued(part="spent", attempts_total=MAX_WORK_ATTEMPTS),
            Queued(part="one_left", attempts_total=MAX_WORK_ATTEMPTS - 1),
        ],
    )
    rows = store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000)
    assert [row.unit_part for row in rows] == ["one_left"]


def test_a_future_retry_after_is_not_claimable_and_a_past_one_is(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """`retry_after` is a STORE-clock timestamp compared against the store clock (08:597)."""
    store, _ = opened
    seed(
        owstore,
        [
            Queued(part="later", status="failed_transient", retry_after=FAR_FUTURE_MS),
            Queued(part="due", status="failed_transient", retry_after=1),
        ],
    )
    rows = store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000)
    assert [row.unit_part for row in rows] == ["due"]


def test_a_deferred_row_is_not_claimable(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """08:133-137: *"`deferred` is not claimable, and that is a fact about the claim SQL"*."""
    store, _ = opened
    seed(owstore, [Queued(part="held", status="deferred")])
    assert store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000) == []


def test_a_claim_against_an_empty_queue_returns_nothing_rather_than_raising(
    opened: tuple[SqliteStore, ow.StoreThread],
) -> None:
    """The commonest state a polling claim loop is in, and the charter's SQL raises in it.

    With nothing claimable the `head` CTE is empty and its scalar subquery is NULL; SQLite raises
    `datatype mismatch` on a NULL `LIMIT`. `IFNULL(..., 0)` is the fix, and this is the regression
    that pins it -- it is not a corner case, it is every idle tick of the supervisor.
    """
    store, _ = opened
    assert store.claim(batch=10, gen=1, worker=WORKER, lease_ms=60_000) == []


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"batch": 0}, "a claim of no rows"),
        ({"lease_ms": 0}, "the claim IS the lease"),
        ({"worker": ""}, "records WHO holds the lease"),
    ],
)
def test_claim_refuses_a_nonsensical_argument(
    opened: tuple[SqliteStore, ow.StoreThread], kwargs: dict[str, object], needle: str
) -> None:
    """Each refusal is a raise with a fix, never a silent empty claim."""
    store, _ = opened
    call = {"batch": 4, "gen": 1, "worker": WORKER, "lease_ms": 1_000, **kwargs}
    with pytest.raises(StoreError) as caught:
        store.claim(**call)  # type: ignore[arg-type]
    assert needle in str(caught.value)
    assert caught.value.fix


# ---------------------------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------------------------


def claim_one(store: SqliteStore, gen: int = 7) -> WorkRow:
    """Claim exactly one row and return it."""
    rows = store.claim(batch=1, gen=gen, worker=WORKER, lease_ms=600_000)
    assert len(rows) == 1
    return rows[0]


def test_complete_writes_the_transition_the_cache_key_and_the_metrics(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """`ok` -> `done`, plus 02:487's `work.cache_key` and 08:120-124's metric columns."""
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store)

    assert store.complete(
        row.id,
        7,
        result("ok", metrics=StepMetrics(queued_ms=11, ran_ms=22, micros=99, peak_rss_bytes=7)),
    )

    after = read_work(owstore, row.id)
    assert after["status"] == "done"
    assert after["cache_key"] == CACHE_KEY
    assert after["queued_ms"] == 11
    assert after["ran_ms"] == 22
    assert after["cost_micros"] == 99
    assert after["peak_rss_bytes"] == 7
    assert after["claimed_by"] is None
    assert after["claimed_gen"] is None
    assert after["lease_expires"] is None
    assert after["retry_after"] is None


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_outcome_lands_the_status_the_transition_table_specifies(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread], outcome: str
) -> None:
    """08:94-103 is the specification, and this is the eight-row assertion over it.

    The attempt-counter cell is checked in the same pass, because `deferred_budget` and `cancelled`
    decrementing is the reason the table exists (08:105-112) and a test of status alone would let
    that cell be wrong.
    """
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store)
    assert row.attempts_total == 1

    assert store.complete(row.id, 7, result(outcome, metrics=StepMetrics(micros=50)))

    transition = TRANSITIONS[outcome]
    after = read_work(owstore, row.id)
    assert after["status"] == transition.status
    assert after["attempts_total"] == (0 if transition.decrements_attempts else 1)
    assert after["attempts_today"] == (0 if transition.decrements_attempts else 1)
    assert after["cost_micros"] == (50 if transition.adds_micros else 0)


def test_the_attempt_decrement_is_floored_at_zero(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """`MAX(0, attempts_total - 1)` (08:116-119): a claim at 0 goes to 1 and comes back to 0."""
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    for _ in range(3):
        row = claim_one(store)
        assert store.complete(row.id, 7, result("cancelled"))
        assert read_work(owstore, row.id)["attempts_total"] == 0


def test_failed_transient_writes_a_store_clock_retry_after(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """The caller supplies an OFFSET and the store adds its own clock (08:597).

    Asserted as a band rather than a value: what matters is that the column holds a wall-clock
    millisecond timestamp in the future by roughly the offset, not a bare `300000`.
    """
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store)
    assert store.complete(row.id, 7, result("failed_transient"))

    after = read_work(owstore, row.id)
    assert after["status"] == "failed_transient"
    assert after["failure_class"] == "upstream_unavailable"
    retry_after = after["retry_after"]
    assert isinstance(retry_after, int)
    now_ms = int(str(scalar(owstore, "SELECT CAST(unixepoch('subsec')*1000 AS INTEGER)")))
    assert now_ms < retry_after <= now_ms + 300_000


def test_complete_returns_false_for_a_superseded_generation(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """`claimed_gen` is what the commit predicate compares (08:2841); a mismatch writes nothing."""
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store, gen=7)

    assert store.complete(row.id, 8, result("ok")) is False
    after = read_work(owstore, row.id)
    assert after["status"] == "claimed", "a superseded completion writes nothing"
    assert after["cache_key"] == "seed"
    assert after["claimed_gen"] == 7


def test_complete_returns_false_once_the_row_has_been_reaped_and_reclaimed(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """The other two ways to be superseded: a reap, then another worker's claim."""
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store, gen=7)
    assert store.reap_expired_leases(FAR_FUTURE_MS) == 1
    assert store.complete(row.id, 7, result("ok")) is False

    reclaimed = claim_one(store, gen=9)
    assert reclaimed.id == row.id
    assert store.complete(row.id, 7, result("ok")) is False
    assert store.complete(row.id, 9, result("ok")) is True


def test_complete_raises_rather_than_returning_false_for_a_row_that_does_not_exist(
    opened: tuple[SqliteStore, ow.StoreThread],
) -> None:
    """08:2489-2494: a boolean meaning both "someone else won" and "you are wrong" is a no-op bug.

    The half that is easy to get wrong is this one -- the commit predicate matches zero rows for a
    nonexistent id exactly as it does for a superseded one, so collapsing them is one line of
    laziness away. `is False` rather than a falsy check, because the bug being guarded against
    returns `False`.
    """
    store, _ = opened
    with pytest.raises(StoreError) as caught:
        store.complete(4321, 7, result("ok"))
    assert "does not exist" in str(caught.value)


def test_complete_raises_rather_than_returning_false_for_an_outcome_outside_the_eight(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """A driver reporting an outcome the transition table has no row for is a driver being wrong."""
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store)

    class Rogue:
        outcome = "mostly_ok"
        cache_key = CACHE_KEY
        failure_class = None
        failure_message = None
        retry_after_ms = None
        metrics = StepMetrics()

    with pytest.raises(StoreError) as caught:
        store.complete(row.id, 7, Rogue())  # type: ignore[arg-type]
    assert "mostly_ok" in str(caught.value)
    assert read_work(owstore, row.id)["status"] == "claimed"


def test_complete_raises_rather_than_returning_false_above_max_deps_per_unit(
    opened_with: object,
) -> None:
    """`MAX_DEPS_PER_UNIT` is 08:2491's first named raise, and it must not be a `False`."""
    over = [("unit", f"k{i}", "d") for i in range(MAX_DEPS_PER_UNIT + 1)]
    store, path = opened_with(dep_rows=lambda row_id, _r: dep_statements(row_id, over))  # type: ignore[operator]
    seed(path, [Queued(part="p0")])
    row = claim_one(store)
    with pytest.raises(ResourceLimit) as caught:
        store.complete(row.id, 7, result("ok"))
    assert caught.value.limit == "[runtime] max_deps_per_unit"
    assert read_work(path, row.id)["status"] == "claimed"


@pytest.fixture
def opened_with(owstore: Path) -> Iterator[object]:
    """A factory for a `SqliteStore` with participant contributions, closed on the way out."""
    threads: list[ow.StoreThread] = []

    def make(**kwargs: object) -> tuple[SqliteStore, Path]:
        thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
        threads.append(thread)
        return SqliteStore(thread, **kwargs), owstore  # type: ignore[arg-type]

    try:
        yield make
    finally:
        for thread in threads:
            thread.close()


DEP_INSERT = Statement(
    participant="derived_rows",
    name="probe_dep",
    sql="INSERT INTO dep(dependent_id, kind, key, digest) VALUES(:dependent_id, 'unit', 'k', 'd')",
    params={},
)
"""A real, valid write for an earlier participant to make, so "nothing landed" has something to be
about. It goes into `dep` because that table exists at P2, cascades off `work(id)`, and is trivially
countable from outside the store."""


def _derived(row_id: int, _result: object) -> Sequence[Statement]:
    return (replace(DEP_INSERT, params={"dependent_id": row_id}),)


def _broken(_row_id: int, _result: object) -> Sequence[Statement]:
    return (
        Statement(
            participant="spend_row",
            name="deliberately_broken",
            sql="INSERT INTO no_such_table(x) VALUES(1)",
            params={},
        ),
    )


def test_complete_is_atomic_across_every_participant_it_has(
    opened_with: object,
) -> None:
    """One participant fails and NOTHING landed -- not the transition, not the earlier row.

    This is the assertion 07:2730-2733 makes ("together or not at all") and the one a test of the
    exception alone would miss entirely: a store that committed the first two participants and then
    raised would satisfy `pytest.raises` perfectly. The failing participant is `spend_row`, which
    comes LAST, so both of the participants before it have already executed when it blows up.
    """
    store, path = opened_with(derived_rows=_derived, spend_row=_broken)  # type: ignore[operator]
    seed(path, [Queued(part="p0")])
    row = claim_one(store)

    with pytest.raises(sqlite3.OperationalError):
        store.complete(row.id, 7, result("ok"))

    assert scalar(path, "SELECT count(*) FROM dep") == 0, "an earlier participant's row survived"
    after = read_work(path, row.id)
    assert after["status"] == "claimed", "the work transition survived a failed participant"
    assert after["cache_key"] == "seed"


def test_a_superseded_complete_rolls_back_the_earlier_participants_too(
    opened_with: object,
) -> None:
    """charter.md:4105: *"ZERO ROWS => SUPERSEDED => THE WHOLE TRANSACTION ROLLS BACK."*

    Returning `False` from inside the closure instead of raising would leave `derived_rows`'
    `dep` row committed against a row somebody else now owns. That is why supersession is a raise
    internally and a `False` only at the boundary.
    """
    store, path = opened_with(derived_rows=_derived)  # type: ignore[operator]
    seed(path, [Queued(part="p0")])
    row = claim_one(store, gen=7)

    assert store.complete(row.id, 8, result("ok")) is False
    assert scalar(path, "SELECT count(*) FROM dep") == 0
    assert read_work(path, row.id)["status"] == "claimed"


def test_a_contribution_lands_when_nothing_fails(opened_with: object) -> None:
    """The control for the two rollback tests: the same `dep` row DOES land on the happy path.

    Without it, both tests above pass against a store whose `derived_rows` contribution is never
    executed at all.
    """
    store, path = opened_with(derived_rows=_derived)  # type: ignore[operator]
    seed(path, [Queued(part="p0")])
    row = claim_one(store, gen=7)

    assert store.complete(row.id, 7, result("ok")) is True
    assert scalar(path, "SELECT count(*) FROM dep") == 1
    assert read_work(path, row.id)["status"] == "done"


# ---------------------------------------------------------------------------------------------
# ST14 -- durability, asserted AT COMMIT TIME
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cost_class", "expected"),
    [("billed_api", ow.SYNCHRONOUS_FULL), ("free", ow.SYNCHRONOUS_NORMAL)],
)
def test_the_synchronous_pragma_at_commit_is_full_for_billed_and_normal_for_free(
    owstore: Path, cost_class: str, expected: int
) -> None:
    """ST14 (07:2735-2740): *"a test asserts the pragma value **at commit time**"*.

    Inside `Unit.on_commit`, with the transaction still open -- reading it after `COMMIT` would
    assert nothing, since the pragma is a connection setting that outlives the transaction and the
    next unit resets it anyway. That the store had to READ `work.cost_class` to get here is the
    consequence of the narrow `complete()` this test also covers: nothing in the call carries it.
    """
    observed: list[int] = []
    thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        store = SqliteStore(
            thread,
            on_commit=lambda c: observed.append(int(c.execute("PRAGMA synchronous").fetchone()[0])),
        )
        seed(owstore, [Queued(part="p0", cost_class=cost_class)])
        row = claim_one(store)
        assert row.cost_class == cost_class
        assert store.complete(row.id, 7, result("ok"))
    finally:
        thread.close()
    assert observed == [expected]


# ---------------------------------------------------------------------------------------------
# reap
# ---------------------------------------------------------------------------------------------


def test_an_expired_lease_is_reaped_and_the_row_becomes_claimable_again(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """08:2411: the row goes to `pending` with `attempts_total` decremented. Not to a failure."""
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store)
    assert row.attempts_total == 1

    assert store.reap_expired_leases(FAR_FUTURE_MS) == 1

    after = read_work(owstore, row.id)
    assert after["status"] == "pending"
    assert after["attempts_total"] == 0, "a power cut is not an attempt (08:121-122)"
    assert after["attempts_today"] == 0
    assert after["claimed_by"] is None
    assert after["claimed_gen"] is None
    assert after["lease_expires"] is None
    assert [r.id for r in store.claim(batch=8, gen=9, worker=WORKER, lease_ms=1_000)] == [row.id]


def test_a_live_lease_is_not_reaped(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """`lease_expires < :now_ms` is strict, so a lease in the future -- or exactly now -- survives.

    The paired assertion with the test above: a reaper that swept unconditionally would pass that
    one and fail this one, and only this one distinguishes "reaps expired leases" from "reaps".
    """
    store, _ = opened
    seed(owstore, [Queued(part="p0")])
    row = claim_one(store)
    lease = read_work(owstore, row.id)["lease_expires"]
    assert isinstance(lease, int)

    assert store.reap_expired_leases(lease) == 0, "a lease expiring exactly now is still live"
    assert store.reap_expired_leases(lease - 1) == 0
    assert read_work(owstore, row.id)["status"] == "claimed"
    assert store.reap_expired_leases(lease + 1) == 1


def test_the_reap_releases_the_reservations_of_exactly_the_rows_it_reaped(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """I29 (0004_runtime.sql:238-240): released IN THE SAME TRANSACTION as the lease reap.

    The table has no P2 producer, so the rows are seeded by hand -- which is the only way to assert
    that the statement is correct before P4 can exercise it. The unclaimed row's reservation is the
    control: a sweep that released every `held` row would pass a one-row test.
    """
    store, _ = opened
    ids = seed(owstore, [Queued(part="p0"), Queued(part="p1", dispatch_key="dk2")])
    row = claim_one(store)
    other = next(i for i in ids if i != row.id)

    connection = ow.connect(owstore)
    try:
        connection.execute(
            "INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest,"
            " policy_digest, pricebook_digest, lock_digest, omniweave_version, contract, schema,"
            " started_ns, status, manifest_path)"
            " VALUES('r_1', 1, 'cli', '[]', 'c', 's', 'p', 'pb', 'l', '0.1', 1, 1, 1,"
            " 'running', 'm')"
        )
        for index, work_id in ((0, row.id), (1, other)):
            connection.execute(
                "INSERT INTO budget_reservation(reservation_id, run_id, work_id, decision_id,"
                " dim, amount, scope, scope_key, claimed_gen, expires_ms, state)"
                " VALUES(?, 'r_1', ?, ?, 'micros', 10, 'run', '', 7, 1, 'held')",
                (f"res_{index}", work_id, f"dec_p{index}"),
            )
    finally:
        connection.close()

    assert store.reap_expired_leases(FAR_FUTURE_MS) == 1

    held = scalar(owstore, "SELECT count(*) FROM budget_reservation WHERE state = 'held'")
    assert held == 1, "only the reaped row's reservation is released"
    state = scalar(owstore, "SELECT state FROM budget_reservation WHERE reservation_id = 'res_0'")
    assert state == "released"


# ---------------------------------------------------------------------------------------------
# counts_by_status
# ---------------------------------------------------------------------------------------------


def test_counts_by_status_is_total_over_the_six_statuses(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """Every status is a key. A zero is an answer and a missing key is not."""
    store, _ = opened
    seed(
        owstore,
        [
            Queued(part="a"),
            Queued(part="b"),
            Queued(part="c", status="deferred"),
            Queued(part="d", status="failed_permanent"),
        ],
    )
    counts = store.counts_by_status()
    assert set(counts) == set(WORK_STATUSES)
    assert counts == {
        "pending": 2,
        "claimed": 0,
        "done": 0,
        "failed_transient": 0,
        "failed_permanent": 1,
        "deferred": 1,
    }

    claim_one(store)
    assert store.counts_by_status()["claimed"] == 1
    assert store.counts_by_status()["pending"] == 1


def test_counts_by_status_issues_exactly_one_query(
    owstore: Path, opened: tuple[SqliteStore, ow.StoreThread]
) -> None:
    """0004_runtime.sql:137 forbids the alternative, and "one query" is countable.

    Counted with `set_trace_callback` on the store thread's own connection, so what is measured is
    what SQLite actually received -- not what this module intended to send. Transaction demarcation
    and pragmas are filtered out: they are `sqlite.py`'s and are asserted in its own suite.
    """
    store, thread = opened
    seed(owstore, [Queued(part="a"), Queued(part="b", status="done")])
    traced: list[str] = []

    thread.run(ow.Unit(name="trace-on", run=lambda c: c.set_trace_callback(traced.append)))
    traced.clear()
    counts = store.counts_by_status()
    thread.run(ow.Unit(name="trace-off", run=lambda c: c.set_trace_callback(None)))

    queries = [
        line
        for line in traced
        if not line.upper().startswith(("BEGIN", "COMMIT", "ROLLBACK", "PRAGMA"))
    ]
    assert queries == [COUNTS_SQL], queries
    assert counts["pending"] == 1


# ---------------------------------------------------------------------------------------------
# The plan, the participants and the crash boundaries
# ---------------------------------------------------------------------------------------------


def test_the_p2_complete_plan_is_the_work_transition_alone(
    opened: tuple[SqliteStore, ow.StoreThread],
) -> None:
    """Four of the five participants have no P2 producer, and the plan says so out loud."""
    store, _ = opened
    plan = store.complete_plan(1, result("ok"))
    assert [statement.participant for statement in plan] == ["work_transition"]
    assert plan[0].name == "work_update"
    assert plan[0].sql == COMPLETE_SQL


def test_a_contribution_extends_the_plan_in_participant_order(opened_with: object) -> None:
    """The composition seam: a participant is a slot, and the order is 07:2731's printed order."""
    store, _ = opened_with(derived_rows=_derived, spend_row=_broken)  # type: ignore[operator]
    plan = store.complete_plan(4, result("ok"))
    participants = [statement.participant for statement in plan]
    assert participants == ["derived_rows", "work_transition", "spend_row"]
    assert participants == sorted(participants, key=COMPLETE_PARTICIPANTS.index)
    assert plan[0].params["dependent_id"] == 4


def test_complete_boundaries_enumerates_two_more_points_than_the_plan_has_statements(
    opened_with: object,
) -> None:
    """W2.9 SIGKILLs at every one of these, and gets them from here rather than from the source.

    `len(plan) + 2`: one after `BEGIN IMMEDIATE`, one after each statement, one after `COMMIT`.
    """
    store, _ = opened_with(derived_rows=_derived)  # type: ignore[operator]
    plan = store.complete_plan(1, result("ok"))
    boundaries = complete_boundaries(plan)
    assert len(boundaries) == len(plan) + 2
    assert boundaries == (
        "after:begin",
        "after:derived_rows/probe_dep",
        "after:work_transition/work_update",
        "after:commit",
    )


def test_the_five_participants_are_the_five_the_plan_prints() -> None:
    """07:2730-2733 and 02:487 print the same five in the same order; both are transcribed."""
    assert COMPLETE_PARTICIPANTS == (
        "derived_rows",
        "work_transition",
        "dep_rows",
        "reservation_commit",
        "spend_row",
    )


# ---------------------------------------------------------------------------------------------
# dep_statements -- the refusals ship before the producer does
# ---------------------------------------------------------------------------------------------


def test_dep_statements_produces_one_insert_or_ignore_per_dep() -> None:
    """Idempotency mechanism 2 (08:428): `INSERT OR IGNORE` against `dep`'s own PRIMARY KEY."""
    statements = dep_statements(3, [("unit", "file:///a", "d1"), ("part", "file:///a#p1", "d2")])
    assert [s.participant for s in statements] == ["dep_rows", "dep_rows"]
    assert all("INSERT OR IGNORE INTO dep" in s.sql for s in statements)
    assert [s.params["key"] for s in statements] == ["file:///a", "file:///a#p1"]


def test_dep_statements_refuses_above_max_deps_per_unit() -> None:
    """`ResourceLimit`, naming the knob. The cap itself is accepted, so the edge is asserted."""
    at_cap = [("unit", f"k{i}", "d") for i in range(MAX_DEPS_PER_UNIT)]
    assert len(dep_statements(1, at_cap)) == MAX_DEPS_PER_UNIT
    with pytest.raises(ResourceLimit) as caught:
        dep_statements(1, [*at_cap, ("unit", "one_too_many", "d")])
    assert caught.value.limit == "[runtime] max_deps_per_unit"
    assert "cohort dep" in caught.value.fix


def test_dep_statements_refuses_a_kind_outside_the_closed_domain() -> None:
    """The CHECK would catch it inside the transaction; this catches it before one opens."""
    with pytest.raises(StoreError) as caught:
        dep_statements(1, [("dependency", "k", "d")])
    assert "dependency" in str(caught.value)


def test_dep_statements_refuses_a_key_outside_the_invocations_input_set() -> None:
    """08:2491's second named raise. Optional: the narrow signature has no channel for the set."""
    allowed = frozenset({"file:///a"})
    assert dep_statements(1, [("unit", "file:///a", "d")], allowed_keys=allowed)
    with pytest.raises(StoreError) as caught:
        dep_statements(1, [("unit", "file:///elsewhere", "d")], allowed_keys=allowed)
    assert "input set" in str(caught.value)


# ---------------------------------------------------------------------------------------------
# `StepResult`'s own constructor invariants moved to `test_operator.py` with the type (08:222-231).
# What stays here is the boundary's refusal: `test_complete_refuses_an_outcome_outside_the_eight`
# above hands `complete()` a duck-typed object whose `outcome` is `'mostly_ok'` and asserts a
# `StoreError` naming it, which is the check that survives a caller who never built a `StepResult`
# at all.
# ---------------------------------------------------------------------------------------------


def test_work_row_refuses_a_tuple_of_the_wrong_width() -> None:
    """The guard that makes the named `RETURNING` projection safe against a later migration."""
    with pytest.raises(StoreError, match="columns"):
        WorkRow.from_row((1, 2, 3))
