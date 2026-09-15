"""`omniweave.route.eval` against 05-ingest-and-routing.md sections 4.2, 4.3 and 4.6.

**The load-bearing test in this file is `test_a_clean_born_digital_page_reads_exactly_five_keys`.**
Section 4.3 property 1 is INV-13 as a number -- *"A clean born-digital page computes zero
`LOCAL_COMPUTE` signals"*, and *"a clean born-digital part writes five"* `route_signal` rows
(05:2362). That number is a claim about the interaction of first-match-wins, the derived phase and
the read log, and it is reproducible only against the plan's own forty-rule policy. It is five.

The second is RT1: `evaluate()` is pure, so evaluating the same evidence twice -- in either order,
from either of two records built the same way -- returns the same decision and the same
`decision_id`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route import evidence as ev
from omniweave.route import policy as rp
from omniweave.route.decision import Modifiers, RouteHints
from omniweave.route.eval import PHASES, SLICE_UNAVAILABLE, evaluate, pending_deferrals, slice_key
from omniweave.route.rung import Rung
from omniweave_ports.types import CostClass

if TYPE_CHECKING:
    from pathlib import Path

CLEAN_PDF: dict[str, Any] = {
    "unit.format": "pdf",
    "unit.encrypted": False,
    "unit.corrupt": False,
    "unit.bytes": 1_200_000,
    "unit.part_count": 42,
    "unit.schema_requested": False,
    "trigger.kind": "cli",
    "unit.producer_family": "workiva",
    "decode.has_text_span": True,
    "corpus.lang": "en",
    "decode.char_count": 3100,
}


def _ev(**over: Any) -> ev.Evidence:
    record = ev.Evidence(content_sha256="a" * 64, unit_part="p1")
    for key, value in {**CLEAN_PDF, **over}.items():
        record.put(key, value, provider_version="1.0.0")
    return record


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


@pytest.fixture(scope="module")
def shipped(plan: Any, registry: ev.SignalRegistry) -> rp.RoutePolicy:
    """Section 4.4's forty rules, compiled against the day-one registry."""
    plan.require()
    for body in plan.fences("05-ingest-and-routing.md", "toml"):
        if 'policy_name    = "builtin:balanced"' in body:
            layer = rp.load_layer(body.encode(), layer="builtin", origin="05 section 4.4")
            return rp.compile_policy([layer], registry=registry)
    pytest.skip("05 section 4.4's policy fence is not in this checkout")


# --------------------------------------------------------------------------------------------
# 1. INV-13, as a number.
# --------------------------------------------------------------------------------------------


def test_a_clean_born_digital_page_reads_exactly_five_keys(shipped: rp.RoutePolicy) -> None:
    """Section 4.3 property 1, reproduced. *"At `DECODE`'s select phase in the `text` lane the FREE
    group yields `unit.format = "pdf"` and `decode.char_count > 0`; `decode.pdf-text-layer` matches
    with no earlier deferring rule; the `LOCAL_COMPUTE` group holding `ink.tiles` is never
    reached."*

    The five are the four `[slice] by` axes plus `decode.char_count`, and `unit.format` is both a
    slice axis and the key the winning rule reads. `ink.tiles` is not among them, which is the
    whole of INV-13: a clean page computes zero `LOCAL_COMPUTE` signals.
    """
    record = _ev()
    decision, _ = evaluate(shipped, record, RouteHints(), Rung.DECODE, "text", "select")
    read = [key for key, _, _ in record.read_set()]
    assert decision.rule_id == "decode.pdf-text-layer"
    assert decision.driver == "parse.pdf.pdfium"
    assert read == [
        "unit.format",
        "unit.producer_family",
        "decode.has_text_span",
        "corpus.lang",
        "decode.char_count",
    ]
    assert "ink.tiles" not in read
    assert "ink.coverage" not in read


def test_later_action_rules_are_not_tested_so_their_keys_stay_out_of_the_identity(
    shipped: rp.RoutePolicy,
) -> None:
    """05:1023's *"not tested"* is stronger than *"does not win"*, and `read_set_digest` is why:
    merely declining to let a later action rule win would still evaluate its `when`, which reads
    its keys, which puts them in an IDENTITY column."""
    record = _ev()
    evaluate(shipped, record, RouteHints(), Rung.DECODE, "text", "select")
    read = {key for key, _, _ in record.read_set()}
    # `decode.blank-part-escape` is a later action rule at the same (rung, lane, phase).
    assert "ink.tiles" not in read


def test_a_pure_modifier_behind_the_action_still_contributes(shipped: rp.RoutePolicy) -> None:
    """The other half of the same sentence: *"every matching rule contributes"* (05:1024).
    `decode.admit-table-lane` is a pure modifier and carries its own comment saying so -- *"it
    admits a lane and takes no action, so it coexists with whichever action rule above fired."*"""
    record = _ev(**{"geometry.ruled_regions": 3, "garble.score": 0.01, "block.flagged_frac": 0.0})
    decision, mods = evaluate(shipped, record, RouteHints(), Rung.DECODE, "text", "settle")
    assert "table" in mods.lanes(frozenset({"text"}))
    assert "decode.admit-table-lane" in mods.rule_ids
    assert decision.matched is False or decision.rule_id != "decode.admit-table-lane"


# --------------------------------------------------------------------------------------------
# 2. RT1 -- purity, as behaviour and as an import list.
# --------------------------------------------------------------------------------------------


def test_the_same_evidence_evaluates_the_same_way_twice(shipped: rp.RoutePolicy) -> None:
    """RT1. Two records built the same way, evaluated in two orders, give one decision id."""
    first, second = _ev(), _ev()
    a, _ = evaluate(shipped, first, RouteHints(), Rung.DECODE, "text", "select")
    b, _ = evaluate(shipped, second, RouteHints(), Rung.DECODE, "text", "select")
    assert a == b
    assert a.decision_id() == b.decision_id()

    third = _ev()
    again, _ = evaluate(shipped, third, RouteHints(), Rung.DECODE, "text", "select")
    assert again.decision_id() == a.decision_id()


def test_eval_imports_nothing_that_could_read_the_machine(repo_root: Path) -> None:
    """The import set as a pinned literal -- the assertion that catches a future edit.

    05:1820 names five bans for this module: `time.`, `random.`, `os.environ`, `importlib` and
    `open(`. The semgrep bank enforces the first two and `importlib` (through
    `omniweave-no-ambient-input-in-purity-islands` and the two import rules), and it cannot be
    extended to the other two without claiming 02-architecture.md:392 ordered something it did not
    -- `test_the_bank_carries_no_rule_the_plan_did_not_order` is that lock. D206 files the gap; this
    test is the enforcement W5.2 can honestly ship.
    """
    source = (repo_root / "packages/omniweave/src/omniweave/route/eval.py").read_text("utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    calls: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            attributes.add(f"{node.value.id}.{node.attr}")
    assert roots == {"__future__", "dataclasses", "typing", "omniweave"}
    for banned in ("time", "random", "os", "importlib", "pathlib", "sqlite3", "asyncio"):
        assert banned not in roots
    # The AST and not a substring search: this module's own docstring QUOTES 05:1820's ban list,
    # so a `"open(" not in source` would fail on the sentence that documents the ban.
    assert "open" not in calls
    assert "os.environ" not in attributes


# --------------------------------------------------------------------------------------------
# 3. The shipped policy, rung by rung.
# --------------------------------------------------------------------------------------------


def test_gate_refuses_a_zero_byte_file(shipped: rp.RoutePolicy) -> None:
    decision, _ = evaluate(
        shipped, _ev(**{"unit.format": "empty"}), RouteHints(), Rung.GATE, "text", "select"
    )
    assert (decision.rule_id, decision.outcome, decision.failure_class) == (
        "gate.empty",
        "refuse",
        "corrupt_input",
    )
    assert decision.reason == "zero-byte-file"
    assert decision.driver == ""  # 05:1952: a GATE refusal writes a row with driver = ''


def test_a_watch_trigger_clamps_the_cost_class_without_taking_an_action(
    shipped: rp.RoutePolicy,
) -> None:
    """*"graphify watch.py: FREE runs now, LOCAL_COMPUTE within headroom, BILLED_API never."*"""
    decision, mods = evaluate(
        shipped, _ev(**{"trigger.kind": "watch"}), RouteHints(), Rung.GATE, "text", "select"
    )
    assert decision.matched is False
    assert mods.max_cost_class is CostClass.LOCAL_COMPUTE
    assert mods.rule_ids == ("gate.watcher-may-not-bill",)


def test_an_mcp_trigger_takes_the_same_clamp_from_a_different_rule(
    shipped: rp.RoutePolicy,
) -> None:
    """*"An `ow_add` arriving over MCP or the SDK is not the cost consent a human gave by
    typing."* `ow add --allow-cost <micros>` is the approval path, and it is CLI-only because
    `RouteHints` correctly has no budget field."""
    _, mods = evaluate(
        shipped, _ev(**{"trigger.kind": "mcp"}), RouteHints(), Rung.GATE, "text", "select"
    )
    assert mods.max_cost_class is CostClass.LOCAL_COMPUTE
    assert mods.rule_ids == ("gate.agent-triggered-may-not-bill",)


def test_a_supplied_schema_admits_the_fields_lane(shipped: rp.RoutePolicy) -> None:
    _, mods = evaluate(
        shipped,
        _ev(**{"unit.schema_requested": True}),
        RouteHints(),
        Rung.GATE,
        "text",
        "select",
    )
    assert "fields" in mods.lanes(frozenset({"text"}))
    assert mods.render == "structure"


def test_an_office_document_settles_at_decode_and_is_terminal(shipped: rp.RoutePolicy) -> None:
    """*"terminal = true STOPS EVALUATION"*, and office/text is the `terminal? = yes` row of
    section 3's ladder."""
    decision, _ = evaluate(
        shipped, _ev(**{"unit.format": "docx"}), RouteHints(), Rung.DECODE, "text", "select"
    )
    assert decision.rule_id == "decode.office-native"
    assert decision.driver == "parse.office.anydoc"
    assert decision.terminal is True


def test_a_page_with_no_text_layer_escalates_to_page_at_the_glyph_profile(
    shipped: rp.RoutePolicy,
) -> None:
    decision, mods = evaluate(
        shipped,
        _ev(**{"decode.char_count": 0, "decode.has_text_span": False}),
        RouteHints(),
        Rung.DECODE,
        "text",
        "select",
    )
    assert decision.rule_id == "decode.no-text-layer"
    assert decision.escalate_to is Rung.PAGE
    assert decision.driver == "parse.page.olmocr"
    assert mods.render == "glyph"


def test_a_garbled_page_escalates_and_records_the_clause_that_fired(
    shipped: rp.RoutePolicy,
) -> None:
    """`cause_from = "when"` -- 05:1974's *"a GENERATED string, so 'why it escalated' is a
    `GROUP BY` and not a log grep"*."""
    decision, _ = evaluate(
        shipped,
        _ev(
            **{
                "garble.score": 0.71,
                "ink.coverage": 0.9,
                "decode.line_count": 40,
                "geometry.overlap_line_frac": 0.1,
            }
        ),
        RouteHints(),
        Rung.DECODE,
        "text",
        "settle",
    )
    assert decision.rule_id == "decode.part-text-unusable"
    assert decision.cause == "garble.score=0.71>=0.5"
    assert decision.escalate_to is Rung.PAGE


# --------------------------------------------------------------------------------------------
# 4. `on_unknown`, `max_rung` and `slice_key`.
# --------------------------------------------------------------------------------------------


def test_on_unknown_match_fires_the_rule_and_skip_does_not(shipped: rp.RoutePolicy) -> None:
    """`decode.part-text-unusable` declares `match`, and every one of its keys is UNKNOWN on a
    record that computed none of them -- which is the DOCX case its comment names."""
    blind = _ev()
    decision, _ = evaluate(shipped, blind, RouteHints(), Rung.DECODE, "text", "settle")
    assert decision.rule_id == "decode.part-text-unusable"

    fine = _ev(
        **{
            "garble.score": 0.01,
            "ink.coverage": 0.9,
            "decode.line_count": 40,
            "geometry.overlap_line_frac": 0.1,
            "decode.cid_ratio": 0.0,
            "decode.replacement_ratio": 0.0,
        }
    )
    decision, _ = evaluate(shipped, fine, RouteHints(), Rung.DECODE, "text", "settle")
    assert decision.rule_id != "decode.part-text-unusable"


def test_max_rung_suppresses_an_escalation_and_never_redirects_it(
    shipped: rp.RoutePolicy,
) -> None:
    """05:2024. A suppressed escalation is `None` and not the ceiling: escalating TO the ceiling
    would run a rung the policy did not choose, which is a different decision rather than a
    restricted one."""
    record = _ev(**{"decode.char_count": 0, "decode.has_text_span": False})
    capped, _ = evaluate(
        shipped, record, RouteHints(max_rung=Rung.DECODE), Rung.DECODE, "text", "select"
    )
    assert capped.rule_id == "decode.no-text-layer"
    assert capped.escalate_to is None

    allowed, _ = evaluate(
        shipped,
        _ev(**{"decode.char_count": 0, "decode.has_text_span": False}),
        RouteHints(max_rung=Rung.ENRICH),
        Rung.DECODE,
        "text",
        "select",
    )
    assert allowed.escalate_to is Rung.PAGE


def test_the_slice_key_is_the_plans_own_rendering(shipped: rp.RoutePolicy) -> None:
    """05:1206: *"`pdf/workiva/true/en`, `docx/~/true/de`"* -- a bool renders LOWER-CASE, which is
    the plan's spelling and not Python's."""
    assert slice_key(shipped, _ev()) == "pdf/workiva/true/en"
    record = ev.Evidence(content_sha256="b" * 64)
    for key, value in {
        "unit.format": "docx",
        "decode.has_text_span": True,
        "corpus.lang": "de",
    }.items():
        record.put(key, value, provider_version="1.0.0")
    record.put(
        "unit.producer_family", None, provider_version="1.0.0", unavailable_reason="no field"
    )
    assert slice_key(shipped, record) == f"docx/{SLICE_UNAVAILABLE}/true/de"


def test_the_clean_page_is_clean_because_the_deferring_rule_is_not_earlier(
    shipped: rp.RoutePolicy,
) -> None:
    """05:1121, the sentence that makes INV-13 hold, checked against the shipped file order.

    *"`decode.pdf-text-layer` precedes `decode.blank-part-escape` in file order, so on a clean page
    there is no earlier deferring rule and the LOCAL group is never touched."*

    `decode.blank-part-escape` IS a deferring rule and its keys ARE unknown on a clean page -- it
    reads `ink.tiles`, which is `LOCAL_COMPUTE`. What makes the page cheap is not that no rule
    defers, it is that the one that does sits BELOW the rule that matched. Both halves are asserted
    here, because a policy edit that moved the two rules past each other would silently make every
    clean page pay 15 ms for a raster.
    """
    record = _ev()
    assert pending_deferrals(shipped, record, Rung.DECODE, "text", "select") == (
        "decode.blank-part-escape",
    )
    assert (
        pending_deferrals(
            shipped, record, Rung.DECODE, "text", "select", before="decode.pdf-text-layer"
        )
        == ()
    )


def test_a_defer_rule_is_pending_while_its_keys_are_unknown() -> None:
    """The mechanism, on a policy that declares one -- because the shipped forty do not."""
    raw = (
        b'surface = "route"\n\n[[rule]]\nid = "a.defer"\nrung = "DECODE"\non_unknown = "defer"\n'
        b'when = { "ink.coverage" = { lt = 0.25 } }\nthen = { escalate_to = "PAGE" }\n\n'
        b'[[rule]]\nid = "b.cheap"\nrung = "DECODE"\non_unknown = "skip"\n'
        b'when = { "decode.char_count" = { gt = 0 } }\nthen = { driver = "parse.pdf.pdfium" }\n'
    )
    policy = rp.compile_policy([rp.load_layer(raw, layer="builtin", origin="a test")])
    blind = _ev()
    assert pending_deferrals(policy, blind, Rung.DECODE, "text", "select") == ("a.defer",)
    assert pending_deferrals(policy, blind, Rung.DECODE, "text", "select", before="a.defer") == ()

    computed = _ev(**{"ink.coverage": 0.9})
    assert pending_deferrals(policy, computed, Rung.DECODE, "text", "select") == ()


def test_a_deferring_rule_does_not_fire_from_inside_one_call() -> None:
    """`defer` is not `match`: it does not fire here, and the loop promotes the group instead."""
    raw = (
        b'surface = "route"\n\n[[rule]]\nid = "a.defer"\nrung = "DECODE"\non_unknown = "defer"\n'
        b'when = { "ink.coverage" = { lt = 0.25 } }\nthen = { escalate_to = "PAGE" }\n'
    )
    policy = rp.compile_policy([rp.load_layer(raw, layer="builtin", origin="a test")])
    decision, _ = evaluate(policy, _ev(), RouteHints(), Rung.DECODE, "text", "select")
    assert decision.matched is False


def test_an_unknown_phase_is_a_programming_error() -> None:
    policy = rp.compile_policy(
        [rp.load_layer(b'surface = "route"\n', layer="builtin", origin="a test")]
    )
    assert PHASES == ("select", "settle")
    with pytest.raises(ValueError, match="settling"):
        evaluate(policy, _ev(), RouteHints(), Rung.GATE, "text", "settling")


def test_an_unmatched_call_still_returns_a_policy_stamped_decision() -> None:
    """The loop treats the return value uniformly rather than unpacking an optional, so the
    digest fields are filled even when nothing matched."""
    policy = rp.compile_policy(
        [rp.load_layer(b'surface = "route"\n', layer="builtin", origin="a test")]
    )
    decision, mods = evaluate(policy, _ev(), RouteHints(), Rung.GATE, "text", "select")
    assert decision.matched is False
    assert decision.policy_digest == policy.policy_digest
    assert decision.rung is Rung.GATE
    assert mods == Modifiers()
