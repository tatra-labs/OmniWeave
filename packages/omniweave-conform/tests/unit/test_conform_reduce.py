"""`omniweave_conform.reduce`: the frozen `shape` Reduction. D817."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from omniweave_conform.reduce import SHAPE_FORMAT, reduce_shape, shape_counters
from omniweave_core.archive.owdoc import BlockExport, DocHeader, GridRow, RelRow
from omniweave_core.contract import SCHEMA
from omniweave_core.model import (
    Addr,
    Block,
    BlockId,
    Cite,
    Kind,
    Layer,
    Mark,
    Method,
    OriginNone,
    Quad,
    Quote,
    RelKind,
    Trust,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_KEY = "3f2a" + "0" * 60
_QUAD = Quad(0, 0, 10, 0, 10, 10, 0, 10)


def _block(
    addr: str,
    *,
    page: int = 0,
    kind: Kind = Kind.PARAGRAPH,
    layer: Layer = Layer.BODY,
    trust: Trust = Trust.EXTRACTED,
    quote: Quote = Quote.NORMALIZED,
    marks: Sequence[Mark] = (),
    quad: Quad | None = None,
    text: str | None = "SECRET body text",
    tombstoned: bool = False,
) -> BlockExport:
    block = Block(
        id=BlockId(1),
        addr=Addr(addr),
        cite=Cite("d1#1"),
        doc_ord=1,
        gen=1,
        page=page,
        parent=None,
        ord=0,
        kind=kind,
        raw_kind=None,
        layer=layer,
        label=None,
        text=text,
        content_digest=bytes(16),
        layout_digest=None,
        revision=0,
        quad=quad,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.NATIVE,
        trust=trust,
        quote=quote,
        marks=tuple(marks),
        tombstoned=tombstoned,
    )
    return BlockExport(block=block, producer=0)


def _grid(addr: str, *, merges: bool) -> GridRow:
    return GridRow(
        table=Addr(addr),
        n_rows=1,
        n_cols=1,
        row_len=(1,),
        kind="native",
        cells=((0, 0, 1, 1),),
        has_merges=merges,
    )


class Source:
    """A hand-written `Reducible`: five reads, no store."""

    def __init__(
        self,
        blocks: Iterable[BlockExport],
        *,
        rels: Iterable[RelRow] = (),
        grids: Iterable[GridRow] = (),
        diags: Iterable[Mapping[str, Any]] = (),
        page_count: int | None = 2,
        achieved: Mapping[str, Any] | None = None,
    ) -> None:
        self._blocks = tuple(blocks)
        self._rels = tuple(rels)
        self._grids = tuple(grids)
        self._diags = tuple(diags)
        self._page_count = page_count
        self._achieved = (
            {"origin_span": "none", "marks": True, "math": []} if achieved is None else achieved
        )

    def header(self) -> DocHeader:
        return DocHeader(
            doc_key=_KEY,
            gen=1,
            status="ok",
            source={"page_count": self._page_count, "uri": "file:///x.docx"},
            declared={},
            achieved=self._achieved,
        )

    def blocks(self) -> Iterable[BlockExport]:
        return self._blocks

    def rels(self) -> Iterable[RelRow]:
        return self._rels

    def grids(self) -> Iterable[GridRow]:
        return self._grids

    def diags(self) -> Iterable[Mapping[str, Any]]:
        return self._diags


def _document() -> Source:
    return Source(
        [
            _block("doc", kind=Kind.DOCUMENT, quote=Quote.SYNTHETIC, text=None),
            _block("p0/0", kind=Kind.HEADING, quad=_QUAD),
            _block("p0/1", marks=[Mark(0, 4, "bold"), Mark(5, 9, "italic")], quad=_QUAD),
            _block("p0/2", trust=Trust.INFERRED, quote=Quote.REFLOWED, marks=[Mark(0, 3, "bold")]),
            _block("p1/0", page=1, layer=Layer.FURNITURE),
        ],
        rels=[
            RelRow(
                src=Addr("p0/1"),
                dst=Addr("p1/0"),
                kind=RelKind.NOTE_REF,
                producer=0,
                trust=Trust.EXTRACTED,
                origin_operator="parse",
            )
        ],
        grids=[_grid("p0/3", merges=True), _grid("p0/4", merges=False)],
        diags=[{"code": "OW_TABLE_SPAN_CLAMPED"}, {"code": "OW_TABLE_SPAN_CLAMPED"}],
    )


EXPECTED = (
    f"owshape/1  corpus=core@2026.09  doc={_KEY}  driver=parse.office.anydoc@0.2.4"
    f"  schema_v={SCHEMA}\n"
    "achieved.marks true\n"
    "achieved.math []\n"
    "achieved.origin_span none\n"
    "blocks.kind.document 1\n"
    "blocks.kind.heading 1\n"
    "blocks.kind.paragraph 3\n"
    "blocks.layer.body 4\n"
    "blocks.layer.furniture 1\n"
    "blocks.total 5\n"
    "diag.OW_TABLE_SPAN_CLAMPED 2\n"
    "grid.tables_with_merges 1\n"
    "marks.kind.bold 2\n"
    "marks.kind.italic 1\n"
    "pages.total 2\n"
    "quad.present_frac 0.4000\n"
    "quote.normalized 3\n"
    "quote.reflowed 1\n"
    "quote.synthetic 1\n"
    "rel.kind.note_ref 1\n"
    "trust.extracted 4\n"
    "trust.inferred 1\n"
)


def _shape(source: Source) -> str:
    return reduce_shape(source, corpus="core@2026.09", driver="parse.office.anydoc@0.2.4")


def test_the_shape_of_a_small_document() -> None:
    assert _shape(_document()) == EXPECTED


def test_the_header_is_the_charters() -> None:
    head = _shape(_document()).split("\n", 1)[0]
    assert head.split("  ") == [
        SHAPE_FORMAT,
        "corpus=core@2026.09",
        f"doc={_KEY}",
        "driver=parse.office.anydoc@0.2.4",
        f"schema_v={SCHEMA}",
    ]


def test_one_counter_per_line_sorted_lf() -> None:
    text = _shape(_document())
    assert "\r" not in text
    assert text.endswith("\n")
    body = text.splitlines()[1:]
    assert body == sorted(body)
    assert all(len(line.split(" ")) == 2 for line in body)


def test_no_text_reaches_the_shape() -> None:
    assert "SECRET" not in _shape(_document())


def test_block_order_does_not_move_a_byte() -> None:
    source = _document()
    reordered = Source(
        reversed(tuple(source.blocks())),
        rels=source.rels(),
        grids=reversed(tuple(source.grids())),
        diags=source.diags(),
    )
    assert _shape(reordered) == _shape(source)


def test_a_one_counter_change_is_a_one_line_diff() -> None:
    before = _shape(_document()).splitlines()
    blocks = list(_document().blocks())
    first = blocks[1].block
    blocks[1] = replace(blocks[1], block=replace(first, marks=(Mark(0, 1, "underline"),)))
    source = _document()
    after = _shape(
        Source(blocks, rels=source.rels(), grids=source.grids(), diags=source.diags())
    ).splitlines()
    assert sorted(set(after) - set(before)) == ["marks.kind.underline 1"]
    assert set(before) - set(after) == set()


def test_a_tombstoned_block_counts_nowhere() -> None:
    source = _document()
    extra = _block("p1/1", page=1, kind=Kind.TABLE, quad=_QUAD, tombstoned=True)
    with_tomb = Source(
        [*source.blocks(), extra], rels=source.rels(), grids=source.grids(), diags=source.diags()
    )
    assert _shape(with_tomb) == _shape(source)


def test_an_empty_document_has_no_fraction() -> None:
    counters = shape_counters(Source([], page_count=None, achieved={}))
    assert counters == {
        "blocks.total": "0",
        "quad.present_frac": "none",
        "grid.tables_with_merges": "0",
        "pages.total": "none",
    }


def test_a_fraction_is_four_places() -> None:
    blocks = [_block("a", quad=_QUAD), _block("b"), _block("c")]
    assert shape_counters(Source(blocks))["quad.present_frac"] == "0.3333"


def test_an_empty_histogram_bucket_is_not_printed() -> None:
    counters = shape_counters(_document())
    assert "trust.ambiguous" not in counters
    assert "quote.verbatim" not in counters
    assert "rel.kind.caption_of" not in counters
