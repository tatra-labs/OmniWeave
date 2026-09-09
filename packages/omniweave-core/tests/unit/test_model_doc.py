"""`Doc` is lazy, and the laziness is MEASURED rather than asserted.

Three assertions here are the work item and the rest support them
(03-document-model.md section 13.5, 16-roadmap.md W2.1):

**Constructing a handle reads nothing, and asking for page 3 reads page 3.** Every test in section
1 counts the calls a recording fake received, because a test that only checks returned values
cannot tell a lazy handle from an eager one: an implementation that loaded all 5,000 pages in
`__init__` and filtered in `blocks()` returns exactly the same blocks. 03:2584-2585 is the claim
being tested -- "there is deliberately no `Doc.pages: list[Page]` and no `Doc.blocks:
list[Block]`" -- and 03:2607-2610 is the cost model it protects.

**`Doc.serialize` is `model.serialize` over the resolved scope, byte for byte, in all five
formats.** `Doc.serialize` is a forwarding method (03:2603) and the assertion is equality with the
direct call, so a `Doc` that reordered, re-resolved or post-processed the view would fail rather
than merely differ.

**Nothing bulk is cached.** `payload()` and `grid()` reach the reader on every call; only the one
`doc` row is memoised. 03:983-984 is why for `payload` -- "materialising a JSON object per block
would put a `json.loads` on every row of a 600k-block scan" -- and a memo of them here would be
that dictionary with the cost merely deferred. Asserted by call count.

The fake is hand-written and in-memory. `Doc` must not import `omniweave_core.store` (the
dependency runs the other way) and `store/sqlite.py` is another wave's, so the read side under
test is `DocReadSide`, a structural Protocol, and a recording stub is what a structural Protocol
is for.

Specified in 03-document-model.md section 13.5 (:2572-2627), the `Doc` fence (:2588-2604),
section 4.4's payload reader (:983-995) and section 16.1's serializer (:2809-2811).
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, BinaryIO

import pytest
from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.block import Addr, Block, BlockId, Capabilities, Cite
from omniweave_core.model.doc import DEFAULT_LAYERS, Doc
from omniweave_core.model.enums import Kind, Layer, Method, Quote, RelKind, TableKind, Trust
from omniweave_core.model.grid import Grid, build_grid
from omniweave_core.model.serialize import FORMATS, ViewScope, serialize
from omniweave_core.model.spans import OriginNone

DOC_ORD = 7
GEN = 3
DOC_KEY = bytes(range(32))

CAPS = Capabilities(
    spatial="block_bbox",
    origin_span="exact",
    text_span=True,
    marks=True,
    reading_order="char_stream",
    sections="typed_levels",
    tables="cells_with_spans",
    math=frozenset({"latex"}),
    assets="bytes",
    asset_origin=True,
    notes="linked",
    confidence="element",
    furniture="separated",
    round_trip="passthrough",
)


@dataclass(frozen=True, slots=True)
class Rec:
    """A stand-in for `DocRecord` (03:404-412), which 03 section 2.8 homes in `block.py`'s cluster.

    `Doc.rec` names it as an unresolved forward reference for exactly that reason (see `doc.py`'s
    docstring), so the handle reads whatever the read side hands back and touches only `declared`
    and `achieved`. Two fields is all this test needs; the real record has eighteen.
    """

    doc_ord: int
    gen: int
    declared: Capabilities
    achieved: Capabilities


def a_block(block: int, page: int, order: int, text: str, kind: Kind = Kind.PARAGRAPH) -> Block:
    return Block(
        id=BlockId(block),
        addr=Addr(f"p{page}/{order}"),
        cite=Cite(f"d{DOC_ORD}#{block}"),
        doc_ord=DOC_ORD,
        gen=GEN,
        page=page,
        parent=None,
        ord=order,
        kind=kind,
        raw_kind=None,
        layer=Layer.BODY,
        label=None,
        text=text,
        content_digest=bytes(16),
        layout_digest=None,
        revision=1,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.TEXT_LAYER,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
    )


#: Four pages, three blocks each. Small enough to read, large enough that "page 3 only" is a
#: claim about eight blocks the fake must not have been asked for.
CORPUS: tuple[Block, ...] = tuple(
    a_block(100 * page + order, page, order, f"page {page} block {order}")
    for page in (1, 2, 3, 4)
    for order in (0, 1, 2)
)

FURNITURE: Block = replace(
    a_block(999, 3, 3, "running header"),
    layer=Layer.FURNITURE,
    kind=Kind.PAGE_HEADER,
)


@dataclass(slots=True)
class Fake:
    """A `DocReadSide` that records every call it received, in order.

    `calls` is the whole point: each entry is `(method, arguments)`, so a test asserts what was
    read rather than what came back. Nothing here is a store -- it is a dict -- which is what
    keeps `model` free of `omniweave_core.store` (INV, and `doc.py`'s three reasons).
    """

    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    blocks_by_id: Mapping[BlockId, Block] = field(
        default_factory=lambda: MappingProxyType({b.id: b for b in (*CORPUS, FURNITURE)})
    )

    def named(self, name: str) -> list[tuple[object, ...]]:
        return [args for called, args in self.calls if called == name]

    # -- the thirteen reads --------------------------------------------

    def doc_record(self, doc_ord: int, gen: int) -> Rec:
        self.calls.append(("doc_record", (doc_ord, gen)))
        return Rec(doc_ord, gen, CAPS, replace(CAPS, tables="cells"))

    def block(self, doc_ord: int, gen: int, block: BlockId) -> Block | None:
        self.calls.append(("block", (doc_ord, gen, int(block))))
        return self.blocks_by_id.get(block)

    def block_at_addr(self, doc_ord: int, gen: int, addr: Addr) -> Block | None:
        self.calls.append(("block_at_addr", (doc_ord, gen, str(addr))))
        return next((b for b in self.blocks_by_id.values() if b.addr == addr), None)

    def block_at_cite(self, doc_ord: int, gen: int, cite: Cite) -> Block | None:
        self.calls.append(("block_at_cite", (doc_ord, gen, str(cite))))
        return next((b for b in self.blocks_by_id.values() if b.cite == cite), None)

    def blocks(
        self,
        doc_ord: int,
        gen: int,
        *,
        pages: range | None,
        kinds: frozenset[Kind] | None,
        layers: frozenset[Layer],
        under: BlockId | None,
        trust_below: Trust | None,
    ) -> Iterator[Block]:
        self.calls.append(("blocks", (doc_ord, gen, pages, kinds, layers, under, trust_below)))
        rows = [
            b
            for b in self.blocks_by_id.values()
            if (pages is None or b.page in pages)
            and (kinds is None or b.kind in kinds)
            and b.layer in layers
            and (under is None or b.parent == under)
            and (trust_below is None or b.trust < trust_below)
        ]
        return iter(rows)

    def payload(self, doc_ord: int, gen: int, block: BlockId) -> Mapping[str, Any]:
        self.calls.append(("payload", (doc_ord, gen, int(block))))
        return MappingProxyType({"level": 2}) if int(block) == 101 else MappingProxyType({})

    def frames(self, doc_ord: int, gen: int) -> Iterator[object]:
        self.calls.append(("frames", (doc_ord, gen)))
        return iter(("frame-0", "frame-1"))

    def rels(
        self,
        doc_ord: int,
        gen: int,
        block: BlockId,
        kind: RelKind | None,
        *,
        inbound: bool,
    ) -> Iterator[object]:
        self.calls.append(("rels", (doc_ord, gen, int(block), kind, inbound)))
        return iter((("continues", int(block)),))

    def grid(self, doc_ord: int, gen: int, table: BlockId) -> Grid:
        self.calls.append(("grid", (doc_ord, gen, int(table))))
        return build_grid((), kind=TableKind.DATA, diag=lambda _d: None)

    def page_render(self, doc_ord: int, page: int, dpi: int) -> object:
        self.calls.append(("page_render", (doc_ord, page, dpi)))
        return f"asset:{page}@{dpi}"

    def asset(self, ref: object) -> BinaryIO:
        self.calls.append(("asset", (ref,)))
        return typing.cast("BinaryIO", f"stream:{ref}")

    def verify_quote(self, doc_ord: int, gen: int, block: BlockId) -> str:
        self.calls.append(("verify_quote", (doc_ord, gen, int(block))))
        return "match"

    def resolve_scope(
        self,
        doc_ord: int,
        gen: int,
        *,
        pages: range | None,
        under: BlockId | None,
    ) -> ViewScope:
        self.calls.append(("resolve_scope", (doc_ord, gen, pages, under)))
        chosen = tuple(
            b
            for b in (*CORPUS, FURNITURE)
            if (pages is None or b.page in pages) and (under is None or b.parent == under)
        )
        return ViewScope(
            blocks=chosen,
            kind="document" if pages is None else "pages",
            corpus_id="fixture",
            gen=gen,
        )


def a_doc(fake: Fake | None = None) -> tuple[Doc, Fake]:
    read = fake or Fake()
    return Doc(read, DOC_ORD, GEN, DOC_KEY), read


# ---------------------------------------------------------------------------
# 1. Laziness, measured.
# ---------------------------------------------------------------------------


def test_constructing_a_Doc_reads_nothing_at_all() -> None:  # noqa: N802
    """03:2584: "`Doc` is a **lazy handle**, not a loaded object."

    The identity is available without a read, which is the property the whole of section 13.5
    rests on: a handle to a 5,000-page document costs nothing until something is asked of it.
    """
    doc, read = a_doc()
    assert read.calls == []
    assert (doc.doc_ord, doc.gen, doc.doc_key) == (DOC_ORD, GEN, DOC_KEY)
    assert repr(doc) == "Doc(doc_ord=7, gen=3)"
    assert read.calls == []


def test_asking_for_one_pages_blocks_reads_that_page_and_no_other() -> None:
    """03:2607: "`blocks(pages=range(300, 321))` is a cursor over `block_read`".

    One call reaches the reader, carrying the page range; the returned blocks are page 3's and the
    other nine blocks of the fixture were never materialised. Counting the call is what makes the
    second half checkable at all.
    """
    doc, read = a_doc()
    got = list(doc.blocks(pages=range(3, 4)))
    assert [b.page for b in got] == [3, 3, 3]
    assert read.named("blocks") == [
        (DOC_ORD, GEN, range(3, 4), None, frozenset(DEFAULT_LAYERS), None, None)
    ]
    assert len(read.calls) == 1


def test_blocks_returns_the_readers_cursor_and_does_not_materialise_it() -> None:
    """ "There is deliberately no `Doc.blocks: list[Block]`" (03:2584-2585).

    The returned object is an iterator, and consuming it twice yields nothing the second time --
    which is the observable difference between a cursor and a list, and the reason peak RSS for a
    full scan is the page cache plus one mark window (03:2609) rather than the document.
    """
    doc, _ = a_doc()
    cursor = doc.blocks()
    assert iter(cursor) is cursor
    assert len(list(cursor)) == 12
    assert list(cursor) == []


def test_the_doc_row_is_read_once_and_memoised() -> None:
    """`rec`, `declared` and `achieved` are one row (03:410), so they are one read.

    The memo is the ONE thing this handle holds; 03:2617's "what is never resident" list does not
    contain it, and re-reading it per capability check would issue three statements to answer one
    question about fifteen fields.
    """
    doc, read = a_doc()
    assert doc.rec.doc_ord == DOC_ORD
    assert doc.declared is CAPS
    assert doc.achieved.tables == "cells"
    assert read.named("doc_record") == [(DOC_ORD, GEN)]


def test_a_payload_is_never_memoised() -> None:
    """03:983-984. A cache here is the resident dictionary section 13.5 spent itself refusing."""
    doc, read = a_doc()
    assert doc.payload(BlockId(101)) == {"level": 2}
    assert doc.payload(BlockId(101)) == {"level": 2}
    assert doc.payload(BlockId(102)) == {}
    assert read.named("payload") == [
        (DOC_ORD, GEN, 101),
        (DOC_ORD, GEN, 101),
        (DOC_ORD, GEN, 102),
    ]


def test_a_grid_is_never_memoised() -> None:
    """The cover map is "derived and lazily materialized" (03:1841), so two asks build two.

    A `Doc` that cached grids would hold a 4M-slot cover map for as long as the handle lived,
    which is the one allocation 03:2054-2057 says the lazy materialisation removes.
    """
    doc, read = a_doc()
    doc.grid(BlockId(100))
    doc.grid(BlockId(100))
    assert read.named("grid") == [(DOC_ORD, GEN, 100), (DOC_ORD, GEN, 100)]


def test_serialize_issues_exactly_one_read() -> None:
    """The RESOLVE query is one join, not one statement per block (see `resolve_scope`).

    A `Doc` that built the scope by asking `payload()` per block would issue 600k statements for
    the plan's 5,000-page document, which is the N+1 the Protocol's shape exists to prevent.
    """
    doc, read = a_doc()
    doc.serialize("md", pages=range(1, 2))
    assert read.calls == [("resolve_scope", (DOC_ORD, GEN, range(1, 2), None))]


# ---------------------------------------------------------------------------
# 2. `serialize` agrees with `model.serialize`, byte for byte.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_Doc_serialize_agrees_with_serialize_on_the_same_scope(fmt: str) -> None:  # noqa: N802
    """03:2603 makes it a forwarding method, so equality with the direct call is the whole test."""
    doc, read = a_doc()
    view, smap = doc.serialize(fmt)
    scope = read.resolve_scope(DOC_ORD, GEN, pages=None, under=None)
    direct, direct_map = serialize(scope, fmt)  # type: ignore[arg-type]
    assert view == direct
    assert smap.view_id == direct_map.view_id
    assert [smap.block_at(i) for i in range(len(view))] == [
        direct_map.block_at(i) for i in range(len(direct))
    ]


@pytest.mark.parametrize("fmt", FORMATS)
def test_Doc_serialize_forwards_layers_and_contextualize_unchanged(fmt: str) -> None:  # noqa: N802
    """`layers` is `serialize()`'s argument and not the scope's (03:2810), which is what lets one
    resolved scope render a body view and a body-plus-furniture view without being re-resolved."""
    doc, read = a_doc()
    wanted = frozenset({Layer.BODY, Layer.FURNITURE})
    view, _ = doc.serialize(fmt, layers=wanted, contextualize=True)
    scope = read.resolve_scope(DOC_ORD, GEN, pages=None, under=None)
    direct, _ = serialize(scope, fmt, layers=wanted, contextualize=True)  # type: ignore[arg-type]
    assert view == direct
    assert "running header" in view


def test_serialize_over_a_page_range_is_the_page_ranged_loop_the_plan_requires() -> None:
    """03:2625-2626: "Whole-document rendering is therefore a page-ranged loop by construction."

    The concatenation of the four per-page views is not required to equal the whole-document view
    character for character -- separators differ at the joins -- but every page's text must appear
    in the whole, which is the property a loop relies on.
    """
    doc, _ = a_doc()
    whole, _ = doc.serialize("text")
    for page in (1, 2, 3, 4):
        part, _ = doc.serialize("text", pages=range(page, page + 1))
        assert part
        for line in part.splitlines():
            assert line in whole


def test_serialize_refuses_an_unknown_format_before_resolving_a_scope() -> None:
    """A typo must not cost a resolve of a 5,000-page document."""
    doc, read = a_doc()
    with pytest.raises(UsageError, match="fmt must be one of"):
        doc.serialize("docx")
    assert read.calls == []


# ---------------------------------------------------------------------------
# 3. The twelve methods forward what the plan prints.
# ---------------------------------------------------------------------------


def test_block_raises_on_a_miss_while_by_addr_and_by_cite_return_None() -> None:  # noqa: N802
    """03:2590-2592's asymmetry. An `addr` and a `cite` are names a CALLER supplies; a `BlockId`
    is store-local and "never exported, never shown to a model" (03:270), so a miss is torn."""
    doc, _ = a_doc()
    assert doc.block(BlockId(101)).text == "page 1 block 1"
    with pytest.raises(NotFoundError) as caught:
        doc.block(BlockId(4242))
    assert caught.value.EXIT == 2
    assert doc.by_addr(Addr("p2/1")) is not None
    assert doc.by_addr(Addr("p9/9")) is None
    assert doc.by_cite(Cite("d7#201")) is not None
    assert doc.by_cite(Cite("d7#9999")) is None


def test_blocks_forwards_every_one_of_its_five_filters() -> None:
    """03:2593-2595, keyword-only and in the printed order."""
    doc, read = a_doc()
    list(
        doc.blocks(
            pages=range(1, 3),
            kinds=(Kind.PARAGRAPH,),
            layers=(Layer.BODY, Layer.FURNITURE),
            under=BlockId(100),
            trust_below=Trust.EXTRACTED,
        )
    )
    assert read.named("blocks") == [
        (
            DOC_ORD,
            GEN,
            range(1, 3),
            frozenset({Kind.PARAGRAPH}),
            frozenset({Layer.BODY, Layer.FURNITURE}),
            BlockId(100),
            Trust.EXTRACTED,
        )
    ]


def test_blocks_defaults_to_the_body_layer_alone() -> None:
    """03:1014-1016: furniture is excluded unless asked for, which is the one default that
    changes what the call returns."""
    doc, _ = a_doc()
    assert all(b.layer is Layer.BODY for b in doc.blocks())
    with_furniture = list(doc.blocks(layers=(Layer.BODY, Layer.FURNITURE)))
    assert any(b.layer is Layer.FURNITURE for b in with_furniture)


def test_blocks_consumes_a_generator_argument_before_it_crosses_the_boundary() -> None:
    """A backend that iterated `kinds` twice would see it empty the second time and return the
    whole document. Normalising to a frozenset here is what makes that unreachable."""
    doc, read = a_doc()
    list(doc.blocks(kinds=(k for k in (Kind.PARAGRAPH, Kind.PAGE_HEADER))))
    (args,) = read.named("blocks")
    assert args[3] == frozenset({Kind.PARAGRAPH, Kind.PAGE_HEADER})


def test_a_strided_page_range_is_a_usage_error_decided_before_any_read() -> None:
    """07:1613-1615: "a strided page filter has no index expression and would silently become a
    full scan"."""
    doc, read = a_doc()
    with pytest.raises(UsageError, match="step 1"):
        doc.blocks(pages=range(1, 9, 2))
    assert read.calls == []


def test_a_filter_member_outside_its_closed_domain_is_a_usage_error() -> None:
    """`Kind` and `Layer` are two of the fifteen closed `enum_val` domains (03 section 2.1), and a
    string that looks like a member is the shape of a filter that silently matches nothing."""
    doc, read = a_doc()
    with pytest.raises(UsageError, match="kinds holds Kind"):
        doc.blocks(kinds=("paragraph",))  # type: ignore[arg-type]
    with pytest.raises(UsageError, match="layers holds Layer"):
        doc.blocks(layers=("body",))  # type: ignore[arg-type]
    assert read.calls == []


def test_frames_rels_page_render_asset_and_verify_quote_forward_as_printed() -> None:
    """03:2597-2604. Each is one read with the handle's identity threaded through it."""
    doc, read = a_doc()
    assert list(doc.frames()) == ["frame-0", "frame-1"]
    assert list(doc.rels(BlockId(101))) == [("continues", 101)]
    assert list(doc.rels(BlockId(101), RelKind.CONTINUES, inbound=True)) == [("continues", 101)]
    ref = doc.page_render(3, 200)
    assert ref == "asset:3@200"
    assert doc.asset(ref) == "stream:asset:3@200"
    assert doc.verify_quote(BlockId(101)) == "match"
    assert read.named("frames") == [(DOC_ORD, GEN)]
    assert read.named("rels") == [
        (DOC_ORD, GEN, 101, None, False),
        (DOC_ORD, GEN, 101, RelKind.CONTINUES, True),
    ]
    assert read.named("page_render") == [(DOC_ORD, 3, 200)]
    assert read.named("verify_quote") == [(DOC_ORD, GEN, 101)]


def test_a_negative_doc_ord_or_generation_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="doc_ord"):
        Doc(Fake(), -1, 0)
    with pytest.raises(UsageError, match="gen"):
        Doc(Fake(), 0, -1)


# ---------------------------------------------------------------------------
# 4. The shape rules -- the ones a value cannot state about itself.
# ---------------------------------------------------------------------------


def test_Doc_holds_no_dict_so_nothing_can_be_cached_onto_it_by_accident() -> None:  # noqa: N802
    """`__slots__` is what makes "nothing bulk is resident" (03:2617-2621) structural: a handle
    with a `__dict__` would let any call site attach a materialised page to it."""
    doc, _ = a_doc()
    assert not hasattr(doc, "__dict__")
    assert set(Doc.__slots__) == {"_read", "_rec", "doc_key", "doc_ord", "gen"}
    with pytest.raises(AttributeError):
        doc.pages = []  # type: ignore[attr-defined]


def test_Doc_carries_no_bulk_field_at_all() -> None:  # noqa: N802
    """03:2584-2585 names the two absences by name: no `pages` list and no `blocks` list."""
    assert not hasattr(Doc, "pages")
    assert callable(Doc.blocks)
    assert not isinstance(Doc.blocks, (list, tuple))


def test_no_model_class_here_carries_an_html_or_markdown_field() -> None:
    """INV-1, asserted on the read handle because that is where a cache would be tempting."""
    assert set(Doc.__slots__).isdisjoint({"html", "markdown", "md", "text", "view"})


def test_Doc_is_not_a_dataclass_and_cannot_be_reflected_into_a_wire_schema() -> None:  # noqa: N802
    """Two independent reasons `schema/document-v1.json` stays PENDING, both local facts.

    `tools/schemagen.py`'s `build_schema` reflects dataclasses and refuses anything else, and
    `_object_schema` calls `typing.get_type_hints()`. `Doc` fails both gates: the plan prints
    `class Doc:` undecorated (03:2588), unlike every record in section 2.8, and `Doc.rec`'s
    annotation names `DocRecord`, which section 2.8 homes in `block.py`'s cluster and which has
    not landed. A handle over a live reader has no wire form either way -- 03:2617-2619's list of
    what is never resident is the whole of what this type reaches.
    """
    assert not dataclasses.is_dataclass(Doc)
    with pytest.raises(NameError, match="DocRecord"):
        typing.get_type_hints(Doc.rec.fget)  # type: ignore[union-attr]
