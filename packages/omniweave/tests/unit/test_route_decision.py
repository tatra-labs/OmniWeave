"""`omniweave.route.decision` against 05-ingest-and-routing.md section 4.6 (:1907-2033).

Three types, and the tests split the same way they do. `RouteDecision`'s content is its IDENTITY --
eight fields, derived id, and nothing about when it was made. `Modifiers`' content is its MONOIDS --
seven keys, seven combining rules, and the whole reason `then` splits in two. `RouteHints`' content
is a field it does not have, so the test for it is a list of absences.
"""

from __future__ import annotations

from dataclasses import fields

import pytest
from omniweave.route.decision import (
    DECISION_PREFIX,
    IDENTITY_FIELDS,
    OUTCOMES,
    Modifiers,
    RouteDecision,
    RouteHints,
)
from omniweave.route.rung import Rung
from omniweave_core.drivers.resolve import COST_CLASS_ORDER
from omniweave_ports.types import CostClass

IDENTITY = {
    "content_sha256": "a" * 64,
    "unit_part": "p1",
    "lane": "text",
    "rung": Rung.DECODE,
    "policy_digest": "p",
    "pricebook_digest": "b",
    "hints_digest": "h",
    "read_set_digest": "r",
}


# --------------------------------------------------------------------------------------------
# 1. `RouteDecision` -- eight identity fields, and a derived id.
# --------------------------------------------------------------------------------------------


def test_the_identity_is_exactly_the_eight_columns_in_the_plans_order() -> None:
    """05:1913: *"EXACTLY the eight columns of `route_decision_identity`"*, and the order is the
    digest's input order -- a reordering is a different id for the same decision."""
    assert IDENTITY_FIELDS == (
        "content_sha256",
        "unit_part",
        "lane",
        "rung",
        "policy_digest",
        "pricebook_digest",
        "hints_digest",
        "read_set_digest",
    )
    names = {f.name for f in fields(RouteDecision)}
    assert set(IDENTITY_FIELDS) <= names


def test_decision_id_is_derived_from_the_identity_and_nothing_else() -> None:
    """05:1988: *"DERIVED, which is what makes the insert idempotent under concurrency: two
    `ow ingest` processes computing the same decision converge on one row."*"""
    bare = RouteDecision(**IDENTITY)
    rich = RouteDecision(**IDENTITY, matched=True, reason="x", driver="parse.pdf.pdfium")
    assert bare.decision_id() == rich.decision_id()
    assert bare.decision_id().startswith(DECISION_PREFIX)
    assert len(bare.decision_id()) == len(DECISION_PREFIX) + 24


@pytest.mark.parametrize("field_name", IDENTITY_FIELDS)
def test_every_identity_field_changes_the_id(field_name: str) -> None:
    """The mirror of the test above: the one that catches a field dropped from the digest."""
    moved = dict(IDENTITY)
    moved[field_name] = Rung.PAGE if field_name == "rung" else "moved"
    assert RouteDecision(**moved).decision_id() != RouteDecision(**IDENTITY).decision_id()


def test_the_rung_digests_as_its_name_and_not_its_ordinal() -> None:
    """The ordinal is append-only in SQL and the NAME is what `route_decision.rung` stores
    (05:1216). Digesting the integer would renumber every historical `decision_id` the day the
    ladder gained a member -- a change the stored column is designed to survive."""
    assert dict(RouteDecision(**IDENTITY).identity())["rung"] == "DECODE"


def test_an_unmatched_decision_still_has_an_id() -> None:
    """05:1946 makes `matched = False` the common case -- *"the loop continues and writes no
    row"* -- so the loop unpacks a record rather than an optional, and every field is at default."""
    unmatched = RouteDecision()
    assert unmatched.matched is False
    assert unmatched.decision_id().startswith(DECISION_PREFIX)


def test_not_eligible_is_not_an_outcome() -> None:
    """05:1054: it is a MODIFIER -- *"it excludes **blocks** from the rung without touching the
    part"* -- so it lands in `Modifiers.not_eligible` and never in this field. A five-member
    literal would let a first-match action rule settle a part by excluding some of its blocks."""
    assert set(OUTCOMES) == {"ok", "ok_partial", "refuse", "skip"}
    assert "not_eligible" not in OUTCOMES


def test_four_things_the_table_carries_that_the_type_does_not() -> None:
    """05:1984, each with its own reason: `audit_selected` needs `unit_uri`, which RT2 forbids
    `evaluate()` from seeing; `grant_id` is `admit()` step 3's; `admission` is `admit()`'s verdict;
    `decided_at` exists for humans and retention only."""
    names = {f.name for f in fields(RouteDecision)}
    for absent in ("audit_selected", "grant_id", "admission", "decided_at", "unit_uri"):
        assert absent not in names


def test_the_modifier_family_is_absent_for_a_different_reason() -> None:
    """05:1986: they are a pure function of `(policy_digest, evidence)`, both already in the
    identity, so `ow route explain` recomputes them exactly and they need no column."""
    names = {f.name for f in fields(RouteDecision)}
    for absent in ("render", "max_cost_class", "skip_rungs", "deny_lanes", "admit_lanes"):
        assert absent not in names


# --------------------------------------------------------------------------------------------
# 2. `Modifiers` -- one monoid per key, and the four-at-once case.
# --------------------------------------------------------------------------------------------


def test_max_cost_class_takes_the_minimum_and_defaults_to_the_identity() -> None:
    """05:2001: *"A clamp: it can only lower."* `BILLED_API` is `min`'s identity element under
    `COST_CLASS_ORDER`, not a claim that billing is allowed."""
    assert Modifiers().max_cost_class is CostClass.BILLED_API
    clamped = Modifiers(max_cost_class=CostClass.LOCAL_COMPUTE).merge(Modifiers())
    assert clamped.max_cost_class is CostClass.LOCAL_COMPUTE
    lower = clamped.merge(Modifiers(max_cost_class=CostClass.FREE))
    assert lower.max_cost_class is CostClass.FREE
    assert lower.merge(Modifiers(max_cost_class=CostClass.BILLED_API)).max_cost_class is (
        CostClass.FREE
    )


def test_the_clamp_order_agrees_with_cost_class_order() -> None:
    """The duplication is deliberate -- `drivers.resolve` reaches a `Catalog` and `eval.py` is held
    to purity -- so a test asserts the two orderings agree rather than a comment claiming it."""
    ordered = [CostClass.FREE, CostClass.LOCAL_COMPUTE, CostClass.BILLED_API]
    assert list(COST_CLASS_ORDER) == ordered
    folded = Modifiers(max_cost_class=CostClass.BILLED_API)
    for member in ordered:
        folded = folded.merge(Modifiers(max_cost_class=member))
    assert folded.max_cost_class is CostClass.FREE


def test_a_denial_always_wins_because_it_is_applied_after_every_admission() -> None:
    """05:2003. A caller that unioned and subtracted in the other order would let
    `gate.form-admits-fields` re-admit a lane section 2.3's rule had just denied."""
    mods = Modifiers(admit_lanes=frozenset({"fields"})).merge(
        Modifiers(deny_lanes=frozenset({"fields"}))
    )
    assert mods.lanes(frozenset({"text"})) == frozenset({"text"})
    assert mods.lanes(frozenset({"text", "fields"})) == frozenset({"text"})


def test_render_takes_the_more_expensive_profile() -> None:
    """05:2005. `glyph` is 1384 px on the short edge against `structure`'s 692 (section 4.4's
    `[render.*]`), so the order is fixed by the shipped configuration and not by the name."""
    assert Modifiers(render="structure").merge(Modifiers(render="glyph")).render == "glyph"
    assert Modifiers(render="glyph").merge(Modifiers(render="structure")).render == "glyph"
    assert Modifiers(render="structure").merge(Modifiers()).render == "structure"
    assert Modifiers().merge(Modifiers()).render is None


def test_the_set_valued_keys_union_and_flag_blocks_ors() -> None:
    merged = Modifiers(skip_rungs=frozenset({Rung.REPAIR}), not_eligible=frozenset({1})).merge(
        Modifiers(skip_rungs=frozenset({Rung.REGEN}), not_eligible=frozenset({2}), flag_blocks=True)
    )
    assert merged.skip_rungs == {Rung.REPAIR, Rung.REGEN}
    assert merged.not_eligible == {1, 2}
    assert merged.flag_blocks is True


def test_rule_ids_concatenate_in_file_order_and_are_the_one_non_commutative_key() -> None:
    """`ow route explain` prints them, and a set would lose the order. It is also the only evidence
    that a modifier which contributed nothing fired at all."""
    first = Modifiers(rule_ids=("a",)).merge(Modifiers(rule_ids=("b",)))
    second = Modifiers(rule_ids=("b",)).merge(Modifiers(rule_ids=("a",)))
    assert first.rule_ids == ("a", "b")
    assert second.rule_ids == ("b", "a")
    assert first.admit_lanes == second.admit_lanes  # every other key commutes


def test_four_gate_modifiers_take_effect_on_one_part() -> None:
    """05:1018's case, and the whole reason `then` splits in two: *"the shipped `GATE` block
    contains four rules that must **all** take effect on one part -- two cost clamps, a lane
    admission for forms and a lane admission for a supplied schema -- which a single
    first-match-wins list cannot deliver."*"""
    folded = Modifiers()
    for one in (
        Modifiers(max_cost_class=CostClass.LOCAL_COMPUTE, rule_ids=("gate.watcher-may-not-bill",)),
        Modifiers(max_cost_class=CostClass.LOCAL_COMPUTE, rule_ids=("gate.agent-triggered",)),
        Modifiers(admit_lanes=frozenset({"fields"}), render="structure", rule_ids=("gate.form",)),
        Modifiers(admit_lanes=frozenset({"fields"}), render="structure", rule_ids=("gate.schema",)),
    ):
        folded = folded.merge(one)
    assert folded.max_cost_class is CostClass.LOCAL_COMPUTE
    assert folded.lanes(frozenset({"text"})) == {"text", "fields"}
    assert folded.render == "structure"
    assert len(folded.rule_ids) == 4


# --------------------------------------------------------------------------------------------
# 3. `RouteHints` -- the fields it does not have.
# --------------------------------------------------------------------------------------------


def test_route_hints_has_no_budget_no_egress_and_no_licence_field() -> None:
    """05:2030, in capitals: *"IT HAS NO budget, egress OR licence FIELD, AND THEREFORE CANNOT
    WIDEN ANYTHING. `--allow-cost` is CLI-only for exactly this reason, and the absence IS the
    mechanism: there is nothing to validate at the MCP boundary because there is no field to
    send."* An absence is what a later contributor adds without noticing."""
    names = {f.name for f in fields(RouteHints)}
    for absent in (
        "budget",
        "micros",
        "allow_cost",
        "max_cost_class",
        "bytes_egress",
        "egress",
        "licence",
        "license",
        "grant",
    ):
        assert absent not in names, f"RouteHints grew {absent}, which 05:2030 forbids"


def test_route_hints_is_exactly_the_plans_five_fields() -> None:
    assert [f.name for f in fields(RouteHints)] == [
        "lane",
        "max_rung",
        "prefer_capability",
        "deadline_ms",
        "schema",
    ]


def test_every_hint_defaults_to_none_which_means_the_request_said_nothing() -> None:
    """`None` is *"the request said nothing"* and not *"no limit"*: the merge is a restriction and
    there is no value of any field that raises a ceiling."""
    hints = RouteHints()
    assert all(getattr(hints, f.name) is None for f in fields(RouteHints))
