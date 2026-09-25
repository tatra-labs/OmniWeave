"""The Answer document: nine sections, two orders, and a truncator that cuts whole things.

16:662's estimation basis asks for *"one fixture per section"*, and section 3 is that. The other
three families are the ones a renderer gets wrong quietly:

* **Two orders, not one.** 10:575-581 prints a funding order and a cut order and they disagree on
  `ow:provenance` -- funded first among the three, cut second. Section 2 asserts both, and asserts
  they disagree, so a reader who collapsed them into one list fails here.
* **The truncator cuts whole things.** Section 4 drives `max_chars` down to 1,000 at every one of
  the five `BUDGET_TIERS` and asserts 10:607-609's three properties: the never-dropped set survives,
  no cut lands inside a fence, and the rendered length equals the `chars=` field EXACTLY.
* **The counts are self-referential.** Section 5 asserts the substituted number against `len()` of
  the document it appears in, including the over-budget case, where the honest number is above the
  denominator printed beside it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.answer.allocate import BLOCK_OVERHEAD, DOC_OVERHEAD
from omniweave_core.answer.budget import BUDGET_TIERS, HARD_CEILING, AnswerBudget
from omniweave_core.answer.render import (
    BOLD,
    CUT_ORDER,
    NEVER_DROPPED,
    SECTION_ORDER,
    SECTIONS,
    SUMMARY_SENTINEL,
    Answer,
    ImpactRow,
    Pointer,
    RenderedBlock,
    blocks_of,
    measure,
    render,
    sections_of,
    sent_earlier_chars,
)
from omniweave_core.answer.untrusted import CLOSING_DELIMITER, NOTICE
from omniweave_core.errors import UsageError
from omniweave_core.model.enums import Quote

if TYPE_CHECKING:
    from conftest import PlanDocs

INTERFACES = "10-interfaces.md"

# The roster's own names, in 10:563-571's order.
ROSTER = (
    "status",
    "blocking",
    "evidence",
    "provenance",
    "related",
    "impact",
    "sent-earlier",
    "notseen",
    "trailer",
)


def _block(
    ordinal: int, *, doc: str = "policy.pdf", chars: int = 120, **over: object
) -> RenderedBlock:
    fields: dict[str, object] = {
        "cite": f"handbook:d7#{400 + ordinal}",
        "addr": f"p14/{ordinal}",
        "doc_uri": doc,
        "page": 14,
        "kind": "paragraph",
        "text": "x" * chars,
        "quote": Quote.VERBATIM,
        "trust": "extracted",
        "method": "text_layer",
        "origin_driver": "parse.pdf.pdfium@2",
        "byte_exact": True,
    }
    fields.update(over)
    return RenderedBlock(**fields)  # type: ignore[arg-type]


def _budget(**over: int) -> AnswerBudget:
    fields = {
        "tier_index": 2,
        "blocks_below": 500_000,
        "max_chars": 22_000,
        "chars_used": 0,
        "max_docs": 8,
        "docs_used": 1,
        "calls_allowed": 3,
        "call_ord": 1,
        "chars_deduped": 3_912,
        "doc_overhead": DOC_OVERHEAD,
        "block_overhead": BLOCK_OVERHEAD,
    }
    fields.update(over)
    return AnswerBudget(**fields)  # type: ignore[arg-type]


def _answer(**over: object) -> Answer:
    fields: dict[str, object] = {
        "state": "ok",
        "corpus": "handbook",
        "generation": 41,
        "freshness": "fresh",
        "evidence": tuple(_block(i) for i in range(3)),
        "blocking": ("> warning, with its fix.",),
        "related": ("- `handbook:d7#404` neighbour",),
        "pointers": (
            Pointer(
                "policy.pdf", (31,), ("handbook:d7#1104",), 1, 'ow_open ref="d7#1104"', "cliffed"
            ),
        ),
        "withheld": (Pointer("policy.pdf", (12,), ("d7#390", "d7#404"), 15, "", "sent_earlier"),),
        "blocks_matched": 61,
        "docs_matched": 17,
        "budget": _budget(),
        "trailer_extra": (("verdict.gates", "[]"),),
        "next_command": 'ow query --corpus handbook "notice period"',
    }
    fields.update(over)
    return Answer(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. The roster and the markers
# ---------------------------------------------------------------------------


def test_the_nine_sections_are_the_rosters_in_its_order(plan: PlanDocs) -> None:
    """10:563-571's table, read out of the document rather than retyped."""
    plan.require()
    hits = plan.grep(r"^\| `?(ow:[a-z-]+|status line)`? \| ", documents=(INTERFACES,))
    printed = tuple(
        match.group(1).replace("status line", "status").removeprefix("ow:")
        for hit in hits
        if (match := re.match(r"\| `?(ow:[a-z-]+|status line)`?", hit.text))
    )
    assert printed[: len(ROSTER)] == ROSTER
    assert SECTION_ORDER == ROSTER


def test_the_section_order_is_frozen_at_the_end_of_this_phase(plan: PlanDocs) -> None:
    """16:668 freezes *"the Answer section names and their order"* at the end of P6."""
    plan.require()
    assert plan.grep(
        r"the Answer\nsection names and their order|Answer section names",
        documents=("16-roadmap.md",),
    )
    assert len(SECTIONS) == 9


def test_no_line_of_a_rendered_answer_is_an_atx_heading(plan: PlanDocs) -> None:
    """10:557: markdown-rendering MCP clients blow `####` up to H1 (codegraph #778)."""
    plan.require()
    assert plan.grep(r"never an ATX heading", documents=(INTERFACES,))
    document = render(_answer())
    assert not any(line.startswith("#") for line in document.splitlines())


def test_every_section_carries_the_greppable_marker() -> None:
    document = render(_answer())
    for name in sections_of(document):
        assert f"{BOLD}ow:{name}{BOLD}" in document


def test_the_status_line_carries_no_marker_of_its_own() -> None:
    """It is first and it is not `**ow:status**`: 10:566 gives it a shape, not a name."""
    document = render(_answer())
    assert f"{BOLD}ow:status{BOLD}" not in document
    assert document.splitlines()[0].startswith("ow/1 ")


def test_related_is_query_only_and_impact_is_open_only(plan: PlanDocs) -> None:
    """10:568-569. No Answer carries both, which is why they share a rank in the cut order."""
    plan.require()
    query = sections_of(render(_answer(surface="query")))
    opened = sections_of(
        render(
            _answer(
                surface="open",
                impact=(ImpactRow("deck.pptx", 3, "u04", "e17", "quote", True, 41, False),),
            )
        )
    )
    assert "related" in query and "impact" not in query
    assert "impact" in opened and "related" not in opened


def test_a_section_with_nothing_in_it_carries_no_marker() -> None:
    """A marker with nothing under it is a section a reader would try to interpret."""
    document = render(_answer(related=(), pointers=()))
    assert "related" not in sections_of(document)
    assert "notseen" not in sections_of(document)


# ---------------------------------------------------------------------------
# 2. Two orders, and the fact that they disagree
# ---------------------------------------------------------------------------


def test_the_never_dropped_four_are_the_ones_the_drop_block_names(plan: PlanDocs) -> None:
    """10:576: the status line, `ow:blocking`, `ow:sent-earlier` and `ow:trailer`."""
    plan.require()
    hits = plan.grep(r"charged first, never dropped:", documents=(INTERFACES,))
    assert hits
    named = {name.removeprefix("ow:") for name in re.findall(r"ow:[a-z-]+", hits[0].text)}
    assert named | {"status"} == NEVER_DROPPED
    assert {"status", "blocking", "sent-earlier", "trailer"} == NEVER_DROPPED


def test_the_never_dropped_set_is_derived_from_the_funding_column() -> None:
    """Not written twice: a section charged first or allocated is not funded from remaining room."""
    assert {spec.name for spec in SECTIONS if spec.charge == "first"} == NEVER_DROPPED
    assert {spec.name for spec in SECTIONS if spec.charge == "allocated"} == {"evidence"}
    assert "evidence" not in NEVER_DROPPED
    assert not next(spec for spec in SECTIONS if spec.name == "evidence").droppable


def test_the_cut_order_is_the_one_the_drop_block_prints(plan: PlanDocs) -> None:
    """10:579-581: `ow:related|ow:impact -> ow:provenance -> ow:notseen`."""
    plan.require()
    hits = plan.grep(r"cut order:", documents=(INTERFACES,))
    assert hits
    assert CUT_ORDER == (("related", "impact"), ("provenance",), ("notseen",))


def test_the_funding_order_and_the_cut_order_disagree_on_provenance(plan: PlanDocs) -> None:
    """10:577 funds `ow:provenance` FIRST of the three and 10:579 cuts it SECOND."""
    plan.require()
    hits = plan.grep(r"from remaining room:", documents=(INTERFACES,))
    assert hits
    funded = re.findall(r"ow:([a-z-]+)", hits[0].text)
    cut = [name for rank in CUT_ORDER for name in rank]
    assert funded[0] == "provenance"
    assert cut.index("provenance") > cut.index("related")


def test_related_is_cut_before_provenance() -> None:
    answer = _answer()
    full = len(render(answer))
    document = render(answer, max_chars=full - 20)
    assert "related" not in sections_of(document)
    assert "provenance" in sections_of(document)


def test_provenance_collapses_to_a_count_before_notseen_goes() -> None:
    """10:580: `ow:provenance` *"(collapses to a count)"* -- a cut, not a drop."""
    answer = _answer()
    document = render(answer, max_chars=len(render(answer)) - 300)
    assert "provenance" in sections_of(document)
    assert "rows omitted for room" in document
    assert "| cite | doc |" not in document


def test_notseen_is_the_last_section_to_go() -> None:
    answer = _answer()
    sequence = []
    for budget in range(len(render(answer)), 900, -25):
        present = sections_of(render(answer, max_chars=budget))
        if not sequence or present != sequence[-1]:
            sequence.append(present)
    order = [name for present in sequence for name in ("related", "notseen") if name not in present]
    assert order.index("related") < order.index("notseen")


# ---------------------------------------------------------------------------
# 3. One fixture per section
# ---------------------------------------------------------------------------


def test_the_status_line_is_the_shape_the_roster_prints(plan: PlanDocs) -> None:
    """10:566's field roster, and 10:617's own width: the worked status line is 102 characters."""
    plan.require()
    line = render(_answer()).splitlines()[0]
    for field in ("corpus=", "blocks=", "docs=", "chars=", "calls=", "spend=", "scorer="):
        assert field in line
    assert line.startswith("ow/1 ok corpus=handbook@41 fresh ")
    worked = plan.lines(INTERFACES)[616]
    assert len(worked) == 100
    assert len(line) == len(worked)
    assert (
        measure("".join(plan.text(INTERFACES).splitlines(keepends=True)[616:686]))["status"] == 102
    )


def test_blocking_is_charged_first_and_prints_what_it_was_given() -> None:
    document = render(_answer(blocking=("> the banner.", "> its fix.")))
    assert (
        f"{BOLD}ow:blocking{BOLD}" + chr(10) + "> the banner." + chr(10) + "> its fix." in document
    )


def test_evidence_is_wrapped_once_and_carries_the_notice() -> None:
    """W6.6b's frame: one opener, one close, the data-not-instruction line first."""
    document = render(_answer())
    assert document.count("<ow:untrusted") == 1
    assert document.count(CLOSING_DELIMITER) == 1
    assert NOTICE in document


def test_each_evidence_block_carries_a_header_an_advisory_and_a_fence() -> None:
    document = render(_answer(evidence=(_block(0),)))
    body = document.split(f"{BOLD}ow:evidence{BOLD}")[1].split(f"{BOLD}ow:provenance{BOLD}")[0]
    assert body.count("**« ") == 1
    assert "> Byte-exact: these bytes equal the source." in body
    assert body.count("```text") == 1


def test_a_block_that_is_not_byte_exact_gets_the_weaker_advisory() -> None:
    """SV13: the predicate is `byte_exact`, not the tier -- a claim without the proof is weaker."""
    document = render(_answer(evidence=(_block(0, byte_exact=False),)))
    assert "Byte-exact" not in document
    assert "Do not present this as a verbatim quote." in document


def test_a_defanged_block_is_marked_in_its_own_header(plan: PlanDocs) -> None:
    """10:599: *"A separate section would have been droppable"*, and a droppable disclosure is
    none."""
    plan.require()
    assert plan.grep(
        r"A defanged block is marked inline, not in a section of its own", documents=(INTERFACES,)
    )
    document = render(_answer(evidence=(_block(0, defanged=True),), defanged_blocks=1))
    assert "ow:defanged" in blocks_of(document)[0]
    assert f"{BOLD}ow:defanged{BOLD}" not in document


def test_provenance_is_one_row_per_rendered_block_with_eleven_columns(plan: PlanDocs) -> None:
    """10:657's header: cite, doc, page, addr, kind, quote, trust, method, driver, score, restr."""
    plan.require()
    header = plan.grep(r"^\| cite \| doc \| page \| addr \| kind \|", documents=(INTERFACES,))
    assert header
    document = render(_answer())
    assert header[0].text in document
    rows = [line for line in document.splitlines() if line.startswith("| handbook:")]
    assert len(rows) == 3
    assert rows[0].count("|") == 12


def test_related_is_the_neighbourhood_and_prints_what_it_was_given() -> None:
    document = render(_answer(related=("- `handbook:e118` 14 mentions",)))
    assert f"{BOLD}ow:related{BOLD}" + chr(10) + "- `handbook:e118` 14 mentions" in document


def test_impact_marks_a_proved_quote_and_an_older_generation() -> None:
    """10:766: the surface prints `(proved)` because a reader cannot tell it from a declaration."""
    rows = (
        ImpactRow("deck.pptx", 3, "u04", "e17", "quote", True, 41, False),
        ImpactRow("handbook.docx", 1, "u11", "e08", "paraphrase", False, 40, True),
    )
    document = render(_answer(surface="open", impact=rows))
    assert "verbatim (proved)" in document
    assert "older gen" in document


def test_sent_earlier_says_why_the_copy_is_still_exact() -> None:
    """10:666-668's two clauses, which are the two facts `withhold()` checks."""
    document = render(_answer())
    assert f"{BOLD}Already sent earlier in this conversation:{BOLD}" in document
    assert "the content digest is unchanged and the source has not been edited" in document
    assert "do NOT Read this file." in document


def test_notseen_carries_the_call_that_fetches_it() -> None:
    """10:671-672: a pointer without its `ow_open` line is a dead end."""
    document = render(_answer())
    assert "matched, below the byte cliff." in document
    assert '`ow_open ref="d7#1104"`' in document


def test_the_trailer_aligns_every_key_and_carries_the_verdict(plan: PlanDocs) -> None:
    """10:676-686's `key = value` block, with the `=` in one column."""
    plan.require()
    document = render(_answer())
    trailer = document.split(f"{BOLD}ow:trailer{BOLD}" + chr(10))[1].splitlines()
    assert trailer[0].startswith("verdict.state      = ok")
    columns = {line.index("= ") for line in trailer if "= " in line}
    assert len(columns) == 1
    assert any(line.startswith("budget ") for line in trailer)
    assert any(line.startswith("next ") for line in trailer)


def test_the_two_safety_counts_share_a_trailer_line(plan: PlanDocs) -> None:
    """10:684 prints them together: `defanged_blocks = 0   instruction_shaped = 0`."""
    plan.require()
    assert plan.grep(r"defanged_blocks    = 0   instruction_shaped = 0", documents=(INTERFACES,))
    document = render(_answer(defanged_blocks=2, instruction_shaped=1))
    assert "defanged_blocks    = 2   instruction_shaped = 1" in document


# ---------------------------------------------------------------------------
# 4. The truncator -- 10:607-609's three properties, at every tier
# ---------------------------------------------------------------------------


def _wide(blocks: int = 12, chars: int = 900) -> Answer:
    return _answer(evidence=tuple(_block(i, chars=chars) for i in range(blocks)))


@pytest.mark.parametrize("tier_index", range(len(BUDGET_TIERS)))
def test_the_never_dropped_set_survives_at_a_thousand_characters(tier_index: int) -> None:
    """10:607: the property test runs *"at every one of the five `BUDGET_TIERS`"*."""
    document = render(_wide(), max_chars=min(1_000, BUDGET_TIERS[tier_index].max_chars))
    present = set(sections_of(document)) | {"status"}
    assert present >= NEVER_DROPPED


@pytest.mark.parametrize("tier_index", range(len(BUDGET_TIERS)))
def test_no_cut_lands_inside_a_fence(tier_index: int) -> None:
    """10:608. A fence left open would make the rest of the Answer read as document text."""
    document = render(_wide(), max_chars=min(1_000, BUDGET_TIERS[tier_index].max_chars))
    assert document.count("```text") == document.count("```") - document.count("```text")


@pytest.mark.parametrize("budget", [1_000, 1_500, 2_500, 4_000, 8_000, 22_000])
def test_the_rendered_length_equals_the_chars_field_exactly(budget: int) -> None:
    """10:609's third property, and the whole reason the sentinel is fixed-width."""
    document = render(_wide(), max_chars=budget)
    printed = int(re.search(r"chars=\s*(\d+)/", document).group(1))  # type: ignore[union-attr]
    assert printed == len(document)


def test_truncation_cuts_whole_blocks() -> None:
    """13:882's P-18: whole sections and whole blocks, never mid-fence."""
    answer = _wide()
    document = render(answer, max_chars=4_000)
    kept = blocks_of(document)
    assert 0 < len(kept) < len(answer.evidence)
    for header in kept:
        cite = header.split(" · ")[0].removeprefix("**« ")
        assert f"**« {cite}" in document


def test_the_blocks_that_survive_are_the_top_of_the_ranking() -> None:
    """The front of the list is the answer; the truncator takes from the back."""
    answer = _wide()
    kept = blocks_of(render(answer, max_chars=4_000))
    assert kept == blocks_of(render(answer))[: len(kept)]


def test_one_evidence_block_always_survives() -> None:
    """An `ow:evidence` marker with nothing under it is worse than one block over budget."""
    document = render(_wide(), max_chars=1_000)
    assert len(blocks_of(document)) == 1


def test_an_answer_may_be_over_its_budget_and_says_so() -> None:
    """The never-dropped four plus one block can exceed 1,000, and none of them may go."""
    document = render(_wide(), max_chars=1_000)
    assert len(document) > 1_000
    assert f"chars={len(document):>5}/1000" in document


def test_the_counts_in_the_status_line_are_post_truncation() -> None:
    """10:588: the honest count is only known after truncation."""
    answer = _wide()
    document = render(answer, max_chars=4_000)
    kept = len(blocks_of(document))
    assert f"blocks={kept}/61" in document
    assert kept < len(answer.evidence)


@given(st.integers(min_value=1_000, max_value=HARD_CEILING))
def test_rendering_is_total_over_every_legal_budget(budget: int) -> None:
    document = render(_wide(), max_chars=budget)
    assert SUMMARY_SENTINEL not in document
    assert document.endswith("\n")
    assert set(sections_of(document)) <= set(SECTION_ORDER)


# ---------------------------------------------------------------------------
# 5. The sentinel
# ---------------------------------------------------------------------------


def test_the_sentinel_is_five_characters_wide(plan: PlanDocs) -> None:
    """10:593: *"five characters, the decimal width of `HARD_CEILING = 24_000`"*."""
    plan.require()
    assert plan.grep(r"width of `HARD_CEILING = 24_000`", documents=(INTERFACES,))
    assert len(SUMMARY_SENTINEL) == len(str(HARD_CEILING))


def test_substitution_is_length_preserving() -> None:
    """The count is printed right-aligned into exactly the room the sentinel held."""
    document = render(_answer())
    assert f"chars={len(document):>5}/" in document


def test_both_self_referential_counts_are_substituted(plan: PlanDocs) -> None:
    """10:591: *"Two of those substituted counts are the `chars=` fields"*, status line and
    trailer."""
    plan.require()
    assert plan.grep(
        r"Two of those substituted counts are the `chars=` fields", documents=(INTERFACES,)
    )
    document = render(_answer())
    assert document.count(f"{len(document):>5}/22000") == 2


def test_the_worked_answer_prints_the_leading_space_this_produces(plan: PlanDocs) -> None:
    """10:596: *"why the worked example below prints `chars= 3871/22000` with a leading space"*."""
    plan.require()
    assert plan.grep(r"chars= 3871/22000", documents=(INTERFACES,))
    assert f"{3871:>5}" == " 3871"


def test_a_nul_in_the_evidence_is_refused_rather_than_mis_substituted() -> None:
    """Any printable filler could be a run a document contains; a stray NUL is an internal error."""
    with pytest.raises(ValueError, match="NUL character"):
        render(_answer(evidence=(_block(0, text="before\x00after"),)))


def test_a_document_above_the_hard_ceiling_is_refused() -> None:
    """`HARD_CEILING` is five digits, so a sixth would break the fixed-width substitution."""
    with pytest.raises(ValueError, match="above HARD_CEILING"):
        render(_wide(blocks=200, chars=4_000), max_chars=HARD_CEILING + 50_000)


# ---------------------------------------------------------------------------
# 6. `sections=` narrows, and cannot drop what is charged first
# ---------------------------------------------------------------------------


def test_sections_narrows_the_render() -> None:
    document = render(_answer(), sections=frozenset(NEVER_DROPPED | {"evidence"}))
    assert set(sections_of(document)) == {"blocking", "evidence", "sent-earlier", "trailer"}


def test_sections_cannot_reorder_because_it_is_a_set() -> None:
    """18:586: *"it cannot reorder"* -- structurally, not by a check."""
    wanted = NEVER_DROPPED | {"evidence", "provenance"}
    first = render(_answer(), sections=frozenset(wanted))
    second = render(_answer(), sections=frozenset(sorted(wanted, reverse=True)))
    assert first == second


@pytest.mark.parametrize("dropped", sorted(NEVER_DROPPED))
def test_dropping_a_never_dropped_section_is_refused(dropped: str) -> None:
    """18:588: `UsageError(OW_SECTION_NOT_DROPPABLE, OW-A-018)`."""
    with pytest.raises(UsageError, match="charges first and never drops") as caught:
        render(_answer(), sections=frozenset(set(SECTION_ORDER) - {dropped}))
    assert caught.value.code() == "OW_SECTION_NOT_DROPPABLE"
    assert caught.value.fix


def test_the_refusal_names_the_section_and_a_way_out() -> None:
    with pytest.raises(UsageError) as caught:
        render(_answer(), sections=frozenset({"evidence"}))
    assert "blocking" in str(caught.value)
    assert "drop the argument" in caught.value.fix


# ---------------------------------------------------------------------------
# 7. The partition sums, which is what makes the measured fixture usable
# ---------------------------------------------------------------------------


def test_the_per_section_counts_sum_to_the_document(plan: PlanDocs) -> None:
    """10:704: *"Both columns sum exactly"*, because every boundary is a blank line."""
    plan.require()
    assert plan.grep(r"Both columns sum exactly", documents=(INTERFACES,))
    document = render(_answer())
    counts = measure(document)
    assert sum(counts.values()) == len(document)
    assert tuple(counts) == ("status", *sections_of(document))


def test_measure_reproduces_the_worked_answers_eight_counts(plan: PlanDocs) -> None:
    """The same partition, run over 10:617-686 rather than over a rendered one."""
    plan.require()
    lines = plan.text(INTERFACES).splitlines(keepends=True)
    worked = "".join(lines[616:686])
    assert list(measure(worked).values()) == [102, 303, 1508, 549, 240, 287, 204, 678]
    assert sum(measure(worked).values()) == 3_871


@pytest.mark.parametrize(
    ("cites", "blocks", "named"),
    [
        (("d7#390", "d7#404"), 15, "d7#390\u2013d7#404"),
        (("d1#3", "d1#2"), 2, "d1#3, d1#2"),
        (("d1#1", "d1#5", "d1#9"), 3, "d1#1, d1#5, d1#9"),
        (("d1#1", "d1#2", "d1#3", "d1#4"), 9, "d1#1, d1#2, d1#3, d1#4 and 5 more"),
    ],
)
def test_a_sent_earlier_row_is_a_range_only_in_the_worked_examples_shape(
    cites: tuple[str, ...], blocks: int, named: str
) -> None:
    """D535. A range claims every block between its ends was sent, so it is printed only for two
    cites standing for more blocks than two -- 10:666's `d7#390`-`d7#404` for fifteen."""
    pointer = Pointer("policy.pdf", (12,), cites, blocks, "", "sent_earlier")
    document = render(
        Answer(state="ok", corpus="c", generation=1, freshness="fresh", withheld=(pointer,))
    )
    assert f"`policy.pdf` {named} (p.12)" in document
    assert sent_earlier_chars(pointer) > 0
