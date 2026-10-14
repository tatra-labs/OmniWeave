"""`parse.docx.native`: compile.docx.native's read_back, over packages `lower()` built. D786.

Each test lowers owflow/1 with `test_docx_lower`'s helpers, reads the `.docx` back with
`DocxReader`, and looks at the `owdoc-fragment/1` it proposes. One decodes it through the store's
own `DocSink`, as an ingest would, and one holds it to R2 (09 section 11.1) over its IL.
"""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the sink wrote.
import zipfile
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.blobs import BlobStore
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.model.block import Capabilities
from omniweave_core.out.roundtrip import ILElement, ReadBlock, r2
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode, records_of
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.detect import StreamHint
from omniweave_ports.types import PartSelector, UnitRef
from omniweave_target_docx.driver import DocxCompiler, table
from omniweave_target_docx.read.driver import MEDIA_TYPE, DocxReader, kinds
from test_docx_lower import Lowered, lowered, section

READER_CARD = (
    Path(__file__).resolve().parents[2] / "src" / "omniweave_target_docx" / "read" / "driver.toml"
)
UNIT = section(
    '<h1 data-ow-el="u01/e2">Results</h1>'
    '<p data-ow-el="u01/e3" data-ow-cite="d7#1">Revenue   rose.<a data-ow-note="n1"></a></p>'
    '<ul data-ow-el="u01/e4"><li data-ow-el="u01/e5">one<ul><li>two</li></ul></li></ul>'
    '<blockquote data-ow-el="u01/e6"><p>Quoted.</p></blockquote>'
    '<table data-ow-el="u01/e7"><caption>Q3</caption><tr><th colspan="2">R</th></tr>'
    '<tr><td data-ow-el="u01/e8" rowspan="2">EU</td><td>1</td></tr><tr><td>2</td></tr></table>'
    '<aside data-ow-footnote="n1" data-ow-el="u01/e9"><p>Audited.</p></aside>',
    el="u01/e1",
)


def _read(out: Lowered, tmp_path: Path) -> list[dict[str, Any]]:
    store = MemoryBlobStore(tmp_path / "read")
    sha = store.add(out.data)
    unit = UnitRef(
        uri="file:///memo.docx",
        part="",
        content_sha256=sha,
        byte_len=len(out.data),
        media_type=MEDIA_TYPE,
    )
    result = DocxReader().parse(unit, PartSelector(), make_io(store, tmp_path / "rio"))
    [ref] = result.produced
    body = ref.inline if ref.inline is not None else store.open(ref.blob or "").read()
    return [dict(r) for r in records_of(body)]


def _blocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["t"] == "block"]


def _by_el(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {b["x"]["x.ow.el"]: b for b in _blocks(records) if "x" in b}


# ---------------------------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------------------------


def test_the_card_is_an_ordinary_parse_card_reached_by_name() -> None:
    card = load_card(READER_CARD.read_bytes(), origin="driver_path", source=str(READER_CARD))
    assert isinstance(card, DriverCard)
    assert (str(card.identity.id), str(card.identity.port)) == ("parse.docx.native", "parse")
    drivers = {e.name: e.value for e in entry_points(group="omniweave.drivers")}
    assert drivers["parse.docx.native"] == "omniweave_target_docx.read"
    assert DocxReader.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    hint = StreamHint(filename="m.docx", extension=".docx", declared_media_type=None, byte_len=9)
    assert DocxReader().sniff(b"PK\x03\x04", hint) == (), "ruling 5: never by content"


# ---------------------------------------------------------------------------------------------
# the read-back
# ---------------------------------------------------------------------------------------------


def test_every_address_lands_on_the_block_of_its_constructs_kind(tmp_path: Path) -> None:
    records = _read(lowered(tmp_path, UNIT, cites={"d7#1": 3}), tmp_path)
    found = {el: (b["kind"], b["text"]) for el, b in _by_el(records).items()}
    assert found == {
        "u01/e1": ("section", "Results\nRevenue rose.\none\ntwo\nQuoted.\nQ3\nR\nEU\n1\n2"),
        "u01/e2": ("heading", "Results"),
        "u01/e3": ("paragraph", "Revenue rose."),
        "u01/e4": ("list", "one\ntwo"),
        "u01/e5": ("list_item", "one\ntwo"),
        "u01/e6": ("blockquote", "Quoted."),
        "u01/e7": ("table", "Q3\nR\nEU\n1\n2"),
        "u01/e8": ("table_cell", "EU"),
        "u01/e9": ("footnote", "Audited."),
    }
    assert _by_el(records)["u01/e3"]["x"]["x.ow.cites"] == ["d7#1"]


def test_every_block_is_a_read_backs(tmp_path: Path) -> None:
    records = _read(lowered(tmp_path, UNIT, cites={"d7#1": 3}), tmp_path)
    assert {(b["method"], b["trust"], b["quote"]) for b in _blocks(records)} == {
        ("roundtrip", "inferred", "normalized")
    }
    assert records[0]["media_type"] == MEDIA_TYPE


def test_units_are_sections_and_cells_carry_their_spans(tmp_path: Path) -> None:
    records = _read(lowered(tmp_path, UNIT, section("<p>Second.</p>"), cites={"d7#1": 3}), tmp_path)
    roots = [b for b in _blocks(records) if b["parent"] is None]
    assert [(b["kind"], b["layer"]) for b in roots] == [
        ("section", "body"),
        ("section", "body"),
        ("footnote", "note"),
    ]
    cells = [b["cell"] for b in _blocks(records) if b["kind"] == "table_cell"]
    assert cells == [
        {"r": 0, "c": 0, "row_span": 1, "col_span": 2},
        {"r": 1, "c": 0, "row_span": 2, "col_span": 1},
        {"r": 1, "c": 1, "row_span": 1, "col_span": 1},
        {"r": 2, "c": 1, "row_span": 1, "col_span": 1},
    ]
    [table_] = [b for b in _blocks(records) if b["kind"] == "table"]
    assert table_["payload"]["header_rows"] == 0


def test_a_note_reference_is_a_zero_width_mark_naming_its_body(tmp_path: Path) -> None:
    records = _read(lowered(tmp_path, UNIT, cites={"d7#1": 3}), tmp_path)
    by_el = _by_el(records)
    [mark] = by_el["u01/e3"]["marks"]
    assert (mark["kind"], mark["a"], mark["b"], mark["label"]) == ("note_ref", 13, 13, "1")
    assert mark["target_tmp"] == by_el["u01/e9"]["tmp"]
    note_children = [b for b in _blocks(records) if b["parent"] == by_el["u01/e9"]["tmp"]]
    assert {b["layer"] for b in note_children} == {"note"}


def test_lists_keep_their_order_and_nesting(tmp_path: Path) -> None:
    records = _read(lowered(tmp_path, section('<ol start="2"><li>a<ul><li>b</li></ul></li>'
                                              "<li>c</li></ol>")), tmp_path)  # fmt: skip
    blocks = _blocks(records)
    lists = [b for b in blocks if b["kind"] == "list"]
    assert [b["payload"]["ordered"] for b in lists] == [True, False]
    items = [b["text"] for b in blocks if b["kind"] == "list_item"]
    assert items == ["a\nb", "b", "c"]


def test_a_figure_is_its_picture_and_its_caption(tmp_path: Path) -> None:
    import hashlib  # noqa: PLC0415

    from test_docx_lower import SMALL  # noqa: PLC0415

    slot = "asset-slot:" + hashlib.sha256(SMALL).hexdigest()
    out = lowered(
        tmp_path,
        section(f'<figure><img src="{slot}" alt="a chart"><figcaption>C</figcaption></figure>'),
        assets=[SMALL],
    )
    blocks = _blocks(_read(out, tmp_path))
    [figure] = [b for b in blocks if b["kind"] == "figure"]
    kids = [(b["kind"], b["payload"], b["text"]) for b in blocks if b["parent"] == figure["tmp"]]
    assert kids == [("picture", {"alt": "a chart"}, ""), ("caption", None, "C")]


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
            "VALUES('parse.docx', 1, '', X'00')"
        )
        connection.commit()
        producer_id = int(cursor.lastrowid or 0)
    finally:
        connection.close()
    return path, BlobStore(tmp_path / "cas"), producer_id


def test_the_store_takes_the_read_back_as_an_ingest_would(tmp_path: Path) -> None:
    records = _read(lowered(tmp_path, UNIT, cites={"d7#1": 3}), tmp_path)
    path, blobs, producer = _store(tmp_path / "store")
    declared = Capabilities(
        spatial="none",
        origin_span="none",
        text_span=False,
        marks=False,
        reading_order="source",
        sections="outline_from_source",
        tables="cells_with_spans",
        math=frozenset(),
        assets="none",
        asset_origin=False,
        notes="linked",
        confidence="none",
        furniture="destroyed",
        round_trip="structure",
    )
    doc = FragmentDoc(
        doc_key=b"\x01" * 16,
        source_sha256=b"\x02" * 32,
        normalizer=None,
        uri="file:///memo.docx",
        source_bytes=1,
        declared=declared,
        model_version="1.1",
    )
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer,
            origin_operator="parse.docx",
            origin_driver="parse.docx.native",
            driver_schema_v=1,
            blobs=blobs,
        )
        decode(records, sink=sink, doc=doc)
    connection = sqlite3.connect(path)
    try:
        stored = [json.loads(x) for (x,) in connection.execute("SELECT x FROM block")]
        rels = connection.execute("SELECT count(*) FROM rel").fetchone()[0]
    finally:
        connection.close()
    els = sorted(x["x.ow.el"] for x in stored if "x.ow.el" in x)
    assert els == [f"u01/e{n}" for n in range(1, 10)]
    assert rels == 1, "the note reference is its NOTE_REF"


def test_the_read_back_satisfies_r2_over_its_il(tmp_path: Path) -> None:
    """09 section 11.1's R2, for every address whose construct has a kind."""
    records = _read(lowered(tmp_path, UNIT, cites={"d7#1": 3}), tmp_path)
    compiler = DocxCompiler()
    doc = compiler.carrier("il/u01.html", UNIT)
    from omniweave_target_docx.lower._emit import rows_of  # noqa: PLC0415

    rows = rows_of(table())
    kind_map = kinds()
    elements = []
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
    assert len(elements) == 9
    result = r2(elements, blocks, kind_map)
    assert result.passed, result.failures


# ---------------------------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------------------------


def _parse_bytes(tmp_path: Path, data: bytes) -> None:
    store = MemoryBlobStore(tmp_path / "bad")
    sha = store.add(data)
    unit = UnitRef(uri="file:///x.docx", part="", content_sha256=sha, byte_len=len(data))
    DocxReader().parse(unit, PartSelector(), make_io(store, tmp_path / "bio"))


def test_a_docx_this_target_did_not_build_is_refused(tmp_path: Path) -> None:
    out = lowered(tmp_path, section("<p>a</p>"))
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(out.data)) as src, zipfile.ZipFile(buffer, "w") as dst:
        for info in src.infolist():
            if "provenance" not in info.filename:
                dst.writestr(info, src.read(info))
    with pytest.raises(DriverError, match=r"not one compile\.docx\.native built") as caught:
        _parse_bytes(tmp_path, buffer.getvalue())
    assert caught.value.cls is FailureClass.CORRUPT_INPUT


def test_bytes_that_are_not_a_package_are_corrupt(tmp_path: Path) -> None:
    with pytest.raises(DriverError, match="not a package") as caught:
        _parse_bytes(tmp_path, b"not a zip")
    assert caught.value.cls is FailureClass.CORRUPT_INPUT


def test_a_comment_is_an_annotation_block_and_a_manual_regions_text_its_own(
    tmp_path: Path,
) -> None:
    """D787: the reason in the comment, the region's text in its paragraph, which R2 can hold."""
    out = lowered(
        tmp_path,
        section('<div data-ow-el="u01/e2" data-ow-manual="unverifiable_data">a chart</div>'),
    )
    blocks = _blocks(_read(out, tmp_path))
    [comment] = [b for b in blocks if b["kind"] == "comment"]
    assert (comment["layer"], comment["parent"], comment["text"]) == (
        "annotation",
        None,
        "ow:manual unverifiable_data",
    )
    assert comment["payload"] == {"author": "omniweave"}
    region = _by_el(_read(out, tmp_path / "again"))["u01/e2"]
    assert (region["kind"], region["text"]) == ("paragraph", "a chart")
