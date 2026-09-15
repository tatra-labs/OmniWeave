"""`admit()` -- the only impure half of routing, and the one channel budget reaches a decision by.

05-ingest-and-routing.md:1838 prints the module and says what it is in two sentences:

```python
# omniweave/route/admit.py — IMPURE, and the only impure half of routing. It runs strictly AFTER
# the `route_decision` row is written (§4.3 property 6), so a budget can never change which rung
# was chosen — only whether it ran (RT9).
def admit(d: "RouteDecision", ledger: "BudgetLedger") -> "Admitted | Deferred | Degraded": ...
```

Section 6.4 (:2519) prints the six steps, and this module is those six steps:

```
1. clamp:   d.driver's cost_class above the GATE-established max_cost_class
            -> Degraded(Degradation(kind="budget", unit_dim="max_cost_class", …))
2. licence: compute_tier(card) not in [licence] allow_tiers -> Degraded(kind="driver_unavailable")
3. egress:  est_spend.bytes_egress > 0 with no site-layer Grant -> Degraded(kind="grant_missing")
4. reserve reserved_micros and every other declared dimension against budget_reservation,
   per (dim, scope, scope_key), with headroom computed IN SQL
5. the first dimension whose headroom is below the request -> Deferred(dim)
6. otherwise Admitted, with a durable reservation row whose expiry == the work row's lease_expires
```

**Steps 4-6 are `omniweave_core.budget.admit()`'s and are not re-implemented here.** They reserve,
they read headroom in SQL, and they name the bound dimension; none of that needs a `RouteDecision`.
Steps 1-3 are here because each compares something only this distribution can see -- a driver's
cost class against the GATE-established ceiling, `compute_tier(card)` against `[licence]
allow_tiers`, and an estimated egress against a site-layer `Grant`.

## Why there is a third argument, and why the plan's two are still the free path

05:1841 prints `admit(d, ledger)` and 02-architecture.md:478's hop 8 prints the same pair. Steps
1-3 compare four facts neither argument carries: `RouteDecision` has a `driver` **id** and no cost
class, no `max_cost_class` (that is `Modifiers`', and 05:1988 keeps the modifier family off the
decision on purpose), no estimate and no grant. So `AdmissionRequest` gathers exactly what the
three steps read and nothing else, and it **defaults to the free path**: `admit(d, ledger)` with
no request is `Admitted(())`, which is hop 8's own case -- *"a `free` decision reserves nothing"*.
The plan's printed signature is therefore not superseded, it is the zero-argument call. D212 files
the gap.

This is the same shape 05:1845 already applies to `evaluate()`: the charter prints three parameters,
this document prints six, and the paragraph after the fence explains the difference rather than
pretending the shorter form was wrong.

## RT9, stated as what this module may not read

05:3349: *"exhaustion re-enters as the evidence key `budget.exhausted`, **written by `admit()`** and
read only by the `DEGRADE` rules; `admit()` is the sole impure half of routing and runs strictly
after `route_decision` is written, so a budget change can never alter which rung a document would
have taken."*

Nothing here reads a rung, a lane or a rule, and nothing here returns a rung. The only thing this
module writes into the router's own world is one boolean, through `Evidence.put()`, under one
condition -- and `write_exhausted()` is that condition, executed.

## The condition, and the count nobody can answer

05:2534: *"`budget.exhausted` is written into `Evidence` -- and `on_exhausted` therefore
consulted -- only when a deferred row is re-offered with **no sibling reservation still in flight
for the same scope key**. Without that clause a p95 reservation model degrades the second half of
every document while spending a third of the cap."*

`writes_exhausted(siblings_in_flight=...)` in core is the predicate. The **count** is not derivable
from `BudgetLedger`'s four calls: `HEADROOM_SQL` subtracts held *and* committed in one expression,
so `headroom == limit` means "nothing reserved and nothing ever spent" rather than "nothing in
flight", and §10.3's own trace has a committed 2,000 before the first reservation. Local bookkeeping
cannot substitute either, because the ledger is durable precisely so that *"two scheduler processes
cannot each admit 2 and show the provider 4"* (05:2543) -- a sibling held by another process is the
one whose release would lift the denial. So `write_exhausted()` takes the count, and D211 files the
gap.

## What is not here

`price()` is `route/estimate.py`'s (05:1832) and is pure over `(decision, catalog, book)`. The
reservation rows are `omniweave_core.budget.requests()`'. The SQL is the store's. The drain loop
that re-offers a deferred row is `omniweave.run`'s.

Specified in 05-ingest-and-routing.md sections 4.6, 6.4, 6.5 and 10.3; RT9 at 05:3349; scheduled by
16-roadmap.md:605.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from omniweave_core.budget import Degraded, writes_exhausted
from omniweave_core.budget import admit as reserve_all
from omniweave_core.drivers.resolve import COST_CLASS_ORDER
from omniweave_core.observe.degradation import Degradation
from omniweave_ports.types import CostClass, LicenceTier

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Mapping, Sequence

    from omniweave_core.budget import AdmissionVerdict, BudgetLedger, Reservation
    from omniweave_core.drivers.licence import Grant

    from omniweave.route.decision import RouteDecision
    from omniweave.route.evidence import Evidence

__all__ = [
    "ADMIT_PROVIDER",
    "EXHAUSTED_KEY",
    "EXHAUSTED_VERSION",
    "FREE",
    "POLICY_PATH",
    "AdmissionRequest",
    "admit",
    "binding_knob",
    "clamp_refusal",
    "egress_refusal",
    "exhaustion",
    "licence_refusal",
    "write_exhausted",
]

# --------------------------------------------------------------------------------------------
# 1. The names this module writes with.
# --------------------------------------------------------------------------------------------

EXHAUSTED_KEY: Final[str] = "budget.exhausted"
"""The one evidence key `admit()` writes. RT9's whole channel, and the registry's one `admit` row.

`omniweave/route/signals.toml` declares it with `provider = "admit"` -- *"the one row whose provider
column names a FUNCTION and not a package"* -- and a test holds this constant against that file.
"""

ADMIT_PROVIDER: Final[str] = "admit"
"""`SignalSpec.provider` for `budget.exhausted`, and a reserved name `load_signals()` refuses from a
third party's `signals.toml`: no installed package may claim to be `admit()`."""

EXHAUSTED_VERSION: Final[str] = "1.0.0"
"""`budget.exhausted`'s `version`, which `Evidence.put()` records into the read set.

A constant rather than a registry lookup because `put()` is on the drain loop's path and the
registry is read from disk once per run; a test pins the two together, which is the same trade
`BUILTIN_SIGNALS` makes for the file itself.
"""

POLICY_PATH: Final[str] = ".omniweave/policy.d/00-builtin-route.toml"
"""The path `exhaustion()`'s message tells an operator to edit, verbatim from 05:3312.

**The `project` directory and the `builtin` basename**, which is what the trace prints. It reads as
a conflation -- the shipped `builtin` layer is package data at
`omniweave/route/policies/00-builtin-route.toml` -- but it is also the correct instruction: an
operator who wants a different `on_exhausted` copies the block into `.omniweave/policy.d/`, and
naming the package-data path would tell them to edit a file inside their virtualenv. It is a
parameter so a site installation can name its own.
"""

_CLAMP_DIM: Final[str] = "max_cost_class"
"""`Degradation.unit_dim` for step 1. 05:2528 says why it is a `unit_dim` and not a new `kind`:
*"the charter's `kind` literal is closed, a cost-class clamp is a spend refusal, and inventing a
parallel member for it would be the second `Degradation` type section 5 X21 forbids."*"""


# --------------------------------------------------------------------------------------------
# 2. What steps 1-3 compare.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    """Everything `admit()`'s two printed arguments do not carry, and nothing else.

    Every field defaults to the free path, so `AdmissionRequest()` is a decision that clamps to
    nothing, is licensed, egresses nothing and reserves nothing -- 02:478's hop 8 exactly. A caller
    that fills none of it gets `Admitted(())`, which is what a `free` decision should get.

    `clamped_by` is the one field that is not a comparison: it is the `rule_ids` of the modifiers
    that set the ceiling, carried so step 1's message can name the rule an operator would edit.
    `Modifiers.rule_ids` is the only record that a modifier fired at all -- every other key it
    merges can be contributed by two rules or by none -- and a clamp refusal naming no rule would
    send an operator to grep forty rules for whichever one set a ceiling.
    """

    driver_cost_class: CostClass = CostClass.FREE
    max_cost_class: CostClass = CostClass.BILLED_API
    clamped_by: tuple[str, ...] = ()
    tier: LicenceTier | None = None
    allow_tiers: frozenset[LicenceTier] = frozenset({LicenceTier.OPEN})
    bytes_egress: int = 0
    grant: Grant | None = None
    now: dt.datetime | None = None
    reservations: tuple[Reservation, ...] = ()
    limits: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.bytes_egress < 0:
            raise ValueError(f"bytes_egress of {self.bytes_egress} is not a quantity")


FREE: Final[AdmissionRequest] = AdmissionRequest()
"""The zero value, so `admit(d, ledger)` is the plan's printed call and means the free path."""


# --------------------------------------------------------------------------------------------
# 3. Steps 1-3. Three pure refusals, each returning the `Degradation` that explains it.
# --------------------------------------------------------------------------------------------


def clamp_refusal(d: RouteDecision, request: AdmissionRequest) -> Degradation | None:
    """Step 1: the driver costs more than the `GATE`-established ceiling allows.

    `None` when the driver is at or below the ceiling. The comparison is on `COST_CLASS_ORDER` --
    `FREE < LOCAL_COMPUTE < BILLED_API` -- and never on price, because the ceiling is a class and a
    class is what a `[[rule]]` can name.

    **It is a downgrade and not a denial.** `Degraded` is one of three admissions and only
    `deferred` short-circuits, so the work still runs: the caller re-resolves under the lower
    ceiling, which in the shipped policy is what `degrade.budget-exhausted` does when
    `on_exhausted[0] = "spill_to_free"` fires (05:2604).
    """
    if _rank(request.driver_cost_class) <= _rank(request.max_cost_class):
        return None
    rules = ", ".join(request.clamped_by) or "a GATE modifier"
    return Degradation(
        kind="budget",
        unit_dim=_CLAMP_DIM,
        wanted_driver=d.driver,
        message=(
            f"{d.driver or 'the chosen driver'} is {request.driver_cost_class.value} and "
            f"{rules} clamped this part to max_cost_class = "
            f"{request.max_cost_class.value}; raise it in the rule's `then`, or pass --allow-cost"
        ),
        knob=_CLAMP_DIM,
        fix_command=(
            f"ow route lint --explain {request.clamped_by[0]}"
            if request.clamped_by
            else "ow route explain"
        ),
    )


def licence_refusal(d: RouteDecision, request: AdmissionRequest) -> Degradation | None:
    """Step 2: the driver's computed tier is not in `[licence] allow_tiers`.

    `None` when no tier was supplied, because a caller with no card in hand is not asserting that
    the driver is licensed -- it is `resolve()`'s check that already ran, and 05:3261's trace is
    exactly that path: *"the pre-evaluation resolution already resolved it ... `compute_tier` is
    `restricted`, and `[licence] allow_tiers = ["open"]` refuses it -> `driver.unavailable`."*
    The refusal reaches `evaluate()` as evidence, so by the time `admit()` runs the lane has usually
    already degraded. This step is the late half of the same check, for the case where a driver was
    chosen by a `[[pin]]` or by a layer `resolve()` did not see.

    The tier is **computed from card facts and never supplied as a label** (DR15), so what arrives
    here is `compute_tier()`'s output and not an operator's opinion of it.
    """
    if request.tier is None or request.tier in request.allow_tiers:
        return None
    allowed = ", ".join(sorted(tier.value for tier in request.allow_tiers)) or "nothing"
    return Degradation(
        kind="driver_unavailable",
        wanted_driver=d.driver,
        message=(
            f"{d.driver or 'the chosen driver'} computes to licence tier "
            f"{request.tier.value!r} and [licence] allow_tiers permits {allowed}; add the tier to "
            "[licence] allow_tiers after reading the licence, or enable a different driver"
        ),
        knob="[licence] allow_tiers",
        fix_command=f"ow drivers explain {d.driver}" if d.driver else "ow drivers explain",
    )


def egress_refusal(d: RouteDecision, request: AdmissionRequest) -> Degradation | None:
    """Step 3: the estimate egresses bytes and no live site-layer `Grant` authorises it.

    `None` when the estimate egresses nothing, which is the shipped default: `bytes_egress = 0` in
    `[budget.per_unit]` is *"0 = NO hosted escalation without a site-layer Grant"* (05:1290), so the
    first hosted call on a fresh install reaches this step and is refused.

    A `Grant` is refused **if it has expired**, and the clock is the caller's: `Grant.is_active`
    takes `now` as a parameter, for the reason that class documents -- a value type that consulted
    the wall clock would make every test of it a test of the day it ran. A request with
    `bytes_egress > 0`, a grant, and no `now` is refused rather than admitted: an unchecked expiry
    is AP-4 (01:1091), *"The safety mechanism whose default disables it"*, whose verdict is *"the
    mechanism exists, the audit finds it, and it has never once run."*

    The message names the `dpa_ref` when there is one. 14:806: validating it *"would imply omniweave
    can tell whether your data-processing agreement covers this, which it cannot. Naming it forces
    someone to write down which agreement they are relying on."*
    """
    if request.bytes_egress <= 0:
        return None
    grant = request.grant
    if grant is not None and request.now is not None and grant.is_active(request.now):
        return None
    why = _egress_reason(grant, request.now)
    return Degradation(
        kind="grant_missing",
        wanted_driver=d.driver,
        unit_dim="bytes_egress",
        spent=0,
        limit=request.bytes_egress,
        message=(
            f"{d.driver or 'the chosen driver'} would egress {request.bytes_egress} bytes and "
            f"{why}; [budget.per_unit] bytes_egress defaults to 0, so the first hosted call needs "
            "a site-layer Grant naming a dpa_ref, an approver, an expiry and a scope"
        ),
        knob="[budget.per_unit] bytes_egress",
        fix_command="ow doctor --grants",
    )


def _egress_reason(grant: Grant | None, now: dt.datetime | None) -> str:
    if grant is None:
        return "no site-layer Grant authorises it"
    if now is None:
        return f"grant {grant.grant_id} ({grant.dpa_ref}) was not checked against a clock"
    return f"grant {grant.grant_id} ({grant.dpa_ref}) expired at {grant.expires}"


def _rank(cost_class: CostClass) -> int:
    """`COST_CLASS_ORDER`'s index. Imported and not restated, unlike `decision._COST_ORDER`.

    `decision.py` keeps its own copy because `Modifiers.merge` is on `evaluate()`'s side of the
    purity line and `drivers.resolve` reaches a `Catalog`; this module is the impure half by
    definition, so it reads the authority directly and a test asserts the two agree.
    """
    return COST_CLASS_ORDER.index(cost_class)


# --------------------------------------------------------------------------------------------
# 4. The six steps, composed.
# --------------------------------------------------------------------------------------------


def admit(
    d: RouteDecision, ledger: BudgetLedger, request: AdmissionRequest = FREE
) -> AdmissionVerdict:
    """05:2519's ladder, in its printed order. `Admitted | Deferred | Degraded`.

    **The order is the ladder's and it matters.** Steps 1-3 are refusals that cost nothing to
    evaluate and that make a reservation pointless: clamping, a licence tier and a missing grant
    each mean this driver will not run as chosen, so reserving headroom for it first would hold
    money against work that was never going to happen -- and a held reservation is money another
    part cannot have until it expires or is released.

    **Only the FIRST refusal is returned.** `Degraded` carries a tuple, so returning all three would
    be possible and would be wrong: steps 2 and 3 read a card and a grant for a driver step 1 has
    already established will not be used, and a degradation naming a licence tier for a driver the
    clamp rejected would send an operator to the wrong knob.

    Steps 4-6 are `omniweave_core.budget.admit()`, which reserves every declared dimension in `DIMS`
    order and returns `Deferred(dim)` naming the first whose headroom was short. It refuses two rows
    sharing one `reservation_id` before the ledger sees them (D173) and returns `Admitted(())` for
    an empty reservation set, which is the free path this function's default argument produces.

    Nothing here writes `budget.exhausted`: a `Deferred` is not exhaustion, and `write_exhausted()`
    is the separate call with the separate condition.
    """
    for step in (clamp_refusal, licence_refusal, egress_refusal):
        refused = step(d, request)
        if refused is not None:
            return Degraded((refused,))
    return reserve_all(request.reservations, ledger=ledger, limits=request.limits)


# --------------------------------------------------------------------------------------------
# 5. The write-back. RT9's single channel.
# --------------------------------------------------------------------------------------------


def write_exhausted(ev: Evidence, *, siblings_in_flight: int) -> bool:
    """Write `budget.exhausted = true` into `Evidence`, iff 05:2534's clause holds. Returns whether.

    *"only when a deferred row is re-offered with **no sibling reservation still in flight for the
    same scope key**."* `writes_exhausted()` in core is that predicate and this is the write; the
    split is core's own, because `Evidence` is `omniweave.route`'s type and the predicate is a
    statement about the ledger.

    `siblings_in_flight` is `count(*) FROM budget_reservation WHERE state='held'` for the deferred
    dimension's `(dim, scope, scope_key)`. **It is a parameter because no `BudgetLedger` call
    answers it** -- see the module docstring and D211 -- and passing it explicitly is what keeps the
    clause visible at the call site rather than buried in a helper that quietly assumed zero.

    §10.3's trace is the whole behaviour in five passes: at pass 1 part 3 is deferred with two
    siblings held, so nothing is written and the document keeps going; at pass 5 part 6 is deferred
    with nothing held, `budget.exhausted` is written, `degrade.budget-exhausted` matches on
    `{exists = true}` and `on_exhausted` is finally consulted. The gap between those two is the
    whole of why the clause exists.

    The write goes through `Evidence.put()`, which refuses to change a value the current window has
    already read -- and that refusal is the reason this is legal: `admit()` writes between one
    rung's decision and the next's, and the loop clears the read log in between.
    """
    if not writes_exhausted(siblings_in_flight=siblings_in_flight):
        return False
    ev.put(EXHAUSTED_KEY, value=True, provider_version=EXHAUSTED_VERSION)
    return True


# --------------------------------------------------------------------------------------------
# 6. The degradation an exhausted budget produces, and the knob its message names.
# --------------------------------------------------------------------------------------------


def binding_knob(limits: Mapping[str, int], *, part_count: int) -> str:
    """Which `[budget.per_unit]` key an operator would actually raise. 05:2612's rule, executed.

    *"The message names the knob that would actually raise **this** limit ... Naming `micros_max`
    there would name a knob whose change does nothing."*

    `per_unit_micros` is `clamp(micros_base + micros_per_part x part_count, 0, micros_max)`, so
    three keys can bind and exactly one of them is worth naming:

    * `micros_max` when the clamp is active. Raising either other key moves nothing at all.
    * `micros_per_part` when it is not and the unit has more than one part. Its coefficient is
      `part_count` and `micros_base`'s is one, so it is the key with more leverage on this document
      -- which is the sense in which it *"would actually raise this limit"*.
    * `micros_base` otherwise, which is the one-part and zero-part case.

    §10.3's numbers are the worked example: `4,000 + 800 x 6 = 8,800` under a `micros_max` of
    12,000, so the clamp is inactive, the unit has six parts, and the message names
    `micros_per_part` -- which is what the trace prints.
    """
    uncapped = limits["micros_base"] + limits["micros_per_part"] * part_count
    if uncapped >= limits["micros_max"]:
        return "micros_max"
    if part_count > 1:
        return "micros_per_part"
    return "micros_base"


def exhaustion(
    *,
    limits: Mapping[str, int],
    part_count: int,
    spent: int,
    limit: int,
    settled_parts: int,
    parts_affected: Sequence[int] = (),
    rung_reached: str | None = None,
    unit_uri: str | None = None,
    policy_path: str = POLICY_PATH,
) -> Degradation:
    """The `Degradation(kind="budget")` an exhausted per-unit `micros` cap produces.

    05:3306's record and 05:3310's message, reproduced field for field:

    ```
    Degradation(kind='budget', unit_dim='micros', spent=6270, limit=8800, rung_reached=PAGE,
                parts_affected=(6,))
    message: "[budget.per_unit].micros_per_part gives 8800 for 6 parts; exhausted at 6270/8800
              after part 5/6; raise micros_per_part, pass --allow-cost, or set
              on_exhausted=['defer'] in .omniweave/policy.d/00-builtin-route.toml"
    ```

    Three clauses and each is load-bearing. The first names the knob and what it currently gives,
    so an operator can see the arithmetic without opening the file. The second names where the money
    went and how far the document got, which is what turns *"the money ran out"* into *"the money
    ran out on page 63 of 188"* (05:2600). The third names three fixes in increasing order of
    commitment: raise the cap, authorise this one run, or stop degrading and defer.

    `--allow-cost` is named and `RouteHints` deliberately has no field for it (05:2030), which is
    why the message says *pass* it: it is a CLI flag and there is nothing to send at the MCP
    boundary.
    """
    knob = binding_knob(limits, part_count=part_count)
    return Degradation(
        kind="budget",
        unit_dim="micros",
        message=(
            f"[budget.per_unit].{knob} gives {limit} for {part_count} parts; "
            f"exhausted at {spent}/{limit} after part {settled_parts}/{part_count}; "
            f"raise {knob}, pass --allow-cost, or set on_exhausted=['defer'] in {policy_path}"
        ),
        unit_uri=unit_uri,
        parts_affected=tuple(parts_affected),
        spent=spent,
        limit=limit,
        rung_reached=rung_reached,
        knob=f"[budget.per_unit].{knob}",
        fix_command=f"ow add --allow-cost {limit}",
    )
