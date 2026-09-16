"""The five tiers, the four worth tables, and reserve-then-render.

Three families of assertion, and the split between them is the point:

* **The numbers are read out of `_plan/`, never retyped.** The five tier rows and the four
  `WORTH_*` tables are parsed from charter.md's own source block, so a transcription error fails
  here rather than shipping as a slightly different packer. These tests take the `plan` fixture and
  skip on a clean clone.
* **The invariants are property tests.** 16:662 names the one the roadmap wants -- *"a larger tier
  may never receive a smaller chars-per-doc"* -- and 13:882 calls it P-18. It is stated over
  arbitrary tables and not only over the shipped one, because SV4 is a check on an OPERATOR'S
  table (02:1201) and the shipped table passing it proves nothing about the mechanism.
* **The allocator's rules get one fixture each**, each moving exactly one fact off a clean
  baseline, so a rule that fires on the baseline fails here rather than in a rendered document
  nobody diffs.

The last section re-measures the worked Answer at 10:617-686. All eight of 10:693-702's
per-section character counts and the 3,871 total reproduce exactly, which is what makes it
W6.6c's fixture -- and what prices D273's shortfall in the plan's own bytes.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.answer.allocate import (
    BLOCK_OVERHEAD,
    BUY_POOL,
    CLIFF_EXEMPT_CHANNELS,
    CLIFF_EXEMPT_TRUST,
    CLIFF_FRACTION,
    DOC_OVERHEAD,
    MAX_SHARE,
    MIN_CHARS,
    SPINE_BOOST,
    WHOLE_SECTION_BUY,
    Candidate,
    allocate,
)
from omniweave_core.answer.budget import (
    BUDGET_TIERS,
    HARD_CEILING,
    MIN_REQUESTABLE_CHARS,
    TIER_COLUMNS,
    AnswerBudget,
    effective_max_chars,
    tier_for,
    tiers,
)
from omniweave_core.answer.worth import (
    MAX_WORTH,
    WORTH_KIND,
    WORTH_KIND_DEFAULT,
    WORTH_LAYER,
    WORTH_QUOTE,
    WORTH_TRUST,
    worth,
)
from omniweave_core.config import PACKING_TIER
from omniweave_core.errors import ConfigError
from omniweave_core.model.enums import Kind, Layer, Quote, Trust

if TYPE_CHECKING:
    from collections.abc import Sequence

    from conftest import PlanDocs
    from omniweave_core.config import Scalar

CHARTER = "_notes/charter.md"
INTERFACES = "10-interfaces.md"

# 10:557's greppable section marker, and its two asterisks as their own name. Spelling them
# here rather than inline keeps the scratchpad citation checker's quote scanner from pairing a
# `"*"` literal with a later `"**` one across half the file.
STARS = "*"
MARKER = "**ow:"

TIER_0 = BUDGET_TIERS[0]
TIER_2 = BUDGET_TIERS[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell(printed: str) -> object:
    """One charter cell. `INF` is `sys.maxsize`, the only integer spelling a TOML table has."""
    if printed in {"True", "False"}:
        return printed == "True"
    if printed == "INF":
        return 9_223_372_036_854_775_807
    return int(printed)


def _charter_tiers(plan: PlanDocs) -> tuple[tuple[object, ...], ...]:
    """charter.md:6647's five rows, parsed out of the source block."""
    text = plan.text(CHARTER)
    start = text.index("BUDGET_TIERS = (")
    body = text[start : text.index("# MONOTONICITY (SV4)", start)]
    rows: list[tuple[object, ...]] = []
    for line in body.splitlines()[1:]:
        cells = re.findall(r"(?<![\w.])(\d[\d_]*|True|False|INF)(?![\w.])", line)
        if len(cells) == len(TIER_COLUMNS):
            rows.append(tuple(_cell(cell) for cell in cells))
    return tuple(rows)


def _charter_worth(plan: PlanDocs, name: str) -> dict[str, float]:
    """One `WORTH_*` table, as `{member: value}` with the enum name stripped."""
    text = plan.text(CHARTER)
    start = text.index(f"{name} ")
    body = text[start : text.index("}", start)]
    return {member: float(value) for member, value in re.findall(r"\.(\w+)\s*:\s*([\d.]+)", body)}


def _worked_answer(plan: PlanDocs) -> tuple[str, ...]:
    """10:617-686 -- the seventy rendered lines of the worked Answer, with their newlines."""
    lines = plan.text(INTERFACES).splitlines(keepends=True)
    opens = [i for i, line in enumerate(lines) if line.startswith("````text")]
    closes = [i for i, line in enumerate(lines) if line.rstrip("\n") == "````"]
    first = opens[0]
    last = next(i for i in closes if i > first)
    return tuple(lines[first + 1 : last])


def _candidate(
    doc: str,
    cite: str,
    chars: int,
    score: float,
    *,
    block_worth: float = 1.0,
    trust: Trust = Trust.EXTRACTED,
    channels: frozenset[str] = frozenset({"lexical"}),
    spine: bool = False,
    section: str | None = None,
) -> Candidate:
    return Candidate(
        doc_key=doc,
        cite=cite,
        chars=chars,
        score=score,
        worth=block_worth,
        trust=trust,
        channels=channels,
        spine=spine,
        section=section,
    )


def _row(**over: Scalar) -> tuple[Scalar, ...]:
    """One tier row as eight cells, defaulted to the shipped first tier."""
    shipped: tuple[Scalar, ...] = (5_000, 12_000, 4, 3_500, 1, False, False, False)
    cells: dict[str, Scalar] = dict(zip(TIER_COLUMNS, shipped, strict=True))
    cells.update(over)
    return tuple(cells[name] for name in TIER_COLUMNS)


# ---------------------------------------------------------------------------
# 1. The tier table is the charter's
# ---------------------------------------------------------------------------


def test_the_shipped_tiers_are_the_five_rows_the_charter_prints(plan: PlanDocs) -> None:
    """charter.md:6647-6652, cell for cell. `INF` is `sys.maxsize`, the only integer spelling."""
    plan.require()
    printed = _charter_tiers(plan)
    assert len(printed) == 5
    assert printed == tuple(tuple(row) for row in PACKING_TIER)
    assert BUDGET_TIERS[-1].blocks_below == 9_223_372_036_854_775_807


def test_the_three_flag_columns_are_the_charter_s(plan: PlanDocs) -> None:
    """`related`, `pointers`, `meta_text`, and 12:402's reason the last is off on a small corpus."""
    plan.require()
    printed = _charter_tiers(plan)
    assert [row[5:] for row in printed] == [
        (tier.related, tier.pointers, tier.meta_text) for tier in BUDGET_TIERS
    ]
    assert not BUDGET_TIERS[0].meta_text
    assert BUDGET_TIERS[0].calls == 1


def test_the_smallest_tier_is_the_one_the_performance_document_prints(plan: PlanDocs) -> None:
    """12:401 prints tier 0 in full: `[5000, 12000, 4, 3500, 1, false, false, false]`."""
    plan.require()
    hits = plan.grep(
        r"\[5000, 12000, 4, 3500, 1, false, false, false\]", documents=("12-performance.md",)
    )
    assert hits, "12:401's tier-0 row moved"
    assert (TIER_0.blocks_below, TIER_0.max_chars, TIER_0.max_docs, TIER_0.chars_per_doc) == (
        5_000,
        12_000,
        4,
        3_500,
    )


def test_the_column_order_is_the_config_row_s(plan: PlanDocs) -> None:
    """18:1739 prints the eight column names in the wire order `serve.packing.tier` uses."""
    plan.require()
    hits = plan.grep(
        r"blocks_below, max_chars, max_docs, chars_per_doc", documents=("18-api-sketch.md",)
    )
    assert hits
    assert "[" + ", ".join(TIER_COLUMNS) + "]" in hits[0].text


def test_the_hard_ceiling_is_the_one_number_the_charter_names(plan: PlanDocs) -> None:
    """charter.md:6643, 18:1729. ONE ceiling for every tool."""
    plan.require()
    assert HARD_CEILING == 24_000
    assert plan.grep(r"HARD_CEILING = 24_000", documents=(CHARTER,))
    assert max(tier.max_chars for tier in BUDGET_TIERS) == HARD_CEILING


# ---------------------------------------------------------------------------
# 2. SV4 / P-18 -- monotonicity, over arbitrary tables and not only the shipped one
# ---------------------------------------------------------------------------

_SIZES = st.lists(st.integers(min_value=1, max_value=HARD_CEILING), min_size=2, max_size=6)


@given(_SIZES)
def test_a_larger_tier_may_never_receive_a_smaller_chars_per_doc(sizes: list[int]) -> None:
    """16:662's named property, stated the way 13:882 states it (P-18).

    The table is built from an arbitrary list, then accepted or refused by `tiers()`; the assertion
    is that acceptance and monotonicity are the same condition, in both directions.
    """
    rows = [
        _row(blocks_below=(index + 1) * 1_000, chars_per_doc=size)
        for index, size in enumerate(sizes)
    ]
    monotone = all(a <= b for a, b in itertools.pairwise(sizes))
    if monotone:
        parsed = tiers(rows)
        assert [tier.chars_per_doc for tier in parsed] == sizes
    else:
        with pytest.raises(ConfigError, match="not monotone in chars_per_doc"):
            tiers(rows)


def test_the_shipped_table_is_monotone_in_all_four_size_columns() -> None:
    """`chars_per_doc` is the one the document names; three more carry size and are checked too."""
    for column in ("max_chars", "max_docs", "chars_per_doc", "calls"):
        values = [getattr(tier, column) for tier in BUDGET_TIERS]
        assert values == sorted(values), column


def test_blocks_below_is_strictly_increasing_and_a_repeat_is_refused() -> None:
    """Two rows at one threshold make the second unreachable, so it is not a warning."""
    assert [tier.blocks_below for tier in BUDGET_TIERS] == sorted(
        {tier.blocks_below for tier in BUDGET_TIERS}
    )
    with pytest.raises(ConfigError, match="it can never be selected"):
        tiers([_row(blocks_below=5_000), _row(blocks_below=5_000)])


def test_the_flag_columns_are_not_checked_for_monotonicity() -> None:
    """A latch turned off at the top tier is a policy, not an error -- see the module docstring."""
    parsed = tiers([_row(blocks_below=1_000, meta_text=True), _row(blocks_below=2_000)])
    assert [tier.meta_text for tier in parsed] == [True, False]


# ---------------------------------------------------------------------------
# 3. `tiers()`'s refusals
# ---------------------------------------------------------------------------


def test_an_empty_table_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ConfigError, match="no tier to serve any corpus from"):
        tiers([])


def test_a_short_row_names_the_eight_columns() -> None:
    with pytest.raises(ConfigError, match="not 8"):
        tiers([_row()[:7]])


def test_a_tier_above_the_hard_ceiling_is_refused_and_not_clamped() -> None:
    """A clamp would make `omniweave.toml` say one number and the trailer print another."""
    with pytest.raises(ConfigError, match="above HARD_CEILING"):
        tiers([_row(max_chars=HARD_CEILING + 1)])


@pytest.mark.parametrize(
    "column", ["blocks_below", "max_chars", "max_docs", "chars_per_doc", "calls"]
)
def test_a_non_positive_size_is_refused(column: str) -> None:
    with pytest.raises(ConfigError, match="not positive"):
        tiers([_row(**{column: 0})])


def test_a_boolean_in_an_integer_column_is_refused() -> None:
    """`True` is an `int` in Python. A tier bound of `True` would be a `max_docs` of one."""
    with pytest.raises(ConfigError, match="not an integer"):
        tiers([_row(max_docs=True)])


def test_an_integer_in_a_flag_column_is_refused() -> None:
    with pytest.raises(ConfigError, match="not a boolean"):
        tiers([_row(related=1)])


def test_every_refusal_carries_a_command() -> None:
    """Every `OwError` names the command that clears it, and a tier refusal is a config one."""
    for bad in ([], [_row(max_chars=HARD_CEILING + 1)], [_row(related=1)], [_row(max_docs=0)]):
        with pytest.raises(ConfigError) as caught:
            tiers(bad)
        assert "serve.packing.tier" in caught.value.fix or "serve.packing.tier" in str(caught.value)


# ---------------------------------------------------------------------------
# 4. `tier_for` -- keyed on INDEXED BLOCKS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("blocks", "index"),
    [(0, 0), (4_999, 0), (5_000, 1), (49_999, 1), (50_000, 2), (499_999, 2), (500_000, 3)],
)
def test_the_threshold_is_exclusive(blocks: int, index: int) -> None:
    """A corpus of exactly 5,000 blocks is the SECOND tier's, not the first's."""
    assert tier_for(blocks)[0] == index


def test_a_spreadsheet_heavy_corpus_lands_two_tiers_above_a_document_count(plan: PlanDocs) -> None:
    """12:403: *"ten spreadsheet-heavy documents can be 40k Blocks and land two tiers up."*"""
    plan.require()
    assert plan.grep(r"can be 40k Blocks and land two tiers up", documents=("12-performance.md",))
    assert tier_for(40_000)[0] == 1
    assert tier_for(10)[0] == 0


def test_a_count_above_the_last_threshold_takes_the_last_row() -> None:
    small = tiers([_row(blocks_below=10)])
    assert tier_for(10_000, small)[0] == 0


def test_a_negative_block_count_is_a_bug_and_not_the_smallest_tier() -> None:
    with pytest.raises(ValueError, match="cannot be"):
        tier_for(-1)


# ---------------------------------------------------------------------------
# 5. `effective_max_chars` -- 10:479's clamp
# ---------------------------------------------------------------------------


def test_the_clamp_is_the_minimum_of_three(plan: PlanDocs) -> None:
    """10:479: `min(requested, tier.max_chars, HARD_CEILING)`."""
    plan.require()
    assert plan.grep(r"min\(requested, tier\.max_chars, HARD_CEILING\)", documents=(INTERFACES,))
    assert effective_max_chars(8_000, TIER_2) == 8_000
    assert effective_max_chars(30_000, TIER_2) == TIER_2.max_chars
    assert effective_max_chars(None, TIER_2) == TIER_2.max_chars


def test_a_request_above_the_tier_is_honoured_at_the_tier_and_never_refused() -> None:
    """10:480: *"honoured at the tier and disclosed, never refused."*"""
    assert effective_max_chars(HARD_CEILING, TIER_0) == TIER_0.max_chars


def test_a_request_below_the_documented_floor_is_refused_rather_than_raised_to_it() -> None:
    """10:476 bounds the argument at 1,000-24,000. A caller given 1,000 for 200 was not told."""
    with pytest.raises(ValueError, match="MIN_REQUESTABLE_CHARS"):
        effective_max_chars(MIN_REQUESTABLE_CHARS - 1, TIER_2)


def test_the_clamp_can_never_raise_a_request() -> None:
    for tier in BUDGET_TIERS:
        for requested in (1_000, 5_000, 11_999, 24_000):
            assert effective_max_chars(requested, tier) <= requested


# ---------------------------------------------------------------------------
# 6. `AnswerBudget`
# ---------------------------------------------------------------------------


def _budget(**over: int) -> AnswerBudget:
    fields = {
        "tier_index": 2,
        "blocks_below": 500_000,
        "max_chars": 22_000,
        "chars_used": 3_871,
        "max_docs": 8,
        "docs_used": 2,
        "calls_allowed": 3,
        "call_ord": 1,
        "chars_deduped": 3_912,
        "doc_overhead": DOC_OVERHEAD,
        "block_overhead": BLOCK_OVERHEAD,
    }
    fields.update(over)
    return AnswerBudget(**fields)  # type: ignore[arg-type]


def test_the_budget_carries_the_worked_answers_own_numbers() -> None:
    """The worked trailer prints `3871/22000 chars - call 1 of 3 - dedup saved 3,912 chars`."""
    budget = _budget()
    assert (budget.chars_used, budget.max_chars) == (3_871, 22_000)
    assert (budget.call_ord, budget.calls_allowed) == (1, 3)
    assert budget.chars_deduped == 3_912
    assert not budget.over_budget


def test_call_ord_is_one_based_like_the_fusion_ranks() -> None:
    with pytest.raises(ValueError, match="1-based"):
        _budget(call_ord=0)


@pytest.mark.parametrize("field_name", ["chars_used", "docs_used", "chars_deduped"])
def test_a_negative_count_is_refused(field_name: str) -> None:
    with pytest.raises(ValueError, match="negative"):
        _budget(**{field_name: -1})


def test_over_budget_is_reportable_and_not_a_refusal() -> None:
    """A renderer that overran must SAY so; a constructor refusal leaves only a traceback."""
    assert _budget(chars_used=22_001).over_budget


# ---------------------------------------------------------------------------
# 7. The four worth tables are the charter's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "table", "enum"),
    [
        ("WORTH_LAYER", WORTH_LAYER, Layer),
        ("WORTH_KIND", WORTH_KIND, Kind),
        ("WORTH_TRUST", WORTH_TRUST, Trust),
        ("WORTH_QUOTE", WORTH_QUOTE, Quote),
    ],
)
def test_each_worth_table_is_the_one_the_charter_prints(
    plan: PlanDocs, name: str, table: object, enum: type
) -> None:
    """charter.md:6667-6673, member for member and value for value."""
    plan.require()
    printed = _charter_worth(plan, name)
    shipped = {member.name: value for member, value in dict(table).items()}  # type: ignore[call-overload]
    assert shipped == printed
    assert all(hasattr(enum, member) for member in printed)


def test_the_three_total_tables_cover_their_whole_enum() -> None:
    """`Layer`, `Trust` and `Quote` are total; a new member must be priced before it can pack."""
    assert set(WORTH_LAYER) == set(Layer)
    assert set(WORTH_TRUST) == set(Trust)
    assert set(WORTH_QUOTE) == set(Quote)


def test_the_kind_table_is_a_penalty_list_and_not_a_total_one() -> None:
    """Five of thirty-five, and every other kind is the default rather than a `KeyError`."""
    assert len(WORTH_KIND) == 5
    assert set(WORTH_KIND) < set(Kind)
    assert worth(
        layer=Layer.BODY, kind=Kind.PARAGRAPH, trust=Trust.EXTRACTED, quote=Quote.NORMALIZED
    ) == pytest.approx(WORTH_KIND_DEFAULT)


def test_trust_is_monotone_in_its_own_ordering() -> None:
    """`Trust` is an ordered `IntEnum`, weakest lowest; worth never rewards a weaker provenance."""
    values = [WORTH_TRUST[member] for member in sorted(Trust, key=int)]
    assert values == sorted(values)


def test_quote_is_monotone_in_its_own_ordering() -> None:
    """Same for `Quote`, which is what makes `min(quote)` the weakest rung AND the cheapest."""
    values = [WORTH_QUOTE[member] for member in sorted(Quote, key=int)]
    assert values == sorted(values)


def test_hidden_is_zero_and_therefore_an_exclusion(plan: PlanDocs) -> None:
    """10:472: `layers=` is *"the **only** path to `Layer.HIDDEN`"* because this is 0.0."""
    plan.require()
    assert plan.grep(r"`WORTH_LAYER` weight is `0\.0`", documents=(INTERFACES,))
    assert WORTH_LAYER[Layer.HIDDEN] == 0.0
    assert (
        worth(layer=Layer.HIDDEN, kind=Kind.PARAGRAPH, trust=Trust.EXTRACTED, quote=Quote.VERBATIM)
        == 0.0
    )


def test_the_products_supremum_is_the_named_constant() -> None:
    """Derived from the four tables rather than trusting `MAX_WORTH`'s own line."""
    best = (
        max(WORTH_LAYER.values())
        * WORTH_KIND_DEFAULT
        * max(WORTH_TRUST.values())
        * max(WORTH_QUOTE.values())
    )
    assert best == pytest.approx(MAX_WORTH)
    assert MAX_WORTH > 1.0


def test_an_unknown_layer_trust_or_quote_raises_rather_than_defaulting() -> None:
    """A `Layer` member's own wire string is the same key -- `Layer` is a `StrEnum` -- so the
    refusal is of a name that is not a member at all, which is what a new enum member looks like to
    a packer that has not been told what it is worth."""
    assert WORTH_LAYER["body"] == WORTH_LAYER[Layer.BODY]  # type: ignore[index]
    with pytest.raises(KeyError):
        worth(layer="marginalia", kind=Kind.PARAGRAPH, trust=Trust.EXTRACTED, quote=Quote.VERBATIM)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 8. D270 -- the 0.68 the plan prices the down-weight with is a product, not a ratio
# ---------------------------------------------------------------------------


def test_the_re_imported_artefact_multiplier_is_the_one_two_documents_print(plan: PlanDocs) -> None:
    """07:1620 and 00:671 both print `0.85 x 0.80 = 0.68`, and that product is exact here."""
    plan.require()
    assert plan.grep(r"0\.85 . 0\.80 = 0\.68", documents=("07-store-and-retrieval.md",))
    reimported = worth(
        layer=Layer.BODY, kind=Kind.PARAGRAPH, trust=Trust.INFERRED, quote=Quote.RECONSTRUCTED
    )
    assert reimported == pytest.approx(0.68)


def test_but_it_is_not_that_fraction_of_a_source_block_because_verbatim_is_above_one() -> None:
    """D270. A source Block is 1.15, so the re-imported artefact competes at 0.591 and not 0.68."""
    source = worth(
        layer=Layer.BODY, kind=Kind.PARAGRAPH, trust=Trust.EXTRACTED, quote=Quote.VERBATIM
    )
    reimported = worth(
        layer=Layer.BODY, kind=Kind.PARAGRAPH, trust=Trust.INFERRED, quote=Quote.RECONSTRUCTED
    )
    assert source == pytest.approx(1.15)
    assert reimported / source == pytest.approx(0.5913, abs=5e-5)


def test_a_badly_scanned_source_page_is_worth_less_than_a_re_imported_artefact(
    plan: PlanDocs,
) -> None:
    """07:1622: *"a well-written generated summary outranks a badly-scanned source page."*"""
    plan.require()
    assert plan.grep(r"badly-scanned source page", documents=("07-store-and-retrieval.md",))
    scanned = worth(
        layer=Layer.BODY, kind=Kind.PARAGRAPH, trust=Trust.AMBIGUOUS, quote=Quote.RECONSTRUCTED
    )
    reimported = worth(
        layer=Layer.BODY, kind=Kind.PARAGRAPH, trust=Trust.INFERRED, quote=Quote.RECONSTRUCTED
    )
    assert scanned < reimported


# ---------------------------------------------------------------------------
# 9. The allocation constants are the charter's
# ---------------------------------------------------------------------------


def test_the_allocation_constants_are_the_ones_the_charter_prints(plan: PlanDocs) -> None:
    """charter.md:6656-6664, every cell of the `ALLOCATION` dict."""
    plan.require()
    text = plan.text(CHARTER)
    body = text[text.index("ALLOCATION = {") : text.index("# RELEVANCE and WORTH")]
    printed = dict(re.findall(r'"(\w+)":\s*([\d.]+)', body))
    assert float(printed["CLIFF_FRACTION"]) == CLIFF_FRACTION
    assert int(printed["MIN_CHARS"]) == MIN_CHARS
    assert float(printed["MAX_SHARE"]) == MAX_SHARE
    assert int(printed["DOC_OVERHEAD"]) == DOC_OVERHEAD
    assert int(printed["BLOCK_OVERHEAD"]) == BLOCK_OVERHEAD
    assert float(printed["SPINE_BOOST"]) == SPINE_BOOST
    assert float(printed["WHOLE_SECTION_BUY"]) == WHOLE_SECTION_BUY
    assert float(printed["BUY_POOL"]) == BUY_POOL
    assert "Trust.EXTRACTED" in body
    assert CLIFF_EXEMPT_TRUST is Trust.EXTRACTED


# ---------------------------------------------------------------------------
# 10. The cliff -- and D271's second conjunct
# ---------------------------------------------------------------------------


def _two_docs(weak_score: float, **over: object) -> tuple[Candidate, ...]:
    """One strong document and one whose weight is `weak_score` relative to it."""
    return (
        _candidate("strong", "c:d1#1", 1_200, 1.0),
        _candidate("weak", "c:d2#1", 1_200, weak_score, **over),  # type: ignore[arg-type]
    )


def test_a_document_below_the_cliff_becomes_a_pointer() -> None:
    result = allocate(_two_docs(0.10), tier=TIER_2)
    assert [plan.doc_key for plan in result.packed] == ["strong"]
    assert [(c.doc_key, c.reason) for c in result.cliffed] == [("weak", "below_cliff")]


def test_a_document_just_above_the_cliff_packs() -> None:
    result = allocate(_two_docs(0.20), tier=TIER_2)
    assert [plan.doc_key for plan in result.packed] == ["strong", "weak"]
    assert result.cliffed == ()


def test_a_cliffed_document_does_not_consume_a_max_docs_slot(plan: PlanDocs) -> None:
    """18:1730: *"and does not consume a `max_docs` slot"*. Four slots, one wasted on noise."""
    plan.require()
    assert plan.grep(r"does not consume a `max_docs` slot", documents=("18-api-sketch.md",))
    candidates = [_candidate(f"d{i}", f"c:d{i}#1", 700, 1.0 - i * 0.05) for i in range(4)]
    candidates.insert(1, _candidate("noise", "c:d9#1", 700, 0.01))
    result = allocate(candidates, tier=TIER_0)
    assert len(result.packed) == TIER_0.max_docs
    assert [c.doc_key for c in result.cliffed] == ["noise"]


def test_an_exact_cite_extracted_hit_is_never_cliffed() -> None:
    """charter.md:6659's comment, with BOTH of its conjuncts. D271."""
    result = allocate(
        _two_docs(0.01, trust=Trust.EXTRACTED, channels=frozenset({"exact"})), tier=TIER_2
    )
    assert [plan.doc_key for plan in result.packed] == ["strong", "weak"]


def test_an_extracted_hit_that_is_not_an_exact_cite_is_cliffed_like_any_other() -> None:
    """The half that makes the lever work: a born-digital corpus is almost entirely EXTRACTED."""
    result = allocate(
        _two_docs(0.01, trust=Trust.EXTRACTED, channels=frozenset({"lexical"})), tier=TIER_2
    )
    assert [c.reason for c in result.cliffed] == ["below_cliff"]


def test_an_exact_hit_below_extracted_trust_is_cliffed() -> None:
    """Both conjuncts, so failing either one is enough."""
    result = allocate(
        _two_docs(0.01, trust=Trust.INFERRED, channels=frozenset({"exact"})), tier=TIER_2
    )
    assert [c.reason for c in result.cliffed] == ["below_cliff"]


@pytest.mark.parametrize("channel", sorted(CLIFF_EXEMPT_CHANNELS))
def test_both_exact_channels_exempt(channel: str) -> None:
    result = allocate(_two_docs(0.01, channels=frozenset({channel})), tier=TIER_2)
    assert result.cliffed == ()


def test_a_spine_neighbour_is_cliff_exempt_and_weighs_double() -> None:
    """18:1736: *"applied to a block reachable by `rel` from another hit; cliff-exempt."*"""
    result = allocate(_two_docs(0.01, spine=True), tier=TIER_2)
    assert result.cliffed == ()
    assert result.packed[1].weight == pytest.approx(0.01 * SPINE_BOOST)


def test_the_cliff_is_measured_against_the_top_documents_weight_and_not_a_score() -> None:
    """Weight is `score x worth`, so a low-worth document falls off a cliff a score clears."""
    footer = worth(
        layer=Layer.BODY, kind=Kind.PAGE_FOOTER, trust=Trust.EXTRACTED, quote=Quote.VERBATIM
    )
    candidates = (
        _candidate("strong", "c:d1#1", 1_200, 1.0, block_worth=MAX_WORTH),
        _candidate("footer", "c:d2#1", 1_200, 0.9, block_worth=footer),
    )
    assert 0.9 * footer < CLIFF_FRACTION * MAX_WORTH
    assert [c.reason for c in allocate(candidates, tier=TIER_2).cliffed] == ["below_cliff"]


# ---------------------------------------------------------------------------
# 11. Reserve-then-render
# ---------------------------------------------------------------------------


def test_the_reserve_is_doc_overhead_times_docs_plus_block_overhead_times_blocks(
    plan: PlanDocs,
) -> None:
    """10:724's own arithmetic: two documents and three blocks reserve `2 x 180 + 3 x 95 = 645`."""
    plan.require()
    assert plan.grep(r"2 . 180 \+ 3 . 95 = \*\*645 characters", documents=(INTERFACES,))
    candidates = (
        _candidate("a", "c:d1#1", 400, 1.0),
        _candidate("a", "c:d1#2", 400, 0.9),
        _candidate("b", "c:d2#1", 400, 0.8),
    )
    result = allocate(candidates, tier=TIER_2)
    assert result.reserved == 2 * DOC_OVERHEAD + 3 * BLOCK_OVERHEAD == 645
    assert result.pool == result.envelope - 645


def test_the_smallest_tiers_four_by_eight_reserve_is_the_documents_number(plan: PlanDocs) -> None:
    """10:726 prints it: *"1,480 characters, 12.3% of the envelope, before a single character"*."""
    plan.require()
    assert plan.grep(r"4 . 180 \+ 8 . 95 = \*\*1,480 characters", documents=(INTERFACES,))
    candidates = [
        _candidate(f"d{i}", f"c:d{i}#{j}", 300, 1.0 - i * 0.01) for i in range(4) for j in range(2)
    ]
    result = allocate(candidates, tier=TIER_0)
    assert result.reserved == 1_480
    assert result.reserved / TIER_0.max_chars == pytest.approx(0.1233, abs=5e-5)


def test_the_reserve_comes_off_before_a_single_character_of_evidence() -> None:
    """The whole of "reserve-then-render": the pool the split divides is already net of overhead."""
    candidates = tuple(_candidate("a", f"c:d1#{i}", 10_000, 1.0) for i in range(3))
    result = allocate(candidates, tier=TIER_2)
    assert result.spent <= result.pool
    assert result.spent + result.reserved <= result.envelope


def test_a_reserve_that_would_eat_the_envelope_drops_documents_rather_than_overrunning() -> None:
    """Ten documents of eight blocks each reserve 9,400 against the smallest tier's 12,000."""
    candidates = [
        _candidate(f"d{i}", f"c:d{i}#{j}", 5_000, 1.0) for i in range(10) for j in range(8)
    ]
    result = allocate(candidates, tier=TIER_0)
    assert result.reserved < result.envelope
    assert result.spent + result.reserved <= result.envelope


# ---------------------------------------------------------------------------
# 12. The split
# ---------------------------------------------------------------------------


def test_no_document_takes_more_than_the_tiers_chars_per_doc() -> None:
    candidates = tuple(_candidate("a", f"c:d1#{i}", 900, 1.0) for i in range(12))
    result = allocate(candidates, tier=TIER_0)
    assert result.packed[0].chars <= TIER_0.chars_per_doc


def test_no_document_takes_more_than_max_share_of_the_pool(plan: PlanDocs) -> None:
    """charter.md:6661: *"a valve against one god-document."*"""
    plan.require()
    assert plan.grep(r"a valve against one god-document", documents=(CHARTER,))
    candidates = (
        _candidate("god", "c:d1#1", 20_000, 1.0),
        _candidate("small", "c:d2#1", 700, 0.5),
    )
    result = allocate(candidates, tier=BUDGET_TIERS[4])
    assert result.packed[0].chars <= int(result.pool * MAX_SHARE)


def test_a_document_that_needs_less_than_its_share_carries_the_rest_forward() -> None:
    """A top-ranked 400-character document must not strand a share a lower one can use."""
    candidates = (
        _candidate("tiny", "c:d1#1", 400, 1.0),
        _candidate("big", "c:d2#1", 4_000, 0.9),
    )
    result = allocate(candidates, tier=TIER_2)
    by_key = {plan.doc_key: plan for plan in result.packed}
    assert by_key["tiny"].chars == 400
    assert by_key["big"].chars == 4_000


def test_the_split_never_funds_more_than_a_document_demands() -> None:
    candidates = (_candidate("a", "c:d1#1", 120, 1.0),)
    result = allocate(candidates, tier=TIER_2)
    assert result.packed[0].chars == 120
    assert result.unspent > 0


def test_the_unspent_pool_is_the_room_the_remaining_sections_are_funded_from(
    plan: PlanDocs,
) -> None:
    """10:584's drop order gives three sections *"from remaining room"*; this is that room."""
    plan.require()
    assert plan.grep(r"from remaining room:\s+ow:provenance", documents=(INTERFACES,))
    result = allocate((_candidate("a", "c:d1#1", 200, 1.0),), tier=TIER_2)
    assert result.unspent == result.pool - result.spent > 0


# ---------------------------------------------------------------------------
# 13. `MIN_CHARS` -- a fragment is worse than a pointer
# ---------------------------------------------------------------------------


def _crowded() -> list[Candidate]:
    """Four documents of twenty-five blocks each: the reserve alone is 10,220 of the 12,000.

    At four documents the split leaves ~378 characters apiece against a 10,000-character demand,
    which is the fragment condition; at three it leaves ~1,228, which is not. So the fixpoint runs
    exactly once, which is what these three tests are about.
    """
    return [
        _candidate(f"d{i}", f"c:d{i}#{j}", 400, 1.0 - i * 0.01) for i in range(4) for j in range(25)
    ]


def test_a_document_cut_below_min_chars_becomes_a_pointer() -> None:
    result = allocate(_crowded(), tier=TIER_0)
    assert all(plan.chars >= MIN_CHARS for plan in result.packed)
    assert [c.reason for c in result.cliffed] == ["fragment"]


def test_a_document_that_fits_entirely_below_min_chars_still_packs() -> None:
    """A 200-character table cell is a complete small thing, not a fragment. See the module."""
    result = allocate((_candidate("a", "c:d1#1", 200, 1.0),), tier=TIER_2)
    assert result.packed[0].chars == 200
    assert result.cliffed == ()


def test_the_lowest_ranked_fragment_is_dropped_first() -> None:
    """Reserve-then-render means the ranking decides who eats."""
    result = allocate(_crowded(), tier=TIER_0)
    assert [c.doc_key for c in result.cliffed if c.reason == "fragment"] == ["d3"]
    assert [plan.doc_key for plan in result.packed] == ["d0", "d1", "d2"]


def test_dropping_a_fragment_returns_its_overhead_to_the_pool() -> None:
    """The fixpoint: removing a document frees `DOC_OVERHEAD` plus its blocks' overhead."""
    result = allocate(_crowded(), tier=TIER_0)
    assert result.reserved == 3 * DOC_OVERHEAD + 75 * BLOCK_OVERHEAD
    expected = DOC_OVERHEAD * len(result.packed) + BLOCK_OVERHEAD * sum(
        len(plan.blocks) + len(plan.dropped) for plan in result.packed
    )
    assert result.reserved == expected


# ---------------------------------------------------------------------------
# 14. Whole blocks, never a partial one
# ---------------------------------------------------------------------------


def test_a_block_is_packed_whole_or_not_at_all(plan: PlanDocs) -> None:
    """13:882's P-18: *"cuts whole Answer sections and whole blocks, never mid-fence."*"""
    plan.require()
    assert plan.grep(r"whole Answer sections and whole blocks", documents=("13-quality.md",))
    candidates = tuple(_candidate("a", f"c:d1#{i}", 1_500, 1.0 - i * 0.01) for i in range(5))
    result = allocate(candidates, tier=TIER_0)
    packed = result.packed[0]
    assert packed.chars == sum(block.chars for block in packed.blocks)
    assert set(packed.blocks) | set(packed.dropped) == set(candidates)


def test_a_block_too_large_to_fit_does_not_stop_the_scan() -> None:
    """A later, smaller block still fits; stopping would waste the tail of the document."""
    candidates = (
        _candidate("a", "c:d1#1", 3_400, 1.0),
        _candidate("a", "c:d1#2", 3_400, 0.9),
        _candidate("a", "c:d1#3", 80, 0.8),
    )
    result = allocate(candidates, tier=TIER_0)
    assert [block.cite for block in result.packed[0].blocks] == ["c:d1#1", "c:d1#3"]
    assert result.packed[0].truncated


def test_a_document_reports_the_blocks_that_did_not_fit() -> None:
    candidates = tuple(_candidate("a", f"c:d1#{i}", 2_000, 1.0 - i * 0.01) for i in range(4))
    result = allocate(candidates, tier=TIER_0)
    assert result.packed[0].dropped
    assert result.packed[0].truncated


# ---------------------------------------------------------------------------
# 15. The buy pool
# ---------------------------------------------------------------------------


def test_a_section_already_mostly_packed_buys_the_rest() -> None:
    """charter.md:6664's `WHOLE_SECTION_BUY` threshold, spent from `BUY_POOL`."""
    blocks = [_candidate("a", f"c:d1#{i}", 1_100, 1.0 - i * 0.01, section="s1") for i in range(3)]
    blocks.append(_candidate("a", "c:d1#9", 300, 0.90, section="s1"))
    result = allocate(blocks, tier=TIER_0)
    assert result.buy_spent == 300
    assert [block.cite for block in result.packed[0].blocks][-1] == "c:d1#9"
    assert result.packed[0].bought == 300


def test_a_section_below_the_threshold_does_not_buy() -> None:
    blocks = [_candidate("a", "c:d1#1", 3_400, 1.0, section="s1")]
    blocks += [_candidate("a", f"c:d1#{i}", 300, 0.5, section="s1") for i in range(2, 6)]
    result = allocate(blocks, tier=TIER_0)
    assert result.buy_spent == 0


def test_an_unsectioned_block_never_buys() -> None:
    """A block with no section has no whole to complete."""
    blocks = [_candidate("a", f"c:d1#{i}", 1_100, 1.0 - i * 0.01) for i in range(3)]
    blocks.append(_candidate("a", "c:d1#9", 300, 0.90))
    assert allocate(blocks, tier=TIER_0).buy_spent == 0


def test_the_buy_pool_is_bounded_by_its_fraction_of_the_pool() -> None:
    blocks = [_candidate("a", f"c:d1#{i}", 1_100, 1.0 - i * 0.01, section="s1") for i in range(3)]
    blocks += [_candidate("a", f"c:d1#9{i}", 400, 0.5, section="s1") for i in range(6)]
    result = allocate(blocks, tier=TIER_0)
    assert result.buy_spent <= int(result.pool * BUY_POOL)


def test_the_buy_does_not_break_the_god_document_valve() -> None:
    blocks = [_candidate("a", f"c:d1#{i}", 1_100, 1.0 - i * 0.01, section="s1") for i in range(3)]
    blocks += [_candidate("a", f"c:d1#9{i}", 400, 0.5, section="s1") for i in range(6)]
    blocks.append(_candidate("b", "c:d2#1", 900, 0.6))
    result = allocate(blocks, tier=TIER_0)
    assert result.packed[0].chars <= int(result.pool * MAX_SHARE)


# ---------------------------------------------------------------------------
# 16. Determinism and totality
# ---------------------------------------------------------------------------


def test_the_document_order_is_total_and_a_weight_tie_breaks_on_first_appearance() -> None:
    """ST7's shape: `(-weight, first_index)`, and the input is already totally ordered."""
    candidates = (
        _candidate("b", "c:d2#1", 700, 0.5),
        _candidate("a", "c:d1#1", 700, 0.5),
    )
    assert [plan.doc_key for plan in allocate(candidates, tier=TIER_2).packed] == ["b", "a"]


def test_the_plan_is_a_function_of_the_candidates_and_not_of_their_grouping() -> None:
    """Interleaving one document's blocks with another's must not move a character."""
    grouped = (
        _candidate("a", "c:d1#1", 800, 1.0),
        _candidate("a", "c:d1#2", 800, 0.8),
        _candidate("b", "c:d2#1", 800, 0.9),
        _candidate("b", "c:d2#2", 800, 0.7),
    )
    interleaved = (grouped[0], grouped[2], grouped[1], grouped[3])
    assert allocate(grouped, tier=TIER_2) == allocate(interleaved, tier=TIER_2)


def test_an_empty_candidate_set_still_carries_an_envelope() -> None:
    """An Answer with no evidence still has a budget, and `ow:trailer` prints it."""
    result = allocate((), tier=TIER_2)
    assert result.packed == () and result.cliffed == ()
    assert result.envelope == TIER_2.max_chars
    assert result.docs_used == 0


def test_all_three_cliff_reasons_are_reachable_and_each_names_a_different_fact() -> None:
    """`ow:notseen` prints a different sentence for each, so each must be produced by something."""
    below = allocate(_two_docs(0.01), tier=TIER_2)
    slots = allocate(
        [_candidate(f"d{i}", f"c:d{i}#1", 700, 1.0 - i * 0.01) for i in range(6)], tier=TIER_0
    )
    assert {c.reason for c in below.cliffed} == {"below_cliff"}
    assert {c.reason for c in slots.cliffed} == {"no_slot"}
    assert {c.reason for c in allocate(_crowded(), tier=TIER_0).cliffed} == {"fragment"}


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=5),
            st.integers(min_value=1, max_value=4_000),
            st.floats(min_value=0.001, max_value=1.0, allow_nan=False),
        ),
        min_size=1,
        max_size=24,
    ),
    st.integers(min_value=0, max_value=4),
)
def test_the_allocation_never_overruns_its_envelope(
    rows: list[tuple[int, int, float]], tier_index: int
) -> None:
    """The post-condition the whole module exists for, over arbitrary candidate sets."""
    tier = BUDGET_TIERS[tier_index]
    candidates = [
        _candidate(f"d{doc}", f"c:d{doc}#{i}", chars, score)
        for i, (doc, chars, score) in enumerate(rows)
    ]
    result = allocate(candidates, tier=tier)
    assert result.spent + result.reserved <= result.envelope
    assert result.spent == sum(plan.chars for plan in result.packed)
    assert len(result.packed) <= tier.max_docs
    assert all(plan.chars <= tier.chars_per_doc for plan in result.packed)
    keys = [plan.doc_key for plan in result.packed] + [c.doc_key for c in result.cliffed]
    assert len(keys) == len(set(keys)) == len({c.doc_key for c in candidates})


# ---------------------------------------------------------------------------
# 17. The worked Answer, re-measured -- and D273
# ---------------------------------------------------------------------------


def test_the_worked_answer_is_the_length_the_document_says_it_is(plan: PlanDocs) -> None:
    """10:689: *"the 70 rendered lines, each with its newline: 3,871 characters"*."""
    plan.require()
    lines = _worked_answer(plan)
    assert len(lines) == 70
    assert len("".join(lines)) == 3_871


def test_all_eight_section_counts_reproduce(plan: PlanDocs) -> None:
    """10:693-702's table. 10:704 says both columns *"sum exactly"*, and they do."""
    plan.require()
    lines = _worked_answer(plan)
    starts = [i for i, line in enumerate(lines) if line.startswith(MARKER)]
    bounds = [0, *starts, len(lines)]
    measured = [len("".join(lines[a:b])) for a, b in itertools.pairwise(bounds)]
    assert measured == [102, 303, 1508, 549, 240, 287, 204, 678]
    assert sum(measured) == 3_871


def test_the_section_marker_is_never_an_atx_heading(plan: PlanDocs) -> None:
    """10:557: markdown-rendering MCP clients blow `####` up to H1 (codegraph #778)."""
    plan.require()
    lines = _worked_answer(plan)
    assert not any(line.startswith("#") for line in lines)
    assert sum(1 for line in lines if line.startswith(MARKER)) == 7


def test_the_evidence_section_carries_one_untrusted_frame_and_not_one_per_block(
    plan: PlanDocs,
) -> None:
    """D272. 14:603's frame is per BLOCK and carries `sha256`. This one is per SECTION."""
    plan.require()
    lines = _worked_answer(plan)
    assert sum(1 for line in lines if line.startswith("<ow:untrusted")) == 1
    assert sum(1 for line in lines if line.startswith("</ow:untrusted>")) == 1
    assert sum(1 for line in lines if line.startswith("**« ")) == 3
    opener = next(line for line in lines if line.startswith("<ow:untrusted"))
    assert "corpus=" in opener and "gen=" in opener
    assert "sha256=" not in opener and "cite=" not in opener


def test_the_measured_block_overhead_is_two_and_a_half_times_the_reserved_one(
    plan: PlanDocs,
) -> None:
    """D273, priced in the plan's own bytes: 200/271/283 measured against `BLOCK_OVERHEAD = 95`."""
    plan.require()
    lines = _worked_answer(plan)
    start = next(i for i, line in enumerate(lines) if line.startswith(MARKER + "evidence"))
    end = next(i for i, line in enumerate(lines) if line.startswith(MARKER + "provenance"))
    section = lines[start:end]
    heads = [i for i, line in enumerate(section) if line.startswith("**« ")]
    heads.append(next(i for i, line in enumerate(section) if line.startswith("</ow:untrusted")))
    overheads: list[int] = []
    for a, b in itertools.pairwise(heads):
        inside, over = False, 0
        for line in section[a:b]:
            if line.startswith("```"):
                inside = not inside
                over += len(line)
            elif not inside:
                over += len(line)
        overheads.append(over)
    assert overheads == [200, 271, 283]
    assert math.fsum(overheads) / len(overheads) > 2.5 * BLOCK_OVERHEAD


def test_the_evidence_sections_structure_costs_more_than_the_reserve_funds(plan: PlanDocs) -> None:
    """The consequence: `2 x 180 + 3 x 95 = 645` against 1,010 characters of actual structure."""
    plan.require()
    lines = _worked_answer(plan)
    start = next(i for i, line in enumerate(lines) if line.startswith(MARKER + "evidence"))
    end = next(i for i, line in enumerate(lines) if line.startswith(MARKER + "provenance"))
    inside, text = False, 0
    for line in lines[start:end]:
        if line.startswith("```"):
            inside = not inside
        elif inside:
            text += len(line)
    structure = len("".join(lines[start:end])) - text
    assert (text, structure) == (498, 1_010)
    assert structure > 2 * DOC_OVERHEAD + 3 * BLOCK_OVERHEAD


def _sections(lines: Sequence[str]) -> tuple[str, ...]:
    return tuple(line.strip().strip(STARS) for line in lines if line.startswith(MARKER))


def test_the_worked_answers_section_order_is_the_rosters(plan: PlanDocs) -> None:
    """10:563-571's roster order, which W6.6c freezes. Recorded here because the fixture is here."""
    plan.require()
    assert _sections(_worked_answer(plan)) == (
        "ow:blocking",
        "ow:evidence",
        "ow:provenance",
        "ow:related",
        "ow:sent-earlier",
        "ow:notseen",
        "ow:trailer",
    )
