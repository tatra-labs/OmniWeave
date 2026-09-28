"""`store/fragment.py`: `owdoc-fragment/1` decoded into a real `DocSink`, over a real store.

Every test drives the real sink over a freshly migrated store, because the decoder's whole claim is
that what it writes is what `DocSink` accepts -- a fake sink would test the decoder against the
decoder's own idea of the sink. The first test runs the office driver's real output for
`rich.docx`; the rest are hand-built fragments, each with exactly the defect it names.
"""

from __future__ import annotations

import hashlib
import sqlite3  # noqa: TID251 -- the assertions read the rows the sink wrote.
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import ModelError
from omniweave_core.model.block import Capabilities
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import (
    DANGLING_TMP,
    OUT_OF_SCOPE,
    Decoded,
    FragmentDoc,
    decode,
    records_of,
)
from omniweave_ports.types import ArtifactRef, PartSelector

NOW_NS = 1_700_000_000_000_000_000
FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures"
DECLARED = Capabilities(
    spatial="none",
    origin_span="none",
    text_span=False,
    marks=True,
    reading_order="source",
    sections="outline_from_source",
    tables="cells_with_spans",
    math=frozenset({"latex"}),
    assets="bytes",
    asset_origin=True,
    notes="linked",
    confidence="none",
    furniture="destroyed",
    round_trip="structure",
)


def _store(tmp_path: Path) -> tuple[Path, BlobStore, int]:
    path = tmp_path / "index.owstore"
    cas = tmp_path / "cas"
    cas.mkdir()
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.office', 1, '', X'00')"
        )
        connection.commit()
        producer_id = int(cursor.lastrowid or 0)
    finally:
        connection.close()
    return path, BlobStore(cas), producer_id


def _doc(key: bytes = b"\x01" * 16) -> FragmentDoc:
    return FragmentDoc(
        doc_key=key,
        source_sha256=b"\x02" * 32,
        normalizer=None,
        uri="c:/docs/memo.docx",
        source_bytes=100,
        declared=DECLARED,
        model_version="1.1",
    )


def _run(
    tmp_path: Path,
    records: list[Mapping[str, Any]] | list[dict[str, Any]],
    *,
    assets: tuple[ArtifactRef, ...] = (),
    selector: PartSelector = PartSelector(),  # noqa: B008
) -> tuple[Decoded, Path]:
    path, blobs, producer_id = _store(tmp_path)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.office",
            origin_driver="parse.office.anydoc",
            driver_schema_v=1,
            blobs=blobs,
        )
        decoded = decode(records, sink=sink, doc=_doc(), assets=assets, selector=selector)
    return decoded, path


def _rows(path: Path, sql: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _block(tmp: str, text: str = "words", **extra: Any) -> dict[str, Any]:
    return {
        "t": "block",
        "tmp": tmp,
        "parent": None,
        "page": 0,
        "kind": "paragraph",
        "layer": "body",
        "text": text,
        "quote": "normalized",
        "trust": "extracted",
        "method": "native_xml",
        "os": {"k": "none"},
        "quad": None,
        "marks": [],
        "payload": None,
        **extra,
    }


HEAD: list[dict[str, Any]] = [
    {"t": "doc", "format": "docx", "media_type": "application/x-test", "page_count": 1},
    {"t": "page", "page": 0, "page_kind": "stream", "method": "native_xml"},
]
END: dict[str, Any] = {"t": "end", "status": "ok", "page_stats": {"0": {"blocks": 1}}}


# ---------------------------------------------------------------------------------------------
# the real driver's output
# ---------------------------------------------------------------------------------------------


def test_the_office_drivers_real_fragment_commits_one_visible_generation(tmp_path: Path) -> None:
    """`rich.docx` through the office driver, then through this decoder into a real `DocSink`.

    Twenty-four blocks plus the root the host mints; the table's five origin cells; the one asset;
    the footnote reference written as a `NOTE_REF` rel -- which is what makes the store's own
    `notes` rollup read `linked` (D587) -- and the picture's block->asset link counted, not
    written, because `DocSink` has no `block_asset` writer (D586)."""
    from omniweave_conform.harness import Fixture, run_parse  # noqa: PLC0415
    from omniweave_office.driver import AnydocParser  # noqa: PLC0415

    run = run_parse(AnydocParser(), Fixture.of(FIXTURES / "rich.docx"), tmp_path / "kit")
    decoded, path = _run(
        tmp_path, list(records_of(run.body)), assets=tuple(run.result.produced[1:])
    )
    assert (decoded.pages, decoded.blocks, decoded.assets, decoded.rels) == (1, 24, 1, 1)
    assert decoded.asset_links_dropped == 1
    assert (decoded.record.doc_ord, decoded.record.gen, decoded.status) == (1, 1, "ok")
    assert decoded.record.achieved.notes == "linked"
    assert _rows(path, "SELECT count(*) FROM block") == [(25,)]
    assert _rows(path, "SELECT count(*) FROM cell") == [(5,)]
    assert _rows(path, "SELECT gen, format FROM doc") == [(1, "docx")]
    assert _rows(path, "SELECT addr FROM block WHERE parent_id IS NULL") == [("doc",)]


def test_the_host_mints_the_document_root_and_a_null_parent_is_a_page_root(
    tmp_path: Path,
) -> None:
    """04's worked driver (04:2268) emits `"parent": None` and no `document` block; `DocSink`
    requires exactly one parentless `document` (03:1098). The decoder mints it."""
    decoded, path = _run(tmp_path, [*HEAD, _block("b1"), _block("b2"), END])
    assert decoded.blocks == 2
    rows = _rows(path, "SELECT addr, kind FROM block ORDER BY block_id")
    assert [addr for addr, _kind in rows] == ["doc", "p0/0", "p0/1"]


def test_marks_carry_03s_value_shapes_and_a_note_ref_becomes_a_rel(tmp_path: Path) -> None:
    """A link's `{target, kind}`, a plain mark's null, and a forward `note_ref` whose target is
    defined on a LATER line -- resolved once minted, as a rel, with the mark's label kept."""
    marks = [
        {"kind": "bold", "a": 0, "b": 2},
        {"kind": "link", "a": 3, "b": 5, "target": "https://x.invalid", "target_kind": "external"},
        {"kind": "note_ref", "a": 5, "b": 5, "target_tmp": "n1", "label": "1"},
    ]
    note = _block("n1", "a note", kind="footnote", layer="note", payload={"note_id": "1"})
    decoded, path = _run(tmp_path, [*HEAD, _block("b1", "ab cd", marks=marks), note, END])
    assert decoded.rels == 1
    values = _rows(path, "SELECT kind, value FROM mark ORDER BY a, b, kind")
    assert values == [
        ("bold", None),
        ("link", '{"kind":"external","target":"https://x.invalid"}'),
        ("note_ref", '{"label":"1"}'),
    ]  # fmt: skip


# ---------------------------------------------------------------------------------------------
# the two fragment refusals, 04:1797-1798
# ---------------------------------------------------------------------------------------------


def test_a_parent_no_earlier_record_defined_fails_the_whole_document(tmp_path: Path) -> None:
    with pytest.raises(ModelError) as caught:
        _run(tmp_path, [*HEAD, _block("b1", parent="ghost"), END])
    assert caught.value.code() == DANGLING_TMP


def test_a_tmp_defined_twice_fails_the_whole_document(tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="defined twice") as caught:
        _run(tmp_path, [*HEAD, _block("b1"), _block("b1"), END])
    assert caught.value.code() == DANGLING_TMP


def test_a_note_ref_to_nothing_fails_before_the_generation_is_visible(tmp_path: Path) -> None:
    """The check fires before `end_doc`, so the staged page is durable and invisible."""
    marks = [{"kind": "note_ref", "a": 0, "b": 0, "target_tmp": "nowhere", "label": "9"}]
    path = tmp_path / "index.owstore"
    with pytest.raises(ModelError, match="nowhere") as caught:
        _run(tmp_path, [*HEAD, _block("b1", marks=marks), END])
    assert caught.value.code() == DANGLING_TMP
    assert _rows(path, "SELECT gen FROM doc") == [(0,)], "gen 0 is 'no committed generation'"


def test_a_page_outside_the_part_selector_is_refused_before_it_opens(tmp_path: Path) -> None:
    head = [HEAD[0], {**HEAD[1], "page": 7}]
    with pytest.raises(ModelError) as caught:
        _run(tmp_path, [*head, _block("b1", page=7), END], selector=PartSelector(pages=(0, 1)))
    assert caught.value.code() == OUT_OF_SCOPE


def test_an_empty_selector_is_the_whole_document(tmp_path: Path) -> None:
    head = [HEAD[0], {**HEAD[1], "page": 7}]
    decoded, _path = _run(tmp_path, [*head, _block("b1", page=7), END])
    assert decoded.pages == 1


# ---------------------------------------------------------------------------------------------
# the stream's own grammar
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([HEAD[1], _block("b1"), END], "begins with its `doc` record"),
        ([*HEAD, _block("b1")], "no `end` record"),
        ([HEAD[0], END], "no `page` record"),
        ([*HEAD, {"t": "chapter"}, END], "is not one of"),
        ([*HEAD, END, _block("b1")], "after `end`"),
        ([*HEAD, HEAD[0], END], "second `doc`"),
        ([*HEAD, _block("b1", kind="document"), END], "the host mints the root"),
        ([*HEAD, _block("b1", os={"k": "bytes"}), END], "this decoder reads none"),
        ([*HEAD, _block("b1", trust="certain"), END], "not a Trust member"),
        ([*HEAD, _block("b1", page=3), END], "names page 3 while page 0 is open"),
    ],
)
def test_a_fragment_that_breaks_the_grammar_is_refused(
    tmp_path: Path, records: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ModelError, match=message):
        _run(tmp_path, records)


def test_a_block_before_any_page_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="before any `page` record"):
        _run(tmp_path, [HEAD[0], _block("b1"), END])


def test_an_unknown_block_kind_is_unknown_with_its_raw_kind_kept(tmp_path: Path) -> None:
    """03 section 2.1's producing-side asymmetry: a kind core does not recognise is `unknown`
    plus `raw_kind`, never a refusal -- the reader-side fail-closed rule is not this one."""
    _decoded, path = _run(tmp_path, [*HEAD, _block("b1", kind="marginalia"), END])
    assert _rows(path, "SELECT raw_kind FROM block WHERE raw_kind IS NOT NULL") == [("marginalia",)]


def test_an_asset_is_hashed_by_the_host_and_named_by_its_produced_position(
    tmp_path: Path,
) -> None:
    body = b"\x89PNG not really"
    ref = ArtifactRef(kind="asset", byte_len=len(body), inline=body)
    asset = {"t": "asset", "tmp": "a1", "ord": 0, "media_type": "image/png", "origin_part": "x"}
    decoded, path = _run(tmp_path, [*HEAD, asset, _block("b1"), END], assets=(ref,))
    assert decoded.assets == 1
    assert _rows(path, "SELECT hex(sha256) FROM asset") == [
        (hashlib.sha256(body).hexdigest().upper(),)
    ]


def test_an_asset_naming_a_position_produced_does_not_have_is_dangling(tmp_path: Path) -> None:
    asset = {"t": "asset", "tmp": "a1", "ord": 3, "media_type": "image/png"}
    with pytest.raises(ModelError) as caught:
        _run(tmp_path, [*HEAD, asset, _block("b1"), END])
    assert caught.value.code() == DANGLING_TMP


def test_records_of_reads_ndjson_and_refuses_a_line_that_is_not_an_object() -> None:
    assert list(records_of(b'{"t":"doc"}\n\n{"t":"end"}\n')) == [{"t": "doc"}, {"t": "end"}]
    with pytest.raises(ModelError, match="line 2 is not JSON"):
        list(records_of(b'{"t":"doc"}\n{oops\n'))
    with pytest.raises(ModelError, match="line 1 is not an object"):
        list(records_of(b"[1, 2]\n"))


# ---------------------------------------------------------------------------------------------
# the PDF path: a glyph origin, a quad, and the part they are proved against (D628)
# ---------------------------------------------------------------------------------------------

PDF_FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures"


def _pdf_run(tmp_path: Path, *, retain: bool) -> tuple[Decoded, Path, Any, bytes]:
    """`gen02p.pdf` through the real PDF driver, then this decoder, with or without the part."""
    from omniweave_conform.harness import Fixture, run_parse  # noqa: PLC0415
    from omniweave_pdf.driver import ACHIEVED, PdfiumParser  # noqa: PLC0415

    source = PDF_FIXTURES / "gen02p.pdf"
    raw = source.read_bytes()
    run = run_parse(PdfiumParser(), Fixture.of(source), tmp_path / "kit")
    names = Capabilities.__dataclass_fields__
    declared = Capabilities(
        **{  # type: ignore[arg-type] -- ACHIEVED is the card's own values
            key: frozenset(value) if isinstance(value, list) else value
            for key, value in ACHIEVED.items()
            if key in names
        }
    )
    path, blobs, producer_id = _store(tmp_path)
    with source.open("rb") as handle:
        digest = blobs.put(handle)

    def open_part(sha256: bytes) -> Any:
        return blobs.open(sha256) if retain and sha256 == digest else None

    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.pdf",
            origin_driver="parse.pdf.pdfium",
            driver_schema_v=1,
            blobs=blobs,
        )
        decoded = decode(
            records_of(run.body),
            sink=sink,
            doc=FragmentDoc(
                doc_key=hashlib.sha256(raw).digest()[:16],
                source_sha256=hashlib.sha256(raw).digest(),
                normalizer=None,
                uri="c:/docs/gen02p.pdf",
                source_bytes=len(raw),
                declared=declared,
                model_version="1.1",
            ),
            open_part=open_part,
        )
    return decoded, path, run, digest


def test_the_pdf_drivers_real_fragment_stores_glyph_origins_quads_and_the_retained_part(
    tmp_path: Path,
) -> None:
    """Every text block is `verbatim` on INV-10's `glyphs` branch, so its part is retained and its
    quad is `Quad.from_driver`'s over the page record's frame -- recomputed here from the fragment
    alone, which is the audit 03:1394 promises."""
    from omniweave_core.model.enums import Quote  # noqa: PLC0415
    from omniweave_core.model.spans import OriginGlyphs, Quad  # noqa: PLC0415
    from omniweave_core.store.portable import read_block  # noqa: PLC0415

    decoded, path, run, digest = _pdf_run(tmp_path, retain=True)
    blocks = [record for record in records_of(run.body) if record["t"] == "block"]
    assert (decoded.pages, decoded.blocks, decoded.status) == (2, len(blocks), "ok")
    assert _rows(path, "SELECT path, store_ref IS NOT NULL, sha256 FROM part") == [
        ("pdf/source.pdf", 1, digest)
    ]
    frames = {record["page"]: record for record in records_of(run.body) if record["t"] == "page"}
    first = blocks[0]
    frame = frames[first["page"]]
    text = str(first["text"]).replace("'", "''")
    ((block_id,),) = _rows(path, f"SELECT block_id FROM block WHERE text = '{text}'")  # noqa: S608
    connection = ow.connect(path)
    try:
        stored = read_block(connection, block_id)
    finally:
        connection.close()
    assert stored is not None
    assert stored.text == first["text"]
    assert stored.origin == OriginGlyphs(
        part="pdf/source.pdf",
        extractor=first["os"]["extractor"],
        start=first["os"]["start"],
        length=first["os"]["length"],
    )
    points = first["quad"]
    assert stored.quad == Quad.from_driver(
        [(points[i], points[i + 1]) for i in range(0, 8, 2)],
        origin="bottomleft",
        unit="pt",
        page_h=frame["h_mpt"] / 1000,
        dpi=None,
        rotation=0,
    )
    assert stored.quote is Quote.VERBATIM


def test_a_part_the_host_does_not_hold_is_recorded_unretained(tmp_path: Path) -> None:
    """`store_ref` NULL is the DDL's *"bytes were not retained"* (03:602-604): the row is still
    written, with its digest and length, so the check that fails can name the part."""
    _decoded, path, _run, digest = _pdf_run(tmp_path, retain=False)
    assert _rows(path, "SELECT path, store_ref, sha256 FROM part") == [
        ("pdf/source.pdf", None, digest)
    ]


PDF_HEAD: list[dict[str, Any]] = [
    {"t": "doc", "format": "pdf", "media_type": "application/pdf", "page_count": 1},
    {
        "t": "page",
        "page": 0,
        "page_kind": "page",
        "w_mpt": 612000,
        "h_mpt": 792000,
        "quad_origin": "bottomleft",
        "quad_unit": "pt",
        "quad_dpi": None,
        "rotation": 0,
        "method": "text_layer",
    },
]
GLYPHS = {"k": "glyphs", "part": "pdf/source.pdf", "extractor": "pypdfium2@5.13.0"}


@pytest.mark.parametrize(
    ("page", "block", "said"),
    [
        ({}, {"os": {**GLYPHS, "start": -1, "length": 3}}, "glyphs origin"),
        ({}, {"os": {**GLYPHS, "start": 0}}, "glyphs origin"),
        ({}, {"quad": [0, 0, 1, 1, 2, 2]}, "eight numbers in a pt, emu or px frame"),
        ({"rotation": 90}, {"quad": [0, 10, 5, 10, 5, 0, 0, 0]}, "quad"),
        ({"quad_unit": "px"}, {"quad": [0, 10, 5, 10, 5, 0, 0, 0]}, "eight numbers"),
    ],
)
def test_an_origin_or_a_quad_the_model_refuses_refuses_the_document(
    tmp_path: Path, page: dict[str, Any], block: dict[str, Any], said: str
) -> None:
    """The fail-closed direction, as for the origins: a rotated page's quad cannot be un-rotated
    from the printed signature (`spans._reject_rotation`), and a `px` page needs its dpi."""
    head = [PDF_HEAD[0], {**PDF_HEAD[1], **page}]
    records = [*head, _block("b1", method="text_layer", **block), END]
    with pytest.raises(ModelError, match=said):
        _run(tmp_path, records)
