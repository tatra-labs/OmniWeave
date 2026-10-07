"""`derive.anchor.native`: what a document declares about itself. 06 section 3.3, D670.

The third block of tests is the property that makes this Pass worth running: for every label
kind, the name an anchor is minted under is the name `derive.xref.pattern` captures from a
reference to it, so `ref_unresolved`'s equality join meets.
"""

from __future__ import annotations

import pytest
from omniweave_graph.native.rules import find
from omniweave_graph.view import Mark, Member
from omniweave_graph.xref.rules import find as find_refs


def anchors(
    text: str, kind: str = "heading", marks: tuple[Mark, ...] = ()
) -> list[tuple[str, str]]:
    member = Member(cite="d1#1", kind=kind, text=text, marks=marks)
    out = find([member])
    for a in out:
        if a.rule != "mark":
            assert text[a.span[0] : a.span[1]] == a.name
    return [(a.akind, a.name) for a in out]


# -- anchor marks ---------------------------------------------------------------------------------


def test_an_anchor_mark_is_an_anchor_as_declared() -> None:
    marks = (
        Mark(0, 0, "anchor", {"name": "_Toc42", "akind": "bookmark"}),
        Mark(4, 4, "anchor", {"name": "risk-factors", "akind": "section"}),
        Mark(0, 4, "bold", None),
    )
    assert anchors("Risk factors", kind="paragraph", marks=marks) == [
        ("bookmark", "_Toc42"),
        ("section", "risk-factors"),
    ]


@pytest.mark.parametrize(
    "mark",
    [
        Mark(0, 0, "anchor", {"name": "x", "akind": "chapter"}),
        Mark(0, 0, "anchor", {"name": " ", "akind": "bookmark"}),
        Mark(0, 0, "anchor", {"akind": "bookmark"}),
        Mark(0, 0, "anchor", "x"),
        Mark(0, 99, "anchor", {"name": "x", "akind": "bookmark"}),
    ],
)
def test_a_mark_that_does_not_declare_a_known_anchor_is_not_one(mark: Mark) -> None:
    assert anchors("Some text", kind="paragraph", marks=(mark,)) == []


# -- heading numbering ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1. Definitions", ("section", "1")),
        ("4.2 Indemnity", ("section", "4.2")),
        ("4.2.1) Scope", ("section", "4.2.1")),
        ("Article 7", ("section", "7")),
        ("ARTICLE IV - Covenants", ("section", "IV")),
        ("Section 12: Notices", ("section", "12")),
        ("Clause 3.1 Payment", ("section", "3.1")),
        ("Chapter 2", ("section", "2")),
    ],
)
def test_a_numbered_heading_defines_its_number(text: str, expected: tuple[str, str]) -> None:
    assert anchors(text) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "Definitions",
        "2020 Annual Report",
        "I Introduction",
        "C Corp matters",
        "Articles of Association",
        "1,000 reasons",
    ],
)
def test_not_a_numbered_heading(text: str) -> None:
    assert [a for a in anchors(text) if a[0] == "section"] == []


def test_a_bare_number_heading_alone_is_a_section() -> None:
    """`4.2` with nothing after it is still a numbered heading: the lookahead admits end of text."""
    assert anchors("4.2") == [("section", "4.2")]


def test_numbering_is_read_on_headings_and_titles_only() -> None:
    assert anchors("1. Definitions", kind="title") == [("section", "1")]
    assert anchors("1. Definitions", kind="paragraph") == []
    assert anchors("1. Definitions", kind="list_item") == []


# -- labels ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("Figure 3: Revenue by quarter", "caption", ("figure", "3")),
        ("Fig. 3a Detail", "caption", ("figure", "3a")),
        ("Table 4.1 Results", "caption", ("table", "4.1")),
        ("Tab. 2", "caption", ("table", "2")),
        ("Schedule 1 - Lenders", "heading", ("exhibit", "1")),
        ("SCHEDULE 4", "heading", ("exhibit", "4")),
        ("Exhibit C", "heading", ("exhibit", "C")),
        ("Annex II: Forms", "title", ("exhibit", "II")),
        ("Equation 3", "caption", ("equation", "3")),
    ],
)
def test_a_label_defines_its_name(text: str, kind: str, expected: tuple[str, str]) -> None:
    assert anchors(text, kind=kind) == [expected]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Table of Contents", "heading"),
        ("Schedule of Payments", "heading"),
        ("Figure 3 shows growth", "paragraph"),
        ("Revenue, see Figure 3", "caption"),
    ],
)
def test_not_a_label(text: str, kind: str) -> None:
    assert anchors(text, kind=kind) == []


def test_a_heading_can_be_numbered_and_labelled_at_once() -> None:
    assert anchors("3. Schedule 1") == [("section", "3")]
    assert anchors("Schedule 1 4.2") == [("exhibit", "1")]


# -- the two sides meet ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "kind", "reference"),
    [
        ("4.2 Indemnity", "heading", "as set out in Section 4.2 above"),
        ("Clause 3.1 Payment", "heading", "under clause 3.1"),
        ("Figure 3a Detail", "caption", "see Fig. 3a"),
        ("Table 4.1 Results", "caption", "in Table 4.1"),
        ("Schedule 1 - Lenders", "heading", "listed in Schedule 1"),
        ("Exhibit C", "heading", "attached as Exhibit C"),
        ("Equation 12", "caption", "by Eq. (12)"),
    ],
)
def test_the_anchor_name_is_the_name_a_reference_to_it_captures(
    definition: str, kind: str, reference: str
) -> None:
    [declared] = find([Member(cite="d1#1", kind=kind, text=definition)])
    [ref] = find_refs([Member(cite="d1#2", kind="paragraph", text=reference)]).refs
    assert ref.name == declared.name
    assert ref.akind == declared.akind
