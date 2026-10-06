"""`DefinedTerms` on the wire: `owgraph-segment/1`'s Segment form in, `owgraph-items/1` out.

The rules are `test_defterm_rules.py`'s; this is the Segment-form decoding every free Pass shares,
the item frames D666 rules, and the refusals a host will meet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.model.enums import MAX_TRUST_BY_METHOD, Method, Trust
from omniweave_graph.defterm.driver import DRIVER_ID, EMPTY_REASON, LANES, DefinedTerms
from omniweave_graph.view import Cell, Member, read_segment_view
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef


def view(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


def seg(name: str = "seg:9f2c1d4a77b03e51", **extra: Any) -> dict[str, Any]:
    return {"t": "segment", "seg": name, "heading_path": ["Part II"], **extra}


def block(cite: str, text: str | None, kind: str = "paragraph", **extra: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {"t": "block", "cite": cite, "kind": kind, **extra}
    if text is not None:
        frame["text"] = text
    return frame


def run(tmp_path: Path, *views: bytes, cancel_after: int = 0) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"seg:{i}", part="", content_sha256=blobs.add(v), byte_len=len(v))
        for i, v in enumerate(views)
    )
    io = make_io(blobs, tmp_path / "tmp", cancel_after_progress=cancel_after)
    scope = DeriveScope(lane="anchor", units=units, allowed_cites=frozenset())
    result = DefinedTerms().derive(scope, io)
    assert result.outcome == "ok"
    [ref] = result.produced
    assert ref.kind == "graph_items"
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    assert DefinedTerms().is_valid_nonempty(ref)
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_needs_nothing_and_the_port_is_derive() -> None:
    assert DefinedTerms.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert DefinedTerms.PORT == "derive/1"
    assert DRIVER_ID == "derive.anchor.defterm"


def test_config_takes_nothing() -> None:
    with pytest.raises(ValueError, match="takes no max_per_block"):
        DefinedTerms(max_per_block=3)


def test_a_definition_is_an_entity_its_aliases_and_its_anchor_then_cover(tmp_path: Path) -> None:
    text = 'International Business Machines Corporation ("IBM") is a party.'
    frames = run(tmp_path, view(seg(), block("d7#4", text)))
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {
            "t": "entity",
            "tmp": "e1",
            "key": "IBM",
            "etype": "defined_term",
            "title": "IBM",
            "scope": "document",
            "trust": "extracted",
        },
        {
            "t": "alias",
            "entity": "e1",
            "surface": "International Business Machines Corporation",
            "alias_kind": "expansion",
            "trust": "extracted",
        },
        {
            "t": "alias",
            "entity": "e1",
            "surface": "IBM",
            "alias_kind": "abbrev",
            "trust": "extracted",
        },
        {
            "t": "anchor",
            "name": "IBM",
            "akind": "defined_term",
            "cite": "d7#4",
            "span": [46, 49],
            "scope": "document",
            "surface": "IBM",
        },
        {"t": "cover", "lane": "anchor", "cites": ["d7#4"]},
        {"t": "cover", "lane": "entity", "cites": ["d7#4"]},
    ]
    assert text[46:49] == "IBM"


def test_a_definition_with_context_carries_it_as_the_description(tmp_path: Path) -> None:
    frames = run(tmp_path, view(seg(), block("d7#4", '"Lender" means Beta Bank.')))
    assert frames[1]["description"] == "Beta Bank."


def test_the_claimed_trust_is_within_the_heuristic_ceiling() -> None:
    assert MAX_TRUST_BY_METHOD[Method.HEURISTIC] >= Trust.EXTRACTED


def test_a_segment_with_no_definition_is_two_cover_empty_frames_and_ok(tmp_path: Path) -> None:
    frames = run(tmp_path, view(seg(), block("d7#1", "Nothing is defined here.")))
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        *({"t": "cover_empty", "lane": lane, "reason": EMPTY_REASON} for lane in LANES),
    ]
    assert LANES == ("anchor", "entity")


def test_cover_names_each_block_once_in_reading_order(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        view(
            seg(),
            block("d7#1", '"Lender" means A. "Borrower" means B.'),
            block("d7#2", "No definition."),
            block("d7#3", '"Agent" means C.'),
        ),
    )
    covers = [f for f in frames if f["t"] == "cover"]
    assert [c["cites"] for c in covers] == [["d7#1", "d7#3"], ["d7#1", "d7#3"]]


def test_tmp_tokens_run_across_units_and_each_unit_opens_with_its_seg(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        view(seg("seg:aaaaaaaaaaaaaaaa"), block("d7#1", '"Lender" means A.')),
        view(seg("seg:bbbbbbbbbbbbbbbb"), block("d8#1", '"Agent" means B. "Escrow" means C.')),
    )
    assert [f["seg"] for f in frames if f["t"] == "seg"] == [
        "seg:aaaaaaaaaaaaaaaa",
        "seg:bbbbbbbbbbbbbbbb",
    ]
    assert [f["tmp"] for f in frames if f["t"] == "entity"] == ["e1", "e2", "e3"]
    second = frames.index({"t": "seg", "seg": "seg:bbbbbbbbbbbbbbbb"})
    assert all(f.get("cite", "d8").startswith("d8") for f in frames[second:])


def test_a_refused_overflow_is_a_diag_frame_after_the_cover(tmp_path: Path) -> None:
    text = " ".join(f'"Term{n:02d}" means item {n}.' for n in range(17))
    frames = run(tmp_path, view(seg(), block("d7#1", text)))
    assert [f["t"] for f in frames[-3:]] == ["cover", "cover", "diag"]
    diag = frames[-1]
    assert diag["code"] == "OW_RESOURCE_LIMIT"
    assert diag["component"] == DRIVER_ID
    assert diag["cite"] == "d7#1"
    assert diag["detail"] == {"limit": "DEFTERM_MAX_PER_BLOCK", "value": 16, "found": 17}
    assert diag["fatal"] is False


def test_the_glossary_rule_reads_the_heading_path_off_the_segment_frame(tmp_path: Path) -> None:
    item = block("d7#2", "Affiliate: any entity.", kind="list_item")
    assert [f for f in run(tmp_path, view(seg(), item)) if f["t"] == "anchor"] == []
    frames = run(tmp_path, view(seg(heading_path=["Part I", "1. Definitions"]), item))
    assert [f["name"] for f in frames if f["t"] == "anchor"] == ["Affiliate"]


def test_the_output_is_byte_identical_across_runs(tmp_path: Path) -> None:
    v = view(seg(), block("d7#1", 'Acme Holdings Ltd. (hereinafter, the "Company") agrees.'))
    assert run(tmp_path / "a", v) == run(tmp_path / "b", v)


def test_non_ascii_text_is_written_as_utf8_not_escaped(tmp_path: Path) -> None:
    frames = run(tmp_path, view(seg(), block("d7#1", "“Société” means X.")))
    assert frames[1]["key"] == "Société"


def test_cancellation_is_checked_before_each_unit(tmp_path: Path) -> None:
    one = view(seg(), block("d7#1", '"Lender" means A.'))
    with pytest.raises(DriverError) as caught:
        run(tmp_path, one, one, cancel_after=1)
    assert caught.value.cls is FailureClass.TIMEOUT


# -- the Segment form, decoded --------------------------------------------------------------------


def test_defaults_fill_what_a_block_frame_leaves_out() -> None:
    v = read_segment_view(
        view(
            seg(defaults={"layer": "note", "covered": True, "trust": 2}, doc={"format": "pdf"}),
            block("d7#1", "a", page=3, marks=[[0, 1, "bold", None]]),
            block("d7#2", "b", layer="body", covered=False),
            block("d7#3", None, kind="table"),
        )
    )
    assert v.seg == "seg:9f2c1d4a77b03e51"
    assert v.heading_path == ("Part II",)
    assert v.members == (
        Member(cite="d7#1", kind="paragraph", text="a", layer="note", covered=True),
        Member(cite="d7#2", kind="paragraph", text="b", layer="body", covered=False),
        Member(cite="d7#3", kind="table", text=None, layer="note", covered=True),
    )


def test_a_cell_frame_carries_its_table_position() -> None:
    table = {"table_cite": "d7#9", "r": 2, "c": 1, "header_rows": 1, "n_cols": 2, "row_span": 1}
    [m] = read_segment_view(
        view(seg(), block("d7#10", "x", kind="table_cell", table=table))
    ).members
    assert m.table == Cell(table_cite="d7#9", r=2, c=1, header_rows=1, n_cols=2)
    [m] = read_segment_view(
        view(
            seg(),
            block("d7#10", "x", kind="table_cell", table={"table_cite": "d7#9", "r": 0, "c": 0}),
        )
    ).members
    assert m.table == Cell(table_cite="d7#9", r=0, c=0, header_rows=0, n_cols=0)


def test_a_segment_with_no_blocks_decodes_to_no_members() -> None:
    assert read_segment_view(view(seg())).members == ()


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        (b"", "does not open with a segment frame"),
        (view({"t": "doc", "doc": "d7"}), "does not open with a segment frame"),
        (view({"t": "segment"}), "does not open with a segment frame"),
        (view(seg(heading_path="Part II")), "heading_path must be a list"),
        (view(seg(defaults=[1])), "defaults must be an object"),
        (b'{"t":"segment","seg":"s"}\nnot json\n', "line 2 is not JSON"),
        (b'{"t":"segment","seg":"s"}\n[1]\n', "line 2 is not a frame"),
        (view(seg(), {"t": "anchor"}), "'anchor' frame where a block frame belongs"),
        (view(seg(), {"t": "block", "kind": "paragraph"}), "cite, kind and layer must be strings"),
        (view(seg(), block("d7#1", None, layer=3)), "cite, kind and layer must be strings"),
        (view(seg(), {"t": "block", "cite": "d7#1", "kind": "x", "text": 7}), "not a string"),
        (view(seg(), block("d7#1", "x", covered="yes")), "covered is not a boolean"),
        (view(seg(), block("d7#1", "x", table=[1])), "table is not an object"),
        (view(seg(), block("d7#1", "x", table={"r": 0, "c": 0})), "table is missing"),
        (
            view(seg(), block("d7#1", "x", table={"table_cite": "t", "r": -1, "c": 0})),
            "table mistypes a field",
        ),
        (
            view(seg(), block("d7#1", "x", table={"table_cite": "t", "r": True, "c": 0})),
            "table mistypes a field",
        ),
    ],
)
def test_a_malformed_view_is_corrupt_input(raw: bytes, says: str) -> None:
    with pytest.raises(DriverError) as caught:
        read_segment_view(raw)
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
    assert says in str(caught.value)


def test_a_document_form_view_is_refused_by_the_driver(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as caught:
        run(tmp_path, view({"t": "doc", "doc": "d7"}, block("d7#1", '"Lender" means A.')))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
