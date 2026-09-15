"""`omniweave.route.demand` against 05-ingest-and-routing.md section 4.3 and RT4.

**The strongest test here runs section 4.3's own loop.** `_drain()` below is the fifteen lines
printed at 05:1090-1101, with `compute(group) into Evidence` filled by a dict the test supplies --
so the assertions are about the ordering the plan specifies and not about a model of it. Two parts
from section 10.1's 188-page 10-K go through it:

* a clean body part, where `decode.pdf-text-layer` matches on the FREE group and the LOCAL group
  holding `ink.tiles` is never reached. That is INV-13, and the counters read zero;
* a scanned exhibit, where `decode.char_count = 0`, `decode.blank-part-escape` defers on an UNKNOWN
  `ink.tiles`, the LOCAL group is promoted, one raster is rendered and `ink.tiles = 9,240` is above
  `@thresholds.blank_page_tiles = 4`, so the escape does not fire and `decode.no-text-layer` wins.

The difference between the two is **file order and nothing else**, which is 05:3110's own claim:
*"THAT ORDERING IS WHAT MAKES INV-13 TRUE."* D213 is what happens when the printed one-argument
`deferrals_pending(ev)` is taken literally, and it has a test of its own.

`_plan/` is not read here. The shipped policy is a committed file and the two provider
`signals.toml` files are committed too; every number below comes off those.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route import demand as rd
from omniweave.route import evidence as ev
from omniweave.route import policy as rp
from omniweave.route.counters import Counters
from omniweave.route.decision import RouteHints
from omniweave.route.eval import evaluate
from omniweave.route.rung import Rung
from omniweave_ports.types import CostClass

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave.route.decision import Modifiers, RouteDecision

CLEAN_PART: dict[str, Any] = {
    "unit.format": "pdf",
    "unit.bytes": 14_200_000,
    "unit.producer_family": "workiva",
    "corpus.lang": "en",
    "decode.has_text_span": True,
    "decode.char_count": 3180,
    "decode.line_count": 71,
    "decode.cid_ratio": 0.00,
    "decode.replacement_ratio": 0.00,
    "garble.score": 0.02,
    "geometry.overlap_line_frac": 0.06,
    "geometry.ruled_regions": 0,
    "math.font_hit": False,
    "math.part_frac": 0.001,
    "ink.tiles": 9_240,
    "ink.coverage": 0.91,
}
"""Section 10.1's `parts 1-42, 55-176`, keyed by signal. *"164 parts: clean body text."*

`ink.tiles` and `ink.coverage` carry values so the test cannot pass by their being uncomputable:
INV-13 says they are never COMPUTED on this part, which is a claim about the plan's ordering and
not about the provider's availability."""

EXHIBIT: dict[str, Any] = {**CLEAN_PART, "decode.char_count": 0, "ink.tiles": 9_240}
"""Section 10.1's `parts 43-54` -- *"12 scanned exhibits"*, `decode.char_count=0`, and 9,240 of
13,464 tiles inked. 05:3127: *"ink.tiles=9,240 of 13,464 > 4, so the escape does not fire."*"""

_UNAVAILABLE = "no provider serves this format"


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> ev.SignalRegistry:
    """Core's 37 plus pdfium's and officexml's: 53 of section 5.1's 54 keys.

    The fifty-fourth is `layout.class_hist`, whose provider column reads *"none (day 1)"*
    (05:2161) -- so the registry is complete and the absence is the plan's, which is what
    `test_the_one_unregistered_key_is_the_one_the_plan_says_has_no_provider` asserts.
    """
    specs = list(ev.builtin_specs())
    for provider, relative in (
        ("pdfium", "packages/omniweave-pdf/src/omniweave_pdf/signals.toml"),
        ("officexml", "packages/omniweave-office/src/omniweave_office/signals.toml"),
    ):
        raw = (repo_root / relative).read_bytes()
        specs.extend(ev.load_signals(raw, provider=provider, origin=relative))
    return ev.build_registry(specs)


@pytest.fixture(scope="module")
def shipped(registry: ev.SignalRegistry) -> rp.RoutePolicy:
    """Section 4.4's forty rules from the committed file, compiled against the day-one registry."""
    return rp.compile_policy([rp.builtin_layer()], registry=registry)


@pytest.fixture(scope="module")
def demand(shipped: rp.RoutePolicy, registry: ev.SignalRegistry) -> rd.DemandMap:
    return rd.compile_demand(shipped, registry=registry)


def _record(part: str = "p1") -> ev.Evidence:
    return ev.Evidence(content_sha256="a" * 64, unit_part=part)


def _fill(record: ev.Evidence, keys: object, values: dict[str, Any]) -> None:
    """`compute(group) into Evidence` -- a whole group at once, 05:1110's unit."""
    for key in keys:  # type: ignore[attr-defined]
        value = values.get(key)
        if value is None:
            record.put(key, None, provider_version="1.0.0", unavailable_reason=_UNAVAILABLE)
        else:
            record.put(key, value, provider_version="1.0.0")


def _drain(
    policy: rp.RoutePolicy,
    plan: rd.DemandPlan,
    record: ev.Evidence,
    values: dict[str, Any],
    *,
    counters: Counters,
    ceiling: CostClass | None = None,
) -> tuple[RouteDecision, Modifiers, list[rd.Group]]:
    """Section 4.3's inner loop, 05:1095-1101, with `compute()` supplied by `values`.

    ```
    plan = policy.demand[(rung, lane, phase)]
    for group in plan.groups:                       # FREE, then LOCAL_COMPUTE, then BILLED
        compute(group) into Evidence                # route_signal cache first, per (key,ver)
        d, mods = evaluate(policy, ev, hints, rung, lane, phase)   # PURE
        if d.matched and not plan.deferrals_pending(ev): break
    ```

    Two departures, both deliberate and both named where they are made. `deferrals_pending` is
    passed `before=` and `ceiling=` (D213). And a LOCAL_COMPUTE group is charged one `structure`
    raster, which is 05:2290's recipe for `ink.tiles` -- *"Render the part at the `structure`
    profile in grayscale"* -- and is an assumption of THIS TEST rather than a registered fact:
    D214 files that no `SignalSpec` column says a key needs a raster.
    """
    ran: list[rd.Group] = []
    decision, mods = evaluate(policy, record, RouteHints(), plan.rung, plan.lane, plan.phase)
    while True:
        group = plan.next_group(record, ceiling=ceiling)
        if group is None:
            return decision, mods, ran
        ran.append(group)
        _fill(record, group.keys, values)
        for key in group.keys:
            counters.computed(key, unit_part=record.scope[1])
        if group.cost_class is not CostClass.FREE:
            counters.rendered("structure", unit_part=record.scope[1])
        record.clear_read_log()
        decision, mods = evaluate(policy, record, RouteHints(), plan.rung, plan.lane, plan.phase)
        pending = plan.deferrals_pending(record, before=decision.rule_id, ceiling=ceiling)
        if decision.matched and not pending:
            return decision, mods, ran


# --------------------------------------------------------------------------------------------
# 1. INV-13 and RT4, on the plan's own two parts.
# --------------------------------------------------------------------------------------------


def test_a_clean_body_part_never_reaches_the_local_group_and_renders_nothing(
    shipped: rp.RoutePolicy, demand: rd.DemandMap
) -> None:
    """Section 4.3 property 1 and 05:3107's trace line, run rather than restated.

    *"FREE group: `decode.char_count=3180 > 0` -> `decode.pdf-text-layer`. ... the LOCAL group is
    never computed and no raster is rendered."* The three counters are the assertion, because
    05:1153 makes them exact: a deviation of one fails.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record, counters = _record(), Counters()
    decision, _, ran = _drain(shipped, plan, record, CLEAN_PART, counters=counters)

    assert decision.rule_id == "decode.pdf-text-layer"
    assert decision.driver == "parse.pdf.pdfium"
    assert [group.cost_class for group in ran] == [CostClass.FREE]
    assert not record.computed("ink.tiles")
    tally = counters.tally()
    assert tally.page_renders == 0
    assert tally.service_attaches == 0
    assert tally.signal_computations == len(plan.groups[0].keys) == 3


def test_a_scanned_exhibit_promotes_the_local_group_and_pays_for_one_raster(
    shipped: rp.RoutePolicy, demand: rd.DemandMap
) -> None:
    """05:3121, the other half of the same ordering.

    *"`decode.blank-part-escape`'s `ink.tiles` is UNKNOWN, it declares defer, and it is EARLIER
    than `decode.no-text-layer` -> the LOCAL group runs: one 96-DPI grayscale render, 15 ms.
    `ink.tiles=9,240` of 13,464 > 4, so the escape does not fire."*
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record, counters = _record("p43"), Counters()
    decision, _, ran = _drain(shipped, plan, record, EXHIBIT, counters=counters)

    assert [group.cost_class for group in ran] == [CostClass.FREE, CostClass.LOCAL_COMPUTE]
    assert decision.rule_id == "decode.no-text-layer"
    assert decision.escalate_to is Rung.PAGE
    assert record.read("ink.tiles") == 9_240
    tally = counters.tally()
    assert tally.page_renders == 1
    assert tally.signal_computations == 4


def test_the_two_parts_differ_only_in_file_order_of_the_rule_that_matched(
    demand: rd.DemandMap,
) -> None:
    """05:3110: *"THAT ORDERING IS WHAT MAKES INV-13 TRUE."*

    `decode.blank-part-escape` is UNKNOWN and deferring on **both** parts. The only thing that
    differs is whether the rule that matched sits ahead of it, so that is asserted as a position
    in the rule list rather than as a property of the evidence.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    order = list(plan.rule_ids)
    assert order.index("decode.pdf-text-layer") < order.index("decode.blank-part-escape")
    assert order.index("decode.blank-part-escape") < order.index("decode.no-text-layer")

    clean = _record()
    _fill(clean, plan.groups[0].keys, CLEAN_PART)
    assert plan.deferrals_pending(clean, before="decode.pdf-text-layer") == ()
    assert plan.deferrals_pending(clean, before="decode.no-text-layer") == (
        "decode.blank-part-escape",
    )


def test_the_printed_one_argument_call_promotes_the_local_group_on_a_clean_page(
    demand: rd.DemandMap,
) -> None:
    """D213. `plan.deferrals_pending(ev)` is what 05:1099 prints, and it cannot see file order.

    On the clean body part the answer is non-empty, so the section 4.3 loop would not break, the
    LOCAL group would be promoted and a 96-DPI raster would be rendered on every clean born-digital
    page in the corpus -- `page_renders` 188 rather than 13 on section 10.1's document, against a
    counter 01:403 makes exact.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record = _record()
    _fill(record, plan.groups[0].keys, CLEAN_PART)
    assert plan.deferrals_pending(record) == ("decode.blank-part-escape",)
    assert plan.deferrals_pending(record, before="decode.pdf-text-layer") == ()


def test_a_defer_stops_being_pending_once_its_group_has_run(demand: rd.DemandMap) -> None:
    """05:1128: *"Once every group in the plan has been computed, a key that is still UNKNOWN is
    genuinely unavailable ... and the rule's `on_unknown` decides."* At that point `defer` has
    degraded to `skip` and there is nothing left to wait for -- which is also what makes the loop
    terminate without a counter (05:1131)."""
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record = _record()
    for group in plan.groups:
        _fill(record, group.keys, {**CLEAN_PART, "ink.tiles": None})
    assert record.computed("ink.tiles")
    assert record.read("ink.tiles") is None
    assert plan.deferrals_pending(record) == ()


def test_the_gate_clamp_forbids_promoting_a_group_above_the_ceiling(demand: rd.DemandMap) -> None:
    """05:1117's parenthetical: the promotion is *"still ascending, still under the `GATE` clamp"*.

    Enforced here as well as in `admit()` step 1 because step 1 clamps the DRIVER, and a
    `local_compute` signal computed under a `free` clamp has already spent the 15 ms by the time
    any driver is chosen.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record = _record()
    _fill(record, plan.groups[0].keys, EXHIBIT)
    assert plan.next_group(record) is not None
    assert plan.next_group(record, ceiling=CostClass.FREE) is None
    assert plan.deferrals_pending(record, ceiling=CostClass.FREE) == ()


def test_the_settle_phase_escalates_every_clean_page_because_its_only_falsifier_is_local(
    shipped: rp.RoutePolicy, demand: rd.DemandMap
) -> None:
    """D216, as the two measurements that make it. `DECODE` settle, `text` lane, a clean part.

    `decode.part-text-unusable` is first in file order, is an ACTION, and declares
    `on_unknown = "match"`. Its `any_of` has four clauses; three are FREE and false on a clean
    part, and the fourth reads `ink.coverage`, the only LOCAL_COMPUTE key at this phase. Kleene OR
    over `F, F, U, F` is UNKNOWN, so `on_unknown` decides and the rule MATCHES -- escalating a
    clean born-digital page to `parse.page.olmocr` at 854 micros.

    Give it `ink.coverage` and the `any_of` is false and **no action rule matches at all**, so
    section 4.3's loop does not break at the FREE group and the LOCAL group is computed. Either way
    a clean page is not free: 05:1149's *"A clean born-digital page computes zero `LOCAL_COMPUTE`
    signals"* holds at `select` and at neither reading of `settle`.

    05:3117 gets the third answer by calling `decode.skip-block-recheck-on-clean-parts` an
    *"action"*; it is a modifier (`skip_rungs`, 05:1025's modifier family) and a modifier does not
    stop evaluation. And the rule's own comment in the shipped policy, 05:1519, asserts it *"fires
    only after the LOCAL group has actually been computed (4.3)"* -- which nothing makes true,
    because it declares no `defer`.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "settle")
    assert plan.rule_ids[0] == "decode.part-text-unusable"
    assert [group.cost_class for group in plan.groups] == [
        CostClass.FREE,
        CostClass.LOCAL_COMPUTE,
    ]
    assert plan.groups[1].keys == ("ink.coverage",)
    assert plan.deferring == ()

    without = _record()
    _fill(without, plan.groups[0].keys, CLEAN_PART)
    decision, _ = evaluate(shipped, without, RouteHints(), Rung.DECODE, "text", "settle")
    assert decision.matched is True
    assert decision.rule_id == "decode.part-text-unusable"
    assert decision.escalate_to is Rung.PAGE

    withal = _record()
    for group in plan.groups:
        _fill(withal, group.keys, CLEAN_PART)
    settled, _ = evaluate(shipped, withal, RouteHints(), Rung.DECODE, "text", "settle")
    assert settled.matched is False


# --------------------------------------------------------------------------------------------
# 2. The shipped policy's plan, as measured numbers.
# --------------------------------------------------------------------------------------------


def test_the_shipped_policy_compiles_to_fourteen_plans(demand: rd.DemandMap) -> None:
    """Forty rules over seven rungs, five lanes and two phases; 14 of the 70 slots have a rule.

    Asserted as a number because `compile_demand()` stores nothing for an empty slot -- storing the
    empties would put 70 entries in a map whose real size is 14, and `plan_for()` is the lookup
    that makes the loop body uniform without them.
    """
    assert len(demand) == 14
    assert sum(len(plan.rule_ids) for plan in demand.values()) == 40
    assert all(plan.groups for plan in demand.values())


def test_only_three_keys_in_the_whole_registry_are_above_free(
    registry: ev.SignalRegistry,
) -> None:
    """`ink.tiles`, `ink.coverage` and `block.has_ink` -- section 5.1's only LOCAL_COMPUTE rows
    with a provider. `layout.class_hist` is the fourth and has none, which is why it is not here
    and why INV-13's claim is about a group that three keys can put a page into."""
    registered = registry.keys()  # a tuple, not a mapping: SIM118 does not apply
    above = sorted(key for key in registered if registry.cost_class_of(key) is not CostClass.FREE)
    assert above == ["block.has_ink", "ink.coverage", "ink.tiles"]
    assert all(registry.cost_class_of(key) is CostClass.LOCAL_COMPUTE for key in above)


def test_only_the_two_ink_keys_put_a_text_lane_part_above_free(demand: rd.DemandMap) -> None:
    """The `text` lane's whole exposure to `LOCAL_COMPUTE`, at both DECODE phases.

    `block.has_ink` is the third LOCAL key and it is read only by a `REPAIR`-rung rule, so a part
    that never reaches `REPAIR` cannot pay for it -- which is property 2 (05:1155) doing its job
    one rung further along than the lane example it is stated with.
    """
    local = {
        key
        for phase in rd.PHASES
        for group in rd.plan_for(demand, Rung.DECODE, "text", phase).groups
        if group.cost_class is CostClass.LOCAL_COMPUTE
        for key in group.keys
    }
    assert local == {"ink.tiles", "ink.coverage"}


def test_the_gate_rung_has_no_local_group_at_all(demand: rd.DemandMap) -> None:
    """05:3103: *"signals computed: 10 FREE. rasters: 0. services attached: 0."*

    The rasters-zero half is structural rather than evidential: GATE's twelve rules read nine keys
    and every one is FREE, so no evidence can put a unit into a LOCAL group at this rung. The
    counted nine against the trace's ten is D215.
    """
    plan = rd.plan_for(demand, Rung.GATE, "text", "select")
    assert [group.cost_class for group in plan.groups] == [CostClass.FREE]
    assert len(plan.keys) == 9
    assert rd.plan_for(demand, Rung.GATE, "text", "settle").groups == ()


def test_every_key_the_shipped_policy_reads_is_registered(demand: rd.DemandMap) -> None:
    """Check 1 (`OW-P-001`) from the demand plan's side: no plan carries an `unregistered` key.

    The linter reports; this asserts the consequence -- a policy with an unregistered key has a
    rule whose guard can never fire, because nothing can ever compute what it reads.
    """
    assert {key for plan in demand.values() for key in plan.unregistered} == set()


def test_the_one_unregistered_key_is_the_one_the_plan_says_has_no_provider(
    registry: ev.SignalRegistry, shipped: rp.RoutePolicy
) -> None:
    """Section 5.1 tabulates 54 keys; 53 register. The missing one is `layout.class_hist`, whose
    provider column is *"none (day 1)"* (05:2161), and 05:2325 gives the consequence in full --
    *"`layout.class_hist` is absent at release 1 and every decision that would have read it records
    `cause = "layout_unavailable"`"*. No shipped rule reads it, so no plan mentions it either."""
    registered = registry.keys()  # a tuple, not a mapping: SIM118 does not apply
    assert len(registered) == 53
    assert "layout.class_hist" not in registered
    assert all("layout.class_hist" not in rule.when.keys for rule in shipped.rules)


# --------------------------------------------------------------------------------------------
# 3. The type: ordering, grouping, and what a plan refuses.
# --------------------------------------------------------------------------------------------


def test_groups_ascend_by_cost_class_and_empty_classes_are_omitted(demand: rd.DemandMap) -> None:
    """05:1110's *"partitions it by `CostClass`, ascending"*, both halves.

    Ascending is asserted over every plan; omitted-when-empty is asserted by the count, because a
    plan that stored an empty `billed_api` group would make `len(plan.groups)` a wrong answer to
    "how many acquisition rounds does this cost".
    """
    for plan in demand.values():
        ranks = [group.rank for group in plan.groups]
        assert ranks == sorted(ranks)
        assert len(ranks) == len(set(ranks))
        assert all(group.keys for group in plan.groups)


def test_keys_within_a_group_are_sorted(demand: rd.DemandMap) -> None:
    """Within a group there is no order -- it is computed as a whole -- so exposing first-read
    order would make `--explain` depend on which rule happens to be first in the file."""
    for plan in demand.values():
        for group in plan.groups:
            assert list(group.keys) == sorted(group.keys)


def test_a_group_with_no_keys_is_refused() -> None:
    """A group is a unit of computation; an empty one is not a step."""
    with pytest.raises(ValueError, match="not a step"):
        rd.Group(cost_class=CostClass.FREE, keys=())


def test_a_plan_whose_groups_descend_is_refused() -> None:
    with pytest.raises(ValueError, match="ascending run of CostClass"):
        rd.DemandPlan(
            rung=Rung.DECODE,
            lane="text",
            phase="select",
            groups=(
                rd.Group(cost_class=CostClass.LOCAL_COMPUTE, keys=("ink.tiles",)),
                rd.Group(cost_class=CostClass.FREE, keys=("unit.bytes",)),
            ),
        )


def test_a_rung_and_lane_with_no_rule_gets_an_empty_plan_rather_than_none(
    demand: rd.DemandMap,
) -> None:
    """`plan_for()` returns a plan so the section 4.3 loop body needs no branch of its own: an
    empty `groups` makes `next_group()` return `None` on the first call."""
    plan = rd.plan_for(demand, Rung.ENRICH, "caption", "settle")
    assert plan.groups == ()
    assert plan.keys == ()
    assert plan.next_group(_record()) is None
    assert plan.deferrals_pending(_record()) == ()


def test_keys_at_deduplicates_across_the_two_phases(demand: rd.DemandMap) -> None:
    """A key read in both phases is computed once: `route_signal`'s primary key is
    `(content_sha256, unit_part, signal_key, signal_version)`, so the second read is a hit."""
    both = rd.keys_at(demand, Rung.DECODE, "text")
    assert len(both) == len(set(both))
    select = rd.plan_for(demand, Rung.DECODE, "text", "select").keys
    assert both[: len(select)] == select
    assert set(both) == set(select) | set(rd.plan_for(demand, Rung.DECODE, "text", "settle").keys)


def test_computed_through_counts_leading_groups_only(demand: rd.DemandMap) -> None:
    """A group is computed as a WHOLE, so a half-filled one means acquisition is mid-flight or a
    provider raised; either way the next group may not start."""
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record = _record()
    assert plan.computed_through(record) == 0
    record.put("ink.tiles", 5, provider_version="1.0.0")
    assert plan.computed_through(record) == 0
    _fill(record, plan.groups[0].keys, CLEAN_PART)
    assert plan.computed_through(record) == 2


def test_a_bounded_probe_adds_nothing_to_the_read_set_and_an_unbounded_one_does(
    shipped: rp.RoutePolicy, demand: rd.DemandMap
) -> None:
    """`deferrals_pending()` evaluates a `when`, and `When.holds()` reads. The `before=` bound is
    what keeps that invisible to the identity.

    05:1876 requires the `computed()` probe not to go through `read()` and `computed_through()` /
    `next_group()` honour that literally. The Kleene half cannot: deciding whether a rule is
    currently UNKNOWN IS evaluating its `when`, and 05:1868 makes `read()` the only accessor. The
    bound is what makes it harmless -- `before` is the rule that matched, first-match-wins already
    tested every rule ahead of it, and `read_set()` deduplicates at first occurrence, so every key
    a bounded probe touches is already in the log.

    Unbounded, it is not harmless, and that is D213's second consequence: `ink.tiles` enters the
    read set of a clean born-digital page that never computed it, and `read_set_digest` is one of
    `route_decision`'s eight identity columns (05:2665). The decision would be keyed on a signal
    the ordering exists to avoid.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    record = _record()
    _fill(record, plan.groups[0].keys, CLEAN_PART)
    record.clear_read_log()

    decision, _ = evaluate(shipped, record, RouteHints(), Rung.DECODE, "text", "select")
    before = record.read_set()
    assert plan.computed_through(record) == 1
    assert plan.next_group(record) is not None
    assert plan.deferrals_pending(record, before=decision.rule_id) == ()
    assert record.read_set() == before
    assert "ink.tiles" not in [key for key, _, _ in before]

    assert plan.deferrals_pending(record) == ("decode.blank-part-escape",)
    assert "ink.tiles" in [key for key, _, _ in record.read_set()]


# --------------------------------------------------------------------------------------------
# 4. Reachability -- property 5, from the compiler's side.
# --------------------------------------------------------------------------------------------


def test_a_pruned_rule_is_dropped_from_the_plan_and_its_keys_with_it(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    """05:1170: the compiler *"drops it from the demand plan with a recorded
    `Degradation(kind="policy_pruned")`"*. `decode.blank-part-escape` is the only reader of
    `ink.tiles` in the whole policy, so pruning it removes the LOCAL group entirely -- which is
    the shape that makes property 5 a lint rather than an optimisation: a subsumed guard's keys
    stop being computed, and nobody notices unless something reports it."""
    pruned = rd.compile_demand(shipped, registry=registry, pruned=["decode.blank-part-escape"])
    plan = rd.plan_for(pruned, Rung.DECODE, "text", "select")
    assert "decode.blank-part-escape" not in plan.rule_ids
    assert plan.pruned == ("decode.blank-part-escape",)
    assert [group.cost_class for group in plan.groups] == [CostClass.FREE]
    assert "ink.tiles" not in plan.keys
    assert "decode.blank-part-escape" not in plan.deferrals_pending(_record())


def test_pruning_nothing_is_the_default_and_ow_route_lint_needs_it(
    shipped: rp.RoutePolicy, demand: rd.DemandMap, registry: ev.SignalRegistry
) -> None:
    """A plan that already dropped the subsumed rules cannot be asked whether dropping them
    changed anything, which is why `pruned` defaults to `()` rather than to the linter's output."""
    assert rd.reachable(shipped) == shipped.rules
    assert len(rd.compile_demand(shipped, registry=registry)) == len(demand)


def test_render_names_the_pruned_and_unregistered_sets_even_though_they_are_not_groups(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    """`ow route lint --explain` (05:1143) prints a rule's derived phase and read set. A reader
    whose guard did not fire needs to see the two reasons a key is in no group."""
    pruned = rd.compile_demand(shipped, registry=registry, pruned=["decode.blank-part-escape"])
    lines = rd.plan_for(pruned, Rung.DECODE, "text", "select").render()
    assert lines[0].startswith("DECODE/text/select")
    assert any("free:" in line for line in lines)
    assert any("pruned (OW-P-011" in line for line in lines)
