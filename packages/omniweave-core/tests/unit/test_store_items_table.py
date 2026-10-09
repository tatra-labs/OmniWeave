"""A table in the office parse's own shape, through the view and through `derive.entity.table`.

**D681.** The office parse writes a cell as a container block with no text and its text as child
paragraphs. 06:1316 prints the view's answer -- a `paragraph` frame carrying its cell's `table` --
and before D681 the view joined `cell` on the member alone, so no member of a parsed table had a
position and every rule reading one never fired. These tests use that shape, not a `table_cell`
holding its own text, which is the shape `test_store_items.py`'s glossary fixture uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.model.enums import Method, Trust
from omniweave_core.store import sqlite as ow
from omniweave_core.store.graph import PassIdentity
from omniweave_core.store.items import decode_items, drive_items
from omniweave_graph.table.driver import TableEntities
from test_store_items import _answer, _Spend, block, rows, store, views

TABLE = "derive.entity.table"


def office_table() -> list[dict[str, Any]]:
    """A heading, then a two-row table: each cell an empty container holding a paragraph, and one
    cell holding a list whose item is two levels below the cell."""
    frames: list[dict[str, Any]] = [
        {"t": "doc", "format": "docx", "media_type": "application/x-test", "page_count": 1},
        {"t": "page", "page": 0, "page_kind": "stream", "method": "native_xml"},
        block("h0", "Signatories", "heading", payload={"level": 1}),
        block("t", None, "table", payload={"header_rows": 1}),
    ]
    grid = [
        ("Party", "Signed", "Fee (EUR)"),
        ("Acme Holdings Ltd.", "2026-06-30", "1,250"),
        ("Beta Bank plc", "30 June 2026", None),
    ]
    for r, row in enumerate(grid):
        for c, text in enumerate(row):
            frames.append(block(f"c{r}{c}", None, "table_cell", parent="t", cell={"r": r, "c": c}))
            if text is not None:
                frames.append(block(f"q{r}{c}", text, "paragraph", parent=f"c{r}{c}"))
    frames += [
        block("l", None, "list", parent="c22"),
        block("li", "waived", "list_item", parent="l"),
        {"t": "end", "status": "ok", "page_stats": {"0": {"blocks": 20}}},
    ]
    return frames


@pytest.fixture
def table(tmp_path: Path) -> tuple[Path, int]:
    path, producer = store(tmp_path, office_table())
    connection = ow.connect(path)
    try:
        connection.execute(
            "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, "
            "granularity, card_sha256, schema_version) VALUES(?, 'derive/1', 'free', 0, 20, "
            "'[\"entity\",\"claim\"]', 'document', 'sha', 1)",
            (TABLE,),
        )
        connection.commit()
    finally:
        connection.close()
    return path, producer


def _members(path: Path) -> dict[str, dict[str, Any]]:
    return {
        frame["text"]: frame
        for v in views(path)
        for frame in map(json.loads, v.body.splitlines())
        if frame.get("t") == "block" and "text" in frame
    }


def test_a_paragraph_in_a_cell_carries_its_cells_position(table: Any) -> None:
    path, _ = table
    members = _members(path)
    assert members["Party"]["kind"] == "paragraph"
    assert members["Party"]["table"] == {
        "table_cite": members["Party"]["table"]["table_cite"],
        "r": 0,
        "c": 0,
        "header_rows": 1,
        "n_cols": 3,
    }
    assert (members["2026-06-30"]["table"]["r"], members["2026-06-30"]["table"]["c"]) == (1, 1)


def test_a_list_item_two_levels_inside_a_cell_carries_that_cells_position(table: Any) -> None:
    path, _ = table
    item = _members(path)["waived"]
    assert item["kind"] == "list_item"
    assert (item["table"]["r"], item["table"]["c"]) == (2, 2)


def test_a_block_outside_any_table_carries_no_position(table: Any) -> None:
    path, _ = table
    assert "table" not in _members(path)["Signatories"]


def _derive(path: Path, producer: int, tmp: Path) -> None:
    vs = views(path)
    units = decode_items(_answer(TableEntities(), [v.body for v in vs], tmp), vs)
    identity = PassIdentity(
        pass_id=TABLE,
        producer_id=producer,
        method=Method.NATIVE_XML,
        origin_operator="derive.entity",
        origin_driver=TABLE,
        driver_schema_v=1,
        cost_class="free",
    )
    connection = ow.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for unit in units:
            drive_items(connection, unit, identity, _Spend())
        connection.execute("COMMIT")
    finally:
        connection.close()


def test_the_table_pass_through_the_host_writes_entities_claims_and_mentions(
    table: Any, tmp_path: Path
) -> None:
    """06 section 3.6 end to end: a `Party` column is the subject and names an `org` across the
    corpus; each other cell is an `attribute` claim at its own cite, its predicate the header
    normalised by the sink, its datatype inferred; nothing is quarantined."""
    path, producer = table
    _derive(path, producer, tmp_path)
    assert rows(path, "SELECT scope, etype, key, trust FROM entity ORDER BY key") == [
        (0, "org", "acme_holdings_ltd", int(Trust.EXTRACTED)),
        (0, "org", "beta_bank_plc", int(Trust.EXTRACTED)),
    ]
    claims = rows(
        path,
        "SELECT s.key, c.predicate, c.object_literal, c.object_datatype, b.text FROM claim c "
        "JOIN entity s ON s.entity_id = c.subject_entity "
        "JOIN block b ON b.block_id = c.observed_block ORDER BY 1, 2",
    )
    assert claims == [
        ("acme_holdings_ltd", "fee_eur", "1,250", "money:EUR", "1,250"),
        ("acme_holdings_ltd", "signed", "2026-06-30", "xsd:date", "2026-06-30"),
        ("beta_bank_plc", "fee_eur", "waived", "string", "waived"),
        ("beta_bank_plc", "signed", "30 June 2026", "xsd:date", "30 June 2026"),
    ]
    mentions = rows(
        path,
        "SELECT e.key, b.text, m.ts_a, m.ts_b FROM mention m JOIN entity e USING(entity_id) "
        "JOIN block b ON b.block_id = m.block_id ORDER BY 1",
    )
    assert mentions == [
        ("acme_holdings_ltd", "Acme Holdings Ltd.", 0, 18),
        ("beta_bank_plc", "Beta Bank plc", 0, 13),
    ]
    assert rows(path, "SELECT count(*) FROM quarantine") == [(0,)]
    aliases = rows(path, "SELECT alias_kind, count(*) FROM entity_alias GROUP BY 1")
    assert aliases == [("canonical", 2)]


def test_an_office_table_is_cut_as_a_table_segment(table: Any) -> None:
    """D682. The segmenter's view places a cell's paragraphs in their cell as the derive view does,
    so the spine packs the table by rows into a `table` atom rather than reading it as prose."""
    path, _ = table
    segments = rows(
        path,
        "SELECT s.atom, group_concat(b.text, '|') FROM segment s "
        "JOIN segment_block sb ON sb.segment_id = s.segment_id "
        "JOIN block b ON b.block_id = sb.block_id WHERE s.state = 0 "
        "GROUP BY s.segment_id ORDER BY s.ord",
    )
    assert segments == [
        (None, "Signatories"),
        (
            "table",
            "Party|Signed|Fee (EUR)|Acme Holdings Ltd.|2026-06-30|1,250|Beta Bank plc|"
            "30 June 2026|waived",
        ),
    ]


def nested_table() -> list[dict[str, Any]]:
    """An outer table whose first cell holds a whole two-by-two table: the climb stops at the INNER
    cell. Every grid is complete -- a sparse one fails the parse's own checks and the generation is
    never promoted, which is what D681's first try at this fixture ran into."""
    frames: list[dict[str, Any]] = [
        {"t": "doc", "format": "docx", "media_type": "application/x-test", "page_count": 1},
        {"t": "page", "page": 0, "page_kind": "stream", "method": "native_xml"},
        block("h0", "Nested", "heading", payload={"level": 1}),
        block("T", None, "table", payload={"header_rows": 0}),
        block("o00", None, "table_cell", parent="T", cell={"r": 0, "c": 0}),
        block("t", None, "table", parent="o00", payload={"header_rows": 1}),
    ]
    for r in range(2):
        for c in range(2):
            frames.append(block(f"i{r}{c}", None, "table_cell", parent="t", cell={"r": r, "c": c}))
            frames.append(block(f"p{r}{c}", f"inner {r}{c}", "paragraph", parent=f"i{r}{c}"))
    frames += [
        block("o01", None, "table_cell", parent="T", cell={"r": 0, "c": 1}),
        block("outer", "outer text", "paragraph", parent="o01"),
        {"t": "end", "status": "ok", "page_stats": {"0": {"blocks": 15}}},
    ]
    return frames


def test_a_nested_table_is_placed_in_its_inner_cells_and_cut_on_its_own(tmp_path: Path) -> None:
    """The derive view places each inner paragraph in its inner cell, once; the inner table is its
    own `table` Segment; and the outer table's cell met after it is prose (spine reading 7)."""
    path, _ = store(tmp_path, nested_table())
    placed = {
        text: (frame["table"]["r"], frame["table"]["c"], frame["table"]["header_rows"])
        for text, frame in _members(path).items()
        if "table" in frame
    }
    assert placed == {
        "inner 00": (0, 0, 1),
        "inner 01": (0, 1, 1),
        "inner 10": (1, 0, 1),
        "inner 11": (1, 1, 1),
        "outer text": (0, 1, 0),
    }
    frames = [f for v in views(path) for f in map(json.loads, v.body.splitlines())]
    assert sum(1 for f in frames if f.get("text") == "inner 00") == 1
    segments = rows(
        path,
        "SELECT s.atom, group_concat(b.text, '|') FROM segment s "
        "JOIN segment_block sb ON sb.segment_id = s.segment_id "
        "JOIN block b ON b.block_id = sb.block_id WHERE s.state = 0 "
        "GROUP BY s.segment_id ORDER BY s.ord",
    )
    assert segments == [
        (None, "Nested"),
        ("table", "inner 00|inner 01|inner 10|inner 11"),
        (None, "outer text"),
    ]
