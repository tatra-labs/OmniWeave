"""`ow route lint --explain <rule-id>` -- one rule, everything a reviewer needs to argue with it.

05:1811 lists exactly what it prints and the list is the specification:

> `ow route lint --explain <rule-id>` prints the rule's derived phase, whether it is an action or a
> modifier, its read set with each key's `cost_class`, nullability and resolved provider, and the
> demand-plan group it lands in.

Five facts, and **not one of them is in the rule's own text.** The phase is derived from the keys'
`requires` (05:1136); action-or-modifier is derived from which family the `then` keys belong to
(05:1025); `cost_class`, nullability and the provider are the registry's; and the group is the
compiled demand plan's. So this is not a pretty-printer for a TOML block -- it is the four
derivations a reader would otherwise have to perform by hand, performed once and attributed.

## Why the provider column is per format

05:2224: *"`ow route lint --explain` prints the provider resolved per format, which is how a
reviewer sees at a glance that `block.type` has no PDF row."* A registry lookup by key alone
answers "somebody serves this"; the question a reviewer actually has is "does anybody serve it for
the units this rule fires on", and those are two different answers for three of the day-one
registry's keys. `unserved` is that difference made explicit: the format tokens the rule's own
`unit.format` clause names for which the key resolves to nothing.

**A rule that names no format gets an empty `unserved` and that is not a pass.** It means the
question was not asked, because the rule fires on every format and "every format" is not a list this
module may invent -- the computed domain is `route/detect.py`'s and 05 section 2.2 has not shipped
it. A caller with the domain passes it; one without gets silence rather than a guess.

## What is NOT here

`ow route explain <unit> [--part N] [--lane L]` (05:1215) is a different command with a different
subject: it reads a stored `route_decision` and its `route_evidence` payload and prints what one
part actually did. It needs a store and this module needs none, which is why they are not one
function -- and it is W5.5's other half.

Specified in 05-ingest-and-routing.md sections 4.5 and 5.2; scheduled by 16-roadmap.md:607.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave.route import demand as rd

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from omniweave_ports.types import CostClass

    from omniweave.route.evidence import SignalRegistry
    from omniweave.route.policy import RoutePolicy, Rule
    from omniweave.route.rung import Rung

__all__ = ["KeyReading", "RuleExplanation", "explain_rule"]

FALLBACK: Final[str] = "*"
"""What a spec with an empty `serves` is shown as -- the row `resolve()` falls back to.

05:2220: *"the same `(key, format)` is `OW-P-022` at startup, not a precedence puzzle, so exactly
one provider serves a key for a given `unit.format`."* An empty `serves` means every format, and
printing it as an empty set would read as "no format", which is the opposite. `*` is the only
glyph in this module that is not a key, a format token or a provider name, so it cannot be
mistaken for one."""


@dataclass(frozen=True, slots=True)
class KeyReading:
    """One key of one rule's read set, with the four things the registry and the plan know about it.

    `group` is the index into the rule's own `(rung, lane, phase)` plan, so `0` is the FREE group
    and `-1` is "in no group" -- which for a key the rule reads means nothing can compute it, and
    is check 1's finding seen from the other side.
    """

    key: str
    cost_class: CostClass | None
    nullable: bool
    requires: tuple[Rung, ...]
    providers: tuple[tuple[str, tuple[str, ...]], ...]
    unserved: tuple[str, ...] = ()
    group: int = -1

    def render(self) -> str:
        """One line: the key, its cost class, its nullability, its providers, its group."""
        cost = self.cost_class.value if self.cost_class is not None else "UNREGISTERED"
        served = (
            ", ".join(f"{name}[{'|'.join(formats)}]" for name, formats in self.providers)
            or "no provider"
        )
        parts = [
            f"{self.key:32s}",
            f"{cost:13s}",
            "nullable" if self.nullable else "non-null",
            f"group {self.group}" if self.group >= 0 else "no group",
            served,
        ]
        if self.requires:
            parts.append("requires " + ",".join(rung.name for rung in self.requires))
        if self.unserved:
            parts.append("UNSERVED on " + ",".join(self.unserved))
        return "  ".join(parts)


@dataclass(frozen=True, slots=True)
class RuleExplanation:
    """05:1811's five facts about one rule, derived rather than transcribed."""

    rule_id: str
    origin: str
    layer: str
    rung: Rung
    lane: str
    phase: str
    kind: str
    reads: tuple[KeyReading, ...]
    plan_label: str
    on_unknown: str = ""

    def render(self) -> tuple[str, ...]:
        """What the command prints. The header, then one line per key in the rule's read order.

        Read order and not sorted: `policy.When.keys` is documented as the order a reader sees in
        the file, and a reviewer reading `--explain` beside the policy is comparing two lists. The
        demand plan sorts within a group for its own reason; this is the other view.
        """
        header = (
            f"{self.rule_id}  [{self.layer}] {self.origin}\n"
            f"  {self.rung.name}/{self.lane}/{self.phase}  {self.kind}"
            + (f"  on_unknown={self.on_unknown}" if self.on_unknown else "  on_unknown=(none)")
            + f"  -> demand plan {self.plan_label}"
        )
        return (header, *(f"  {reading.render()}" for reading in self.reads))


def explain_rule(
    policy: RoutePolicy,
    rule_id: str,
    *,
    registry: SignalRegistry,
    demand: rd.DemandMap | None = None,
    formats: Sequence[str] = (),
) -> RuleExplanation:
    """The five facts, for one rule id. Raises `KeyError` on an id the policy does not carry.

    `demand` is optional: without it every `group` is `-1` and the header's plan label says so,
    which keeps `--explain` usable on a policy compiled without a registry. With it the group index
    is the one section 4.3's loop would compute, so a reviewer can read "group 1" as "this key costs
    a raster before this rule can be tested".

    `formats` narrows the `unserved` column. Empty means the rule's own `unit.format` literals,
    which is the right default: a rule that names formats is asking about those, and one that names
    none is asking about all of them -- a set this module may not invent.
    """
    rule = _find(policy, rule_id)
    phase = policy.phase_of_rule(rule)
    plan = rd.plan_for(demand, rule.rung, rule.lane, phase) if demand is not None else None
    asked = tuple(formats) or _format_literals(rule)
    return RuleExplanation(
        rule_id=rule.id,
        origin=rule.origin or "(no origin)",
        layer=rule.layer or "(no layer)",
        rung=rule.rung,
        lane=rule.lane,
        phase=phase,
        kind="action" if rule.is_action else "modifier",
        on_unknown=rule.on_unknown,
        plan_label=plan.label if plan is not None else "(not compiled)",
        reads=tuple(_reading(key, registry, plan, asked) for key in rule.when.keys),
    )


def _find(policy: RoutePolicy, rule_id: str) -> Rule:
    for rule in policy.rules:
        if rule.id == rule_id:
            return rule
    known = ", ".join(sorted(rule.id for rule in policy.rules)[:6])
    message = f"{rule_id!r} is not a rule in this policy; it has {len(policy.rules)}: {known}, ..."
    raise KeyError(message)


def _reading(
    key: str, registry: SignalRegistry, plan: rd.DemandPlan | None, formats: Iterable[str]
) -> KeyReading:
    specs = registry.specs_for(key)
    providers = tuple(
        (spec.provider, tuple(sorted(spec.serves)) if spec.serves else (FALLBACK,))
        for spec in specs
    )
    return KeyReading(
        key=key,
        cost_class=registry.cost_class_of(key),
        nullable=registry.nullable_of(key),
        requires=registry.requires_of(key),
        providers=providers,
        unserved=tuple(token for token in formats if registry.resolve(key, token) is None),
        group=plan.index_of(key) if plan is not None else -1,
    )


def _format_literals(rule: Rule) -> tuple[str, ...]:
    """The rule's own `unit.format` literals, sorted. Duplicated from `checks.py` on purpose.

    Three lines, and importing them would make this module depend on the one that reads driver
    cards -- for a function that reads a `When`. The two will diverge the day one of them needs a
    second key, and a shared helper would then have two callers wanting two things.
    """
    named: set[str] = set()
    for clause in rule.when.clauses:
        for key, test in clause.tests:
            if key != "unit.format" or test.op == "exists":
                continue
            values = test.value if isinstance(test.value, tuple) else (test.value,)
            named.update(one for one in values if isinstance(one, str))
    return tuple(sorted(named))
