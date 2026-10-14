"""`parse.pptx.native`: compile.pptx.native's read_back, over decks `lower()` built. D804.

Each test lowers owsvg/1 with `lowered()` (tests/lowerkit.py), reads the `.pptx` back with
`PptxReader`, and looks at the `owdoc-fragment/1` it proposes. One decodes it through the store's
own `DocSink`, as an ingest would, and one holds it to R2 (09 section 11.1) over its IL.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the sink wrote.
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from lowerkit import (  # type: ignore[import-not-found]  # tests/lowerkit.py
    Lowered,
    lowered,
    picture_slot,
    png,
    slide,
)
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.blobs import BlobStore
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.model.block import Capabilities
from omniweave_core.out.lowering import rows_of
from omniweave_core.out.opc import write_opc
from omniweave_core.out.roundtrip import ILElement, ReadBlock, r2
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode, records_of
from omniweave_ports import ArtifactRef, DriverError, FailureClass, ProbeStatus
from omniweave_ports.detect import StreamHint
from omniweave_ports.types import PartSelector, UnitRef
from omniweave_target_pptx.back.driver import MEDIA_TYPE, PptxReader, kinds
from omniweave_target_pptx.driver import PROVENANCE, PptxCompiler, table

READER_CARD = (
    Path(__file__).resolve().parents[2] / "src" / "omniweave_target_pptx" / "back" / "driver.toml"
)
PICTURE = png(4, 4)
UNIT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u01/e1">'
    '<defs><rect id="r" width="5" height="5"/></defs>'
    '<g data-ow-el="u01/e2"><text data-ow-el="u01/e3" y="40" data-ow-cite="d7#1">Revenue '
    '<tspan data-ow-el="u01/e4" font-weight="bold">rose</tspan>'
    '<tspan data-ow-el="u01/e5" x="0" dy="20">in Q3</tspan></text>'
    '<rect data-ow-el="u01/e6" width="10" height="10"/></g>'
    '<a data-ow-el="u01/e7" href="#u01"><text data-ow-el="u01/e8" y="90">Next</text></a>'
    '<use data-ow-el="u01/e9" href="#r" x="50"/>'
    f'<image data-ow-el="u01/e10" href="{picture_slot(PICTURE)}" width="10" height="10"/>'
    '<g data-ow-el="u01/e11" data-ow-manual="unverifiable_data">'
    '<text data-ow-el="u01/e12" y="120">TBD</text></g>'
    f'<image href="{picture_slot(PICTURE)}" width="5" height="5"/>'
    "</svg>"
)
SECOND = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u02/e1">'
    '<g><text y="9">b</text><rect width="1" height="1"/></g>'
    '<text id="t" y="20">c</text><use href="#t" y="40"/>'
    '<text data-ow-el="u02/e2" y="60">d <tspan data-ow-el="u02/e3">e</tspan></text>'
    '<g data-ow-el="u02/e4" data-ow-manual="insufficient_source"><text y="80">f</text></g>'
    "</svg>"
)
SPACED = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u01/e1">'
    '<text y="9">a <tspan data-ow-el="u01/e2">  b  </tspan> c</text>'
    '<text data-ow-el="u01/e3" y="30" xml:space="preserve"> d  '
    '<tspan data-ow-el="u01/e4"> e  f </tspan></text>'
    "</svg>"
)


def _deck(tmp_path: Path, *units: str) -> Lowered:
    return lowered(tmp_path, *units, assets=[PICTURE], cites={"d7#1": 3}, draft=True)


def _parse(tmp_path: Path, data: bytes) -> tuple[ArtifactRef, list[dict[str, Any]]]:
    store = MemoryBlobStore(tmp_path / "read")
    sha = store.add(data)
    unit = UnitRef(
        uri="file:///deck.pptx",
        part="",
        content_sha256=sha,
        byte_len=len(data),
        media_type=MEDIA_TYPE,
    )
    result = PptxReader().parse(unit, PartSelector(), make_io(store, tmp_path / "rio"))
    [ref] = result.produced
    body = ref.inline if ref.inline is not None else store.open(ref.blob or "").read()
    return ref, [dict(r) for r in records_of(body)]


def _read(out: Lowered, tmp_path: Path) -> list[dict[str, Any]]:
    return _parse(tmp_path, out.data)[1]


def _blocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["t"] == "block"]


def _by_el(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {b["x"]["x.ow.el"]: b for b in _blocks(records) if "x" in b}


def _page(records: list[dict[str, Any]], page: int) -> list[tuple[str | None, str, str]]:
    """Each block of one page: its address, its kind and its text, in order."""
    return [
        (b.get("x", {}).get("x.ow.el"), b["kind"], b["text"])
        for b in _blocks(records)
        if b["page"] == page
    ]


# ---------------------------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------------------------


def test_the_card_is_an_ordinary_parse_card_reached_by_name() -> None:
    card = load_card(READER_CARD.read_bytes(), origin="driver_path", source=str(READER_CARD))
    assert isinstance(card, DriverCard)
    assert (str(card.identity.id), str(card.identity.port)) == ("parse.pptx.native", "parse")
    drivers = {e.name: e.value for e in entry_points(group="omniweave.drivers")}
    assert drivers["parse.pptx.native"] == "omniweave_target_pptx.back"
    assert PptxReader.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    hint = StreamHint(filename="d.pptx", extension=".pptx", declared_media_type=None, byte_len=9)
    assert PptxReader().sniff(b"PK\x03\x04", hint) == (), "ruling 5: never by content"
    assert card.parse is not None and card.parse.format_tokens == (), "D812: no pair to back"
    assert card.limits.max_input_bytes == 64 << 20, "D812: under the host's ceiling"


def test_each_slide_is_a_loop_top_and_a_cancelled_read_stops(tmp_path: Path) -> None:
    """D812 (ruling 6), the kit's contract suite: progress after each slide, and a read
    cancelled after the first slide or the last stops as `TIMEOUT`."""
    out = _deck(tmp_path, UNIT, SECOND)
    store = MemoryBlobStore(tmp_path / "cancel")
    sha = store.add(out.data)
    unit = UnitRef(uri="file:///d.pptx", part="", content_sha256=sha, byte_len=len(out.data))
    whole = make_io(store, tmp_path / "whole")
    PptxReader().parse(unit, PartSelector(), whole)
    assert whole.call().progress == [(1, 2), (2, 2)]
    for after in (1, 2):
        cut = make_io(store, tmp_path / f"cut{after}", cancel_after_progress=after)
        with pytest.raises(DriverError, match="cancelled") as caught:
            PptxReader().parse(unit, PartSelector(), cut)
        assert caught.value.cls is FailureClass.TIMEOUT
        assert len(cut.call().progress) == after, "nothing read past the cancel"


def test_a_read_back_is_valid_and_nonempty_by_its_blocks(tmp_path: Path) -> None:
    ref, records = _parse(tmp_path, _deck(tmp_path, UNIT).data)
    assert PptxReader().is_valid_nonempty(ref)
    bare = "".join(
        json.dumps(r, separators=(",", ":")) + "\n" for r in records if r["t"] != "block"
    )
    io_ = make_io(MemoryBlobStore(tmp_path / "bare"), tmp_path / "bio")
    assert not PptxReader().is_valid_nonempty(ArtifactRef.of("doc_fragment", bare.encode(), io_))


# ---------------------------------------------------------------------------------------------
# the read-back
# ---------------------------------------------------------------------------------------------


def test_every_address_lands_on_the_block_of_its_constructs_kind(tmp_path: Path) -> None:
    records = _read(_deck(tmp_path, UNIT), tmp_path)
    found = {el: (b["kind"], b["text"]) for el, b in _by_el(records).items()}
    assert found == {
        "u01/e1": ("section", "Revenue rose\nin Q3\nNext\nTBD"),
        "u01/e2": ("container", "Revenue rose\nin Q3"),
        "u01/e3": ("paragraph", "Revenue rose\nin Q3"),
        "u01/e4": ("paragraph", "rose"),
        "u01/e5": ("paragraph", "in Q3"),
        "u01/e6": ("diagram", ""),
        "u01/e7": ("container", "Next"),
        "u01/e8": ("paragraph", "Next"),
        "u01/e9": ("container", ""),
        "u01/e10": ("picture", ""),
        "u01/e11": ("paragraph", "TBD"),
        "u01/e12": ("paragraph", "TBD"),
    }
    assert _by_el(records)["u01/e3"]["x"]["x.ow.cites"] == ["d7#1"]
    assert "x.ow.cites" not in _by_el(records)["u01/e4"]["x"]
    assert [b["kind"] for b in _blocks(records) if "x" not in b] == ["picture", "comment"]


def test_the_tree_is_the_decks_and_a_runs_block_is_its_text_boxs_child(tmp_path: Path) -> None:
    records = _read(_deck(tmp_path, UNIT), tmp_path)
    blocks = _blocks(records)
    tmp = {b["tmp"]: b for b in blocks}
    by_el = _by_el(records)

    def parent(el: str) -> str | None:
        up = by_el[el]["parent"]
        return None if up is None else tmp[up].get("x", {}).get("x.ow.el")

    assert [parent(f"u01/e{n}") for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)] == [
        "u01/e1",
        "u01/e2",
        "u01/e3",
        "u01/e3",
        "u01/e2",
        "u01/e1",
        "u01/e7",
        "u01/e1",
        "u01/e1",
        "u01/e1",
        "u01/e11",
    ]
    assert by_el["u01/e1"]["parent"] is None
    assert not [b for b in blocks if b["parent"] == by_el["u01/e9"]["tmp"]], "a clone is not read"


def test_each_slide_is_read_by_its_own_addresses(tmp_path: Path) -> None:
    """Rulings 1 and 3 on a second slide: its root, an unaddressed group, an unaddressed `<use>`
    whose clone is not read again, a run, and a manual region, each where `at` put it."""
    records = _read(_deck(tmp_path, UNIT, SECOND), tmp_path)
    assert _page(records, 1) == [
        ("u02/e1", "section", "b\nc\nd e\nf"),
        (None, "container", "b"),
        (None, "paragraph", "b"),
        (None, "diagram", ""),
        (None, "paragraph", "c"),
        (None, "container", ""),
        ("u02/e2", "paragraph", "d e"),
        ("u02/e3", "paragraph", "e"),
        ("u02/e4", "paragraph", "f"),
        (None, "paragraph", "f"),
        (None, "comment", "ow:manual insufficient_source"),
    ]


def test_a_manual_regions_outline_is_a_comment_on_the_annotation_layer(tmp_path: Path) -> None:
    records = _read(_deck(tmp_path, UNIT, SECOND), tmp_path)
    blocks = _blocks(records)
    notes = [b for b in blocks if b["kind"] == "comment"]
    assert [(n["layer"], n["text"], "x" in n) for n in notes] == [
        ("annotation", "ow:manual unverifiable_data", False),
        ("annotation", "ow:manual insufficient_source", False),
    ]
    assert [(n["parent"], n["page"]) for n in notes] == [(None, 0), (None, 1)], "M-INV-5"
    last = [max(i for i, b in enumerate(blocks) if b["page"] == p) for p in (0, 1)]
    assert [blocks.index(n) for n in notes] == last, "after its slide's section"


def test_every_block_is_a_read_backs_and_each_slide_a_page(tmp_path: Path) -> None:
    records = _read(_deck(tmp_path, UNIT, SECOND), tmp_path)
    assert {(b["method"], b["trust"], b["quote"]) for b in _blocks(records)} == {
        ("roundtrip", "inferred", "normalized")
    }
    doc, part, *rest = records
    assert (doc["t"], doc["format"], doc["media_type"], doc["page_count"]) == (
        "doc",
        "pptx",
        MEDIA_TYPE,
        2,
    )
    assert (part["t"], part["path"]) == ("part", "pptx/package")
    pages = [r for r in rest if r["t"] == "page"]
    assert [(p["page"], p["page_kind"], p["w_mpt"], p["h_mpt"]) for p in pages] == [
        (0, "slide", 960_000, 540_000),
        (1, "slide", 960_000, 540_000),
    ]
    [end] = [r for r in rest if r["t"] == "end"]
    assert end["page_stats"] == {"0": {"blocks": 14}, "1": {"blocks": 11}}
    assert [r["t"] for r in rest if r["t"] != "block"] == ["page", "page", "end"]
    second = rest.index(pages[1])
    assert {r["page"] for r in rest[:second] if r["t"] == "block"} == {0}, "page by page"


@pytest.mark.parametrize(
    ("body", "text"),
    [
        ("<text data-ow-el='u01/e2' y='9' xml:space='preserve'> a  b </text>", " a  b "),
        ("<text data-ow-el='u01/e2' y='9'><tspan x='0' dy='9'>a</tspan></text>", "a"),
        (
            "<text data-ow-el='u01/e2' y='9' xml:space='preserve'><tspan x='0' dy='9'>a</tspan>"
            "</text>",
            "\na",
        ),
    ],
)
def test_a_text_boxs_ends_are_trimmed_of_empty_lines_unless_preserved(
    tmp_path: Path, body: str, text: str
) -> None:
    records = _read(_deck(tmp_path, slide(body)), tmp_path)
    assert [(el, kind) for el, kind, _ in _page(records, 0)] == [
        (None, "section"),
        ("u01/e2", "paragraph"),
    ], "an unaddressed slide's section takes no address of its shapes'"
    assert _by_el(records)["u01/e2"]["text"] == text


def test_an_address_its_line_does_not_hold_is_not_placed(tmp_path: Path) -> None:
    """An `at` naming a line its text box lacks places nothing, and R2 says which address."""
    members = dict(_deck(tmp_path, UNIT).members)
    embedded = json.loads(members[PROVENANCE])
    embedded["at"]["u01/e5"]["line"] = 2  # one past its text box's last paragraph
    members[PROVENANCE] = json.dumps(embedded).encode()
    records = _parse(tmp_path, write_opc(members))[1]
    assert sorted(_by_el(records), key=lambda e: int(e[5:])) == [
        f"u01/e{n}" for n in range(1, 13) if n != 5
    ]


# ---------------------------------------------------------------------------------------------
# into the store, and R2
# ---------------------------------------------------------------------------------------------


def _store(tmp_path: Path) -> tuple[Path, BlobStore, int]:
    path = tmp_path / "index.owstore"
    (tmp_path / "cas").mkdir(parents=True)
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1)
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.pptx', 1, '', X'00')"
        )
        connection.commit()
        producer_id = int(cursor.lastrowid or 0)
    finally:
        connection.close()
    return path, BlobStore(tmp_path / "cas"), producer_id


def test_the_store_takes_the_read_back_as_an_ingest_would(tmp_path: Path) -> None:
    records = _read(_deck(tmp_path, UNIT, SECOND), tmp_path)
    path, blobs, producer = _store(tmp_path / "store")
    declared = Capabilities(
        spatial="none",
        origin_span="none",
        text_span=False,
        marks=False,
        reading_order="source",
        sections="outline_from_source",
        tables="none",
        math=frozenset(),
        assets="none",
        asset_origin=False,
        notes="none",
        confidence="none",
        furniture="destroyed",
        round_trip="structure",
    )
    doc = FragmentDoc(
        doc_key=b"\x01" * 16,
        source_sha256=b"\x02" * 32,
        normalizer=None,
        uri="file:///deck.pptx",
        source_bytes=1,
        declared=declared,
        model_version="1.1",
    )
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer,
            origin_operator="parse.pptx",
            origin_driver="parse.pptx.native",
            driver_schema_v=1,
            blobs=blobs,
        )
        decode(records, sink=sink, doc=doc)
    connection = sqlite3.connect(path)
    try:
        stored = [json.loads(x) for (x,) in connection.execute("SELECT x FROM block")]
        kinds_stored = {
            k
            for (k,) in connection.execute(
                "SELECT DISTINCT e.name FROM page p JOIN enum_val e "
                "ON e.domain = 'page_kind' AND e.ord = p.page_kind"
            )
        }
    finally:
        connection.close()
    els = sorted(x["x.ow.el"] for x in stored if "x.ow.el" in x)
    assert els == sorted(
        [*(f"u01/e{n}" for n in range(1, 13)), "u02/e1", "u02/e2", "u02/e3", "u02/e4"]
    )
    assert kinds_stored == {"slide"}


@pytest.mark.parametrize(
    ("units", "count"),
    [((UNIT, SECOND), 16), ((SPACED,), 4)],
    ids=["deck", "spaced"],
)
def test_the_read_back_satisfies_r2_over_its_il(
    tmp_path: Path, units: tuple[str, ...], count: int
) -> None:
    """09 section 11.1's R2, for every address whose construct has a kind."""
    records = _read(_deck(tmp_path, *units), tmp_path)
    rows = rows_of(table())
    kind_map = kinds()
    elements = []
    for n, unit in enumerate(units, 1):
        doc = PptxCompiler().carrier(f"il/u{n:02d}.svg", unit)
        for node in doc.select("@data-ow-el"):
            construct = next(
                r.construct.id
                for r in rows
                if r.selector.kind == "element" and r.selector.matches(node)
            )
            if construct not in kind_map:
                continue
            elements.append(
                ILElement(
                    el=node.el or "",
                    construct=construct,
                    visible_text=doc.visible_text(node),
                    cites=frozenset((node.attr("data-ow-cite") or "").split()),
                )
            )
    blocks = [
        ReadBlock(
            el=b.get("x", {}).get("x.ow.el"),
            kind=b["kind"],
            text=b["text"],
            cites=frozenset(b.get("x", {}).get("x.ow.cites", [])),
        )
        for b in _blocks(records)
    ]
    assert len(elements) == count
    result = r2(elements, blocks, kind_map)
    assert result.passed, result.failures


# ---------------------------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------------------------


def test_a_pptx_this_target_did_not_build_is_refused(tmp_path: Path) -> None:
    out = lowered(tmp_path, slide('<rect width="1" height="1"/>'))
    members = {k: v for k, v in out.members.items() if k != PROVENANCE}
    with pytest.raises(DriverError, match=r"is not one compile\.pptx\.native built") as caught:
        _parse(tmp_path, write_opc(members))
    assert caught.value.cls is FailureClass.CORRUPT_INPUT


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (b"not a zip", "not a package"),
        (write_opc({"[Content_Types].xml": b"<Types/>", "_rels/.rels": b"<Relationships/>",
                    PROVENANCE: b"{}"}), "no ppt/presentation.xml"),
    ],
)  # fmt: skip
def test_a_package_that_is_not_a_deck_is_refused(tmp_path: Path, data: bytes, said: str) -> None:
    with pytest.raises(DriverError, match=said) as caught:
        _parse(tmp_path, data)
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
