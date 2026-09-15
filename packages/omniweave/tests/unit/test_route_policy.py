"""`omniweave.route.policy` against 05-ingest-and-routing.md sections 4.1, 4.2 and 4.4.

**The strongest test in this file is that section 4.4 loads.** The plan prints a complete
forty-rule policy, and a grammar that cannot read it is wrong whatever its unit tests say. So the
shipped fence is the fixture, and the assertions against it are the plan's own printed counts:
forty rules, twelve at `GATE`, one carrying `expect_unavailable`, one whose `when` is `exists`-only,
and -- section 4.5 check 4 against section 4.4 -- **zero** rules that read a nullable key without
declaring `on_unknown`, which 05:3409 states as a measured number.

Those tests skip when `_plan/` is absent, because the design tree is `.gitignore`d and a clean
clone has none. Everything that does not need it is written against a fixture in this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route import evidence as ev
from omniweave.route import policy as rp
from omniweave.route.rung import Rung
from omniweave_core.errors import RouteError
from omniweave_ports.types import CostClass

if TYPE_CHECKING:
    from pathlib import Path

MINIMAL = b"""
surface = "route"
policy_name = "test"
policy_version = 1

[thresholds]
garble_escalate = 0.5

[[rule]]
id   = "gate.empty"
rung = "GATE"
when = { "unit.format" = "empty" }
then = { outcome = "refuse", failure_class = "corrupt_input", reason = "zero-byte-file" }
"""


def _layer(body: bytes, *, layer: str = "builtin", origin: str = "a test") -> rp.Layer:
    return rp.load_layer(body, layer=layer, origin=origin)


def _policy(body: bytes = MINIMAL, **kw: Any) -> rp.RoutePolicy:
    return rp.compile_policy([_layer(body)], **kw)


def _with_rule(**over: str) -> bytes:
    """A one-rule policy with the named keys spliced into the rule table, for a refusal test."""
    keys = "\n".join(f"{key} = {value}" for key, value in over.items())
    return (
        b'surface = "route"\n\n[[rule]]\nid = "r"\nrung = "DECODE"\n'
        b'when = { "unit.format" = "pdf" }\n' + keys.encode() + b"\n"
    )


# --------------------------------------------------------------------------------------------
# 1. The loader refuses what the grammar closes.
# --------------------------------------------------------------------------------------------


def test_a_file_without_surface_route_does_not_load() -> None:
    """05:951: the three surfaces share one directory and one grammar, and the declaration is the
    only thing keeping a retrieval policy from routing."""
    with pytest.raises(RouteError, match="surface"):
        _layer(b'policy_name = "x"\n')
    with pytest.raises(RouteError, match="surface"):
        _layer(b'surface = "retrieval"\n')


def test_a_then_with_neither_an_action_nor_a_modifier_is_a_load_error() -> None:
    """`OW-P-013`. 05:1028: a `then` of only `reason` MATCHES, pre-empts every later rule under
    first-match-wins, and does nothing -- which is what `gate.untrusted-raises-audit` was."""
    with pytest.raises(RouteError, match="OW-P-013") as caught:
        _layer(_with_rule(**{"then": '{ reason = "nothing" }'}))
    assert caught.value.code() == "OW_POLICY_RULE_DOES_NOTHING"


def test_a_backward_escalate_to_is_refused_at_load() -> None:
    """`OW-P-005`, RT8's FIRST enforcer. 05:3348 calls the SQL trigger *"CI parity ... rather than
    a second opinion"*, which only holds if the compiler refuses first."""
    with pytest.raises(RouteError, match="OW-P-005"):
        _layer(_with_rule(**{"then": '{ escalate_to = "GATE" }'}))
    with pytest.raises(RouteError, match="OW-P-005"):
        _layer(_with_rule(**{"then": '{ escalate_to = "DECODE" }'}))  # equal is not greater


def test_degrade_is_a_legal_forward_escalation_from_page() -> None:
    """The case an ordering built on cost would get wrong: `DEGRADE = 5 > PAGE = 3` while running
    a cheaper driver (05:862)."""
    raw = (
        b'surface = "route"\n\n[[rule]]\nid = "r"\nrung = "PAGE"\n'
        b'when = { "budget.exhausted" = { exists = true } }\n'
        b'then = { escalate_to = "DEGRADE", driver = "parse.pdf.pdfium" }\n'
    )
    (rule,) = _layer(raw).rules
    assert rule.then.escalate_to is Rung.DEGRADE


def test_a_skip_rungs_member_at_or_below_the_rules_own_rung_is_refused() -> None:
    with pytest.raises(RouteError, match="OW-P-005"):
        _layer(_with_rule(**{"then": '{ skip_rungs = ["GATE"] }'}))


def test_a_lower_case_rung_is_refused_and_named() -> None:
    """`OW-P-023`. 05:1219: the policy file is *"an author-facing config artefact and not a
    wire"*, and the lower-case member name is the GENERATED form."""
    with pytest.raises(RouteError, match="OW-P-023") as caught:
        _layer(
            b'surface = "route"\n\n[[rule]]\nid = "r"\nrung = "decode"\n'
            b'when = { "unit.format" = "pdf" }\nthen = { terminal = true }\n'
        )
    assert caught.value.code() == "OW_POLICY_RUNG_SPELLING"


def test_an_unknown_then_key_is_refused_because_the_grammar_is_closed() -> None:
    """05:975: *"A rule that needs a derived quantity gets a `Signal`, not a grammar feature."*"""
    with pytest.raises(RouteError, match="temperature"):
        _layer(_with_rule(**{"then": "{ temperature = 0.7 }"}))


def test_a_when_may_not_nest_a_combinator() -> None:
    """05:968's `when` production is ONE level, and the flatness is what the interval-box
    subsumption linter is decidable over (05:1170)."""
    raw = (
        b'surface = "route"\n\n[[rule]]\nid = "r"\nrung = "GATE"\nthen = { terminal = true }\n'
        b'when.any_of = [ { any_of = [ { "unit.format" = "pdf" } ] } ]\n'
    )
    with pytest.raises(RouteError, match="ONE level"):
        _layer(raw)


def test_two_combinators_in_one_when_are_refused() -> None:
    raw = (
        b'surface = "route"\n\n[[rule]]\nid = "r"\nrung = "GATE"\nthen = { terminal = true }\n'
        b'when.any_of = [ { "unit.format" = "pdf" } ]\n'
        b'when.all_of = [ { "unit.bytes" = { gt = 0 } } ]\n'
    )
    with pytest.raises(RouteError, match="ONE level"):
        _layer(raw)


def test_an_unknown_on_unknown_value_is_refused() -> None:
    with pytest.raises(RouteError, match="on_unknown"):
        _layer(_with_rule(**{"then": "{ terminal = true }", "on_unknown": '"maybe"'}))


def test_two_rules_with_one_id_are_refused() -> None:
    """Not in the plan and refused anyway, for `Registry`'s reason (DR3): `route_decision.rule_id`
    is what `ow route explain` resolves and what 15 section 6.2 groups by."""
    raw = MINIMAL + MINIMAL.split(b"[[rule]]", 1)[1].join([b"[[rule]]", b""])
    with pytest.raises(RouteError, match="declared twice"):
        rp.compile_policy([_layer(raw)])


# --------------------------------------------------------------------------------------------
# 2. The test grammar, three-valued.
# --------------------------------------------------------------------------------------------


def _ev(**values: object) -> ev.Evidence:
    record = ev.Evidence(content_sha256="a" * 64, unit_part="p1")
    for key, value in values.items():
        record.put(key.replace("__", "."), value, provider_version="1.0.0")  # type: ignore[arg-type]
    return record


def test_exists_is_the_only_total_test() -> None:
    """05:1004: *"it tests the presence of a value, so it is defined on UNKNOWN and a rule whose
    `when` consists only of `exists` tests needs no `on_unknown`."*"""
    assert rp.Test("exists", value=True).total is True
    assert rp.Test("eq", value=1).total is False
    assert rp.Test("exists", value=True).holds(None) is False
    assert rp.Test("exists", value=False).holds(None) is True
    assert rp.Test("exists", value=True).holds(0) is True


def test_every_other_test_is_unknown_on_an_unknown_value() -> None:
    for test in (rp.Test("eq", 1), rp.Test("gt", 0.5), rp.Test("in", (1, 2)), rp.Test("ne", "x")):
        assert test.holds(None) is None


def test_a_dtype_mismatch_reads_as_unknown_rather_than_raising() -> None:
    """A provider that answered a count with a string is a defect check 2 and `ow drivers check`
    report; a router that raised on it would take the corpus down at the first bad part, and one
    that returned False would route that part as though the signal were computed and clean."""
    assert rp.Test("gt", 5).holds("not a number") is None
    assert rp.Test("lt", 5).holds(True) is None  # a bool is not a number here


def test_a_clause_ands_across_keys_and_false_beats_unknown() -> None:
    """Kleene. A clause with one False test cannot match whatever the unknown turns out to be, so
    returning UNKNOWN would send the rule into `on_unknown` on the strength of an irrelevant key --
    and `on_unknown = "match"` would fire a rule the author's second condition exists to prevent."""
    clause = rp.Clause(tests=(("a.b", rp.Test("eq", 1)), ("c.d", rp.Test("eq", 2))))
    assert clause.holds(_ev(a__b=1, c__d=2)) is True
    assert clause.holds(_ev(a__b=9, c__d=2)) is False
    assert clause.holds(_ev(c__d=2)) is None
    assert clause.holds(_ev(a__b=9)) is False  # False beats UNKNOWN


def test_any_of_is_true_when_one_clause_holds_even_with_another_unknown() -> None:
    when = rp.When(
        op="any_of",
        clauses=(
            rp.Clause(tests=(("a.b", rp.Test("eq", 1)),)),
            rp.Clause(tests=(("c.d", rp.Test("eq", 2)),)),
        ),
    )
    assert when.holds(_ev(a__b=1)) is True
    assert when.holds(_ev(a__b=9)) is None
    assert when.holds(_ev(a__b=9, c__d=9)) is False


def test_none_of_is_the_negation_of_any_of_unknown_included() -> None:
    when = rp.When(op="none_of", clauses=(rp.Clause(tests=(("a.b", rp.Test("eq", 1)),)),))
    assert when.holds(_ev(a__b=1)) is False
    assert when.holds(_ev(a__b=9)) is True
    assert when.holds(_ev()) is None


def test_an_unresolved_threshold_refuses_to_evaluate() -> None:
    """A test between `load_layer` and `compile_policy` still holds the literal reference, and
    comparing a float against `"@thresholds.garble_escalate"` would be a silent False on every
    part in the corpus."""
    raw = rp.Test("gte", "@thresholds.garble_escalate", "garble_escalate")
    assert raw.resolved is False
    with pytest.raises(RouteError, match="never substituted"):
        raw.holds(0.9)


def test_the_cause_renders_the_clause_that_fired() -> None:
    """05:1974's `'garble.score=0.71>=0.50'` -- a GENERATED string, *"so 'why it escalated' is a
    `GROUP BY` and not a log grep"*."""
    test = rp.Test("gte", 0.5, "garble_escalate")
    assert test.render("garble.score", 0.71) == "garble.score=0.71>=0.5"


# --------------------------------------------------------------------------------------------
# 3. `@thresholds`, the merge and the digest.
# --------------------------------------------------------------------------------------------


def test_a_threshold_is_substituted_at_compile_and_keeps_its_reference() -> None:
    """05:977: a COMPILE-TIME substitution, not an expression. The reference survives because
    check 1 resolves it and `ow route propose` fits one threshold and needs every site."""
    raw = (
        b'surface = "route"\n\n[thresholds]\ngarble_escalate = 0.5\n\n[[rule]]\n'
        b'id = "r"\nrung = "DECODE"\non_unknown = "match"\n'
        b'when = { "garble.score" = { gte = "@thresholds.garble_escalate" } }\n'
        b'then = { escalate_to = "PAGE" }\n'
    )
    policy = rp.compile_policy([_layer(raw)])
    (_key, test) = policy.rules[0].when.clauses[0].tests[0]
    assert test.value == 0.5
    assert test.threshold == "garble_escalate"
    assert policy.threshold_keys() == ("garble_escalate",)


def test_a_threshold_the_policy_does_not_declare_is_refused() -> None:
    raw = (
        b'surface = "route"\n\n[[rule]]\nid = "r"\nrung = "DECODE"\non_unknown = "skip"\n'
        b'when = { "garble.score" = { gte = "@thresholds.nope" } }\n'
        b'then = { escalate_to = "PAGE" }\n'
    )
    with pytest.raises(RouteError, match="nope"):
        rp.compile_policy([_layer(raw)])


def test_a_non_numeric_threshold_is_refused() -> None:
    """Every threshold is a number because that is what makes it fittable by isotonic regression
    over the decision log (05:977)."""
    with pytest.raises(RouteError, match="isotonic"):
        rp.compile_policy([_layer(b'surface = "route"\n[thresholds]\nx = "high"\n')])


def test_a_higher_layer_prepends_so_first_match_wins_needs_no_arithmetic() -> None:
    """05:936: *"First match wins, so prepending makes the higher layer win with no precedence
    arithmetic at all."*"""
    builtin = _layer(MINIMAL, layer="builtin", origin="builtin.toml")
    project = _layer(
        b'surface = "route"\n\n[[rule]]\nid = "project.first"\nrung = "GATE"\n'
        b'when = { "unit.format" = "empty" }\nthen = { outcome = "skip", reason = "ours" }\n',
        layer="project",
        origin="project.toml",
    )
    policy = rp.compile_policy([builtin, project])
    assert [rule.id for rule in policy.rules] == ["project.first", "gate.empty"]


def test_a_project_layer_may_not_raise_a_budget() -> None:
    """`OW-P-020`. 05:959: *"at load, not a silent clamp"* -- the third option is the worst,
    because the file then reads as a raise and behaves as a no-op."""
    site = _layer(
        b'surface = "route"\n[budget.per_unit]\nmicros_max = 1000\n', layer="site", origin="site"
    )
    project = _layer(
        b'surface = "route"\n[budget.per_unit]\nmicros_max = 9999\n',
        layer="project",
        origin="project",
    )
    with pytest.raises(RouteError, match="OW-P-020") as caught:
        rp.compile_policy([site, project])
    assert caught.value.code() == "OW_POLICY_BUDGET_RAISED"


def test_a_project_layer_may_lower_a_budget() -> None:
    site = _layer(
        b'surface = "route"\n[budget.per_unit]\nmicros_max = 1000\n', layer="site", origin="site"
    )
    project = _layer(
        b'surface = "route"\n[budget.per_unit]\nmicros_max = 500\n',
        layer="project",
        origin="project",
    )
    assert rp.compile_policy([site, project]).budgets["per_unit"]["micros_max"] == 500


def test_expires_drops_a_rule_only_when_today_is_supplied() -> None:
    """05:2976's auto-demote rule *"expires on its own"*. The date is INJECTED: G8 bans a clock in
    library code, and a policy that changed shape at midnight would change `policy_digest`, which
    is an identity column on every `route_decision` ever written."""
    raw = MINIMAL.replace(b'rung = "GATE"', b'rung = "GATE"\nexpires = "2026-01-01"')
    assert len(_policy(raw).rules) == 1
    assert len(_policy(raw, today="2025-12-31").rules) == 1
    assert len(_policy(raw, today="2026-06-01").rules) == 0


def test_the_digest_covers_the_rule_body_the_thresholds_and_the_origin() -> None:
    base = _policy().policy_digest
    assert _policy().policy_digest == base  # deterministic
    moved = _policy(MINIMAL.replace(b'reason = "zero-byte-file"', b'reason = "empty"'))
    assert moved.policy_digest != base
    threshold = _policy(MINIMAL.replace(b"garble_escalate = 0.5", b"garble_escalate = 0.6"))
    assert threshold.policy_digest != base
    origin = rp.compile_policy([_layer(MINIMAL, origin="elsewhere.toml")])
    assert origin.policy_digest != base


def test_the_digest_does_not_cover_the_derived_phases() -> None:
    """A phase is derived from `SignalSpec.requires`, which is a property of the INSTALLED
    providers. Folding it in would make two machines running the same files compute two
    `policy_digest`s and therefore two `decision_id`s for one decision."""
    registry = ev.build_registry(ev.builtin_specs())
    assert _policy(registry=registry).policy_digest == _policy().policy_digest


# --------------------------------------------------------------------------------------------
# 4. The action/modifier split.
# --------------------------------------------------------------------------------------------


def test_outcome_not_eligible_parses_as_a_modifier_and_leaves_outcome_unset() -> None:
    """05:1054, made structural: it excludes BLOCKS from the rung without touching the part, which
    is how `REPAIR` is made unavailable on PDF."""
    (rule,) = _layer(
        _with_rule(**{"then": '{ outcome = "not_eligible", reason = "layout_unavailable" }'})
    ).rules
    assert rule.then.not_eligible is True
    assert rule.then.outcome is None
    assert rule.is_modifier is True
    assert rule.is_action is False


@pytest.mark.parametrize(
    ("then", "action", "modifier"),
    [
        ('{ driver = "parse.pdf.pdfium" }', True, False),
        ('{ outcome = "refuse", failure_class = "encrypted" }', True, False),
        ('{ max_cost_class = "local_compute" }', False, True),
        ('{ lane = "fields", render = "structure" }', False, True),
        ('{ skip_rungs = ["REPAIR"] }', False, True),
        ('{ escalate_to = "PAGE", render = "glyph" }', True, True),
    ],
)
def test_the_split_is_decided_by_the_keys_present(then: str, action: bool, modifier: bool) -> None:
    (rule,) = _layer(_with_rule(**{"then": then})).rules
    assert (rule.is_action, rule.is_modifier) == (action, modifier)


def test_rule_lane_and_then_lane_are_different_keys() -> None:
    """05:1032, the conflation a reader makes: `rule.lane` says which lane's rule LIST this rule
    belongs to; `then.lane` ADMITS a lane for this part."""
    (rule,) = _layer(_with_rule(**{"lane": '"table"', "then": '{ lane = "fields" }'})).rules
    assert rule.lane == "table"
    assert rule.then.admit_lane == "fields"


def test_a_modifier_contributes_its_own_monoid_element() -> None:
    (rule,) = _layer(_with_rule(**{"then": '{ max_cost_class = "free", lane = "math" }'})).rules
    mods = rule.then.modifiers()
    assert mods.max_cost_class is CostClass.FREE
    assert mods.admit_lanes == {"math"}


# --------------------------------------------------------------------------------------------
# 5. Section 4.4, the shipped policy. The strongest test here.
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shipped(plan: Any) -> bytes:
    """Section 4.4's ` ```toml ` fence -- the complete forty-rule `builtin` layer."""
    plan.require()
    for body in plan.fences("05-ingest-and-routing.md", "toml"):
        if 'policy_name    = "builtin:balanced"' in body:
            return body.encode()
    pytest.skip("05 section 4.4's policy fence is not in this checkout")


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> ev.SignalRegistry:
    specs = list(ev.builtin_specs())
    for provider, relative in (
        ("pdfium", "packages/omniweave-pdf/src/omniweave_pdf/signals.toml"),
        ("officexml", "packages/omniweave-office/src/omniweave_office/signals.toml"),
    ):
        raw = (repo_root / relative).read_bytes()
        specs.extend(ev.load_signals(raw, provider=provider, origin=relative))
    return ev.build_registry(specs)


def test_the_shipped_policy_loads_and_is_forty_rules(shipped: bytes) -> None:
    """05:1216: *"Forty rules."* A grammar that cannot read the plan's own printed policy is wrong
    whatever its unit tests say."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")])
    assert len(policy.rules) == 40
    assert policy.name == "builtin:balanced"
    assert policy.version == 1


def test_the_gate_block_is_twelve_rules(shipped: bytes) -> None:
    """The fence's own heading: *"GATE -- nothing has been decoded. Twelve rules."*"""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")])
    assert len([rule for rule in policy.rules if rule.rung is Rung.GATE]) == 12


def test_exactly_one_shipped_rule_carries_expect_unavailable(shipped: bytes) -> None:
    """05:1219: *"THE ONE RULE IN THIS FILE THAT CARRIES IT"*, and check 14 makes it
    self-retiring -- the day an open-tier driver ships, this line fails the build."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")])
    assert [rule.id for rule in policy.rules if rule.expect_unavailable] == ["fields.extract"]


def test_exactly_one_shipped_rule_is_exists_only(shipped: bytes) -> None:
    """05:1004's named beneficiary: *"That is what lets `degrade.budget-exhausted` read
    `budget.exhausted` without one."*"""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")])
    assert [rule.id for rule in policy.rules if rule.exists_only] == ["degrade.budget-exhausted"]


def test_check_four_finds_nothing_in_the_shipped_policy(
    shipped: bytes, registry: ev.SignalRegistry
) -> None:
    """05:3409 states it as a measured number: seven rules of the charter's retired policy fail
    check 4 *"against **zero** in section 4.4"*. This reproduces the zero."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")], registry=registry)
    assert rp.rules_needing_on_unknown(policy, registry) == ()


def test_the_shipped_policy_names_only_registered_signals(
    shipped: bytes, registry: ev.SignalRegistry
) -> None:
    """Check 1's core: every key in a `when` clause resolves against the `SignalSpec` registry.
    `layout.class_hist` is the one key with no provider at release 1, and no shipped rule reads
    it."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")], registry=registry)
    registered = set(registry.keys())
    unknown = sorted(key for key in policy.read_set() if key not in registered)
    assert unknown == []


def test_every_shipped_slice_axis_is_a_registered_signal(
    shipped: bytes, registry: ev.SignalRegistry
) -> None:
    """The other half of check 1: `[slice] by`. A slice axis nothing computes is a scoreboard
    column that is always `~`."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")], registry=registry)
    assert policy.slice_by == (
        "unit.format",
        "unit.producer_family",
        "decode.has_text_span",
        "corpus.lang",
    )
    assert all(key in set(registry.keys()) for key in policy.slice_by)


def test_two_shipped_thresholds_are_read_by_no_rule(shipped: bytes) -> None:
    """D204. `[thresholds]` is *"the learnable numbers. `ow route propose` fits these per slice"*
    and two of the sixteen are read by a PROVIDER rather than by a rule: `garble_min_chars` is
    `garble.score`'s own floor (05:2285) and `math_char_frac` is the per-block fraction inside
    `math.part_frac` (05:2248). `ow route propose` cannot move either."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")])
    assert len(policy.thresholds) == 16
    unread = sorted(set(policy.thresholds) - set(policy.threshold_keys()))
    assert unread == ["garble_min_chars", "math_char_frac"]


def test_every_shipped_rung_and_lane_is_a_member_of_its_registry(shipped: bytes) -> None:
    from omniweave.route.rung import LANES  # noqa: PLC0415 -- one assertion needs it

    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")])
    assert {rule.lane for rule in policy.rules} <= LANES
    assert {rule.rung for rule in policy.rules} <= set(Rung)


def test_the_derived_phase_is_format_independent(
    shipped: bytes, registry: ev.SignalRegistry
) -> None:
    """D205. `decode.admit-table-lane` reads `block.type`, which has no PDF row (05:2162), so a
    per-format derivation would make it a `select` rule on a PDF and a `settle` rule on a DOCX.
    Section 4.3 builds ONE demand plan per `(rung, lane, phase)` and memoises it on
    `(policy_digest, caps_digest)`, neither of which carries a format."""
    policy = rp.compile_policy([_layer(shipped, origin="05 section 4.4")], registry=registry)
    assert policy.phases["decode.admit-table-lane"] == "settle"
    assert policy.phases["decode.pdf-text-layer"] == "select"
    assert policy.phases["decode.part-text-unusable"] == "settle"


def test_a_policy_compiled_without_a_registry_puts_every_rule_in_select() -> None:
    """The default is correct rather than lenient: `SignalSpec.requires` defaults to `()`, so a
    policy over signals that read no driver output is entirely a select-phase policy."""
    policy = _policy()
    assert policy.phases == {}
    assert policy.phase_of_rule(policy.rules[0]) == "select"
