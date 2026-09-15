"""The policy grammar and the six-layer loader -- *"the policy loader"* of 11-repo-layout.md:250.

05-ingest-and-routing.md section 4.1 (:927-963) gives the six layers and the merge; section 4.2
(:964-1080) gives the grammar, the action/modifier split and every `then` key's meaning; section 4.4
(:1214-1766) is the shipped policy this grammar must load without a special case. 16-roadmap.md:604
schedules the lot as W5.2.

**The whole design is one sentence: the policy is data, and the grammar is small enough to
mechanically check.** 05:975: *"No arithmetic, no indexing, no user functions, no dotted import
paths, no `eval`. A rule that needs a derived quantity gets a `Signal`, not a grammar feature -- and
this is checked to be sufficient: none of the eight escalation ladders catalogued in
`mine-parse.md` section B2 needs arithmetic over more than one evidence key."* The price of the
alternative is stated too: *"A hand-rolled predicate language with arithmetic forfeits both
interval-box subsumption linting and that fit, for 1,500 LoC and a strictly smaller checkable
surface."*

## Higher layers PREPEND, which is why there is no precedence arithmetic

05:936: *"First match wins, so prepending makes the higher layer win with no precedence arithmetic
at all."* `LAYERS` is in ascending authority and `compile_policy` reverses it, so a `project` rule
lands ahead of every `builtin` rule and simply wins. There is no rule-level priority field, no
override key and no merge of two rules into one -- three mechanisms the design does not need
because the list order already says everything.

Scalars are last-write-wins, with one asymmetry that is not a style choice: *"A `project` layer may
only LOWER a budget: a `micros_max` above the site layer's is `OW-P-020` at load, not a silent
clamp"* (05:959). Silently clamping would make a policy that reads as a raise behave as a no-op,
which is the worst of the three available behaviours.

## Three-valued throughout, and `{exists: bool}` is the only total test

A test over an UNKNOWN evidence value is UNKNOWN, not False, and the combinators are Kleene's:
`all_of` is False if any clause is False even when another is UNKNOWN, because the rule cannot match
whatever the unknown turns out to be; `any_of` is True if any clause is True for the mirror reason.
Collapsing UNKNOWN to False would make `on_unknown` unreachable -- the key the whole of section 4.3
turns on -- because a rule reading an uncomputed signal would simply not match and no branch would
ever be taken.

`{exists: bool}` *"is **total** -- it tests the presence of a value, so it is defined on UNKNOWN and
a rule whose `when` consists only of `exists` tests needs no `on_unknown`"* (05:1004). That is what
lets `degrade.budget-exhausted` read `budget.exhausted` without one, and `Rule.exists_only()` is the
predicate lint check 4 exempts on.

## `on_unknown` is required, and this module decides *when* rather than *whether*

RT7 (05:3347): *"`on_unknown` in {skip, match, defer} is **required** on any rule reading a nullable
key (`OW-P-004`); `{exists: bool}` is total and therefore exempt."* Nullability is a `SignalSpec`
column, so the requirement cannot be checked without the registry -- which is why
`rules_needing_on_unknown()` takes one and is a function rather than a `__post_init__`. W5.5's
`ow route lint` check 4 is a two-line caller of it.

The same argument makes `phase_of()` live here: 05:1136 says *"The two phases are derived, not
declared"*, derived from `SignalSpec.requires`, and 05:1143 notes *"There is no new grammar key"* --
so a rule has no phase until a registry is in hand, and a `Rule` that carried one would be claiming
a fact about a machine it has never seen.

## What is NOT here, and why each is somewhere else

The **interval-box subsumption linter** (check 8, `OW-P-011`) and the **isotonic threshold fitter**
are W5.2's other half. Both are analyses OVER a compiled policy and neither is needed to compile
one; the linter additionally needs the whole rule list at one `(rung, lane, phase)`, which is
`rules_at()`'s output rather than a loader concern. The **shipped forty-rule `builtin` layer**
(section 4.4) is data this module reads and does not contain, and it lands beside the linter that
proves check 10's coverage claim -- a policy and the proof that it names every format token are one
reviewable unit.

`evaluate()` is `eval.py`'s, and it is a separate module because semgrep holds that one to purity
and this one opens files.

## `expires` is applied at compile time with an INJECTED date, never a clock

05:2976 gives `expires` its only job: `ow route propose --auto-demote` writes a `[[rule]]` into a
generated `90-auto-demote.toml` *"carrying an `expires` field, so it is visible in a `git diff`,
expires on its own, and is reverted by deleting a file."* Dropping an expired rule needs today's
date, and G8 bans a clock in library code, so `compile_policy(..., today=...)` takes it as an
argument and defaults to keeping every rule. A policy that silently changed shape at midnight would
also change `policy_digest`, and `policy_digest` is in every `route_decision`'s identity.

Core, ports and this package's `decision`, `evidence` and `rung`. `tomllib` and no other IO.

Tier T-PUBLIC: 18-api-sketch.md:843.

Specified in 05-ingest-and-routing.md sections 4.1, 4.2 and 4.4; 11-repo-layout.md:250;
16-roadmap.md:604.
"""

from __future__ import annotations

import operator
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import RouteError
from omniweave_ports.types import CostClass

from omniweave.route.decision import OUTCOMES, Modifiers
from omniweave.route.rung import RUNG_BY_NAME, Rung

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave.route.evidence import Evidence, Scalar, SignalRegistry

__all__ = [
    "ACTION_KEYS",
    "BUILTIN_POLICY",
    "LAYERS",
    "MEMBER_OPS",
    "MODIFIER_KEYS",
    "ON_UNKNOWN",
    "OPS",
    "ORDERED_OPS",
    "PIN_REJECTIONS",
    "POLICIES",
    "PROFILE_FAST",
    "SURFACE",
    "THRESHOLD_PREFIX",
    "Clause",
    "Layer",
    "Pin",
    "RoutePolicy",
    "Rule",
    "Test",
    "Then",
    "When",
    "builtin_layer",
    "compile_policy",
    "load_layer",
    "phase_of",
    "rules_needing_on_unknown",
]

# --------------------------------------------------------------------------------------------
# 1. The vocabulary. Every closed set the grammar has, as data.
# --------------------------------------------------------------------------------------------

SURFACE: Final[str] = "route"
"""05:951: *"Every file declares `surface = "route"`; a file without it, or with an unknown surface,
fails to load -- which is what lets the routing, retrieval and graph policies share one directory
without any of them silently governing the others."* The three surfaces share one grammar and one
directory, so the declaration is the only thing keeping a retrieval policy from routing."""

LAYERS: Final[tuple[str, ...]] = ("builtin", "site", "project", "profile", "request", "pin")
"""05:940's six, in ASCENDING authority. `compile_policy` reverses them, because higher PREPENDS.

*"Six layers, and there is deliberately no seventh"* (05:947): a `driver` layer was considered and
refused -- below `builtin` it cannot pre-empt a builtin `DECODE` rule and so does not solve the case
that motivates it; above `builtin` it would let an installed wheel redirect spend. A third party's
route lands through publish step 8's `project`-layer fragment.
"""

OPS: Final[tuple[str, ...]] = ("eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "exists")
"""Nine, and no tenth. 05:970-973's `test` production, closed."""

ORDERED_OPS: Final[frozenset[str]] = frozenset({"lt", "lte", "gt", "gte"})
"""The four whose bound must be a number. `eq`/`ne` compare any scalar; `in`/`not_in` a list."""

MEMBER_OPS: Final[frozenset[str]] = frozenset({"in", "not_in"})

ON_UNKNOWN: Final[tuple[str, ...]] = ("skip", "match", "defer")
"""05:1126-1130's three, and the table's own summary of why there are three rather than a default:
`skip` when *"the rule is an optimisation ... and not firing is safe"*, `match` when *"the `then` is
conservative"*, `defer` when *"the key is computable but expensive, and deciding without it would
either overspend or silently pass a page."*"""

THRESHOLD_PREFIX: Final[str] = "@thresholds."
"""05:977: *"a **compile-time substitution** from `[thresholds]`, not an expression, which is
precisely what makes a threshold learnable by one-dimensional isotonic regression over the decision
log."* The reference survives on the compiled `Test` as `Test.threshold`, because `ow route lint`
check 1 has to resolve it and `ow route propose` has to find every site that reads a given
threshold -- substituting it away entirely would make both a text search."""

ACTION_KEYS: Final[tuple[str, ...]] = (
    "driver",
    "driver_by",
    "escalate_to",
    "sequence",
    "terminal",
    "outcome",
    "failure_class",
    "cause_from",
)
"""05:1023's action row. **First match wins**: exactly one action per `(rung, lane, phase)`, and
later matching action rules are not tested.

`outcome` is in this row and `outcome = "not_eligible"` is in the modifier row -- the one key that
is both, depending on its value. That is not an inconsistency in the plan; it is section 4.2's
sentence *"`not_eligible` is a modifier: it excludes **blocks** from the rung without touching the
part"*, and `Then.__post_init__` is where the value decides which row the rule lands in.
"""

MODIFIER_KEYS: Final[tuple[str, ...]] = (
    "max_cost_class",
    "lane",
    "deny_lanes",
    "render",
    "skip_rungs",
    "flag_blocks",
)
"""05:1024's modifier row, minus `outcome = "not_eligible"`, which `ACTION_KEYS` explains.

*"Every matching rule contributes, by a per-key monoid."* The monoids are `Modifiers.merge()`'s and
are written down exactly once, there.
"""

PIN_REJECTIONS: Final[frozenset[str]] = frozenset(
    {"driver_not_enabled", "licence_tier", "probe_unavailable", "expired", "rung_below_parent"}
)
"""05:961: *"`[[pin]]` blocks are honoured or refused, never ignored -- `PinRejected{driver,
reason}` is a typed return, and the reasons are exactly"* these five. A closed set, because "never
ignored" is only checkable if the refusal has a name."""

_FIX = "uv run ow route lint --strict"
_RENDER_PROFILES: Final[frozenset[str]] = frozenset({"structure", "glyph"})
_WHEN_OPS: Final[tuple[str, ...]] = ("any_of", "all_of", "none_of")


# --------------------------------------------------------------------------------------------
# 2. `Test` -- one comparison, three-valued.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Test:
    """One `<evidence_key>: test` comparison. 05:970-973's `test` production, compiled.

    `value` is the bound after `@thresholds` substitution and `threshold` is the reference it came
    from, kept so that check 1 can resolve it and `ow route propose` can find every rule that reads
    one threshold. `exists` carries its boolean in `value`.

    **A test has two states and the type carries both**, because substitution is a COMPILE step and
    `load_layer` runs before it: between the two, `value` is still the literal
    `"@thresholds.garble_escalate"` and the bound of an ordered op is therefore a string. The type
    checks below apply only to a RESOLVED test, and `holds()` refuses to run on an unresolved one --
    comparing a float against `"@thresholds.garble_escalate"` would be a silent False on every part
    in the corpus, which is the worst available failure for a policy that gates money.
    """

    op: str
    value: Scalar | tuple[Scalar, ...] = None
    threshold: str = ""

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise RouteError(f"{self.op!r} is not one of {', '.join(OPS)}", fix=_FIX)
        if self.op in MEMBER_OPS and not isinstance(self.value, tuple):
            raise RouteError(f"`{self.op}` takes a list, not {self.value!r}", fix=_FIX)
        if not self.resolved:
            return
        if self.op == "exists" and not isinstance(self.value, bool):
            raise RouteError(f"`exists` takes a boolean, not {self.value!r}", fix=_FIX)
        if self.op in ORDERED_OPS and not isinstance(self.value, int | float):
            raise RouteError(f"`{self.op}` takes a number, not {self.value!r}", fix=_FIX)

    @property
    def resolved(self) -> bool:
        """False between `load_layer` and `compile_policy`, while `value` is still the reference.

        `threshold` alone does not say which state the test is in -- it survives substitution on
        purpose -- so the state is read off the VALUE, which is the thing that changes.
        """
        return not (isinstance(self.value, str) and self.value.startswith(THRESHOLD_PREFIX))

    @property
    def total(self) -> bool:
        """True iff this test is defined on UNKNOWN. Only `exists` is. 05:1004."""
        return self.op == "exists"

    def holds(self, value: Scalar) -> bool | None:
        """Three-valued. `None` is UNKNOWN and is what `on_unknown` exists to decide.

        **A dtype mismatch reads as UNKNOWN rather than raising**, and that is a deliberate
        choice about where a provider's bug surfaces. A provider that answered `decode.char_count`
        with a string is a defect `ow route lint` check 2 and `ow drivers check` are the reporters
        for; a router that raised on it would take the whole corpus down at the first bad part,
        and a router that returned False would route that part as though the signal had been
        computed and found clean. UNKNOWN routes it through `on_unknown`, which is the branch the
        policy author already had to write.
        """
        if not self.resolved:
            raise RouteError(
                f"{self.value!r} was never substituted; this policy was loaded and not compiled."
                " Evaluating it would compare every part against a string and match none",
                fix=_FIX,
            )
        if self.op == "exists":
            return (value is not None) == self.value
        if value is None:
            return None
        if self.op in ORDERED_OPS:
            return _ordered(self.op, value, self.value)
        return _EXACT[self.op](value, self.value)

    def render(self, key: str, value: Scalar) -> str:
        """`'garble.score=0.71>=0.50'` -- 05:1974's exact shape, for `cause_from = "when"`.

        A GENERATED string, *"so 'why it escalated' is a `GROUP BY` and not a log grep"*. The
        threshold's VALUE and not its name, because the name is stable while the number is what
        `ow route propose` moved, and a scoreboard grouping by cause must separate the two.
        """
        return f"{key}={_scalar(value)}{_SYMBOL[self.op]}{_scalar(self.value)}"


_EXACT: Final[Mapping[str, Callable[[Any, Any], bool]]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "in": lambda value, bound: value in bound,
    "not_in": lambda value, bound: value not in bound,
}
"""The five non-ordered ops as functions, so `holds()` is one dispatch rather than five branches.
A table and not an `if` chain because the set is closed by `OPS` and a missing entry is then a
`KeyError` naming the op, which is a better failure than a silent fall-through to the last branch.
"""

_SYMBOL: Final[Mapping[str, str]] = {
    "eq": "==",
    "ne": "!=",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
    "in": " in ",
    "not_in": " not in ",
    "exists": " exists ",
}


def _ordered(op: str, value: Scalar, bound: object) -> bool | None:
    """`lt`/`lte`/`gt`/`gte` over a number, or UNKNOWN when the value is not one."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    number = float(bound)  # type: ignore[arg-type] -- __post_init__ proved it numeric
    if op == "lt":
        return value < number
    if op == "lte":
        return value <= number
    if op == "gt":
        return value > number
    return value >= number


def _scalar(value: object) -> str:
    """Render a bound for `cause`. A tuple renders as its members, so `in` reads as a set."""
    if isinstance(value, tuple):
        return "[" + ",".join(_scalar(item) for item in value) + "]"
    return str(value)


# --------------------------------------------------------------------------------------------
# 3. `Clause` and `When` -- Kleene's combinators, one level deep.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Clause:
    """`{ <evidence_key>: test, ... }` -- **implicit AND across keys** (05:969).

    A tuple of pairs and not a mapping, because the clause is part of `policy_digest` and a mapping
    would make the digest depend on insertion order in a way `sha256_canonical` would then hide by
    sorting. Pairs in the author's order, digested in the author's order, rendered for `cause` in
    the author's order.
    """

    tests: tuple[tuple[str, Test], ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.tests)

    @property
    def total(self) -> bool:
        """True iff every test is defined on UNKNOWN -- i.e. every one is `exists`."""
        return all(test.total for _, test in self.tests)

    def holds(self, ev: Evidence) -> bool | None:
        """Three-valued AND. **False beats UNKNOWN**, and that is Kleene's rule, not a shortcut.

        A clause with one False test cannot match whatever the unknown turns out to be, so
        returning UNKNOWN would send a rule into `on_unknown` on the strength of a key that was
        already irrelevant -- and `on_unknown = "match"` would then fire a rule the author wrote a
        second condition specifically to prevent.
        """
        unknown = False
        for key, test in self.tests:
            verdict = test.holds(ev.read(key))
            if verdict is False:
                return False
            if verdict is None:
                unknown = True
        return None if unknown else True

    def cause(self, ev: Evidence) -> str:
        """The rendered clause, for `cause_from = "when"`. Every test, joined by `&`."""
        return "&".join(test.render(key, ev.read(key)) for key, test in self.tests)


@dataclass(frozen=True, slots=True)
class When:
    """A bare clause, or ONE level of `any_of` / `all_of` / `none_of`. 05:968.

    One level and no nesting, and the flatness is what the subsumption linter is built on: a
    condition box over interval-bounded keys is decidable precisely because the grammar is
    comparison-only and the combinators do not nest (05:1170).
    """

    op: str
    clauses: tuple[Clause, ...]

    def __post_init__(self) -> None:
        if self.op and self.op not in _WHEN_OPS:
            raise RouteError(f"{self.op!r} is not one of {', '.join(_WHEN_OPS)}", fix=_FIX)
        if not self.clauses:
            raise RouteError(
                "a `when` with no clause matches everything and says nothing", fix=_FIX
            )
        if not self.op and len(self.clauses) != 1:
            raise RouteError("a bare `when` holds exactly one clause", fix=_FIX)

    @property
    def keys(self) -> tuple[str, ...]:
        """Every evidence key this `when` reads, in order, deduplicated at first occurrence.

        This IS the rule's read set for the demand plan and for check 7, so the order is the one a
        reader sees in the file: a set would make `ow route lint --explain`'s output depend on hash
        ordering.
        """
        seen: list[str] = []
        for clause in self.clauses:
            for key in clause.keys:
                if key not in seen:
                    seen.append(key)
        return tuple(seen)

    @property
    def total(self) -> bool:
        return all(clause.total for clause in self.clauses)

    def holds(self, ev: Evidence) -> bool | None:
        """Kleene over the clauses. `none_of` is the negation of `any_of`, UNKNOWN included."""
        verdicts = [clause.holds(ev) for clause in self.clauses]
        if self.op == "any_of":
            return _kleene_or(verdicts)
        if self.op == "none_of":
            hit = _kleene_or(verdicts)
            return None if hit is None else not hit
        return _kleene_and(verdicts)

    def cause(self, ev: Evidence) -> str:
        """The clause that FIRED, for `cause_from = "when"`. 05:1974's `'garble.score=0.71>=0.50'`.

        For `any_of` that is the first clause that held -- one clause, not four, because the whole
        point of the column is that `ow route scoreboard` can `GROUP BY` it. For `all_of` and a
        bare clause every clause held, so every clause is rendered. For `none_of` the rule fired
        because nothing held, and there is no clause to name: it renders the negation.
        """
        if self.op == "none_of":
            return "none_of(" + " | ".join(clause.cause(ev) for clause in self.clauses) + ")"
        if self.op == "any_of":
            for clause in self.clauses:
                if clause.holds(ev) is True:
                    return clause.cause(ev)
            return ""
        return " & ".join(clause.cause(ev) for clause in self.clauses)


def _kleene_or(verdicts: Sequence[bool | None]) -> bool | None:
    if any(v is True for v in verdicts):
        return True
    return None if any(v is None for v in verdicts) else False


def _kleene_and(verdicts: Sequence[bool | None]) -> bool | None:
    if any(v is False for v in verdicts):
        return False
    return None if any(v is None for v in verdicts) else True


# --------------------------------------------------------------------------------------------
# 4. `Then` -- the action/modifier split, decided by the keys present.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Then:
    """What a matching rule does. 05:1035-1057's key table, one field per key.

    Two kinds in one record rather than two records, because 05:1028 makes a rule carrying BOTH
    legal -- `decode.no-text-layer` sets `escalate_to` (action) and `render` (modifier) in one
    `then` -- and a type that split them would have to model a rule as a pair.
    """

    # -- action keys --
    driver: str = ""
    driver_by: Literal["cheapest_admissible"] | None = None
    escalate_to: Rung | None = None
    sequence_max_parts: int | None = None
    terminal: bool = False
    outcome: str | None = None
    failure_class: str | None = None
    cause_from: Literal["when"] | None = None
    # -- modifier keys --
    max_cost_class: CostClass | None = None
    admit_lane: str = ""
    deny_lanes: frozenset[str] = frozenset()
    render: Literal["structure", "glyph"] | None = None
    skip_rungs: frozenset[Rung] = frozenset()
    flag_blocks: bool = False
    not_eligible: bool = False
    # -- legal on both (05:1027) --
    reason: str | None = None

    @property
    def is_action(self) -> bool:
        """True iff any action key is set. `outcome = "not_eligible"` is NOT one -- it parses into
        `not_eligible` and leaves `outcome` unset, which is 05:1054's sentence made structural."""
        return bool(
            self.driver
            or self.driver_by
            or self.escalate_to is not None
            or self.sequence_max_parts is not None
            or self.terminal
            or self.outcome is not None
            or self.failure_class is not None
            or self.cause_from is not None
        )

    @property
    def is_modifier(self) -> bool:
        return bool(
            self.max_cost_class is not None
            or self.admit_lane
            or self.deny_lanes
            or self.render is not None
            or self.skip_rungs
            or self.flag_blocks
            or self.not_eligible
        )

    def modifiers(self, blocks: Iterable[int] = ()) -> Modifiers:
        """This `then`'s contribution to the merged `Modifiers`. One rule's share and no more.

        `blocks` is the block id set a `not_eligible` rule excludes, supplied by the caller because
        a pure `evaluate()` has no block list -- `Evidence` is scalar-valued and the ids come from
        the part's decode. An empty set from a rule that fired is still recorded, through
        `Modifiers.rule_ids`, so "fired and excluded nothing" and "did not fire" stay distinct.
        """
        return Modifiers(
            max_cost_class=self.max_cost_class
            if self.max_cost_class is not None
            else CostClass.BILLED_API,
            admit_lanes=frozenset({self.admit_lane}) if self.admit_lane else frozenset(),
            deny_lanes=self.deny_lanes,
            render=self.render,
            skip_rungs=self.skip_rungs,
            flag_blocks=self.flag_blocks,
            not_eligible=frozenset(blocks) if self.not_eligible else frozenset(),
        )


# --------------------------------------------------------------------------------------------
# 5. `Rule` and `Pin`.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    """One `[[rule]]` block. 05:967-972's `rule` production plus the origin a reader needs.

    `origin` is 05:1949's `'project:.omniweave/policy.d/10-route.toml:41'` -- a column on
    `route_decision` *"because `ow route explain` and 15 section 6.2's escalation report both print
    it"*, so it is carried from the file rather than reconstructed.
    """

    id: str
    rung: Rung
    when: When
    then: Then
    lane: str = "text"
    """**`rule.lane` and `then.lane` are different keys doing different jobs** (05:1032), and this
    is the one a reader conflates. `rule.lane` says which lane's rule LIST this rule belongs to;
    `then.lane` (here `Then.admit_lane`) ADMITS a lane for this part."""

    comment: str = ""
    on_unknown: str = ""
    expect_unavailable: bool = False
    expires: str = ""
    canary: Scalar = None
    """**Declared by the grammar and defined nowhere.** 05:968 lists `canary?` in the `rule`
    production and the charter's identical line at `charter.md:2544` does the same; no other line in
    any plan document says what it holds, what reads it or what it does. (The `canary` of 11, 13 and
    15 is G29's redaction canary -- a different thing entirely, which is part of why the gap is easy
    to miss.) It is accepted, carried into `policy_digest` and read by nothing. D203."""

    origin: str = ""
    layer: str = ""

    @property
    def read_set(self) -> tuple[str, ...]:
        """Every evidence key the `when` reads. What the demand plan unions and check 7 tests."""
        return self.when.keys

    @property
    def is_action(self) -> bool:
        return self.then.is_action

    @property
    def is_modifier(self) -> bool:
        return self.then.is_modifier

    @property
    def exists_only(self) -> bool:
        """05:1004's exemption: a `when` of `exists` tests alone needs no `on_unknown`."""
        return self.when.total


@dataclass(frozen=True, slots=True)
class Pin:
    """`[[pin]]` -- *"one `(unit, part?, lane) -> driver` plus `reason` and `expires`"* (05:944).

    `reason` and `expires` are MANDATORY (05:2817 repeats it), and that is the whole difference
    between a pin and a permanent override: a pin that never expires is an override nobody reviews.
    """

    unit: str
    driver: str
    reason: str
    expires: str
    part: str = ""
    lane: str = "text"


# --------------------------------------------------------------------------------------------
# 6. The compiled policy.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Layer:
    """One loaded TOML file, before the merge. Not frozen into a policy until `compile_policy`."""

    layer: str
    origin: str
    rules: tuple[Rule, ...] = ()
    pins: tuple[Pin, ...] = ()
    scalars: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    """*"The merged, compiled, frozen, content-addressed form of six TOML layers"* (05:929).

    05:930: *"There is no routing code branching on a format name anywhere in the framework;
    `ow route lint` and a semgrep rule banning a format literal under `omniweave/route/` are the
    enforcers."* This type is what that rule is possible against: every format the router knows is
    a literal in a `[[rule]]` block, and this record holds them.
    """

    rules: tuple[Rule, ...]
    policy_digest: str
    thresholds: Mapping[str, float] = field(default_factory=dict)
    budgets: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    audit: Mapping[str, object] = field(default_factory=dict)
    slice_by: tuple[str, ...] = ()
    max_slices: int = 0
    render: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    calibration: Mapping[str, object] = field(default_factory=dict)
    pins: tuple[Pin, ...] = ()
    name: str = ""
    version: int = 0

    phases: Mapping[str, str] = field(default_factory=dict)
    """Rule id -> `"select"` | `"settle"`, filled by `compile_policy(..., registry=...)`.

    **It is NOT in `policy_digest`, and the exclusion is the point.** 05:929 defines the digest over
    *"six TOML layers"*; a phase is derived from `SignalSpec.requires`, which is a property of the
    installed providers. Folding it in would make two machines running the same policy files compute
    two `policy_digest`s and therefore two `decision_id`s for one decision -- which is exactly what
    section 4.3 property 6's idempotent insert exists to prevent.

    Section 4.3's own diagram puts the derivation here: the compiler builds a *"DemandPlan per
    `(rung, lane, phase)`"* and resolves `driver.unavailable` once, both before any evaluation.
    """

    def phase_of_rule(self, rule: Rule) -> str:
        """This rule's derived phase, defaulting to `"select"`.

        The default is correct rather than lenient: `SignalSpec.requires` defaults to `()`, so a
        policy compiled against no registry is a policy over signals that read no driver output --
        and every such rule IS a select-phase rule. A policy compiled against a real registry has
        every id in `phases` and the default is never taken.
        """
        return self.phases.get(rule.id, "select")

    def rules_at(self, rung: Rung, lane: str) -> tuple[Rule, ...]:
        """Every rule declared at one `(rung, lane)`, in merged order -- higher layers first.

        Phase is NOT a parameter: `phase_of_rule()` is the filter and `evaluate()` applies it, so
        this method stays a pure function of the policy and callers that do not care about phase
        (the subsumption linter, `ow route explain`) do not have to supply a registry.
        """
        return tuple(rule for rule in self.rules if rule.rung == rung and rule.lane == lane)

    def threshold_keys(self) -> tuple[str, ...]:
        """Every `@thresholds.<name>` any rule referenced, sorted. `ow route lint` check 1's input,
        and `ow route propose`'s: it fits one threshold per pass and needs the sites."""
        refs = {
            test.threshold
            for rule in self.rules
            for clause in rule.when.clauses
            for _, test in clause.tests
            if test.threshold
        }
        return tuple(sorted(refs))

    def read_set(self) -> tuple[str, ...]:
        """Every evidence key any rule reads, sorted. Check 1 resolves each against the registry."""
        return tuple(sorted({key for rule in self.rules for key in rule.read_set}))


# --------------------------------------------------------------------------------------------
# 7. Where the shipped layers are, and the loader.
# --------------------------------------------------------------------------------------------

POLICIES: Final[Path] = Path(__file__).with_name("policies")
"""`omniweave/route/policies/` -- the shipped `[[rule]]` files, as package data.

`Path(__file__).with_name(...)` and not `importlib.resources`, for `evidence.BUILTIN_SIGNALS`'
reason: the files are siblings of the module that documents them, and nothing in this framework is
zip-safe because `omniweave_core.discovery` locates every card as a filesystem path.
"""

BUILTIN_POLICY: Final[Path] = POLICIES / "00-builtin-route.toml"
"""Section 4.4's forty rules, at the path 05:1267 prints in the fence's own first line.

**The file is a transcription of the plan's fence and a test holds it to that**, which is the only
form of "the shipped policy is section 4.4" a reader can check. It is data and not a Python literal
for 05:928's reason -- *"the policy is data"* -- and it is committed rather than generated because
`_plan/` is not in version control and a builtin layer that could only be rebuilt from a design tree
would be unbuildable from a clone.
"""

PROFILE_FAST: Final[Path] = POLICIES / "50-profile-fast.toml"
"""05:1750's `--profile fast` overlay. *"A `--profile fast` overlay changes no rule"* -- it is four
thresholds and a `[budget.per_part]`, which is what makes `profile` a layer and not a code path."""


def builtin_layer() -> Layer:
    """The shipped `builtin` layer, read from disk on every call and deliberately not cached.

    `evidence.builtin_specs()`' argument applies unchanged: a policy is compiled once per run
    (05:1084), so this is read once per run, and a module-level cache would serve a long-lived
    `ow route lint` the file it had at process start -- which is exactly the loop an author editing
    a policy is in.
    """
    return load_layer(
        BUILTIN_POLICY.read_bytes(),
        layer="builtin",
        origin=f"builtin:{BUILTIN_POLICY.name}",
    )


def load_layer(raw: bytes, *, layer: str, origin: str) -> Layer:
    """Parse one policy file. `tomllib` and nothing else -- no import, no code, no `eval`.

    Refuses a file whose `surface` is absent or not `"route"` (05:951), because the three surfaces
    share a directory and a grammar and the declaration is the only thing keeping a retrieval
    policy from routing.
    """
    if layer not in LAYERS:
        raise RouteError(f"{layer!r} is not one of {', '.join(LAYERS)}", fix=_FIX)
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RouteError(f"{origin} is not readable TOML: {exc}", fix=_FIX) from exc
    surface = doc.get("surface")
    if surface != SURFACE:
        raise RouteError(
            f'{origin} declares surface={surface!r}; a route policy declares "{SURFACE}"', fix=_FIX
        )
    rules = tuple(
        _rule(body, index=index, layer=layer, origin=origin)
        for index, body in enumerate(_blocks(doc.get("rule", []), "rule", origin))
    )
    pins = tuple(_pin(body, origin) for body in _blocks(doc.get("pin", []), "pin", origin))
    scalars = {key: value for key, value in doc.items() if key not in {"rule", "pin"}}
    return Layer(layer=layer, origin=origin, rules=rules, pins=pins, scalars=scalars)


def _blocks(raw: object, name: str, origin: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise RouteError(f"{origin}: [[{name}]] is not an array of tables", fix=_FIX)
    return tuple(raw)  # type: ignore[arg-type]


def _rule(body: Mapping[str, object], *, index: int, layer: str, origin: str) -> Rule:
    """One `[[rule]]`. `index` is the block's position, which is what `origin` renders."""
    rule_id = body.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        raise RouteError(f"{origin}: [[rule]] #{index} has no `id`", fix=_FIX)
    where = f"{origin}: rule {rule_id!r}"
    then = _then(body.get("then"), where)
    if not (then.is_action or then.is_modifier):
        raise RouteError(
            f"OW-P-013: {where}'s `then` contains neither an action key nor a modifier key."
            " A rule that only carries `reason` matches, pre-empts every later rule and does"
            " nothing -- which is exactly what `gate.untrusted-raises-audit` was",
            symbol="OW_POLICY_RULE_DOES_NOTHING",
            fix=_FIX,
        )
    rung = _rung(body.get("rung"), where)
    _check_forward(then, rung, where)
    return Rule(
        id=rule_id,
        rung=rung,
        when=_when(body.get("when"), where),
        then=then,
        lane=_text(body, "lane", where, default="text"),
        comment=_text(body, "comment", where, default=""),
        on_unknown=_on_unknown(body.get("on_unknown"), where),
        expect_unavailable=_flag(body, "expect_unavailable", where),
        expires=_text(body, "expires", where, default=""),
        canary=body.get("canary"),  # type: ignore[arg-type] -- D203: no declared type to check
        origin=f"{layer}:{origin}:{index}",
        layer=layer,
    )


def _check_forward(then: Then, rung: Rung, where: str) -> None:
    """RT8, at LOAD. 05:3348: *"the compiler rejects a backward `escalate_to` and a `skip_rungs`
    member at or below the rule's own rung **at load** (`OW-P-005`), which is CI parity for the
    charter's `route_decision_monotone` trigger rather than a second opinion."*"""
    if then.escalate_to is not None and then.escalate_to <= rung:
        raise RouteError(
            f"OW-P-005: {where} escalates from {rung.name} to {then.escalate_to.name},"
            " which is not strictly greater. Note that DEGRADE is FORWARD (5) and cheaper",
            symbol="OW_POLICY_RUNG_NOT_FORWARD",
            fix=_FIX,
        )
    backward = sorted(member.name for member in then.skip_rungs if member <= rung)
    if backward:
        raise RouteError(
            f"OW-P-005: {where} skips {', '.join(backward)}, at or below its own {rung.name}",
            symbol="OW_POLICY_RUNG_NOT_FORWARD",
            fix=_FIX,
        )


def _rung(raw: object, where: str) -> Rung:
    """`OW-P-023`: SCREAMING_SNAKE and nothing else.

    05:1216 makes the spelling a decision rather than an accident: `.omniweave/policy.d/*.toml` is
    *"an author-facing config artefact and not a wire"*, so the author reads the literal against
    section 4.2's ladder -- while every GENERATED artefact emits the lower-case member name the
    terminology lock requires. *"There is one authored form rather than two."*
    """
    if not isinstance(raw, str) or not raw:
        raise RouteError(f"{where} has no `rung`", fix=_FIX)
    if raw in RUNG_BY_NAME:
        return RUNG_BY_NAME[raw]
    if raw.upper() in RUNG_BY_NAME:
        raise RouteError(
            f"OW-P-023: {where} spells its rung {raw!r}; a policy file writes {raw.upper()!r}."
            " The lower-case member name is the GENERATED form, not the authored one",
            symbol="OW_POLICY_RUNG_SPELLING",
            fix=_FIX,
        )
    listed = ", ".join(RUNG_BY_NAME)
    raise RouteError(f"{where}: {raw!r} is not a rung; the seven are {listed}", fix=_FIX)


def _when(raw: object, where: str) -> When:
    """A bare clause, or exactly one of `any_of` / `all_of` / `none_of`. One level (05:968)."""
    if not isinstance(raw, dict) or not raw:
        raise RouteError(f"{where} has no `when`", fix=_FIX)
    present = [op for op in _WHEN_OPS if op in raw]
    if not present:
        return When(op="", clauses=(_clause(raw, where),))
    if len(present) > 1 or len(raw) > 1:
        raise RouteError(
            f"{where}'s `when` mixes {', '.join(sorted(raw))}; the grammar is ONE level and one"
            " combinator per rule",
            fix=_FIX,
        )
    op = present[0]
    members = raw[op]
    if not isinstance(members, list) or not members:
        raise RouteError(f"{where}'s `{op}` is not a non-empty list of clauses", fix=_FIX)
    return When(op=op, clauses=tuple(_clause(member, where) for member in members))


def _clause(raw: object, where: str) -> Clause:
    if not isinstance(raw, dict) or not raw:
        raise RouteError(f"{where} has an empty clause, which matches everything", fix=_FIX)
    if any(key in _WHEN_OPS for key in raw):
        raise RouteError(
            f"{where} nests a combinator inside a clause; the grammar is ONE level", fix=_FIX
        )
    return Clause(tests=tuple((key, _test(value, f"{where}[{key}]")) for key, value in raw.items()))


def _test(raw: object, where: str) -> Test:
    """A scalar is the equality shorthand; a one-key table is the explicit form."""
    if isinstance(raw, bool | int | float | str):
        return Test(op="eq", value=raw)
    if not isinstance(raw, dict) or len(raw) != 1:
        raise RouteError(f"{where} is {raw!r}; a test is a scalar or a ONE-key table", fix=_FIX)
    [(op, bound)] = raw.items()
    if op in MEMBER_OPS:
        if not isinstance(bound, list) or not bound:
            raise RouteError(f"{where}: `{op}` takes a non-empty list", fix=_FIX)
        return Test(op=op, value=tuple(bound))
    if isinstance(bound, str) and bound.startswith(THRESHOLD_PREFIX):
        return Test(op=op, value=bound, threshold=bound[len(THRESHOLD_PREFIX) :])
    return Test(op=op, value=bound)  # type: ignore[arg-type] -- Test.__post_init__ types it


def _then(raw: object, where: str) -> Then:
    if not isinstance(raw, dict):
        raise RouteError(f"{where} has no `then` table", fix=_FIX)
    unknown = sorted(set(raw) - set(ACTION_KEYS) - set(MODIFIER_KEYS) - {"reason"})
    if unknown:
        raise RouteError(
            f"{where}'s `then` names {', '.join(unknown)}."
            " The grammar is closed; a rule that needs a derived quantity gets a Signal (05:975)",
            fix=_FIX,
        )
    outcome = raw.get("outcome")
    legal = OUTCOMES | {"not_eligible"}
    if outcome is not None and (not isinstance(outcome, str) or outcome not in legal):
        raise RouteError(
            f"{where}: outcome {outcome!r} is not one of {', '.join(sorted(legal))}", fix=_FIX
        )
    return Then(
        driver=_text(raw, "driver", where, default=""),
        driver_by=_literal(raw.get("driver_by"), {"cheapest_admissible"}, "driver_by", where),
        escalate_to=_rung(raw["escalate_to"], where) if "escalate_to" in raw else None,
        sequence_max_parts=_sequence(raw.get("sequence"), where),
        terminal=_flag(raw, "terminal", where),
        outcome=None if outcome == "not_eligible" else outcome,
        failure_class=_text(raw, "failure_class", where, default="") or None,
        cause_from=_literal(raw.get("cause_from"), {"when"}, "cause_from", where),
        max_cost_class=_cost_class(raw.get("max_cost_class"), where),
        admit_lane=_text(raw, "lane", where, default=""),
        deny_lanes=frozenset(_str_list(raw.get("deny_lanes", []), "deny_lanes", where)),
        render=_literal(raw.get("render"), _RENDER_PROFILES, "render", where),
        skip_rungs=frozenset(
            _rung(name, where) for name in _str_list(raw.get("skip_rungs", []), "skip_rungs", where)
        ),
        flag_blocks=_flag(raw, "flag_blocks", where),
        not_eligible=outcome == "not_eligible",
        reason=_text(raw, "reason", where, default="") or None,
    )


def _sequence(raw: object, where: str) -> int | None:
    """`sequence = { max_parts = N }` -- 05:1049's only shape."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"max_parts"}:
        raise RouteError(f"{where}: `sequence` is `{{ max_parts = N }}` and nothing else", fix=_FIX)
    value = raw["max_parts"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RouteError(
            f"{where}: sequence.max_parts is {value!r}, not a positive integer", fix=_FIX
        )
    return value


def _pin(body: Mapping[str, object], origin: str) -> Pin:
    where = f"{origin}: [[pin]]"
    return Pin(
        unit=_text(body, "unit", where),
        driver=_text(body, "driver", where),
        reason=_text(body, "reason", where),
        expires=_text(body, "expires", where),
        part=_text(body, "part", where, default=""),
        lane=_text(body, "lane", where, default="text"),
    )


def _cost_class(raw: object, where: str) -> CostClass | None:
    if raw is None:
        return None
    try:
        return CostClass(raw)
    except ValueError as exc:
        listed = ", ".join(member.value for member in CostClass)
        raise RouteError(
            f"{where}: max_cost_class {raw!r} is not one of {listed}", fix=_FIX
        ) from exc


def _on_unknown(raw: object, where: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str) or raw not in ON_UNKNOWN:
        listed = ", ".join(ON_UNKNOWN)
        raise RouteError(f"{where}: on_unknown {raw!r} is not one of {listed}", fix=_FIX)
    return raw


def _literal(raw: object, allowed: Iterable[str], name: str, where: str) -> Any:
    """Validate a string against a closed set. Returns `Any` because every caller assigns it to a
    `Literal[...]` field and the membership check IS the narrowing -- a `cast` at three call sites
    would say the same thing with more ceremony and one more place to get the literal wrong."""
    if raw is None:
        return None
    if not isinstance(raw, str) or raw not in set(allowed):
        listed = ", ".join(sorted(allowed))
        raise RouteError(f"{where}: {name} {raw!r} is not one of {listed}", fix=_FIX)
    return raw


def _text(body: Mapping[str, object], name: str, where: str, *, default: str | None = None) -> str:
    value = body.get(name, default)
    if value is None or not isinstance(value, str) or (not value and default is None):
        raise RouteError(f"{where} needs a non-empty string `{name}`", fix=_FIX)
    return value


def _flag(body: Mapping[str, object], name: str, where: str) -> bool:
    value = body.get(name, False)
    if not isinstance(value, bool):
        raise RouteError(f"{where}: `{name}` is {value!r} and not a boolean", fix=_FIX)
    return value


def _str_list(raw: object, name: str, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RouteError(f"{where}: `{name}` is {raw!r} and not a list of strings", fix=_FIX)
    return tuple(raw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# 8. The merge, the substitution, and the digest.
# --------------------------------------------------------------------------------------------


def compile_policy(
    layers: Sequence[Layer],
    *,
    registry: SignalRegistry | None = None,
    today: str = "",
) -> RoutePolicy:
    """Merge, substitute `@thresholds`, drop expired rules, digest. 05:955-961.

    **Rules CONCATENATE with the higher layer first.** 05:936: *"First match wins, so prepending
    makes the higher layer win with no precedence arithmetic at all."* `layers` arrives in
    `LAYERS` order and is reversed here, so a caller never has to remember which end wins.

    **Scalars are last-write-wins, with one exception that raises.** A `project` layer may only
    LOWER a budget; a `micros_max` above the site layer's is `OW-P-020` *"at load, not a silent
    clamp"* (05:959).

    `today` is an ISO date and defaults to `""`, which keeps every rule. G8 bans a clock in library
    code and this is the reason the ban is right rather than merely a rule: a policy that changed
    shape at midnight would change `policy_digest`, and `policy_digest` is an identity column on
    every `route_decision` ever written.

    `registry` derives each rule's `select`/`settle` phase, which section 4.3's diagram does at
    compile time beside the demand plan. It is optional because `policy_digest` must not depend on
    it -- see `RoutePolicy.phases` -- and because `ow route lint`'s grammar checks, the subsumption
    linter and `ow route explain --render json` all want a compiled policy without needing one.
    """
    ordered = [layer for name in reversed(LAYERS) for layer in layers if layer.layer == name]
    scalars: dict[str, object] = {}
    for layer in reversed(ordered):  # ascending authority: the higher layer writes last
        _merge_scalars(scalars, layer)
    thresholds = _thresholds(scalars.get("thresholds", {}))
    rules = tuple(
        _substitute(rule, thresholds)
        for layer in ordered
        for rule in layer.rules
        if not _expired(rule, today)
    )
    _refuse_duplicate_ids(rules)
    phases = {rule.id: phase_of(rule, registry) for rule in rules} if registry is not None else {}
    policy = RoutePolicy(
        rules=rules,
        policy_digest="",
        thresholds=thresholds,
        budgets=_tables(scalars.get("budget", {})),
        audit=_table(scalars.get("audit", {})),
        slice_by=tuple(_str_list(_table(scalars.get("slice", {})).get("by", []), "by", "[slice]")),
        max_slices=int(_table(scalars.get("slice", {})).get("max_slices", 0) or 0),  # type: ignore[arg-type]
        render=_tables(scalars.get("render", {})),
        calibration=_table(scalars.get("calibration", {})),
        pins=tuple(pin for layer in ordered for pin in layer.pins),
        name=str(scalars.get("policy_name", "")),
        version=int(scalars.get("policy_version", 0) or 0),  # type: ignore[arg-type]
        phases=phases,
    )
    return replace(policy, policy_digest=digest_of(policy))


_ONE_LEVEL: Final[frozenset[str]] = frozenset({"thresholds", "audit", "slice", "calibration"})
"""The scalar blocks that are `key -> value`. Merged PER KEY; see `_merge_scalars`."""

_TWO_LEVEL: Final[frozenset[str]] = frozenset({"budget", "render"})
"""The scalar blocks 05:958 spells with a star -- `[budget.*]`, `[render.*]`. Merged per key of
each sub-table, which is the same rule one level down."""


def _merge_scalars(into: dict[str, object], layer: Layer) -> None:
    """Last-write-wins **on scalars**, which is per KEY and not per block. 05:958.

    *"Merge is concatenation of `[[rule]]` blocks and last-write-wins on scalars (`[thresholds]`,
    `[budget.*]`, `[audit]`, `[slice]`, `[render.*]`)."* The parenthesis names the blocks that HOLD
    the scalars, and the unit that wins is the scalar inside one -- not the block.

    **Section 4.4's own `--profile fast` overlay is what settles the reading**, and it settles it
    the way nothing in section 4.1 does. `50-profile-fast.toml` declares three of the sixteen
    thresholds; under a per-BLOCK merge the other thirteen would vanish, and the first rule reading
    `@thresholds.blank_page_tiles` would fail to compile -- so the plan's own printed overlay would
    not load against the plan's own printed policy. A per-key merge is also the only reading under
    which 05:1747's *"a `--profile fast` overlay changes no rule"* is a statement about rules rather
    than an accident of which keys the overlay happened to restate. D210.

    Top-level scalars (`policy_name`, `policy_version`, `schema`) are single values and are simply
    overwritten, which is the same rule with no nesting to descend.
    """
    for key, value in layer.scalars.items():
        if key == "budget" and layer.layer == "project" and "budget" in into:
            _refuse_raised_budget(_tables(into["budget"]), _tables(value), layer.origin)
        if key in _ONE_LEVEL:
            into[key] = {**_table(into.get(key, {})), **_table(value)}
        elif key in _TWO_LEVEL:
            into[key] = _merge_blocks(_tables(into.get(key, {})), _tables(value))
        else:
            into[key] = value


def _merge_blocks(
    into: Mapping[str, Mapping[str, object]], over: Mapping[str, Mapping[str, object]]
) -> dict[str, dict[str, object]]:
    """`[budget.*]` and `[render.*]`: merge each named sub-table per key, keep the rest.

    A `profile` restating `[budget.per_part] micros` must not silently drop `tokens_out`, `calls`
    and `gpu_ms` -- which under section 6.4's *"first exhausted dimension wins"* would not read as a
    looser budget but as three dimensions that no longer bind at all.
    """
    merged = {block: dict(values) for block, values in into.items()}
    for block, values in over.items():
        merged.setdefault(block, {}).update(values)
    return merged


def _refuse_raised_budget(
    site: Mapping[str, Mapping[str, object]],
    project: Mapping[str, Mapping[str, object]],
    origin: str,
) -> None:
    for block, values in project.items():
        floor = site.get(block, {})
        for dim, value in values.items():
            prior = floor.get(dim)
            if isinstance(prior, int | float) and isinstance(value, int | float) and value > prior:
                raise RouteError(
                    f"OW-P-020: {origin} raises [budget.{block}] {dim} from {prior} to {value}."
                    " A project layer may only LOWER a budget, and a silent clamp would make a"
                    " policy that reads as a raise behave as a no-op",
                    symbol="OW_POLICY_BUDGET_RAISED",
                    fix=_FIX,
                )


def _expired(rule: Rule, today: str) -> bool:
    """A rule whose `expires` is strictly before `today`. String comparison, because ISO-8601 dates
    sort lexicographically -- which is why the format is ISO-8601 and not a locale's."""
    return bool(today and rule.expires and rule.expires < today)


def _refuse_duplicate_ids(rules: Sequence[Rule]) -> None:
    """Two rules with one id across the merged list.

    Not in the plan and refused anyway, for `Registry`'s reason (DR3): `route_decision.rule_id` is
    what `ow route explain` resolves and what 15 section 6.2's escalation report groups by, so two
    rules sharing an id make a report that cannot be acted on. A LAYER may legitimately replace a
    rule -- by prepending one that pre-empts it -- and that is a different id by construction.
    """
    seen: dict[str, str] = {}
    for rule in rules:
        prior = seen.get(rule.id)
        if prior is not None:
            raise RouteError(
                f"rule id {rule.id!r} is declared twice: {prior} and {rule.origin}", fix=_FIX
            )
        seen[rule.id] = rule.origin


def _substitute(rule: Rule, thresholds: Mapping[str, float]) -> Rule:
    """Resolve every `@thresholds.<name>` to its value, keeping the reference on the `Test`.

    A COMPILE-TIME substitution and not an expression (05:977). The reference survives because
    `ow route lint` check 1 resolves it and `ow route propose` fits one threshold at a time and
    needs every site that reads it -- a substitution that erased the name would make both a grep.
    """
    clauses = []
    for clause in rule.when.clauses:
        tests = []
        for key, test in clause.tests:
            if not test.threshold:
                tests.append((key, test))
                continue
            if test.threshold not in thresholds:
                raise RouteError(
                    f"{rule.origin}: rule {rule.id!r} reads @thresholds.{test.threshold},"
                    f" which [thresholds] does not declare",
                    fix=_FIX,
                )
            tests.append((key, Test(test.op, thresholds[test.threshold], test.threshold)))
        clauses.append(Clause(tests=tuple(tests)))
    return replace(rule, when=When(op=rule.when.op, clauses=tuple(clauses)))


def _thresholds(raw: object) -> Mapping[str, float]:
    table = _table(raw)
    out: dict[str, float] = {}
    for key, value in table.items():
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise RouteError(
                f"[thresholds] {key} = {value!r} is not a number. Every threshold is a number"
                " because that is what makes it fittable by isotonic regression (05:977)",
                fix=_FIX,
            )
        out[key] = float(value)
    return out


def _table(raw: object) -> Mapping[str, object]:
    return raw if isinstance(raw, dict) else {}


def _tables(raw: object) -> Mapping[str, Mapping[str, object]]:
    table = _table(raw)
    return {key: value for key, value in table.items() if isinstance(value, dict)}


def digest_of(policy: RoutePolicy) -> str:
    """`policy_digest` -- `sha256_canonical` over the compiled form, rules in merged order.

    05:929 puts it in every `route_decision`, so it has to cover everything that could change a
    decision and nothing that could not. `origin` and `comment` are IN, because a rule moving
    between layers changes which rule pre-empts which even when both texts are identical, and
    because a decision a reviewer cannot trace to a file is the thing `rule_origin` exists to
    prevent. `canary` is in too -- it is read by nothing (D203) and digesting it costs one field,
    while omitting it would make two policies that differ only there share an identity.
    """
    body = {
        "name": policy.name,
        "version": policy.version,
        "thresholds": dict(sorted(policy.thresholds.items())),
        "budgets": {k: dict(sorted(v.items())) for k, v in sorted(policy.budgets.items())},  # type: ignore[arg-type]
        "audit": dict(sorted(policy.audit.items())),  # type: ignore[arg-type]
        "slice_by": list(policy.slice_by),
        "max_slices": policy.max_slices,
        "render": {k: dict(sorted(v.items())) for k, v in sorted(policy.render.items())},  # type: ignore[arg-type]
        "calibration": dict(sorted(policy.calibration.items())),  # type: ignore[arg-type]
        "rules": [_rule_form(rule) for rule in policy.rules],
        "pins": [
            [pin.unit, pin.part, pin.lane, pin.driver, pin.reason, pin.expires]
            for pin in policy.pins
        ],
    }
    return sha256_canonical(body)  # type: ignore[arg-type]


def _rule_form(rule: Rule) -> list[object]:
    """One rule as JSON, in a fixed field order. A list and not a dict, so the order is the
    module's and not `sha256_canonical`'s sort."""
    return [
        rule.id,
        rule.rung.name,
        rule.lane,
        rule.on_unknown,
        rule.expect_unavailable,
        rule.expires,
        rule.canary,
        rule.comment,
        rule.origin,
        [
            rule.when.op,
            [[[k, t.op, t.value, t.threshold] for k, t in c.tests] for c in rule.when.clauses],
        ],
        [
            rule.then.driver,
            rule.then.driver_by,
            None if rule.then.escalate_to is None else rule.then.escalate_to.name,
            rule.then.sequence_max_parts,
            rule.then.terminal,
            rule.then.outcome,
            rule.then.failure_class,
            rule.then.cause_from,
            None if rule.then.max_cost_class is None else rule.then.max_cost_class.value,
            rule.then.admit_lane,
            sorted(rule.then.deny_lanes),
            rule.then.render,
            sorted(member.name for member in rule.then.skip_rungs),
            rule.then.flag_blocks,
            rule.then.not_eligible,
            rule.then.reason,
        ],
    ]


# --------------------------------------------------------------------------------------------
# 9. The two questions that need a registry.
# --------------------------------------------------------------------------------------------


def phase_of(rule: Rule, registry: SignalRegistry) -> str:
    """`"settle"` iff any key in the rule's read set requires this rule's own rung. 05:1140.

    *"A rule belongs to the **settle** phase of rung `R` iff any key in its read set has `R` in
    `requires`, and to `R`'s **select** phase otherwise."* Derived and not declared -- there is no
    grammar key -- which is what keeps `decode.part-text-unusable` from shadowing
    `decode.pdf-text-layer` in the select phase even though both declare `rung = "DECODE"`.

    **Format-independent**, through `registry.requires_of()` rather than `registry.resolve()`. A
    per-format derivation would make one rule a `select` rule on a PDF and a `settle` rule on a
    DOCX, and section 4.3 builds ONE demand plan per `(rung, lane, phase)` and memoises it on
    `(policy_digest, caps_digest)` -- neither of which carries a format. D205 files the gap the
    plan leaves: it says the phase is derived from `SignalSpec.requires` and does not say which
    spec answers when a key has three and the unit's format matches none of them.
    """
    return (
        "settle"
        if any(rule.rung in registry.requires_of(key) for key in rule.read_set)
        else "select"
    )


def rules_needing_on_unknown(policy: RoutePolicy, registry: SignalRegistry) -> tuple[str, ...]:
    """`ow route lint` check 4's finding list: rule ids that read a nullable key and declare none.

    RT7 (05:3347) and the `nullable` column (05:2119). The `exists`-only exemption is 05:1004's and
    is `Rule.exists_only`: an `exists` test is total, so a rule built only of them has no UNKNOWN
    branch to declare.

    Nullability is read through `registry.nullable_of()` and is therefore format-independent, for
    `phase_of()`'s reason: a rule that needs an `on_unknown` on a DOCX needs one on a PDF, and a
    check whose answer moved with the corpus would pass on the machine that ran it and fail on the
    next. An UNREGISTERED key counts as nullable, which is the conservative direction.
    """
    return tuple(
        rule.id
        for rule in policy.rules
        if not (rule.on_unknown or rule.exists_only)
        and any(registry.nullable_of(key) for key in rule.read_set)
    )
