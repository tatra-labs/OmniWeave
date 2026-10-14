"""`omniweave_conform.reduce`: the frozen `shape` (D817) and the tracked `pages` and `outline`
(D818) Reductions."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from omniweave_conform.reduce import (
    OUTLINE_FORMAT,
    OUTLINE_MAX_PAGES,
    PAGES_FORMAT,
    SHAPE_FORMAT,
    reduce_outline,
    reduce_pages,
    reduce_shape,
    shape_counters,
)
from omniweave_core.archive.owdoc import BlockExport, DocHeader, GridRow, RelRow
from omniweave_core.contract import SCHEMA
from omniweave_core.limits import MAX_REDUCTION_BYTES
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


# --- pages (D818) ----------------------------------------------------------------------------


def _digest(*rows: tuple[str, bytes]) -> str:
    """Ruling 7's page digest, restated: sha256 over `addr hex` lines, first 8 hex."""
    return hashlib.sha256("".join(f"{a} {d.hex()}\n" for a, d in rows).encode()).hexdigest()[:8]


def _pages(source: Source, **kw: Any) -> str:
    return reduce_pages(source, corpus="core@2026.09", driver="parse.office.anydoc@0.2.4", **kw)


def _outline(source: Source, **kw: Any) -> str:
    return reduce_outline(source, corpus="core@2026.09", driver="parse.office.anydoc@0.2.4", **kw)


def test_the_pages_of_a_small_document() -> None:
    zero = bytes(16)
    lines = _pages(_document()).splitlines()
    assert lines[0].startswith(f"{PAGES_FORMAT}  corpus=core@2026.09  doc={_KEY}  ")
    assert lines[1:] == [
        "p0000 n=4 kind{document:1,heading:1,paragraph:2} layer{body:4}"
        " trust{extracted:3,inferred:1} quote{normalized:2,reflowed:1,synthetic:1}"
        f" cdig={_digest(('doc', zero), ('p0/0', zero), ('p0/1', zero), ('p0/2', zero))}"
        f" ldig={_digest(('doc', b''), ('p0/0', b''), ('p0/1', b''), ('p0/2', b''))}"
        " diag{}",
        "p0001 n=1 kind{paragraph:1} layer{furniture:1} trust{extracted:1}"
        f" quote{{normalized:1}} cdig={_digest(('p1/0', zero))} ldig={_digest(('p1/0', b''))}"
        " diag{}",
    ]


def test_the_page_histograms_sum_to_the_shape() -> None:
    """The arithmetic the churn classifier will rest on: per-page kinds sum to `shape`'s."""
    shape = shape_counters(_document())
    total: Counter[str] = Counter()
    for line in _pages(_document()).splitlines()[1:]:
        inner = line.split("kind{", 1)[1].split("}", 1)[0]
        for pair in filter(None, inner.split(",")):
            key, value = pair.split(":")
            total[key] += int(value)
    assert {f"blocks.kind.{k}": str(v) for k, v in total.items()} == {
        k: v for k, v in shape.items() if k.startswith("blocks.kind.")
    }


def test_a_paged_diag_lands_on_its_page_and_may_make_one() -> None:
    source = _document()
    paged = Source(
        source.blocks(),
        diags=[
            {"code": "OW_X", "page": 1},
            {"code": "OW_X", "page": 1},
            {"code": "OW_Y", "page": 7},
        ],
    )
    lines = _pages(paged).splitlines()[1:]
    assert lines[1].endswith("diag{OW_X:2}")
    assert lines[2].startswith("p0007 n=0 kind{} layer{} trust{} quote{} cdig=")
    assert lines[2].endswith("diag{OW_Y:1}")


def test_pages_run_in_numeric_order_past_four_digits() -> None:
    blocks = [_block("p10000/0", page=10_000), _block("p9999/0", page=9_999)]
    labels = [line.split(" ", 1)[0] for line in _pages(Source(blocks)).splitlines()[1:]]
    assert labels == ["p9999", "p10000"]


def test_a_text_fix_moves_only_its_pages_cdig() -> None:
    """Section 5.4's `incidental` shape: one digest moves, every count stays."""
    before = _pages(_document()).splitlines()
    blocks = list(_document().blocks())
    blocks[4] = replace(blocks[4], block=replace(blocks[4].block, content_digest=b"\x01" * 16))
    after = _pages(Source(blocks)).splitlines()
    assert before[:2] == after[:2]
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert len(changed) == 1
    old, new = (line.split(" ") for line in changed[0])
    assert [i for i, (x, y) in enumerate(zip(old, new, strict=True)) if x != y] == [6]


def test_pages_over_the_byte_cap_are_one_line() -> None:
    text = _pages(_document(), max_bytes=100)
    size = len(_pages(_document()).encode())
    assert text == f"{PAGES_FORMAT} SUPPRESSED reason=bytes pages=2 would_be_bytes={size}\n"


# --- outline (D818) --------------------------------------------------------------------------


def test_the_outline_of_a_small_document() -> None:
    lines = _outline(_document()).splitlines()
    assert lines[0].startswith(f"{OUTLINE_FORMAT}  corpus=core@2026.09  doc={_KEY}  ")
    zero = "0" * 8
    assert lines[1:] == [
        f"doc document body extracted synthetic {zero} -",
        f"p0/0 heading body extracted normalized {zero} - SECRET body text",
        f"p0/1 paragraph body extracted normalized {zero} - SECRET body text",
        f"p0/2 paragraph body inferred reflowed {zero} - SECRET body text",
        f"p1/0 paragraph furniture extracted normalized {zero} - SECRET body text",
    ]


def test_an_outline_preview_is_one_line_of_48() -> None:
    text = "  Master\tServices\n\nAgreement " + "x" * 80
    block = _block("p0/0", text=text)
    block = replace(block, block=replace(block.block, layout_digest=bytes.fromhex("aa03f7de" * 4)))
    line = _outline(Source([block])).splitlines()[1]
    preview = ("Master Services Agreement " + "x" * 80)[:48]
    assert line == f"p0/0 paragraph body extracted normalized {'0' * 8} aa03f7de {preview}"


def test_the_outline_keeps_the_sources_order() -> None:
    forward = _outline(_document()).splitlines()[1:]
    backward = _outline(Source(reversed(tuple(_document().blocks())))).splitlines()[1:]
    assert backward == forward[::-1]


def test_the_outline_is_suppressed_above_five_hundred_pages() -> None:
    blocks = list(_document().blocks())
    assert _outline(Source(blocks, page_count=500)).count("\n") == 6
    assert _outline(Source(blocks, page_count=501)) == (
        f"{OUTLINE_FORMAT} SUPPRESSED reason=pages pages=501 blocks=5\n"
    )


def test_the_outline_over_the_byte_cap_is_one_line() -> None:
    size = len(_outline(_document()).encode())
    assert _outline(_document(), max_bytes=size) == _outline(_document())
    assert _outline(_document(), max_bytes=size - 1) == (
        f"{OUTLINE_FORMAT} SUPPRESSED reason=bytes blocks=5 would_be_bytes={size}\n"
    )


def test_the_tracked_kinds_never_count_a_tombstone() -> None:
    source = _document()
    tomb = _block("p1/1", page=1, kind=Kind.TABLE, tombstoned=True)
    with_tomb = Source([*source.blocks(), tomb])
    assert _pages(with_tomb) == _pages(Source(source.blocks()))
    assert _outline(with_tomb) == _outline(Source(source.blocks()))


def test_the_cap_is_the_registers_and_the_guard_is_five_hundred() -> None:
    assert MAX_REDUCTION_BYTES == 262_144
    assert OUTLINE_MAX_PAGES == 500
