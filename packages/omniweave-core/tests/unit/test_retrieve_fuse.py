"""`fuse()`, `ceiling()` and the `_weight()` they share -- ST6, stated in its three halves.

07:1428 says what this file is for in one sentence: *"A ceiling that drifts from the scorer
silently rescales every confidence number in the product."* Every number below is therefore read
out of `_plan/` rather than retyped -- the three rows of section 5.3's worked table and the three
printed numbers of each of section 6.6's four transcripts -- so a scorer that drifted from the
document would fail here rather than produce a plausible wrong number.

**The property test is stated in THREE halves and not two.** 07:1429-1435 is the authority and
07:3240 confirms it in the ST6 row, *"the three-part property test of §5.3, halves
(a)/(b)/(c)"*. 13:873 (P-9), 15:877 and 16:659 all still say two, and 15:877 additionally gives the
pre-ADR-6 reason for half (a)'s failure. D259 records that; the code follows 07.

The behavioural half of every test runs on a clean clone. Only the plan-fidelity tests take the
`plan` fixture, and those skip when the design tree is absent.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import TYPE_CHECKING, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.retrieve.ceiling import ceiling, confidence
from omniweave_core.retrieve.fuse import _ranks, fuse
from omniweave_core.retrieve.types import (
    CEILING_WEIGHT_DENOMINATOR,
    CHANNELS,
    DEFAULT_WEIGHTS,
    RRF_K,
    ChannelResult,
    ChannelStatus,
    FusedHit,
    OffReason,
    _channel_set,
    _weight,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conftest import PlanDocs

DOC = "07-store-and-retrieval.md"
OK = ChannelStatus.OK
EMPTY = ChannelStatus.EMPTY
OFF = ChannelStatus.OFF
UNAVAILABLE = ChannelStatus.UNAVAILABLE


def _result(
    name: str,
    status: ChannelStatus = OK,
    ranked: tuple[int, ...] = (),
    *,
    rank_of: Mapping[int, int] | None = None,
    weight: float | None = None,
    reason: str = "",
    truncated_at_limit: bool = False,
) -> ChannelResult:
    """One `ChannelResult`, with 07:1232's `reason` supplied whenever the status needs one."""
    if status != OK and not reason:
        reason = "not stated by this fixture"
    return ChannelResult(
        name=name,
        status=status,
        ranked=ranked,
        rank_of=dict(rank_of or {}),
        weight=weight,
        reason=reason,
        truncated_at_limit=truncated_at_limit,
    )


def _best(hits: Sequence[FusedHit]) -> float | None:
    """07:2010's `best_score`: *"fuse()[0].score. None iff no Channel ranked"*."""
    return hits[0].score if hits else None


# ---------------------------------------------------------------------------
# 1. The formula, against the document that prints it
# ---------------------------------------------------------------------------


def test_the_shipped_weights_are_the_five_the_document_prints(plan: PlanDocs) -> None:
    """07:1381's `DEFAULT_WEIGHTS`, read out of the fence rather than retyped."""
    plan.require()
    for body in plan.fences(DOC, "python"):
        if "DEFAULT_WEIGHTS = {" not in body:
            continue
        printed = dict(re.findall(r'"([a-z]+)":\s*(\d+\.\d+)', body.split("DEFAULT_WEIGHTS")[1]))
        assert {name: float(value) for name, value in printed.items()} == dict(DEFAULT_WEIGHTS)
        return
    pytest.fail("no python fence in 07 prints DEFAULT_WEIGHTS")


def test_the_smoothing_constant_is_the_one_the_document_prints(plan: PlanDocs) -> None:
    """07:1383: *"`RRF_K = 60 ; SCORER_VERSION = 1`"*, and the ceiling's denominator follows it."""
    plan.require()
    assert plan.grep(r"^RRF_K = 60 ; SCORER_VERSION = 1", documents=[DOC])
    assert RRF_K == 60
    assert CEILING_WEIGHT_DENOMINATOR == RRF_K + 1


def _worked_table(plan: PlanDocs) -> dict[str, float]:
    """Section 5.3's three-row table: weight sum -> printed ceiling."""
    text = plan.text(DOC)
    body = text[text.index("Worked, at `k = 60`:") : text.index("**Never hardcode")]
    rows = re.findall(r"^\|.+?\| (\d+\.\d+) \| .+? \| \*\*(\d+\.\d+)\*\* \|$", body, re.M)
    assert len(rows) == 3, body
    return {total: float(value) for total, value in rows}


@pytest.mark.parametrize(
    ("total", "results"),
    [
        ("5.4", [_result(name) for name in CHANNELS]),
        (
            "4.6",
            [
                *[_result(name) for name in CHANNELS if name != "semantic"],
                _result("semantic", OFF, reason=OffReason.VECTORS),
            ],
        ),
        (
            "3.0",
            [
                _result("identity"),
                _result("lexical"),
                *[
                    _result(name, OFF, reason=OffReason.NOT_IN_PLAN)
                    for name in ("exact", "structural", "semantic")
                ],
            ],
        ),
    ],
)
def test_the_three_worked_ceilings_are_what_ceiling_computes(
    plan: PlanDocs, total: str, results: list[ChannelResult]
) -> None:
    """07:1402-1406's table, one row at a time.

    The middle row is *"four (semantic off, the shipped default)"* and it is the number charter D5
    prints. The bottom row is what a two-Channel plan normalises against: the weights *"are not
    normalised to sum to 1, so the ceiling genuinely depends on which Channels ran"* (07:1408).
    """
    plan.require()
    printed = _worked_table(plan)[total]
    assert round(ceiling(results), 5) == printed
    assert round(float(total) / 61, 5) == printed


# ---------------------------------------------------------------------------
# 2. `_weight()` -- the three levels, and the one both functions read
# ---------------------------------------------------------------------------


def test_an_explicit_weight_beats_the_named_default() -> None:
    """07:1484's level 1: *"an explicit float ... set by the Channel builder from the plan"*."""
    assert _weight(_result("identity", weight=0.25), DEFAULT_WEIGHTS) == 0.25
    assert _weight(_result("identity"), DEFAULT_WEIGHTS) == 2.0


def test_zero_is_a_weight_and_not_an_absent_one() -> None:
    """07:1485: *"`0.0` is a value, not "unset""* -- which is what `None` as the sentinel buys."""
    assert _weight(_result("identity", weight=0.0), DEFAULT_WEIGHTS) == 0.0


def test_a_channel_the_weight_map_does_not_name_weighs_one() -> None:
    """07:1385's third level. A sixth Channel weighs like an unweighted one, not like a zero."""
    assert _weight(_result("cartographic"), DEFAULT_WEIGHTS) == 1.0


def test_both_functions_resolve_the_same_override() -> None:
    """ST6 (07:3240): *"`fuse()` and `ceiling()` share `_weight()`"*, asserted as one movement.

    An override moves the numerator and the denominator by the same factor, so a hit ranked first
    everywhere keeps `confidence == 1.0` -- which is the invariant a drifting ceiling breaks.
    """
    plain = [_result("identity", ranked=(9,)), _result("lexical", ranked=(9,))]
    tuned = [_result("identity", ranked=(9,), weight=7.5), _result("lexical", ranked=(9,))]
    assert fuse(plain)[0].score != fuse(tuned)[0].score
    assert ceiling(plain) != ceiling(tuned)
    for results in (plain, tuned):
        assert confidence(_best(fuse(results)), ceiling(results)) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. `_channel_set()` -- materialised once, unique by name
# ---------------------------------------------------------------------------


def test_a_generator_reaches_both_functions() -> None:
    """The printed signatures take one `chs`; a drained iterator would be a silent `0.0`."""
    results = [_result("identity", ranked=(9,)), _result("lexical", ranked=(9,))]
    stream = (result for result in results)
    assert len(_channel_set(stream)) == 2
    assert fuse(result for result in results)
    assert ceiling(result for result in results) > 0.0


def test_one_name_twice_is_refused_by_both_functions() -> None:
    """`ceiling()` would count the weight twice and `fuse()` would keep one contribution."""
    doubled = [_result("lexical", ranked=(9,)), _result("lexical", ranked=(8,))]
    for call in (lambda: fuse(doubled), lambda: ceiling(doubled)):
        with pytest.raises(ValueError, match="two ChannelResults named 'lexical'"):
            call()


# ---------------------------------------------------------------------------
# 4. `FusedHit` -- the shape, and the 1-based rule it refuses to break
# ---------------------------------------------------------------------------


def test_a_rank_below_one_is_refused_on_the_shape() -> None:
    """07:1425: *"a 0-based implementation silently yields `confidence > 1`"*."""
    with pytest.raises(ValueError, match="rank 0 for block 9"):
        FusedHit(
            block_id=9,
            score=0.0164,
            channel_contributions={"lexical": 0.0164},
            channel_ranks={"lexical": 0},
        )


def test_the_two_mappings_must_carry_the_same_channels() -> None:
    """A contribution with no rank is a number nobody can re-derive."""
    with pytest.raises(ValueError, match="carries contributions from"):
        FusedHit(
            block_id=9,
            score=0.0164,
            channel_contributions={"lexical": 0.0164},
            channel_ranks={"lexical": 1, "identity": 1},
        )


def test_the_contributions_add_up_to_the_score() -> None:
    """07:1458: a fusion that returns only a score is one nobody can tune or check."""
    results = [
        _result("identity", ranked=(9, 4)),
        _result("lexical", ranked=(4, 9)),
        _result("structural", ranked=(4,)),
    ]
    for hit in fuse(results):
        assert hit.score == math.fsum(hit.channel_contributions.values())
        assert set(hit.channel_contributions) == set(hit.channel_ranks)


# ---------------------------------------------------------------------------
# 5. `fuse()`
# ---------------------------------------------------------------------------


def test_rank_is_one_based() -> None:
    """07:1392: *"rank(c, b) is 1-BASED"*, and bounded by `[1, len(c.ranked)]`."""
    hits = fuse([_result("lexical", ranked=(9, 8, 7))])
    assert [hit.block_id for hit in hits] == [9, 8, 7]
    assert [hit.channel_ranks["lexical"] for hit in hits] == [1, 2, 3]
    assert hits[0].score == pytest.approx(1.0 / 61)


def test_rank_of_overrides_the_position() -> None:
    """07:1240: *"a segment hit at rank r yields its member blocks at rank r"*.

    Four blocks lifted from two segments arrive at two ranks, not four, which is the region-level
    property a positional derivation would destroy.
    """
    lifted = _result("semantic", ranked=(9, 8, 7, 6), rank_of={9: 1, 8: 1, 7: 2, 6: 2})
    assert _ranks(lifted) == {9: 1, 8: 1, 7: 2, 6: 2}
    hits = fuse([lifted])
    assert {hit.block_id: hit.channel_ranks["semantic"] for hit in hits} == {9: 1, 8: 1, 7: 2, 6: 2}
    assert hits[0].score == hits[1].score


def test_an_unavailable_channel_contributes_nothing_although_it_ranked() -> None:
    """07:1791: a Channel over its own budget returns `UNAVAILABLE(timeout)` *"with what it has"*.

    The partial ranking is real and is carried; the `over c.status == OK` clause is what keeps it
    out of the score, and `counts_in_ceiling` keeps it out of the denominator too.
    """
    timed_out = _result("lexical", UNAVAILABLE, ranked=(9, 8), reason="timeout")
    assert fuse([timed_out]) == []
    assert ceiling([timed_out]) == 0.0


def test_a_pre_empted_channel_scores_like_a_complete_one() -> None:
    """The split's other side (07:1791): `OK` with `truncated_at_limit`, and nothing else
    differs -- the flag is carried for the Verdict and read by no arithmetic here."""
    partial = _result("lexical", ranked=(9,), truncated_at_limit=True)
    whole = _result("lexical", ranked=(9,))
    assert fuse([partial])[0].score == fuse([whole])[0].score


def test_empty_and_off_channels_rank_nothing() -> None:
    results = [
        _result("identity", EMPTY, reason="no cite, addr, uri or title matched"),
        _result("semantic", OFF, reason=OffReason.VECTORS),
    ]
    assert fuse(results) == []
    assert _best(fuse(results)) is None


def test_a_block_ranked_twice_by_one_channel_takes_its_first_position() -> None:
    """`1 + ch.ranked.index(b)` is the printed rule and `.index()` means the first occurrence."""
    assert _ranks(_result("lexical", ranked=(9, 8, 9))) == {9: 1, 8: 2}


def test_the_order_is_total_and_a_tie_breaks_on_block_id() -> None:
    """ST7 (07:1455). Two equal weights, two different blocks at rank 1, one deterministic order."""
    results = [
        _result("lexical", ranked=(9,)),
        _result("semantic", ranked=(3,), weight=1.0),
    ]
    hits = fuse(results)
    assert hits[0].score == hits[1].score
    assert [hit.block_id for hit in hits] == [3, 9]
    assert [hit.block_id for hit in fuse(reversed(results))] == [3, 9]


def test_the_output_is_a_function_of_the_channel_set_and_not_of_its_order() -> None:
    """All 120 orderings of five Channels, one identical ranking and identical scores.

    `math.fsum` is what makes the score half of that exact rather than nearly exact; the sort and
    the contribution mappings are what make the rest of it hold.
    """
    results = [
        _result("identity", ranked=(9, 4)),
        _result("exact", ranked=(4,)),
        _result("lexical", ranked=(9, 7, 4)),
        _result("structural", ranked=(7, 9)),
        _result("semantic", ranked=(4, 7), rank_of={4: 1, 7: 1}),
    ]
    reference = fuse(results)
    for order in itertools.permutations(results):
        assert fuse(order) == reference
        assert ceiling(order) == ceiling(results)


def test_a_hit_carries_only_the_channels_that_ranked_it() -> None:
    results = [_result("identity", ranked=(9,)), _result("lexical", ranked=(9, 4))]
    by_block = {hit.block_id: hit for hit in fuse(results)}
    assert set(by_block[9].channel_ranks) == {"identity", "lexical"}
    assert set(by_block[4].channel_ranks) == {"lexical"}


def test_the_weight_map_argument_is_honoured() -> None:
    results = [_result("identity", ranked=(9,))]
    assert fuse(results, weights={"identity": 4.0})[0].score == pytest.approx(4.0 / 61)
    assert ceiling(results, weights={"identity": 4.0}) == pytest.approx(4.0 / 61)


def test_k_smooths_the_score_and_is_not_an_output_bound() -> None:
    """D257: this `k` is `RRF_K`; the `k` that *"bounds fusion output"* (07:2349) is `Query.k`."""
    results = [_result("lexical", ranked=tuple(range(1, 31)))]
    assert len(fuse(results, k=20)) == 30
    assert fuse(results, k=20)[0].score == pytest.approx(1.0 / 21)
    assert ceiling(results, k=20) == pytest.approx(1.0 / 21)


# ---------------------------------------------------------------------------
# 6. `ceiling()`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason", "counts"),
    [
        (OK, "", True),
        (EMPTY, "no match", True),
        (UNAVAILABLE, "timeout", False),
        (OFF, OffReason.QUERY_DEADLINE, True),
        (OFF, OffReason.VECTORS, False),
        (OFF, OffReason.NOT_IN_PLAN, False),
        (OFF, OffReason.NOT_BUILT, False),
    ],
)
def test_the_ceilings_status_set_is_the_one_the_formula_prints(
    status: ChannelStatus, reason: str, counts: bool
) -> None:
    """07:1394-1396, one row per member, and 07:1415 for the `OFF` split.

    *"`OFF(vectors)` and `OFF(not_in_plan)` are operator choices: the Channel was never going to
    look, so its weight has no business in a denominator that measures "we looked there"."*
    """
    result = _result("identity", status, reason=reason)
    assert result.counts_in_ceiling is counts
    assert ceiling([result]) == (2.0 / 61 if counts else 0.0)


@pytest.mark.parametrize("reason", ["short_circuit", "narrowing_empty", "vectors_disabled"])
def test_an_off_reason_outside_the_closed_enum_does_not_bear_the_ceiling(reason: str) -> None:
    """D236's three, and worked plans (1) and (2) are the evidence for the fall-through.

    07:1850 excludes an `OFF(vectors_disabled)` semantic Channel from `4.6 / 61` and 07:1867
    excludes four `OFF(short_circuit)` Channels from `2.0 / 61`, so the document's own arithmetic
    reads all three as ceiling-exempt. `narrowing_empty` is the one with no printed arithmetic and
    it is the one D236 is about: every Channel at that reason makes the ceiling a sum over nothing.
    """
    assert ceiling([_result("identity", OFF, reason=reason)]) == 0.0


def test_a_raw_string_status_reaches_the_ceilings_branch() -> None:
    """The store's `ChannelOutcome` carries `status` as a `Literal` of the four VALUES.

    Its docstring states the property that makes that safe: `ChannelStatus` is a `StrEnum`, so
    `ChannelStatus.OFF == "off"` is `True` and P6 can compare against those outcomes without a
    conversion shim. `counts_in_ceiling` compared with `is not` until W6.3, which silently read a
    string `"off"` at `query_deadline` as not ceiling-bearing: the exact inversion 07:1419 names.
    """
    raw = _result("semantic", cast("ChannelStatus", "off"), reason=OffReason.QUERY_DEADLINE)
    assert raw.counts_in_ceiling is True
    assert ceiling([raw]) == pytest.approx(0.8 / 61)


def test_the_denominator_comes_from_the_argument_and_matches_the_named_constant() -> None:
    """07:1408: *"Never hardcode `1/(k+1)`."*

    `CEILING_WEIGHT_DENOMINATOR` names the DEFAULT's denominator so no reader has to recognise 61;
    it is not what the function divides by, because a ceiling normalising by 61 while `fuse()`
    scored with a different `k` is a ceiling from another scorer.
    """
    results = [_result("identity")]
    assert ceiling(results) == 2.0 / CEILING_WEIGHT_DENOMINATOR
    assert ceiling(results, k=9) == pytest.approx(2.0 / 10)


def test_a_channel_set_that_looked_nowhere_has_a_ceiling_of_zero() -> None:
    """Which is a denominator. D258."""
    assert ceiling([]) == 0.0
    assert ceiling([_result("semantic", OFF, reason=OffReason.VECTORS)]) == 0.0


# ---------------------------------------------------------------------------
# 7. `confidence()` -- the ratio, and both of its undefined cases
# ---------------------------------------------------------------------------


def test_confidence_is_none_when_nothing_ranked() -> None:
    """07:2010: `best_score` is *"None iff no Channel ranked"*, and `confidence` follows it."""
    results = [_result("identity", EMPTY, reason="no match")]
    assert _best(fuse(results)) is None
    assert confidence(_best(fuse(results)), ceiling(results)) is None


def test_confidence_is_none_over_a_zero_ceiling_carrying_a_real_best_score() -> None:
    """D258. 07:1484 blesses `0.0` as an explicit weight, and the ceiling is a denominator.

    The channel set is worked plan (2)'s -- one `OK` Channel, four `OFF(short_circuit)` -- with the
    one weight a policy is allowed to set. `best_score` is a real `0.0`, the ceiling is `0.0`, and
    07:2010's `None` rule is keyed to the numerator, so no field can say which zero this is.
    """
    results = [
        _result("identity", ranked=(412,), weight=0.0),
        *[_result(name, OFF, reason="short_circuit") for name in CHANNELS if name != "identity"],
    ]
    assert _best(fuse(results)) == 0.0
    assert ceiling(results) == 0.0
    assert confidence(_best(fuse(results)), ceiling(results)) is None


def test_confidence_is_the_ratio() -> None:
    assert confidence(0.03, 0.06) == 0.5


# ---------------------------------------------------------------------------
# 8. ST6, in its three halves
# ---------------------------------------------------------------------------

_SETS = st.lists(st.sampled_from(CHANNELS), unique=True, min_size=1, max_size=5)
_TAILS = st.lists(st.lists(st.integers(2, 60), unique=True, max_size=4), min_size=5, max_size=5)


@given(names=_SETS, tails=_TAILS)
def test_st6_half_a_all_ok_and_a_consensus_hit_attains_the_ceiling(
    names: list[str], tails: list[list[int]]
) -> None:
    """(a) 07:1432: *"over Channel sets whose members are **all `OK`**, `fuse()[0].score ==
    ceiling()`"*.

    Block 1 is ranked first by every member, which is what makes the ceiling ATTAINABLE: it is
    `sum of _weight / (k + 1)` and `k + 1` is *"the best attainable term"* (07:1425). The plan
    states the bound as 1e-12; `math.fsum` over the same multiset on both sides makes it exact.
    """
    results = [_result(name, ranked=(1, *tail)) for name, tail in zip(names, tails, strict=False)]
    hits = fuse(results)
    assert hits[0].block_id == 1
    assert hits[0].score == pytest.approx(ceiling(results), abs=1e-12)
    assert hits[0].score == ceiling(results)
    assert confidence(_best(hits), ceiling(results)) == pytest.approx(1.0)


@given(
    names=st.lists(st.sampled_from(CHANNELS), unique=True, min_size=2, max_size=5),
    cut=st.integers(min_value=1, max_value=4),
)
def test_st6_half_b_any_empty_member_puts_the_ceiling_out_of_reach(
    names: list[str], cut: int
) -> None:
    """(b) *"with **any `EMPTY`** member, `fuse()[0].score < ceiling()` **and** `confidence < 1`"*.

    07:1444: an `EMPTY` Channel's weight in the ceiling *"discloses "we looked there and found
    nothing", which is exactly the confidence penalty an honest ceiling should carry"*.
    """
    edge = min(cut, len(names) - 1)
    results = [
        *[_result(name, ranked=(1, 2)) for name in names[:edge]],
        *[_result(name, EMPTY, reason="no match") for name in names[edge:]],
    ]
    hits = fuse(results)
    assert hits[0].score < ceiling(results)
    ratio = confidence(_best(hits), ceiling(results))
    assert ratio is not None
    assert ratio < 1.0


@given(
    names=st.lists(st.sampled_from(CHANNELS), unique=True, min_size=2, max_size=5),
    index=st.integers(min_value=0, max_value=4),
)
def test_st6_half_c_off_query_deadline_keeps_its_ceiling_weight(
    names: list[str], index: int
) -> None:
    """(c) 07:1434: the ceiling *"is unchanged from the all-ran case"* and confidence falls.

    07:1419 states what exempting it would do: it *"shrinks the denominator and makes a worse
    answer report higher confidence, which is the exact inversion `ceiling()` exists to prevent"*.
    """
    target = names[index % len(names)]
    all_ran = [_result(name, ranked=(1, 2)) for name in names]
    pre_empted = [
        _result(name, OFF, reason=OffReason.QUERY_DEADLINE) if name == target else result
        for name, result in zip(names, all_ran, strict=True)
    ]
    assert ceiling(pre_empted) == ceiling(all_ran)
    fell = confidence(_best(fuse(pre_empted)), ceiling(pre_empted))
    stood = confidence(_best(fuse(all_ran)), ceiling(all_ran))
    assert fell is not None
    assert stood is not None
    assert fell < stood


def test_the_two_kinds_of_off_move_the_confidence_in_opposite_directions() -> None:
    """07:1415's split, as the two inequalities it is stated to prevent.

    The same Channel, the same absent ranking, one reason apart: at `query_deadline` the
    denominator stands and the confidence falls; at `vectors` the denominator shrinks and the
    confidence RISES above the case where the Channel ran and contributed.
    """
    all_ran = [_result(name, ranked=(1,)) for name in CHANNELS]
    by_reason = {
        reason: [
            _result("semantic", OFF, reason=reason) if name == "semantic" else result
            for name, result in zip(CHANNELS, all_ran, strict=True)
        ]
        for reason in (OffReason.QUERY_DEADLINE, OffReason.VECTORS)
    }
    deadline = by_reason[OffReason.QUERY_DEADLINE]
    vectors = by_reason[OffReason.VECTORS]

    assert ceiling(deadline) == ceiling(all_ran)
    assert ceiling(vectors) < ceiling(all_ran)

    ran = confidence(_best(fuse(all_ran)), ceiling(all_ran))
    fell = confidence(_best(fuse(deadline)), ceiling(deadline))
    rose = confidence(_best(fuse(vectors)), ceiling(vectors))
    assert ran is not None
    assert fell is not None
    assert rose is not None
    assert ran == pytest.approx(1.0)
    assert fell < ran
    assert rose == pytest.approx(1.0)
    assert rose > fell


def test_half_a_is_false_on_the_shipped_default() -> None:
    """16:659's estimation basis, as an assertion rather than as a sentence.

    *"Half (a) alone is false on the shipped default -- `vectors = "off"` makes `semantic` EMPTY
    and an empty `exact` channel is routine."* The first clause is the charter erratum ADR-6
    discharged and 07:1439 corrects it: `vectors = "off"` yields `OFF(vectors)`, which is
    ceiling-exempt, so it does not bear on half (a) at all. The second clause is the live one, and
    it is worked plan (1): three Channels `EMPTY`, one `OK`, `confidence` 0.217.
    """
    shipped = [
        _result("identity", EMPTY, reason="no cite, addr, uri or title matched"),
        _result("exact", EMPTY, reason="no reference-shaped token in the query"),
        _result("lexical", ranked=(101, 102)),
        _result("structural", EMPTY, reason="the frontier is empty at hop 1"),
        _result("semantic", OFF, reason=OffReason.VECTORS),
    ]
    assert ceiling(shipped) == pytest.approx(4.6 / 61)
    assert fuse(shipped)[0].score < ceiling(shipped)

    without_semantic = [result for result in shipped if result.name != "semantic"]
    assert ceiling(without_semantic) == ceiling(shipped)
    as_empty = [
        _result("semantic", EMPTY, reason="read as EMPTY, which ADR-6 refused")
        if result.name == "semantic"
        else result
        for result in shipped
    ]
    assert ceiling(as_empty) == pytest.approx(5.4 / 61)
    assert pytest.approx(0.852, abs=5e-4) == 4.6 / 5.4


# ---------------------------------------------------------------------------
# 9. The four worked plans of section 6.6, against their printed arithmetic
# ---------------------------------------------------------------------------


def _transcript(plan: PlanDocs, index: int) -> dict[str, str]:
    """The `ceiling`, `best_score` and `confidence` worked plan `index` prints.

    The last float before the transcript's own annotation is the computed value on every one of
    the twelve lines: an arrow (`->`, `<-`) or a parenthesised aside introduces the commentary.
    """
    text = plan.text(DOC)
    start = text.index(f"**({index}) `ow ")
    following = f"**({index + 1}) `ow "
    body = text[start : text.index(following, start)] if index < 5 else text[start:]
    numbers: dict[str, str] = {}
    for line in body.splitlines():
        field = line.split(":")[0].strip()
        if field not in ("ceiling", "best_score", "confidence") or field in numbers:
            continue
        head = re.split(r"←|→|\s\s\(", line)[0]
        numbers[field] = re.findall(r"\d+\.\d+", head)[-1]
    assert set(numbers) == {"ceiling", "best_score", "confidence"}, body
    return numbers


WORKED: dict[int, list[ChannelResult]] = {
    # (1) the ordinary mixed query: three EMPTY, lexical OK at rank 1, semantic an operator choice
    1: [
        _result("identity", EMPTY, reason="no cite, addr, uri or title matched"),
        _result("exact", EMPTY, reason="no reference-shaped token in the query"),
        _result("lexical", ranked=(101, 102, 103)),
        _result("structural", EMPTY, reason="the frontier is empty at hop 1"),
        _result("semantic", OFF, reason="vectors_disabled"),
    ],
    # (2) `ow open handbook:d7#412`: identity alone, the rest short-circuited away
    2: [
        _result("identity", ranked=(412,)),
        *[_result(name, OFF, reason="short_circuit") for name in CHANNELS if name != "identity"],
    ],
    # (3) purely structural: 311 ranked from the narrowed set, two Channels not in the plan
    3: [
        _result("identity", EMPTY, reason="no cite, addr, uri or title matched"),
        _result("exact", EMPTY, reason="no reference-shaped token in the query"),
        _result("structural", ranked=(511, 512, 513)),
        *[_result(name, OFF, reason=OffReason.NOT_IN_PLAN) for name in ("lexical", "semantic")],
    ],
    # (4) purely thematic: the top block is semantic rank 1 and structural rank 3
    4: [
        *[_result(name, OFF, reason=OffReason.NOT_IN_PLAN) for name in ("identity", "exact")],
        _result("lexical", EMPTY, reason="none of the query's terms occurs as a term"),
        _result("semantic", ranked=(7000, 7001), rank_of={7000: 1, 7001: 1}),
        _result("structural", ranked=(8001, 8002, 7000)),
    ],
}


@pytest.mark.parametrize("index", [1, 2, 3, 4])
def test_the_worked_plans_arithmetic_is_what_this_module_computes(
    plan: PlanDocs, index: int
) -> None:
    """Section 6.6's four transcripts, each read out of the document and recomputed.

    07:1834 says what they are: *"These five are illustrations. The contract is §6.7 (the
    `Verdict` record) and §6.8 (the fifteen gates)."* They are still the only
    end-to-end arithmetic the plan prints, and all four of the ceiling's status classes appear
    across them -- `OK`, `EMPTY`, an `OffReason` member and two
    `OFF` reasons that are not members of it.
    """
    plan.require()
    printed = _transcript(plan, index)
    results = WORKED[index]
    hits = fuse(results)
    score_ceiling = ceiling(results)
    ratio = confidence(_best(hits), score_ceiling)
    assert ratio is not None
    _agrees(score_ceiling, printed["ceiling"])
    _agrees(hits[0].score, printed["best_score"])
    _agrees(ratio, printed["confidence"])


def _agrees(computed: float, printed: str) -> None:
    """Compare at the precision the document PRINTED, which a float conversion throws away.

    Worked plan (2)'s confidence is printed `1.000` and means three decimals of 1, not one.
    """
    assert round(computed, len(printed.split(".")[1])) == float(printed), (computed, printed)
