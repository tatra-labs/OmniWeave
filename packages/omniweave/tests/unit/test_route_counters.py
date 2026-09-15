"""`omniweave.route.counters` against INV-13, 05 section 4.3 and 13-quality.md section 2.8.

Two halves. The first is the instrument: three sets, each keyed on the cache key its own subsystem
is keyed on, so a repeat is a member already present and the count cannot drift by one for any of
the reasons a running sum can. The second is the numbers -- section 10.1's 188-page 10-K driven
part by part through section 4.3's loop, with the counters read off the end.

**The document's `select`-phase numbers come out and its `settle`-phase numbers cannot**, and the
second half of that sentence is D216 rather than a gap in this file. At `DECODE`'s settle phase in
the `text` lane no action rule matches a clean born-digital part on the FREE group, so the loop
either fires `decode.part-text-unusable`'s `on_unknown = "match"` on an UNKNOWN `ink.coverage` and
escalates the page to a VLM, or computes the LOCAL group and renders the raster INV-13 forbids.
The tests below assert what the shipped policy and the shipped `evaluate()` actually do, with the
plan's own printed number beside each one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route import counters as rc
from omniweave.route import demand as rd
from omniweave.route import evidence as ev
from omniweave.route import policy as rp
from omniweave.route.decision import RouteHints
from omniweave.route.eval import evaluate
from omniweave.route.rung import Rung
from omniweave_ports.types import CostClass
from test_route_demand import CLEAN_PART, EXHIBIT  # the same two parts, single-homed

if TYPE_CHECKING:
    from pathlib import Path

_UNAVAILABLE = "no provider serves this format"

GATE_VALUES: dict[str, Any] = {
    "unit.format": "pdf",
    "unit.format_basis": "magic",
    "unit.bytes": 14_200_000,
    "unit.encrypted": False,
    "unit.corrupt": False,
    "unit.part_count": 188,
    "unit.schema_requested": False,
    "trigger.kind": "cli",
    "corpus.is_form": False,
}
"""Section 10.1's GATE line (05:3095), less the two keys no GATE rule reads.

The trace prints nine values -- `unit.format`, `format_basis`, `bytes`, `encrypted`, `corrupt`,
`part_count`, `producer_family`, `trigger.kind` and `trust_class`. `unit.producer_family` is a
`[slice] by` axis and `unit.trust_class` is the sampler's, and neither is in any demand plan; the
two here that the trace does not print, `corpus.is_form` and `unit.schema_requested`, are read by
GATE modifier rules. D215."""


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> ev.SignalRegistry:
    specs = list(ev.builtin_specs())
    for provider, relative in (
        ("pdfium", "packages/omniweave-pdf/src/omniweave_pdf/signals.toml"),
        ("officexml", "packages/omniweave-office/src/omniweave_office/signals.toml"),
    ):
        specs.extend(
            ev.load_signals((repo_root / relative).read_bytes(), provider=provider, origin=relative)
        )
    return ev.build_registry(specs)


@pytest.fixture(scope="module")
def shipped(registry: ev.SignalRegistry) -> rp.RoutePolicy:
    return rp.compile_policy([rp.builtin_layer()], registry=registry)


@pytest.fixture(scope="module")
def demand(shipped: rp.RoutePolicy, registry: ev.SignalRegistry) -> rd.DemandMap:
    return rd.compile_demand(shipped, registry=registry)


# --------------------------------------------------------------------------------------------
# 1. The instrument. Three sets, three cache keys.
# --------------------------------------------------------------------------------------------


def test_a_repeated_computation_is_not_a_second_computation() -> None:
    """The whole reason the counter is a set. `route_signal` is keyed
    `(content_sha256, unit_part, signal_key, signal_version)` (05:2345), so the second read of a
    computed signal is a cache hit -- and an acquirer that called this on every read, hit or miss,
    still gets an exact count."""
    counters = rc.Counters()
    assert counters.computed("garble.score", unit_part="p1") is True
    assert counters.computed("garble.score", unit_part="p1") is False
    assert counters.tally().signal_computations == 1


def test_the_same_key_on_two_parts_is_two_computations() -> None:
    counters = rc.Counters()
    counters.computed("garble.score", unit_part="p1")
    counters.computed("garble.score", unit_part="p2")
    assert counters.tally().signal_computations == 2


def test_a_unit_scoped_key_is_counted_once_for_the_whole_unit() -> None:
    """`unit_part = ''` is the unit grain. 05:2659 spells the column and its reason in one
    comment: *"'' folds NULL (NULLs are distinct in a UNIQUE)"*. So `unit.format`, computed once at
    GATE, is one computation and not one per part -- a 188-page document does not report 188."""
    counters = rc.Counters()
    counters.computed("unit.format")
    counters.computed("unit.format")
    assert counters.tally().signal_computations == 1


def test_a_part_rasterised_at_two_profiles_is_two_renders() -> None:
    """One raster per profile per part -- the key `cache_index` layer `render` uses (05:2356). A
    part rasterised at `structure` for `ink.tiles` and again at `glyph` for a `PAGE` driver is two
    images, so it is two renders."""
    counters = rc.Counters()
    assert counters.rendered("structure", unit_part="p43") is True
    assert counters.rendered("glyph", unit_part="p43") is True
    assert counters.rendered("structure", unit_part="p43") is False
    assert counters.tally().page_renders == 2


def test_a_profile_outside_the_two_is_refused() -> None:
    """05:907 declares `[render.structure]` and `[render.glyph]` and `Modifiers.render` is typed to
    exactly those, so a third spelling is a typo that would make the count one too high."""
    with pytest.raises(ValueError, match="not a render profile"):
        rc.Counters().rendered("thumbnail")


def test_a_service_is_counted_once_per_run_however_many_calls_it_serves() -> None:
    """05:2474: the model load is *"paid once per run ... Charging it per decision double-counts
    it; charging it per sequence under-counts the unsequenced case."* Section 10.1 makes 14
    `parse.page.olmocr` calls and reports *"services attached: 1."*"""
    counters = rc.Counters()
    for _ in range(14):
        counters.attached("model:olmocr")
    assert counters.tally().service_attaches == 1


def test_an_attach_with_no_service_id_is_refused() -> None:
    with pytest.raises(ValueError, match="no service id"):
        rc.Counters().attached("")


def test_computed_all_returns_how_many_were_new() -> None:
    counters = rc.Counters()
    assert counters.computed_all(("a.b", "c.d"), unit_part="p1") == 2
    assert counters.computed_all(("a.b", "e.f"), unit_part="p1") == 1
    assert counters.tally().signal_computations == 3


# --------------------------------------------------------------------------------------------
# 2. The reading, and what `exact` means arithmetically.
# --------------------------------------------------------------------------------------------


def test_the_tolerance_is_zero_and_any_delta_is_a_mismatch() -> None:
    """13:307: *"Counters are `exact` by default (±1 fails) or `ratchet` with a tolerance"*. A
    tolerance of zero and a `±1` that fails are one statement; this is the arithmetic one."""
    assert rc.EXACT == 0
    observed = rc.Tally(page_renders=14, service_attaches=1, signal_computations=940)
    expected = rc.Tally(page_renders=13, service_attaches=1, signal_computations=940)
    findings = rc.compare(observed, expected)
    assert [finding.counter for finding in findings] == ["page_renders"]
    assert findings[0].delta == 1
    assert "any delta fails" in findings[0].render()


def test_a_counter_that_went_down_is_reported_too() -> None:
    """13:302's case read backwards: *"a silent re-render, a re-billed free operator and a 100%
    cache miss all leave a clock untouched."* A render count that fell while a signal count rose is
    exactly that shape, and clamping the delta at zero would hide it."""
    findings = rc.compare(rc.Tally(page_renders=0), rc.Tally(page_renders=13))
    assert findings[0].delta == -13
    assert (rc.Tally(page_renders=0) - rc.Tally(page_renders=13)).page_renders == -13


def test_compare_reports_every_counter_that_moved_not_only_the_first() -> None:
    """A run that moved two counters should say so once; a gate that stopped at the first would
    take two CI rounds to show the same information."""
    findings = rc.compare(rc.Tally(1, 1, 1), rc.Tally(0, 0, 0))
    assert [finding.counter for finding in findings] == list(rc.COUNTERS)


def test_only_narrows_and_a_name_outside_the_three_raises() -> None:
    """`--check page_renders,service_attaches,signal_computations` (16-roadmap.md:635) takes a
    subset. A typo that quietly checked nothing would be a green gate that tested nothing."""
    moved = rc.Tally(page_renders=1, signal_computations=1)
    assert len(rc.compare(moved, rc.Tally(), only=["page_renders"])) == 1
    assert rc.compare(moved, rc.Tally(), only=[]) == ()
    with pytest.raises(KeyError, match="is not one of"):
        rc.Tally().get("gpu_ms")


def test_the_closed_set_is_three_in_the_order_the_cli_names_them() -> None:
    """13:308: *"The charter's sixteen rows stand unchanged and this document adds none."*"""
    assert rc.COUNTERS == ("page_renders", "service_attaches", "signal_computations")
    assert rc.Tally(1, 2, 3).render() == ("page_renders=1 service_attaches=2 signal_computations=3")


# --------------------------------------------------------------------------------------------
# 3. The numbers, on section 10.1's document.
# --------------------------------------------------------------------------------------------


def _unit_record(registry: ev.SignalRegistry, part: str = "") -> ev.Evidence:
    record = ev.Evidence(content_sha256="a" * 64, unit_part=part)
    for key, value in GATE_VALUES.items():
        if registry.specs_for(key)[0].scope in {"unit", "doc"}:
            record.put(key, value, provider_version="1.0.0")
    return record


def _grain(registry: ev.SignalRegistry, key: str, part: str) -> str:
    specs = registry.specs_for(key)
    return "" if specs and specs[0].scope in {"unit", "doc"} else part


def _drain(
    policy: rp.RoutePolicy,
    registry: ev.SignalRegistry,
    plan: rd.DemandPlan,
    record: ev.Evidence,
    values: dict[str, Any],
    *,
    counters: rc.Counters,
) -> Any:
    """Section 4.3's loop (05:1095-1101), with the grain of each computation taken from `scope`."""
    part = record.scope[1]
    decision, _ = evaluate(policy, record, RouteHints(), plan.rung, plan.lane, plan.phase)
    while True:
        group = plan.next_group(record)
        if group is None:
            return decision
        for key in group.keys:
            value = None if registry.resolve(key, "pdf") is None else values.get(key)
            if value is None:
                record.put(key, None, provider_version="1.0.0", unavailable_reason=_UNAVAILABLE)
                continue
            record.put(key, value, provider_version="1.0.0")
            counters.computed(key, unit_part=_grain(registry, key, part))
        if group.cost_class is not CostClass.FREE:
            counters.rendered("structure", unit_part=part)
        record.clear_read_log()
        decision, _ = evaluate(policy, record, RouteHints(), plan.rung, plan.lane, plan.phase)
        if decision.matched and not plan.deferrals_pending(record, before=decision.rule_id):
            return decision


def test_the_gate_rung_computes_nine_signals_and_renders_nothing(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry, demand: rd.DemandMap
) -> None:
    """05:3103 prints *"signals computed: 10 FREE. rasters: 0. services attached: 0."* and
    05:3185 prints the same three for the DOCX. The two zeroes come out; the ten is nine.

    The difference is the two keys the trace's own line names that no GATE rule reads --
    `unit.producer_family`, a `[slice] by` axis, and `unit.trust_class`, whose comment in the
    shipped policy at 05:1302 reads *"applied by the SAMPLER from unit.trust_class, not by a
    rule"*. Both are read once per decision and neither is in any demand plan, which is D215.
    Counting them would give eleven, not ten.
    """
    counters = rc.Counters()
    plan = rd.plan_for(demand, Rung.GATE, "text", "select")
    record = ev.Evidence(content_sha256="a" * 64, unit_part="")
    decision = _drain(shipped, registry, plan, record, GATE_VALUES, counters=counters)

    assert decision.matched is False
    tally = counters.tally()
    assert tally.signal_computations == 9
    assert tally.page_renders == 0
    assert tally.service_attaches == 0
    assert rc.predicted(plan, plan.groups) == 9


def test_the_select_phase_of_the_whole_document_renders_twelve_rasters(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry, demand: rd.DemandMap
) -> None:
    """GATE, then 188 parts through `DECODE`'s select phase, on one `Counters`.

    Section 10.1's document total at 05:3166 reads *"signals: 188 x ~5 FREE, plus 13 LOCAL
    renders.  services attached: 1."* Twelve of the thirteen renders are here -- parts 43-54, one
    `structure` raster each, asserted by name rather than by count. The thirteenth
    is part 177's, which the trace puts at the SETTLE phase over `ink.coverage`, and the settle
    phase does not behave as the trace prints: D216.

    `signal_computations` is **209**: nine unit-scoped keys at GATE, then `decode.char_count` for
    each of 188 parts, then `ink.tiles` for each of the twelve exhibits. `unit.bytes` and
    `unit.format` are in the select FREE group too and add nothing, because they are unit-scoped
    and GATE already computed them -- which is the set's whole point. The trace's `188 x ~5` counts
    the read set instead, three of whose five are `[slice] by` axes that no demand plan contains
    (D215).
    """
    counters = rc.Counters()
    gate = rd.plan_for(demand, Rung.GATE, "text", "select")
    _drain(
        shipped,
        registry,
        gate,
        ev.Evidence(content_sha256="a" * 64),
        GATE_VALUES,
        counters=counters,
    )

    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    escalated: list[str] = []
    for index in range(1, 189):
        part = f"p{index}"
        values = EXHIBIT if 43 <= index <= 54 else CLEAN_PART
        record = _unit_record(registry, part)
        decision = _drain(shipped, registry, plan, record, values, counters=counters)
        if decision.matched and decision.escalate_to is Rung.PAGE:
            escalated.append(part)
    counters.attached("model:olmocr")

    assert escalated == [f"p{index}" for index in range(43, 55)]
    tally = counters.tally()
    assert tally.page_renders == 12
    assert tally.service_attaches == 1
    assert tally.signal_computations == 9 + 188 + 12 == 209


def test_predicted_counts_signals_and_says_nothing_about_the_other_two(
    demand: rd.DemandMap,
) -> None:
    """The one derivation, and its boundary.

    `signal_computations` follows from which groups ran because a group is computed as a whole
    (05:1110). `page_renders` does not: no `SignalSpec` column says computing `ink.tiles` needs a
    raster, and `predicted()` has nothing to read. D214.
    """
    plan = rd.plan_for(demand, Rung.DECODE, "text", "select")
    assert rc.predicted(plan, ()) == 0
    assert rc.predicted(plan, plan.groups[:1]) == 3
    assert rc.predicted(plan, plan.groups) == 4
    assert rc.predicted(plan, (*plan.groups, *plan.groups)) == 4
    assert not hasattr(rc, "predicted_renders")
