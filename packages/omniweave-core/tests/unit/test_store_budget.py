"""`SqliteBudgetLedger` against a real `.owstore`: reserve, headroom, commit, release, and D141.

Everything here runs the shipped SQL on a real SQLite file with all four migrations applied, because
the properties that matter are properties of *the database*: that a partial reservation cannot
exist, that a committed row still consumes its cap, that lowering `amount` at commit is what
releases the over-reservation, and that a reservation the commit transaction forgets is unreachable
forever. None of those can be asserted against a mock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from omniweave_core.budget import (
    COMMIT_SQL,
    UNCAPPED,
    Reservation,
    reservation_id,
    reserved_amount,
    scope_key_for,
)
from omniweave_core.errors import StoreError
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.budget import (
    RELEASE_REMAINING_SQL,
    SqliteBudgetLedger,
    reservation_commit,
    reservation_commit_statements,
)
from omniweave_core.work import REAP_RESERVATIONS_SQL

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

NOW_NS = 1_757_400_000_000_000_000
RUN_ID = "r_01HF7YAT000000000000000000"
URI = "file:///corpus/a.pdf"
PART = "p3"
DECISION = "dec_p3"
LEASE_EXPIRES_MS = 1_757_400_120_000

PART_KEY = scope_key_for("part", unit_uri=URI, unit_part=PART)

_RUN_SQL = (
    "INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest,"
    " policy_digest, pricebook_digest, lock_digest, omniweave_version, contract, schema,"
    " started_ns, status, manifest_path)"
    " VALUES(:run_id, 1, 'cli', '[]', 'c', 's', 'p', 'pb', 'l', '0.1', 1, 1, 1,"
    " 'running', 'm')"
)

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
  'drv', 'billed_api', 'r1', 'test:1', 'sk',
  'ev', '{}', 0, 0, 'admitted', 1, 1)
"""

_WORK_SQL = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key,
                 decision_id, driver, cost_class, dispatch_key, status,
                 claimed_by, claimed_gen, lease_expires)
VALUES(:uri, :part, 'parse.page', 1, 'seed',
       :decision_id, 'drv', 'billed_api', 'dk1', :status,
       'host:1:2.0', 1, :lease_expires)
"""


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    """A real `.owstore` with all four migrations, one run, one unit, one decision, one work row."""
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        assert len(applied) == 4
        connection.execute(_RUN_SQL, {"run_id": RUN_ID})
        connection.execute(_UNIT_SQL, {"uri": URI})
        connection.execute(_EVIDENCE_SQL)
        connection.execute(_DECISION_SQL, {"decision_id": DECISION, "unit_part": PART})
        connection.execute(
            _WORK_SQL,
            {
                "uri": URI,
                "part": PART,
                "decision_id": DECISION,
                "status": "claimed",
                "lease_expires": LEASE_EXPIRES_MS,
            },
        )
    finally:
        connection.close()
    return path


@pytest.fixture
def ledger(owstore: Path) -> Iterator[SqliteBudgetLedger]:
    """A ledger over its own store thread, closed on the way out."""
    thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield SqliteBudgetLedger(thread)
    finally:
        thread.close()


def work_id(path: Path) -> int:
    connection = ow.connect(path)
    try:
        row = connection.execute("SELECT id FROM work").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        connection.close()


def rows(path: Path) -> list[tuple[str, str, int]]:
    """`(dim, state, amount)` for every reservation, read outside the ledger under test."""
    connection = ow.connect(path)
    try:
        return [
            (str(dim), str(state), int(amount))
            for dim, state, amount in connection.execute(
                "SELECT dim, state, amount FROM budget_reservation ORDER BY dim"
            )
        ]
    finally:
        connection.close()


def run_sql(path: Path, sql: str, params: dict[str, object]) -> int:
    """Run one statement outside the ledger and return its `rowcount`."""
    connection = ow.connect(path)
    try:
        with connection:
            return connection.execute(sql, params).rowcount
    finally:
        connection.close()


def reservation(
    path: Path, dim: str, amount: int, *, scope: str = "part", attempt: int = 1
) -> Reservation:
    identity = work_id(path)
    return Reservation(
        reservation_id=reservation_id(identity, DECISION, attempt, dim),
        run_id=RUN_ID,
        work_id=identity,
        decision_id=DECISION,
        dim=dim,
        amount=amount,
        scope=scope,
        scope_key=PART_KEY if scope == "part" else RUN_ID,
        claimed_gen=1,
        expires_ms=LEASE_EXPIRES_MS,
    )


# ---------------------------------------------------------------------------------------------
# 1. Headroom
# ---------------------------------------------------------------------------------------------


def test_headroom_of_an_empty_ledger_is_the_whole_limit(
    ledger: SqliteBudgetLedger,
) -> None:
    """`SUM` over no rows is `NULL`, and `COALESCE` is why this is 6000 rather than `None`."""
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 6_000


def test_a_held_reservation_subtracts_and_so_does_a_committed_one(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """I29's arithmetic: `limit - sum(held) - sum(committed)`. A committed row is still spent."""
    held = reservation(owstore, "micros", 2_732)
    assert ledger.reserve([held], {"micros": 6_000}) is None
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 3_268

    assert ledger.commit(held.reservation_id, 854) is True
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 5_146


def test_headroom_refuses_the_uncapped_sentinel_rather_than_binding_it(
    ledger: SqliteBudgetLedger,
) -> None:
    """`:limit` is an integer in the statement; `-1` would deny every request in the run."""
    with pytest.raises(StoreError, match="no declared cap"):
        ledger.headroom("micros", "part", PART_KEY, UNCAPPED)
    with pytest.raises(StoreError, match="not a cap"):
        ledger.headroom("micros", "part", PART_KEY, -7)
    assert ledger.headroom("bytes_egress", "run", RUN_ID, 0) == 0


def test_headroom_is_recomputed_and_never_memoised(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """A figure cached in an attribute is wrong the moment another process reserves.

    The second writer here is a plain connection outside the ledger, which is the closest a unit
    test gets to the second scheduler process 05:2543 is written against.
    """
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 6_000
    row = reservation(owstore, "micros", 1_000)
    run_sql(
        owstore,
        "INSERT INTO budget_reservation(reservation_id, run_id, work_id, decision_id, dim,"
        " amount, scope, scope_key, claimed_gen, expires_ms, state)"
        " VALUES(:reservation_id, :run_id, :work_id, :decision_id, :dim, :amount, :scope,"
        " :scope_key, :claimed_gen, :expires_ms, :state)",
        dict(row.as_params()),
    )
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 5_000


# ---------------------------------------------------------------------------------------------
# 2. Reserve -- all of them, or none of them
# ---------------------------------------------------------------------------------------------


def test_one_decision_takes_one_row_per_dimension(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """08:2244. The crash snapshot's six held rows are four dimensions on one billed part."""
    wanted = [
        reservation(owstore, "micros", 2_732),
        reservation(owstore, "tokens_in", 1_800),
        reservation(owstore, "tokens_out", reserved_amount(1_100, "tokens_out", 3.2)),
        reservation(owstore, "calls", 1),
    ]
    assert ledger.reserve(wanted, {"micros": 6_000, "tokens_out": 24_000, "calls": 3}) is None
    assert rows(owstore) == [
        ("calls", "held", 1),
        ("micros", "held", 2_732),
        ("tokens_in", "held", 1_800),
        ("tokens_out", "held", 3_520),
    ]


def test_a_denial_inserts_nothing_at_all(ledger: SqliteBudgetLedger, owstore: Path) -> None:
    """Two passes in one transaction: check every dimension, then insert every dimension.

    A loop that inserted as it checked would leave three rows holding headroom for work that will
    never run -- and after the work row settles, nothing can release them (see D141 below).
    """
    wanted = [
        reservation(owstore, "micros", 2_732),
        reservation(owstore, "tokens_in", 1_800),
        reservation(owstore, "calls", 4),
    ]
    assert ledger.reserve(wanted, {"micros": 6_000, "calls": 3}) == "calls"
    assert rows(owstore) == []


def test_the_first_exhausted_dimension_wins_and_it_is_the_first_in_order(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """05:2527 step 5. Two dimensions over their cap, and the answer names the one checked first."""
    wanted = [
        reservation(owstore, "tokens_out", 99_999),
        reservation(owstore, "calls", 99),
    ]
    assert ledger.reserve(wanted, {"tokens_out": 24_000, "calls": 3}) == "tokens_out"
    assert ledger.reserve(list(reversed(wanted)), {"tokens_out": 24_000, "calls": 3}) == "calls"


def test_an_uncapped_dimension_is_still_recorded(ledger: SqliteBudgetLedger, owstore: Path) -> None:
    """A dimension absent from `limits` inserts its row, so the held sum is right on the day a cap
    is declared for it. Skipping the insert would make the first capped run start from zero."""
    assert ledger.reserve([reservation(owstore, "gpu_ms", 7_680, scope="run")], {}) is None
    assert rows(owstore) == [("gpu_ms", "held", 7_680)]


def test_a_retried_reserve_is_a_no_op_and_not_a_second_row(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """`INSERT OR IGNORE` over a content-addressed primary key. 08:2238.

    The second call must neither raise nor double-count: a crash between the insert and the
    caller's acknowledgement is exactly the case the idempotence is for.
    """
    wanted = [reservation(owstore, "micros", 2_732)]
    assert ledger.reserve(wanted, {"micros": 6_000}) is None
    assert ledger.reserve(wanted, {"micros": 6_000}) is None
    assert rows(owstore) == [("micros", "held", 2_732)]
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 3_268


def test_reserving_nothing_is_refused(ledger: SqliteBudgetLedger) -> None:
    """An admission that reserves nothing looks admitted and bounds nothing."""
    with pytest.raises(StoreError, match="not an admission"):
        ledger.reserve([], {"micros": 10})


# ---------------------------------------------------------------------------------------------
# 3. Commit and release
# ---------------------------------------------------------------------------------------------


def test_a_commit_only_moves_a_held_row(ledger: SqliteBudgetLedger, owstore: Path) -> None:
    """`AND state='held'`: a second commit finds nothing and says so rather than double-counting."""
    held = reservation(owstore, "micros", 2_732)
    ledger.reserve([held], {"micros": 6_000})

    assert ledger.commit(held.reservation_id, 854) is True
    assert ledger.commit(held.reservation_id, 1) is False
    assert rows(owstore) == [("micros", "committed", 854)]


def test_a_release_gives_the_whole_reservation_back(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """A cancel, or a cache hit (I25): *"zero budget, zero tokens, zero rate-limit slots"*."""
    held = reservation(owstore, "micros", 2_732)
    ledger.reserve([held], {"micros": 6_000})

    assert ledger.release(held.reservation_id) is True
    assert ledger.headroom("micros", "part", PART_KEY, 6_000) == 6_000
    assert rows(owstore) == [("micros", "released", 2_732)]
    assert ledger.release(held.reservation_id) is False


def test_a_commit_for_a_row_that_was_never_reserved_is_false_not_an_error(
    ledger: SqliteBudgetLedger,
) -> None:
    """Three outcomes share the `False`, and none of them is a bug in the caller."""
    assert ledger.commit("res_000000000000000000000000", 1) is False
    assert ledger.release("res_000000000000000000000000") is False


def test_the_retry_arithmetic_the_plan_works_out_by_hand(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """05:2489-2492, executed: *"attempt 1 reserves 2,732 and commits 854, attempt 2 sees
    6000 - 854 = 5146 of headroom, attempt 3 sees 6000 - 1708 = 4292, and the `micros` dimension
    alone would permit **five** attempts before 6000 - 3416 = 2584 < 2732."*

    Release-on-commit is what makes a retry chain not accumulate p95 reservations. The plan's own
    conclusion is the last assertion: `micros` is not what stops a runaway part on this pricebook.
    """
    headroom = []
    for attempt in (1, 2, 3, 4, 5):
        row = reservation(owstore, "micros", 2_732, attempt=attempt)
        available = ledger.headroom("micros", "part", PART_KEY, 6_000)
        headroom.append(available)
        if available < row.amount:
            break
        assert ledger.reserve([row], {"micros": 6_000}) is None
        assert ledger.commit(row.reservation_id, 854) is True

    assert headroom == [6_000, 5_146, 4_292, 3_438, 2_584]
    assert headroom[-1] < 2_732, "the fifth attempt is the one micros denies"


# ---------------------------------------------------------------------------------------------
# 4. The commit participant, and D141
# ---------------------------------------------------------------------------------------------


def test_the_participant_commits_every_dimension_then_sweeps_what_is_left(
    owstore: Path,
) -> None:
    """Order is the property: the release-remaining statement is last, and must be."""
    identity = work_id(owstore)
    statements = reservation_commit_statements(
        identity, decision_id=DECISION, attempt=1, actual={"micros": 854, "calls": 1}
    )

    assert [statement.name for statement in statements] == [
        "reservation_commit[micros]",
        "reservation_commit[calls]",
        "reservation_release_remaining",
    ]
    assert {statement.participant for statement in statements} == {"reservation_commit"}
    assert statements[-1].sql == RELEASE_REMAINING_SQL
    assert statements[0].sql == COMMIT_SQL


def test_both_commit_paths_submit_the_same_statement() -> None:
    """One home for `COMMIT_SQL`, two submitters, so its predicate cannot drift."""
    statements = reservation_commit_statements(1, decision_id="d", attempt=1, actual={"micros": 1})
    assert statements[0].sql is COMMIT_SQL
    source = SqliteBudgetLedger.commit.__doc__ or ""
    assert (
        "runner does not call this" in source.lower() or "The runner does not call this" in source
    )


def test_the_participant_reserves_nothing_for_a_core_only_row() -> None:
    """08:2302's accounting hole: an `op.*` row's `decision_id` is NULL by CHECK, so it cannot hold
    a reservation at all -- `budget_reservation.decision_id` is `NOT NULL`."""
    with pytest.raises(StoreError, match="holds no reservation"):
        reservation_commit_statements(1, decision_id="", attempt=1, actual={"micros": 1})


def test_a_bound_contribution_ignores_the_result_view_and_uses_the_row_id(owstore: Path) -> None:
    """The narrow `(row_id, result)` signature two sites print, with the rest closed over."""
    contribute = reservation_commit(DECISION, 1, {"micros": 854})
    identity = work_id(owstore)
    statements = contribute(identity, object())  # type: ignore[operator, arg-type]
    assert statements[0].params["reservation_id"] == reservation_id(identity, DECISION, 1, "micros")


def test_a_held_reservation_on_a_settled_work_row_is_unreachable_by_the_reaper(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """**D141**, demonstrated rather than argued.

    `work.REAP_RESERVATIONS_SQL` finds expired reservations *through their work rows* --
    `WHERE status = 'claimed' AND lease_expires < :now_ms` -- so a reservation left `held` when the
    row went `done` is invisible to it at any clock value. It would subtract from headroom for the
    life of the store.

    The first half of this test is the leak; the second is `RELEASE_REMAINING_SQL` closing it.
    """
    held = reservation(owstore, "tokens_out", 3_520)
    assert ledger.reserve([held], {"tokens_out": 24_000}) is None
    run_sql(owstore, "UPDATE work SET status='done' WHERE id=:id", {"id": work_id(owstore)})

    swept = run_sql(owstore, REAP_RESERVATIONS_SQL, {"now_ms": 1 << 62})
    assert swept == 0, "the reaper cannot see a reservation whose work row has settled"
    assert ledger.headroom("tokens_out", "part", PART_KEY, 24_000) == 20_480

    closed = run_sql(owstore, RELEASE_REMAINING_SQL, {"work_id": work_id(owstore)})
    assert closed == 1
    assert ledger.headroom("tokens_out", "part", PART_KEY, 24_000) == 24_000


def test_the_reaper_does_reach_a_reservation_whose_lease_expired_while_claimed(
    ledger: SqliteBudgetLedger, owstore: Path
) -> None:
    """The other side of D141: on a row still `claimed`, 08:2244's guarantee holds as written.

    This is what makes the defect a gap rather than a broken statement -- the reap is correct for
    the case it was written for, which is the SIGKILLed worker.
    """
    held = reservation(owstore, "tokens_out", 3_520)
    assert ledger.reserve([held], {"tokens_out": 24_000}) is None

    assert run_sql(owstore, REAP_RESERVATIONS_SQL, {"now_ms": LEASE_EXPIRES_MS - 1}) == 0
    assert run_sql(owstore, REAP_RESERVATIONS_SQL, {"now_ms": LEASE_EXPIRES_MS + 1}) == 1
    assert ledger.headroom("tokens_out", "part", PART_KEY, 24_000) == 24_000
