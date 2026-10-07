"""`DeclaredAnchors` on the wire, and the `marks` and `label` the Segment view now carries. D670."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_graph.native.driver import DRIVER_ID, EMPTY_REASON, LANE, DeclaredAnchors
from omniweave_graph.view import Mark, read_segment_view
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef


def view(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


SEG = {"t": "segment", "seg": "seg:9f2c1d4a77b03e51", "heading_path": []}


def block(cite: str, text: str, kind: str = "heading", **extra: Any) -> dict[str, Any]:
    return {"t": "block", "cite": cite, "kind": kind, "text": text, **extra}


def run(tmp_path: Path, *views: bytes) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"doc:{i}", part="", content_sha256=blobs.add(v), byte_len=len(v))
        for i, v in enumerate(views)
    )
    result = DeclaredAnchors().derive(
        DeriveScope(lane=LANE, units=units, allowed_cites=frozenset()),
        make_io(blobs, tmp_path / "tmp"),
    )
    [ref] = result.produced
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    assert DeclaredAnchors().is_valid_nonempty(ref)
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_needs_nothing_and_config_takes_nothing() -> None:
    assert DeclaredAnchors.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert (DeclaredAnchors.PORT, DRIVER_ID) == ("derive/1", "derive.anchor.native")
    with pytest.raises(ValueError, match="takes no x"):
        DeclaredAnchors(x=1)


def test_a_declared_anchor_is_an_anchor_frame_then_cover(tmp_path: Path) -> None:
    frames = run(tmp_path, view(SEG, block("d7#40", "4.2 Indemnity")))
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {
            "t": "anchor",
            "name": "4.2",
            "akind": "section",
            "cite": "d7#40",
            "span": [0, 3],
            "scope": "document",
            "surface": "4.2 Indemnity",
        },
        {"t": "cover", "lane": "anchor", "cites": ["d7#40"]},
    ]


def test_an_anchor_mark_on_the_wire_is_read(tmp_path: Path) -> None:
    mark = [0, 0, "anchor", {"name": "_Toc7", "akind": "bookmark"}]
    frames = run(tmp_path, view(SEG, block("d7#1", "Plain text", kind="paragraph", marks=[mark])))
    assert frames[1]["name"] == "_Toc7"
    assert frames[1]["span"] == [0, 0]


def test_a_segment_declaring_nothing_is_cover_empty(tmp_path: Path) -> None:
    frames = run(tmp_path, view(SEG, block("d7#1", "Nothing", kind="paragraph")))
    assert frames[1:] == [{"t": "cover_empty", "lane": "anchor", "reason": EMPTY_REASON}]


def test_a_view_that_is_not_the_segment_form_is_corrupt_input(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as caught:
        run(tmp_path, view({"t": "doc", "doc": "d7"}))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT


# -- marks and label in the view -----------------------------------------------------------------


def test_marks_and_label_decode() -> None:
    marks = [[0, 4, "bold", None], [2, 2, "anchor", {"name": "x", "akind": "bookmark"}]]
    [member] = read_segment_view(
        view(SEG, block("d7#1", "abcd", kind="list_item", marks=marks, label="(a)"))
    ).members
    assert member.label == "(a)"
    assert member.marks == (
        Mark(0, 4, "bold", None),
        Mark(2, 2, "anchor", {"name": "x", "akind": "bookmark"}),
    )


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ({"marks": {}}, "marks is not a list"),
        ({"marks": [[0, 1, "bold"]]}, "a mark is not"),
        ({"marks": [[2, 1, "bold", None]]}, "a mark is not"),
        ({"marks": [[-1, 1, "bold", None]]}, "a mark is not"),
        ({"marks": [[0, 1, 7, None]]}, "a mark is not"),
        ({"marks": [[True, 1, "bold", None]]}, "a mark is not"),
        ({"label": 3}, "label is not a string"),
    ],
)
def test_a_malformed_mark_or_label_is_corrupt_input(extra: dict[str, Any], says: str) -> None:
    with pytest.raises(DriverError) as caught:
        read_segment_view(view(SEG, block("d7#1", "abcd", **extra)))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
    assert says in str(caught.value)
