"""`derive.entity.table`'s rules over Segment members. **D681**, 06 section 3.6."""

from __future__ import annotations

import pytest
from omniweave_graph.table.rules import datatype, find
from omniweave_graph.view import Cell, Member


def grid(
    rows: list[tuple[str | None, ...]], *, header_rows: int = 1, table: str = "d7#1"
) -> list[Member]:
    """One member per non-None cell, in reading order, as the view hands them."""
    width = max(len(r) for r in rows)
    return [
        Member(
            cite=f"d7#{100 + 10 * r + c}",
            kind="paragraph",
            text=text,
            table=Cell(table, r, c, header_rows, width),
        )
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
        if text is not None
    ]


def test_a_party_column_is_the_subject_and_an_org_across_the_corpus() -> None:
    [row] = find(grid([("Signed", "Party"), ("2026-06-30", "Acme Holdings Ltd.")]))
    assert (row.subject.text, row.etype, row.scope) == ("Acme Holdings Ltd.", "org", "corpus")
    assert [(f.header, f.cell.text, f.datatype) for f in row.facts] == [
        ("Signed", "2026-06-30", "xsd:date")
    ]


def test_without_a_subject_header_each_rows_first_non_empty_cell_is_the_subject() -> None:
    """06:1148 -- *"the first non-empty column as the subject"* -- per row, and a row label under
    a header the map does not know is `unknown` in this document only (ruling 4)."""
    rows = find(grid([("region", "units"), ("north", "17"), (None, "4")]))
    assert [(r.subject.text, r.etype, r.scope) for r in rows] == [
        ("north", "unknown", "document"),
        ("4", "unknown", "document"),
    ]
    assert [(f.header, f.cell.text, f.datatype) for f in rows[0].facts] == [
        ("units", "17", "xsd:decimal")
    ]
    assert rows[1].facts == (), "the subject cell is not also a fact about itself"


@pytest.mark.parametrize(
    ("header", "etype"),
    [("Party", "org"), ("Counterparty", "org"), ("Person", "person"), ("Country", "place"),
     ("Product", "product"), ("Name", "unknown"), ("Party Name", "unknown")],
)  # fmt: skip
def test_the_etype_is_read_off_the_subject_header_and_a_guess_is_unknown(
    header: str, etype: str
) -> None:
    [row] = find(grid([(header, "Notes"), ("X Corp", "fine")]))
    assert row.etype == etype


def test_a_table_without_a_header_row_is_no_relation() -> None:
    assert find(grid([("north", "17"), ("south", "4")], header_rows=0)) == ()


def test_a_cell_under_an_empty_header_asserts_nothing() -> None:
    [row] = find(grid([("Party", None, "Role"), ("Acme", "x", "Lender")]))
    assert [f.header for f in row.facts] == ["Role"]


def test_a_row_with_no_subject_is_skipped() -> None:
    assert find(grid([("Party", "Role"), (None, "Lender")])) == ()


def test_two_header_rows_join_into_one_header() -> None:
    [row] = find(grid([("Party", "Fee"), (None, "EUR"), ("Acme", "1,250")], header_rows=2))
    assert [(f.header, f.datatype) for f in row.facts] == [("Fee EUR", "money:EUR")]


def test_a_cell_of_two_paragraphs_is_one_text_grounded_at_the_first() -> None:
    cell = Cell("d7#1", 1, 1, 1, 2)
    members = [
        *grid([("Party", "Notes")]),
        Member("d7#110", "paragraph", text="Acme", table=Cell("d7#1", 1, 0, 1, 2)),
        Member("d7#111", "paragraph", text="  first line ", table=cell),
        Member("d7#112", "paragraph", text="second", table=cell),
    ]
    [row] = find(members)
    [fact] = row.facts
    assert (fact.cell.cite, fact.cell.text, fact.cell.span) == (
        "d7#111",
        "first line second",
        (2, 12),
    )


def test_two_tables_in_one_segment_are_read_apart() -> None:
    first = grid([("Party", "Role"), ("Acme", "Lender")], table="d7#1")
    second = grid([("Product", "Price"), ("Widget", "12")], table="d7#2")
    rows = find([*first, *second])
    assert [(r.table_cite, r.subject.text, r.etype) for r in rows] == [
        ("d7#1", "Acme", "org"),
        ("d7#2", "Widget", "product"),
    ]
    assert rows[1].facts[0].datatype == "xsd:decimal"


@pytest.mark.parametrize(
    ("cell", "header", "expected"),
    [
        ("2026-06-30", "Date", "xsd:date"),
        ("2026-02-30", "Date", "string"),
        ("30 June 2026", "Signed", "xsd:date"),
        ("June 30, 2026", "Signed", "xsd:date"),
        ("06/30/2026", "Signed", "string"),
        ("1,250,000 (as restated)", "Amount (USD)", "money:USD"),
        ("EUR 12", "Fee", "money:EUR"),
        ("£ 400", "Fee", "money:GBP"),
        ("$400", "Fee", "string"),
        ("12.5", "Rate", "xsd:decimal"),
        ("1,250", "Total", "xsd:decimal"),
        ("12.5", "Notes", "string"),
        ("USD", "Currency", "string"),
        ("steady", "Note", "string"),
    ],
)
def test_the_datatype_is_closed_and_a_guess_is_string(
    cell: str, header: str, expected: str
) -> None:
    """Ruling 6. `$` names no one currency, and a currency code with no digit is not an amount."""
    assert datatype(cell, header) == expected
