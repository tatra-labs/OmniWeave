"""`TableEntities` on the wire: Segment views in, `owgraph-items/1` out. **D681.**"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_graph.table.driver import (
    DRIVER_ID,
    EMPTY_REASON,
    LANES,
    NO_FACT_REASON,
    TableEntities,
)
from omniweave_ports import ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef


def view(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


def seg(name: str = "seg:9f2c1d4a77b03e51") -> dict[str, Any]:
    return {"t": "segment", "seg": name, "heading_path": ["Schedule 1"]}


def cell(cite: str, text: str, r: int, c: int, table: str = "d7#1") -> dict[str, Any]:
    return {
        "t": "block",
        "cite": cite,
        "kind": "paragraph",
        "text": text,
        "table": {"table_cite": table, "r": r, "c": c, "header_rows": 1, "n_cols": 2},
    }


def run(tmp_path: Path, *views: bytes) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"doc:{i}", part="", content_sha256=blobs.add(v), byte_len=len(v))
        for i, v in enumerate(views)
    )
    io = make_io(blobs, tmp_path / "tmp")
    result = TableEntities().derive(
        DeriveScope(lane="entity", units=units, allowed_cites=frozenset()), io
    )
    assert result.outcome == "ok"
    [ref] = result.produced
    assert ref.kind == "graph_items"
    assert TableEntities().is_valid_nonempty(ref)
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_needs_nothing_and_the_port_is_derive() -> None:
    assert TableEntities.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert TableEntities.PORT == "derive/1"
    assert DRIVER_ID == "derive.entity.table"
    assert LANES == ("entity", "claim")


def test_config_takes_nothing() -> None:
    with pytest.raises(ValueError, match="takes no rows"):
        TableEntities(rows=3)


def test_a_row_is_an_entity_its_alias_its_mention_and_its_claims_then_cover(
    tmp_path: Path,
) -> None:
    frames = run(
        tmp_path,
        view(
            seg(),
            cell("d7#2", "Party", 0, 0),
            cell("d7#3", "Signed", 0, 1),
            cell("d7#4", "Acme Holdings Ltd.", 1, 0),
            cell("d7#5", "2026-06-30", 1, 1),
        ),
    )
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {
            "t": "entity",
            "tmp": "e1",
            "key": "Acme Holdings Ltd.",
            "etype": "org",
            "title": "Acme Holdings Ltd.",
            "scope": "corpus",
            "trust": "extracted",
        },
        {
            "t": "alias",
            "entity": "e1",
            "surface": "Acme Holdings Ltd.",
            "alias_kind": "canonical",
            "trust": "extracted",
        },
        {
            "t": "mention",
            "entity": "e1",
            "cite": "d7#4",
            "span": [0, 18],
            "surface": "Acme Holdings Ltd.",
            "trust": "extracted",
        },
        {
            "t": "claim",
            "subject": "e1",
            "object_literal": "2026-06-30",
            "object_datatype": "xsd:date",
            "claim_type": "attribute",
            "predicate": "Signed",
            "description": "Signed of Acme Holdings Ltd.: 2026-06-30",
            "status": "asserted",
            "observed": {"cite": "d7#5", "span": [0, 10]},
            "trust": "extracted",
        },
        {"t": "cover", "lane": "entity", "cites": ["d7#4"]},
        {"t": "cover", "lane": "claim", "cites": ["d7#5"]},
    ]


def test_a_subject_on_two_rows_keeps_one_token_within_a_segment(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        view(
            seg(),
            cell("d7#2", "Party", 0, 0),
            cell("d7#3", "Role", 0, 1),
            cell("d7#4", "Acme", 1, 0),
            cell("d7#5", "Lender", 1, 1),
            cell("d7#6", "ACME", 2, 0),
            cell("d7#7", "Agent", 2, 1),
        ),
    )
    assert [f["tmp"] for f in frames if f["t"] == "entity"] == ["e1"]
    assert [f["entity"] for f in frames if f["t"] == "mention"] == ["e1", "e1"]
    assert [f["subject"] for f in frames if f["t"] == "claim"] == ["e1", "e1"]


def test_a_token_is_never_reused_across_segments(tmp_path: Path) -> None:
    """`drive_items` opens a sink per Segment, so a token from Segment one is unbound in Segment
    two: the same party there mints its own, numbered on from the last."""
    rows = (
        cell("d7#2", "Party", 0, 0),
        cell("d7#3", "Role", 0, 1),
        cell("d7#4", "Acme", 1, 0),
        cell("d7#5", "Lender", 1, 1),
    )
    frames = run(tmp_path, view(seg("seg:a"), *rows), view(seg("seg:b"), *rows))
    assert [f["tmp"] for f in frames if f["t"] == "entity"] == ["e1", "e2"]
    assert [f["subject"] for f in frames if f["t"] == "claim"] == ["e1", "e2"]


def test_no_table_is_two_cover_empty_and_a_subject_without_facts_is_one(tmp_path: Path) -> None:
    prose = {"t": "block", "cite": "d7#9", "kind": "paragraph", "text": "No table here."}
    bare = (cell("d7#2", "Party", 0, 0), cell("d7#4", "Acme", 1, 0))
    frames = run(tmp_path, view(seg("seg:a"), prose), view(seg("seg:b"), *bare))
    empties = [(f["lane"], f["reason"]) for f in frames if f["t"] == "cover_empty"]
    assert empties == [
        ("entity", EMPTY_REASON),
        ("claim", EMPTY_REASON),
        ("claim", NO_FACT_REASON),
    ]
