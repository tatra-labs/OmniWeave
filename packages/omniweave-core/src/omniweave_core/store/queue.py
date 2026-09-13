"""The QUEUE boundary's SQLite implementation: `Store`'s four methods, and the one transaction.

Implements 07-store-and-retrieval.md section 1.1 (:56-60), which prints the four signatures, and
section 10.1-10.2 (:2716-2743), which fixes the write model, the "together or not at all" sentence
and ST14. The `Outcome` -> row transition it writes is 08-runtime.md section 1.2 (:94-131) -- *"This
table is the specification; a reviewer may reject any `Store.complete()` change that alters a cell
without amending it"* (08:91-92) -- and the claim statement is charter.md:4083-4102, the only place
the batch-coherent claim is printed as SQL.

## What left with P4 W4.1

`WorkRow`, `WORK_STATUSES`, `WORK_COLUMNS`, `OUTCOMES`, `Transition`, `TRANSITIONS`,
`DECREMENTING` and all seven statements were written here at P2 and now live in
`omniweave_core.work`, which 02-architecture.md:246 makes the home of *"`WorkRow`, `FailureClass`
re-export, `classify()`, the claim/complete/reap SQL, the retry ladder"*. `MAX_WORK_ATTEMPTS` went
one step further, to `omniweave_core.limits`, which is the home of every `MAX_*` ceiling -- this
file's own docstring recorded that as an owed edit and named it.

**A move and not a re-export.** This module imports what it submits; it re-exports nothing, so
`from omniweave_core.store.queue import CLAIM_SQL` now fails, which is the point. A type with two
importable homes is the failure INV-21 names, and the cheapest moment to make the ownership
question unanswerable is the moment the second home is created.

What stayed is what the STORE owns rather than what the work vocabulary owns: `SqliteStore`,
`COMPLETE_PARTICIPANTS` and `Statement` (the shape of one transaction), `dep_statements` with
`DEP_KINDS`, and the two `*View` Protocols.

## What left with P4's `operator.py`

`StepMetrics` and `StepResult` were carried here at P2 under a docstring that named the day they
would go -- *"Deleted when `omniweave_core/operator.py` lands (P4). `StepMetricsView` is what
survives."* That module has landed and this is the deletion, which is what a carrier is for: the
class never became load-bearing anywhere, because everything in this file reads the two **Views**
and P4's real types satisfy them structurally with no edit on either side. `CACHE_KEY_HEX_LEN` went
with them -- it is `StepResult.__post_init__`'s only length rule and a constant belongs beside the
one invariant that reads it. `omniweave_core.store` imports `StepResult` from the runtime's
vocabulary now, so the `Store` Protocol's `complete()` names a type that resolves.

**Where this module lives, and why it is not a second home.** 16-roadmap.md:416 homes W2.3's whole
surface in `store/sqlite.py`. That file already holds every connection-and-thread mechanism the
plan gives it -- `connect`, the four pragma tuples, `StoreThread`, `Unit`, `snapshot`, the locks --
and this module adds no mechanism of its own: it holds the queue's SQL and the `Store` object that
submits it. One work item split across two files is a wave-level split; nothing here duplicates a
constant, a pragma or a transaction shape that `sqlite.py` owns, and everything here reaches the
database through `StoreThread.run(Unit(...))`. INV-17 is therefore intact by construction: this
module never calls `sqlite3.connect`, and the only `Connection` it ever touches is the one handed
to a `Unit`'s closure on the store thread.

## The narrow `Store`, and the ruling this module implements

`store/__init__.py`'s `Store` docstring records the finding in full and it is not restated here:
07:56-60 and charter.md:3393-3397 print a four-parameter `claim` and a three-parameter `complete`;
08-runtime.md:2478-2485 prints a wider pair. Two definition sites against one, the charter is
settled law, and 08's extra parameters are typed `CostClass`, `Dep` and `DerivedRows` -- P4 types
that do not exist at 16-roadmap.md:428's P2 freeze. **The narrow form is what ships**, and two
consequences of that choice are mechanisms in this file rather than opinions:

1. **`claim()` takes no `cost_class`, so the claim SQL carries no `cost_class` clause.** Batch
   coherence comes from `dispatch_key` alone, which is what the charter's `head` CTE selects on
   anyway. That is not a widening of what a batch may contain: `dispatch_key` is
   `sha256(driver||config_digest||isolation)[:16]` and `cost_class` is derived by the planner from
   the same resolved `Candidate` (0004_runtime.sql:96-105), so one `dispatch_key` is one
   `cost_class` by construction. `[runtime.claim] batch` per class (08:2578) is then a caller's
   choice of `batch`, which is exactly the parameter the narrow signature does carry.
2. **`complete()` takes no `cost_class` either, and ST14 needs one before `BEGIN`.** So the store
   reads it: `COST_CLASS_SQL` runs in its own short unit, and only then is the durable unit
   submitted. 07:2736 is unambiguous that `synchronous = FULL` is set *before* `BEGIN`, and
   `sqlite.py`'s `_transact` reads `Unit.durable` before it issues either statement, so there is no
   way to learn the class inside the transaction and still honour ST14.

## `complete()` is one transaction with five participants

07:2730-2733: *"`Store.complete()` is the only mutation entry point on the queue boundary, and one
unit's derived rows, its `work` transition, its `dep` rows, its reservation commit and its spend row
commit **together or not at all**."* 02-architecture.md:487 prints the same five in the same order.
`COMPLETE_PARTICIPANTS` transcribes them, and `SqliteStore.complete_plan()` returns the statements
each contributes, in that order, so a participant is a slot rather than a rewrite.

**Four of the five have no producer at P2, and this is which, why, and whose:**

* `derived_rows` -- **empty.** L2 rows are written by `DocSink`, and `end_page()` commits its own
  transaction (03:594) -- a shape the narrow `complete()` cannot reach into. 08's
  `rows: "DerivedRows"` is the channel that would. **P4**, and `DerivedRows` is 08-runtime.md's.
* `work_transition` -- **the one statement that ships.** 08:113-125, plus `cache_key` from 02:487.
  **Here.**
* `dep_rows` -- **empty at P2**, but the refusals were not: `dep_statements()` shipped with
  `MAX_DEPS_PER_UNIT` and the closed `kind` domain enforced, because 08:2491 makes both a raise.
  The producer arrived at **P4 W4.6** as `omniweave_core.deps` -- 02-architecture.md:244 homes
  `Dep`, `DepKind` and `record_deps` there, not in `omniweave_core.work`, which is why `DEP_KINDS`
  did not travel with the work vocabulary at W4.1 and does now.
  `omniweave_core.store.deps.dep_rows()` is the `Contribution` that binds the two.
* `reservation_commit` -- **empty.** `budget_reservation.decision_id` is
  `NOT NULL REFERENCES route_decision`, and no P2 code writes a `route_decision` row. **P4**;
  05-ingest-and-routing.md section 6.4.
* `spend_row` -- **empty**, same foreign key, plus `Spend` itself is P4's (05:2370). **P4**;
  `route_spend`.

So `complete_plan()` returns exactly one statement at P2 and the transaction has three boundaries.
That is reported rather than padded: W2.9's *"every statement boundary in `Store.complete()`"*
(16:422, "~40") is the count of a fully-populated plan, and `complete_boundaries()` is the API that
answers it for whatever the plan actually holds -- so the crash matrix enumerates boundaries by
calling this module, never by parsing its source.

## The one boolean, and every other refusal

08:2486-2496: `complete()` *"returns `False` for exactly one condition -- superseded -- and
**raises** for every other refusal ... because a boolean that means both 'someone else won' and
'your driver is wrong' turns a bug into a no-op."* Superseded is measured by the commit predicate
`WHERE id = :id AND claimed_gen = :gen AND status = 'claimed'` (charter.md:4104, 02:487) matching
**zero rows**, and 08:2841 says what `gen` is compared against in as many words: `WorkRow`
*"carrying `claimed_gen` -- which is what the commit predicate compares, and therefore what makes a
superseded result write nothing."* The `gen` a caller passes to `complete()` is the `gen` it passed
to `claim()`, which the claim wrote into `work.claimed_gen`; a reap, another worker's claim or a new
generation all move that column, and all three read as superseded.

Zero rows rolls the WHOLE transaction back (charter.md:4105), which is why supersession is signalled
out of the closure by raising `_Superseded` -- `sqlite.py`'s `_transact` rolls back on any raise --
and turned into `False` outside it. Every other refusal is an ordinary `OwError` and reaches the
caller unchanged.

## Stdlib only (INV-2 / G1), and one of the nine lazy names

`import sqlite3` is legal here because this file is under `store/`, where pyproject.toml's
per-file-ignore covers TID251 (INV-17). Nothing in this module connects: the import is for
`sqlite3.Connection` in the signatures of the closures a `Unit` runs. `unixepoch('subsec')` is SQL
and not a Python clock read -- charter.md:4090 marks it *"THE STORE'S CLOCK, never a worker's"*, and
it is the reason `claim()` needs no `now_ms` while `reap_expired_leases(now_ms)` has one (07:57-59
prints both signatures that way).

Tier T-SCHEMA: 02-architecture.md section 2 row 26.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

from omniweave_core.deps import DEP_KINDS as _DEP_KINDS
from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.limits import MAX_DEPS_PER_UNIT
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit
from omniweave_core.work import (
    CLAIM_SQL,
    COMPLETE_SQL,
    COST_CLASS_SQL,
    COUNTS_SQL,
    OUTCOMES,
    REAP_RESERVATIONS_SQL,
    REAP_SQL,
    TRANSITIONS,
    WORK_STATUSES,
    WorkRow,
)

__all__ = [
    "COMPLETE_PARTICIPANTS",
    "DEP_KINDS",
    "SqliteStore",
    "Statement",
    "StepMetricsView",
    "StepResultView",
    "complete_boundaries",
    "dep_statements",
]


# --------------------------------------------------------------------------------------------
# 1. What the STORE owns of the closed domains. The rest is `omniweave_core.work`'s.
# --------------------------------------------------------------------------------------------

#: `dep.kind`'s CHECK (0004_runtime.sql:186), re-exported from its home in `omniweave_core.deps`.
#:
#: It was declared here at W4.1 with a note saying where it belonged and why it had not moved yet:
#: *"02-architecture.md:244 homes `Dep`, `DepKind` and `record_deps` there, not in
#: `omniweave_core.work`."* W4.6 built that module, so the tuple moved and this name is now an
#: alias -- kept because `dep_statements()` is the enforcement site and a reader of the refusal
#: should find the domain in the file that raises.
#:
#: Enforced in Python as well as by the CHECK because 08:2489-2496 requires the refusal to be a
#: RAISE that names the offence: a CHECK violation surfaces as `sqlite3.IntegrityError("CHECK
#: constraint failed: dep")`, which does not say which kind, which key or which unit, and it
#: arrives after the derived rows of the same transaction have already been written.
DEP_KINDS: Final = _DEP_KINDS

COMPLETE_PARTICIPANTS: Final = (
    "derived_rows",
    "work_transition",
    "dep_rows",
    "reservation_commit",
    "spend_row",
)
"""The five things one `complete()` commits together or not at all, in printed order.

07:2730-2733 and 02-architecture.md:487 print the same five in the same order, which is why the
order is transcribed rather than chosen. The module docstring's table says which are empty at P2 and
who fills each.

**The order costs one thing and the plan pays it knowingly.** `work_transition` is second, so a
superseded result has already written its derived rows by the time the commit predicate matches zero
rows -- and then the whole transaction rolls them back (charter.md:4105). Putting the transition
first would detect supersession before doing that work, and it is not what two definition sites
print; since the outcome is identical and the cost is a rollback of work already done, the printed
order wins.
"""


# --------------------------------------------------------------------------------------------
# 2. What `complete()` reads off a `StepResult`. The type itself is `operator.py`'s.
# --------------------------------------------------------------------------------------------


class StepMetricsView(Protocol):
    """The `StepMetrics` fields the `work` transition writes. Structural, never imported.

    08:200-207 prints seven fields; `spend` is the one this module never reads, because the physical
    `Spend` is the `spend_row` participant's and `route_spend` has no P2 producer (see the module
    docstring's table). A Protocol listing only what is read is what lets P4's real `StepMetrics`
    satisfy this with no edit on either side -- the same reason `model/rebind.py` declares
    `RebindReadSide` instead of taking `store.Reader`.

    **Read-only members, and that is what makes the structural claim true.** A Protocol attribute
    written as `queued_ms: int` is *mutable*, and a mutable member is invariant: a frozen dataclass
    does not satisfy it, and a field narrower than the declared type does not either. Declaring each
    member as a property makes it read-only and therefore covariant, which is the whole point of a
    type whose name ends in `View` -- `complete()` reads these and writes none of them. The
    alternative was a Protocol that only a mutable class could satisfy, which is the opposite of
    what a read surface is for.
    """

    @property
    def queued_ms(self) -> int: ...

    @property
    def ran_ms(self) -> int: ...

    @property
    def micros(self) -> int: ...

    @property
    def was_cache_hit(self) -> bool: ...

    @property
    def rows_written(self) -> int: ...

    @property
    def peak_rss_bytes(self) -> int: ...


class StepResultView(Protocol):
    """What `complete()` reads off a `StepResult`. Six attributes, and the boundary's real input.

    `Store.complete(row_id, gen, result)` is typed against `"StepResult"` (07:58), whose home is
    `omniweave_core.operator` (08:187, 18-api-sketch.md:844) at P4. This Protocol is that type's
    read surface, so the P4 class satisfies it structurally and `store/` never grows an import edge
    into the runtime's vocabulary. `outcome` is typed `str` and not an enum for the reason
    `OUTCOMES` argues; a `StrEnum` member is a `str`, so 08's `Outcome` fits.

    **`failure_message` EXTENDS the charter, and the extension is a column with no printed
    producer.** `work.failure_message` is a real column (0004_runtime.sql:107, charter.md:4040) and
    08:113-125's own UPDATE binds `:failure_message` -- but 08:209-231's `StepResult` has no such
    field. The message lives on `Failure`, which `classify()` returns (08:537-539) and which
    `StepResult` does not carry; 08:565 relies on it existing (*"the message names the deadline the
    driver was working to"*), and 08:583 on it naming *"which knob would need raising"*. A column
    the plan's own statement writes must have a channel, so the read surface declares one and the
    defect is reported as **D138**. `omniweave_core.operator.StepResult` carries the concrete
    field, optional, and `None` writes NULL.

    Read-only members, for the reason `StepMetricsView` records -- and here it is load-bearing
    twice. `StepResult` is frozen, and its `outcome` is an `Outcome` where this says `str`: a
    mutable `outcome: str` would be invariant, so the narrower `StrEnum` would not satisfy it and
    the carrier's deletion would have cost this seam the property it exists for.
    """

    @property
    def outcome(self) -> str: ...

    @property
    def cache_key(self) -> str: ...

    @property
    def failure_class(self) -> str | None: ...

    @property
    def failure_message(self) -> str | None: ...

    @property
    def retry_after_ms(self) -> int | None: ...

    @property
    def metrics(self) -> StepMetricsView: ...


# --------------------------------------------------------------------------------------------
# 3. `Statement` -- the unit of a `complete()` plan, and therefore of a crash boundary.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Statement:
    """One SQL statement inside one transaction, tagged with the participant that contributed it.

    `complete()` executes a `tuple[Statement, ...]` in order, so the statements ARE the transaction
    and the gaps between them ARE the crash boundaries. 16-roadmap.md:422 gives W2.9 *"every
    statement boundary in `Store.complete()`"*, and a crash matrix that had to find those by parsing
    this module's source would break on any edit to it. `SqliteStore.complete_plan()` plus
    `complete_boundaries()` answer the question directly instead.

    `params` is a mapping and never a positional sequence, because a plan is inspected as well as
    executed and `{"id": 4}` is legible where `(4,)` is not.
    """

    participant: str
    name: str
    sql: str
    params: Mapping[str, object]


def complete_boundaries(plan: Sequence[Statement]) -> tuple[str, ...]:
    """The crash boundaries of a `complete()` plan, in order: `len(plan) + 2` of them.

    A boundary is a point at which the process may be SIGKILLed and the store must be found
    consistent. There is one after `BEGIN IMMEDIATE`, one after each statement, and one after
    `COMMIT` -- so a plan of N statements has N + 2. Every boundary before the last must leave the
    store exactly as it was, and the last must leave every participant's rows present; that is the
    whole of the assertion W2.9 makes, and this function is the enumeration it makes it over.

    The read that precedes the transaction (`COST_CLASS_SQL`, ST14's requirement -- see the module
    docstring) is deliberately NOT a boundary here: it runs in its own unit, writes nothing, and a
    crash across it is indistinguishable from a crash before `complete()` was called.
    """
    return ("after:begin", *(f"after:{s.participant}/{s.name}" for s in plan), "after:commit")


Contribution = Callable[[int, StepResultView], Sequence[Statement]]
"""What a participant contributes to one `complete()` plan: statements, given the row id and result.

Four of the five participants take one of these and default to contributing nothing (see
`SqliteStore.__init__`). It is a constructor seam and NOT a widening of the boundary: `complete()`
still takes `(row_id, gen, result)` and nothing else, which is the frozen signature (07:58,
charter.md:3395). P4 supplies contributions when it has rows to write.
"""


# --------------------------------------------------------------------------------------------
# 4. `dep` rows -- empty at P2, but the refusals ship now.
# --------------------------------------------------------------------------------------------


def dep_statements(
    dependent_id: int,
    deps: Sequence[tuple[str, str, str]],
    *,
    allowed_keys: frozenset[str] | None = None,
) -> tuple[Statement, ...]:
    """The `dep_rows` participant's statements, one per dep, with both of 08:2491's refusals.

    Each dep is `(kind, key, digest)` -- `dep`'s three non-key columns (0004_runtime.sql:184-191),
    two of them and not three by the ruling that file records at :192-195. `dependent_id` is the
    `work.id` the dep hangs off, `ON DELETE CASCADE`.

    **Two raises, and 08:2491 names both as raises rather than as a `False`:** *"`MAX_DEPS_PER_UNIT`
    exceeded, a `dep` key outside the invocation's input set, a `cache.put` allowlist violation."*

    * Above `MAX_DEPS_PER_UNIT` this raises `ResourceLimit`, which is the one error class required
      to name a knob -- `[runtime] max_deps_per_unit`. limits.py's own docstring for the ceiling
      says where the raise belongs: *"Enforced in `Store.complete()`, which **raises**"*, and
      *"past it the operator MUST declare a cohort dep -- coarser, always safe, over-invalidating on
      purpose"* (0004_runtime.sql:200-202), which is what the fix names.
    * `allowed_keys`, when given, is the invocation's input set, and a key outside it raises
      `StoreError`. It is optional because the narrow `complete()` has no channel for it; a caller
      that knows the set passes it and gets the check, and one that does not gets the `kind` domain
      check and the cap regardless.

    `INSERT OR IGNORE`, because `dep`'s `PRIMARY KEY (dependent_id, kind, key)` is the UNIQUE index
    it conflicts on -- idempotency mechanism 2 of 08:428, whose warning is that *"`INSERT OR IGNORE`
    with no UNIQUE index to conflict on is a plain `INSERT`"*. Here there is one.

    One `Statement` per dep rather than one `executemany`, because a plan is a boundary enumeration:
    a crash between dep 3 and dep 4 is a boundary W2.9 must be able to name.
    """
    if len(deps) > MAX_DEPS_PER_UNIT:
        raise ResourceLimit(
            f"work row {dependent_id} declared {len(deps)} deps and MAX_DEPS_PER_UNIT is "
            f"{MAX_DEPS_PER_UNIT}",
            limit="[runtime] max_deps_per_unit",
            fix="declare a cohort dep instead: coarser, always safe, over-invalidating on purpose",
        )
    out: list[Statement] = []
    for index, (kind, key, digest) in enumerate(deps):
        if kind not in DEP_KINDS:
            raise StoreError(
                f"dep kind {kind!r} on work row {dependent_id} is outside {DEP_KINDS}",
                fix="use one of the six dep kinds the dep CHECK declares",
            )
        if allowed_keys is not None and key not in allowed_keys:
            raise StoreError(
                f"dep key {key!r} on work row {dependent_id} is outside the invocation's "
                f"input set of {len(allowed_keys)} keys",
                fix="record a dep only on an input the invocation actually read",
            )
        out.append(
            Statement(
                participant="dep_rows",
                name=f"dep_insert[{index}]",
                sql=(
                    "INSERT OR IGNORE INTO dep(dependent_id, kind, key, digest) "
                    "VALUES(:dependent_id, :kind, :key, :digest)"
                ),
                params=MappingProxyType(
                    {
                        "dependent_id": dependent_id,
                        "kind": kind,
                        "key": key,
                        "digest": digest,
                    }
                ),
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------------------------
# 5. `Store` -- the four methods.
# --------------------------------------------------------------------------------------------


class _Superseded(Exception):  # noqa: N818 -- an internal signal, never seen by a caller.
    """Raised inside a `complete()` closure to roll the transaction back and return `False`.

    charter.md:4105: *"ZERO ROWS => SUPERSEDED => THE WHOLE TRANSACTION ROLLS BACK."* A closure that
    returned `False` would leave whatever the earlier participants wrote committed, so the rollback
    has to be a raise -- `sqlite.py`'s `_transact` rolls back on any exception -- and `complete()`
    catches exactly this one class. Every other exception passes straight through, which is
    08:2489's rule: `False` means superseded and nothing else.

    Not an `OwError`, because it never reaches a caller and an `OwError` requires a `fix` command
    for an operator who will never see it.
    """


class SqliteStore:
    """`Store`'s four methods over one `StoreThread`. Structural: no inheritance edge (18:1779).

    Satisfies `omniweave_core.store.Store` -- four methods, never widened. `Store` is a `Protocol`
    with `@runtime_checkable` deliberately off, so nothing `isinstance`-checks this class and the
    conformance is asserted against the printed signatures instead.

    **Every one of the four reaches the database as a `Unit` on the store thread**, including
    `counts_by_status()`. INV-17 makes the store thread *"the only holder of a `Connection` in a
    process"* (07:2722), so there is no second route to a cursor from here; `sqlite.py` never
    exports one. The cost of that for the one read among the four is a `BEGIN IMMEDIATE` around a
    `GROUP BY`, which takes the write lock for the duration of one aggregate over a partial index.
    `Reader.snapshot()`'s `BEGIN DEFERRED` is the read path proper (ST2), and `counts_by_status` is
    on `Store` and not on `Reader` -- the queue boundary, whose four calls a supervisor makes in a
    loop it already serialises.

    **Enqueue before attempting the lock** (07:2730) is `StoreThread.submit`'s and is inherited
    rather than re-implemented: `run()` queues the unit and the store thread takes `store.write`
    when it dequeues, at that unit's own `wait_ms`. `wait_ms` is a constructor parameter for the
    same reason 07:2726-2729 makes it a per-call argument -- an interactive `ow add` pays
    `INTERACTIVE_WAIT_MS` and a watcher batch pays `BATCH_WAIT_MS`, and *"a lock timeout is a UX
    decision."*

    The four `Contribution` parameters are the P4 composition seam the module docstring's table
    describes. They are constructor arguments and not method arguments precisely so that
    `complete()`'s signature stays the three parameters two definition sites print.

    `on_commit` fires on the store thread inside `complete()`'s transaction, immediately before
    `COMMIT`. It is `Unit.on_commit` passed through, and `Unit`'s own docstring already names both
    of its jobs: it is *"the hook ST14's test uses"* -- 07:2737 asks for the pragma value **at
    commit time** -- and *"the hook the reservation-commit and spend-row writes of 07:2731-2733 will
    use when P4 lands, since those must land in the same transaction as the derived rows."* A hook
    that raises aborts the unit, which is the desired coupling.
    """

    __slots__ = ("_contributions", "_on_commit", "_thread", "_wait_ms")

    def __init__(
        self,
        thread: StoreThread,
        *,
        wait_ms: int = INTERACTIVE_WAIT_MS,
        derived_rows: Contribution | None = None,
        dep_rows: Contribution | None = None,
        reservation_commit: Contribution | None = None,
        spend_row: Contribution | None = None,
        on_commit: Callable[[sqlite3.Connection], None] | None = None,
    ) -> None:
        self._thread = thread
        self._wait_ms = wait_ms
        self._on_commit = on_commit
        self._contributions: Mapping[str, Contribution | None] = MappingProxyType(
            {
                "derived_rows": derived_rows,
                "work_transition": None,  # this module's; never a contribution.
                "dep_rows": dep_rows,
                "reservation_commit": reservation_commit,
                "spend_row": spend_row,
            }
        )

    # -- claim ---------------------------------------------------------------------------------

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]:
        """Claim up to `batch` rows of one `dispatch_key`, atomically. 07:57, charter.md:4083-4102.

        One statement in one transaction, and that is what makes two concurrent claimers safe. The
        UPDATE selects and writes in the same statement under `BEGIN IMMEDIATE`, so there is no
        window between "these are the rows" and "these are mine" for a second claimer to read; and
        the claimed rows come back from `RETURNING`, not from a following `SELECT` that would
        re-open exactly that window. *"THE CLAIM IS THE LEASE"* (charter.md:4105, I23): the same
        statement writes `claimed_by`, `claimed_gen` and `lease_expires`, so a claim with no lease
        does not exist.

        `gen` is the run's generation (`RunContext.generation`, *"a monotonic INTEGER, never a
        clock"*, 08:270) and lands in `work.claimed_gen`, which is what `complete()`'s commit
        predicate compares (08:2841).

        `worker` is `'<host>:<pid>:<process_create_time>'` (0004_runtime.sql:110), the identity
        whose third component *"stops a recycled pid from looking like a live holder"*
        (07:2724-2725). The store records it and does not parse it; `lease_reaper` reads it back.

        Returns the rows ordered by `(-priority, id)` -- the claim's own `ORDER BY`. `RETURNING`
        makes no ordering promise, and a batch handed to `dispatch` in storage order would make
        *"priority survives batching"* (08:625) untestable.

        Refuses rather than degrades on a nonsensical argument: a `batch` below one claims nothing
        while looking like it worked, and a `lease_ms` below one mints a lease already expired,
        which is a row the reaper takes back from a worker that is running it.
        """
        if batch < 1:
            raise StoreError(
                f"batch is {batch}; a claim of no rows is not a claim",
                fix="pass batch >= 1, e.g. [runtime.claim] batch.free = 256",
            )
        if lease_ms < 1:
            raise StoreError(
                f"lease_ms is {lease_ms}; the claim IS the lease, and a lease that has already "
                f"expired hands the row straight back to the reaper",
                fix="pass lease_ms >= 1, e.g. [runtime] lease_ms = 120000",
            )
        if not worker:
            raise StoreError(
                "worker is empty; a claim records WHO holds the lease",
                fix="pass '<host>:<pid>:<process_create_time>'",
            )
        params = {"worker": worker, "gen": gen, "lease_ms": lease_ms, "batch": batch}

        def run(connection: sqlite3.Connection) -> object:
            rows = connection.execute(CLAIM_SQL, params).fetchall()
            return tuple(WorkRow.from_row(row) for row in rows)

        claimed = self._thread.run(
            Unit(name="store.claim", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if not isinstance(claimed, tuple):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError("the claim unit returned no rows tuple", fix="report this as a bug")
        return sorted(claimed, key=lambda row: (-row.priority, row.id))

    # -- complete ------------------------------------------------------------------------------

    def complete_plan(self, row_id: int, result: StepResultView) -> tuple[Statement, ...]:
        """The statements one `complete()` executes, in `COMPLETE_PARTICIPANTS` order. PURE.

        No connection, no clock, no id minting -- so W2.9 can enumerate `complete()`'s crash
        boundaries by calling this and `complete_boundaries()`, without parsing this module and
        without a database. It is also where every participant's refusals fire, which is what makes
        them observable without a transaction: a plan that cannot be built is a `complete()` that
        raises before it writes anything at all.

        At P2 this returns exactly one statement, the `work` transition. The module docstring's
        table says which participants are empty and who fills each.

        `gen` is not bound here. A plan is a thing W2.9 enumerates for any row, and the generation
        is a property of one call; `complete()` binds it.
        """
        transition = TRANSITIONS.get(result.outcome)
        if transition is None:
            raise StoreError(
                f"outcome {result.outcome!r} is not one of the eight the transition table "
                f"specifies: {OUTCOMES}",
                fix="return one of the eight Outcome members from 08-runtime.md section 1.3",
            )
        metrics = result.metrics
        plan: list[Statement] = []
        for participant in COMPLETE_PARTICIPANTS:
            if participant == "work_transition":
                plan.append(
                    Statement(
                        participant=participant,
                        name="work_update",
                        sql=COMPLETE_SQL,
                        params=MappingProxyType(
                            {
                                "id": row_id,
                                "gen": None,
                                "status": transition.status,
                                "outcome": result.outcome,
                                "cache_key": result.cache_key,
                                "retry_after_ms": result.retry_after_ms,
                                "micros": metrics.micros if transition.adds_micros else 0,
                                "queued_ms": metrics.queued_ms,
                                "ran_ms": metrics.ran_ms,
                                "peak_rss_bytes": metrics.peak_rss_bytes,
                                "failure_class": result.failure_class,
                                "failure_message": result.failure_message,
                            }
                        ),
                    )
                )
                continue
            contribute = self._contributions[participant]
            if contribute is not None:
                plan.extend(contribute(row_id, result))
        return tuple(plan)

    def complete(self, row_id: int, gen: int, result: StepResultView) -> bool:
        """One transaction, five participants, `False` only for superseded. 07:58, 07:2730-2733.

        `False` means the commit predicate `WHERE id = :id AND claimed_gen = :gen AND status =
        'claimed'` matched zero rows, and nothing else. 08:2486-2496: *"returns `False` for exactly
        one condition -- superseded -- and **raises** for every other refusal ... because a boolean
        that means both 'someone else won' and 'your driver is wrong' turns a bug into a no-op."*
        Three things move `claimed_gen` or `status` out from under a caller and all three are
        supersession: another worker's claim, a lease reap, and a newer generation completing the
        same row. Zero rows rolls the whole transaction back (charter.md:4105), which is why the
        signal out of the closure is a raise.

        Every other refusal is an `OwError`: an `outcome` outside the eight, a `dep` kind outside
        `DEP_KINDS`, a dep key outside the invocation's input set, more than `MAX_DEPS_PER_UNIT`
        deps, and a `row_id` that names no `work` row at all. The last is worth naming: the
        charter's comment collapses it into superseded (*"ZERO ROWS => SUPERSEDED"*), but a comment
        is not a definition site and 08:2489's prose is, so a completion for a row that does not
        exist is a driver being wrong and raises. It is detected by `COST_CLASS_SQL`, which has to
        run anyway.

        **Two units, and ST14 is why.** The first reads `work.cost_class`; the second is the
        transaction, durable exactly when that class is in `DURABLE_COST_CLASSES`. `synchronous =
        FULL` must be set *before* `BEGIN` (07:2736), and `Unit.durable` is read before either
        statement, so the class cannot be learned inside the transaction -- and the narrow
        `complete()` does not carry it. Between the two units the row may move; the commit predicate
        catches that and the answer is `False`.
        """
        plan = self.complete_plan(row_id, result)
        cost_class = self._cost_class(row_id)
        bound = tuple(
            Statement(
                participant=statement.participant,
                name=statement.name,
                sql=statement.sql,
                params=(
                    MappingProxyType({**statement.params, "gen": gen})
                    if "gen" in statement.params
                    else statement.params
                ),
            )
            for statement in plan
        )

        def run(connection: sqlite3.Connection) -> object:
            for statement in bound:
                cursor = connection.execute(statement.sql, dict(statement.params))
                if statement.participant == "work_transition" and cursor.rowcount == 0:
                    raise _Superseded(row_id)
            return True

        unit = Unit(
            name="store.complete",
            run=run,
            cost_class=cost_class,
            wait_ms=self._wait_ms,
            on_commit=self._on_commit,
        )
        try:
            self._thread.run(unit)
        except _Superseded:
            return False
        return True

    def _cost_class(self, row_id: int) -> str:
        """`work.cost_class` for `row_id`, or a raise. ST14's read; see `COST_CLASS_SQL`."""

        def run(connection: sqlite3.Connection) -> object:
            return connection.execute(COST_CLASS_SQL, {"id": row_id}).fetchone()

        row = self._thread.run(
            Unit(
                name="store.complete.cost_class",
                run=run,
                cost_class="free",
                wait_ms=self._wait_ms,
            )
        )
        if row is None:
            raise StoreError(
                f"work row {row_id} does not exist, so completing it is not a lost race: "
                f"a completion names a row the caller claimed",
                fix="complete only a row_id returned by Store.claim()",
            )
        return str(row[0])  # type: ignore[index]

    # -- reap ----------------------------------------------------------------------------------

    def reap_expired_leases(self, now_ms: int) -> int:
        """Return every expired claim to `pending`, decremented, releasing its reservations. 07:59.

        Two statements in one transaction, reservations first -- `REAP_RESERVATIONS_SQL` argues the
        order, and I29 is why they share a transaction at all. Returns the number of `work` rows
        reaped, which is the count an operator and `ow queue status` read.

        **A reaped row returns to the queue rather than failing** (08:2411, 08:462-470), with
        `attempts_total` and `attempts_today` decremented and floored at zero, because *"a power cut
        is not an attempt"* (08:121-122). Nothing about a reap says the work is bad.

        `now_ms` is INJECTED and not read here, and the injection is the whole reason the signature
        has a parameter: `time.time` is semgrep-banned in library code (02:392, 08:281-283) and
        *"`Clock` is injected, which is what makes the debounce and generation invariants testable
        without an operating system."* The asymmetry with `claim()`, which reads
        `unixepoch('subsec')` inside SQL, is the plan's own: charter.md:4090 marks the claim's clock
        as *"THE STORE'S CLOCK, never a worker's"* because the lease it mints must be comparable
        across processes, while the reaper is a single sweep whose `now` its caller already holds.

        Holder liveness and the one lease extension are 08:462-470's `lease_reaper`, not this
        method's; `REAP_SQL`'s docstring records the boundary and who owns it.
        """
        params = {"now_ms": now_ms}

        def run(connection: sqlite3.Connection) -> object:
            connection.execute(REAP_RESERVATIONS_SQL, params)
            return connection.execute(REAP_SQL, params).rowcount

        reaped = self._thread.run(
            Unit(name="store.reap", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        return int(reaped)  # type: ignore[arg-type]

    # -- counts --------------------------------------------------------------------------------

    def counts_by_status(self) -> Mapping[str, int]:
        """`work` rows per status, from ONE query. 07:60, 0004_runtime.sql:137.

        Total over `WORK_STATUSES`: every one of the six is a key, zero where the `GROUP BY`
        returned no row. A missing key and a zero are different answers to *"is anything failing"*,
        and only one of them is true. Filling the six costs no second query -- see `WORK_STATUSES`.

        A status the CHECK does not allow cannot appear, so an unexpected key is schema drift and
        raises rather than being merged in silently.
        """

        def run(connection: sqlite3.Connection) -> object:
            return connection.execute(COUNTS_SQL).fetchall()

        rows = self._thread.run(
            Unit(name="store.counts", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        counts = dict.fromkeys(WORK_STATUSES, 0)
        for status, count in rows:  # type: ignore[union-attr]
            if status not in counts:
                raise StoreError(
                    f"work.status holds {status!r}, which its CHECK does not allow: "
                    f"the schema and WORK_STATUSES have drifted",
                    fix="ow store repair",
                )
            counts[status] = int(count)
        return MappingProxyType(counts)
