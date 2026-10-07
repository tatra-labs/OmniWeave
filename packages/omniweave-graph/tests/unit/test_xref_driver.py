"""`ReferencePatterns` on the wire: a document's Segments in, `xref` frames and cover out. D669."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_graph.xref import rules
from omniweave_graph.xref.driver import DRIVER_ID, EMPTY_REASON, LANE, ReferencePatterns
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef


def view(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


def seg(name: str = "seg:9f2c1d4a77b03e51") -> dict[str, Any]:
    return {"t": "segment", "seg": name, "heading_path": []}


def block(cite: str, text: str) -> dict[str, Any]:
    return {"t": "block", "cite": cite, "kind": "paragraph", "text": text}


def run(tmp_path: Path, *views: bytes, cancel_after: int = 0) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"doc:{i}", part="", content_sha256=blobs.add(v), byte_len=len(v))
        for i, v in enumerate(views)
    )
    io = make_io(blobs, tmp_path / "tmp", cancel_after_progress=cancel_after)
    result = ReferencePatterns().derive(
        DeriveScope(lane=LANE, units=units, allowed_cites=frozenset()), io
    )
    assert result.outcome == "ok"
    [ref] = result.produced
    assert ref.kind == "graph_items"
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    assert ReferencePatterns().is_valid_nonempty(ref)
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_reports_the_pattern_count_and_the_port() -> None:
    verdict = ReferencePatterns.probe(None)  # type: ignore[arg-type]
    assert (verdict.status, verdict.detail) == (ProbeStatus.OK, "6 patterns")
    assert ReferencePatterns.PORT == "derive/1"
    assert DRIVER_ID == "derive.xref.pattern"


def test_a_broken_pattern_file_makes_the_probe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> Any:
        raise ValueError("pattern x: akind or scope is out of vocabulary")

    monkeypatch.setattr("omniweave_graph.xref.driver.patterns", broken)
    verdict = ReferencePatterns.probe(None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.UNAVAILABLE
    assert "pattern x" in verdict.detail


def test_config_takes_nothing() -> None:
    with pytest.raises(ValueError, match="takes no extra"):
        ReferencePatterns(extra=1)


def test_an_occurrence_is_an_xref_frame_then_cover_on_the_xref_lane(tmp_path: Path) -> None:
    text = "Payment is due under Section 4.2(b)."
    frames = run(tmp_path, view(seg(), block("d7#4", text)))
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {
            "t": "xref",
            "name": "4.2(b)",
            "akind": "section",
            "cite": "d7#4",
            "span": [21, 35],
            "surface": "Section 4.2(b)",
        },
        {"t": "cover", "lane": "xref", "cites": ["d7#4"]},
    ]
    assert text[21:35] == "Section 4.2(b)"


def test_a_segment_with_no_reference_is_cover_empty_with_its_reason(tmp_path: Path) -> None:
    frames = run(tmp_path, view(seg(), block("d7#1", "Nothing refers anywhere.")))
    assert frames[1:] == [{"t": "cover_empty", "lane": "xref", "reason": EMPTY_REASON}]


def test_a_documents_segments_each_answer_under_their_own_seg(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        view(
            seg("seg:aaaaaaaaaaaaaaaa"),
            block("d7#1", "See Exhibit C."),
            seg("seg:bbbbbbbbbbbbbbbb"),
            block("d7#2", "No reference."),
        ),
    )
    assert [f["t"] for f in frames] == ["seg", "xref", "cover", "seg", "cover_empty"]


def test_a_truncated_block_is_a_diag_after_the_cover(tmp_path: Path) -> None:
    text = " ".join(f"Section {n}" for n in range(rules.MAX_REF_SITES_PER_BLOCK + 1))
    frames = run(tmp_path, view(seg(), block("d7#1", text)))
    assert [f["t"] for f in frames].count("xref") == rules.MAX_REF_SITES_PER_BLOCK
    diag = frames[-1]
    assert (diag["t"], diag["code"], diag["component"]) == (
        "diag",
        "OW_REFSITE_TRUNCATED",
        DRIVER_ID,
    )


def test_cancellation_is_checked_before_each_unit(tmp_path: Path) -> None:
    one = view(seg(), block("d7#1", "See Section 1."))
    with pytest.raises(DriverError) as caught:
        run(tmp_path, one, one, cancel_after=1)
    assert caught.value.cls is FailureClass.TIMEOUT


def test_a_view_that_is_not_the_segment_form_is_corrupt_input(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as caught:
        run(tmp_path, view({"t": "doc", "doc": "d7"}, block("d7#1", "See Section 1.")))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
