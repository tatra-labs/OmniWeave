"""`build_verdict()` -- the fifteen gates, one fixture each, and the one site that says `absent`.

`V01-8` requires one fixture per gate and 07:2168 requires them to be independent: each test below
takes the clean baseline and moves exactly ONE fact, then asserts `gates == (that gate,)`. A gate
that fired on the baseline, or one that dragged a neighbour with it, fails here rather than in a
transcript nobody diffs.

The ladder itself is asserted three ways, because it has three separable claims: every gate is
evaluated whatever fired before it (07:2202), the surviving causes come back in `ABSENCE_GATES`
order (07:2166), and `ABSENT` is the residual that only an empty hit list with a clean ladder
reaches (07:2152). Worked plan (5) of 07:1936-1968 is the fixture for the first two: three gates
fire at once and the document prints the tuple.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import re
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.retrieve import verdict as vd
from omniweave_core.retrieve.fuse import fuse
from omniweave_core.retrieve.types import (
    ABSENCE_GATES,
    CHANNELS,
    NO_FILTERS,
    SCORER_VERSION,
    ChannelResult,
    ChannelStatus,
    FusionSpec,
    PackSpec,
    QueryPlan,
)
from omniweave_core.store.types import Coverage, IndexCaps, Narrowing

if TYPE_CHECKING:
    from conftest import PlanDocs

DOC = "07-store-and-retrieval.md"
OK = ChannelStatus.OK
EMPTY = ChannelStatus.EMPTY
OFF = ChannelStatus.OFF
UNAVAILABLE = ChannelStatus.UNAVAILABLE

PLAN = QueryPlan(
    channels=(),
    filters=NO_FILTERS,
    fusion=FusionSpec(),
    pack=PackSpec(),
    gates=ABSENCE_GATES,
    short_circuit=None,
    scorer_version=SCORER_VERSION,
    plan_digest="sha256:plan",
    policy_digest="sha256:policy",
)

CAPS = IndexCaps(
    schema="1.0",
    scorer_version=SCORER_VERSION,
    channels=frozenset(CHANNELS),
    has_head_fts=True,
    has_trigram=False,
    fts_state="ok",
    space_id=None,
    vec_backend=None,
    vec_ceiling=0,
    vec_pushdown=False,
    live_blocks=41_822,
    live_segments=0,
    docs=17,
    stat_age_ns=1_000_000_000,
    shard_ord=0,
    federated=False,
    caps_digest="sha256:caps",
)

CLEAN_COVERAGE = Coverage(
    discovered=17,
    indexed=17,
    partial=0,
    failed=0,
    skipped=0,
    complete=True,
    scope_rows=1,
    pending_work=0,
    stale_units=0,
    unreadable_units=0,
    gaps=(),
)


def _results(**status: ChannelStatus) -> tuple[ChannelResult, ...]:
    """All five Channels, `identity` ranking one block and the rest EMPTY unless told otherwise."""
    built: list[ChannelResult] = []
    for name in CHANNELS:
        state = status.get(name, OK if name == "identity" else EMPTY)
        ranked = (9,) if state == OK else ()
        reason = "" if state == OK else "nothing to report"
        built.append(ChannelResult(name=name, status=state, ranked=ranked, reason=reason))
    return tuple(built)


def _kwargs(**over: Any) -> dict[str, Any]:
    """The clean baseline: every gate passes, one block ranked, `state == OK`."""
    results = over.pop("results", _results())
    fused = over.pop("fused", fuse(results))
    base: dict[str, Any] = {
        "plan": PLAN,
        "results": results,
        "coverage": CLEAN_COVERAGE,
        "narrowing": Narrowing(kind="set", table="tmp_narrow", n=38_104),
        "caps": CAPS,
        "fused": fused,
        "returned": len(fused),
        "freshness": "fresh",
        "withheld": {"rows": 0},
        "snapshot_gen": 41,
        "generation_at_pack": 41,
    }
    base.update(over)
    return base


def _verdict(**over: Any) -> vd.Verdict:
    return vd.build_verdict(**_kwargs(**over))


def _coverage(**over: Any) -> Coverage:
    return dataclasses.replace(CLEAN_COVERAGE, **over)


# ---------------------------------------------------------------------------
# 1. The shapes, against the document that prints them
# ---------------------------------------------------------------------------


def test_the_four_states_are_the_charters_four() -> None:
    """07:1983: *"`ok | low_confidence | absent | degraded`"*."""
    assert [state.value for state in vd.VerdictState] == [
        "ok",
        "low_confidence",
        "absent",
        "degraded",
    ]


def test_the_blocking_diags_are_the_thirteen_the_injector_table_names(plan: PlanDocs) -> None:
    """13:2118 defines the set as one per `Diag` code, and 13:1281-1295 prints the thirteen rows.

    The count is load-bearing: 07:2238 calls `degradation_detection == 1.000` *"a claim about
    the thirteen"*, so a fourteenth member here would make a hard gate a claim about a population it
    does not cover.
    """
    plan.require()
    text = plan.text("13-quality.md")
    table = text[text.index("| injector | `Diag` |") : text.index("The suite asserts three things")]
    printed = tuple(re.findall(r"\|\s*`(OW_[A-Z_]+)`\s*\|", table))
    assert printed == vd.ABSENCE_BLOCKING_DIAGS
    assert len(vd.ABSENCE_BLOCKING_DIAGS) == 13


def test_the_fifteen_predicates_are_the_fifteen_gates_in_precedence_order() -> None:
    """07:2166: `ABSENCE_GATES`' *"order is the precedence order"*, as a literal and not a sort."""
    assert tuple(name for name, _predicate in vd._GATES) == ABSENCE_GATES
    assert len(vd._GATES) == 15


def test_a_cause_naming_something_that_is_not_a_gate_is_refused() -> None:
    """07:1990: `DegradeCause.gate` is a member of `ABSENCE_GATES`, NOT free text."""
    with pytest.raises(ValueError, match="is not one of the fifteen absence gates"):
        vd.DegradeCause(gate="looked_a_bit_thin", detail="")


def test_a_cause_carrying_a_non_blocking_diag_is_refused() -> None:
    """A code outside the thirteen does not block an absence claim, so it may not ride here."""
    with pytest.raises(ValueError, match="is not one of the thirteen"):
        vd.DegradeCause(gate="parse_gap_in_scope", detail="", diag_codes=("OW_SOMETHING_ELSE",))


def test_citable_as_absence_is_the_state_and_nothing_else() -> None:
    """07:2036: THE ONE GATE. NEVER A SECOND RULE."""
    absent = _verdict(fused=(), results=_results(identity=EMPTY))
    assert absent.state is vd.VerdictState.ABSENT
    assert absent.citable_as_absence is True
    assert _verdict().citable_as_absence is False


def test_exactly_one_return_of_the_absent_state_exists_in_the_module() -> None:
    """INV-11 / SV8, asserted here as well as by `tools/gate_semgrep.py`'s count pass.

    The gate walks `packages/*/src/**` and rejects a SECOND site; this asserts the FIRST one is
    here, which the gate cannot -- zero sites passes it and would mean the ladder stopped saying
    `absent` at all.
    """
    source = pathlib.Path(vd.__file__ or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "ABSENT"
    ]
    assert len(sites) == 1


# ---------------------------------------------------------------------------
# 2. The state ladder
# ---------------------------------------------------------------------------


def test_the_clean_baseline_is_ok() -> None:
    """One Channel ranked, four looked and found nothing: `2.0 / 5.4 = 0.370` is above 0.35."""
    made = _verdict()
    assert made.gates == ()
    assert made.state is vd.VerdictState.OK
    assert made.confidence == pytest.approx(2.0 / 5.4)


def test_a_failed_gate_forces_degraded_even_with_hits() -> None:
    """07:2147: *"A failed gate forces `DEGRADED` whether or not hits were returned."*"""
    made = _verdict(freshness="unknown")
    assert made.state is vd.VerdictState.DEGRADED
    assert made.best_score is not None


def test_low_confidence_sits_below_degraded_in_the_ladder() -> None:
    """07:2161: *"A degraded answer with high confidence is still degraded."*"""
    weak = _results(identity=EMPTY, lexical=OK)
    assert _verdict(results=weak).state is vd.VerdictState.LOW_CONFIDENCE
    assert _verdict(results=weak, freshness="unknown").state is vd.VerdictState.DEGRADED


def test_an_uncomputable_confidence_is_low_and_never_ok() -> None:
    """D258: a `0.0` weight is legal (07:1484) and makes `best / ceiling` a `0/0`.

    `None` is not a high confidence. Treating it as `OK` would publish "this is good evidence"
    from a number that does not exist.
    """
    zeroed = tuple(
        ChannelResult(name=r.name, status=r.status, ranked=r.ranked, reason=r.reason, weight=0.0)
        for r in _results()
    )
    made = _verdict(results=zeroed)
    assert made.score_ceiling == 0.0
    assert made.confidence is None
    assert made.state is vd.VerdictState.LOW_CONFIDENCE


def test_absent_needs_an_empty_hit_list_and_a_clean_ladder() -> None:
    """07:2152: *"`ABSENT` is the residual, not a gate's output."*"""
    nothing = _results(identity=EMPTY)
    assert _verdict(results=nothing, fused=()).state is vd.VerdictState.ABSENT
    assert _verdict(results=nothing, fused=(), freshness="unknown").state is (
        vd.VerdictState.DEGRADED
    )


# ---------------------------------------------------------------------------
# 3. One fixture per gate -- V01-8
# ---------------------------------------------------------------------------


def _fires(gate: str, **over: Any) -> vd.DegradeCause:
    """Build a verdict that fires exactly `gate`, and return its cause."""
    made = _verdict(**over)
    assert made.gates == (gate,), made.gates
    assert made.state is vd.VerdictState.DEGRADED
    return made.degraded_because[0]


def test_g01_timed_out() -> None:
    """07:2181. A Channel over its OWN `budget_ms`; a snapshot that expired is the same gate."""
    results = _results(lexical=UNAVAILABLE)
    results = tuple(
        ChannelResult(name=r.name, status=r.status, ranked=r.ranked, reason="timeout")
        if r.name == "lexical"
        else r
        for r in results
    )
    assert "lexical" in _fires("timed_out", results=results).detail
    assert "snapshot expired" in _fires("timed_out", snapshot_expired=True).detail


def test_g01_does_not_fire_on_a_channel_pre_empted_by_the_query_deadline() -> None:
    """07:2181: *"A Channel at `OFF(query_deadline)` is **not** this gate."*

    That is the two-deadline split (07:1791) reaching the ladder: the same absence of a result
    means two different things, and only the `reason` tells them apart.
    """
    results = tuple(
        ChannelResult(name=r.name, status=OFF, reason="query_deadline")
        if r.name == "lexical"
        else r
        for r in _results()
    )
    assert _verdict(results=results).gates == ()


def test_g02_channel_unavailable() -> None:
    """07:2182: `UNAVAILABLE` for any reason but timeout, or an `OFF` the caller asked for."""
    broken = tuple(
        ChannelResult(name=r.name, status=UNAVAILABLE, reason="fts_building")
        if r.name == "lexical"
        else r
        for r in _results()
    )
    cause = _fires("channel_unavailable", results=broken)
    assert "fts_building" in cause.detail
    assert cause.fix == "ow doctor"


def test_g02_fires_on_an_off_channel_the_caller_asked_for() -> None:
    """The second disjunct: an operator choice the caller overrode is still a Channel that
    did not look."""
    off = tuple(
        ChannelResult(name=r.name, status=OFF, reason="vectors") if r.name == "semantic" else r
        for r in _results()
    )
    cause = _fires("channel_unavailable", results=off, requested=frozenset({"semantic"}))
    assert "semantic" in cause.detail


def test_g03_store_changed_mid_query() -> None:
    """07:2183: one counter, read at plan and at pack. `fix` is empty -- the fix is to retry."""
    cause = _fires("store_changed_mid_query", generation_at_pack=42)
    assert cause.fix == ""
    assert "41" in cause.detail and "42" in cause.detail


def test_g04_coverage_incomplete_three_ways() -> None:
    """07:2184. **No row means coverage UNKNOWN, never clean** -- the disjunct that matters."""
    assert "UNKNOWN" in _fires("coverage_incomplete", coverage=_coverage(scope_rows=0)).detail
    _fires("coverage_incomplete", coverage=_coverage(indexed=16))
    _fires("coverage_incomplete", coverage=_coverage(complete=False))


def test_g05_pending_work_in_scope() -> None:
    """07:2185: a queued unit is a coverage hole with a completion date."""
    cause = _fires("pending_work_in_scope", coverage=_coverage(pending_work=1))
    assert cause.fix == ""


def test_g06_source_edited_unindexed() -> None:
    """07:2186: the corpus is complete and idle, and a source moved under it."""
    _fires("source_edited_unindexed", coverage=_coverage(stale_units=2))


def test_g07_freshness_unknown_and_not_tracked_is_not_a_failure() -> None:
    """07:2187: *"`not_tracked` is deliberately not a failure"* -- disclosed, not refused."""
    _fires("freshness_unknown", freshness="unknown")
    assert _verdict(freshness="not_tracked").gates == ()


def test_g08_inputs_unreadable() -> None:
    """07:2188: names a specific unit the scan should have read and could not."""
    _fires("inputs_unreadable", coverage=_coverage(unreadable_units=1))


def test_g09_parse_gap_in_scope_carries_the_codes_the_pages_and_the_command() -> None:
    """07:2189, and 07:1960's printed cause. The one gate that can name pages.

    The `where` triples are `(doc_ord, page_lo, page_hi)` INCLUSIVE, and the fix is a real command
    because `Coverage.gaps` was built where the document was in hand.
    """
    gap = vd.DegradeCause(
        gate="parse_gap_in_scope",
        detail="diag_code join: OW_NEEDS_OCR on 2024-appendix.pdf p.12-15",
        diag_codes=("OW_NEEDS_OCR",),
        where=((7, 12, 15),),
        fix="ow add 2024-appendix.pdf --allow-cost 40000",
    )
    cause = _fires("parse_gap_in_scope", coverage=_coverage(gaps=(gap,)))
    assert cause.diag_codes == ("OW_NEEDS_OCR",)
    assert cause.where == ((7, 12, 15),)
    assert cause.fix == "ow add 2024-appendix.pdf --allow-cost 40000"


def test_g09_merges_several_gaps_into_one_cause() -> None:
    """07:2005 gives `degraded_because` one entry per failed gate; `Coverage.gaps` is plural.

    D266: nothing says how several become one. Shipped: every code and every page range, merged in
    the join's own order, with the first gap's `fix`.
    """
    gaps = (
        vd.DegradeCause(
            gate="parse_gap_in_scope",
            detail="OW_NEEDS_OCR on a.pdf p.1-2",
            diag_codes=("OW_NEEDS_OCR",),
            where=((1, 1, 2),),
            fix="ow add a.pdf",
        ),
        vd.DegradeCause(
            gate="parse_gap_in_scope",
            detail="OW_ENCRYPTED on b.pdf p.9-9",
            diag_codes=("OW_ENCRYPTED",),
            where=((2, 9, 9),),
            fix="ow add b.pdf",
        ),
    )
    cause = _fires("parse_gap_in_scope", coverage=_coverage(gaps=gaps))
    assert cause.diag_codes == ("OW_NEEDS_OCR", "OW_ENCRYPTED")
    assert cause.where == ((1, 1, 2), (2, 9, 9))
    assert cause.fix == "ow add a.pdf"
    assert cause.detail.startswith("2 parse gaps")


def test_g10_restricted_withheld_reads_rows_and_no_other_key() -> None:
    """07:2079: *"Gate 10 reads this key and no other"*, because a block carrying two
    bits must not count twice."""
    assert _verdict(withheld={"rows": 0, "COPYLEFT_NETWORK": 0}).gates == ()
    cause = _fires("restricted_withheld", withheld={"rows": 3, "COPYLEFT_NETWORK": 3})
    assert "3 block(s)" in cause.detail
    assert "COPYLEFT_NETWORK" in cause.detail


def test_g11_filter_starved() -> None:
    """07:2191. Vacuous where pushdown is available; the survivor count is the second conjunct."""
    results = _results(semantic=OK)
    cause = _fires("filter_starved", results=results, degradations=("pushdown_unavailable",))
    assert "k=20" in cause.detail
    assert _verdict(results=results).gates == ()


def test_g12_truncated_by_packing() -> None:
    """07:2192, whose own row shouts it: AN EMPTY RESPONSE IS NOT AN EMPTY SEARCH."""
    cause = _fires("truncated_by_packing", returned=0)
    assert "matched and packing returned none" in cause.detail


def test_g13_space_mismatch_and_its_two_vacuous_cases() -> None:
    """07:2193: the same comparison that raises `OW-S-020` on the build path.

    Vacuous at `vectors = "off"` -- no space ran -- and vacuous with no configured `model_key`,
    which is D250's missing carrier rather than a clean bill of health.
    """
    space = {"model_key": "bge-small@1", "backend": "vector.brute"}
    cause = _fires("space_mismatch", space=space, configured_model_key="e5-base@2")
    assert cause.diag_codes == ("OW_INDEX_MODEL_CHANGED",)
    assert _verdict(space=space).gates == ()
    assert _verdict(configured_model_key="e5-base@2").gates == ()


def test_g14_shard_unreachable_is_vacuous_on_a_single_store() -> None:
    """07:2194: T4 only -- *"checking it late costs nothing on the store every reader
    actually has"*."""
    cause = _fires(
        "shard_unreachable", federated=True, shards_expected=2, shards_contributed="shard-0"
    )
    assert cause.fix == ""
    assert _verdict(shards_expected=2).gates == ()


def test_g15_similarity_only_is_checked_last_and_says_so() -> None:
    """07:2195: the only Channel with `status is OK` was `semantic`.

    `fix` is empty for the reason the gate is last -- 07:2195 again: *"a cosine zero is a
    statement about the model, not about the corpus"* -- so there is no command, and saying so
    is the disclosure.
    """
    only = _results(identity=EMPTY, semantic=OK)
    cause = _fires("similarity_only", results=only)
    assert cause.fix == ""
    assert _verdict(results=_results(semantic=OK)).gates == ()


# ---------------------------------------------------------------------------
# 4. The ladder runs to the end, and worked plan (5) is the proof
# ---------------------------------------------------------------------------


def test_worked_plan_five_fires_three_gates_in_precedence_order(plan: PlanDocs) -> None:
    """07:1955-1962. The tuple is read out of the transcript rather than retyped.

    Three gates fire at once, which is only possible because no gate ends the ladder (07:2202);
    they arrive in `ABSENCE_GATES` order, which 07:2166 calls the precedence order.
    """
    plan.require()
    text = plan.text(DOC)
    line = next(
        row
        for row in text.splitlines()
        if row.startswith("=> VerdictState.DEGRADED") or row.startswith("⇒ VerdictState.DEGRADED")
    )
    printed = tuple(re.findall(r'"([a-z_]+)"', line))
    gap = vd.DegradeCause(
        gate="parse_gap_in_scope",
        detail="diag_code join: OW_NEEDS_OCR on 2024-appendix.pdf p.12-15",
        diag_codes=("OW_NEEDS_OCR",),
        where=((7, 12, 15),),
        fix="ow add 2024-appendix.pdf --allow-cost 40000",
    )
    made = _verdict(
        results=_results(identity=EMPTY),
        fused=(),
        coverage=_coverage(indexed=16, complete=False, pending_work=1, gaps=(gap,)),
    )
    assert made.gates == printed
    assert made.state is vd.VerdictState.DEGRADED
    assert len(made.degraded_because) == 3
    assert [cause.gate for cause in made.degraded_because] == list(printed)


def test_every_gate_is_evaluated_whatever_fired_before_it() -> None:
    """One query that fails the first gate and the last one: both appear, in order."""
    results = tuple(
        ChannelResult(name=r.name, status=UNAVAILABLE, reason="timeout")
        if r.name == "identity"
        else ChannelResult(
            name=r.name,
            status=OK if r.name == "semantic" else EMPTY,
            ranked=(9,) if r.name == "semantic" else (),
            reason="",
        )
        for r in _results()
    )
    made = _verdict(results=results)
    assert made.gates == ("timed_out", "similarity_only")


def test_the_gates_that_failed_are_a_subsequence_of_the_precedence_order() -> None:
    """The general form of the two tests above, over a query that fails five gates at once."""
    made = _verdict(
        freshness="unknown",
        generation_at_pack=99,
        coverage=_coverage(pending_work=1, unreadable_units=1, scope_rows=0),
    )
    positions = [ABSENCE_GATES.index(name) for name in made.gates]
    assert positions == sorted(positions)
    assert len(positions) == 5


# ---------------------------------------------------------------------------
# 5. The derived fields
# ---------------------------------------------------------------------------


def test_channels_carries_all_five_always() -> None:
    """07:2016: *"A missing key would be indistinguishable from `OFF`, which is the disclosure this
    exists to make."*"""
    assert set(_verdict().channels) == set(CHANNELS)


def test_a_result_set_that_does_not_name_the_five_is_refused() -> None:
    """Completing it here would invent the disclosure the field exists for."""
    short = tuple(r for r in _results() if r.name != "semantic")
    with pytest.raises(ValueError, match="carries all five"):
        _verdict(results=short, fused=fuse(short))


@pytest.mark.parametrize(
    ("narrowing", "expected"),
    [
        (Narrowing(kind="set", table="tmp_narrow", n=38_104), 38_104),
        (Narrowing(kind="all", table=None, n=200_001), 41_822),
        (Narrowing(kind="empty", table=None, n=0), 0),
    ],
)
def test_scanned_narrowed_is_the_three_way_rule(narrowing: Narrowing, expected: int) -> None:
    """07:2058: `Narrowing.n` at `set`, `stat.live_blocks` at `all`, `0` at `empty`.

    The `all` row is the one that is not `narrowing.n`: above `PREFILTER_MAX` the probe's count is
    the cap, and reporting the cap as the number scanned would understate the search.
    """
    assert _verdict(narrowing=narrowing).scanned["narrowed"] == expected


def test_scanned_carries_its_four_keys_and_blocks_is_derived() -> None:
    """07:2068-2079's closed key set, and 07:2075 makes `blocks` *"distinct `block_id`s any Channel
    ranked"*."""
    results = _results(lexical=OK)
    made = _verdict(results=results, scanned_segments=12, scanned_docs=3)
    assert set(made.scanned) == {"narrowed", "blocks", "segments", "docs"}
    assert made.scanned["blocks"] == 1
    assert made.scanned["segments"] == 12


def test_fusion_kind_is_rank_merge_only_under_federation() -> None:
    """07:2052: *"`rank_merge` IFF federated"*, else `rrf`. The charter's `exact` is
    superseded."""
    assert _verdict().fusion_kind == "rrf"
    assert _verdict(federated=True).fusion_kind == "rank_merge"


def test_did_you_mean_is_bounded_by_its_named_constant() -> None:
    """07:1987's `MAX_DID_YOU_MEAN = 5`. A suggestion is never evidence and never unbounded."""
    made = _verdict(did_you_mean=tuple(f"s{n}" for n in range(9)))
    assert len(made.did_you_mean) == vd.MAX_DID_YOU_MEAN


def test_the_arithmetic_is_fuse_and_ceiling_and_not_a_second_spelling() -> None:
    """ST6 reaches the Verdict: `score_ceiling` is `ceiling()` over the same channel set."""
    made = _verdict()
    assert made.score_ceiling == pytest.approx(5.4 / 61)
    assert made.best_score == pytest.approx(2.0 / 61)
    assert made.matches_before_packing == 1
    assert made.scorer_version == SCORER_VERSION
    assert made.plan_digest == "sha256:plan"
