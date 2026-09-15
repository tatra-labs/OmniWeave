"""`evaluate()` -- PURE. One `(rung, lane, phase)` in, one action and every modifier out.

05-ingest-and-routing.md section 4.6 prints the signature with the file header
`# omniweave/route/eval.py -- PURE`; section 4.2 (:1016-1080) gives the action/modifier split;
section 4.3 (:1081-1186) gives the loop this function is called from and the seven properties that
order buys. 16-roadmap.md:604 schedules it as W5.2.

**INV-14 in one line: this module sees no ledger, no clock, no RNG, no environment, no IO and no
`RunContext`.** 05:1817 says why the claim is checkable at all: *"A purity claim is only checkable
if the types on both sides of the function are printed, because purity is a property of a
**signature** plus what the argument types can reach."* The four argument types are
`RoutePolicy` (frozen data), `Evidence` (a read log whose only accessor returns a `Scalar`),
`RouteHints` (five optional scalars and no budget field) and two enum members. None of them reaches
anything.

`tools/gate_pure_eval.py` is the mechanical half: semgrep bans `time.`, `random.`, `os.environ`,
`importlib` and `open(` in this file, and the module-level import set is pinned by a test. RT1 is
the behavioural half -- a property test evaluates fixtures twice in shuffled order and asserts
identity.

## What one call does, and what it deliberately does not

One call walks the rules at `(rung, lane)` whose derived phase is `phase`, in merged order, and
returns two things:

- **at most ONE action**, first-match-wins. 05:1023: *"Exactly one action per `(rung, lane, phase)`;
  later matching action rules are not tested."*
- **every matching modifier**, merged by `Modifiers`' per-key monoids. 05:1024: *"every matching
  rule contributes."* This is the half a single ordered list cannot deliver, and the shipped `GATE`
  block is the proof: four rules -- two cost clamps and two lane admissions -- must all take effect
  on one part.

It does **not** settle the part, run the driver, write the row, mint a `Degradation` or advance the
rung. Those are section 4.3's loop's, and the split is what keeps this function pure: a
`Degradation` names a `unit_uri`, and RT2 says `evaluate()` must never see one.

## `on_unknown`, and why `defer` looks like "did not fire" from in here

Three values (05:1126-1130) and this function implements two of them. `match` fires the rule;
`skip` does not. `defer` does not fire it **in this call** -- because whether a deferral is still
pending is a question about which `CostClass` groups have been computed, and that is the demand
plan's state, not the evidence's. `pending_deferrals()` below is the pure predicate the loop asks,
and 05:1119 is the clause it implements: a deferral promotes a group only when the deferring rule is
*"earlier in file order"* than the rule that matched.

*"If the key is still unavailable afterwards, `defer` degrades to `skip` and records
`Degradation(kind="signal_unavailable")` naming the key and its provider"* -- the degradation is the
loop's to mint, for RT2's reason.

**A rule that reads a nullable key and declares no `on_unknown` does not fire on UNKNOWN.** That
rule is `ow route lint` check 4's error (`OW-P-004`), so a linted policy never reaches this branch;
`skip` is the right behaviour for an unlinted one because it is the only one of the three that
cannot spend money.

## `RouteHints` reaches exactly one decision, and the other four arrive as evidence

`max_rung` clamps `escalate_to`, and that is the whole of it. The other four fields --
`lane`, `prefer_capability`, `deadline_ms`, `schema` -- are registered as the `request.*` evidence
keys of 05 section 5.1, put into `Evidence` by the `builtin` provider, and read by rules like any
other signal. Applying them here as well would give one fact two paths and two ways to disagree,
and only one of the two would be in `read_set_digest`.

A clamp suppresses the escalation and records nothing else: *"a part that would have escalated past
it records `Degradation(kind="rung_ceiling")`"* (05:2024), and that record is the loop's.

Core plus this package's `decision`, `policy` and `rung`. Nothing else, and the import list is a
pinned test.

Tier T-PUBLIC: 18-api-sketch.md:843.

Specified in 05-ingest-and-routing.md sections 4.2, 4.3 and 4.6; 01-principles.md INV-14;
16-roadmap.md:604.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from omniweave.route.decision import Modifiers, RouteDecision, RouteHints
from omniweave.route.rung import Rung

if TYPE_CHECKING:
    from omniweave.route.evidence import Evidence, Scalar
    from omniweave.route.policy import RoutePolicy, Rule

__all__ = [
    "PHASES",
    "SLICE_UNAVAILABLE",
    "evaluate",
    "pending_deferrals",
    "slice_key",
]

PHASES: Final[tuple[str, str]] = ("select", "settle")
"""05:1090's inner loop, in order. Derived from `SignalSpec.requires` and never declared."""

SLICE_UNAVAILABLE: Final[str] = "~"
"""05:1207: *"`~` is chosen because it sorts after every alphanumeric and cannot collide with a
format token or an ISO-639-1 code."* One character, and the sort order is the reason for it."""

_SLICE_JOIN: Final[str] = "/"


def evaluate(  # noqa: PLR0917 -- 05:1826 prints six positional arguments; see below
    policy: RoutePolicy,
    ev: Evidence,
    hints: RouteHints,
    rung: Rung,
    lane: str,
    phase: str,
) -> tuple[RouteDecision, Modifiers]:
    """The six-argument, two-value form of 05:1826. PURE.

    **Six positional arguments, because the plan prints six.** The charter's
    `evaluate(policy, ev, hints)` is superseded and this form is the superseding one; making the
    last three keyword-only to satisfy a lint would put a third spelling of one signature into the
    framework, which is the cost the supersession was taken to avoid.

    05:1836 explains why it is six and not the charter's three: *"This document's rung loop
    evaluates one `(rung, lane, phase)` at a time and unpacks two values, because the
    action/modifier split means one call yields at most one action and *every* matching modifier.
    The three-argument, single-return form is superseded by the six-argument, two-value form printed
    here."*

    Returns a decision with `matched = False` when no action rule fired. 05:1946: *"the loop in
    section 4.3 continues and writes no row."* The `Modifiers` are returned either way -- a part
    whose `GATE` action refused still took its two cost clamps, and `ow route explain` prints them.

    **"Not tested" is stronger than "does not win", and the read set is why.** 05:1023 says
    *"later matching action rules are **not tested**"*, so once an action has fired this walk skips
    every later rule carrying an action key -- including the eleven of the shipped forty that carry
    both an action and a modifier. Merely declining to let them win would still evaluate their
    `when`, which READS their keys, which puts those keys in `read_set_digest` -- an identity
    column. A clean born-digital page would then carry `ink.tiles` and `block.type` in its
    decision's identity, both UNKNOWN, both belonging to rules the page never reached. Pure
    modifiers behind the action are still tested, because *"every matching rule contributes"*.

    `terminal` stops the walk. 05:1059: *"`terminal` stops evaluation rather than merely forbidding
    escalation"*, and the difference is what makes `decode.office-native` followed by
    `decode.part-text-unusable` (`on_unknown = "match"`, because every `pdfium` key is UNKNOWN on a
    DOCX) an unreachable contradiction rather than a policy the linter has to refuse. In the shipped
    policy the stop costs nothing: every `terminal` rule is in a `select` phase and every lane
    admission is in a `settle` phase, so no modifier is behind one.
    """
    if phase not in PHASES:
        message = f"{phase!r} is not one of {', '.join(PHASES)}"
        raise ValueError(message)
    decision = RouteDecision(
        lane=lane,
        rung=rung,
        policy_digest=policy.policy_digest,
        slice_key=slice_key(policy, ev),
    )
    mods = Modifiers()
    for rule in policy.rules_at(rung, lane):
        if policy.phase_of_rule(rule) != phase:
            continue
        if decision.matched and rule.is_action:
            continue  # 05:1023: "later matching action rules are NOT TESTED"
        if not _fires(rule, ev):
            continue
        if rule.is_modifier:
            mods = mods.merge(replace(rule.then.modifiers(), rule_ids=(rule.id,)))
        if rule.is_action:
            decision = _decide(decision, rule, ev, hints)
            if rule.then.terminal:
                break
    return decision, mods


def _fires(rule: Rule, ev: Evidence) -> bool:
    """Whether this rule's `when` fires, with `on_unknown` applied to the UNKNOWN case.

    `defer` reads as "does not fire" here and is not the same as `skip`: the loop asks
    `pending_deferrals()` before letting a later rule win, and promotes the group holding this
    rule's keys. From inside one call the two are indistinguishable, which is correct -- a pure
    function cannot know which groups have run.
    """
    verdict = rule.when.holds(ev)
    if verdict is not None:
        return verdict
    return rule.on_unknown == "match"


def _decide(base: RouteDecision, rule: Rule, ev: Evidence, hints: RouteHints) -> RouteDecision:
    """Fill the decision from the winning action rule. Every field 05:1943-1979 lists."""
    then = rule.then
    return replace(
        base,
        matched=True,
        rule_id=rule.id,
        rule_origin=rule.origin,
        driver=then.driver,
        driver_by=then.driver_by,
        escalate_to=_clamp(then.escalate_to, hints.max_rung),
        terminal=then.terminal,
        outcome=then.outcome,  # type: ignore[arg-type] -- the loader closed it over OUTCOMES
        failure_class=then.failure_class,
        sequence_max_parts=then.sequence_max_parts,
        cause=rule.when.cause(ev) if then.cause_from == "when" else None,
        reason=then.reason,
    )


def _clamp(escalate_to: Rung | None, ceiling: Rung | None) -> Rung | None:
    """`RouteHints.max_rung`, the one hint this function applies. It RESTRICTS and never widens.

    A suppressed escalation returns `None` rather than the ceiling: escalating to the ceiling would
    run a rung the policy did not choose, which is a different decision rather than a restricted
    one. The loop then settles the part where it is and records `Degradation(kind="rung_ceiling")`.
    """
    if escalate_to is None or ceiling is None:
        return escalate_to
    return escalate_to if escalate_to <= ceiling else None


def pending_deferrals(
    policy: RoutePolicy,
    ev: Evidence,
    rung: Rung,
    lane: str,
    phase: str,
    *,
    before: str = "",
) -> tuple[str, ...]:
    """Rule ids at this `(rung, lane, phase)` that are UNKNOWN and declare `on_unknown = "defer"`.

    05:1116, the clause this implements: *"If an action rule matches on the FREE group alone,
    evaluation stops there -- unless a rule EARLIER IN FILE ORDER at this `(rung, lane, phase)` is
    currently UNKNOWN and declares `on_unknown = "defer"`, in which case the group holding its
    missing keys is promoted (still ascending, still under the `GATE` clamp) and evaluation
    restarts."*

    `before` is that "earlier in file order" clause, made mechanical: pass the id of the rule that
    matched and the result holds only the deferring rules ahead of it. 05:1120 gives the case the
    clause exists for and the case it exists to avoid, in one sentence: *"It is the whole reason a
    scanned page pays 15 ms for `ink.tiles` before spending 2.4 s of GPU, and the whole reason a
    clean page does not."*

    Pure, and named here rather than on the `DemandPlan` because the predicate is over the policy
    and the evidence and nothing else. `DemandPlan.deferrals_pending(ev)` (W5.2's other half) is the
    caller that also knows which groups have run.
    """
    out: list[str] = []
    for rule in policy.rules_at(rung, lane):
        if rule.id == before:
            break
        if (
            policy.phase_of_rule(rule) == phase
            and rule.on_unknown == "defer"
            and rule.when.holds(ev) is None
        ):
            out.append(rule.id)
    return tuple(out)


def slice_key(policy: RoutePolicy, ev: Evidence) -> str:
    """`'pdf/workiva/true/en'` -- 05:1206's `/`-joined `[slice] by` in DECLARATION ORDER.

    *"With `~` for an unavailable component: `pdf/workiva/true/en`, `docx/~/true/de`."*

    **A bool renders lower-case.** The plan's own example is `true`, not Python's `True`, and the
    key is a stored string a scoreboard groups by -- so a `str(True)` here would give `ow route
    scoreboard` two spellings of one slice the day anything else wrote the JSON form.

    **The `~overflow` fold is NOT here.** 05:1209 puts it *"beyond `max_slices = 512` distinct keys
    in one generation"*, which is a count over the whole generation; this function sees one part.
    The scoreboard folds, and `ow route scoreboard` prints the fold count.

    Reading the slice keys puts them in the read set, and that is correct rather than incidental:
    section 4.3 property 1 says a clean born-digital part writes **five** `route_signal` rows, and
    the shipped `[slice] by` is four keys of which `unit.format` is also the one
    `decode.pdf-text-layer` reads -- four plus `decode.char_count` is the five.
    """
    return _SLICE_JOIN.join(_component(ev.read(key)) for key in policy.slice_by)


def _component(value: Scalar) -> str:
    if value is None:
        return SLICE_UNAVAILABLE
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
