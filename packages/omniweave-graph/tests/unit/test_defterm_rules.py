"""`derive.anchor.defterm`'s rules: 06-structure-extraction.md section 3.5 and D666's readings.

The wire is `test_defterm_driver.py`'s. Every definition any test here finds is also checked to
carry a span that slices its own term out of the block, because that span is what the host
bounds-checks and stores.
"""

from __future__ import annotations

import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from omniweave_core.ident import normalize_key
from omniweave_graph.defterm.rules import (
    DEFTERM_MAX_PER_BLOCK,
    Alias,
    Definition,
    find,
    is_glossary_heading,
    key_form,
)
from omniweave_graph.view import Cell, Member


def defs(*texts: str, kind: str = "paragraph", heading: str | None = None) -> list[Definition]:
    members = [Member(cite=f"d1#{i}", kind=kind, text=t) for i, t in enumerate(texts)]
    found = find(members, [] if heading is None else [heading])
    for d in found.definitions:
        text = members[int(d.cite.split("#")[1])].text or ""
        assert text[d.span[0] : d.span[1]] == d.term
    return list(found.definitions)


def terms(*texts: str, **kw: str) -> list[str]:
    return [d.term for d in defs(*texts, **kw)]


def kinds(d: Definition) -> list[tuple[str, str]]:
    return [(a.surface, a.alias_kind) for a in d.aliases]


# -- the four rows of 06:1119-1124 ----------------------------------------------------------------


def test_copular_mints_the_canonical_alias_and_keeps_the_definition_as_context() -> None:
    [d] = defs('"Indemnified Party" means any Person entitled to indemnification.')
    assert (d.term, d.rule) == ("Indemnified Party", "copular")
    assert kinds(d) == [("Indemnified Party", "canonical")]
    assert d.description == "any Person entitled to indemnification."
    assert d.span == (1, 18)


def test_a_parenthetical_abbreviation_mints_the_expansion_and_the_abbreviation() -> None:
    [d] = defs('International Business Machines Corporation ("IBM") is a party.')
    assert (d.term, d.rule, d.description) == ("IBM", "parenthetical", None)
    assert kinds(d) == [
        ("International Business Machines Corporation", "expansion"),
        ("IBM", "abbrev"),
    ]


def test_hereinafter_mints_the_variant_and_the_abbreviation() -> None:
    [d] = defs('Acme Holdings Ltd. (hereinafter, the "Company") agrees.')
    assert (d.term, d.rule) == ("Company", "hereinafter")
    assert kinds(d) == [("Acme Holdings Ltd.", "variant"), ("Company", "abbrev")]


def test_a_glossary_row_mints_the_canonical_alias() -> None:
    [d] = defs(
        "Affiliate: any entity controlling a party.", kind="list_item", heading="Definitions"
    )
    assert (d.term, d.rule) == ("Affiliate", "glossary")
    assert kinds(d) == [("Affiliate", "canonical")]
    assert d.description == "any entity controlling a party."


# -- copular --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb",
    [
        "means",
        "shall mean",
        "refers to",
        "is defined as",
        "has the meaning",
        "shall have the meaning",
        "have the meanings",
        "MEANS",
    ],
)
def test_each_copular_verb_defines(verb: str) -> None:
    assert terms(f'"Closing Date" {verb} the date set out below.') == ["Closing Date"]


def test_up_to_three_words_may_stand_between_the_term_and_the_verb() -> None:
    assert terms('"Agreement" as used herein means this agreement.') == ["Agreement"]
    assert terms('"Agreement" as is used herein means this agreement.') == []


def test_punctuation_attached_to_the_quote_is_not_a_word() -> None:
    assert terms('"Agreement"), as amended, means this agreement.') == ["Agreement"]


def test_a_sentence_end_between_the_term_and_the_verb_stops_the_match() -> None:
    assert terms('He wrote "Agreement". It means nothing.') == []


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("“Business Day” means a weekday.", "Business Day"),
        ("‘Business Day’ means a weekday.", "Business Day"),
    ],
)
def test_curly_quotes_are_quotes(text: str, term: str) -> None:
    assert terms(text) == [term]


def test_straight_single_quotes_are_apostrophes() -> None:
    assert terms("'Business Day' means a weekday.") == []


def test_a_quoted_span_longer_than_eighty_characters_is_a_quotation() -> None:
    assert terms(f'"{"x" * 80}" means a term.') == ["x" * 80]
    assert terms(f'"{"x" * 81}" means a term.') == []


def test_the_trailing_context_is_at_most_512_characters() -> None:
    [d] = defs('"Lender" means ' + "y" * 600)
    assert d.description == "y" * 512


def test_no_trailing_context_is_none_not_an_empty_string() -> None:
    [d] = defs('"Lender" means')
    assert d.description is None


# -- the capitalised run --------------------------------------------------------------------------


def test_a_sentence_end_stops_the_run_and_an_abbreviation_does_not() -> None:
    [d] = defs('It was signed. Bank of America, N.A. (the "Bank") pays.')
    assert kinds(d)[0] == ("Bank of America, N.A.", "expansion")
    [d] = defs('He signed the Agreement. Bank of America ("BOA") pays.')
    assert kinds(d)[0] == ("Bank of America", "expansion")
    [d] = defs('Parties: Bank of America ("BOA") pays.')
    assert kinds(d)[0] == ("Bank of America", "expansion")
    [d] = defs('U.S. Steel Corporation ("USS") makes steel.')
    assert kinds(d)[0] == ("U.S. Steel Corporation", "expansion")


def test_a_lower_case_word_ends_the_run_and_a_connector_never_starts_it() -> None:
    [d] = defs('Payments to International Business Machines ("IBM") clear.')
    assert kinds(d)[0] == ("International Business Machines", "expansion")
    [d] = defs('the of Acme Widgets ("AWX") here.')
    assert kinds(d)[0] == ("Acme Widgets", "expansion")


def test_a_run_with_a_digit_led_token() -> None:
    [d] = defs('3M Company ("3MC") sells tape.')
    assert kinds(d)[0] == ("3M Company", "expansion")


def test_the_run_is_at_most_eight_tokens() -> None:
    [d] = defs('Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota ("ABC") here.')
    assert kinds(d)[0] == ("Beta Gamma Delta Epsilon Zeta Eta Theta Iota", "expansion")


def test_a_parenthetical_needs_two_capitalised_tokens() -> None:
    assert terms('the seller Acme ("Seller") agrees.') == []
    assert terms('the seller ("Seller") agrees.') == []


def test_hereinafter_needs_no_run_and_mints_the_variant_only_when_there_is_one() -> None:
    [d] = defs('the seller (hereinafter referred to as "Seller") agrees.')
    assert kinds(d) == [("Seller", "abbrev")]
    [d] = defs('Acme (hereinafter called the "Buyer") agrees.')
    assert kinds(d) == [("Acme", "variant"), ("Buyer", "abbrev")]


# -- one definition per term per block, none below three key characters ------------------------


def test_two_rules_on_one_term_in_one_block_are_one_definition() -> None:
    [d] = defs('International Business Machines ("IBM") means the company in New York.')
    assert d.rule == "copular"
    assert kinds(d) == [
        ("IBM", "canonical"),
        ("International Business Machines", "expansion"),
        ("IBM", "abbrev"),
    ]
    assert d.description == "the company in New York."


def test_one_term_in_two_blocks_is_two_definitions_and_the_sink_decides() -> None:
    found = defs('"Lender" means A Bank.', '"Lender" means B Bank.')
    assert [(d.cite, d.term) for d in found] == [("d1#0", "Lender"), ("d1#1", "Lender")]


def test_a_term_shorter_than_three_key_characters_is_not_minted() -> None:
    assert terms('"A" means a. "AB" means ab. "A B" means a b. "Tax" means tax.') == [
        "A B",
        "Tax",
    ]


def test_definitions_come_back_in_reading_order() -> None:
    assert terms('Acme Holdings ("Acme") and "Borrower" means Beta Corp.') == [
        "Acme",
        "Borrower",
    ]


# -- the per-block bound --------------------------------------------------------------------------


def test_at_most_sixteen_definitions_per_block_and_the_rest_are_disclosed() -> None:
    text = " ".join(f'"Term{n:02d}" means item {n}.' for n in range(20))
    found = find([Member(cite="d1#1", kind="paragraph", text=text)], [])
    assert [d.term for d in found.definitions] == [f"Term{n:02d}" for n in range(16)]
    [notice] = found.notices
    assert (notice.code, notice.cite) == ("OW_RESOURCE_LIMIT", "d1#1")
    assert notice.detail == {
        "limit": "DEFTERM_MAX_PER_BLOCK",
        "value": DEFTERM_MAX_PER_BLOCK,
        "found": 20,
    }


def test_the_bound_is_per_block() -> None:
    text = " ".join(f'"Term{n:02d}" means item {n}.' for n in range(16))
    found = find([Member(cite=f"d1#{i}", kind="paragraph", text=text) for i in range(2)], [])
    assert len(found.definitions) == 32
    assert found.notices == ()


@pytest.mark.parametrize(
    "text",
    [
        '"x" ' * 50_000,
        '("' * 50_000,
        "A " * 100_000 + '("IBM")',
        '"Term" ' + "a" * 200_000 + " means",
        "(hereinafter " * 20_000,
    ],
    ids=["quotes", "open-parens", "long-run", "long-gap", "hereinafters"],
)
def test_a_pathological_block_costs_linear_time(text: str) -> None:
    started = time.perf_counter()
    find([Member(cite="d1#1", kind="paragraph", text=text)], [])
    assert time.perf_counter() - started < 2.0


# -- which blocks are read ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", ["code", "formula", "toc", "toc_entry", "page_header", "page_footer"]
)
def test_a_kind_without_prose_is_not_read(kind: str) -> None:
    assert terms('"Lender" means A Bank.', kind=kind) == []


@pytest.mark.parametrize("kind", ["heading", "list_item", "footnote", "table_cell", "caption"])
def test_a_text_bearing_kind_is_read(kind: str) -> None:
    assert terms('"Lender" means A Bank.', kind=kind) == ["Lender"]


def test_a_container_without_text_is_skipped() -> None:
    assert find([Member(cite="d1#1", kind="table")], []).definitions == ()


# -- the glossary rule ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "Definitions",
        "DEFINITIONS",
        "Definition",
        "1. Definitions and Interpretation",
        "1.1 Definitions",
        "Article I Definitions",
        "Article 1 - Definitions",
        "Section 2: Glossary",
        "(a) Glossary",
        "IV. Glossary of Terms",
        "Defined Terms",
    ],
)
def test_a_glossary_heading(heading: str) -> None:
    assert is_glossary_heading(heading)


@pytest.mark.parametrize(
    "heading",
    ["Civil Definitions", "1.2 Interpretation", "Definitional issues", "Terms", "", "1."],
)
def test_not_a_glossary_heading(heading: str) -> None:
    assert not is_glossary_heading(heading)


@pytest.mark.parametrize(
    ("text", "term", "description"),
    [
        ("Affiliate: any entity.", "Affiliate", "any entity."),
        ("Business Day - a weekday.", "Business Day", "a weekday."),
        ("Business Day – a weekday.", "Business Day", "a weekday."),
        ("Escrow Agent\tthe bank.", "Escrow Agent", "the bank."),
        ("Escrow Agent means the bank.", "Escrow Agent", "means the bank."),
        ("(b) Business Day: a weekday.", "Business Day", "a weekday."),
        ("- Business Day: a weekday.", "Business Day", "a weekday."),
        ("**Business Day**: a weekday.", "Business Day", "a weekday."),
        ("Business Day:", "Business Day", None),
    ],
)
def test_a_glossary_list_item(text: str, term: str, description: str | None) -> None:
    [d] = defs(text, kind="list_item", heading="1. Definitions")
    assert (d.term, d.description, d.rule) == (term, description, "glossary")


@pytest.mark.parametrize(
    "text",
    [
        "In this agreement, words have meanings; see below: x",
        "One two three four five six seven eight nine: too long",
        "no separator at all",
        ": an empty term",
    ],
)
def test_not_a_glossary_list_item(text: str) -> None:
    assert terms(text, kind="list_item", heading="Definitions") == []


def test_a_glossary_rule_needs_a_glossary_heading_and_a_list_item() -> None:
    assert terms("Affiliate: any entity.", kind="list_item", heading="Interpretation") == []
    assert terms("Affiliate: any entity.", kind="list_item") == []
    assert terms("Affiliate: any entity.", kind="paragraph", heading="Definitions") == []


def test_only_the_nearest_heading_makes_a_glossary() -> None:
    members = [Member(cite="d1#1", kind="list_item", text="Affiliate: any entity.")]
    assert find(members, ["Definitions", "1.2 Interpretation"]).definitions == ()
    assert len(find(members, ["Part I", "Definitions"]).definitions) == 1


def cell(i: int, r: int, c: int, text: str, *, n_cols: int = 2, header_rows: int = 1) -> Member:
    return Member(
        cite=f"d1#{i}", kind="table_cell", text=text, table=Cell("d1#0", r, c, header_rows, n_cols)
    )


def test_a_two_column_table_row_under_a_glossary_heading() -> None:
    members = [
        cell(1, 0, 0, "Term"),
        cell(2, 0, 1, "Meaning"),
        cell(3, 1, 0, "Escrow Agent"),
        cell(4, 1, 1, "The bank holding funds."),
        cell(5, 2, 0, "“Lender”"),
    ]
    found = find(members, ["Glossary"]).definitions
    assert [(d.cite, d.term, d.description) for d in found] == [
        ("d1#3", "Escrow Agent", "The bank holding funds."),
        ("d1#5", "Lender", None),
    ]
    assert kinds(found[0]) == [("Escrow Agent", "canonical")]


def test_a_paragraph_in_a_glossary_cell_is_the_same_row() -> None:
    """D681. The office parse puts a cell's text in a child paragraph, and the view gives that
    paragraph its cell's position (06:1316); the rule reads the position, not the block kind."""
    members = [
        Member("d1#3", "paragraph", text="Escrow Agent", table=Cell("d1#0", 1, 0, 1, 2)),
        Member("d1#4", "paragraph", text="The bank.", table=Cell("d1#0", 1, 1, 1, 2)),
    ]
    found = find(members, ["Definitions"]).definitions
    assert [(d.cite, d.term, d.description) for d in found] == [
        ("d1#3", "Escrow Agent", "The bank.")
    ]


@pytest.mark.parametrize(
    "member",
    [
        cell(1, 1, 0, "Escrow Agent", n_cols=3),
        cell(1, 1, 0, "Escrow Agent", n_cols=0),
        cell(1, 1, 1, "Escrow Agent"),
        cell(1, 0, 0, "Escrow Agent"),
        cell(1, 1, 0, "A sentence; not a term"),
    ],
)
def test_not_a_glossary_table_row(member: Member) -> None:
    assert find([member], ["Glossary"]).definitions == ()


# -- key_form is normalize_key --------------------------------------------------------------------


@pytest.mark.parametrize(
    "s",
    ["IBM", "A B", "İstanbul", "Straße", "ﬁnance", "ᾀͅ", "  __x--y__ ", "Ångström", "中文", "ᾼ͂"],
)
def test_key_form_is_normalize_key(s: str) -> None:
    assert key_form(s) == normalize_key(s)


@given(st.text(max_size=40))
@settings(max_examples=500, deadline=None)
def test_key_form_is_normalize_key_everywhere(s: str) -> None:
    assert key_form(s) == normalize_key(s)


def test_the_alias_type_is_value_equal() -> None:
    assert Alias("IBM", "abbrev") == Alias("IBM", "abbrev")
