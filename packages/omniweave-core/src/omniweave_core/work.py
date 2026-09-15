"""The work vocabulary: `WorkRow`, the claim/complete/reap SQL, `classify()` and the retry ladder.

02-architecture.md section 2 row 22 is this module's charter, and it is four things and one
exclusion:

> | 22 | Work vocabulary | `omniweave_core.work` | `WorkRow`, `FailureClass` re-export,
> `classify()`, the claim/complete/reap SQL, the retry ladder | **running the loop (L5's job)** |
> the SQL plus `WorkRow` | T-SCHEMA |

16-roadmap.md:541 schedules it as P4 W4.1. Six sites in the tree already name `work.classify()` as
the one home of the retry axis before this file existed -- `errors.py:121` and `:327`,
`host/subproc.py:595`, `store/queue.py` three times -- which is what a forward reference is for and
also why it had to land before anything in P4 could call it.

**The exclusion is the important half.** Nothing here runs. There is no loop, no `asyncio`, no
`Store`, no connection and no clock read: this module holds the *statements* and the *decisions*,
and `omniweave_core.store.queue.SqliteStore` submits the first while `omniweave/run/` -- L5, a
different distribution -- makes the second happen. A module that both defined the ladder and
climbed it would put the runtime's scheduling policy inside core, which is the boundary
02-architecture.md section 3.2 draws and G4 gates.

## What moved here, and from where

`WorkRow`, the closed domains and the seven statements were written in `store/queue.py` at P2,
under a docstring that said exactly what would happen next: *"When `work.py` lands it takes this
class verbatim and this one is deleted -- not re-exported, because 02-architecture.md:246 gives
that module the claim/complete/reap SQL too, and a type with two homes is the failure INV-21
names."* This is that move, and it is a move rather than a copy for that reason. `store/queue.py`
now imports from here.

What stayed in `store/queue.py` is what the *store* owns: `SqliteStore` itself, `StepMetrics` and
`StepResult` (08-runtime.md:177 homes those in `omniweave_core.operator`, not here),
`COMPLETE_PARTICIPANTS` and `Statement` (the shape of one transaction), `CACHE_KEY_HEX_LEN` (a
`StepResult` invariant) and `dep_statements` with `DEP_KINDS` (02-architecture.md:244 homes `Dep`
and `DepKind` in `omniweave_core.deps`, which is W4.6's and not this cell's).

## The three tiers of `classify()`, and why the order is the specification

08-runtime.md:535-556 prints the signature and the order:

1. **A structured `FailureClass` from the driver wins.** `DriverError` carries one and it is
   believed.
2. **Otherwise `status_code`**, against a fixed table. This tier exists because *"an exception
   crossing the S4 wire from a third-party HTTP client routinely loses the class and keeps the
   code."*
3. **Otherwise the message table, and only then**, with `Diag(OW-D-051, severity='warning')`
   recording the unclassified string, *"so the gap is closed rather than tolerated."*

LDR's 120 lines of substring matching (`"requires login" in details_lower`) is the named
anti-pattern -- it *"silently reclassifies a permanent failure as retryable the day upstream
changes its wording"* -- and codegraph's `isWatchResourceExhaustion` is the named discipline:
prefer the structured code, match messages only when there is no code. `MESSAGE_PATTERNS` ships
**empty** for that reason, and its docstring is the argument.

## The `source` axis, and the one class whose verdict depends on it

08:572-576: *"a **host**-detected deadline breach is `FAILED_PERMANENT{TIMEOUT}` because the host
killed a process that produced nothing, and a **driver**-reported timeout is transient because the
driver observed a remote peer being slow. One `FailureClass`, two producers, two verdicts, and
`Failure.source ∈ {driver, host}` records which."*

`classify()`'s printed signature carries no `source` parameter, so it is derived from the exception,
and the derivation is exact rather than a heuristic. `host/subproc.py:616-631` refuses to build a
`DriverError` for a host-detected transient class at all -- *"a host-detected {class} is
failed_permanent and has no `retry_after_ms`, so it is not expressible as a `DriverError`"* -- and
raises `DriverHostError` instead. So a host-detected `timeout` can only reach a caller as a
`DriverHostError`, and `isinstance(exc, DriverHostError)` is the test. `driver_crashed` is the one
class the table itself fixes as host-sourced (08:569) whichever exception carries it, because the
host synthesises it from an exit status and a stderr ring and a driver cannot report its own death.

## What this module does NOT mint

A `Diag`. Tier 3 records `OW-D-051` and the raw message on the `Failure`, and the caller mints the
row: `Diag` is `omniweave_core.model`'s and still owed by W2.1, and a classifier that constructed
one would be importing the lazy L2 model into a module the scheduler calls per failure. The code
and the string are the material; minting is `run/pipeline.py`'s.

Stdlib plus `omniweave_ports` (INV-2, G1). No `sqlite3`: the statements here are text, and the only
thing that executes them is `store/queue.py`.

Specified in 02-architecture.md section 2 row 22 and section 7.5, 08-runtime.md sections 1.2, 1.3
and 1.6 (:94-131, :533-608), charter.md:4083-4118, and 16-roadmap.md:541.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_ports.types import FailureClass

from omniweave_core.errors import DriverHostError, StoreError
from omniweave_core.limits import MAX_WORK_ATTEMPTS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CLAIM_SQL",
    "COMPLETE_SQL",
    "COST_CLASS_SQL",
    "COUNTS_SQL",
    "DECREMENTING",
    "DIAG_UNCLASSIFIED",
    "ESCALATION_MS",
    "FIRST_COOLDOWN_MS",
    "LADDER",
    "MAX_ATTEMPTS_TODAY",
    "MAX_WORK_ATTEMPTS",
    "MESSAGE_PATTERNS",
    "OUTCOMES",
    "RATE_LIMIT_COOLDOWN_MS",
    "REAP_RESERVATIONS_SQL",
    "REAP_SQL",
    "SERVER_ERROR_CEILING",
    "SERVER_ERROR_FLOOR",
    "STATUS_CODE_TIER",
    "STORE_NOW_MS",
    "TIMEOUT_FROM_HOST",
    "TRANSITIONS",
    "UNCLASSIFIED_COOLDOWN_MS",
    "WORK_COLUMNS",
    "WORK_STATUSES",
    "Failure",
    "FailureClass",
    "Rung",
    "Scope",
    "Source",
    "Transition",
    "Verdict",
    "WorkRow",
    "classify",
    "escalate",
    "match_message",
    "rate_limit_cooldown_ms",
    "rung_for",
]


# --------------------------------------------------------------------------------------------
# 1. The closed domains, transcribed from the shipped DDL and from 08 section 1.2.
# --------------------------------------------------------------------------------------------

WORK_STATUSES: Final[tuple[str, ...]] = (
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

WORK_COLUMNS: Final[tuple[str, ...]] = (
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

OUTCOMES: Final[tuple[str, ...]] = (
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

**`Outcome` the `StrEnum` is NOT minted here.** 08:177-179 is explicit that its own block is *"the
sole home of `Outcome`, `StepMetrics` and `StepResult`"* and 18-api-sketch.md:844 homes all three in
`omniweave_core.operator`; a second `StrEnum` here would be the second home that sentence forbids.
What the queue needs is the DOMAIN and the transition, and a tuple plus `TRANSITIONS` is exactly
that. A `StrEnum` member compares and binds equal to its value, so P4's real `Outcome` satisfies
every check in this module the day `operator.py` lands.

**Eight, and the count is load-bearing** (08:179-183): *"adding or removing a member is one edit to
this enum **and** to section 1.2's transition table in the same change -- that table is the
specification, and a member with no row in it is a rejectable PR."* `TRANSITIONS` has eight keys and
`test_work.py` asserts the two agree, in both directions.
"""

MAX_ATTEMPTS_TODAY: Final[int] = 3
"""08:595's per-unit daily cap. Declared here, spent by the runtime, and NOT in the claim SQL.

08:595 says *"Plus a per-unit daily cap of 3, enforced by `attempts_today` with `last_attempt_at`
as the period stamp beside it"*, but the charter's claim SQL (charter.md:4085-4102) has no
`attempts_today` predicate, and 02:596 and 02:1028 both put it the weaker way -- `attempts_today` is
period-stamped *"so a daily cap is enforceable"*. One printed statement beats three lines of prose
about what it enables, so `CLAIM_SQL` maintains the counter and its period stamp and enforces only
`attempts_total`. The number lives here because whoever spends it needs a single home for it, and
`store/queue.py` recorded the same reading before the constant had one. Reported."""


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
    the driver supplies as `StepResult.retry_after_ms` and whose later rungs are `escalate()`'s;
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
cut is not an attempt"* (08:121-122), which is why `REAP_SQL` shares the arithmetic.

`skipped_cached` and `skipped_unchanged` KEEP the attempt (08:120-121): the row goes to `done` and
the counter is thereafter inert, and *"spending a branch to tidy an unread integer is not worth
it."* Both are marked `decrements_attempts=False` for that reason and not by omission.

`cancelled` is the row that makes `WORK_STATUSES` six long: it returns to `pending`, immediately
claimable, because a cancellation is not a state a row rests in.

The ninth row of the plan's table -- *(superseded)*, "unchanged, **zero rows updated**" -- is NOT a
key here. It is not an `Outcome`; it is what the commit predicate does when the row moved under the
caller, and `complete()` returns `False` for it. A key would have implied a caller can report it.
"""

DECREMENTING: Final[tuple[str, ...]] = tuple(
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
# 4. Failure classification and the retry ladder. 08-runtime.md section 1.6.
# --------------------------------------------------------------------------------------------


class Source(StrEnum):
    """Who observed the failure. 08:576: *"`Failure.source ∈ {driver, host}` records which."*

    It is not decoration and it is not an audit field: `timeout` is transient from a driver and
    permanent from a host, so this is an input to the verdict for one of the thirteen classes.
    `host/subproc.py`'s `HostVerdict.detected_by` carries the same two values on the other side of
    the seam, spelled the same way, so a verdict crossing into `classify()` does not change
    vocabulary on the way.
    """

    DRIVER = "driver"
    HOST = "host"


class Verdict(StrEnum):
    """What the ladder says to do with the row. Three values, and `NOT_A_FAILURE` is one of them.

    08:563 makes `needs_ocr` *"**not a failure**"* at all -- *"it is routing data: the named pages
    escalate one Rung"* -- so a two-valued verdict would have forced `needs_ocr` to be one of
    permanent or transient, and both are wrong. 02-architecture.md section 7.1 says the same from
    the other direction.
    """

    PERMANENT = "permanent"
    TRANSIENT = "transient"
    NOT_A_FAILURE = "not_a_failure"


class Scope(StrEnum):
    """How wide a permanent verdict reaches. The plan's own qualifiers, made into a field.

    08:558-570 does not say "permanent" seven times; it says permanent, *"permanent **for this
    operator**"* (`too_large`, re-queued for a part-granularity operator at the same `unit_part`),
    *"permanent **for this unit**"* (`driver_crashed`, retried once at `batch = 1` to localise the
    poison unit) and -- in tier 2 -- *"permanent for this locator"* (404/410). Collapsing those to
    one word would lose the side effect each of them names, and the side effect is the whole
    content of three rows of that table.

    `ROW` is the default and means what it says: this `work` row is done failing.
    """

    ROW = "row"
    OPERATOR = "operator"
    UNIT = "unit"
    LOCATOR = "locator"


@dataclass(frozen=True, slots=True)
class Rung:
    """One row of 08:558-570's table. A transcription, not a design.

    `first_cooldown_ms` is `None` for every permanent row and for `needs_ocr`, which is the table's
    own em dash. `rate_limited` is `None` too and is the one row whose cooldown is not a constant:
    08:564 gives it as *"the driver's `retry_after_ms` if present, else
    `RATE_LIMIT_COOLDOWN_MS[provider]`"*, so it is computed by `rate_limit_cooldown_ms()` and the
    table records the absence rather than a number that would be wrong for every provider.
    """

    failure_class: str
    source: str
    verdict: Verdict
    scope: Scope
    first_cooldown_ms: int | None
    side_effect: str


LADDER: Final[Mapping[str, Rung]] = MappingProxyType(
    {
        rung.failure_class: rung
        for rung in (
            Rung(
                "encrypted",
                "driver",
                Verdict.PERMANENT,
                Scope.ROW,
                None,
                "a Diag row, which the absence contract can join against",
            ),
            Rung(
                "unsupported_format",
                "driver",
                Verdict.PERMANENT,
                Scope.ROW,
                None,
                "a Diag row, which the absence contract can join against",
            ),
            Rung(
                "corrupt_input",
                "driver",
                Verdict.PERMANENT,
                Scope.ROW,
                None,
                "a Diag row, which the absence contract can join against",
            ),
            Rung(
                "empty_result",
                "driver",
                Verdict.PERMANENT,
                Scope.ROW,
                None,
                "a Diag row, which the absence contract can join against",
            ),
            Rung(
                "auth",
                "driver",
                Verdict.PERMANENT,
                Scope.ROW,
                None,
                "a Diag row, which the absence contract can join against",
            ),
            Rung(
                "too_large",
                "driver",
                Verdict.PERMANENT,
                Scope.OPERATOR,
                None,
                "re-queued for a part-granularity or chunked operator at the same unit_part",
            ),
            Rung(
                "driver_bug",
                "driver or host",
                Verdict.PERMANENT,
                Scope.ROW,
                None,
                "`ow drivers explain` prints the card and the fix command",
            ),
            Rung(
                "needs_ocr",
                "driver",
                Verdict.NOT_A_FAILURE,
                Scope.ROW,
                None,
                "routing data: the named pages escalate one Rung",
            ),
            Rung(
                "rate_limited",
                "driver or a 429",
                Verdict.TRANSIENT,
                Scope.ROW,
                None,
                "AIMD does NOT shrink the batch: a provider signal, not a poison unit",
            ),
            Rung(
                "upstream_unavailable",
                "driver or a 5xx",
                Verdict.TRANSIENT,
                Scope.ROW,
                300_000,
                "",
            ),
            Rung(
                "timeout",
                "driver",
                Verdict.TRANSIENT,
                Scope.ROW,
                1_800_000,
                "the message names the deadline the driver was working to",
            ),
            Rung(
                "resource_limit",
                "driver or host",
                Verdict.TRANSIENT,
                Scope.ROW,
                60_000,
                "adapt_batch: max(1, batch // 2); the message names WHICH KNOB would need raising",
            ),
            Rung(
                "driver_crashed",
                "host",
                Verdict.PERMANENT,
                Scope.UNIT,
                None,
                "retry once at batch = 1; 3 crashes in 60 s quarantines the DRIVER",
            ),
        )
    }
)
"""08:558-570's table, one `Rung` per row, keyed by `FailureClass` value.

Thirteen keys for thirteen `FailureClass` members -- and **fourteen rows**, because `timeout` has
two in the plan's table and they disagree on the verdict. The key here is the DRIVER's row;
`TIMEOUT_FROM_HOST` below is the other, and `rung_for()` is where the source selects between them.
08:572-576 calls that split *"the one place two plan documents could have contradicted each
other"*, so it is a branch and not a cell, and `test_work.py` asserts the keys are exactly the
thirteen members so a fourteenth class cannot land without a rung.

The `side_effect` column is transcribed even though nothing in this module acts on it. It is the
column that says what `too_large`, `resource_limit` and `driver_crashed` actually DO, all three of
those actions belong to `run/dispatch.py` (W4.7), and a table that dropped it would leave the
runtime's author to re-derive three behaviours from prose.
"""

TIMEOUT_FROM_HOST: Final = Rung(
    "timeout",
    "host",
    Verdict.PERMANENT,
    Scope.ROW,
    None,
    "`limit` names which of progress_ms or wall_ms_hard fired (04-driver-system.md section 6.3)",
)
"""08:567 -- the second `timeout` row. Host-detected, and therefore **permanent**.

*"A host-detected deadline breach is `FAILED_PERMANENT{TIMEOUT}` because the host killed a process
that produced nothing, and a driver-reported timeout is transient because the driver observed a
remote peer being slow."* And the sentence that makes it permanent rather than merely attributed:
*"A driver that hangs on this input hangs on it again."*
"""

UNCLASSIFIED_COOLDOWN_MS: Final = 3_600_000
"""One hour -- the *unclassified* row of 08:570. **Fail toward retryable, and report the gap.**

The longest transient cooldown in the table by a factor of two, and deliberately so: an
unclassified failure is one the framework does not understand, and retrying something it does not
understand every five minutes is how a misclassification becomes a bill.
"""

RATE_LIMIT_COOLDOWN_MS: Final[Mapping[str, int]] = MappingProxyType({"default": 3_600_000})
"""08:584, verbatim -- and 08:578 calls it *"shipped data, not a constant"*.

LDR keys per-domain cooldowns off the netloc with a `default` (`failure_classifier.py:60`:
arxiv.org 6 h, researchgate.net 12 h, PubMed 2 h, default 1 h) *"and the spread is the point -- a
network blip and an anti-bot challenge are both 'temporary' three orders of magnitude apart."*
omniweave's analogue is keyed on `Spend.provider`, and the plan prints exactly one row.

`[providers.<tag>] rate_limit_cooldown_ms` is the operator override and it is `operational` -- it
changes no output. This mapping is the shipped default the override merges over; it is not read
directly by `classify()`, which goes through `rate_limit_cooldown_ms()` so the `Retry-After`
precedence lives in one function.
"""

ESCALATION_MS: Final[tuple[int | None, ...]] = (None, 86_400_000, 2_592_000_000, 2_592_000_000)
"""The escalation ladder, indexed by `attempts_total`. LDR's `compute_retry_cooldown`, verbatim.

08:590-593: *"`classifier cooldown -> 1 day -> 30 days -> 30 days -> PERMANENT` at `attempts_total
>= 5`, which is the `attempts_total < 5` clause in the claim predicate. The classifier's cooldown
governs the **first** attempt only; after that, repeated failure is itself the evidence."*

Index 0 is `None` and means "the classifier's": `escalate()` substitutes the `Failure`'s own
cooldown there rather than this table holding a copy of a number it does not own. Indexes 1, 2 and
3 are one day and thirty days twice. At index 4 -- `attempts_total == MAX_WORK_ATTEMPTS - 1`, the
last claimable attempt -- and beyond there is no rung, and `escalate()` returns `None` for
permanent, which is what the claim predicate enforces anyway.

Four entries against `MAX_WORK_ATTEMPTS = 5` is not an off-by-one: a cooldown is the wait BEFORE
the next attempt, so attempt 5 needs no rung after it.
"""

STATUS_CODE_TIER: Final[Mapping[int, tuple[str, Verdict, Scope]]] = MappingProxyType(
    {
        401: ("auth", Verdict.PERMANENT, Scope.ROW),
        403: ("auth", Verdict.PERMANENT, Scope.ROW),
        404: ("upstream_unavailable", Verdict.PERMANENT, Scope.LOCATOR),
        410: ("upstream_unavailable", Verdict.PERMANENT, Scope.LOCATOR),
        429: ("rate_limited", Verdict.TRANSIENT, Scope.ROW),
    }
)
"""Tier 2, exactly as 08:545-548 prints it. Plus 5xx, which is a range and is handled below.

*"401/403 -> `auth`; 404/410 -> `upstream_unavailable`, **permanent for this locator**; 429 ->
`rate_limited`; 5xx -> `upstream_unavailable`."*

**404/410 carries its own verdict and it is not the class's.** `upstream_unavailable` is transient
in `LADDER` with a five-minute cooldown, and that is right for a 503: the host is down and will be
back. A 404 is the opposite claim -- this URL is not a thing -- so the row overrides the class,
which is why this table's values are `(class, verdict, scope)` and not a bare class. `Scope.LOCATOR`
is the plan's own qualifier and it is narrower than `ROW`: another locator on the same host is
unaffected, which is what a connector re-planning the unit needs to know.
"""

SERVER_ERROR_FLOOR: Final = 500
SERVER_ERROR_CEILING: Final = 600
"""`5xx` as a half-open range -- 08:548's fourth clause, the only one that is not a single code."""

MESSAGE_PATTERNS: Final[tuple[tuple[str, str], ...]] = ()
"""Tier 3's substring table. **Empty, on purpose, and this docstring is the reason.**

08:549-550 puts tier 3 third and hedges it in the same sentence: *"Otherwise the message table,
**and only then**, with `Diag(OW-D-051, severity='warning')` recording the unclassified string, so
the gap is closed rather than tolerated."* The plan prints no rows for it, and 08:552-554 names the
anti-pattern in the next paragraph: LDR's *"120 lines of substring matching (`"requires login" in
details_lower`) silently reclassifies a permanent failure as retryable the day upstream changes its
wording"*, against codegraph's discipline of *"prefer the structured code, match messages only when
there is no code."*

So the mechanism ships and the table does not, which is the strongest reading of "and only then":
every failure that reaches tier 3 today becomes `transient` at `UNCLASSIFIED_COOLDOWN_MS` with
`OW-D-051` naming the raw string, and the fix for any of them is a tier-1 or tier-2 classification
rather than a row here. A row added later is `(substring, failure_class_value)` and
`match_message()` is where it is read; `classify()` never greps.

The pair is ordered, first match wins, and the substring is matched case-insensitively against the
exception's `str()`. Those three decisions are stated here because with no rows nothing in the
tests can pin them, and `match_message()` is called directly with a table so that they can be.
"""

DIAG_UNCLASSIFIED: Final = "OW-D-051"
"""`OW_DRIVER_MESSAGE_UNCLASSIFIED`, allocated in `codes.toml` and cited at 08:549 and :570.

Carried on the `Failure` rather than minted into a `Diag` here: `Diag` is `omniweave_core.model`'s
and the module docstring's last section says why a classifier may not reach for it.
"""


@dataclass(frozen=True, slots=True)
class Failure:
    """What `classify()` returns: one row of the ladder, resolved for one failure.

    `tier` records which of the three answered, which is the field an operator reading
    `ow queue status` needs to know whether a classification is trustworthy: tier 1 is the driver's
    own word, tier 2 is an HTTP code, and tier 3 is a guess the framework has already logged
    `OW-D-051` about.
    """

    failure_class: str | None
    source: Source
    verdict: Verdict
    scope: Scope
    cooldown_ms: int | None
    message: str
    tier: int
    side_effect: str = ""
    diag_code: str | None = None

    @property
    def is_permanent(self) -> bool:
        return self.verdict is Verdict.PERMANENT

    @property
    def outcome(self) -> str:
        """The `Outcome` wire value this failure maps to. `needs_ocr` maps to neither.

        08:563 makes `needs_ocr` not a failure, so asking a `Failure` carrying it for an outcome
        is a caller bug rather than a value: the router escalates the named pages and no `work`
        transition is written at all. It raises for that reason instead of picking one.
        """
        if self.verdict is Verdict.NOT_A_FAILURE:
            raise StoreError(
                f"{self.failure_class} is routing data and not a failure (08-runtime.md:563), "
                f"so it maps to no Outcome",
                fix="escalate the named pages one Rung; do not complete the work row",
            )
        return "failed_permanent" if self.is_permanent else "failed_transient"


def rung_for(failure_class: str, source: Source) -> Rung | None:
    """The ladder row for a class, with the `timeout` split resolved by the source."""
    if failure_class == "timeout" and source is Source.HOST:
        return TIMEOUT_FROM_HOST
    return LADDER.get(failure_class)


def rate_limit_cooldown_ms(
    provider: str,
    declared_ms: int | None = None,
    overrides: Mapping[str, int] | None = None,
) -> int:
    """`rate_limited`'s first cooldown. 08:564 and 08:587-588, in precedence order.

    *"the driver's `retry_after_ms` if present, else `RATE_LIMIT_COOLDOWN_MS[provider]`"*, and
    *"a `Retry-After` header always overrides both"* -- which reaches here as `declared_ms`,
    because a driver that read a `Retry-After` header is required to put it in
    `DriverError.retry_after_ms` and there is no second channel for it.

    `overrides` is `[providers.<tag>] rate_limit_cooldown_ms`, merged over the shipped default by
    the caller's config layer rather than read from the environment here.
    """
    if declared_ms is not None:
        return declared_ms
    table = overrides if overrides is not None else RATE_LIMIT_COOLDOWN_MS
    if provider in table:
        return table[provider]
    return RATE_LIMIT_COOLDOWN_MS["default"]


def match_message(
    text: str, patterns: tuple[tuple[str, str], ...] = MESSAGE_PATTERNS
) -> str | None:
    """Tier 3. First case-insensitive substring match wins; `None` when nothing matches.

    `patterns` is a parameter with a default rather than a read of the module constant, so the
    three decisions `MESSAGE_PATTERNS`' docstring states -- ordered, first-match, case-insensitive
    -- are testable while the shipped table is empty. `classify()` always passes the default.
    """
    lowered = text.lower()
    for needle, failure_class in patterns:
        if needle.lower() in lowered:
            return failure_class
    return None


def _source_of(declared: FailureClass | str | None, exc: BaseException) -> Source:
    """Who observed it. The module docstring's "the `source` axis" section is the argument.

    `driver_crashed` is host-sourced whatever carries it (08:569: *"host -- exit status plus the
    stderr ring"*), because a driver cannot report its own death. Everything else is the host's
    only when the exception is a `DriverHostError`, which 02-architecture.md:1060 makes the one
    type a host-attributed fault travels as.
    """
    if declared is not None and str(declared) == FailureClass.DRIVER_CRASHED.value:
        return Source.HOST
    return Source.HOST if isinstance(exc, DriverHostError) else Source.DRIVER


def classify(
    declared: FailureClass | str | None,
    exc: BaseException,
    provider: str,
    status_code: int | None,
) -> Failure:
    """08:539-540's signature, and 08:535's three tiers tried in order.

    Pure and table-driven: nothing here reads a clock, a config file or an environment variable,
    and the same four arguments produce the same `Failure` on every machine. That is what lets the
    retry ladder be tested without a queue and what keeps `Failure.cooldown_ms` an offset rather
    than a timestamp -- `COMPLETE_SQL` adds it to the STORE's clock, because 08:600 requires that
    *"a backward NTP step on one worker must not make a row permanently unclaimable."*

    `provider` and `status_code` are *"not decoration: `status_code` drives tier 2, and `provider`
    selects the rate-limit cooldown in the table"* (08:555-556). Neither is `exc`: it carries the
    message tier 3 matches and `OW-D-051` records, it decides the `source` axis, and it is where a
    `Retry-After` arrives -- 08:588's *"a `Retry-After` header always overrides both"* reaches this
    function as `DriverError.retry_after_ms` and nowhere else.
    """
    message = str(exc)
    source = _source_of(declared, exc)

    # Tier 1 -- a structured FailureClass from the driver wins, and it is believed.
    if declared is not None:
        value = str(declared)
        rung = rung_for(value, source)
        if rung is None:
            raise StoreError(
                f"{value!r} is not one of the thirteen FailureClass members",
                fix="use omniweave_ports.types.FailureClass; the set is frozen (16-roadmap.md:498)",
            )
        cooldown = rung.first_cooldown_ms
        if value == FailureClass.RATE_LIMITED.value:
            # 08:564's precedence, and `exc` is the channel: a driver that read a `Retry-After`
            # header is required to put it in `DriverError.retry_after_ms`, and there is no second
            # place for it to arrive. `getattr` rather than an isinstance check because a
            # `HostVerdict` re-raised by a caller carries the same attribute and the same meaning.
            cooldown = rate_limit_cooldown_ms(provider, getattr(exc, "retry_after_ms", None))
        return Failure(
            failure_class=value,
            source=source,
            verdict=rung.verdict,
            scope=rung.scope,
            cooldown_ms=cooldown,
            message=message,
            tier=1,
            side_effect=rung.side_effect,
        )

    # Tier 2 -- the status code, because an exception crossing the S4 wire from a third-party
    # HTTP client routinely loses the class and keeps the code (08:546-548).
    if status_code is not None:
        mapped = STATUS_CODE_TIER.get(status_code)
        if mapped is None and SERVER_ERROR_FLOOR <= status_code < SERVER_ERROR_CEILING:
            mapped = ("upstream_unavailable", Verdict.TRANSIENT, Scope.ROW)
        if mapped is not None:
            value, verdict, scope = mapped
            rung = LADDER[value]
            cooldown = None
            if verdict is Verdict.TRANSIENT:
                cooldown = (
                    rate_limit_cooldown_ms(provider, getattr(exc, "retry_after_ms", None))
                    if value == FailureClass.RATE_LIMITED.value
                    else rung.first_cooldown_ms
                )
            return Failure(
                failure_class=value,
                source=source,
                verdict=verdict,
                scope=scope,
                cooldown_ms=cooldown,
                message=message,
                tier=2,
                side_effect=rung.side_effect,
            )

    # Tier 3 -- the message table, and only then.
    matched = match_message(message)
    if matched is not None:
        rung = LADDER[matched]
        cooldown = (
            rate_limit_cooldown_ms(provider, getattr(exc, "retry_after_ms", None))
            if matched == FailureClass.RATE_LIMITED.value
            else rung.first_cooldown_ms
        )
        return Failure(
            failure_class=matched,
            source=source,
            verdict=rung.verdict,
            scope=rung.scope,
            cooldown_ms=cooldown,
            message=message,
            tier=3,
            side_effect=rung.side_effect,
            diag_code=DIAG_UNCLASSIFIED,
        )

    # Unclassified. Fail toward retryable, and report the gap (08:570).
    return Failure(
        failure_class=None,
        source=source,
        verdict=Verdict.TRANSIENT,
        scope=Scope.ROW,
        cooldown_ms=UNCLASSIFIED_COOLDOWN_MS,
        message=message,
        tier=3,
        side_effect="Diag(OW-D-051) naming the raw message",
        diag_code=DIAG_UNCLASSIFIED,
    )


FIRST_COOLDOWN_MS: Final[Mapping[str, int | None]] = MappingProxyType(
    {failure_class: rung.first_cooldown_ms for failure_class, rung in LADDER.items()}
)
"""Each class's first cooldown, derived from `LADDER` so the two cannot disagree.

`rate_limited`'s entry is `None` and that is not a missing number: its cooldown is a function of
the provider and of any `Retry-After` the driver saw, and `rate_limit_cooldown_ms()` is the home.
"""


def escalate(attempts_total: int, first_cooldown_ms: int | None) -> int | None:
    """The ladder override. 08:590-593, and it is an override rather than a fallback.

    *"The escalation ladder overrides the classifier after the first attempt, so a policy with a
    generous first cooldown still converges."* `attempts_total` is the value the claim statement
    has ALREADY incremented -- the claim does `attempts_total = attempts_total + 1` before the
    attempt runs -- so the first attempt reaches here as 1, and `ESCALATION_MS[0]`'s `None` is what
    substitutes the classifier's own number.

    Returns `None` when the row has no rung left, which is `attempts_total >= MAX_WORK_ATTEMPTS`
    and means permanent: the claim predicate's `attempts_total < 5` makes the row unclaimable at
    that point whatever `retry_after` says, so returning a cooldown there would write a timestamp
    nothing will ever read.
    """
    if attempts_total < 1:
        raise StoreError(
            f"attempts_total is {attempts_total}; the claim increments it before the attempt runs, "
            f"so the first failure reaches the ladder at 1",
            fix="pass work.attempts_total as the claim returned it",
        )
    if attempts_total >= MAX_WORK_ATTEMPTS:
        return None
    rung = ESCALATION_MS[attempts_total - 1] if attempts_total - 1 < len(ESCALATION_MS) else None
    return first_cooldown_ms if rung is None else rung


# --------------------------------------------------------------------------------------------
# 5. The statements. Each transcribed from the one place the plan prints it.
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
`store/queue.py`'s module docstring argues why nothing is lost: one `dispatch_key` is one
`cost_class`.

**(b) `JOIN head h ON w.dispatch_key IS h.dispatch_key`, not `w.dispatch_key = head.dispatch_key`,
and a `LIMIT` that collapses to 1 for a NULL head.** This is a defect in the printed statement.
`dispatch_key` is *"NULL for an `op.*` row, AND A NULL BATCHES ALONE"* (0004_runtime.sql:104-105),
and `=` is never true of two NULLs -- so under the charter's SQL an `op.identify` row selected as
the head matches no row in the `picked` subquery, the UPDATE claims nothing, and `op.identify` is
unclaimable forever. Since `op.identify` *"is what CREATES the part rows the queue then drains"*
(08:619) and carries priority 300, the head is exactly where it would appear. `IS` matches NULL to
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
gives NULL out, which is seven of the eight transitions. The offset a caller binds is
`escalate(attempts_total, failure.cooldown_ms)`, so the ladder and the statement meet here and
nowhere else.

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

Empty at P3 -- `budget_reservation.decision_id` is `NOT NULL REFERENCES route_decision` and nothing
before P5 writes a `route_decision` row -- and correct the day it is not.
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
predicate is what ships and `lease_reaper` -- 08's, in `omniweave/run/`, W4.2 -- owns the liveness
check and the extension. `sqlite.py.process_create_time` is already the probe it needs. Recorded so
nobody reads the missing check as a bug in the store's method.
"""

COUNTS_SQL: Final = "SELECT status, count(*) FROM work GROUP BY status"
"""ONE query, and 0004_runtime.sql:137 is the comment that forbids the alternative.

*"NO COUNTER TABLE: `SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift."*
08:57-58 says the same from the runtime's side and names the counter-example: *"LDR maintains one by
hand and it drifts."* One query and not six, because six `SELECT count(*) WHERE status = ?` reads
are six index probes and, across a non-transactional loop, six inconsistent answers.
"""
