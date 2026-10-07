"""`derive.xref.native`: the references a document's own links make. 06 section 3.4, D671."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_graph.links.driver import DRIVER_ID, EMPTY_REASON, LANE, DocumentLinks
from omniweave_graph.links.rules import MAX_REF_SITES_PER_BLOCK, declared_kinds, find
from omniweave_graph.view import Mark, Member
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef


def link(a: int, b: int, target: str, kind: str = "anchor") -> Mark:
    return Mark(a, b, "link", {"target": target, "kind": kind})


def anchor(name: str, akind: str) -> Mark:
    return Mark(0, 0, "anchor", {"name": name, "akind": akind})


def member(text: str, *marks: Mark, cite: str = "d1#1") -> Member:
    return Member(cite=cite, kind="paragraph", text=text, marks=marks)


# -- the rules ------------------------------------------------------------------------------------


def test_an_anchor_link_is_a_reference_named_by_its_target_without_the_hash() -> None:
    text = "See Indemnification below."
    found = find([member(text, link(4, 19, "#_Toc42"))], {})
    [ref] = found.links
    assert (ref.name, ref.akind, ref.span, ref.surface) == (
        "_Toc42",
        "bookmark",
        (4, 19),
        "Indemnification",
    )


def test_the_akind_is_the_one_the_document_declares_for_the_name() -> None:
    kinds = declared_kinds(
        [
            member("Heading", anchor("risk", "section"), anchor("x", "chapter")),
            member("Other", anchor("risk", "bookmark"), Mark(0, 1, "bold", None)),
        ]
    )
    assert kinds == {"risk": "section"}, "first declaration wins; an unknown akind is no kind"
    [ref] = find([member("go to risks", link(6, 11, "risk"))], kinds).links
    assert (ref.name, ref.akind) == ("risk", "section")


@pytest.mark.parametrize(
    "mark",
    [
        link(0, 4, "https://example.com", kind="external"),
        link(0, 4, "other.docx#x", kind="internal"),
        link(0, 4, "#"),
        link(0, 4, "  "),
        link(0, 99, "#x"),
        Mark(0, 4, "link", "not a mapping"),
        Mark(0, 4, "link", {"kind": "anchor"}),
        Mark(0, 4, "bold", None),
    ],
)
def test_what_is_not_an_in_document_reference(mark: Mark) -> None:
    assert find([member("Some text", mark)], {}).links == ()


def test_an_empty_link_takes_its_target_as_its_surface() -> None:
    [ref] = find([member("Text", link(2, 2, "#here"))], {}).links
    assert (ref.span, ref.surface) == ((2, 2), "#here")


def test_at_most_thirty_two_links_per_block_and_the_rest_are_disclosed() -> None:
    marks = [link(i, i + 1, f"#t{i}") for i in range(40)]
    found = find([member("x" * 50, *marks)], {})
    assert [r.name for r in found.links] == [f"t{i}" for i in range(MAX_REF_SITES_PER_BLOCK)]
    [notice] = found.notices
    assert (notice.code, notice.detail["found"]) == ("OW_REFSITE_TRUNCATED", 40)


def test_links_come_back_in_reading_order() -> None:
    found = find([member("abcdefgh", link(5, 6, "#b"), link(1, 2, "#a"))], {})
    assert [r.name for r in found.links] == ["a", "b"]


# -- the driver -----------------------------------------------------------------------------------


def view(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


def seg(name: str) -> dict[str, Any]:
    return {"t": "segment", "seg": name, "heading_path": []}


def block(cite: str, text: str, marks: list[list[Any]] | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"t": "block", "cite": cite, "kind": "paragraph", "text": text}
    if marks:
        frame["marks"] = marks
    return frame


def run(tmp_path: Path, raw: bytes) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    unit = UnitRef(uri="doc", part="", content_sha256=blobs.add(raw), byte_len=len(raw))
    result = DocumentLinks().derive(
        DeriveScope(lane=LANE, units=(unit,), allowed_cites=frozenset()),
        make_io(blobs, tmp_path / "tmp"),
    )
    [ref] = result.produced
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    assert DocumentLinks().is_valid_nonempty(ref)
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_needs_nothing_and_config_takes_nothing() -> None:
    assert DocumentLinks.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert (DocumentLinks.PORT, DRIVER_ID) == ("derive/1", "derive.xref.native")
    with pytest.raises(ValueError, match="takes no x"):
        DocumentLinks(x=1)


def test_a_link_is_typed_by_an_anchor_declared_in_another_segment(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        view(
            seg("seg:aaaaaaaaaaaaaaaa"),
            block("d7#1", "Risk Factors", [[0, 0, "anchor", {"name": "risk", "akind": "section"}]]),
            seg("seg:bbbbbbbbbbbbbbbb"),
            block(
                "d7#9", "See the risks.", [[8, 13, "link", {"target": "#risk", "kind": "anchor"}]]
            ),
        ),
    )
    assert frames == [
        {"t": "seg", "seg": "seg:aaaaaaaaaaaaaaaa"},
        {"t": "cover_empty", "lane": "xref", "reason": EMPTY_REASON},
        {"t": "seg", "seg": "seg:bbbbbbbbbbbbbbbb"},
        {
            "t": "xref",
            "name": "risk",
            "akind": "section",
            "cite": "d7#9",
            "span": [8, 13],
            "surface": "risks",
        },
        {"t": "cover", "lane": "xref", "cites": ["d7#9"]},
    ]


def test_a_view_that_is_not_the_segment_form_is_corrupt_input(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as caught:
        run(tmp_path, view({"t": "doc", "doc": "d7"}))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
