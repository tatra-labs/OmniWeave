"""The `DemandPlan` -- what a `(rung, lane, phase)` is allowed to compute, cheapest group first.

05-ingest-and-routing.md:1109 is the whole specification in two sentences:

> **The demand plan.** For each `(rung, lane, phase)` the compiler takes the union of the read sets
> of every reachable rule and partitions it by `CostClass`, ascending. Groups are computed in order
> and the rules re-evaluated after each; **a rule matches only on resolved values.**

RT4 (05:3344) is the same thing stated as an enforcement, and it is the one that names the price of
getting it wrong: *"a clean born-digital page never reaches the `LOCAL_COMPUTE` group, and
`service_attaches` / `page_renders` / `signal_computations` are **exact** -- ±1 fails the gate."*
So this module is not an optimisation. It is the mechanism INV-13 is true by, and
`route/counters.py` is the instrument that says so in numbers.

## What is in a plan and what is not

A plan holds **keys**, not rules -- except for the deferring ones, which it holds because
`deferrals_pending()` must evaluate them. Four things are deliberately outside:

- **The acquisition itself.** Computing a group means calling a provider, reading `route_signal` and
  writing a raster into `cache_index` layer `render` (05:2356). All three are impure and all three
  are `omniweave.run`'s. This module answers *which* keys, in *which* order, and stops there.
- **`evaluate()`.** The loop at 05:1090 alternates the two; neither calls the other.
- **Unregistered keys.** A key no `SignalSpec` claims is in `unregistered` and in no group, because
  a group is a unit of *computation* and nothing can compute it. Filing it under FREE would say
  acquisition runs it and gets UNKNOWN back, which is a computation that never happens and a
  `signal_computations` that is one too high -- on an exact counter. `layout.class_hist` is the
  day-one member and the table says so in its provider column: *"none (day 1)"* (05:2161).
- **The format.** `resolve(key, format)` decides whether a registered key has a provider for *this*
  unit, and one plan serves every format at a `(rung, lane, phase)` -- it is memoised on
  `(policy_digest, caps_digest)` and neither carries a format (D205). `block.type` is in the DECODE
  settle group and computes on a DOCX and not on a PDF; the plan is the same plan either way.

## Why the lane is in the key

05:883: *"the `DemandPlan` is keyed `(rung, lane, phase)`, so a signal read only by a `table`-lane
rule is computed only for parts in the `table` lane."* Property 2 (05:1155) prices the alternative:
*"without the lane in the key every `text`-lane part in the corpus pays up to 30 ms for a table
judge it will never read."*

## `deferrals_pending`, and the clause the printed call cannot carry

05:1116 states the early-stop rule and its one exception:

> If an action rule matches on the FREE group alone, evaluation stops there -- unless a rule
> *earlier in file order* at this `(rung, lane, phase)` is currently UNKNOWN and declares
> `on_unknown = "defer"`, in which case the group holding its missing keys is promoted (still
> ascending, still under the `GATE` clamp) and evaluation restarts. That is
> `plan.deferrals_pending`.

Three clauses, and the printed call `plan.deferrals_pending(ev)` can express one of them. The
"earlier in file order" comparison needs the id of the rule that matched, and the "under the `GATE`
clamp" parenthetical needs the ceiling `Modifiers.max_cost_class` established -- neither of which is
reachable from an `Evidence`. This matters on the plan's own clean page, which is why D213 files it:
`decode.blank-part-escape` reads `ink.tiles` (LOCAL, UNKNOWN) and defers, `decode.pdf-text-layer`
matches four rules ahead of it, and 05:3110 spells out what must happen next --

> but it is LATER in file order than the rule that matched, so `plan.deferrals_pending` is false,
> the LOCAL group is never computed and no raster is rendered. THAT ORDERING IS WHAT MAKES INV-13
> TRUE.

-- so the one-argument reading renders a 96-DPI raster on every clean born-digital page, and
`page_renders` reads 188 instead of 13 on the document §10.1 traces. `before=` and `ceiling=` are
keyword-only and both default to the permissive value, so the printed call still parses and still
means something; it just means "ignoring file order", which no caller wants.

## Termination, without a counter

05:1131: *"Because a plan holds finitely many groups and each is computed at most once, evaluation
terminates with no deferral counter."* `next_group()` is that argument executed -- it returns the
first group not yet computed, so the sequence of indices it returns is strictly increasing and
bounded by `len(groups)`. There is no retry, no budget and no loop guard, because the ordering does
the work a guard would have done badly.

Specified in 05-ingest-and-routing.md section 4.3; RT4 at 05:3344; scheduled by 16-roadmap.md:606.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.resolve import COST_CLASS_ORDER
from omniweave_ports.types import CostClass

from omniweave.route.rung import Rung

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from omniweave.route.evidence import Evidence, SignalRegistry
    from omniweave.route.policy import RoutePolicy, Rule

__all__ = [
    "PHASES",
    "DemandMap",
    "DemandPlan",
    "Group",
    "compile_demand",
    "keys_at",
    "plan_for",
    "reachable",
]

PHASES: Final[tuple[str, str]] = ("select", "settle")
"""The two derived phases, in evaluation order. 05:1094's `for phase in (select, settle)`.

Derived and never declared -- 05:1136: *"A rule belongs to the **settle** phase of rung `R` iff any
key in its read set has `R` in `requires`, and to `R`'s **select** phase otherwise."*
`RoutePolicy.phase_of_rule()` is that derivation and this module only reads it."""

_DEFER: Final[str] = "defer"
"""`on_unknown`'s third value, and the only one `deferrals_pending()` looks for. 05:1129."""


# --------------------------------------------------------------------------------------------
# 1. A group -- one `CostClass`, and the unit in which acquisition happens.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Group:
    """One `CostClass`'s share of a plan's keys. The unit 05:1110 computes and re-evaluates around.

    Keys are **sorted**, and that is a decision rather than tidiness. Within a group there is no
    order: the group is computed as a whole and the rules are re-evaluated once afterwards, so any
    order gives the same evidence. Leaving them in first-read order would therefore expose a
    difference that does not exist, and `ow route lint --explain`'s output would depend on which
    rule happened to be first in the file. Between groups the order is `CostClass`, which is the
    order that matters and the one `DemandPlan.groups` carries.
    """

    cost_class: CostClass
    keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError(
                f"a {self.cost_class.value} group with no keys is not a step: "
                "compile_demand() omits empty classes"
            )

    @property
    def rank(self) -> int:
        """Position in `COST_CLASS_ORDER`. `free` is 0, which is what "ascending" means here."""
        return COST_CLASS_ORDER.index(self.cost_class)

    def render(self) -> str:
        """`'free: decode.char_count, unit.bytes, unit.format'`, for `--explain`."""
        return f"{self.cost_class.value}: {', '.join(self.keys)}"


# --------------------------------------------------------------------------------------------
# 2. The plan.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DemandPlan:
    """One `(rung, lane, phase)`'s groups, ascending by `CostClass`. 05:1109.

    `deferring` holds the rules rather than their ids because `deferrals_pending()` has to evaluate
    them -- a deferral is pending only while the rule's `when` is actually UNKNOWN, and that is a
    question about this `Evidence` and not about the policy. Holding the rules is also what lets the
    predicate keep the printed one-argument shape for the two clauses it can serve.

    `unregistered` and `pruned` are carried rather than dropped. A plan that silently omitted them
    would answer "which keys does this rung compute" correctly and "why is this rule's key not in
    any group" not at all, and the second question is the one a reader has when a guard did not
    fire. 05:1170 requires the pruned rules to reach a `Degradation(kind="policy_pruned")`, which
    `lint.degradations()` builds; this is the plan's side of the same fact.
    """

    rung: Rung
    lane: str
    phase: str
    groups: tuple[Group, ...]
    rule_ids: tuple[str, ...] = ()
    deferring: tuple[Rule, ...] = ()
    unregistered: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ranks = [group.rank for group in self.groups]
        if ranks != sorted(set(ranks)):
            raise ValueError(
                f"{self.label} groups are {[g.cost_class.value for g in self.groups]}, "
                "which is not one ascending run of CostClass (05:1110)"
            )

    @property
    def label(self) -> str:
        """`'DECODE/text/select'` -- the plan's key, as a reader writes it."""
        return f"{self.rung.name}/{self.lane}/{self.phase}"

    @property
    def keys(self) -> tuple[str, ...]:
        """Every computable key, in group order then sorted within the group.

        The order acquisition would run them in, which is what makes this the right thing to print.
        `unregistered` is **not** here, for the module docstring's reason.
        """
        return tuple(key for group in self.groups for key in group.keys)

    @property
    def demanded(self) -> tuple[str, ...]:
        """Every key a reachable rule reads, computable or not, sorted. What check 1 resolves."""
        return tuple(sorted({*self.keys, *self.unregistered}))

    def cost_of(self, key: str) -> CostClass | None:
        """The key's group, or `None` for a key this plan does not demand or cannot compute."""
        for group in self.groups:
            if key in group.keys:
                return group.cost_class
        return None

    def index_of(self, key: str) -> int:
        """The key's group index, or `-1`. The number `next_group()` compares against."""
        return next((i for i, group in enumerate(self.groups) if key in group.keys), -1)

    # ---- the two predicates the section 4.3 loop calls ----

    def computed_through(self, ev: Evidence) -> int:
        """How many leading groups have run: the count of groups every key of which is computed.

        Reads `Evidence.computed()` and never `read()`, which 05:1876 requires in bold -- *"a
        planner probe is not a read and may not enter the read set"*. The read set is the
        eight-column identity of a `route_decision` row (05:2665), so a probe that entered it would
        give two runs that decided identically two different digests and re-bill the second.

        **Leading**, not "any". A group is computed as a whole, so a partially-filled group means
        acquisition is mid-flight or a provider raised; either way the next group may not start.
        """
        through = 0
        for group in self.groups:
            if not all(ev.computed(key) for key in group.keys):
                break
            through += 1
        return through

    def next_group(self, ev: Evidence, *, ceiling: CostClass | None = None) -> Group | None:
        """The next group to compute, or `None` when the plan is spent or the clamp forbids it.

        `ceiling` is 05:1117's *"still under the `GATE` clamp"* -- the `max_cost_class` the GATE
        rung's modifiers established, which `admit()` step 1 enforces again on the driver. Enforcing
        it here too is not belt-and-braces: step 1 clamps the *driver*, and a `local_compute` signal
        computed under a `free` clamp has already spent the 15 ms by the time any driver is chosen.
        """
        through = self.computed_through(ev)
        if through >= len(self.groups):
            return None
        group = self.groups[through]
        if ceiling is not None and group.rank > COST_CLASS_ORDER.index(ceiling):
            return None
        return group

    def deferrals_pending(
        self,
        ev: Evidence,
        *,
        before: str = "",
        ceiling: CostClass | None = None,
    ) -> tuple[str, ...]:
        """Rule ids that hold the loop open: UNKNOWN, deferring, earlier than `before`, promotable.

        05:1116's exception to early stopping, all three clauses. A rule qualifies when

        1. it declares `on_unknown = "defer"` and its `when` is currently UNKNOWN;
        2. it is **earlier in file order** than `before` -- the rule that matched. 05:3110 is the
           case this clause exists for and D213 is the gap: the plan prints
           `plan.deferrals_pending(ev)` with no way to say which rule matched, and without it a
           clean born-digital page promotes the LOCAL group and renders a raster INV-13 forbids;
        3. at least one of its keys is in a group that has **not** run and that `ceiling` permits.
           05:1128: *"Once every group in the plan has been computed, a key that is still UNKNOWN is
           genuinely unavailable ... and the rule's `on_unknown` decides."* At that point `defer`
           has degraded to `skip` and there is nothing left to wait for -- returning the rule anyway
           would restart evaluation over evidence that cannot change, which is the one shape that
           does not terminate.

        `before = ""` means "nothing matched", and then every deferring rule is eligible -- which is
        correct: the loop only calls this after a match, and a caller asking without one is asking
        the unconditioned question.

        **This one reads, and the bound is what makes that harmless.** `computed_through()` and
        `next_group()` go through `computed()` exactly as 05:1876 requires, but clause 1 is a
        Kleene question about a `when` and 05:1868 makes `read()` the only way to evaluate one.
        Bounded, every key it touches was already read: first-match-wins tested every rule ahead of
        `before`, and `read_set()` deduplicates at first occurrence, so the digest is unchanged.
        Unbounded, it reaches LATER rules and D213's second consequence appears -- on section
        10.1's clean page `ink.tiles` enters the read set of a decision that never computed it, and
        `read_set_digest` is one of `route_decision`'s eight identity columns.
        """
        limit = COST_CLASS_ORDER.index(ceiling) if ceiling is not None else len(COST_CLASS_ORDER)
        out: list[str] = []
        for rule in self.deferring:
            if rule.id == before:
                break
            if rule.when.holds(ev) is not None:
                continue
            if any(self._promotable(key, ev, limit) for key in rule.when.keys):
                out.append(rule.id)
        return tuple(out)

    def _promotable(self, key: str, ev: Evidence, limit: int) -> bool:
        """The key sits in a group that has not run and that the clamp still allows."""
        index = self.index_of(key)
        return index >= 0 and self.groups[index].rank <= limit and not ev.computed(key)

    # ---- what `ow route lint --explain` prints ----

    def render(self) -> tuple[str, ...]:
        """One line per group, then the two exceptional sets. 05:1143's `--explain`."""
        lines = [f"{self.label}  {len(self.rule_ids)} rules, {len(self.keys)} keys"]
        lines.extend(f"    {group.render()}" for group in self.groups)
        if self.unregistered:
            lines.append(f"    unregistered (no provider, never computed): {self.unregistered}")
        if self.pruned:
            lines.append(f"    pruned (OW-P-011, keys not demanded): {self.pruned}")
        return tuple(lines)


DemandMap = Mapping[tuple[Rung, str, str], DemandPlan]
"""What the compiler emits. 05:1095's `policy.demand[(rung, lane, phase)]`, spelled as a type.

A `Mapping` and not a `dict`, because the compiler hands it out and 05:1160 memoises it on
`(policy_digest, caps_digest)`: a plan a caller could mutate would make the memo key a lie."""


# --------------------------------------------------------------------------------------------
# 3. The compiler.
# --------------------------------------------------------------------------------------------


def reachable(policy: RoutePolicy, *, pruned: Iterable[str] = ()) -> tuple[Rule, ...]:
    """Every rule a demand plan may read, in file order. 05:1167's property 5.

    *"A rule whose condition box is subsumed by an earlier action rule at the same
    `(rung, lane, phase)` can never fire ... `ow route lint` reports `OW-P-011` and the compiler
    drops it from the demand plan with a recorded `Degradation(kind='policy_pruned')`."*

    `pruned` is the linter's finding set and arrives as ids rather than as `Rule`s, because
    `lint.subsumption()` reports and the compiler acts -- two steps, and a compiler that ran the
    linter itself would make `policy_digest` depend on a registry (`compile_policy()`'s docstring
    says why that must not happen). Passing `()` compiles the unpruned plan, which is what
    `ow route lint` itself wants: a plan that already dropped the subsumed rules cannot be asked
    whether dropping them changed anything.
    """
    dropped = frozenset(pruned)
    return tuple(rule for rule in policy.rules if rule.id not in dropped)


def compile_demand(
    policy: RoutePolicy,
    *,
    registry: SignalRegistry,
    pruned: Iterable[str] = (),
) -> DemandMap:
    """One `DemandPlan` per `(rung, lane, phase)` that has a rule. 05:1109.

    **Only keys a reachable rule reads.** Two other readers of `Evidence` exist at every rung and
    neither is a rule: `[slice] by`, which `eval.slice_key()` reads to build the `slice_key` column,
    and `[audit] untrusted_external_rate`, whose comment in the shipped policy (05:1302) reads
    *"applied by the SAMPLER from unit.trust_class, not by a rule"*. Section 4.3 says "the read sets
    of every reachable rule" and says nothing about either, so neither is here -- and D215 files
    that, because `signal_computations` admits no plus-or-minus-one and those are four keys per
    decision.

    **A `(rung, lane)` with no rule gets no plan, not an empty one.** 05:1090's loop reads
    `policy.demand[(rung, lane, phase)]` inside `for phase in (select, settle)`, so a missing key is
    a lookup the caller must handle; `plan_for()` is that handling, and it returns an empty plan so
    the loop body is uniform. Storing the empties instead would put 7 rungs x 5 lanes x 2 phases =
    70 entries in a map whose real size on the shipped policy is 14.

    Raises nothing. A key with no registration is `unregistered`, not an error: check 1
    (`OW-P-001`) is the linter's job and it reports every such key at once, which is the difference
    between a lint and a crash on the first one.
    """
    rules = reachable(policy, pruned=pruned)
    dropped = tuple(sorted({rule.id for rule in policy.rules} - {rule.id for rule in rules}))
    buckets: dict[tuple[Rung, str, str], list[Rule]] = {}
    for rule in rules:
        buckets.setdefault((rule.rung, rule.lane, policy.phase_of_rule(rule)), []).append(rule)
    return MappingProxyType(
        {
            key: _plan(key, members, registry=registry, pruned=dropped)
            for key, members in buckets.items()
        }
    )


def _plan(
    key: tuple[Rung, str, str],
    rules: Sequence[Rule],
    *,
    registry: SignalRegistry,
    pruned: Sequence[str],
) -> DemandPlan:
    """The union, partitioned. `rules` is in file order and `deferring` preserves it."""
    rung, lane, phase = key
    by_class: dict[CostClass, set[str]] = {}
    unregistered: set[str] = set()
    for rule in rules:
        for read in rule.when.keys:
            cost = registry.cost_class_of(read)
            if cost is None:
                unregistered.add(read)
            else:
                by_class.setdefault(cost, set()).add(read)
    return DemandPlan(
        rung=rung,
        lane=lane,
        phase=phase,
        groups=tuple(
            Group(cost_class=cost, keys=tuple(sorted(by_class[cost])))
            for cost in COST_CLASS_ORDER
            if cost in by_class
        ),
        rule_ids=tuple(rule.id for rule in rules),
        deferring=tuple(rule for rule in rules if rule.on_unknown == _DEFER),
        unregistered=tuple(sorted(unregistered)),
        pruned=tuple(pruned),
    )


def plan_for(demand: DemandMap, rung: Rung, lane: str, phase: str) -> DemandPlan:
    """The plan, or an empty one. The lookup 05:1098 writes as a subscript.

    An empty plan is not an error and not a sentinel: a `(rung, lane, phase)` with no rule demands
    nothing, computes nothing and is the case a skipped rung is in. `groups` is `()`, so
    `next_group()` returns `None` immediately and the loop body falls through with no branch of its
    own -- which is why this returns a plan rather than `None`.
    """
    found = demand.get((rung, lane, phase))
    if found is not None:
        return found
    return DemandPlan(rung=rung, lane=lane, phase=phase, groups=())


def keys_at(demand: DemandMap, rung: Rung, lane: str) -> tuple[str, ...]:
    """Both phases' computable keys for one `(rung, lane)`, in `select`-then-`settle` order.

    What a rung costs a part in signals, which is the number `counters.signal_computations` counts
    and the number 05:1152 asserts is zero above FREE on a clean page. Deduplicated across the two
    phases at first occurrence: a key read in both is computed once -- `route_signal`'s primary key
    is `(content_sha256, unit_part, signal_key, signal_version)`, so the second read is a hit.
    """
    seen: list[str] = []
    for phase in PHASES:
        for key in plan_for(demand, rung, lane, phase).keys:
            if key not in seen:
                seen.append(key)
    return tuple(seen)
