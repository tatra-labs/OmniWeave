"""`plan()` -- PURE. One `Query` in, one ordered channel list with its own deadlines out.

07:1532 prints the signature and 07:1541 the purity claim: *"`plan()` is **pure**: no clock, no
RNG, no environment, no IO, **no store read**. It is memoised on `(mode, channel set, filter-field
set, policy_digest, caps_digest)` and carries the same semgrep bans as `evaluate()`. Everything the
planner needs to know about the store arrives as `IndexCaps`, which the `Reader` computed once at
open."* 01:422 names this file beside `route/eval.py` in the semgrep ban list, and
`tools/gate_pure_eval.py` -- P5's exit criterion, still unwritten -- is the mechanical half for
both.

There is **no cost-based optimiser and no join-order search** (07:1554): *"Join-order search over
an embedded store is untestable and produces plan flips that present to a user as outages."* The
planner makes four decisions, and W6.1 is three of them plus the frame for the fourth.

## The two deadlines, which is what this cell is for

16:657 puts the split in the row and the estimation basis says why: *"the split **is**
the verdict. Without it a plan that merely used its budgets makes every query `degraded`, which
turns the honesty machinery into permanent noise."* 07:1791:

> a Channel that exceeds ITS OWN budget_ms returns UNAVAILABLE(timeout) with what it has, which
> contributes nothing to the score and FORCES degraded;
> a Channel PRE-EMPTED BY THE QUERY DEADLINE reports its partial ranking with
> truncated_at_limit = True and status OK, and the remaining Channels are not run and report
> OFF(query_deadline) -- an operator-visible disclosure, not a failure, AND IT KEEPS ITS CEILING
> WEIGHT

What the **planner** owes that split is the two numbers it is stated over and the guarantee that
they cannot collide by accident: every `ChannelSpec` carries its own `budget_ms` from
`[retrieval.budget] channel_ms`, and their sum plus `hydration_reserve_ms` is checked against
`query_ms` -- `15 + 25 + 50 + 40 + 80 = 210, + 40 = 250` against `query_ms = 250`, which is why
07:1803 calls case two *"a safety net rather than the norm"*. `ow route lint` check 3 already
refuses a policy whose sum exceeds it (`OW-P-003`, shipped in W5.5a); `plan()` refuses the same sum
at plan time, because an installation can be edited after it was linted and the planner is the last
place the two numbers are both in hand. Two enforcers, one truth -- the shape RT8 already uses for
the rung trigger.

The **execution** of the split belongs to the Channels (W6.2) and to `build_verdict()` (W6.5), and
absence gate 1 reads only case one. Nothing here reports a status.

## The memo key is a superset of the printed one, and the printed one is short

07:1541's key is `(mode, channel set, filter-field set, policy_digest, caps_digest)`. A plan built
under it is not a function of it: `PackSpec` is `Query.k`, `max_blocks` and `max_chars`,
`ChannelSpec.limit` is `k x overfetch`, `ChannelSpec.budget_ms` is the `QueryBudget`, and the
weights and short-circuit are the matched rule's -- and two rules may name the same channel set
with different weights. On the printed key, `ow query -k 5` and `ow query -k 200` share a cache
entry and the second gets the first's limits. `MEMO_FIELDS` records the eleven this module keys
on; the printed five are among them and the extra six can only ever reduce sharing, never return a
plan built for another query. D234.

`filters` is deliberately **outside** the key and outside `plan_digest`: the key carries the filter
*field set* and never the values, which is exactly what makes 07:1546 true -- *"two different
queries of the same shape share a plan digest and the scoreboard can slice by plan"*. So the memo
holds a shape and `plan()` attaches this query's `Filters` to it.

## Rule selection, and the grammar this module does not own

07:1714: channel selection is *"authored in D4's rule grammar verbatim, `surface = "retrieval"`"*.
D4's loader, its subsumption linter and its clause machinery are `omniweave/route/policy.py`'s, and
`tools/layers.toml` forbids `omniweave_core` from importing `omniweave`. So the grammar has no home
this module can reach, and D235 is that inversion.

What ships is a matcher over the clause forms the four rules of 07:1712-1756 actually use -- a bare
scalar (equality) and a single-operator table over `lt | lte | gt | gte | ne` -- which **refuses**
every other form rather than mis-evaluating it. A partial grammar with a loud edge was preferred to
a second full implementation of D4's: 13:1072 names that failure for a fold table and it is the
same failure here, *"where two normalisers drift and a comparison starts depending on which one
ran"*.

`on_unknown` is carried and one of its three values is unreachable here. All four evidence keys are
total functions of `Query` and `IndexCaps`, so no clause is ever UNKNOWN; `skip` is the disposition
that would fire, and `defer` -- which the shipped `thematic` rule declares -- has nothing to defer
to, because the query path has no `DemandPlan` and no cost-class groups to promote. `_fires()`
refuses it rather than treating it as `skip`, since those are different answers and only one of
them is stated.

## `prove_absent` disables the short-circuit

07:1826: *"`mode = "prove_absent"` disables every short-circuit in the table's first, fifth and
sixth rows: an absence claim is licensed by *all* Channels having looked, so the plan runs to
completion even when a grade-50 identity hit exists."* Row one is the plan's `short_circuit` and is
the only one of the three a plan carries; rows five and six are runtime conditions the Channels
evaluate. (Row six is the vector backend's `VEC_BRUTE_MAX` refusal, whose disabling would run the
scan the ceiling exists to refuse -- read here as a row-count slip in the sentence, and implemented
as rows one and five, the two that are early *exits* rather than refusals.)

## W6.4: decision 3's bind-time half, and decision 1's one refusal

Decision 3 is section 6.3 and it has two halves. `LEX_OVERFETCH = 5` is *"always"* (07:1780) and
belongs to the plan; the semantic Channel's factor is `clamp(1/selectivity, 1, 64)` and cannot,
because that division is by the narrowing's `n` and `n` is a function of the filter VALUES, which
07:1541's memo key excludes on purpose. `overfetch_clamp()` is the division and `bind_overfetch()`
applies it to a built plan without touching `plan_digest`.

Decision 1 is the store's -- `Reader.narrow()` runs the `LIMIT PREFILTER_MAX + 1` probe -- and the
only part of it that is this module's is the one field a caller may not set. 07:1576 makes
`Filters.deny_restriction_bits` *"set by POLICY, never by the caller (DR17)"* and 14:101 states it
as boundary B6. No shipped policy shape carries the value, so the refusal below is the whole of
what this module can enforce and D261 is the rest.

Specified in 07-store-and-retrieval.md section 6; scheduled by 16-roadmap.md:657 and :660.
"""

from __future__ import annotations

import dataclasses
import math
from collections import OrderedDict
from typing import TYPE_CHECKING, Final

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import UsageError
from omniweave_core.retrieve.types import (
    ABSENCE_GATES,
    CHANNELS,
    NO_FILTERS,
    SCORER_VERSION,
    FusionSpec,
    PackSpec,
    QueryBudget,
    QueryPlan,
    Rule,
)
from omniweave_core.store.types import ChannelSpec

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_core.config import Scalar
    from omniweave_core.retrieve.types import Query, RetrievalPolicy
    from omniweave_core.store.types import Filters, IndexCaps, Narrowing

__all__ = [
    "EVIDENCE_KEYS",
    "LEX_OVERFETCH",
    "MEMO_FIELDS",
    "MEMO_MAX",
    "STALE_OVERFETCH",
    "STAT_MAX_AGE_NS",
    "bind_overfetch",
    "clear_memo",
    "evidence",
    "memo_key",
    "overfetch_clamp",
    "plan",
    "select",
]

LEX_OVERFETCH: Final[int] = 5
"""07:1780: *"`LEX_OVERFETCH = 5` for the lexical Channel, always, before re-rank."* Always, so it
is a constant and not a knob -- the re-rank adds the spine term, and a re-rank over `k` candidates
can only re-order what BM25 already chose."""

STAT_MAX_AGE_NS: Final[int] = 86_400_000_000_000
"""07:731's `STAT_MAX_AGE_NS`, one day in nanoseconds.

`store/reader.py` records it as a plan-named constant absent from `limits.py`, and that nothing
there needed it. This module does: it is the one `IndexCaps` field the over-fetch
decision reads, so it is homed beside the decision rather than added to `limits.py`, whose members
are ceilings an operator may hit (INV-22) and this is a staleness horizon."""

STALE_OVERFETCH: Final[int] = 64
"""The maximum of 07:1671's `clamp(1/selectivity, 1, 64)`, forced on a stale `stat` (07:729).

The clamp is not computed HERE and `overfetch_clamp()` below is where it is: the division is by
the narrowing's `n`, `n` is a function of the filter *values*, and 07:1541's memo key carries the
filter field set and never the values. So the plan carries the floor and the bind carries the
measurement. What a plan CAN say is the one value the clamp takes when the statistics are too old
to argue with, and saying it in the plan is what makes `--explain` show an operator that their
`stat` is stale before the query is slow."""

EVIDENCE_KEYS: Final[tuple[str, ...]] = (
    "query.mode",
    "query.has_refs",
    "query.text_terms",
    "caps.has_vectors",
)
"""The four keys the shipped retrieval rules read (07:1712-1756), and the whole vocabulary.

07:1770 says an unregistered key *"fails CI rather than silently never matching"* because `ow route
lint` resolves every `when` key against the `SignalSpec` registry. The shipped registry is the
ROUTING surface's (`omniweave/route/signals.toml`, fifty-four `unit.*`/`decode.*`/`request.*` keys)
and contains none of these four, so the lint that would catch a typo here has nothing to resolve
against. Recorded with D235, whose cause is the same: the retrieval surface's half of D4
lives in a distribution this one may not import."""

MEMO_FIELDS: Final[tuple[str, ...]] = (
    "mode",
    "channels",
    "rule_id",
    "filter_fields",
    "k",
    "max_blocks",
    "max_chars",
    "budget_digest",
    "rule_digest",
    "policy_digest",
    "caps_digest",
)
"""The eleven this module memoises on. 07:1541 prints five; D234 is the rest and the argument."""

MEMO_MAX: Final[int] = 256
"""Plan shapes retained. A bound and not a ceiling: past it the oldest entry is evicted and the
next call rebuilds, which costs a few microseconds of pure arithmetic. An unbounded memo on a
long-lived server process is a leak whose size is the number of distinct query *shapes*, and a
shape is cheap enough that forgetting one is never worth a page of resident memory."""

_ORDERED_OPS: Final[tuple[str, ...]] = ("lt", "lte", "gt", "gte")
_CLAUSE_OPS: Final[tuple[str, ...]] = (*_ORDERED_OPS, "ne")
_FIX: Final[str] = "uv run ow route lint --strict"
_MEMO: OrderedDict[tuple[object, ...], _Shape] = OrderedDict()


@dataclasses.dataclass(frozen=True, slots=True)
class _Shape:
    """Everything in a `QueryPlan` that is a function of the memo key. `filters` is not."""

    channels: tuple[ChannelSpec, ...]
    fusion: FusionSpec
    pack: PackSpec
    gates: tuple[str, ...]
    short_circuit: str | None
    plan_digest: str
    rule_id: str


# --------------------------------------------------------------------------------------------
# 1. Evidence -- four keys, all total
# --------------------------------------------------------------------------------------------


def evidence(q: Query, caps: IndexCaps) -> Mapping[str, Scalar]:
    """The four keys a retrieval rule may read, as a flat namespaced record.

    Namespaced and flat for `Evidence`'s reason on the routing side (05 §5.1): a rule names a key,
    and a nested structure would make the same fact reachable by two spellings. There is no read
    log here and there is no `SignalSpec` registry to validate against -- see `EVIDENCE_KEYS`.

    `caps.has_vectors` is derived from the channel set the store declares rather than from
    `space_id` or `vec_backend`: 07:3275 makes `IndexCaps.channels` *"which of the five CAN run at
    all in this store"*, which is the question the `thematic` rule asks; a store with a
    `space_id` and an unattached sidecar would answer the other two the wrong way.
    """
    return {
        "query.mode": q.mode,
        "query.has_refs": q.has_refs,
        "query.text_terms": q.text_terms,
        "caps.has_vectors": "semantic" in caps.channels,
    }


# --------------------------------------------------------------------------------------------
# 2. Selection -- first match wins, over the clause forms the shipped rules use
# --------------------------------------------------------------------------------------------


def select(pol: RetrievalPolicy, ev: Mapping[str, Scalar]) -> Rule:
    """The first rule whose `when` fires, or the all-five default when none does.

    First-match-wins, and the fall-through is a real `Rule` rather than `None` so that every plan
    names the rule that built it. A policy with no rules at all is a policy that selects the
    default, which is what the shipped `default` rule (07:1751) spells explicitly: an empty
    `[rule.when]` matches everything.
    """
    for rule in pol.rules:
        if _fires(rule, ev):
            return rule
    return Rule(rule_id="builtin:default", channels=CHANNELS)


def _fires(rule: Rule, ev: Mapping[str, Scalar]) -> bool:
    """Every clause true. An empty `when` is a rule that always fires (07:1753)."""
    for key, clause in rule.when.items():
        verdict = _clause(key, clause, ev)
        if verdict is None:
            return _on_unknown(rule)
        if not verdict:
            return False
    return True


def _on_unknown(rule: Rule) -> bool:
    """`skip` does not fire. `defer` is refused, because the query path has nothing to defer to."""
    if rule.on_unknown == "defer":
        raise UsageError(
            f"rule {rule.rule_id!r} declares on_unknown = 'defer', and the retrieval surface has "
            "no DemandPlan to promote a cost-class group into; the three values are the routing "
            "loop's and only 'skip' and 'match' are answerable here",
            fix=_FIX,
        )
    return rule.on_unknown == "match"


def _clause(key: str, clause: object, ev: Mapping[str, Scalar]) -> bool | None:
    """One clause against the evidence. `None` is UNKNOWN, which is not `False` (07:1768).

    Two forms and no more: a bare scalar is equality, and a single-entry mapping is one of the five
    operators. Anything else -- `any_of`, `all_of`, `none_of`, `in`, `not_in`, `exists`, a
    multi-operator table -- is D4's and is refused here rather than approximated, because a clause
    this module silently mis-read would select a different channel set and present as a relevance
    bug three layers away.
    """
    if key not in ev:
        return None
    value = ev[key]
    if not isinstance(clause, dict):
        return bool(value == clause)
    if len(clause) != 1:
        raise UsageError(
            f"clause for {key!r} has {len(clause)} operators; one operator per clause",
            fix=_FIX,
        )
    op, literal = next(iter(clause.items()))
    if op not in _CLAUSE_OPS:
        raise UsageError(
            f"{op!r} is not one of {', '.join(_CLAUSE_OPS)}; the rest of D4's comparison set is "
            "omniweave.route.policy's and this distribution may not import it (D235)",
            fix=_FIX,
        )
    if op == "ne":
        return bool(value != literal)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise UsageError(
            f"{key!r} = {value!r} is not ordered, and {op!r} is an ordered comparison",
            fix=_FIX,
        )
    if not isinstance(literal, int | float) or isinstance(literal, bool):
        raise UsageError(f"{op} = {literal!r} is not a number", fix=_FIX)
    return _compare(op, value, literal)


def _compare(op: str, value: float, literal: float) -> bool:
    """The four ordered comparisons, split out so `_clause()` stays under one screen and under
    ruff's return-count rule. The last branch is `gte` and is unguarded because `_CLAUSE_OPS`
    closed the set two statements earlier."""
    if op == "lt":
        return value < literal
    if op == "lte":
        return value <= literal
    if op == "gt":
        return value > literal
    return value >= literal


# --------------------------------------------------------------------------------------------
# 3. The plan
# --------------------------------------------------------------------------------------------


def memo_key(
    q: Query, caps: IndexCaps, pol: RetrievalPolicy, rule: Rule, budget: QueryBudget
) -> tuple[object, ...]:
    """The eleven of `MEMO_FIELDS`, in that order. Hashable, and a pure function of its arguments.

    `budget_digest` rather than the budget: `QueryBudget.channel_ms` is a `MappingProxyType` and is
    unhashable, and a digest over it is the same identity with a stable spelling.
    """
    return (
        q.mode,
        rule.channels,
        rule.rule_id,
        _filter_fields(q.filters),
        q.k,
        q.max_blocks,
        q.max_chars,
        sha256_canonical(dict(sorted(budget.channel_ms.items())) | {"q": budget.query_ms}),
        rule_digest(rule),
        pol.policy_digest,
        caps.caps_digest,
    )


def rule_digest(rule: Rule) -> str:
    """The matched rule's `then`, digested. Stands in for `policy_digest` when there is none.

    07:1541's key names `policy_digest`, which identifies the whole file; two rules in one file
    share it, and the plan they build does not. This digests the half the plan is a function of --
    the channel list, the weights, the short-circuit and the gate modifiers -- so a policy edit
    that moves a weight invalidates the memo and one that adds an unrelated rule does not.
    """
    return sha256_canonical(
        {
            "channels": list(rule.channels),
            "gates": list(rule.gates),
            "id": rule.rule_id,
            "short_circuit": rule.short_circuit,
            "weights": dict(sorted(rule.weights.items())),
        }
    )


def _refuse_policy_only_filters(filters: Filters) -> None:
    """DR17: `deny_restriction_bits` is *"set by POLICY, never by the caller"* (07:1576).

    14:101 states it as a boundary and not a preference -- B6, store to retrieval, is
    *"`Filters.deny_restriction_bits` is set by policy, never by the caller"*. The asymmetry is
    explicit at 07:1640, where `deny_methods` is the caller-expressible twin: *"a `retrieval`
    policy rule may union members in, and the effective set is `caller u policy`, so a policy can
    only ever narrow further."* A caller-set MASK is the case that rule does not admit, because a
    caller who may set it may also set it to zero.

    **Nothing in any shipped policy shape carries the value.** `RetrievalPolicy` is four fields
    (07:3327) and a `Rule`'s `then` half is a channel list, weights, a short-circuit and gate
    modifiers (07:1712-1756); neither names a filter, and `config.py`'s `[retrieval]` register has
    no key for a restriction mask. So a non-zero value arriving here came from the one source the
    boundary excludes, and D261 is the missing carrier. When it lands, this refusal becomes a
    substitution -- policy's value replacing the caller's -- and until then refusing is the only
    reading that does not let a caller own a mask policy is supposed to own.
    """
    if filters.deny_restriction_bits:
        msg = (
            f"Filters.deny_restriction_bits is 0x{filters.deny_restriction_bits:x} and only "
            f"policy may set it (07:1576, 14:101 boundary B6); no shipped policy shape carries "
            f"the field, so this value can only have come from the caller"
        )
        raise UsageError(msg, fix="drop deny_restriction_bits: the mask is deployment policy")


def plan(q: Query, caps: IndexCaps, pol: RetrievalPolicy) -> QueryPlan:
    """One `QueryPlan`: the ordered specs, their own deadlines, the gates, and two digests.

    Pure. The memo it consults is a cache of this function over its own key and holds no state a
    caller can observe except through `clear_memo()`, which exists for the property test that two
    calls of the same shape return the same digest by arithmetic rather than by cache.

    The filters are the caller's, attached and not memoised (`_Shape` says why), with the one
    field DR17 reserves to policy refused before anything else runs.
    """
    _refuse_policy_only_filters(q.filters)
    budget = q.budget or pol.budget or QueryBudget()
    rule = select(pol, evidence(q, caps))
    key = memo_key(q, caps, pol, rule, budget)
    shape = _MEMO.get(key)
    if shape is None:
        shape = _shape(q, caps, rule, budget, key)
        _MEMO[key] = shape
        if len(_MEMO) > MEMO_MAX:
            _MEMO.popitem(last=False)
    else:
        _MEMO.move_to_end(key)
    return QueryPlan(
        channels=shape.channels,
        filters=q.filters,
        fusion=shape.fusion,
        pack=shape.pack,
        gates=shape.gates,
        short_circuit=shape.short_circuit,
        scorer_version=SCORER_VERSION,
        plan_digest=shape.plan_digest,
        policy_digest=pol.policy_digest,
        rule_id=shape.rule_id,
    )


def clear_memo() -> None:
    """Empty the plan memo. For tests that assert the arithmetic rather than the cache."""
    _MEMO.clear()


def overfetch_clamp(n: Narrowing, caps: IndexCaps) -> int:
    """07:1671's `clamp(1/selectivity, 1, 64)`, measured against the narrowing the probe returned.

    **`n` is exact below the cap and a proof above it, and one division reads both.**
    `Narrowing.n` is *"EXACT when kind == 'set'"* (07:1581) and is `PREFILTER_MAX + 1` when the
    probe stopped counting, so above the cap this computes `live_blocks / (PREFILTER_MAX + 1)` --
    a factor that is too LARGE, because the true narrowed set is bigger than the count that came
    back. Too large is the safe direction and the only safe one: an over-fetch that is too small
    is *"silent recall loss that presents as absence"* (07:1782-1783) and one that is too big
    costs the backend a longer list. 07:722 calls `stat` *"the only input to the over-fetch factor
    above `PREFILTER_MAX`"*, and at the cap the two readings -- the probe's capped count, and the
    bound `PREFILTER_MAX` that `stat` alone would give -- differ by one block.

    **A stale or missing `stat` takes the maximum, before anything is divided.** 07:729:
    *"age > STAT_MAX_AGE_NS or a key is missing => the over-fetch factor is the maximum clamp,
    64"*, and 07:722 gives the reason -- *"a wrong over-fetch factor is a silent recall loss"*, so
    *"staleness fails expensive"*. A `live_blocks` of zero IS the missing key: `stat` is that
    count's only writer.

    **`ceil` and not `round`.** The factor multiplies `PackSpec.k` into a fetch depth, and half a
    candidate rounded down is a candidate the post-filter cannot give back.
    """
    if caps.stat_age_ns > STAT_MAX_AGE_NS or caps.live_blocks <= 0:
        return STALE_OVERFETCH
    if n.kind == "empty" or n.n <= 0:
        return 1
    return min(max(math.ceil(caps.live_blocks / n.n), 1), STALE_OVERFETCH)


def bind_overfetch(query_plan: QueryPlan, n: Narrowing, caps: IndexCaps) -> QueryPlan:
    """Decision 3 applied: the semantic spec's `overfetch` and `limit`, once a narrowing exists.

    **`plan_digest` is not recomputed and must not be.** 07:1545: it *"is computed over the
    unbound specs, so two different queries of the same shape share a plan digest and the
    scoreboard can slice by plan"*. The over-fetch factor is a function of the filter values, which
    is exactly the material a shape excludes; a digest that moved here would slice the scoreboard
    by narrowed-set size instead of by query shape.

    **Only `semantic`.** `LEX_OVERFETCH = 5` is *"always"* (07:1780) and the three exact Channels
    fetch what they rank; 07:1781 gives the selectivity clamp to the semantic Channel by name,
    because it is the one Channel whose filter may have to be pushed into a backend instead of
    joined. `limit` moves with it, since 07:3297 makes the limit `k x overfetch` and a factor
    without a depth is a number nobody spends.
    """
    factor = overfetch_clamp(n, caps)
    channels = tuple(
        dataclasses.replace(spec, overfetch=factor, limit=query_plan.pack.k * factor)
        if spec.name == "semantic"
        else spec
        for spec in query_plan.channels
    )
    return dataclasses.replace(query_plan, channels=channels)


def _shape(
    q: Query, caps: IndexCaps, rule: Rule, budget: QueryBudget, key: tuple[object, ...]
) -> _Shape:
    """Everything the key determines. Called once per distinct shape."""
    names = _run_order(rule)
    _afford(names, budget)
    overfetch = {name: _overfetch(name, caps) for name in names}
    specs = tuple(
        ChannelSpec(
            name=name,
            budget_ms=_budget_ms(name, budget),
            limit=q.k * overfetch[name],
            overfetch=overfetch[name],
            weight=rule.weights.get(name),
            params={},
        )
        for name in names
    )
    gates = _gates(rule)
    short_circuit = None if q.mode == "prove_absent" else (rule.short_circuit or None)
    pack = PackSpec(k=q.k, max_blocks=q.max_blocks, max_chars=q.max_chars)
    digest = sha256_canonical(
        {
            "channels": [
                {
                    "budget_ms": spec.budget_ms,
                    "limit": spec.limit,
                    "name": spec.name,
                    "overfetch": spec.overfetch,
                    "weight": spec.weight,
                }
                for spec in specs
            ],
            "fusion": {"k": FusionSpec().k, "low_confidence": FusionSpec().low_confidence},
            "gates": list(gates),
            "key": [str(part) for part in key],
            "pack": [pack.k, pack.max_blocks, pack.max_chars],
            "scorer_version": SCORER_VERSION,
            "short_circuit": short_circuit,
        }
    )
    return _Shape(specs, FusionSpec(), pack, gates, short_circuit, digest, rule.rule_id)


def _run_order(rule: Rule) -> tuple[str, ...]:
    """The rule's own list, in the rule's own order, refused if it is not a channel set.

    07:1704 is the rule and it is the opposite of what the canonical order suggests: *"A rule that
    names its own channel list fixes that list's order -- `thematic` runs `semantic` before
    `structural` because there the semantic ranked set is the seed."* So the planner does not sort.

    One constraint survives that, and 07:1707 gives it to the linter: *"the one constraint
    `ow route lint` enforces on a hand-authored list is that a list containing both `lexical` and
    `structural` names `lexical` first."* It is enforced here as well, and for the reason RT8 gives
    for the rung trigger: the linter runs on an installation that can be edited afterwards, and the
    planner is the last place the list is in hand before a Channel seeds itself from a ranking that
    does not exist yet.
    """
    names = rule.channels
    unknown = [name for name in names if name not in CHANNELS]
    if unknown:
        raise UsageError(
            f"rule {rule.rule_id!r} names {unknown}, which is not among {', '.join(CHANNELS)}",
            fix=_FIX,
        )
    if len(set(names)) != len(names):
        raise UsageError(f"rule {rule.rule_id!r} names a Channel twice: {list(names)}", fix=_FIX)
    if not names:
        raise UsageError(
            f"rule {rule.rule_id!r} selects no Channel at all; a plan that runs nothing returns a "
            "zero no gate can distinguish from an absence",
            fix=_FIX,
        )
    pair = {"lexical", "structural"} <= set(names)
    if pair and names.index("structural") < names.index("lexical"):
        raise UsageError(
            f"rule {rule.rule_id!r} runs structural before lexical; structural's fallback seed is "
            "lexical's re-ranked top-N, which does not exist yet at that point (07:1697)",
            fix=_FIX,
        )
    return names


def _afford(names: tuple[str, ...], budget: QueryBudget) -> None:
    """`sum(channel_ms) + hydration_reserve_ms <= query_ms`, over the Channels THIS plan runs.

    `ow route lint` check 3 sums every entry in `[retrieval.budget] channel_ms`; this sums the ones
    the plan selected, which is never larger and is the number the query will actually spend. The
    shipped five sum to 210 against a 250 ms `query_ms` net of a 40 ms reserve -- exactly equal,
    and a `<=` is what 07:1104's own arithmetic asks for.
    """
    total = sum(_budget_ms(name, budget) for name in names)
    if total > budget.schedulable_ms:
        raise UsageError(
            f"the {len(names)} selected Channels budget {total} ms against query_ms "
            f"{budget.query_ms} less a {budget.hydration_reserve_ms} ms hydration reserve; every "
            "query would end at the query deadline with Channels reporting OFF(query_deadline)",
            fix=_FIX,
        )


def _budget_ms(name: str, budget: QueryBudget) -> int:
    """This Channel's own deadline: case one of the split, and all a plan can set of it."""
    if name not in budget.channel_ms:
        raise UsageError(
            f"[retrieval.budget] channel_ms has no entry for {name!r}; a Channel with no deadline "
            "of its own can only ever be stopped by the query deadline, which is the outcome that "
            "does NOT force degraded",
            fix=_FIX,
        )
    return budget.channel_ms[name]


def _overfetch(name: str, caps: IndexCaps) -> int:
    """`LEX_OVERFETCH` for lexical; the stale clamp for semantic; 1 for the three exact Channels."""
    if name == "lexical":
        return LEX_OVERFETCH
    if name == "semantic" and caps.stat_age_ns > STAT_MAX_AGE_NS:
        return STALE_OVERFETCH
    return 1


def _gates(rule: Rule) -> tuple[str, ...]:
    """The fifteen, as this rule modifies them. Order preserved, because order is precedence.

    The modifier spelling appears exactly once in the plan -- `gates = ["+similarity_only:off"]`
    (07:1746) -- and nothing anywhere defines the `+` or the `:off`. D237. Two forms are parsed,
    `+<gate>:off` and `+<gate>:on`, and every other spelling is refused: a token this function
    silently ignored would leave a gate in a plan an author believed they had removed, and the gate
    set is what `build_verdict()` walks to decide whether `absent` is reachable at all.
    """
    gates = list(ABSENCE_GATES)
    for token in rule.gates:
        name, _, state = token.removeprefix("+").partition(":")
        if not token.startswith("+") or state not in ("on", "off") or name not in ABSENCE_GATES:
            raise UsageError(
                f"{token!r} is not a gate modifier; the one form the plan prints is "
                "'+<gate>:off' over a member of ABSENCE_GATES (07:1746)",
                fix=_FIX,
            )
        if state == "off" and name in gates:
            gates.remove(name)
        elif state == "on" and name not in gates:
            gates.insert(ABSENCE_GATES.index(name), name)
    return tuple(gates)


def _filter_fields(filters: Filters) -> tuple[str, ...]:
    """Which `Filters` fields this query set, by name. The values never enter the memo key.

    That exclusion is 07:1546's whole mechanism: *"two different queries of the same shape share a
    plan digest and the scoreboard can slice by plan"*. A key carrying `uri_prefix`'s value would
    give every directory its own plan and the scoreboard a column with one row per query.
    """
    blank = NO_FILTERS
    return tuple(
        sorted(
            field.name
            for field in dataclasses.fields(filters)
            if getattr(filters, field.name) != getattr(blank, field.name)
        )
    )
