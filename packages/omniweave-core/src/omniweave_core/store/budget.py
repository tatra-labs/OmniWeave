"""`SqliteBudgetLedger` -- the four budget statements submitted on the store thread.

`omniweave_core.budget` holds the statements, the domains and the identity recipe; this file is what
runs them, and the split is `work.py`/`store/queue.py`'s one module over. 02-architecture.md row 19
gives `omniweave_core.budget` the ledger and names the calls `BudgetLedger.reserve/commit/release/
headroom`; INV-17 gives `omniweave_core.store` *"the ONLY `sqlite3.connect`"*, so the object that
holds a connection lives here and satisfies that Protocol structurally.

## The two paths to a commit, and why there are two

`COMMIT_SQL` has exactly one home (`omniweave_core.budget`) and two submitters:

1. **`reservation_commit_statements()`** -- the `reservation_commit` participant of
   `SqliteStore.complete()`. This is the path the runner takes, because I20 requires the
   held-to-committed transition to land *"IN THE SAME TRANSACTION as the derived rows, the work
   transition, the dep rows and the spend row"* (08:2240-2242, 07:2730-2733).
2. **`SqliteBudgetLedger.commit()`** -- the same statement in a transaction of its own, for the
   callers that are not inside a `complete()`: a repair path, and a test that needs to observe one
   statement at a time.

`test_store_budget.py` asserts both emit the same SQL string, so the `AND state='held'` predicate
that makes a commit safe cannot drift between them.

## The leak the plan does not close, and the statement that closes it (D141)

08:2244 releases expired reservations *"IN THE SAME TRANSACTION as the lease reap, so a SIGKILL
cannot leak headroom"*, and `work.REAP_RESERVATIONS_SQL` implements it by joining to the work rows
about to be reaped -- `WHERE status = 'claimed' AND lease_expires < :now_ms`.

A reservation left `held` on a work row that **completed** is therefore unreachable: the row is
`done`, not `claimed`, so the reaper's subquery never selects it, and its `amount` subtracts from
headroom for the life of the store. That happens whenever a decision reserves a dimension the
attempt does not spend -- which the p95 model makes ordinary rather than exceptional, since
`reserved_amount()` scales `tokens_out` and `gpu_ms` by 3.2 and an attempt that returns early
spends neither.

`RELEASE_REMAINING_SQL` is the answer and it runs last in the commit participant: every row still
`held` for this work row is released in the same transaction that commits the ones that were spent.
It is not in the plan; the defect is filed as D141 and the statement is here rather than in
`omniweave_core.budget` because it is a property of *this* transaction's shape.

Specified in 02-architecture.md section 2 rows 19 and 26, 08-runtime.md section 7.3 (:2224-2249),
05-ingest-and-routing.md section 6.4 and `0004_runtime.sql:222-240`.
"""

from __future__ import annotations

import sqlite3
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.budget import (
    COMMIT_SQL,
    HEADROOM_SQL,
    RELEASE_SQL,
    RESERVE_SQL,
    UNCAPPED,
    reservation_id,
)
from omniweave_core.errors import StoreError
from omniweave_core.store.queue import Contribution, Statement
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.budget import Reservation
    from omniweave_core.store.queue import StepResultView

__all__ = [
    "RELEASE_REMAINING_SQL",
    "SqliteBudgetLedger",
    "reservation_commit",
    "reservation_commit_statements",
]

RELEASE_REMAINING_SQL: Final = """
UPDATE budget_reservation SET state='released'
 WHERE work_id=:work_id AND state='held'
"""
"""Release every reservation this work row still holds. **D141**, and it runs last.

The reaper cannot reach a `held` reservation whose work row is `done`: `work.REAP_RESERVATIONS_SQL`
selects `WHERE status = 'claimed' AND lease_expires < :now_ms`, so a dimension that was reserved
and not spent would subtract from headroom until the store was deleted. Under the p95 model that is
the common case rather than the rare one: `reserved_amount()` scales `tokens_out` and `gpu_ms` by
`tokens_out_p95_multiple`, and an attempt that stops early spends neither.

**Last**, after the per-dimension commits, because it is keyed on `state='held'` and the committed
rows have already left that state. Reversing the order would release the rows this transaction was
about to commit, and the commits would then update zero rows -- a silent, total loss of the bill.
"""


def reservation_commit_statements(
    work_id: int,
    *,
    decision_id: str,
    attempt: int,
    actual: Mapping[str, int],
) -> tuple[Statement, ...]:
    """The `reservation_commit` participant's statements: one commit per dimension, then the sweep.

    `actual` maps `dim` to what was really spent, and the reservation id is **re-derived** rather
    than carried: `reservation_id(work_id, decision_id, attempt, dim)` is content-addressed over
    exactly the four values this function already has (08:2238), so the committer needs no handle on
    the row it is committing and a crash between reserve and commit costs nothing to recover from.

    Committing at the actual amount is what releases the over-reservation. 05:2537: *"on commit, the
    gap between `reserved_micros` and the `route_spend` row's actual `micros` is released **in the
    same transaction**, which can lift the very denial that just fired."* Headroom is
    `limit - held - committed`, so lowering a committed row's `amount` **is** the release; there is
    no separate statement for the gap, and there must not be one.

    One `Statement` per dimension rather than one `executemany`, for the reason `dep_statements()`
    gives: a plan is a boundary enumeration, and a crash between dimension 2 and dimension 3 is a
    boundary the crash matrix must be able to name.
    """
    if attempt < 1:
        raise StoreError(
            f"attempt is {attempt}; a reservation id is derived from a 1-based attempt",
            fix="pass the attempt the reservation was made under",
        )
    if not decision_id:
        raise StoreError(
            f"work row {work_id} has no decision_id, so it holds no reservation: "
            f"budget_reservation.decision_id is NOT NULL and an op.* row's is NULL by CHECK",
            fix="give SqliteStore no reservation_commit contribution for an op.* row (08:2302)",
        )
    out = [
        Statement(
            participant="reservation_commit",
            name=f"reservation_commit[{dim}]",
            sql=COMMIT_SQL,
            params=MappingProxyType(
                {
                    "reservation_id": reservation_id(work_id, decision_id, attempt, dim),
                    "amount": amount,
                }
            ),
        )
        for dim, amount in actual.items()
    ]
    out.append(
        Statement(
            participant="reservation_commit",
            name="reservation_release_remaining",
            sql=RELEASE_REMAINING_SQL,
            params=MappingProxyType({"work_id": work_id}),
        )
    )
    return tuple(out)


def reservation_commit(decision_id: str, attempt: int, actual: Mapping[str, int]) -> Contribution:
    """A `reservation_commit` `Contribution` bound to one decision, attempt and spend vector.

    `SqliteStore`'s four participants are constructor arguments and take `(row_id, result_view)`,
    which is the narrow signature two definition sites print for `complete()`. The three values a
    commit needs beyond the work id are not on that signature and must not be added to it, so they
    are closed over here -- the same device `crashmatrix._contribution()` uses for `dep_rows`.

    The returned callable ignores its `StepResultView`: the physical spend it commits is the priced
    and measured vector the runner assembled, and `StepMetrics.spend` is a `SpendVector` whose home
    is `omniweave.route` (INV-15). Reading the amount off the view would make this module price.
    """

    def contribute(row_id: int, _result: StepResultView) -> Sequence[Statement]:
        return reservation_commit_statements(
            row_id, decision_id=decision_id, attempt=attempt, actual=actual
        )

    return contribute


class SqliteBudgetLedger:
    """`BudgetLedger`'s four methods over one `StoreThread`. Structural: no inheritance edge.

    Satisfies `omniweave_core.budget.BudgetLedger`, which is a `Protocol` with `runtime_checkable`
    deliberately off -- nothing `isinstance`-checks this class and the conformance is asserted
    against the printed method list instead, the same arrangement `Store`/`SqliteStore` has.

    **Every call reaches the database as a `Unit` on the store thread**, so INV-17 holds by
    construction: `sqlite.py` never exports a cursor and there is no second route to one from here.
    `headroom()` is a read and still pays for a `BEGIN IMMEDIATE`, for the reason
    `SqliteStore.counts_by_status()` does: the queue boundary's reads are the Supervisor's, made
    in a loop it already serialises, and `Reader.snapshot()`'s `BEGIN DEFERRED` is the read path.

    **Synchronous, and that is what keeps `RunContext` in core** (08:315-317): headroom is computed
    *"in SQL on a synchronous connection, never awaited and never cached in an attribute"*.
    """

    __slots__ = ("_thread", "_wait_ms")

    def __init__(self, thread: StoreThread, *, wait_ms: int = INTERACTIVE_WAIT_MS) -> None:
        self._thread = thread
        self._wait_ms = wait_ms

    # -- headroom ------------------------------------------------------------------------------

    def headroom(self, dim: str, scope: str, scope_key: str, limit: int) -> int:
        """`limit - sum(held) - sum(committed)`, in SQL, on every call. I29.

        There is no memo and no attribute. A cached figure is wrong the moment another process
        reserves, and this ledger's job is to be right *across* processes: the held sum for
        `(dim='calls', scope='provider')` **is** the cross-process in-flight count (08:2196).

        `UNCAPPED` is refused rather than bound: `:limit` is an integer in the statement, and a
        sentinel that flowed into the SQL would make headroom read `-1 - held - committed` and deny
        everything. A dimension with no declared cap has no headroom question to answer.
        """
        if limit == UNCAPPED:
            raise StoreError(
                f"{dim!r} at {scope!r} has no declared cap, so it has no headroom; UNCAPPED is a "
                f"sentinel and never a limit to bind",
                fix="ask headroom only for a dimension the policy declares a limit for",
            )
        if limit < 0:
            raise StoreError(
                f"a limit of {limit} for {dim!r} is not a cap",
                fix="pass a limit >= 0; bytes_egress defaults to 0 and 0 is a real cap",
            )
        params = {"limit": limit, "dim": dim, "scope": scope, "key": scope_key}

        def run(connection: sqlite3.Connection) -> object:
            row = connection.execute(HEADROOM_SQL, params).fetchone()
            return int(row[0])

        value = self._thread.run(
            Unit(name="budget.headroom", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if not isinstance(value, int):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError("the headroom unit returned no integer", fix="report this as a bug")
        return value

    # -- reserve -------------------------------------------------------------------------------

    def reserve(self, reservations: Sequence[Reservation], limits: Mapping[str, int]) -> str | None:
        """Check every dimension, then insert every dimension. `None`, or the first exhausted `dim`.

        **Two passes in one transaction, and the order is the point.** 05:2527 step 5 is *"the first
        dimension whose headroom is below the request -> `Deferred(dim)`"*, and a loop that inserted
        as it checked would leave a partial reservation behind when the fourth dimension denied:
        three rows holding headroom for work that will never run, unreachable by the reaper the
        moment the work row settles (see `RELEASE_REMAINING_SQL`). Checking all of them first makes
        the denial total.

        One `BEGIN IMMEDIATE` around both passes is what makes the answer true when it is returned.
        Between a check on a separate connection and an insert, another process can reserve the
        headroom this one just measured -- which is the overdraw a durable ledger exists to prevent,
        and *"a durable overdraw is a bill"* (05:2541).

        A dimension absent from `limits` is `UNCAPPED`: its row is still inserted, so the held sum
        is already correct on the day a cap is declared for it.
        """
        if not reservations:
            raise StoreError(
                "reserve() was given no reservations; an admission that reserves nothing is not "
                "an admission",
                fix="pass one Reservation per dimension the decision is capped on",
            )
        rows = tuple(reservations)

        def run(connection: sqlite3.Connection) -> object:
            for row in rows:
                limit = limits.get(row.dim, UNCAPPED)
                if limit == UNCAPPED:
                    continue
                params = {
                    "limit": limit,
                    "dim": row.dim,
                    "scope": row.scope,
                    "key": row.scope_key,
                }
                available = int(connection.execute(HEADROOM_SQL, params).fetchone()[0])
                if available < row.amount:
                    return row.dim
            for row in rows:
                connection.execute(RESERVE_SQL, dict(row.as_params()))
            return None

        denied = self._thread.run(
            Unit(name="budget.reserve", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if denied is not None and not isinstance(denied, str):  # pragma: no cover
            raise StoreError("the reserve unit returned no dim", fix="report this as a bug")
        return denied

    # -- commit and release --------------------------------------------------------------------

    def commit(self, reservation_id_: str, amount: int) -> bool:
        """Held -> committed at the ACTUAL amount, in a transaction of its own.

        **The runner does not call this.** I20 puts the commit in `complete()`'s transaction and
        `reservation_commit()` above is that path. This one exists because 02 row 19 names four
        calls and a caller outside a `complete()` -- a repair path, a test -- needs one; it submits
        the identical `COMMIT_SQL`, so the `AND state='held'` predicate has one home.

        `False` means the row was not `held`: already committed, already released, or never
        inserted. A boolean rather than a raise, because all three are outcomes the caller can act
        on and none is a bug in the caller.
        """
        return self._update(
            COMMIT_SQL, {"reservation_id": reservation_id_, "amount": amount}, name="budget.commit"
        )

    def release(self, reservation_id_: str) -> bool:
        """Held -> released. A cancel, or a cache hit (I25). `False` if the row was not `held`."""
        return self._update(RELEASE_SQL, {"reservation_id": reservation_id_}, name="budget.release")

    def _update(self, sql: str, params: Mapping[str, object], *, name: str) -> bool:
        """One `UPDATE`, and the answer is its `rowcount`. Both callers are state transitions."""

        def run(connection: sqlite3.Connection) -> object:
            return connection.execute(sql, dict(params)).rowcount == 1

        moved = self._thread.run(Unit(name=name, run=run, cost_class="free", wait_ms=self._wait_ms))
        if not isinstance(moved, bool):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError(f"the {name} unit returned no boolean", fix="report this as a bug")
        return moved
