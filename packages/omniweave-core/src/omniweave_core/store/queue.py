"""The QUEUE boundary's SQLite implementation: `Store`'s four methods, and the one transaction.

Implements 07-store-and-retrieval.md section 1.1 (:56-60), which prints the four signatures, and
section 10.1-10.2 (:2716-2743), which fixes the write model, the "together or not at all" sentence
and ST14. The `Outcome` -> row transition it writes is 08-runtime.md section 1.2 (:94-131) -- *"This
table is the specification; a reviewer may reject any `Store.complete()` change that alters a cell
without amending it"* (08:91-92) -- and the claim statement is charter.md:4083-4102, the only place
the batch-coherent claim is printed as SQL.

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
* `dep_rows` -- **empty**, but the refusals are not: `dep_statements()` ships with
  `MAX_DEPS_PER_UNIT` and the closed `kind` domain enforced, because 08:2491 makes both a raise.
  **P4 W4.1** (16:541), in `omniweave_core.work`.
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

from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.limits import MAX_DEPS_PER_UNIT
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

__all__ = [
    "CACHE_KEY_HEX_LEN",
    "COMPLETE_PARTICIPANTS",
    "COMPLETE_SQL",
    "COST_CLASS_SQL",
    "DECREMENTING",
    "DEP_KINDS",
    "MAX_WORK_ATTEMPTS",
    "OUTCOMES",
    "STORE_NOW_MS",
    "TRANSITIONS",
    "WORK_COLUMNS",
    "WORK_STATUSES",
    "SqliteStore",
    "Statement",
    "StepMetrics",
    "StepMetricsView",
    "StepResult",
    "StepResultView",
    "Transition",
    "WorkRow",
    "complete_boundaries",
    "dep_statements",
]


# --------------------------------------------------------------------------------------------
# 1. The closed domains, transcribed from the shipped DDL and from 08 section 1.2.
# --------------------------------------------------------------------------------------------

WORK_STATUSES: Final = (
    "pending",
    "claimed",
    "done",
    "failed_transient",
    "failed_permanent",
    "deferred",
)
"""`work.status`'s CHECK, verbatim and in its printed order (0004_runtime.sql:106-107).

08:85-87 states the omission that makes the list six rather than seven: *"There is no `cancelled`
status, which is deliberate -- a cancellation is not a state a row rests in."* `CANCELLED` maps to
`pending` in `TRANSITIONS`, which is the whole of that decision.

`counts_by_status()` uses it to make its mapping TOTAL. `GROUP BY status` returns only the statuses
present, and an operator reading "no `failed_permanent` key" cannot tell "none" from "the query did
not ask"; a zero is an answer and a missing key is not.
"""

WORK_COLUMNS: Final = (
    "id",
    "unit_uri",
    "unit_part",
    "operator",
    "op_version",
    "cache_key",
    "decision_id",
    "sequence_id",
    "driver",
    "cost_class",
    "dispatch_key",
    "service",
    "staged_gen",
    "status",
    "failure_class",
    "failure_message",
    "retry_after",
    "attempts_total",
    "attempts_today",
    "last_attempt_at",
    "stale_since",
    "claimed_by",
    "claimed_gen",
    "lease_expires",
    "cost_micros",
    "queued_ms",
    "ran_ms",
    "peak_rss_bytes",
    "priority",
)
"""Every column of `work`, in DDL order (0004_runtime.sql:90-131). `WorkRow`'s fields, in order.

**Named, not `RETURNING *`.** charter.md:4102 prints `RETURNING *`, and the star is what makes a
column order a property of `sqlite_master` rather than of this module: a later migration adding a
column to `work` would silently shift every positional unpack in `WorkRow.from_row`. Listing them
costs one tuple and makes that migration a failing test instead of a wrong row. 08:2528-2531 asks
for the same portability from the other side -- *"The `work` schema is deliberately portable"* --
and a named projection is the portable form.
"""

OUTCOMES: Final = (
    "ok",
    "ok_partial",
    "skipped_cached",
    "skipped_unchanged",
    "failed_transient",
    "failed_permanent",
    "deferred_budget",
    "cancelled",
)
"""The eight `Outcome` wire values, in 08:190-198's printed order.

**`Outcome` the `StrEnum` is NOT minted here**, and the precedent is two files old.
`omniweave_ports.types.DriverResult` types its `outcome` as `Literal["ok", "ok_partial"]` rather
than importing an enum, and `sqlite.py`'s `Unit.cost_class` is a `str` *"because `CostClass` is P4's
type and the hook ships before the enum"*. 08:177-179 is explicit that its own block is *"the sole
home of `Outcome`, `StepMetrics` and `StepResult`"* and 18-api-sketch.md:844 homes all three in
`omniweave_core.operator`; a second `StrEnum` here would be the second home that sentence forbids.
What the store needs is the DOMAIN and the transition, and a tuple plus `TRANSITIONS` is exactly
that. A `StrEnum` member compares and binds equal to its value, so P4's real `Outcome` satisfies
every check in this module the day it lands.

**Eight, and the count is load-bearing** (08:179-183): *"adding or removing a member is one edit to
this enum **and** to section 1.2's transition table in the same change -- that table is the
specification, and a member with no row in it is a rejectable PR."* `TRANSITIONS` has eight keys and
`test_store_queue.py` asserts the two agree, in both directions.
"""

DEP_KINDS: Final = ("unit", "part", "name", "cohort", "policy", "service_model")
"""`dep.kind`'s CHECK, verbatim (0004_runtime.sql:186). Enforced by `dep_statements()`.

Enforced in Python as well as by the CHECK because 08:2489-2496 requires the refusal to be a RAISE
that names the offence: a CHECK violation surfaces as `sqlite3.IntegrityError("CHECK constraint
failed: dep")`, which does not say which kind, which key or which unit, and it arrives after the
derived rows of the same transaction have already been written.
"""

CACHE_KEY_HEX_LEN: Final = 64
"""`sha256_canonical` hex is 64 characters, and `StepResult.cache_key` is checked against it.

08:212 types the field *"sha256_canonical hex, 64 chars, from the one `cache_key()`"* and 08:230-231
makes the length a constructor invariant. Named rather than typed inline because the check tracks
`cache_key()`'s output width and not anything this module owns, and because a bare `64` in a
comparison reads as a magic number to a linter and to a reader alike. `work.cache_key` is `TEXT
NOT NULL` with no length CHECK (0004_runtime.sql:95), so this is the only place the width is
enforced at P2.
"""

MAX_WORK_ATTEMPTS: Final = 5
"""`attempts_total < 5` -- the claim predicate's hard ceiling (charter.md:4089, :4099).

Four sites print the same number: the claim SQL twice, 08:107 (*"`attempts_total < 5` is a clause in
the claim predicate"*), 08:593 (*"PERMANENT at `attempts_total >= 5`"*) and charter.md:4650's I7
(*"Every failure path terminates ... `attempts_total < 5` in the claim predicate"*).

**DEFECT -- this is a ceiling with no `limits.py` row, and INV-21 says a ceiling has exactly one
home.** `omniweave_core.limits` holds *"every `MAX_*` ceiling"* (02-architecture.md:231) and has no
`MAX_WORK_ATTEMPTS`; nothing in the plan gives this number a config knob either, so it is a ceiling
and not a setting (INV-22). It is named here rather than typed into a SQL string twice, and the
required edit -- add `MAX_WORK_ATTEMPTS: int = 5` to `limits.py` and import it -- is reported to
that file's owner. `test_store_queue.py` asserts the value against the plan text so the move is one
line and cannot change the number.

**`attempts_today` gets NO clause, and that is a reading with a printed statement behind it.**
08:595 says *"Plus a per-unit daily cap of 3, enforced by `attempts_today`"*, but the charter's
claim SQL (charter.md:4085-4102) has no `attempts_today` predicate, and 02:596 and 02:1028 both put
it the weaker way -- `attempts_today` is period-stamped by `last_attempt_at` *"so a daily cap is
enforceable"*. One printed statement beats three lines of prose about what it enables, so the claim
maintains the counter and its period stamp and enforces only `attempts_total`. Who spends the daily
cap is 08's; reported.
"""

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
# 2. The transition table. 08-runtime.md:94-103, one dataclass per row.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transition:
    """One row of 08:94-103 -- what an `Outcome` does to a `work` row. Seven cells.

    The columns are the plan's, renamed only where a table heading is not an identifier:
    "`work.status` becomes" -> `status`, `attempts_total` -> `decrements_attempts`,
    `cost_micros` -> `adds_micros`, "claimable again" -> `claimable`.

    `retry_after` is a THREE-valued cell and not a number, because two of its three values are
    computed somewhere else: `ladder` is 08 section 1.6's escalation ladder, whose first cooldown
    the driver supplies as `StepResult.retry_after_ms` and whose later rungs are `classify()`'s;
    `sweeper` is 08:126-131's `min(60_000 * 2^(n-1), 1_800_000)`, keyed on an in-run defer streak
    the store cannot see. So the store writes `null`, writes the caller's offset from the store
    clock, or leaves the value to the sweeper -- and never invents a backoff.
    """

    outcome: str
    status: str
    decrements_attempts: bool
    adds_micros: bool
    reservation: str
    retry_after: str
    claimable: str


TRANSITIONS: Final[Mapping[str, Transition]] = MappingProxyType(
    {
        transition.outcome: transition
        for transition in (
            Transition("ok", "done", False, True, "committed", "null", "no"),
            Transition("ok_partial", "done", False, True, "committed", "null", "no"),
            Transition("skipped_cached", "done", False, False, "released", "null", "no"),
            Transition("skipped_unchanged", "done", False, False, "none", "null", "no"),
            Transition(
                "failed_transient",
                "failed_transient",
                False,
                False,
                "released",
                "ladder",
                "yes, at retry_after",
            ),
            Transition(
                "failed_permanent",
                "failed_permanent",
                False,
                True,
                "committed",
                "null",
                "no, until clear_old_permanent(30d)",
            ),
            Transition(
                "deferred_budget",
                "deferred",
                True,
                False,
                "released",
                "sweeper",
                "via deferred_sweeper",
            ),
            Transition("cancelled", "pending", True, False, "released", "null", "immediately"),
        )
    }
)
"""The `Outcome` -> row transition, in full. 08:94-103, which calls itself *the specification*.

**Two cells are the whole reason the table exists** (08:105-112). The claim increments
`attempts_total` unconditionally and `attempts_total < 5` gates the claim, so a row deferred five
times for lack of budget, or cancelled five times by Ctrl-C, *"would become permanently unclaimable
without ever having been attempted -- a corpus that quietly stops ingesting because the operator
interrupted five runs."* `deferred_budget` and `cancelled` therefore decrement, floored at zero, in
the same statement that writes the status. The lease reaper decrements on the same rule *"-- a power
cut is not an attempt"* (08:121-122), which is why `reap_expired_leases` shares the arithmetic.

`skipped_cached` and `skipped_unchanged` KEEP the attempt (08:120-121): the row goes to `done` and
the counter is thereafter inert, and *"spending a branch to tidy an unread integer is not worth
it."* Both are marked `decrements_attempts=False` for that reason and not by omission.

`cancelled` is the row that makes `WORK_STATUSES` six long: it returns to `pending`, immediately
claimable, because a cancellation is not a state a row rests in.

The ninth row of the plan's table -- *(superseded)*, "unchanged, **zero rows updated**" -- is NOT a
key here. It is not an `Outcome`; it is what the commit predicate does when the row moved under the
caller, and `complete()` returns `False` for it. A key would have implied a caller can report it.
"""

DECREMENTING: Final = tuple(
    outcome for outcome in OUTCOMES if TRANSITIONS[outcome].decrements_attempts
)
"""The two outcomes that decrement the attempt counters, in `OUTCOMES` order.

DERIVED from `TRANSITIONS` and then interpolated into `COMPLETE_SQL`'s two `CASE` arms, so the SQL's
IN-list and the transition table cannot disagree. 08:116-119 prints the list as
`:outcome IN ('deferred_budget','cancelled')`; ordering by `OUTCOMES` reproduces that literal
exactly, which is why this is a tuple in the enum's order and not a `frozenset`.
"""


# --------------------------------------------------------------------------------------------
# 3. `WorkRow` -- one claimed `work` row.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkRow:
    """One claimed `work` row as returned by `Store.claim()`. Every column, in DDL order.

    **FORWARD HOME: `omniweave_core.work`.** 02-architecture.md:246 assigns *"`WorkRow`,
    `FailureClass` re-export, `classify()`, the claim/complete/reap SQL, the retry ladder"* to that
    module and 16-roadmap.md:541 schedules it as P4 W4.1. It is a pinned member of
    `test_store_protocols.py`'s `EXPECTED_UNRESOLVED` for exactly that reason, and it stays pinned:
    `store/__init__.py`'s Protocol still names it as a forward reference, which is what keeps the
    boundary declaration free of an import edge into a module that does not exist. When `work.py`
    lands it takes this class verbatim and this one is deleted -- not re-exported, because
    02-architecture.md:246 gives that module the claim/complete/reap SQL too, and a type with two
    homes is the failure INV-21 names.

    **The plan never prints a shape, so this one is derived from the DDL and reported.**
    17-risks.md:653 already logs the gap as defect `08#D1`: *"sixteen charter-named runtime types
    have no lock row"*, `WorkRow` among them, marked discharged by ADR-1 -- an ADR that names the
    problem and does not print the class. Nine mentions plus a return type, and the only field
    anybody specifies is `claimed_gen`: 08:2841 and glossary.md:1124 both read *"carrying
    `claimed_gen` -- which is what the commit predicate compares, and therefore what makes a
    superseded result write nothing."*

    So the shape is the row. Not a projection of it, and the reasoning is not aesthetic: the claim
    statement is `RETURNING`-based (charter.md:4102), the runtime's `dispatch` groups by
    `dispatch_key` and prices by `cost_class` (02:480), the runner needs `operator`, `op_version`,
    `unit_uri`, `unit_part` and `cache_key` to invoke anything at all, `ow queue status` reads
    `failure_class` and `retry_after`, and `attempts_total` is what `adapt_batch` and the ladder
    both read. A narrower row would mean a second `SELECT` per claimed unit against the row the
    claim already returned -- and charter.md:4701 budgets *"claim share + commit + key + ~8 events
    <= 0.5 ms/unit"* for the whole of the runtime overhead. Twenty-nine columns of a STRICT table
    cost one tuple unpack.
    """

    id: int
    unit_uri: str
    unit_part: str
    operator: str
    op_version: int
    cache_key: str
    decision_id: str | None
    sequence_id: str | None
    driver: str | None
    cost_class: str
    dispatch_key: str | None
    service: str | None
    staged_gen: int | None
    status: str
    failure_class: str | None
    failure_message: str | None
    retry_after: int | None
    attempts_total: int
    attempts_today: int
    last_attempt_at: int | None
    stale_since: int | None
    claimed_by: str | None
    claimed_gen: int | None
    lease_expires: int | None
    cost_micros: int
    queued_ms: int
    ran_ms: int
    peak_rss_bytes: int
    priority: int

    @classmethod
    def from_row(cls, row: Sequence[object]) -> WorkRow:
        """Build one from a `WORK_COLUMNS`-ordered tuple, refusing any other width.

        The refusal is the point. A migration that adds a column to `work` changes what
        `WORK_COLUMNS` must say; without this check the addition would be invisible until some
        caller read the wrong attribute, which is the class of bug `RETURNING *` invites.
        """
        if len(row) != len(WORK_COLUMNS):
            raise StoreError(
                f"a work row has {len(WORK_COLUMNS)} columns and this one has {len(row)}: "
                f"WORK_COLUMNS and the `work` DDL have drifted",
                fix="re-read 0004_runtime.sql's work table and update WORK_COLUMNS",
            )
        return cls(*row)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# 4. What `complete()` reads off a `StepResult`, and a P2 carrier for it.
# --------------------------------------------------------------------------------------------


class StepMetricsView(Protocol):
    """The `StepMetrics` fields the `work` transition writes. Structural, never imported.

    08:200-207 prints seven fields; `spend` is the one this module never reads, because the physical
    `Spend` is the `spend_row` participant's and `route_spend` has no P2 producer (see the module
    docstring's table). A Protocol listing only what is read is what lets P4's real `StepMetrics`
    satisfy this with no edit on either side -- the same reason `model/rebind.py` declares
    `RebindReadSide` instead of taking `store.Reader`.
    """

    queued_ms: int
    ran_ms: int
    micros: int
    was_cache_hit: bool
    rows_written: int
    peak_rss_bytes: int


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
    defect is reported. It is optional on the concrete carrier and `None` writes NULL.
    """

    outcome: str
    cache_key: str
    failure_class: str | None
    failure_message: str | None
    retry_after_ms: int | None
    metrics: StepMetricsView


@dataclass(frozen=True, slots=True)
class StepMetrics:
    """08:200-207, field names and order verbatim, minus `spend`. A P2 carrier, not a home.

    `spend: "Spend" = Spend()` is the one field dropped, and dropping it is what keeps this class
    from being a second home for a type it cannot construct: `Spend` is 05-ingest-and-routing.md's
    (:2370), P4's, and a pinned member of `EXPECTED_UNRESOLVED`. A default value cannot be a forward
    reference, so carrying the field would have meant either inventing `Spend` or defaulting it to
    `None` and lying about the annotation. The `spend_row` participant is where it belongs and it
    has no P2 producer anyway.

    Deleted when `omniweave_core/operator.py` lands (P4). `StepMetricsView` is what survives.
    """

    queued_ms: int = 0
    ran_ms: int = 0
    micros: int = 0
    was_cache_hit: bool = False
    rows_written: int = 0
    peak_rss_bytes: int = 0


@dataclass(frozen=True, slots=True)
class StepResult:
    """08:209-231's field names and order, with the un-homed types folded. A P2 carrier, not a home.

    **FORWARD HOME: `omniweave_core/operator.py`** -- 08:187 heads its own block with that path,
    18-api-sketch.md:844 lists `Outcome`, `StepResult`, `StepMetrics`, `Operator`,
    `OperatorIdentity`, `RunContext`, `Roots` and `CancelToken` there under tier `T-CONTRACT`, and
    08:177-179 calls that block *"the sole home"* of three of them. This class exists because
    `Store.complete()` cannot be written, let alone tested, against a type with no shape, and it is
    deleted the day `operator.py` lands. `StepResultView` is the seam that makes that a deletion
    rather than a refactor. It stays in `EXPECTED_UNRESOLVED`.

    **Four of 08's eleven fields are folded, and each fold is a type with no home.**
    `unit: "UnitRef"`, `identity: "OperatorIdentity"`, `produced: tuple["ArtifactRef", ...]` and
    `degradations: tuple["Degradation", ...]` are all P4's, none is read by the `work` transition,
    and none can be given a runtime default here. They are omitted rather than typed `object`,
    because an `object`-typed `identity` on a class named `StepResult` is a field a caller would
    fill and the store would silently drop. `produced` is the one whose absence has a consequence
    worth naming: it is the plausible narrow-signature channel for the `derived_rows` participant,
    so P4 restoring it is what turns that empty slot into statements.

    **`__post_init__` is 08:222-231 verbatim**, minus the `cache_key` length check's dependence on
    `cache_key()` existing. The invariant is in the constructor and not in review, and a
    `FailureClass` is required on `FAILED_TRANSIENT` as well as `FAILED_PERMANENT` *"because the
    retry ladder escalates from the class's first cooldown and a classless transient failure has
    nothing to escalate from"* (08:233-236).
    """

    outcome: str
    cache_key: str
    partial_reason: str | None = None
    failure_class: str | None = None
    failure_message: str | None = None
    retry_after_ms: int | None = None
    deferred_dim: str | None = None
    metrics: StepMetrics = StepMetrics()

    def __post_init__(self) -> None:
        """08:222-231, with `outcome` checked against `OUTCOMES` before it is used as a key."""
        if self.outcome not in TRANSITIONS:
            raise ValueError(f"{self.outcome!r} is not one of the eight Outcome values {OUTCOMES}")
        required = {
            "ok_partial": ("partial_reason",),
            "failed_transient": ("retry_after_ms", "failure_class"),
            "failed_permanent": ("failure_class",),
            "deferred_budget": ("deferred_dim",),
        }.get(self.outcome, ())
        for name in required:
            if getattr(self, name) is None:
                raise ValueError(f"{self.outcome} requires {name}")
        if self.retry_after_ms is not None and self.outcome != "failed_transient":
            raise ValueError("retry_after_ms is meaningful only for failed_transient")
        if len(self.cache_key) != CACHE_KEY_HEX_LEN:
            raise ValueError("cache_key is the 64-char hex output of cache_key()")


# --------------------------------------------------------------------------------------------
# 5. `Statement` -- the unit of a `complete()` plan, and therefore of a crash boundary.
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
# 6. `dep` rows -- empty at P2, but the refusals ship now.
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
# 7. The statements. Each transcribed from the one place the plan prints it.
# --------------------------------------------------------------------------------------------

STORE_NOW_MS: Final = "CAST(unixepoch('subsec')*1000 AS INTEGER)"
"""The store clock as a millisecond INTEGER. charter.md:4090's `unixepoch('subsec')*1000`, CAST.

**DEFECT -- the charter's claim SQL writes a REAL into a STRICT table's INTEGER column.**
`unixepoch('subsec')` returns a floating-point value (that is what `'subsec'` adds over
`unixepoch()`), so `unixepoch('subsec')*1000` is a REAL, and charter.md:4092 and :4098 assign it
straight into `work.lease_expires` and `work.last_attempt_at`. `work` is `) STRICT`
(0004_runtime.sql:131), and a STRICT `INTEGER` column accepts a REAL only when the value is
LOSSLESSLY convertible -- so the statement stores a clean integer whenever the wall clock happens to
land on a whole millisecond and raises `sqlite3.IntegrityError("datatype mismatch")` the rest of the
time. Measured: roughly one claim in a handful fails, at random, on SQLite 3.43.1.

That is the worst possible failure shape -- a claim that works in every hand-run and drops a batch
under load -- so the CAST is not optional. It also matters at the READ side: `lease_expires` is
compared against `reap_expired_leases`'s injected integer `now_ms`, and a stored REAL would make
`lease_expires < :now_ms` a float comparison. One fragment, five uses, so the two cannot diverge.
Reported.
"""

CLAIM_SQL: Final = f"""
WITH head AS (
  SELECT dispatch_key FROM work
   WHERE status IN ('pending','failed_transient')
     AND (retry_after IS NULL OR retry_after <= {STORE_NOW_MS})
     AND attempts_total < {MAX_WORK_ATTEMPTS}
   ORDER BY priority DESC, dispatch_key, id LIMIT 1)
UPDATE work SET
  status='claimed', claimed_by=:worker, claimed_gen=:gen,
  lease_expires = {STORE_NOW_MS} + :lease_ms,
  attempts_total = attempts_total + 1,
  attempts_today = CASE WHEN date(last_attempt_at/1000,'unixepoch')
                          = date(unixepoch('subsec'),'unixepoch') THEN attempts_today+1 ELSE 1 END,
  last_attempt_at = {STORE_NOW_MS}
WHERE id IN (SELECT w.id FROM work w JOIN head h ON w.dispatch_key IS h.dispatch_key
              WHERE w.status IN ('pending','failed_transient')
                AND (w.retry_after IS NULL OR w.retry_after <= {STORE_NOW_MS})
                AND w.attempts_total < {MAX_WORK_ATTEMPTS}
              ORDER BY w.priority DESC, w.id
              LIMIT IFNULL(
                (SELECT CASE WHEN dispatch_key IS NULL THEN 1 ELSE :batch END FROM head), 0))
RETURNING {", ".join(WORK_COLUMNS)}
"""  # noqa: S608 -- see the docstring: no caller input.
"""THE BATCH-COHERENT CLAIM. One statement. Priority survives. charter.md:4083-4102.

Transcribed from the charter's block with exactly three deviations, each forced and each recorded.

**(a) No `cost_class` clause.** The charter's SQL binds `:cost_class` in four places because
08:2478-2481's WIDER `claim` takes one. The narrow signature does not (07:57, charter.md:3394), and
the module docstring argues why nothing is lost: one `dispatch_key` is one `cost_class`.

**(b) `JOIN head h ON w.dispatch_key IS h.dispatch_key`, not `w.dispatch_key = head.dispatch_key`,
and a `LIMIT` that collapses to 1 for a NULL head.** This is a defect in the printed statement.
`dispatch_key` is *"NULL for an `op.*` row, AND A NULL BATCHES ALONE"* (0004_runtime.sql:104-105),
and `=` is never true of two NULLs -- so under the charter's SQL an `op.identify` row selected as
the head matches no row in the `picked` subquery, the UPDATE claims nothing, and `op.identify` is
unclaimable forever. Since `op.identify` *"is what CREATES the part rows the queue then drains"*
(08:614) and carries priority 300, the head is exactly where it would appear. `IS` matches NULL to
NULL, which alone would batch every `op.*` row together; the `LIMIT` subquery is what makes a NULL
head *"batch alone"* as the DDL requires. `ORDER BY w.priority DESC, w.id` then picks the head row
itself. Reported.

The `IFNULL(..., 0)` around that subquery is not decoration. When nothing is claimable the `head`
CTE is empty, the scalar subquery is NULL, and **SQLite raises `datatype mismatch` on a NULL
`LIMIT`** -- measured on 3.43.1, and it is the single most common state a polling claim loop is in.
`LIMIT 0` is the answer: no rows picked, no rows updated, an empty `RETURNING`.

**(c) `RETURNING` the named columns rather than `*`** -- `WORK_COLUMNS`' docstring.

Everything else is the charter's, including the two properties it is shaped for. `ORDER BY priority
DESC, dispatch_key, id` in `head` and `ORDER BY w.priority DESC, w.id` in the picked set are why
*"priority survives batching"* (08:625-627) is a property and not a hope. `unixepoch('subsec')*1000`
is read five times and is *"THE STORE'S CLOCK, never a worker's"* (charter.md:4090) -- which is also
why the `retry_after` comparison uses it: 08:597 requires that *"a backward NTP step on one worker
must not make a row permanently unclaimable."* `attempts_today` is recomputed from
`date(last_attempt_at)` rather than trusting a stored zero because *"a counter without its period
stamp cannot answer 'is this from today'"* (08:595-597).

**`RETURNING` needs no fallback.** charter.md:4104-4118 keeps a *"SQLite 3.35-3.41 (no `RETURNING`):
BEGIN IMMEDIATE + UPDATE + SELECT"* branch and says *"BOTH PATHS RUN IN CI'S 16-PROCESS HAMMER"* --
but the same block's own star note declares `MIN_SQLITE = (3, 42, 0)` the real floor, `limits.py`
declares it, and `sqlite.py`'s `refuse_old_sqlite` refuses below it before the file is touched. The
branch is unreachable, and a second path nothing can execute is a second path nobody tests. One
path; reported.
"""

_DECREMENTING_IN: Final = ",".join(f"'{outcome}'" for outcome in DECREMENTING)

COMPLETE_SQL: Final = f"""
UPDATE work SET
       status = :status,
       cache_key = :cache_key,
       attempts_total = CASE WHEN :outcome IN ({_DECREMENTING_IN})
                             THEN MAX(0, attempts_total - 1) ELSE attempts_total END,
       attempts_today = CASE WHEN :outcome IN ({_DECREMENTING_IN})
                             THEN MAX(0, attempts_today - 1) ELSE attempts_today END,
       retry_after = CASE WHEN :retry_after_ms IS NULL THEN NULL
                          ELSE {STORE_NOW_MS} + :retry_after_ms END,
       claimed_by = NULL, claimed_gen = NULL, lease_expires = NULL,
       cost_micros = cost_micros + :micros,
       queued_ms = :queued_ms, ran_ms = :ran_ms,
       peak_rss_bytes = MAX(peak_rss_bytes, :peak_rss_bytes),
       failure_class = :failure_class, failure_message = :failure_message
 WHERE id = :id AND claimed_gen = :gen AND status = 'claimed'
"""  # noqa: S608 -- see the docstring: no caller input.
"""The `work_transition` participant. 08:113-125 verbatim, plus one column 02-architecture.md adds.

`cache_key = :cache_key` is the addition, and 02:487 is its definition site: the transaction holds
*"the derived rows, `work.status='done'` + `work.cache_key`, the `dep` rows, the reservation commit
and the `route_spend` row (I20)"*. The column is *"RECORDED: a config change is a MISMATCH, not a
reuse"* (0004_runtime.sql:95), which only works if the value written is the one the invocation
actually keyed on -- `StepResult.cache_key`, *"sha256_canonical hex, 64 chars, from the one
`cache_key()`"* (08:212).

`retry_after` is computed from the STORE clock plus the caller's offset (08:597), which is why the
`CASE` adds `:retry_after_ms` to `unixepoch('subsec')*1000` rather than binding a timestamp. NULL in
gives NULL out, which is seven of the eight transitions.

The `WHERE` clause is the commit predicate, printed identically at charter.md:4104 and 02:487.
Zero rows means superseded and nothing else.
"""

COST_CLASS_SQL: Final = "SELECT cost_class FROM work WHERE id = :id"
"""ST14's prerequisite: which `synchronous` this completion commits at, read BEFORE `BEGIN`.

07:2735-2740: *"a `BILLED_API` commit is durable -- `synchronous = FULL` is set **before** `BEGIN`
for that transaction."* `Unit.durable` is read by `sqlite.py`'s `_transact` before it issues the
pragma or the `BEGIN`, so the class cannot be learned inside the transaction. The narrow
`complete()` carries no `cost_class` (08:2478-2481's wider `claim` does), so the store reads it.

Its own short unit, and a crash across it writes nothing.
"""

REAP_RESERVATIONS_SQL: Final = """
UPDATE budget_reservation SET state = 'released'
 WHERE state = 'held'
   AND work_id IN (SELECT id FROM work WHERE status = 'claimed' AND lease_expires < :now_ms)
"""
"""I29: the lease reaper releases expired reservations IN THE SAME TRANSACTION as the reap.

0004_runtime.sql:238-240 states it as a property of the schema: *"headroom(dim,scope,key) = limit -
sum(held) - sum(committed), COMPUTED IN SQL, never cached in an attribute. The lease reaper releases
expired reservations IN THE SAME TRANSACTION. (I29)"* 08:471-473 says why: *"Headroom is computed in
SQL, never cached in an attribute, so a crash cannot leak it."*

**It runs BEFORE the `work` reap and the order is load-bearing.** The subquery identifies the
reservations by the rows about to be reaped; after the reap those rows are `pending` and the
subquery selects nothing, so a reservation whose work row had just been returned to the queue would
stay `held` forever and silently consume headroom. `expires_ms` is not used as the predicate even
though 08:466 says *"Every `expires_ms` == its work row's `lease_expires`"*: that equality is the
runtime's to maintain, and joining on `work_id` releases exactly the reservations of exactly the
reaped rows whether or not it holds.

Empty at P2 -- `budget_reservation.decision_id` is `NOT NULL REFERENCES route_decision` and nothing
at P2 writes a `route_decision` row -- and correct the day it is not.
"""

REAP_SQL: Final = """
UPDATE work SET
       status = 'pending',
       attempts_total = MAX(0, attempts_total - 1),
       attempts_today = MAX(0, attempts_today - 1),
       claimed_by = NULL, claimed_gen = NULL, lease_expires = NULL,
       retry_after = NULL
 WHERE status = 'claimed' AND lease_expires < :now_ms
"""
"""The lease reap. `status='claimed' AND lease_expires < now`, back to `pending`, decremented.

08:2411: *"Each row goes to `pending` with `attempts_total` decremented."* 08:121-122 gives the rule
it shares with `CANCELLED`: *"The lease reaper decrements on the same rule as `CANCELLED` -- a power
cut is not an attempt."* `MAX(0, ...)` is the same floor `COMPLETE_SQL` applies, and for the same
reason: the claim increments unconditionally and `attempts_total < 5` gates the claim, so an
un-floored decrement plus a repeated crash is a row that becomes unclaimable without ever having
been attempted (08:105-112).

`retry_after = NULL` because the row is `pending` and *"claimable again: immediately"* is
`cancelled`'s cell (08:102), which this shares. A stale `retry_after` from an earlier transient
failure would gate the re-claim on a timestamp that has nothing to do with the crash.

**`lease_expires < :now_ms` is strict**, so a lease expiring exactly at `now_ms` is still live. A
reaper and a holder that disagree by one millisecond is a stolen lease, and the plan's own predicate
is `lease_expires < now` (08:2411, 08:462).

**Holder liveness is NOT checked here, and that is a scope boundary rather than an omission.**
08:462-470 requires the reaper to check `_is_live_holder(claimed_by)` --
`'<host>:<pid>:<process_create_time>'`, *"the third component is what stops a recycled pid from
looking alive"* -- and to give a live holder past its lease *"one extension with a WARNING naming
it, never a steal."* Both halves need things the store boundary does not have: an OS probe per row,
and `[runtime] lease_extend_ms = 60000` (08:2578), a runtime config key with no `limits.py` home.
The signature the plan freezes is `reap_expired_leases(now_ms) -> int` and nothing else, so the SQL
predicate is what ships and `lease_reaper` -- 08's, in `omniweave/run/`, P4 W4.1 -- owns the
liveness check and the extension. `sqlite.py.process_create_time` is already the probe it needs.
Recorded so nobody reads the missing check as a bug in this method.
"""

COUNTS_SQL: Final = "SELECT status, count(*) FROM work GROUP BY status"
"""ONE query, and 0004_runtime.sql:137 is the comment that forbids the alternative.

*"NO COUNTER TABLE: `SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift."*
08:57-58 says the same from the runtime's side and names the counter-example: *"LDR maintains one by
hand and it drifts."* One query and not six, because six `SELECT count(*) WHERE status = ?` reads
are six index probes and, across a non-transactional loop, six inconsistent answers.
"""


# --------------------------------------------------------------------------------------------
# 8. `Store` -- the four methods.
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
