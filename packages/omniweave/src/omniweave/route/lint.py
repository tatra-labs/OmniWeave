"""`ow route lint`'s checkable half: the interval-box subsumption linter, and the five checks that
are functions of a compiled policy and the `SignalSpec` registry alone.

05-ingest-and-routing.md section 4.5 (:1767-1814) lists **fourteen** mechanical checks and section
4.3 property 5 (:1167-1174) specifies the one this module exists for:

> A rule whose condition box is subsumed by an earlier action rule at the same `(rung, lane, phase)`
> can never fire; it is a silently disabled guard, which is worse than a missing rule. `ow route
> lint` reports `OW-P-011` and the compiler drops it from the demand plan with a recorded
> `Degradation(kind="policy_pruned")`. Subsumption is computed over interval boxes, which is
> decidable precisely because the grammar is comparison-only. Modifier rules are exempt: they are
> *meant* to overlap.

16-roadmap.md:604 gives the linter and the fitter to W5.2; W5.5 owns the `ow route lint` **command**
that renders a `Report`.

## Sound, never complete, and the incompleteness is named rather than implied

F30 (17-risks.md:890) is this module's shape, and it is a decision and not a caveat:

> Interval-box subsumption, which is **incomplete over open string domains** -- exactly where policy
> authors collide ... the linter reports only the complete cases **and says so** -- a lint that
> overclaims is worse than none.

So `subsumption()` returns two sequences, not one. `Finding`s are **proofs**: every one names a pair
for which every evidence state firing the later rule also fires the earlier. `Undecided`s are the
comparisons the algebra could not settle, each carrying the key and the reason. A caller that prints
the first and drops the second is reporting a lint that overclaims; `Report.render()` prints both
and `ow route lint --strict` is W5.5's decision about which of them fails a build.

**Four things can make a comparison undecidable, and they are the complete list.** Each is checked
for explicitly and each writes its own `reason`:

1. `UNDECIDED_OPEN_DOMAIN` -- the later rule excludes values (`ne`, `not_in`) on a `str` key whose
   domain is not a closed `frozenset`, and the earlier rule requires values. Deciding
   `D \\ {a} ⊆ {b, c}` needs `D`. `unit.format` is the case that matters and 05:631 is why it can
   never be closed: *"The domain is **computed, never closed**: a third party's token joins it by
   enabling the card."* This is F30 exactly, and it is the only one of the four the grammar cannot
   be written around.
2. `UNDECIDED_NONE_OF` -- either `when` is a `none_of`. A complement of a union of boxes is not a
   box, and intersecting it with anything re-enters the algebra somewhere it cannot represent.
3. `UNDECIDED_ON_UNKNOWN` -- the **later** rule declares `on_unknown = "match"` or `"defer"`, so its
   firing set is its box plus an UNKNOWN region, AND the earlier rule matches the all-unknown record
   too. See below: most pairs of this shape are *decided*, against subsumption, by a witness.
4. `UNDECIDED_UNION` -- the earlier rule is an `any_of` and the later box fits no single disjunct.
   Containment in a union of boxes is decidable in principle; this module tests only the sufficient
   condition (the box fits one disjunct), because the complete test needs the boxes to be
   disjointified and the shipped policy has no pair that needs it.

## Why the EARLIER rule's `on_unknown` is irrelevant and the LATER rule's is not

The question check 8 asks is about *firing sets*, not boxes, and `on_unknown` is what separates
them. Write `box(R)` for the states where `R.when` is definitely True.

For the earlier rule the two possible readings both help. `skip` and `defer` fire exactly on
`box(R)`; `match` fires on `box(R)` plus every state where some key is UNKNOWN. Both are supersets
of `box(R)`, so proving `box(later) ⊆ box(earlier)` proves the firing containment either way --
and the argument is worth writing down because the opposite conclusion is the intuitive one.

For the later rule it does not work. A `match` rule fires on states where one of its keys is absent,
and nothing about the earlier rule's box says those states are inside it; a `defer` rule does
something on those states too -- it defers, and 05:1023's *"later matching action rules are not
tested"* means a subsumed rule's deferral never happens either, which is an effect and not a
non-event. **So box subsumption and unfirability are not the same property, and 05:1169 equates
them** -- which is fine for the twenty-three shipped rules that declare no `on_unknown` and the ten
that declare `"skip"`, and not fine for the seven that declare `"match"` or `"defer"`, six of which
are action rules. D207.

`_under_unknown()` decides most of those pairs anyway, and against subsumption: on the record where
every key is UNKNOWN the later rule fires or defers, so if the earlier rule does not match there,
the later rule provably *can* fire and `OW-P-011`'s *"can never fire"* is false of it. Thirteen of
the shipped policy's fifty-two ordered action pairs take that path and twelve are decided by it.
`UNDECIDED_ON_UNKNOWN` is the thirteenth -- `decode.broken-font-encoding` against
`decode.part-text-unusable`, both `on_unknown = "match"`, so both fire on the all-unknown record
and the witness proves nothing. It is the **only** comparison in the whole shipped policy this
module cannot settle: fifty-one decided, one not, and zero findings.

## What the box algebra is, and where the two halves meet

`Span` is a real interval with finitely many excluded points; `Cat` is a finite set of categorical
scalars or the complement of one. The split is on the key's **dtype** and not on the operator,
because `ne` means two different things on the two sides: on a `float` key it is an interval with a
hole and stays inside the interval algebra, and on a `str` key it is a complement and needs the
domain. That one dispatch is what confines F30's incompleteness to categorical keys.

`Cat` carries its `universe` -- the key's declared `frozenset[str]` domain, or `{True, False}` for a
`bool` dtype, or `None`. Only one of the four containment directions consults it
(`complement ⊆ positive`), which is why an open domain costs so little: a finite positive set inside
a complement, a complement inside a complement, and two positive sets are all decided without
knowing `D`.

## The five other checks here, and the eight that are not

Implemented, because each is a function of `(policy, registry)` and nothing else: check 1
(`OW-P-001`, every key resolves), check 2 (`OW-P-002`, every literal is in its signal's domain),
check 4 (`OW-P-004`, a two-line call into `policy.rules_needing_on_unknown()`), check 7
(`OW-P-010`, no rule reads a key requiring a later rung) and check 10 (`OW-P-014`, the `unit.format`
union equals the computed domain) -- check 10 only when the caller supplies the domain, because
core's forty-eight live in `route/detect.py`, which is section 2.2's module and not yet built.

`NOT_RUN` carries the other eight **as data**, each with the reason it is absent, and `Report`
prints them. Two of the eight are absent because they cannot reach here: checks 5 and 12 are
`OW-P-005` and `OW-P-013`, which `load_layer()` raises at load, so a policy carrying either never
compiles into something this module could be handed. The other six need a driver catalog, a card or
`retrieval.toml`.

Specified in 05-ingest-and-routing.md sections 4.3 and 4.5; F30 in 17-risks.md:890; scheduled by
16-roadmap.md:604.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.observe.degradation import Degradation

from omniweave.route.evidence import ComputedDomain, Evidence
from omniweave.route.policy import ORDERED_OPS, rules_needing_on_unknown
from omniweave.route.rung import Rung

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave.route.checks import Installation
    from omniweave.route.evidence import Scalar, SignalRegistry
    from omniweave.route.policy import Clause, RoutePolicy, Rule, Test, When

__all__ = [
    "NOT_RUN",
    "UNDECIDED_NONE_OF",
    "UNDECIDED_ON_UNKNOWN",
    "UNDECIDED_OPEN_DOMAIN",
    "UNDECIDED_UNION",
    "Cat",
    "Finding",
    "Report",
    "Span",
    "Undecided",
    "boxes_of",
    "contains",
    "degradations",
    "format_token_union",
    "lint",
    "subsumption",
]

# --------------------------------------------------------------------------------------------
# 1. The fourteen, and which eight are not here.
# --------------------------------------------------------------------------------------------

SUBSUMPTION_CODE: Final[str] = "OW-P-011"
"""Check 8. 05:1781 and 05:1169, which is the sentence that says what it is FOR."""

NOT_RUN: Final[Mapping[int, str]] = MappingProxyType(
    {
        3: "OW-P-003 is the retrieval surface's channel-budget sum and reads retrieval.toml "
        "(07-store-and-retrieval.md section 4.4, which owns hydration_reserve_ms)",
        5: "OW-P-005 is raised by load_layer(); a policy carrying a backward escalate_to or "
        "skip_rungs member never compiles into a RoutePolicy this module could be handed",
        6: "OW-P-006 resolves every then.driver and every [[pin]] target against omniweave.toml "
        "[drivers] enabled, which is configuration and not policy",
        9: "OW-P-012 reads the chosen driver's [cost.model] class, which is a card",
        11: "OW-P-015 compares a rule's format tokens against the driver's served token set, which "
        "is {format_token_for(m) for m in [capability] formats} union the card's format_tokens",
        12: "OW-P-013 is raised by load_layer(); a `then` doing nothing never compiles",
        13: "OW-P-021 compares [budget.*] micros against card.reserved_micros, which is a card",
        14: "OW-P-024 needs the same [drivers] enabled set check 6 reads",
    }
)
"""The eight checks section 4.5 lists that this module does not run, and why -- **as data**.

A linter that silently ran six of fourteen would be the overclaim F30 objects to, one level up from
subsumption. Two of the eight are already enforced and are listed anyway: a reader counting checks
should find fourteen accounted for, not six plus silence.

A `MappingProxyType` because it is `Report.not_run`'s default and a caller holding the default is
holding this object: a lint whose list of unrun checks could be edited by whatever last read it is
a lint that could be made to look complete.
"""

UNDECIDED_OPEN_DOMAIN: Final[str] = "open-string-domain"
"""F30's case, and the only one of the four the grammar cannot be written around. See above."""

UNDECIDED_NONE_OF: Final[str] = "none-of-is-not-a-box"
UNDECIDED_ON_UNKNOWN: Final[str] = "later-rule-fires-on-unknown"
UNDECIDED_UNION: Final[str] = "earlier-rule-is-a-union"

_INF: Final[float] = math.inf

_BLANK_SHA: Final[str] = "0" * 64
"""The scope of `_under_unknown`'s empty record. Unrelated to INV-19's `witness`.

`Evidence.__init__` requires a `content_sha256` and 05:1856's printed class reads it nowhere --
`read()` takes a key and returns a `Scalar` -- so a lint's throwaway record carries a sha that
names nothing rather than borrowing a real unit's."""


# --------------------------------------------------------------------------------------------
# 2. The value algebra. Two shapes, split on dtype and not on operator.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Span:
    """A real interval with finitely many excluded points. The `float`/`int` half of a box.

    `holes` is what keeps `ne` inside this algebra: on a numeric key `{ne: 0.5}` is
    `(-inf, inf) \\ {0.5}`, which is not an interval but is exactly an interval minus a
    finite set -- and containment between two of those is decidable with no extra machinery.
    Without it every numeric `ne` would be a `Cat` complement over an unbounded universe and so
    undecidable, putting F30's incompleteness on `garble.score` as well as on `unit.format`.

    The endpoints are `-inf`/`inf` by default and the open/closed flags are the operator's:
    `lt` writes `hi` open, `lte` writes it closed. A declared `domain` column is deliberately NOT
    intersected in -- doing so would make a routing lint's verdict depend on a provider honouring a
    declared range at runtime, and 05:2100 gives that column to check 2, which tests a rule's
    LITERALS, not a provider's outputs.
    """

    lo: float = -_INF
    hi: float = _INF
    lo_closed: bool = False
    hi_closed: bool = False
    holes: frozenset[float] = frozenset()

    @property
    def empty(self) -> bool:
        if self.lo > self.hi:
            return True
        return self.lo == self.hi and not (self.lo_closed and self.hi_closed)

    @property
    def universal(self) -> bool:
        return self.lo == -_INF and self.hi == _INF and not self.holes

    def holds(self, value: Scalar) -> bool:
        """Is this scalar in the span? A non-number never is -- an ordered test over a `str` reads
        as UNKNOWN (`Test.holds`), so the state is not in the box."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        if value in self.holes:
            return False
        lower = self.lo <= value if self.lo_closed else self.lo < value
        upper = value <= self.hi if self.hi_closed else value < self.hi
        return lower and upper

    def point(self) -> float | None:
        """The one value this span holds, or `None` if it holds zero or infinitely many."""
        if self.lo == self.hi and self.lo_closed and self.hi_closed and self.lo not in self.holes:
            return self.lo
        return None


@dataclass(frozen=True, slots=True)
class Cat:
    """A finite set of categorical scalars, or -- when `positive` is False -- its complement.

    The complement is taken within `universe`, which is the key's declared `frozenset[str]` domain,
    `{True, False}` for a `bool` dtype, or `None` when the domain is open. **Only one of the four
    containment directions reads it**, and that asymmetry is the whole reason an open domain is
    cheap: `{a} ⊆ {a, b}`, `{a, b} ⊆ D \\ {c}` and `D \\ {a, b} ⊆ D \\ {a}` are all decided without
    knowing `D`, and only `D \\ {a} ⊆ {b, c}` is not.
    """

    items: frozenset[Scalar]
    positive: bool = True
    universe: frozenset[Scalar] | None = None

    @property
    def empty(self) -> bool:
        if self.positive:
            return not self.items
        return self.universe is not None and self.universe <= self.items

    @property
    def universal(self) -> bool:
        return not self.positive and not self.items

    def holds(self, value: Scalar) -> bool:
        return (value in self.items) == self.positive


@dataclass(frozen=True, slots=True)
class Presence:
    """`{exists: bool}` -- the only test 05:1004 calls TOTAL, and the only one defined on UNKNOWN.

    It is its own shape rather than a `Cat` over `{present, absent}` because presence is orthogonal
    to value: every other constraint already implies presence (a test over UNKNOWN is UNKNOWN, so a
    state in any value-constrained box has the key), while `{exists: false}` implies the key has no
    value at all and therefore contradicts every one of them.
    """

    present: bool


PRESENT: Final[Presence] = Presence(present=True)
ABSENT: Final[Presence] = Presence(present=False)
EMPTY: Final[Cat] = Cat(items=frozenset())
"""The empty constraint -- what a contradiction meets to. `{exists: false}` with a value test."""

Constraint = Span | Cat | Presence
Box = dict[str, Constraint]
"""One conjunction: key -> the constraint that key must satisfy. A key absent from the mapping is
unconstrained, which is NOT the same as `PRESENT` -- the rule does not read it at all."""


def _is_empty(constraint: Constraint) -> bool:
    return constraint.empty if isinstance(constraint, Span | Cat) else False


def _is_universal(constraint: Constraint) -> bool:
    return constraint.universal if isinstance(constraint, Span | Cat) else False


def contains(outer: Constraint, inner: Constraint) -> bool | None:
    """Is every state satisfying `inner` also satisfying `outer`? `None` is UNDECIDABLE.

    Three-valued and never a guess. `False` means a witness exists -- some value satisfies `inner`
    and not `outer` -- and `None` means the algebra cannot say, which is only ever the
    `complement ⊆ positive` case over an open categorical domain. Callers report on `True` alone.
    """
    if _is_empty(inner):
        return True
    if _is_universal(outer) and not isinstance(inner, Presence):
        return True
    if isinstance(outer, Presence) or isinstance(inner, Presence):
        return _contains_presence(outer, inner)
    return _contains_values(outer, inner)


def _contains_presence(outer: Constraint, inner: Constraint) -> bool:
    """Every pair where one side is `{exists: bool}`. Four answers and no undecidables.

    `{exists: true}` as the OUTER is implied by every value constraint, since a test over UNKNOWN is
    UNKNOWN and a state in a value-constrained box therefore has the key. `{exists: false}` as the
    outer is implied by nothing else. As the INNER, `{exists: true}` alone permits every present
    value and so fits only a universal outer -- which `contains()` has already returned -- and
    `{exists: false}` permits no value at all.
    """
    if isinstance(outer, Presence):
        return (inner != ABSENT) if outer.present else (inner == ABSENT)
    return False


def _contains_values(outer: Span | Cat, inner: Span | Cat) -> bool | None:
    """The 2x2 of the two value shapes. One of the four consults a universe; see `_cat_in_cat`."""
    if isinstance(outer, Span) and isinstance(inner, Span):
        return _span_in_span(outer, inner)
    if isinstance(outer, Span) and isinstance(inner, Cat):
        return _cat_in_span(outer, inner)
    if isinstance(outer, Cat) and isinstance(inner, Span):
        return _span_in_cat(outer, inner)
    assert isinstance(outer, Cat) and isinstance(inner, Cat)  # noqa: S101 -- the fourth of four
    return _cat_in_cat(outer, inner)


def _span_in_span(outer: Span, inner: Span) -> bool:
    """Interval containment, plus: every point `outer` excludes must be outside `inner` too."""
    if outer.lo > inner.lo or (outer.lo == inner.lo and inner.lo_closed and not outer.lo_closed):
        return False
    if outer.hi < inner.hi or (outer.hi == inner.hi and inner.hi_closed and not outer.hi_closed):
        return False
    return all(not inner.holds(hole) for hole in outer.holes)


def _cat_in_span(outer: Span, inner: Cat) -> bool | None:
    """A categorical set inside a numeric interval. Decidable one way only."""
    if inner.positive:
        return all(outer.holds(item) for item in inner.items)
    # The complement of a finite set of numbers is unbounded, so it fits no bounded interval; and
    # an unbounded `outer` was already returned as universal unless it carries holes, which the
    # complement does not exclude. Either way the answer is False, and it is a proof.
    return False


def _span_in_cat(outer: Cat, inner: Span) -> bool:
    """A numeric interval inside a categorical set. Also decidable, and by counting."""
    if outer.positive:
        # A finite set can hold an interval only if the interval is one point.
        point = inner.point()
        return point is not None and point in outer.items
    # A complement holds the interval iff none of the excluded values is in it. No universe needed.
    return all(not inner.holds(item) for item in outer.items)


def _cat_in_cat(outer: Cat, inner: Cat) -> bool | None:
    """The four directions, and the one that needs the universe. F30 lives in the last line."""
    if inner.positive and outer.positive:
        return inner.items <= outer.items
    if inner.positive and not outer.positive:
        return not (inner.items & outer.items)
    if not inner.positive and not outer.positive:
        return outer.items <= inner.items
    universe = inner.universe if inner.universe is not None else outer.universe
    if universe is None:
        return None
    return (universe - inner.items) <= outer.items


def meet(left: Constraint, right: Constraint) -> Constraint:
    """The intersection of two constraints on one key -- what `all_of` does across its clauses.

    Every pair has an exact answer in one of the two shapes, which is the property that makes an
    `all_of` of N clauses compile to a single box rather than to N of them.
    """
    if isinstance(left, Presence) or isinstance(right, Presence):
        return _meet_presence(left, right)
    if isinstance(left, Span) and isinstance(right, Span):
        return Span(
            lo=max(left.lo, right.lo),
            hi=min(left.hi, right.hi),
            lo_closed=_closed_at(max(left.lo, right.lo), left, right, lower=True),
            hi_closed=_closed_at(min(left.hi, right.hi), left, right, lower=False),
            holes=left.holes | right.holes,
        )
    if isinstance(left, Span) and isinstance(right, Cat):
        return _meet_span_cat(left, right)
    if isinstance(left, Cat) and isinstance(right, Span):
        return _meet_span_cat(right, left)
    assert isinstance(left, Cat) and isinstance(right, Cat)  # noqa: S101 -- the fourth of four
    return _meet_cat_cat(left, right)


def _meet_presence(left: Constraint, right: Constraint) -> Constraint:
    """`{exists: true}` adds nothing to a value test; `{exists: false}` contradicts every one."""
    if ABSENT in (left, right):
        return ABSENT if left == right else EMPTY
    if left == PRESENT:
        return right
    return left


def _closed_at(bound: float, left: Span, right: Span, *, lower: bool) -> bool:
    """Is the tighter of two bounds closed? Both, when the two bounds coincide."""
    flags = [
        (span.lo, span.lo_closed) if lower else (span.hi, span.hi_closed) for span in (left, right)
    ]
    return all(closed for value, closed in flags if value == bound)


def _meet_span_cat(span: Span, cat: Cat) -> Constraint:
    if cat.positive:
        return Cat(
            items=frozenset(item for item in cat.items if span.holds(item)),
            universe=cat.universe,
        )
    numeric = frozenset(
        float(item)
        for item in cat.items
        if isinstance(item, int | float) and not isinstance(item, bool)
    )
    return Span(
        lo=span.lo,
        hi=span.hi,
        lo_closed=span.lo_closed,
        hi_closed=span.hi_closed,
        holes=span.holes | numeric,
    )


def _meet_cat_cat(left: Cat, right: Cat) -> Cat:
    universe = left.universe if left.universe is not None else right.universe
    if left.positive and right.positive:
        return Cat(items=left.items & right.items, universe=universe)
    if left.positive:
        return Cat(items=left.items - right.items, universe=universe)
    if right.positive:
        return Cat(items=right.items - left.items, universe=universe)
    return Cat(items=left.items | right.items, positive=False, universe=universe)


# --------------------------------------------------------------------------------------------
# 3. From a `when` to a disjunction of boxes.
# --------------------------------------------------------------------------------------------


def _universe(
    registry: SignalRegistry | None, key: str, format_domain: Iterable[str] | None
) -> frozenset[Scalar] | None:
    """The closed set a `ne`/`not_in` on this key is a complement of, or `None` for an open one.

    Three sources and one refusal. A `bool` dtype has `{True, False}` whatever its `domain` column
    says -- 05:2099 gives that column to *"a bool or an unbounded int"*, so a bool's domain is
    always absent and always known. A literal `frozenset[str]` domain is itself the universe. A
    `ComputedDomain` is the caller's to supply or to withhold, and withholding is the honest
    default: 05:631 says of `unit.format` that *"the domain is **computed**, never closed"*, so a
    linter treating core's forty-eight as closed would prove a subsumption a third party undoes.
    """
    if registry is None:
        return None
    if registry.dtype_of(key) == "bool":
        return frozenset({True, False})
    domain = registry.domain_of(key)
    if isinstance(domain, frozenset):
        return frozenset(domain)
    if domain is ComputedDomain.FORMAT_TOKENS and format_domain is not None:
        return frozenset(format_domain)
    return None


def _constraint(
    test: Test, key: str, registry: SignalRegistry | None, format_domain: Iterable[str] | None
) -> Constraint:
    """One `Test`, as a constraint. The dtype dispatch on `eq`/`ne` is the load-bearing line.

    `ne` on a `float` key is an interval with a hole and `ne` on a `str` key is a complement over a
    possibly-open domain; sending both down one path would either lose numeric decidability or
    invent a universe for strings. The dispatch is on the VALUE and not on the registry's dtype
    column, because a test's own literal is the thing that has to be comparable and check 2 is the
    check that reconciles the two.
    """
    if test.op == "exists":
        return PRESENT if test.value is True else ABSENT
    if test.op in ORDERED_OPS:
        return _span_of(test.op, float(test.value))  # type: ignore[arg-type] -- a number by load
    items = frozenset(_literals(test))
    positive = test.op in {"eq", "in"}
    if _numeric(items):
        return _numeric_constraint(items, positive=positive)
    return Cat(items=items, positive=positive, universe=_universe(registry, key, format_domain))


def _span_of(op: str, bound: float) -> Span:
    """The four ordered ops, as half-lines. The open/closed flag IS the difference between them."""
    if op == "lt":
        return Span(hi=bound)
    if op == "lte":
        return Span(hi=bound, hi_closed=True)
    if op == "gt":
        return Span(lo=bound)
    return Span(lo=bound, lo_closed=True)


def _numeric(items: frozenset[Scalar]) -> bool:
    """Are all of these numbers? `bool` is excluded deliberately: it is an `int` in Python and a
    categorical value in this grammar, and `{eq: true}` compiled to the interval `[1, 1]` would make
    `driver.unavailable` numerically comparable to `decode.char_count`."""
    return bool(items) and all(
        isinstance(item, int | float) and not isinstance(item, bool) for item in items
    )


def _numeric_constraint(items: frozenset[Scalar], *, positive: bool) -> Constraint:
    values = frozenset(float(item) for item in items)  # type: ignore[arg-type] -- `_numeric` checked
    if not positive:
        return Span(holes=values)
    if len(values) == 1:
        only = next(iter(values))
        return Span(lo=only, hi=only, lo_closed=True, hi_closed=True)
    return Cat(items=frozenset(values))


def _box_of_clause(
    clause: Clause, registry: SignalRegistry | None, format_domain: Iterable[str] | None
) -> dict[str, Constraint]:
    box: dict[str, Constraint] = {}
    for key, test in clause.tests:
        one = _constraint(test, key, registry, format_domain)
        box[key] = meet(box[key], one) if key in box else one
    return box


def boxes_of(
    when: When,
    *,
    registry: SignalRegistry | None = None,
    format_domain: Iterable[str] | None = None,
) -> tuple[Box, ...] | None:
    """A `when` as a disjunction of boxes, or `None` when it is not representable.

    Three of the four `when` forms compile. A bare clause and an `all_of` are one box -- `all_of` by
    `meet`ing its clauses key by key, which is exactly why `meet` has to be total. An `any_of` is
    one box per clause, and the disjunction is the reason `subsumption()` quantifies over the
    later rule's boxes and existentially over the earlier rule's.

    `none_of` returns `None`. It is the complement of a union of boxes, which is neither a box nor a
    union of them, and 05:968's *"1 level"* means there is no nesting to push the negation through.
    """
    if when.op == "none_of":
        return None
    boxes = [_box_of_clause(clause, registry, format_domain) for clause in when.clauses]
    if when.op == "any_of":
        return tuple(boxes)
    merged: dict[str, Constraint] = {}
    for box in boxes:
        for key, one in box.items():
            merged[key] = meet(merged[key], one) if key in merged else one
    return (merged,)


# --------------------------------------------------------------------------------------------
# 4. Check 8 -- the subsumption linter.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's verdict on one rule. A `Finding` is a PROOF, never a suspicion.

    `where` is the `(rung, lane, phase)` group for check 8 and empty for the checks that are
    per-rule; `against` is the subsuming rule, which 15:1077 makes the payload of the
    `policy_pruned` degradation -- *"the subsuming rule's id"*.
    """

    code: str
    check: int
    rule_id: str
    message: str
    against: str = ""
    where: str = ""
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class Undecided:
    """One comparison the algebra could not settle, and the named reason. F30's other half.

    This is not an error and not a warning. It is the count that makes the linter's claim honest:
    *"the linter reports only the complete cases and says so"* (17:890) requires the second half to
    be a number a reader can see, not a paragraph in a docstring.
    """

    rule_id: str
    against: str
    where: str
    reason: str
    key: str = ""


@dataclass(frozen=True, slots=True)
class Report:
    """What `lint()` produced: the proofs, the gaps, and the checks it never ran.

    `compared` is the number of ordered action-rule pairs check 8 actually decided, so
    `compared + len(undecided)` is the total it looked at and the ratio is F30's measurement -- the
    *"interval-box subsumption yield"* 17:525 budgets three engineer-days against a deliberately
    messy 150-rule policy.
    """

    findings: tuple[Finding, ...] = ()
    undecided: tuple[Undecided, ...] = ()
    compared: int = 0
    not_run: Mapping[int, str] = field(default_factory=lambda: NOT_RUN)

    @property
    def ok(self) -> bool:
        """True iff no check produced an error. A warning and an undecidable do not fail a build."""
        return not any(finding.severity == "error" for finding in self.findings)

    def render(self) -> tuple[str, ...]:
        """Every line `ow route lint` prints, findings first and the unrun checks last.

        The unrun checks are printed unconditionally and on a clean run too, because a linter that
        announced its silence only when it had something else to say would be silent exactly when a
        reader was most likely to read "no findings" as "nothing is wrong".
        """
        lines = [
            f"{f.severity}: {f.code} check {f.check}: {f.rule_id}: {f.message}"
            for f in self.findings
        ]
        lines += [
            f"undecided: {u.rule_id} vs {u.against} at {u.where}: {u.reason}"
            + (f" ({u.key})" if u.key else "")
            for u in self.undecided
        ]
        lines.append(f"check 8 decided {self.compared} pair(s); {len(self.undecided)} undecided")
        lines += [f"not run: check {number}: {why}" for number, why in sorted(self.not_run.items())]
        return tuple(lines)


def subsumption(
    policy: RoutePolicy,
    *,
    registry: SignalRegistry | None = None,
    format_domain: Iterable[str] | None = None,
) -> tuple[tuple[Finding, ...], tuple[Undecided, ...], int]:
    """Check 8. Every action rule subsumed by an EARLIER action rule at its `(rung, lane, phase)`.

    05:1781 states both exemptions and this reads them literally. **Modifier rules are exempt on
    both sides**: 05:1174 says they *"are meant to overlap"*, and 05:1023's evaluation order is why
    the exemption is not merely a convenience -- a matched action does not stop a later modifier
    from contributing, so a modifier inside another modifier's box is a working policy and not a
    dead guard. The group is `(rung, lane, phase)` and not `(rung, lane)` because 05:1136's
    derived phase is what separates `decode.part-text-unusable` from `decode.pdf-text-layer`:
    both declare `rung = "DECODE"` and the first settles after the driver has run, so it *"does
    not shadow"* the second.

    Returns the proofs, the gaps and the number of pairs decided, in that order. The caller decides
    what to do with the second, which is the one thing a lint that reports only the complete cases
    must not do for it.
    """
    findings: list[Finding] = []
    undecided: list[Undecided] = []
    compared = 0
    for rung, lane in _groups(policy):
        actions = [rule for rule in policy.rules_at(rung, lane) if rule.is_action]
        by_phase: dict[str, list[Rule]] = {}
        for rule in actions:
            by_phase.setdefault(policy.phase_of_rule(rule), []).append(rule)
        for phase, ordered in by_phase.items():
            where = f"{rung.name}/{lane}/{phase}"
            for index, later in enumerate(ordered):
                for earlier in ordered[:index]:
                    verdict, reason, key = _subsumes(
                        earlier, later, registry=registry, format_domain=format_domain
                    )
                    if verdict is None:
                        undecided.append(
                            Undecided(
                                rule_id=later.id,
                                against=earlier.id,
                                where=where,
                                reason=reason,
                                key=key,
                            )
                        )
                        continue
                    compared += 1
                    if verdict:
                        findings.append(_subsumed_finding(later, earlier, where))
                        break
    return tuple(findings), tuple(undecided), compared


def _subsumed_finding(later: Rule, earlier: Rule, where: str) -> Finding:
    return Finding(
        code=SUBSUMPTION_CODE,
        check=8,
        rule_id=later.id,
        against=earlier.id,
        where=where,
        message=(
            f"can never fire: every state matching it already matched {earlier.id!r}, which is "
            f"earlier at {where}. A silently disabled guard is worse than a missing rule "
            "(05:1169); narrow the earlier rule or move this one ahead of it"
        ),
    )


def _groups(policy: RoutePolicy) -> tuple[tuple[Rung, str], ...]:
    """Every `(rung, lane)` the policy actually declares, in first-appearance order.

    Derived from the rules rather than from `Rung x LANES`: `LANES` is open (05:3341, INV-21), so a
    product would either miss a third party's lane or iterate a cross product that is empty almost
    everywhere.
    """
    seen: list[tuple[Rung, str]] = []
    for rule in policy.rules:
        pair = (rule.rung, rule.lane)
        if pair not in seen:
            seen.append(pair)
    return tuple(seen)


def _subsumes(
    earlier: Rule,
    later: Rule,
    *,
    registry: SignalRegistry | None,
    format_domain: Iterable[str] | None,
) -> tuple[bool | None, str, str]:
    """Does `earlier` fire on every state where `later` fires? `(verdict, reason, key)`.

    The four undecidable cases are tested in the order they cost to detect, and each returns its own
    reason so the report can distinguish F30's case from the three the grammar could avoid.
    """
    if later.on_unknown in {"match", "defer"} and not later.when.total:
        return _under_unknown(earlier, later)
    inner_boxes = boxes_of(later.when, registry=registry, format_domain=format_domain)
    outer_boxes = boxes_of(earlier.when, registry=registry, format_domain=format_domain)
    if inner_boxes is None or outer_boxes is None:
        return None, UNDECIDED_NONE_OF, ""
    undecided_key = ""
    for inner in inner_boxes:
        if all(_is_empty(one) for one in inner.values()) and inner:
            # A self-contradictory box fires on nothing. It is unfirable, but it is not subsumed by
            # anything in particular, and check 8's code names a subsuming rule. Left alone.
            return False, "", ""
        fits, key = _fits_any(outer_boxes, inner)
        if fits is None:
            undecided_key = key
        elif not fits:
            return False, "", ""
    if undecided_key:
        return None, UNDECIDED_OPEN_DOMAIN, undecided_key
    return True, "", ""


def _under_unknown(earlier: Rule, later: Rule) -> tuple[bool | None, str, str]:
    """The later rule fires or defers on UNKNOWN. Can one state prove it is reached anyway?

    **The witness is the empty record**, and using the real evaluator on it rather than reasoning
    about it is the only way this stays correct: `when.holds()` already knows `exists` is total,
    that `any_of` is a Kleene OR and that a `none_of` of an UNKNOWN clause is UNKNOWN, and a
    re-derivation of those three facts inside a linter is a second semantics to keep in step with
    the first.

    On a record where every key is UNKNOWN, a later rule whose `when` reads as UNKNOWN fires (under
    `match`) or defers (under `defer`). Whether the EARLIER rule matched there is `holds()` plus its
    own `on_unknown`: definitely True matches, and UNKNOWN matches only under `"match"`. If it did
    not match, the later rule was reached. That is a **proof of non-subsumption**,
    not a failure to prove one -- which matters, because 05:1169's `OW-P-011` says the subsumed rule
    *"can never fire"*, and a rule that fires on the all-unknown state can.

    The remaining case -- the earlier rule matches the empty record too -- is genuinely undecidable
    here: the later rule's firing set is its box plus an UNKNOWN region this algebra does not
    represent, and containment of that union is not a box question. D207.
    """
    blank = Evidence(content_sha256=_BLANK_SHA)
    if later.when.holds(blank) is not None:
        return None, UNDECIDED_ON_UNKNOWN, ""
    verdict = earlier.when.holds(blank)
    matched = verdict is True or (verdict is None and earlier.on_unknown == "match")
    return (None, UNDECIDED_ON_UNKNOWN, "") if matched else (False, "", "")


def _fits_any(outer_boxes: Sequence[Box], inner: Box) -> tuple[bool | None, str]:
    """Is this box inside ANY of the earlier rule's boxes? The sufficient half of a union test.

    A box can be covered by a union of boxes without fitting inside any single one; deciding that
    needs the union disjointified, and `UNDECIDED_UNION` is what a caller sees instead. One
    disjunct is the whole test whenever the earlier `when` is a bare clause or an `all_of`, which is
    thirty-eight of the shipped forty.
    """
    undecided_key = ""
    for outer in outer_boxes:
        verdict, key = _box_in_box(outer, inner)
        if verdict:
            return True, ""
        if verdict is None:
            undecided_key = key
    if undecided_key:
        return None, undecided_key
    return False, ""


def _box_in_box(outer: Box, inner: Box) -> tuple[bool | None, str]:
    """`inner ⊆ outer`, key by key.

    **A key the earlier rule constrains and the later one does not is a proof of non-containment**,
    and the reason is worth stating because it is where a reader expects a subtlety that is not
    there: a state satisfying `inner` says nothing about that key, so it may be absent -- and an
    absent key makes the earlier rule's test UNKNOWN rather than True, which under `skip` does not
    fire and under `match` fires only because nothing contradicted it. Either way the containment is
    not proved by this algebra, so the answer is False.
    """
    undecided_key = ""
    for key, constraint in outer.items():
        if key not in inner:
            return False, ""
        verdict = contains(constraint, inner[key])
        if verdict is False:
            return False, ""
        if verdict is None:
            undecided_key = key
    return (None, undecided_key) if undecided_key else (True, "")


def degradations(findings: Iterable[Finding]) -> tuple[Degradation, ...]:
    """The `Degradation(kind="policy_pruned")` rows 05:1170 orders for the pruned rules.

    15:1077 gives the member its payload -- *"a subsumed rule was dropped from the demand plan and
    its keys were never computed"*, with the knob column reading *"the subsuming rule's id"* -- and
    `Degradation` rule 1 requires the message to name it in prose, which `_subsumed_finding` already
    does. `knob` carries the same fact machine-readably, and `fix_command` is `ow route lint
    --explain`, which is the command 05:1811 says prints a rule's derived phase and read set.
    """
    return tuple(
        Degradation(
            kind="policy_pruned",
            message=f"rule {finding.rule_id!r} {finding.message}",
            knob=finding.against,
            fix_command=f"ow route lint --explain {finding.rule_id}",
        )
        for finding in findings
        if finding.code == SUBSUMPTION_CODE
    )


# --------------------------------------------------------------------------------------------
# 5. Checks 1, 2, 7 and 10 -- what a registry alone can decide.
# --------------------------------------------------------------------------------------------


def unresolved_keys(policy: RoutePolicy, registry: SignalRegistry) -> tuple[Finding, ...]:
    """Check 1, `OW-P-001`: every key in `[slice] by` and in a `when` clause resolves.

    **The third clause of 05:1774 is not implemented here, because it does not parse.** The plan
    says *"every key in `[slice] by`, in a `when` clause and in `[thresholds]` resolves against the
    `SignalSpec` registry"*, and `[thresholds]`' keys are `garble_escalate`, `ink_coverage_min`,
    `table_grid_min` -- none has a group prefix and none could resolve against a registry of
    `unit.format`-shaped keys under any reading. The check the clause most plausibly means is that
    every `@thresholds.<name>` a rule NAMES is declared, and `policy._substitute()` already refuses
    at compile time. D204.
    """
    known = set(registry.keys())
    findings = [
        _unresolved(key, f"[slice] by names {key!r}") for key in policy.slice_by if key not in known
    ]
    findings += [
        _unresolved(key, f"rule {rule.id!r} reads {key!r}", rule.id)
        for rule in policy.rules
        for key in rule.read_set
        if key not in known
    ]
    return tuple(findings)


def _unresolved(key: str, message: str, rule_id: str = "") -> Finding:
    return Finding(
        code="OW-P-001",
        check=1,
        rule_id=rule_id or key,
        message=f"{message}, which no SignalSpec registers. "
        "A policy that gates money must not name something that does not exist (05:1768)",
    )


def literals_outside_domain(
    policy: RoutePolicy, registry: SignalRegistry, *, format_domain: Iterable[str] | None = None
) -> tuple[Finding, ...]:
    """Check 2, `OW-P-002`: every literal compared against a `str` signal is in its domain.

    05:1775 makes `unit.format` the named exception and it is the one that matters: the comparison
    is against *"the computed domain (core's 48 union the enabled cards' contributed `format_tokens`
    tokens), never against the literal 48"*. So a `ComputedDomain` key is checked only when the
    caller supplies the union, and skipped otherwise -- the alternative, checking against core's
    forty-eight, would fail a third party's `warc` card for naming its own token.
    """
    findings: list[Finding] = []
    for rule in policy.rules:
        for clause in rule.when.clauses:
            for key, test in clause.tests:
                domain = _closed_domain(registry, key, format_domain)
                if domain is None:
                    continue
                for literal in _literals(test):
                    if isinstance(literal, str) and literal not in domain:
                        findings.append(_outside(rule.id, key, literal, domain))
    return tuple(findings)


def _closed_domain(
    registry: SignalRegistry, key: str, format_domain: Iterable[str] | None
) -> frozenset[str] | None:
    domain = registry.domain_of(key)
    if isinstance(domain, frozenset):
        return frozenset(str(member) for member in domain)
    if domain is ComputedDomain.FORMAT_TOKENS and format_domain is not None:
        return frozenset(format_domain)
    return None


def _literals(test: Test) -> tuple[Scalar, ...]:
    """Every literal one test compares against, in the author's order.

    `Test.value` is `Scalar | tuple[Scalar, ...]` because one field carries both an `eq` bound and
    an `in` list, and `Test.__post_init__` already refuses the wrong shape for each op -- so the
    `isinstance` here is a narrowing rather than a check. In the author's order and not a set's,
    because check 2's message names the literal that failed and a reader looks for it in the file.
    """
    if test.op == "exists":
        return ()
    return test.value if isinstance(test.value, tuple) else (test.value,)


def _outside(rule_id: str, key: str, literal: str, domain: frozenset[str]) -> Finding:
    return Finding(
        code="OW-P-002",
        check=2,
        rule_id=rule_id,
        message=f"compares {key} against {literal!r}, which is not one of the "
        f"{len(domain)} members of its domain. A literal outside the domain matches nothing "
        "and reads as a rule that is simply never taken",
    )


def rungs_read_too_early(policy: RoutePolicy, registry: SignalRegistry) -> tuple[Finding, ...]:
    """Check 7, `OW-P-010`: no rule reads a key requiring a rung strictly greater than its own.

    05:1144 calls this *"the only way this can go wrong"* about the derived phase: a rule at
    `DECODE` reading a key whose provider needs `PAGE`'s driver output can never be satisfied in
    any phase of `DECODE`, so the phase derivation has nothing to derive and the rule is a guard
    on a signal that will always be UNKNOWN.
    """
    findings: list[Finding] = []
    for rule in policy.rules:
        for key in rule.read_set:
            late = [rung for rung in registry.requires_of(key) if rung > rule.rung]
            if late:
                findings.append(
                    Finding(
                        code="OW-P-010",
                        check=7,
                        rule_id=rule.id,
                        message=f"is at {rule.rung.name} and reads {key!r}, which requires "
                        f"{', '.join(rung.name for rung in late)}. The key cannot have a value "
                        "when this rule is evaluated, in either phase",
                    )
                )
    return tuple(findings)


def format_token_union(policy: RoutePolicy) -> frozenset[str]:
    """Every `unit.format` literal named by a `GATE` or `DECODE` rule. Check 10's left-hand side.

    Both rungs and no others, because 05:1786 says so and the reason is the routing shape: a format
    token decides whether a unit is admitted and how it is decoded, and nothing above `DECODE`
    branches on it.
    """
    named: set[str] = set()
    for rule in policy.rules:
        if rule.rung not in {Rung.GATE, Rung.DECODE}:
            continue
        for clause in rule.when.clauses:
            for key, test in clause.tests:
                if key == "unit.format":
                    named.update(one for one in _literals(test) if isinstance(one, str))
    return frozenset(named)


def format_coverage(policy: RoutePolicy, domain: Iterable[str]) -> tuple[Finding, ...]:
    """Check 10, `OW-P-014`. **Both directions are the check**, and 05:1786 says which.

    *"A domain member no rule at any layer names fails, and the linter names the driver that
    contributed it; a rule literal outside the domain fails as check 2."* So the unnamed half is
    reported here and the unknown half is left to `literals_outside_domain`, which is where a
    reader looking at a rule would want it.

    05:1790 is what makes this the check worth having: *"`mp3`, `eml`, `zip`, `doc` and six more
    tokens exist in the detection vocabulary, and a policy that never names them routes them
    nowhere."*
    """
    members = frozenset(domain)
    missing = sorted(members - format_token_union(policy))
    if not missing:
        return ()
    return (
        Finding(
            code="OW-P-014",
            check=10,
            rule_id=policy.name or "policy",
            message=f"{len(missing)} format token(s) are in the computed domain and named by no "
            f"GATE or DECODE rule, so a unit detected as one routes nowhere: {', '.join(missing)}",
        ),
    )


def missing_on_unknown(policy: RoutePolicy, registry: SignalRegistry) -> tuple[Finding, ...]:
    """Check 4, `OW-P-004`, as a `Finding` -- `policy.rules_needing_on_unknown()` does the work.

    It lives there because nullability is a `SignalSpec` column and the predicate is the loader's
    other half; it is surfaced here because a caller running `ow route lint` wants fourteen answers
    from one call and not thirteen plus a separate import.
    """
    return tuple(
        Finding(
            code="OW-P-004",
            check=4,
            rule_id=rule_id,
            message="reads a nullable key and declares no `on_unknown`. RT7 requires one on any "
            "rule reading a nullable key; a `when` of `exists` tests alone is exempt (05:1004)",
        )
        for rule_id in rules_needing_on_unknown(policy, registry)
    )


# --------------------------------------------------------------------------------------------
# 6. The one entry point.
# --------------------------------------------------------------------------------------------


def lint(
    policy: RoutePolicy,
    *,
    registry: SignalRegistry | None = None,
    format_domain: Iterable[str] | None = None,
    installation: Installation | None = None,
) -> Report:
    """Run every check available, and report the ones that are not as data. Twelve of fourteen.

    `registry` is optional and its absence narrows the run rather than failing it: check 8 still
    decides every numeric pair and every categorical pair that does not need a universe, which is
    what makes the linter usable from a test that has a policy and no installed providers. Checks 1,
    2, 4 and 7 need the registry by definition and are skipped without one -- and `Report.not_run`
    says which, so the narrowing is visible in the output and not only in this docstring.

    `installation` is the same arrangement for `route/checks.py`'s six: with it, checks 3, 6, 9, 11,
    13 and 14 run against `[drivers] enabled`, the installed cards, a `PriceBook` and
    `[retrieval.budget]`; without it they stay in `not_run`. A field it carries empty narrows one
    check rather than all six (`checks.not_run()` says which), and a driver whose card is missing
    produces an `Undecided` rather than a verdict -- F30's discipline applied to an absent file
    instead of an open domain.

    **Checks 5 and 12 are never here and never will be.** `load_layer()` raises `OW-P-005` and
    `OW-P-013` at load, so a policy carrying either never compiles into a `RoutePolicy` this
    function could be handed. They stay in `not_run` with that sentence rather than being quietly
    dropped, because a reader counting checks should find fourteen accounted for.
    """
    findings: list[Finding] = []
    absent = dict(NOT_RUN)
    if registry is not None:
        findings += unresolved_keys(policy, registry)
        findings += literals_outside_domain(policy, registry, format_domain=format_domain)
        findings += missing_on_unknown(policy, registry)
        findings += rungs_read_too_early(policy, registry)
    else:
        for number, code in ((1, "OW-P-001"), (2, "OW-P-002"), (4, "OW-P-004"), (7, "OW-P-010")):
            absent[number] = f"{code} needs a SignalRegistry and none was supplied"
    if format_domain is None:
        absent[10] = (
            "OW-P-014 needs the computed format domain -- core's 48 union the enabled cards' "
            "format_tokens -- which route/detect.py owns and 05 section 2.2 has not shipped"
        )
    else:
        findings += format_coverage(policy, format_domain)
    subsumed, undecided, compared = subsumption(
        policy, registry=registry, format_domain=format_domain
    )
    findings += subsumed
    gaps = list(undecided)
    if installation is not None:
        from omniweave.route import checks  # noqa: PLC0415 -- checks imports Finding from here

        installed, deferred = checks.run_all(policy, installation)
        findings += installed
        gaps += deferred
        for number in checks.CODES:
            absent.pop(number, None)
        absent.update(checks.not_run(installation))
    return Report(
        findings=tuple(findings),
        undecided=tuple(gaps),
        compared=compared,
        not_run=absent,
    )
