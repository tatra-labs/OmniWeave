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

Specified in 07-store-and-retrieval.md section 6; scheduled by 16-roadmap.md:657.
"""

from __future__ import annotations

import dataclasses
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
    from omniweave_core.store.types import Filters, IndexCaps

__all__ = [
    "EVIDENCE_KEYS",
    "LEX_OVERFETCH",
    "MEMO_FIELDS",
    "MEMO_MAX",
    "STALE_OVERFETCH",
    "STAT_MAX_AGE_NS",
    "clear_memo",
    "evidence",
    "memo_key",
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
"""The maximum of 07:1592's `clamp(1/selectivity, 1, 64)`, forced on a stale `stat` (07:729).

The clamp itself is **not** computed here and cannot be: it is a function of the narrowing's `n`,
`n` is a function of the filter *values*, and the memo key carries the filter field set and never
the values. `retrieve()` applies the clamp at bind time. What a plan can say is the one value the
clamp takes when the statistics are too old to argue with, and saying it in the plan is what makes
`--explain` show an operator that their `stat` is stale before the query is slow."""

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


def plan(q: Query, caps: IndexCaps, pol: RetrievalPolicy) -> QueryPlan:
    """One `QueryPlan`: the ordered specs, their own deadlines, the gates, and two digests.

    Pure. The memo it consults is a cache of this function over its own key and holds no state a
    caller can observe except through `clear_memo()`, which exists for the property test that two
    calls of the same shape return the same digest by arithmetic rather than by cache.
    """
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
