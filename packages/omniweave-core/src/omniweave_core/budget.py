"""The durable budget ledger: `Reservation`, the four statements, and headroom computed in SQL.

02-architecture.md section 2 row 19 is this module's charter, and the exclusion is half of it:

> | 19 | Budget | `omniweave_core.budget` | `BudgetLedger` over `budget_reservation`;
> `Reservation`; headroom **computed in SQL**, never cached in an attribute | **pricing
> (`Spend.micros(book)`'s job) and choosing a rung (INV-14)** | `BudgetLedger.reserve/commit/
> release/headroom` | T-SCHEMA |

16-roadmap.md:545 schedules it as P4 W4.5. 08-runtime.md Part 7 is the specification: section 7.1's
dimension table, section 7.2's three enforcement sites, section 7.3's four statements, section 7.4's
five exhaustion behaviours. 05-ingest-and-routing.md section 6.4 is the same ledger seen from the
routing side, and `0004_runtime.sql:222-240` is the table.

**Nothing here runs, and that is `work.py`'s boundary re-drawn one module over.** This file holds
the *statements*, the *domains* and the *identity recipe*; `omniweave_core.store.budget` submits
them, and `omniweave/route/admit.py` (P5 W5.3) decides what to ask for. A module that both defined
the ledger and spent against it would put admission policy inside core, which is the line
02-architecture.md section 3.2 draws and G4 gates.

## Four facts this module exists to keep true

**1. Headroom is computed in SQL, never cached in an attribute (I29).** `HEADROOM_SQL` is one
statement returning one integer, and there is no `self._headroom`. A cached figure is wrong the
moment another process reserves, and the ledger's whole job is to be right *across processes*:
05:2543 states the failure it prevents as *"two scheduler processes cannot each admit 2 and show
the provider 4"*.

**2. A reservation is a durable row, so a crash cannot leak headroom.** The reaper releases expired
reservations in the same transaction as the lease reap, and that statement is
`omniweave_core.work.REAP_RESERVATIONS_SQL` -- **not here**, because it is one statement inside the
reap's transaction and a second copy keyed on `expires_ms` would be a second home for one rule. See
`RESERVATION_REAP` below, which points at it rather than restating it.

**3. One decision takes one row per dimension it is capped on.** 08:2244-2249: the crash snapshot of
section 1.5 shows six `held` rows for three in-flight units, and *"the identity that produces
[`reservation_id`] includes `dim` -- otherwise four dimensions would collide on one id and three of
them would silently not be reserved."* `reservation_id()` takes `dim` for that reason and the test
asserts four dimensions of one attempt produce four distinct ids.

**4. `amount` is the p95 ceiling, not the mean.** 08:2251-2258: *"a reservation that
under-estimates admits work the budget cannot pay for. The over-reservation is released at commit,
so the cost of pessimism is throughput, not money."* Which dimensions get the multiple is
`OUTPUT_PROPORTIONAL`'s two, and 05:2470 is emphatic that `gpu_ms` is one of them -- *"on a
decode-bound VLM, GPU time is proportional to output tokens, so reserving the mean `gpu_ms` against
a p95 `tokens_out` reserves a number that cannot occur."*

## What is deliberately not here

**`admit()`.** 05:1841 homes it in `omniweave/route/admit.py` and 16-roadmap.md:605 schedules it as
P5 W5.3. It is *"the only impure half of routing"* and it runs strictly after the `route_decision`
row is written, so that a budget can never change which rung was chosen -- only whether it ran
(RT9). This module gives it the ledger to ask; the six-step ladder and the `Degraded` verdicts are
its own.

**`Spend` and `PriceBook`.** 02 row 35 homes both in `omniweave.route`, which core may not import:
`tools/layers.toml` gives `omniweave_core` exactly `["omniweave_ports"]`. Pricing is named in this
module's own exclusion column, and `micros` reaches the ledger as an integer that has already been
priced. `omniweave/route/spend.py` is the other half of W4.5 and lives in that distribution.

**`Estimate`.** 08:2260 says *"every `billed_api` operator implements `estimate(unit) -> Estimate`"*
and prints no shape; 05:2455-2462 prints the arithmetic that produces one and homes it in
`omniweave/route/estimate.py`, which 05:1835 makes *"the ONLY step that sees a PriceBook"*. It is
P5's, and inventing the type here would put the estimator's shape in the ledger's module.

Stdlib plus one intra-core import (INV-2, G1). No `sqlite3`: the statements here are text, and the
only thing that executes them is `omniweave_core.store.budget`.

Tier T-SCHEMA: 02-architecture.md section 2 row 19.

Specified in 02-architecture.md section 2 row 19, 08-runtime.md Part 7 (:2179-2331),
05-ingest-and-routing.md sections 6.3-6.5 (:2444-2600) and `0004_runtime.sql:222-240`.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol, TypeAlias

from omniweave_core.canonical import sha256_canonical

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.observe.degradation import Degradation

__all__ = [
    "ADMISSIONS",
    "COMMIT_SQL",
    "DIMS",
    "DIM_SCOPES",
    "HEADROOM_SQL",
    "INPUT_PROPORTIONAL",
    "OUTPUT_PROPORTIONAL",
    "PER_UNIT_MICROS_KEYS",
    "RELEASE_SQL",
    "RESERVATION_ID_BODY_LEN",
    "RESERVATION_ID_PREFIX",
    "RESERVATION_REAP",
    "RESERVATION_STATES",
    "RESERVE_SQL",
    "SCOPES",
    "UNCAPPED",
    "AdmissionVerdict",
    "Admitted",
    "BudgetLedger",
    "Deferred",
    "Degraded",
    "Reservation",
    "admission_of",
    "admit",
    "per_unit_micros",
    "requests",
    "reservation_id",
    "reserved_amount",
    "scope_key_for",
    "writes_exhausted",
]


# ---------------------------------------------------------------------------------------------
# 1. The three closed domains, and the table that pairs the first two.
# ---------------------------------------------------------------------------------------------

DIMS: Final[tuple[str, ...]] = (
    "micros",
    "tokens_in",
    "tokens_out",
    "calls",
    "gpu_ms",
    "wall_ms",
    "cpu_ms",
    "bytes_egress",
)
"""`budget_reservation.dim`'s CHECK, verbatim and in the DDL's order (0004_runtime.sql:227-228).

**Eight here and seven in `Spend`**, and the extra one is `micros`. That is the whole shape of the
cost model in one difference: a driver reports seven *physical* units and only the operator-owned
`PriceBook` turns them into money (INV-15), so `micros` is a dimension a budget is declared in and
never a dimension a driver reports. 05:2376-2380 gives the reason a contributor may not price:
*"a contributor on a rented A100 cannot know your GPU-hour cost, and if they guess, every estimate
in your fleet is wrong in a way you cannot audit."*

A tuple and not a `StrEnum`, for the reason `work.OUTCOMES` records: the CHECK is the domain, the
column stores the string, and a second enum would be a second home for a list SQLite already
enforces. `test_budget.py` reads the CHECK out of the shipped migration and asserts equality.
"""

SCOPES: Final[tuple[str, ...]] = ("run", "corpus", "unit", "part", "operator", "provider")
"""`budget_reservation.scope`'s CHECK, verbatim (0004_runtime.sql:230).

Six, and `provider` is the one that is not a unit of *work*: a `(dim='calls', scope='provider')`
held sum **is** the cross-process in-flight count (08:2196), which is why the provider semaphore is
a durable row rather than an in-memory counter. 08:700 states the failure that forces it --
*"two scheduler processes each holding an in-memory semaphore of 2 show the provider 4"* -- and it
is the reason `BILLED_API` is absent from the Supervisor's `class_sem` family.
"""

RESERVATION_STATES: Final[tuple[str, ...]] = ("held", "committed", "released")
"""`budget_reservation.state`'s CHECK, verbatim (0004_runtime.sql:234).

Three, and the arithmetic uses two of them: headroom subtracts `held` **and** `committed`, so a
released row is the only one that costs nothing. `released` is not a delete -- 08:2240's reap and
08:2243's cancel path both `UPDATE ... SET state='released'`, which keeps the row as evidence of a
reservation that was made and not spent.
"""

DIM_SCOPES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "micros": ("run", "corpus", "unit", "part", "operator"),
        "tokens_in": ("run", "part", "operator"),
        "tokens_out": ("run", "part", "operator"),
        "calls": ("provider", "run", "part"),
        "gpu_ms": ("run", "operator", "part"),
        "wall_ms": ("run", "unit"),
        "cpu_ms": ("run",),
        "bytes_egress": ("run", "corpus", "unit"),
    }
)
"""Where each dimension may be declared: **08:2186's table, unioned with the shipped policy. D142.**

08:2186-2200's *"scopes it is declared at"* column is the first source and it is transcribed row by
row. The second is 05:1279-1291, the `.omniweave/policy.d` block this framework **ships**, and the
two disagree about four dimensions:

| dim | 08:2186 says | 05:1279 declares it at | added here |
|---|---|---|---|
| `calls` | `provider`, `run` | `[budget.per_part] calls = 3` | `part` |
| `gpu_ms` | `run`, `operator` | `[budget.per_part] gpu_ms = 12_000` | `part` |
| `wall_ms` | `run` | `[budget.per_unit] wall_ms = 600_000` | `unit` |
| `bytes_egress` | `run`, `corpus` | `[budget.per_unit] bytes_egress = 0` | `unit` |

The four additions are not a widening of the plan; they are what the plan's own shipped policy
requires in order to load. Two further sites depend on the first of them: 02:563's worked admission
trace reserves `calls` and `gpu_ms` *"at `[budget.per_part]`"* beside `micros` at `scope='part'`,
and 05:2489's retry arithmetic concludes that *"what binds first on this pricebook is
`[budget.per_part] calls = 3`"* -- a sentence that is false if `calls` cannot be reserved per part.
`bytes_egress` is the one where the omission is most costly: `[budget.per_unit] bytes_egress = 0` is
what makes the first hosted escalation *"a deliberate act"*, and a unit-scoped cap that could not be
reserved would be a guard with no mechanism.

The table is a **declaration** table, not an enforcement one: the DDL's two CHECKs are independent,
so SQLite would accept `(dim='wall_ms', scope='part')`. `Reservation.__post_init__` is where that
pair is refused, because a reservation at a scope no budget is declared at holds headroom nothing
will ever release -- and after the work row settles, nothing can (see `store/budget.py`'s D141).
"""

OUTPUT_PROPORTIONAL: Final[tuple[str, ...]] = ("tokens_out", "gpu_ms")
"""The two dimensions the p95 multiple applies to. 05:2470-2473, and `gpu_ms` is the subtle one.

*"On a decode-bound VLM, GPU time is proportional to output tokens, so reserving the mean `gpu_ms`
against a p95 `tokens_out` reserves a number that cannot occur."* A reservation model that scaled
only `tokens_out` would admit a run whose GPU budget it had already blown.
"""

INPUT_PROPORTIONAL: Final[tuple[str, ...]] = ("tokens_in", "calls", "bytes_egress")
"""Reserved at their declared values: *"they are input-proportional and known before the call"*.

05:2473. The three time dimensions are in neither tuple: `wall_ms`, `cpu_ms` and the `micros` total
are derived rather than declared per call, and `micros` is the priced roll-up of whatever the other
seven came to.
"""

UNCAPPED: Final = -1
"""`headroom()`'s limit for a dimension no budget declares: unbounded, and it is not `0`.

`bytes_egress` makes the distinction load-bearing. Its **default is 0** (08:2202), which means the
first hosted escalation is a deliberate act requiring a site-layer `Grant`; so a `0` limit is a real
cap that denies, and "no cap declared" needs a value that cannot be confused with it. A negative
sentinel rather than `None` because the column is `INTEGER NOT NULL` and the SQL binds `:limit`
directly -- and `headroom()` refuses to bind this one at all.
"""


# ---------------------------------------------------------------------------------------------
# 2. `reservation_id` -- content-addressed, so a retried reserve is idempotent.
# ---------------------------------------------------------------------------------------------

RESERVATION_ID_PREFIX: Final = "res_"
"""08:2236 -- `reservation_id = 'res_' || sha256_canonical(identity)[:24]`."""

RESERVATION_ID_BODY_LEN: Final = 24
"""The digest prefix length, so an id is 28 characters. 08:2236."""


def reservation_id(work_id: int, decision_id: str, attempt: int, dim: str) -> str:
    """`'res_' + sha256_canonical((work_id, decision_id, attempt, dim))[:24]`. 08:2238-2239.

    *"The id is content-addressed over `(work_id, decision_id, attempt, dim)`, so a retried reserve
    is idempotent AND one reservation per dimension is a distinct row."* Both halves are load
    bearing and they pull in opposite directions: drop `attempt` and a second attempt on one
    decision silently re-uses the first attempt's row; drop `dim` and *"four dimensions would
    collide on one id and three of them would silently not be reserved"* (08:2248).

    `sha256_canonical` and not a format string, because the identity is a tuple of mixed types and
    `canonical()` is the one place this repository decides how a tuple becomes bytes. The digest is
    truncated to 24 characters, which is 96 bits -- the birthday bound over a run's reservations is
    not close.
    """
    if dim not in DIMS:
        raise ValueError(f"{dim!r} is not one of budget_reservation's eight dims {DIMS}")
    if attempt < 1:
        raise ValueError(f"attempt is {attempt}; attempts are 1-based (05:2560)")
    identity = [work_id, decision_id, attempt, dim]
    return RESERVATION_ID_PREFIX + sha256_canonical(identity)[:RESERVATION_ID_BODY_LEN]


def scope_key_for(
    scope: str,
    *,
    unit_uri: str = "",
    unit_part: str = "",
    operator: str = "",
    provider: str = "",
    corpus: str = "",
    run_id: str = "",
) -> str:
    """The `scope_key` a reservation at `scope` is keyed by. One place, so two callers agree.

    `budget_reservation.scope_key` is `TEXT NOT NULL DEFAULT ''` and the DDL says nothing about
    its content, which makes it the kind of column two call sites disagree about: a `part`-scoped
    reservation keyed `'p3'` by one process and `'file:///a.pdf#p3'` by another shares no headroom
    with itself. 05:2523 fixes the grain in prose -- *"per-part dimensions are charged per
    `(unit_part, lane)`: two lanes on one part have two budgets"* -- and 08:2186's table fixes the
    rest. This function is that prose, executed.

    The `run` scope keys on the run id rather than on `''`, because a store outlives a run and a
    `run`-scoped cap that keyed on the empty string would be a cap on *every* run the store has
    ever held.
    """
    keys: Mapping[str, str] = {
        "run": run_id,
        "corpus": corpus,
        "unit": unit_uri,
        "part": f"{unit_uri}#{unit_part}" if unit_part else unit_uri,
        "operator": operator,
        "provider": provider,
    }
    if scope not in keys:
        raise ValueError(f"{scope!r} is not one of budget_reservation's six scopes {SCOPES}")
    key = keys[scope]
    if not key:
        raise ValueError(
            f"a {scope!r}-scoped reservation needs a key; an empty one shares headroom with "
            f"every other {scope} in the store"
        )
    return key


def reserved_amount(declared: int, dim: str, p95_multiple: float) -> int:
    """The p95 **ceiling** for one dimension: the declared value, scaled if it is output-bound.

    05:2459-2462 prints the recipe -- *"`reserved_micros` = `est_spend` with its
    OUTPUT-PROPORTIONAL dimensions x `tokens_out_p95_multiple`, priced <- THE p95 CEILING"* -- and
    05:2470-2473 says which dimensions those are and which are left alone.

    Rounded **up**, because a reservation that rounds down under-reserves, and 08:2251 is explicit
    that *"a reservation that under-estimates admits work the budget cannot pay for"*. The cost of
    rounding up is at most one unit of headroom per dimension per attempt, released at commit.
    """
    if dim not in DIMS:
        raise ValueError(f"{dim!r} is not one of budget_reservation's eight dims {DIMS}")
    if declared < 0:
        raise ValueError(f"a declared {dim} of {declared} is not a quantity")
    if p95_multiple < 1.0:
        raise ValueError(
            f"tokens_out_p95_multiple is {p95_multiple}; a multiple below 1.0 reserves less than "
            f"the estimate, which is the under-reservation 08:2251 refuses"
        )
    if dim not in OUTPUT_PROPORTIONAL:
        return declared
    return -int(-declared * p95_multiple // 1)


# ---------------------------------------------------------------------------------------------
# 3. `Reservation` -- one row of `budget_reservation`.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reservation:
    """One `budget_reservation` row. 0004_runtime.sql:222-235, column names and order verbatim.

    **`expires_ms` == the work row's `lease_expires`, and the equality is the crash story.** 08:2242
    and 05:2530 both say so, and `work.REAP_RESERVATIONS_SQL` relies on it from the other side: the
    reaper finds expired reservations *through their work rows* and releases them in the reap's own
    transaction, so a SIGKILLed worker cannot leak headroom. A reservation with a longer expiry than
    its lease would survive its own work row's return to the queue.

    **`claimed_gen` is here for the same reason it is on `work`**: a late result from a superseded
    generation must not commit a reservation the current generation is relying on.

    `state` starts at `'held'` and every constructor here mints one -- a `Reservation` is what
    `reserve` inserts, and `commit` and `release` move the row by `reservation_id` rather than by
    rebuilding the object.
    """

    reservation_id: str
    run_id: str
    work_id: int
    decision_id: str
    dim: str
    amount: int
    scope: str
    scope_key: str
    claimed_gen: int
    expires_ms: int
    state: str = "held"

    def __post_init__(self) -> None:
        """The three CHECKs the DDL carries, plus the one pairing it cannot express.

        SQLite validates `dim`, `scope` and `state` independently, so it accepts
        `(dim='wall_ms', scope='part')` -- a pair 08:2194 declares at no scope smaller than the run.
        A reservation at an undeclared pair holds headroom against a limit that will never be
        configured, so nothing releases it until the lease expires. The refusal is here because a
        value type is where a caller learns it, and because `DIM_SCOPES` is the table that knows.
        """
        if self.dim not in DIMS:
            raise ValueError(f"{self.dim!r} is not one of {DIMS}")
        if self.scope not in SCOPES:
            raise ValueError(f"{self.scope!r} is not one of {SCOPES}")
        if self.state not in RESERVATION_STATES:
            raise ValueError(f"{self.state!r} is not one of {RESERVATION_STATES}")
        if self.scope not in DIM_SCOPES[self.dim]:
            raise ValueError(
                f"08:2186 declares {self.dim!r} at {DIM_SCOPES[self.dim]}, not at "
                f"{self.scope!r}: a reservation at an undeclared pair holds headroom against a "
                f"limit nothing will configure"
            )
        if self.amount < 0:
            raise ValueError(f"a reservation of {self.amount} {self.dim} is not a quantity")
        if not self.scope_key:
            raise ValueError(
                "scope_key is what a reservation shares headroom with; see scope_key_for"
            )

    def as_params(self) -> Mapping[str, object]:
        """The named parameters `RESERVE_SQL` binds. One mapping, so the two cannot drift."""
        return MappingProxyType(
            {
                "reservation_id": self.reservation_id,
                "run_id": self.run_id,
                "work_id": self.work_id,
                "decision_id": self.decision_id,
                "dim": self.dim,
                "amount": self.amount,
                "scope": self.scope,
                "scope_key": self.scope_key,
                "claimed_gen": self.claimed_gen,
                "expires_ms": self.expires_ms,
                "state": self.state,
            }
        )


# ---------------------------------------------------------------------------------------------
# 4. The four statements. 08:2224-2243.
# ---------------------------------------------------------------------------------------------

HEADROOM_SQL: Final = """
SELECT :limit
     - COALESCE((SELECT SUM(amount) FROM budget_reservation
                  WHERE dim=:dim AND scope=:scope AND scope_key=:key AND state='held'), 0)
     - COALESCE((SELECT SUM(amount) FROM budget_reservation
                  WHERE dim=:dim AND scope=:scope AND scope_key=:key AND state='committed'), 0)
"""
"""08:2226-2233. *"Headroom, ALWAYS computed in SQL, never cached in an attribute"* (I29).

Two subqueries and not one `state IN ('held','committed')`, which is how the plan prints it and is
also how the partial index wants it: `res_open ON budget_reservation(dim, scope, scope_key) WHERE
state='held'` covers the first exactly, and the second scans the same three-column prefix. Folding
them into one predicate would give SQLite a disjunction the partial index cannot serve.

`COALESCE(..., 0)` on both, because `SUM` over no rows is `NULL` and `:limit - NULL` is `NULL`:
a dimension with no reservations yet would report headroom `NULL`, which every comparison would
read as "not less than the request" and admit.
"""

RESERVE_SQL: Final = """
INSERT OR IGNORE INTO budget_reservation(
    reservation_id, run_id, work_id, decision_id, dim, amount,
    scope, scope_key, claimed_gen, expires_ms, state)
VALUES(:reservation_id, :run_id, :work_id, :decision_id, :dim, :amount,
       :scope, :scope_key, :claimed_gen, :expires_ms, :state)
"""
"""08:2236-2239. `INSERT OR IGNORE`, and the `OR IGNORE` is what makes the idempotence real.

The plan says *"a retried reserve is idempotent"* and gives the reason -- the id is content
addressed -- but a content-addressed primary key alone makes a retry an `IntegrityError`, not a
no-op. `INSERT OR IGNORE` is idempotency mechanism 2 of 08:428, whose own warning applies in
reverse here: *"`INSERT OR IGNORE` with no UNIQUE index to conflict on is a plain `INSERT`"*.
`reservation_id` is the PRIMARY KEY, so there is one to conflict on.

A retried reserve that ignores is **not** a second reservation: the first row is still `held` at the
same amount, so headroom already reflects it. That is the behaviour a crash between the insert and
the caller's acknowledgement needs.
"""

COMMIT_SQL: Final = """
UPDATE budget_reservation SET state='committed', amount=:amount
 WHERE reservation_id=:reservation_id AND state='held'
"""
"""08:2240-2242. The p95 ceiling becomes the ACTUAL, which is what releases the over-reservation.

**`AND state='held'` is the whole safety of this statement.** It is the same shape as the work
transition's commit predicate: a reservation already committed or already released updates zero
rows, so a late result from a superseded generation cannot rewrite a settled amount, and a
double-commit cannot double-count. The caller reads `rowcount` to learn which happened.

*"IN THE SAME TRANSACTION as the derived rows, the work transition, the dep rows and the spend
row (I20)"* -- which is `omniweave_core.store.queue.SqliteStore`'s `reservation_commit`
participant, and `omniweave_core.store.budget.reservation_commit_statements()` is what builds it.
This constant is the single statement both that participant and any repair path submit.
"""

RELEASE_SQL: Final = """
UPDATE budget_reservation SET state='released'
 WHERE reservation_id=:reservation_id AND state='held'
"""
"""08:2243 -- *"cancel, or a cache hit"*.

**A cache hit releases rather than commits**, and that is I25 from the ledger's side: a hit
*"returns with `was_cache_hit=True` and `Spend` replayed from `cache_index.spend_json`; zero budget,
zero tokens, zero rate-limit slots consumed"* (02:481). Committing a hit at zero would leave a
`committed` row of amount 0, which is harmless arithmetically and wrong as a record: nothing was
paid, so nothing was spent, and `route_spend.was_cache_hit` is where the hit is recorded.

`AND state='held'` for the reason `COMMIT_SQL` carries it: releasing a committed reservation would
hand back headroom that was actually spent.
"""

RESERVATION_REAP: Final = "omniweave_core.work.REAP_RESERVATIONS_SQL"
"""The fifth statement is NOT here, and this constant is the pointer rather than a copy.

08:2244 prints `reap UPDATE ... SET state='released' WHERE expires_ms < :now AND state='held'` and
adds *"IN THE SAME TRANSACTION as the lease reap, so a SIGKILL cannot leak headroom"*. That
transaction is `work.py`'s, the statement went there with W4.1, and its docstring records the one
deviation it makes and why: it joins to the work rows about to be reaped rather than comparing
`expires_ms`, and it must run **before** the work reap or the subquery selects nothing.

A second reap keyed on `expires_ms` would be a second home for one rule, and the two would disagree
the first time a lease was extended. INV-21 does not care that both would be correct today.
"""


# ---------------------------------------------------------------------------------------------
# 5. `BudgetLedger` -- the boundary. Four methods, and one of them is not a loop.
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# 6. `admit()` -- steps 4-6 of 05:2519's ladder. The three-valued verdict.
# ---------------------------------------------------------------------------------------------


PER_UNIT_MICROS_KEYS: Final[tuple[str, str, str]] = (
    "micros_base",
    "micros_per_part",
    "micros_max",
)
"""The three `[budget.per_unit]` keys that make one `micros` cap. 05:1285-1288.

```
[budget.per_unit]                    # base + per_part x part_count, clamped. NO EXPRESSIONS.
micros_base     = 4_000
micros_per_part = 3_000
micros_max      = 16_000_000
```

Three keys and not an expression, and the comment says why in capitals: a policy file that could
carry arithmetic would be a policy file somebody has to evaluate, and `ow route lint` resolves keys
rather than parsing a language. The shipped numbers are their own worked example --
`4,000 + 3,000 x 5,000 = 15,004,000`, *"the largest priced document"*, under a 16,000,000 ceiling.
"""


def per_unit_micros(limits: Mapping[str, int], *, part_count: int) -> int:
    """`clamp(micros_base + micros_per_part x part_count, 0, micros_max)`. 05:2515, executed.

    **This is the only per-unit dimension that scales**, and the line after it says so: *"every
    other per_unit dimension is a scalar and is not scaled by part_count"*. `wall_ms = 600_000` is
    ten minutes per unit whether the unit has one part or five thousand, and `bytes_egress = 0` is a
    refusal rather than a rate.

    `part_count` comes from `unit.part_count`, which `op.identify` writes and which `05:1386`
    guarantees is NOT NULL by the time the router runs -- *"`op.identify` precedes routing"*. A
    caller holding a NULL has a unit that has not been identified and has no business admitting
    work for it.

    The clamp's lower bound is 0 and it is not decoration: `micros_base` and `micros_per_part` are
    `INTEGER` and a policy that set either negative would otherwise produce a cap that grows as the
    document shrinks. `max()` first, then `min()`, so a `micros_max` below `micros_base` yields
    `micros_max` -- the operator's ceiling wins over the operator's floor, which is the direction
    that cannot overspend.
    """
    if part_count < 0:
        raise ValueError(f"a part_count of {part_count} is not a count")
    missing = tuple(key for key in PER_UNIT_MICROS_KEYS if key not in limits)
    if missing:
        raise ValueError(
            f"[budget.per_unit] needs {PER_UNIT_MICROS_KEYS} to make one micros cap; "
            f"{missing} are absent (05:1285)"
        )
    base = limits["micros_base"] + limits["micros_per_part"] * part_count
    return min(max(base, 0), limits["micros_max"])


def requests(
    estimate: Mapping[str, int],
    *,
    limits: Mapping[str, int],
    scope: str,
    scope_key: str,
    run_id: str,
    work_id: int,
    decision_id: str,
    attempt: int,
    claimed_gen: int,
    expires_ms: int,
    p95_multiple: float,
) -> tuple[Reservation, ...]:
    """One `Reservation` per declared dimension, at the p95 ceiling, in `DIMS` order.

    `estimate` is the decision's `est_spend` as a dimension map -- the seven physical units plus the
    priced `micros` -- and `limits` is the `[budget.per_part]` or `[budget.per_unit]` table the
    scope belongs to. A dimension the policy does not declare gets no row: `05:2523`'s ladder
    reserves *"`reserved_micros` and every other **declared** dimension"*, and a reservation at a
    dimension nothing caps would hold headroom against a limit that does not exist.

    **The order is `DIMS`' order and that is what makes "first exhausted wins" reproducible.**
    `05:2506`'s heading is *"first exhausted dimension wins"* and `02:563` gives the reason -- *"a
    count cannot bound spend when per-attempt cost varies 100x with page density"* -- but neither
    says *which* first. `SqliteBudgetLedger.reserve()` checks in the order it is handed, so the
    order is this function's, and `DIMS` is `Spend`'s printed order rather than a dict's insertion
    order or a sort. Two runs over one corpus must report the same bound dimension or the
    scoreboard's `deferred_by_dim` is noise.

    Every amount goes through `reserved_amount()`, so the two output-proportional dimensions are
    scaled by `tokens_out_p95_multiple` and the input-proportional ones are not (`05:2470`).

    `attempt` reaches the id and not the row. `reservation_id()` is
    `'res_' || sha256_canonical(identity)[:24]` over `(work_id, decision_id, attempt, dim)`
    (`08:2236`), so a retried reserve is idempotent *within* one attempt and distinct *across* them;
    `budget_reservation` itself carries no `attempt` column, because the row is reachable from
    `work_id` and the attempt is already in its primary key.
    """
    rows: list[Reservation] = []
    for dim in DIMS:
        if dim not in limits or dim not in estimate:
            continue
        rows.append(
            Reservation(
                reservation_id=reservation_id(work_id, decision_id, attempt, dim),
                run_id=run_id,
                work_id=work_id,
                decision_id=decision_id,
                dim=dim,
                amount=reserved_amount(estimate[dim], dim, p95_multiple),
                scope=scope,
                scope_key=scope_key,
                claimed_gen=claimed_gen,
                expires_ms=expires_ms,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class Admitted:
    """Step 6: *"a durable reservation row whose expiry == the work row's `lease_expires`"*.

    `reservations` is what was inserted, so the caller has the ids it must commit or release. It is
    empty for a `free` decision -- `02:478`'s hop 8 is exactly that case, *"`Admitted(reservations=
    ())` -- a `free` decision reserves nothing"* -- and an empty admission is therefore not a
    contradiction the way an empty `reserve()` call is.
    """

    reservations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Deferred:
    """Step 5: the first dimension whose headroom was below the request. **Not exhaustion.**

    `05:2532`: *"A reservation denial is not exhaustion. Step 5 returns `Deferred(dim)`, the work
    row stays claimable and `cost_micros` is unchanged; on commit, the gap between
    `reserved_micros` and the `route_spend` row's actual `micros` is released in the same
    transaction, which can lift the very denial that just fired."*

    The dimension is the whole of what the operator is told, and `08:2270`'s table is written that
    way: a deferral names a knob, and a deferral that named none would send an operator to read the
    ledger.
    """

    dim: str

    def __post_init__(self) -> None:
        if self.dim not in DIMS:
            raise ValueError(f"{self.dim!r} is not one of the eight dims {DIMS}")


@dataclass(frozen=True, slots=True)
class Degraded:
    """Steps 1-3: admitted at a cheaper driver, or refused for a reason that is not headroom.

    **Degraded is not a denial.** `05:2519`'s steps 1-3 -- the cost-class clamp, the licence tier
    and the egress grant -- each produce a `Degradation` and the work still runs, which is why
    `route_decision.admission`'s CHECK has three values rather than two and why only `deferred`
    short-circuits the middleware.

    This module produces none of the three: all three need a `RouteDecision`, a `DriverCard` and a
    `Grant`, and `omniweave/route/admit.py` (W5.3) is where those are in scope. The type is here
    because `05:1841`'s printed return type is `"Admitted | Deferred | Degraded"` and a union whose
    third member lived in another distribution could not be written down in core at all.
    """

    degradations: tuple[Degradation, ...] = ()

    def __post_init__(self) -> None:
        if not self.degradations:
            raise ValueError(
                "a degraded admission carries the Degradation that explains it; 05:2519's three "
                "steps each name a kind, and a degradation with no record is a silent downgrade"
            )


AdmissionVerdict: TypeAlias = "Admitted | Deferred | Degraded"
"""`05:1841`'s printed return type, as a name. `admit(d, ledger) -> Admitted | Deferred | Degraded`.

Spelled as an alias rather than left inline because three call sites name it -- this module's
`admit()`, `route/admit.py`'s wrapper, and the middleware's projection -- and `route_decision`'s
`admission` column carries the three lower-cased strings its CHECK declares.
"""

ADMISSIONS: Final[Mapping[type, str]] = MappingProxyType(
    {Admitted: "admitted", Deferred: "deferred", Degraded: "degraded"}
)
"""Each verdict's `route_decision.admission` value. The column's CHECK, as a projection.

A mapping from the type rather than a method on each, so the three values live in one place beside
the column they are written to -- and so a fourth verdict class is a missing key rather than a
missing method nobody notices until the INSERT.
"""


def admission_of(verdict: AdmissionVerdict) -> str:
    """The `route_decision.admission` string for a verdict. One lookup, one home."""
    value = ADMISSIONS.get(type(verdict))
    if value is None:
        raise ValueError(f"{type(verdict).__name__} is not one of {sorted(ADMISSIONS.values())}")
    return value


def admit(
    reservations: Sequence[Reservation], *, ledger: BudgetLedger, limits: Mapping[str, int]
) -> Admitted | Deferred:
    """Steps 4-6 of `05:2519`'s ladder: reserve every declared dimension, or name what bound.

    ```
    4. reserve reserved_micros and every other declared dimension against budget_reservation,
       per (dim, scope, scope_key), with headroom computed IN SQL
    5. the first dimension whose headroom is below the request -> Deferred(dim)
    6. otherwise Admitted, with a durable reservation row whose expiry == the work row's
       lease_expires
    ```

    **Steps 1-3 are not here and cannot be.** The cost-class clamp needs the GATE-established
    `max_cost_class` off a `RouteDecision`; the licence check needs `compute_tier(card)` and the
    `[licence] allow_tiers` list; the egress check needs a site-layer `Grant`. All three live in
    `omniweave`, which `tools/layers.toml` forbids core from importing, and all three are W5.3's
    row -- *"one impure function over W4.5's ledger"*, which is this one.

    **It is impure, and it is the only impure thing in the admission path.** `05:1838` says so of
    `route/admit.py` and the reason is RT9: it runs strictly after the `route_decision` row is
    written, *"so a budget can never change which rung was chosen -- only whether it ran."* Nothing
    here reads a rung, a lane or a rule.

    **Two rows sharing one `reservation_id` is refused before the ledger sees them. D173.**
    `08:2238`'s identity is `(work_id, decision_id, attempt, dim)` and carries no scope, while
    `DIM_SCOPES` declares five of the eight dimensions at more than one scope and the shipped policy
    caps `micros` at both `[budget.per_part]` and `[budget.per_unit]`. One work row reserving
    `micros` at both scopes in one attempt therefore mints one id for two rows, and
    `budget_reservation.reservation_id` is the PRIMARY KEY -- so one of the two would silently not
    be reserved -- exactly the failure `08:2248` describes for a missing `dim`. A `ValueError` here
    turns a silent half-reservation into a refusal the caller can read.

    An empty `reservations` is `Admitted(())` rather than a refusal, because `02:478`'s free
    decision reserves nothing and reaching the ledger to say so would take the write lock to insert
    no rows. `SqliteBudgetLedger.reserve()` refuses an empty sequence for the opposite reason, and
    both are right: a reservation-free admission is ordinary, a reservation-free *reserve* is a bug.
    """
    if not reservations:
        return Admitted(())
    seen: dict[str, tuple[str, str]] = {}
    for row in reservations:
        clash = seen.get(row.reservation_id)
        if clash is not None:
            raise ValueError(
                f"{row.dim!r} at {row.scope}/{row.scope_key} and at {clash[0]}/{clash[1]} share "
                f"one reservation_id: 08:2238's identity is (work_id, decision_id, attempt, dim) "
                f"and carries no scope, so two scopes for one dimension collide on the primary "
                f"key and one of the two would silently not be reserved (D173)"
            )
        seen[row.reservation_id] = (row.scope, row.scope_key)
    denied = ledger.reserve(reservations, limits)
    if denied is not None:
        return Deferred(denied)
    return Admitted(tuple(row.reservation_id for row in reservations))


def writes_exhausted(*, siblings_in_flight: int) -> bool:
    """Whether a deferral may write `budget.exhausted` into `Evidence`. **05:2534's clause.**

    *"`budget.exhausted` is written into `Evidence` -- and `on_exhausted` therefore consulted --
    only when a deferred row is re-offered with **no sibling reservation still in flight for the
    same scope key**. Without that clause a p95 reservation model degrades the second half of every
    document while spending a third of the cap, which is exactly what the section 10.3 trace makes
    visible."*

    The arithmetic behind it is `05:2545`'s: at `tokens_out_p95_multiple = 3.2`, in-flight
    reservations consume 3.2x the eventual spend, so a document's later parts are denied against
    headroom its earlier parts are *holding and will release*. Consulting `on_exhausted` there would
    spill to a free driver, or emit a partial, on a budget that was never actually spent.

    `siblings_in_flight` is `count(*) FROM budget_reservation WHERE state='held'` for the same
    `(dim, scope, scope_key)`, excluding the deferred row's own -- which holds none, since step 5
    denies before step 4's inserts. This module states the predicate; the query belongs to the
    ledger and the write-back to `route/admit.py` (W5.3), because `Evidence` is W5.1's type.
    """
    if siblings_in_flight < 0:
        raise ValueError("siblings_in_flight is a count of held rows")
    return siblings_in_flight == 0


class BudgetLedger(Protocol):
    """The four calls 02-architecture.md row 19 names, over `budget_reservation`.

    A `Protocol` and not a base class, for the reason every boundary in this repository is one:
    `omniweave_core.store.budget.SqliteBudgetLedger` satisfies it structurally, `RunContext.budget`
    names it, and a distributed backend (08 section 9.2's seam) can supply another without an
    inheritance edge into core.

    **Synchronous, and 08:298-320 makes that normative rather than incidental.** `RunContext` is
    defined in `omniweave_core.operator` and carries this type, and the third of the three reasons
    core may hold that definition is this one: *"`budget: BudgetLedger` is synchronous. Headroom is
    computed **in SQL on a synchronous connection** (section 7.3), never awaited and never cached in
    an attribute."* An `async def` here would move `RunContext` out of core and invert the
    dependency direction the charter exists to enforce.

    **`commit()` is on the boundary and the runner does not call it.** I20 requires the
    held-to-committed transition to land in the same transaction as the derived rows, the work
    transition, the dep rows and the spend row, and `SqliteStore`'s `reservation_commit`
    participant is that path. This method submits the **same** `COMMIT_SQL` on its own, for the
    callers that are outside a `complete()` -- a repair path, and the tests that need to observe
    one statement at a time. One statement, two submitters; `test_budget.py` asserts they are the
    same string, so there is no second home for the predicate that makes the commit safe.
    """

    def headroom(self, dim: str, scope: str, scope_key: str, limit: int) -> int:
        """`limit - sum(held) - sum(committed)`, in SQL. Never cached, never an attribute."""
        ...

    def reserve(self, reservations: Sequence[Reservation], limits: Mapping[str, int]) -> str | None:
        """Reserve every dimension atomically. `None` on success, else the FIRST exhausted `dim`.

        One transaction for all of them, because 05:2527's step 5 -- *"the first dimension whose
        headroom is below the request"* -- is only a well-defined answer if no other process can
        reserve between the check and the insert. `limits` is keyed by `dim`; a dimension absent
        from it is `UNCAPPED`.
        """
        ...

    def commit(self, reservation_id: str, amount: int, /) -> bool:
        """Held -> committed at the ACTUAL amount. `False` if the row was not `held`.

        **Positional-only, and the `/` is load-bearing.** A Protocol whose parameters have names
        promises those names to every implementor, and `SqliteBudgetLedger` spells this one
        `reservation_id_` -- with the underscore, because `reservation_id()` is a module-level
        function in *this* module and the store's method would otherwise shadow it. A boundary that
        promised the keyword would make that a conformance break, which is exactly what it was
        until `admit()` became the first caller to pass one where the other is expected. The
        boundary promises an order; the argument has one obvious position.
        """
        ...

    def release(self, reservation_id: str, /) -> bool:
        """Held -> released. `False` if the row was not `held`. A cache hit takes this path."""
        ...
