"""`SpineSegmenter` on the wire: `owgraph-segment/1`'s document form in, `owgraph-items/1` out.

The algorithm's rules are `test_segment_spine.py`'s; this is the decoding, the encoding and the
refusals a host will meet. D662.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_graph.segment.driver import DRIVER_ID, SpineSegmenter, read_view
from omniweave_ports import ArtifactRef, DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef


def view(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


DOC = {
    "t": "doc",
    "doc": "d7",
    "sections": {"/0001": "Part II"},
    "defaults": {"layer": "body", "page": 3, "sec": "/0001"},
}


def run(
    tmp_path: Path, *views: bytes, cancel_after: int = 0, **config: Any
) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"view:{i}", part="", content_sha256=blobs.add(v), byte_len=len(v))
        for i, v in enumerate(views)
    )
    io = make_io(blobs, tmp_path / "tmp", cancel_after_progress=cancel_after)
    scope = DeriveScope(lane="segment", units=units, allowed_cites=frozenset())
    result = SpineSegmenter(**config).derive(scope, io)
    assert result.outcome == "ok"
    [ref] = result.produced
    assert ref.kind == "graph_items"
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    assert SpineSegmenter().is_valid_nonempty(ref)
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_needs_nothing() -> None:
    assert SpineSegmenter.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert SpineSegmenter.PORT == "derive/1"


def test_a_view_becomes_its_doc_frame_then_segments_then_diags(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        view(
            DOC,
            {"t": "block", "cite": "d7#1", "kind": "heading", "text": "Part II"},
            {"t": "block", "cite": "d7#2", "kind": "paragraph", "text": "a" * 40},
            {"t": "block", "cite": "d7#3", "kind": "paragraph", "page": 4, "text": "b" * 9000},
        ),
    )
    assert frames[0] == {"t": "doc", "doc": "d7"}
    assert frames[1] == {
        "t": "segment",
        "layer": "body",
        "atom": None,
        "heading_path": ["Part II"],
        "blocks": ["d7#1", "d7#2"],
        "n_tokens": 12,
        "tokenizer": "ow.bytes4/1",
        "synopsis_of": None,
    }
    assert frames[2]["blocks"] == ["d7#3"]
    assert frames[3]["t"] == "diag"
    assert frames[3]["code"] == "OW_RESOURCE_LIMIT"
    assert frames[3]["component"] == DRIVER_ID
    assert (frames[3]["cite"], frames[3]["page"]) == ("d7#3", 4)
    assert frames[3]["detail"] == {"limit": "MAX_SEGMENT_TOKENS", "n_tokens": 2250}


def test_defaults_fill_what_a_block_frame_leaves_out() -> None:
    doc, sections, blocks = read_view(
        view(
            DOC,
            {"t": "block", "cite": "d7#1", "kind": "paragraph", "text": "x"},
            {
                "t": "block",
                "cite": "d7#2",
                "kind": "page_header",
                "layer": "furniture",
                "sec": "/",
                "page": 9,
                "text": "y",
            },
        )
    )
    assert doc == "d7"
    assert sections == {"/0001": "Part II"}
    assert [(b.layer, b.page, b.sec) for b in blocks] == [
        ("body", 3, "/0001"),
        ("furniture", 9, "/"),
    ]


def test_table_geometry_is_read_off_the_grid_and_table_keys() -> None:
    _, _, blocks = read_view(
        view(
            DOC,
            {
                "t": "block",
                "cite": "d7#9",
                "kind": "table",
                "grid": {"n_rows": 2, "n_cols": 1, "header_rows": 1},
            },
            {
                "t": "block",
                "cite": "d7#10",
                "kind": "table_cell",
                "text": "h",
                "table": {"table_cite": "d7#9", "r": 0, "c": 0},
            },
        )
    )
    assert blocks[0].grid is not None
    assert (blocks[0].grid.n_rows, blocks[0].grid.header_rows) == (2, 1)
    assert (blocks[1].table, blocks[1].r, blocks[1].c) == ("d7#9", 0, 0)


def test_two_units_are_two_doc_frames_each_followed_by_its_own_segments(tmp_path: Path) -> None:
    one = view(
        {"t": "doc", "doc": "d1"}, {"t": "block", "cite": "d1#1", "kind": "paragraph", "text": "a"}
    )
    two = view(
        {"t": "doc", "doc": "d2"}, {"t": "block", "cite": "d2#1", "kind": "paragraph", "text": "b"}
    )
    frames = run(tmp_path, one, two)
    assert [(f["t"], f.get("doc") or f["blocks"]) for f in frames] == [
        ("doc", "d1"),
        ("segment", ["d1#1"]),
        ("doc", "d2"),
        ("segment", ["d2#1"]),
    ]


def test_the_output_is_byte_identical_across_runs(tmp_path: Path) -> None:
    body = view(
        DOC,
        *(
            {"t": "block", "cite": f"d7#{i}", "kind": "paragraph", "text": "w" * (i * 37 % 900)}
            for i in range(300)
        ),
    )
    assert run(tmp_path / "a", body) == run(tmp_path / "b", body)


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        (b"", "does not open with a doc frame"),
        (b"not json\n", "line 1 is not JSON"),
        (view({"t": "block", "cite": "x", "kind": "paragraph"}), "does not open with a doc frame"),
        (view(DOC, {"t": "segment"}), "'segment' frame where a block frame belongs"),
        (view(DOC, {"t": "block", "kind": "paragraph"}), "missing or mistypes"),
        (
            view(DOC, {"t": "block", "cite": "x", "kind": "paragraph", "page": "1"}),
            "page is not a int",
        ),
        (
            view(DOC, {"t": "block", "cite": "x", "kind": "paragraph", "text": 5}),
            "text is not a string",
        ),
        (view({"t": "doc", "doc": "d", "sections": {"/0001": 1}}), "sections must map"),
        (view(DOC, [1, 2]), "line 2 is not a frame"),  # type: ignore[arg-type]
    ],
)
def test_a_malformed_view_is_corrupt_input(raw: bytes, says: str) -> None:
    with pytest.raises(DriverError) as caught:
        read_view(raw)
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
    assert says in caught.value.message


def test_a_view_with_no_text_is_an_empty_result_never_an_empty_ok(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as caught:
        run(tmp_path, view(DOC, {"t": "block", "cite": "d7#1", "kind": "picture"}))
    assert caught.value.cls is FailureClass.EMPTY_RESULT
    assert not SpineSegmenter().is_valid_nonempty(
        ArtifactRef(kind="graph_items", byte_len=23, inline=b'{"t":"doc","doc":"d7"}\n')
    )


def test_cancellation_is_checked_before_each_unit(tmp_path: Path) -> None:
    one = view(
        {"t": "doc", "doc": "d1"}, {"t": "block", "cite": "d1#1", "kind": "paragraph", "text": "a"}
    )
    with pytest.raises(DriverError) as caught:
        run(tmp_path, one, one, cancel_after=1)
    assert caught.value.cls is FailureClass.TIMEOUT


def test_config_takes_the_six_params_and_nothing_else(tmp_path: Path) -> None:
    body = view(
        DOC,
        *(
            {"t": "block", "cite": f"d7#{i}", "kind": "paragraph", "text": "a" * 400}
            for i in range(4)
        ),
    )
    frames = run(tmp_path, body, target_tokens=200)
    assert [f["blocks"] for f in frames if f["t"] == "segment"] == [
        ["d7#0", "d7#1"],
        ["d7#2", "d7#3"],
    ]
    with pytest.raises(ValueError, match="takes no colour"):
        SpineSegmenter(colour="red")
    with pytest.raises(ValueError, match="above its ceiling"):
        SpineSegmenter(max_tokens=4096)
