"""`omniweave_conform.tables` and the `table` assertion: grids and relations. D826."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from omniweave_conform.assertions import distance, evaluate_text
from omniweave_conform.tables import html_tables, markdown_tables, tables
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Assertion

MARKDOWN = """Revenue by region.

| Region | 2023 | 2024 |
|:-------|-----:|-----:|
| EMEA   | 10   | 12   |
| APAC   | 7    | 9    |

Notes follow.
"""

HTML = (
    "<table><tr><th>Member State</th><th>Rate</th></tr>"
    '<tr><td rowspan="2">Austria</td><td>20%</td></tr>'
    "<tr><td>13%</td></tr></table>"
)


def _assertion(spec: dict[str, Any], *, max_diffs: int = 0) -> Assertion:
    return Assertion(
        assertion_id="t1",
        corpus_id="golden",
        corpus_version="2026.09",
        doc="d",
        page=1,
        type="table",
        spec=spec,
        addr=None,
        evaluable_in="both",
        checked="verified",
        derived_from_sha256="sha256:" + "cd" * 32,
        max_diffs=max_diffs,
    )


def _transpose(grid: tuple[tuple[str, ...], ...]) -> str:
    """A grid's transpose as a markdown table: section 8.5's planted defect."""
    cols = list(zip(*grid, strict=True))
    lines = ["| " + " | ".join(cols[0]) + " |", "|" + "---|" * len(cols[0])]
    lines += ["| " + " | ".join(col) + " |" for col in cols[1:]]
    return "\n".join(lines)


# --- parsing ---------------------------------------------------------------------------------


def test_a_markdown_table_drops_its_separator_and_outer_pipes() -> None:
    assert markdown_tables(MARKDOWN) == (
        (("Region", "2023", "2024"), ("EMEA", "10", "12"), ("APAC", "7", "9")),
    )


def test_a_short_markdown_row_is_padded_and_an_escaped_pipe_kept() -> None:
    text = "| a | b | c |\n|---|---|---|\n| x \\| y |\n"
    assert markdown_tables(text) == ((("a", "b", "c"), ("x | y", "", "")),)


def test_pipes_without_a_separator_are_not_a_table() -> None:
    assert markdown_tables("| a | b |\n| c | d |\n") == ()


def test_an_html_span_fills_every_slot_it_covers() -> None:
    assert html_tables(HTML) == (
        (("Member State", "Rate"), ("Austria", "20%"), ("Austria", "13%")),
    )
    wide = '<table><tr><td colspan="2">Total</td></tr><tr><td>a</td><td>b</td></tr></table>'
    assert html_tables(wide) == ((("Total", "Total"), ("a", "b")),)


def test_a_bad_span_is_one_and_a_nested_table_is_its_own() -> None:
    bad = '<table><tr><td rowspan="x">a</td><td>b</td></tr></table>'
    assert html_tables(bad) == ((("a", "b"),),)
    nested = "<table><tr><td>outer<table><tr><td>inner</td></tr></table></td></tr></table>"
    assert html_tables(nested) == ((("inner",),), (("outer",),))


def test_tables_come_in_the_order_they_start() -> None:
    text = HTML + "\n\n" + MARKDOWN
    assert [grid[0][0] for grid in tables(text)] == ["Member State", "Region"]


# --- the table assertion ---------------------------------------------------------------------


def test_every_relation_of_a_markdown_cell() -> None:
    spec = {
        "cell": "12",
        "up": "2024",
        "down": "9",
        "left": "10",
        "top_heading": "2024",
        "left_heading": "EMEA",
    }
    assert evaluate_text(_assertion(spec), MARKDOWN).passed
    assert evaluate_text(_assertion({"cell": "7", "right": "9"}), MARKDOWN).passed


def test_a_spanned_cell_is_up_from_the_slot_below_it() -> None:
    spec = {"cell": "13%", "left": "Austria", "up": "20%", "top_heading": "Rate"}
    assert evaluate_text(_assertion(spec), HTML).passed


def test_a_missed_relation_is_named_with_what_was_there() -> None:
    got = evaluate_text(_assertion({"cell": "12", "left": "7"}), MARKDOWN)
    assert not got.passed
    assert "left '7' but '10'" in got.explanation


def test_an_edge_cell_has_no_neighbour_beyond_it() -> None:
    got = evaluate_text(_assertion({"cell": "Region", "up": "x"}), MARKDOWN)
    assert not got.passed
    assert "up 'x' but None" in got.explanation


def test_a_missing_cell_and_no_table_are_said() -> None:
    got = evaluate_text(_assertion({"cell": "LATAM"}), MARKDOWN)
    assert "cell 'LATAM' not found in 1 table(s)" in got.explanation
    got = evaluate_text(_assertion({"cell": "EMEA"}), "no tables here")
    assert "no table in the candidate" in got.explanation


def test_the_threshold_is_olmocr_benchs() -> None:
    """`max(0.5, 1 - max_diffs / len(cell))`: one edit on `Region` with a budget of 1, and the
    0.5 floor holding a short cell to half its length."""
    assert not evaluate_text(_assertion({"cell": "Regoin"}), MARKDOWN).passed
    assert not evaluate_text(_assertion({"cell": "Regon"}), MARKDOWN).passed
    assert evaluate_text(_assertion({"cell": "Regon"}, max_diffs=1), MARKDOWN).passed
    assert distance("10", "1") == 1
    assert evaluate_text(_assertion({"cell": "10"}, max_diffs=5), "| 1 |\n|---|\n").passed
    assert not evaluate_text(_assertion({"cell": "10"}, max_diffs=5), "| 9 |\n|---|\n").passed


def test_ignore_markdown_tables_reads_html_alone() -> None:
    text = MARKDOWN + "\n" + HTML
    spec = {"cell": "EMEA", "ignore_markdown_tables": True}
    assert not evaluate_text(_assertion(spec), text).passed
    assert evaluate_text(_assertion({"cell": "EMEA"}), text).passed


def test_an_empty_cell_is_refused() -> None:
    with pytest.raises(QualityError, match="empty `cell`"):
        evaluate_text(_assertion({"cell": ""}), MARKDOWN)


def test_the_distance_is_levenshtein() -> None:
    assert distance("kitten", "sitting") == 3
    assert distance("", "abc") == 3
    assert distance("abc", "abc") == 0


# --- section 8.5's transposed table ----------------------------------------------------------


def test_a_transposed_table_fails_every_relation_and_keeps_every_string() -> None:
    """13:1262: every `table` assertion fails while every `present` assertion still passes,
    *"because the strings are all there -- which is the point of a relational assertion"*."""
    grid = markdown_tables(MARKDOWN)[0]
    swapped = _transpose(grid)
    relations = [
        {"cell": "12", "up": "2024", "left": "10", "left_heading": "EMEA"},
        {"cell": "10", "left": "EMEA", "top_heading": "2023"},
        {"cell": "9", "up": "12", "left_heading": "APAC"},
        {"cell": "7", "right": "9", "top_heading": "2023"},
    ]
    for spec in relations:
        assert evaluate_text(_assertion(spec), MARKDOWN).passed, spec
    assert [evaluate_text(_assertion(spec), swapped).passed for spec in relations] == [False] * 4
    present = replace(_assertion({}), type="present", spec={"text": "APAC"})
    assert evaluate_text(present, swapped).passed
