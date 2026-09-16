"""`omniweave_core.retrieve.channels` -- the sanitiser's six rows and the ladder's nine grades.

07:1310 prints the transform table and 07:1259 the ladder; both are transcribed here against
`_plan/` rather than retyped, because every row of the first is a recall decision and every grade of
the second is an ordering one.

The two tests that matter most are negative. `test_a_reference_without_a_number_is_not_a_reference`
holds the one character that keeps the lift from eating prose, and
`test_the_forty_tier_does_not_tie_the_literal_match` is 16-roadmap.md:675's freeze item stated as an
inequality rather than as a comment.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import UsageError
from omniweave_core.limits import MAX_QUERY_CHARS, MAX_QUERY_REFS, MAX_QUERY_TERMS
from omniweave_core.retrieve import channels as ch

if TYPE_CHECKING:
    from conftest import PlanDocs

DOC = "07-store-and-retrieval.md"
SECTION = "§"


# ---------------------------------------------------------------------------
# The ladder, against the document that prints it
# ---------------------------------------------------------------------------


def test_the_ladder_is_the_nine_grades_the_plan_prints(plan: PlanDocs) -> None:
    """07:1259's `IDENTITY_LADDER`, read out of the fence rather than retyped."""
    plan.require()
    for body in plan.fences(DOC, "python"):
        if "IDENTITY_LADDER" not in body:
            continue
        stated = dict(re.findall(r'"([a-z_]+)":\s*(\d+)', body.split("IDENTITY_LADDER")[1]))
        assert {name: int(grade) for name, grade in stated.items()} == dict(ch.IDENTITY_LADDER)
        return
    pytest.fail("no python fence in 07 prints IDENTITY_LADDER")


def test_the_three_fifty_grades_are_three_different_measurements() -> None:
    """A cite, an addr and a document URI all grade 50 and `grades` says which one measured."""
    fifties = [name for name, grade in ch.IDENTITY_LADDER.items() if grade == 50]
    assert fifties == ["cite_exact", "addr_exact", "doc_uri_exact"]


def test_the_forty_tier_does_not_tie_the_literal_match() -> None:
    """16-roadmap.md:675's freeze item, as an inequality.

    A punctuation-different label reaches 40; a casefold-different one reaches 45; and 07:1265's
    own worked failure -- *"'Table 3.2 (revised)' tying with 'Table 3.2'"* -- reaches neither."""
    literal = ch.IDENTITY_LADDER[ch.grade_title("Table 3.2", "TABLE 3.2")]
    punctuated = ch.IDENTITY_LADDER[ch.grade_title("Table 3.2", "Table 3-2")]
    revised = ch.IDENTITY_LADDER[ch.grade_title("Table 3.2", "Table 3.2 (revised)")]
    assert literal == 45
    assert punctuated == 40
    assert revised == 30
    assert literal > punctuated > revised


def test_a_label_that_shares_nothing_grades_none() -> None:
    assert ch.grade_title("Parental leave", "Statutory sick pay") == "none"
    assert ch.IDENTITY_LADDER["none"] == 0


def test_an_empty_label_grades_none_rather_than_a_prefix() -> None:
    """Every string starts with `""`, so a container with no label would otherwise grade 30."""
    assert ch.grade_title("anything", "") == "none"


def test_the_cite_carries_its_own_doc_ord() -> None:
    """D240: `block_cite` is `UNIQUE(doc_ord, cite)`, so the lookup needs both columns."""
    assert ch.cite_doc_ord("d7#412") == 7
    assert ch.cite_doc_ord("handbook") is None


# ---------------------------------------------------------------------------
# The six transforms of 07:1310
# ---------------------------------------------------------------------------


def test_the_typographic_marks_become_separators() -> None:
    """07:1316: *"`unicode61` drops them anyway; keeping them creates empty tokens"*."""
    made = ch.sanitize("a ¶ b — c † d")
    assert made.terms == ("a", "b", "c", "d")


def test_a_soft_hyphen_and_a_line_broken_word_fold_to_the_unbroken_form() -> None:
    """07:1317: *"a line-broken word must match its unbroken form"*."""
    assert ch.sanitize("hy­phen").terms == ("hyphen",)
    assert ch.sanitize("line-\nbroken").terms == ("linebroken",)


def test_fts_syntax_is_stripped_and_bare_operators_go_with_it() -> None:
    """07:1318: *"a user cannot inject FTS5 syntax"*. Lower-case `and` is a word and stays."""
    made = ch.sanitize('lease AND rent NOT "quoted phrase" (grouped) col^2')
    assert "AND" not in made.terms
    assert "NOT" not in made.terms
    assert made.terms == ("lease", "rent", "quoted", "phrase", "grouped", "col", "2")
    assert "and" in ch.sanitize("salt and pepper").terms


def test_the_four_printed_shapes_are_lifted_and_three_of_them_carry_an_akind() -> None:
    """07:1319's row. `d7#412` is the fourth and goes to `idents` -- D239."""
    made = ch.sanitize(f"see {SECTION}4.2(b) and Fig. 3a and GL-4471 in d7#412")
    assert {akind: name for name, akind in made.refs} == {
        "clause": "4_2_b",
        "figure": "fig_3a",
        "identifier": "gl_4471",
    }
    assert made.idents == ("d7#412",)
    assert "3a" not in made.terms


def test_a_reference_without_a_number_is_not_a_reference() -> None:
    """The one character that keeps the lift out of prose: every tail must start with a digit."""
    made = ch.sanitize("the table shows the figure of merit")
    assert made.refs == ()
    assert "table" in made.terms
    assert "figure" in made.terms


def test_a_cjk_run_is_bigrammed_and_a_lone_ideograph_survives() -> None:
    """07:1320: *"`unicode61` does not segment CJK"*. Overlapping, so an odd offset matches."""
    assert ch.bigrams("合同条款") == ["合同", "同条", "条款"]
    assert ch.bigrams("合") == ["合"]
    assert ch.sanitize("合同条款 terms").terms == ("合同", "同条", "条款", "terms")


def test_an_unknown_field_prefix_passes_through_as_plain_text() -> None:
    """07:1321: *"so `TODO:` returns results"*. The rule is the field NAME, not the colon."""
    made = ch.sanitize("TODO: ship it foo:bar")
    assert made.fields == {}
    assert "TODO" in made.terms
    assert "foo" in made.terms and "bar" in made.terms


# ---------------------------------------------------------------------------
# The eight-field DSL
# ---------------------------------------------------------------------------


def test_the_dsl_is_the_eight_fields_the_plan_names(plan: PlanDocs) -> None:
    """07:1319: *"The field DSL is `kind: page: doc: layer: trust: quote: sec: lang:`"*."""
    plan.require()
    hits = plan.grep(r"^`MAX_QUERY_TERMS = 64`", documents=(DOC,))
    assert len(hits) == 1
    stated = plan.lines(DOC)[hits[0].line]
    assert tuple(re.findall(r"(\w+):", stated.split("`")[1])) == ch.DSL_FIELDS


def test_a_field_clause_leaves_the_text_and_carries_its_value() -> None:
    made = ch.sanitize("kind:table page:14 lease terms")
    assert dict(made.fields) == {"kind": "table", "page": "14"}
    assert made.terms == ("lease", "terms")


def test_a_field_with_no_value_is_text_and_not_a_filter() -> None:
    """`kind:` alone asked for nothing; dropping the word would answer a different query."""
    made = ch.sanitize("kind: lease")
    assert made.fields == {}
    assert "kind" in made.terms


def test_this_module_validates_no_field_value() -> None:
    """One home for "what is a legal `Kind`", and it is `omniweave_core.model.enums`."""
    assert dict(ch.sanitize("kind:not_a_kind").fields) == {"kind": "not_a_kind"}


# ---------------------------------------------------------------------------
# The three ceilings
# ---------------------------------------------------------------------------


def test_a_query_past_max_query_chars_is_refused_rather_than_cut() -> None:
    with pytest.raises(UsageError) as caught:
        ch.sanitize("x " * MAX_QUERY_CHARS)
    assert str(MAX_QUERY_CHARS) in str(caught.value)


def test_terms_past_max_query_terms_are_dropped_and_the_drop_is_reported() -> None:
    """A query silently cut to 64 terms is a recall loss that presents as absence."""
    made = ch.sanitize(" ".join(f"term{index}" for index in range(MAX_QUERY_TERMS + 6)))
    assert len(made.terms) == MAX_QUERY_TERMS
    assert len(made.dropped) == 6
    assert made.truncated


def test_refs_past_max_query_refs_are_dropped_and_reported() -> None:
    """`MAX_QUERY_REFS = 16` is about the `exact` Channel's one-statement form (07:1283)."""
    made = ch.sanitize(" ".join(f"GL-{index}" for index in range(MAX_QUERY_REFS + 3)))
    assert len(made.refs) == MAX_QUERY_REFS
    assert len(made.dropped) == 3


def test_a_query_that_is_only_a_reference_yields_no_terms() -> None:
    """The lift is a move, not a copy: what went to `exact` is gone from FTS."""
    made = ch.sanitize("GL-4471")
    assert made.terms == ()
    assert made.refs == (("gl_4471", "identifier"),)


# ---------------------------------------------------------------------------
# Order of operations
# ---------------------------------------------------------------------------


def test_the_lift_runs_before_the_fold_or_the_reference_would_be_destroyed() -> None:
    """`TO_SPACE` holds `§` and `FTS_SYNTAX` holds `(` and `)`, so a fold-first sanitiser
    would hand the `exact` Channel nothing and FTS a handful of digits."""
    made = ch.sanitize(f"{SECTION}4.2(b)")
    assert made.refs == (("4_2_b", "clause"),)
    assert made.terms == ()


def test_the_soft_hyphen_fold_runs_before_the_syntax_strip() -> None:
    """`-` is in `FTS_SYNTAX`, so a strip-first sanitiser deletes the join it is meant to make."""
    assert ch.sanitize("line-\nbroken").terms == ("linebroken",)


def test_the_sanitiser_is_deterministic() -> None:
    """It runs in phase 2 and its output is inside no digest, but a plan that re-ran it and got a
    different `ChannelInput` would make one snapshot serve two queries."""
    text = f"{SECTION}4.2 lease AND rent kind:table 合同条款 d7#412"
    assert ch.sanitize(text) == ch.sanitize(text)


# ---------------------------------------------------------------------------
# The lexical weights, which W6.2b spends
# ---------------------------------------------------------------------------


def test_the_three_bm25_weights_are_the_ones_the_plan_prints(plan: PlanDocs) -> None:
    """07:1294, and 07:1293 calls them *"the one place 'D5 owns the BM25 weights' is
    discharged"*."""
    plan.require()
    hits = plan.grep(r"^W_BODY = 1\.0 ; W_HEAD = 6\.0 ; SPINE_DECAY = 0\.6", documents=(DOC,))
    assert len(hits) == 1
    assert (ch.W_BODY, ch.W_HEAD, ch.SPINE_DECAY) == (1.0, 6.0, 0.6)
