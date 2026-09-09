"""`Doc` -- the lazy read handle over one document at one generation. 03 section 13.5.

Implements 03-document-model.md:2584-2610: "`Doc` is a **lazy handle**, not a loaded object. There
is deliberately no `Doc.pages: list[Page]` and no `Doc.blocks: list[Block]`; every traversal
returns an iterator." The twelve methods are transcribed from the fence at :2588-2604 in the
printed order, plus the three attributes its first line carries (`rec`, `declared`, `achieved`).
03:987-989 is the second definition site for `payload()` and says the same thing about it: "There
is no `Block.payload`, because materialising a JSON object per block would put a `json.loads` on
every row of a 600k-block scan for a field two consumers read."

**Nothing bulk is resident, and 03:2621 is the constraint.** "The one thing that is resident,
stated plainly" is a `serialize()` result -- "serializing a whole 5,000-page document materialises
the whole view: ~600k blocks x ~250 chars is ~150 MB of Python string plus a `SpanMap` of 600k
intervals at 24 B ~= 14 MB", capped by `MAX_VIEW_BYTES` (03:2621-2627). Everything else on this
handle is a cursor: 03:2617-2619's "what is never resident" list is page renders, asset bytes,
retained parts, the FTS index, "and a `SpanMap` for a document nobody serialized". So this class
holds an identity, a reader, and ONE memo -- the `doc` row -- and materialises nothing else.

**Why the `doc` row may be memoised when nothing else may.** `rec` is one row of fixed shape
(03:404-412), which the `blocks`/`payload`/`asset` reads are not, and `declared`/`achieved` are
fields OF it (03:410) rather than separate reads -- so a `Doc` that re-read the row for every
capability check would issue three statements to answer one question about fifteen booleans.
03:2617's list does not contain it. Nothing else is cached: `payload()` and `grid()` go to the
reader every time, because a memo over 600k payloads is the resident dictionary the plan spent
section 13.5 refusing.

**`Doc` reads through `DocReadSide`, a structural Protocol, and not through
`omniweave_core.store.Reader`.** Three reasons, and any one would settle it:

1. `model` may not import `store`. The dependency runs the other way -- `store/__init__.py` and
   `store/types.py` import `omniweave_core.model.block` and wait on `Grid` (`store/types.py`:34-36)
   -- and an edge back would be a cycle through `model/__init__.py`.
2. `Reader`'s six methods are FROZEN (16-roadmap.md:428) and are the RETRIEVAL boundary: they
   take a `Snapshot` and answer about Channels, narrowing and hydration. Not one of them answers
   "the Block at this addr in this generation", which is what four of `Doc`'s twelve need. Widening
   `Reader` to serve `Doc` is an ADR, not a patch.
3. A T3 Postgres backend has to be able to satisfy this without either side importing the other,
   which is what structural typing is for. `model/rebind.py` records exactly this decision for
   `RebindReadSide`, in the same words.

`Doc` is deliberately **not** on `omniweave_core.model`'s flat re-export surface yet, and that is
a gate and not an oversight -- see the paragraph in `model/__init__.py`'s docstring. Binding the
name flips `tools/schemagen.py`'s `document-v1.json` row from PENDING to LIVE, and `build_schema`
refuses a non-dataclass; `Doc` cannot be one, because it holds a live reader and because
`Doc.rec`'s annotation names `DocRecord`, which 03 section 2.8 homes in `model/block.py`'s cluster
and which has not landed. Reported with the exact edits.

**Five names in the signatures below have no module yet** -- `DocRecord` (03:404), `Rel` (03:439),
`Frame` (03:444), `AssetRef` (03:434) and `QuoteVerdict` (03:1706) -- and each annotation carries
its own `# noqa: F821` naming the line it comes from, which is the form `store/types.py` uses for
`DegradeCause`. A Protocol method has no body and `from __future__ import annotations` makes every
annotation a string, so the reference costs nothing at import time; what it costs is
`typing.get_type_hints()`, which raises here rather than lying.

Stdlib only (INV-2 / G1). One of the nine LAZY subpackages (G17): `import omniweave_core` must not
reach this module.

Tier T-SCHEMA: 02-architecture.md section 2 row 24, which lists `Doc` beside
`Reader.snapshot() -> Snapshot` at 02:109 -- the read side of the L2/L4 boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from enum import Enum
from typing import Any, BinaryIO, Protocol, TypeVar

from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.block import Addr, Block, BlockId, Capabilities, Cite
from omniweave_core.model.enums import Kind, Layer, RelKind, Trust
from omniweave_core.model.grid import Grid
from omniweave_core.model.serialize import FORMATS, ArraySpanMap, ViewScope, serialize

__all__ = ["Doc", "DocReadSide"]

#: `_closed`'s domain parameter. A plain `TypeVar` and not PEP 695's `def f[E](...)`, because
#: `target-version = "py311"` and that syntax is 3.12's.
_Member = TypeVar("_Member", bound=Enum)

#: `Doc.blocks`'s default `layers`, printed as a TUPLE at 03:2594 rather than the `frozenset`
#: `Filters.layers` carries (07:1569). Both spellings say the same thing -- furniture is excluded
#: unless asked for (03:1014-1016) -- and the plan's own spelling is kept here because `blocks()`
#: is 03's signature and `Filters` is 07's.
DEFAULT_LAYERS: tuple[Layer, ...] = (Layer.BODY,)


class DocReadSide(Protocol):
    """What `Doc` reads. The smallest slice of a store the twelve methods need.

    Every method takes the document identity explicitly, because a reader is corpus-scoped and a
    `Doc` is one document at one generation: threading `(doc_ord, gen)` through the call is what
    lets one open reader serve two generations of the same document -- which is exactly what
    `ow doc diff` does across a staged parse (03:2686-2695).

    Structural, not an ABC (18-api-sketch.md:1779's house rule), and not `omniweave_core.store`'s
    `Reader` -- the module docstring gives the three reasons.

    `block_at_cite` takes the generation like the rest, even though a `cite` is DURABLE across
    generations (03:1141, and it is why `block_cite` is not keyed on the generation while
    `block_addr` is). A `Doc` is pinned to one generation, so the block it should answer with is
    that generation's row; a caller wanting the cite's whole history asks
    `follow_supersession()`, which is `rebind.py`'s.
    """

    def doc_record(self, doc_ord: int, gen: int) -> DocRecord:  # noqa: F821 -- 03:404's.
        """The `doc` row as a value. `Doc.rec`'s single read, memoised by the handle."""
        ...

    def block(self, doc_ord: int, gen: int, block: BlockId) -> Block | None:
        """One Block by its store-local id, or `None`. One index seek; 20 us measured (03:2551)."""
        ...

    def block_at_addr(self, doc_ord: int, gen: int, addr: Addr) -> Block | None:
        """One Block by `addr`. `block_addr` is keyed on the generation (charter.md:1082-1086)."""
        ...

    def block_at_cite(self, doc_ord: int, gen: int, cite: Cite) -> Block | None:
        """One Block by `cite`, in this generation. See the class docstring."""
        ...

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
        """A CURSOR over `block_read` under one `Snapshot`, never a list (03:2607-2610).

        "The iterator yields as SQLite pages in, and the reader holds one `Block` plus one
        512-block mark window at a time." `under=` is a recursive descent over `block_parent`,
        "not a scan" (03:2610).
        """
        ...

    def payload(self, doc_ord: int, gen: int, block: BlockId) -> Mapping[str, Any]:
        """One block's `payload`; an empty mapping when the column is NULL (03:988)."""
        ...

    def frames(self, doc_ord: int, gen: int) -> Iterator[Frame]:  # noqa: F821 -- 03:444's.
        """The document's `.owdoc` Frames, located through `frames.json` (03:2612-2615)."""
        ...

    def rels(
        self,
        doc_ord: int,
        gen: int,
        block: BlockId,
        kind: RelKind | None,
        *,
        inbound: bool,
    ) -> Iterator[Rel]:  # noqa: F821 -- 03:439's.
        """One block's `rel` rows, outbound by default. The closed seven-member vocabulary."""
        ...

    def grid(self, doc_ord: int, gen: int, table: BlockId) -> Grid:
        """One table's cover map -- `table_meta` + `cell` + `grid_slot`, as a `Grid`."""
        ...

    def page_render(self, doc_ord: int, page: int, dpi: int) -> AssetRef:  # noqa: F821 -- 03:434's.
        """LAZY; renders on miss (03:2601). A page render is 10.7 MB decoded and evictable."""
        ...

    def asset(self, ref: AssetRef) -> BinaryIO:  # noqa: F821 -- 03:434's.
        """A STREAM, never bytes (03:2602). `MAX_ASSET_BYTES` is 256 MiB."""
        ...

    def verify_quote(self, doc_ord: int, gen: int, block: BlockId) -> QuoteVerdict:  # noqa: F821 -- 03:1706's.
        """The self-verifying half of confidence; needs no labelled corpus (03:1703-1711)."""
        ...

    def resolve_scope(
        self,
        doc_ord: int,
        gen: int,
        *,
        pages: range | None,
        under: BlockId | None,
    ) -> ViewScope:
        """The RESOLVE query behind `Doc.serialize`: a `ViewScope` and its satellites.

        `ViewScope` "resolves to an ordered, duplicate-free block sequence and carries the corpus
        and the generation it was resolved at" (03:2814-2816), and `model/serialize.py`'s own
        docstring names the query that fills it -- "the pre-order walk over `block_parent`
        restricted to `state = 0`" -- as the store's half of W2.8. It belongs on this Protocol
        rather than being assembled per block by `Doc`, because the satellites (`payload`,
        `table_meta`, `cell`, `rel(continues)`, `heading_path`) are joins one `Snapshot` can do
        once, and asking for them one block at a time is the N+1 that would make `serialize()`
        cost 600k statements.

        `layers` is deliberately NOT a parameter: it is an argument of `serialize()` (03:2810), so
        one resolved scope serialises to a body view and to a body-plus-notes view without being
        re-resolved.
        """
        ...


class Doc:
    """One document, at one generation, read on demand. 03:2588-2604.

    Constructing one reads NOTHING. The identity is `(doc_ord, gen, doc_key)` and the reader is
    held, not consulted; the first read any method performs is the read that method needs, which
    is what makes `blocks(pages=range(300, 321))` a cursor over 21 pages of a 5,000-page document
    rather than a scan of it (03:2607-2610).

    **Not a dataclass, and not frozen.** The plan prints `class Doc:` with three annotated
    attributes and twelve methods (03:2588-2604) and decorates it with nothing, unlike every
    record in 03 section 2.8. Two properties follow from that and both are load-bearing: `rec` is
    a lazily-materialised memo so it cannot be a frozen field, and a handle carrying a live reader
    is not a value -- it has no meaningful equality and no wire form, which is why
    `schema/document-v1.json` cannot be generated from it (see the module docstring).

    `__slots__` because the alternative is a `__dict__` on the one object every read goes through.

    `doc_key` is typed `bytes` rather than `DocKey`: `DocKey = NewType("DocKey", bytes)` is 03
    section 2.2's fourth identity and `model/block.py` records why it is deliberately absent from
    that cluster -- "its only consumer is `DocRecord` (03 section 2.8), which this cluster does not
    own". Naming it here would be the same violation from the other side.
    """

    __slots__ = ("_read", "_rec", "doc_key", "doc_ord", "gen")

    def __init__(self, read: DocReadSide, doc_ord: int, gen: int, doc_key: bytes = b"") -> None:
        """The identity plus the reader. **No read happens here.**

        `doc_key` defaults to empty because a `Doc` is addressed by `doc_ord` in every one of the
        twelve reads -- `doc_key` is the CONTENT identity the ingest path deduplicates on
        (03:405) and a reader that already has a `doc_ord` has already resolved it. Carrying it is
        for the caller who needs to say WHICH document this handle is without paying for `rec`.
        """
        if doc_ord < 0 or gen < 0:
            msg = f"a Doc is (doc_ord >= 0, gen >= 0), not ({doc_ord}, {gen})"
            raise UsageError(msg, fix="ow doc show <cite>  # name a document that exists")
        self._read = read
        self.doc_ord = doc_ord
        self.gen = gen
        self.doc_key = doc_key
        self._rec: DocRecord | None = None  # noqa: F821 -- 03:404's.

    def __repr__(self) -> str:
        """Identity only. A `repr` that touched `rec` would make debugging issue a store read."""
        return f"Doc(doc_ord={self.doc_ord}, gen={self.gen})"

    # -- the three attributes -- 03:2589 ---------------------------------

    @property
    def rec(self) -> DocRecord:  # noqa: F821 -- 03:404's.
        """The `doc` row. ONE read, memoised; see the module docstring's second paragraph.

        `DocRecord.gen` "is the generation this record *describes*: the target generation `g_t`
        while a parse is running, the committed head afterwards" (03:449-450), so a `Doc` at
        `gen = g_t` and a `Doc` at `gen = g_h` are two handles with two records, which is why the
        memo is per handle and not per document.
        """
        if self._rec is None:
            self._rec = self._read.doc_record(self.doc_ord, self.gen)
        return self._rec

    @property
    def declared(self) -> Capabilities:
        """The driver card's claim, copied onto `doc` at parse time (03:533-536).

        A field OF `rec` (03:410) rather than a separate read, so asking for it materialises the
        one row and nothing more.
        """
        return self.rec.declared

    @property
    def achieved(self) -> Capabilities:
        """What the driver actually delivered on THIS document. **Serve reads `achieved`.**

        Computed by the host from the committed rows rather than reported by the driver (INV-7 at
        the capability grain, 03:536), and it may be lower than `declared`, never higher: "a card
        cannot know what a particular PDF permitted" (charter section 5 X9).
        """
        return self.rec.achieved

    # -- the twelve methods, in the printed order -- 03:2590-2604 --------

    def block(self, id: BlockId) -> Block:  # noqa: A002 -- 03:2590 fixes the parameter name.
        """One Block by id. Raises rather than returning `None`, exactly as printed.

        `by_addr` and `by_cite` return `Block | None` and this does not, and the asymmetry is the
        plan's: an `addr` and a `cite` are names a CALLER supplies and may get wrong, while a
        `BlockId` is "store-local, durable ... never exported, never shown to a model" (03:270),
        so an id that answers nothing is a torn read or a retired row and not a lookup miss.
        """
        found = self._read.block(self.doc_ord, self.gen, id)
        if found is None:
            msg = f"no block {int(id)} in document {self.doc_ord} at generation {self.gen}"
            raise NotFoundError(msg, fix="ow doc show d<doc_ord>  # list the document's blocks")
        return found

    def by_addr(self, a: Addr) -> Block | None:
        """One Block by its positional address. `None` is a miss, not an error.

        An `addr` is "unique per `(doc_ord, gen)` -- `addr` is a POSITION, so it legitimately
        repeats across generations" (03:1089-1091), which is why this reads at THIS handle's
        generation and not at the head.
        """
        return self._read.block_at_addr(self.doc_ord, self.gen, a)

    def by_cite(self, c: Cite) -> Block | None:
        """One Block by its durable, prompt-safe name. `None` is a miss, not an error."""
        return self._read.block_at_cite(self.doc_ord, self.gen, c)

    def blocks(
        self,
        *,
        pages: range | None = None,
        kinds: Iterable[Kind] | None = None,
        layers: Iterable[Layer] = DEFAULT_LAYERS,
        under: BlockId | None = None,
        trust_below: Trust | None = None,
    ) -> Iterator[Block]:
        """An ITERATOR over the document's blocks. 03:2593-2595; keyword-only, as printed.

        "There is deliberately no `Doc.blocks: list[Block]`" (03:2584-2585). What comes back is
        the reader's cursor, unwrapped: this method does not materialise it, does not count it and
        does not buffer it, so peak RSS for a full-document scan is "the configured SQLite page
        cache (64 MB) plus that window" (03:2609) and nothing this class adds.

        `pages` must be a `range` of step 1 -- "a strided page filter has no index expression and
        would silently become a full scan" (07:1613-1615). The check is here rather than in the
        backend because it is a usage error, decided before any read.

        `kinds` and `layers` are normalised to frozensets before they cross the boundary: a
        generator argument would be consumed by the first backend that iterated it twice, and a
        frozenset is what `Filters` carries (07:1566-1569) so the two boundaries agree.
        """
        if pages is not None and pages.step != 1:
            msg = f"pages must be a range of step 1, not step {pages.step} (07:1613)"
            raise UsageError(msg, fix="ow doc show --pages 300-320 d<doc_ord>")
        return self._read.blocks(
            self.doc_ord,
            self.gen,
            pages=pages,
            kinds=None if kinds is None else _closed(kinds, Kind, "kinds"),
            layers=_closed(layers, Layer, "layers"),
            under=under,
            trust_below=trust_below,
        )

    def payload(self, id: BlockId) -> Mapping[str, Any]:  # noqa: A002 -- 03:2596's parameter name.
        """One block's `payload`, or an empty mapping. 03:2596, 03:987-989.

        Never memoised. "Materialising a JSON object per block would put a `json.loads` on every
        row of a 600k-block scan for a field two consumers read" (03:983-984), and a cache of
        them here would be that dictionary with the cost merely deferred.
        """
        return self._read.payload(self.doc_ord, self.gen, id)

    def frames(self) -> Iterator[Frame]:  # noqa: F821 -- 03:444's.
        """The document's Frames, as an iterator. 03:2597."""
        return self._read.frames(self.doc_ord, self.gen)

    def rels(
        self,
        id: BlockId,  # noqa: A002 -- 03:2598 fixes the parameter name.
        kind: RelKind | None = None,
        *,
        inbound: bool = False,
    ) -> Iterator[Rel]:  # noqa: F821 -- 03:439's.
        """One block's relations, as an iterator. 03:2598-2599; `inbound` is keyword-only.

        `kind=None` is every kind of the closed seven-member vocabulary, and `inbound=True`
        reverses the direction rather than adding both -- two calls answer both, and a single call
        that merged them would lose which end the block was.
        """
        return self._read.rels(self.doc_ord, self.gen, id, kind, inbound=inbound)

    def grid(self, id: BlockId) -> Grid:  # noqa: A002 -- 03:2600 fixes the parameter name.
        """One table's `Grid`. 03:2600.

        The cover map is "derived and lazily materialized" (03:1841), and this is the read that
        materialises it: a `Doc` never holds one, so two calls build two grids and a 4M-cell sheet
        is only ever resident while a caller is holding it.
        """
        return self._read.grid(self.doc_ord, self.gen, id)

    def page_render(self, page: int, dpi: int) -> AssetRef:  # noqa: F821 -- 03:434's.
        """A page render. LAZY; renders on miss. 03:2601.

        Returns a REF and not bytes, which is what keeps 03:2617's arithmetic true: a decoded page
        render is 10.7 MB and 5,000 of them are 53.5 GB, so the handle names the asset and
        `asset()` streams it.
        """
        return self._read.page_render(self.doc_ord, page, dpi)

    def asset(self, ref: AssetRef) -> BinaryIO:  # noqa: F821 -- 03:434's.
        """A STREAM, never bytes. 03:2602.

        `MAX_ASSET_BYTES = 268_435_456` is one asset's ceiling (03:2634) and it is 256 MiB, which
        is the number a `bytes` return would have to fit in memory.
        """
        return self._read.asset(ref)

    def serialize(
        self,
        fmt: str,
        *,
        pages: range | None = None,
        under: BlockId | None = None,
        layers: frozenset[Layer] = frozenset({Layer.BODY}),
        contextualize: bool = False,
    ) -> tuple[str, ArraySpanMap]:
        """Build a scope and forward to `omniweave_core.model.serialize`. 03:2603.

        **This is the one thing that is resident** (03:2621-2627). `serialize()` returns a `str`,
        so a whole-document call materialises the whole view -- ~150 MB of Python string plus a
        ~14 MB `SpanMap` for a 5,000-page document -- and `MAX_VIEW_BYTES = 67_108_864` caps it
        with `RESOURCE_LIMIT{MAX_VIEW_BYTES}` naming the knob, "checked incrementally as the
        serializer appends rather than after the memory is spent". So "whole-document rendering is
        therefore a page-ranged loop by construction", and `pages=` is how that loop is written.

        The plan prints `serialize(self, fmt: str, **kw)`. The keywords are spelled out instead,
        which is a deliberate narrowing: `**kw` would accept `layer=` for `layers=` and silently
        render the wrong projection, and every keyword a caller can pass is either this scope's
        selection (`pages`, `under`) or `serialize()`'s own (`layers`, `contextualize`). Reported.

        Exactly ONE read happens here -- `resolve_scope` -- and the projection is then a pure
        function of its arguments, which is projection-law rule 4 (03:2970). `fmt` is checked
        BEFORE that read, so a typo does not cost a resolve of a 5,000-page document.
        """
        if fmt not in FORMATS:
            msg = f"fmt must be one of {FORMATS}, not {fmt!r}"
            raise UsageError(msg, fix="ow doc render --format md <cite>")
        scope = self._read.resolve_scope(self.doc_ord, self.gen, pages=pages, under=under)
        return _serialize(scope, fmt, layers=layers, contextualize=contextualize)

    def verify_quote(self, id: BlockId) -> QuoteVerdict:  # noqa: A002, F821 -- 03:2604, 03:1706.
        """The byte-exactness self-check. 03:2604, 03:1703-1711.

        Four verdicts and no boolean, because `source_ahead` -- "the source is newer and the slice
        still matches" -- **must not read as corruption** (03:1709-1710). "The verdict names what
        it compared against: `{sha256, mtime_ns, part}`."
        """
        return self._read.verify_quote(self.doc_ord, self.gen, id)


def _serialize(
    scope: ViewScope,
    fmt: str,
    *,
    layers: frozenset[Layer],
    contextualize: bool,
) -> tuple[str, ArraySpanMap]:
    """`serialize()` with `fmt` already checked against `FORMATS`.

    `serialize`'s own `fmt` parameter is a `Literal` of the five (03:2809), and `Doc.serialize`'s
    is a `str` because 03:2603 prints it that way. The narrowing happens once, at the check above,
    and this shim is where the type system is told so -- rather than a `# type: ignore` on the
    call, which would suppress every other argument's checking with it.
    """
    return serialize(scope, fmt, layers=layers, contextualize=contextualize)  # type: ignore[arg-type]


def _closed(values: Iterable[_Member], domain: type[_Member], name: str) -> frozenset[_Member]:
    """One filter argument as a frozenset, with every member checked against its closed domain.

    A generator is consumed here rather than at the backend, which is the bug this exists to make
    impossible: a `Reader` that iterated `kinds` twice would see it empty the second time and
    return the whole document. Membership is checked because `Kind` and `Layer` are two of the
    fifteen closed `enum_val` domains (03 section 2.1) and a string that looks like a member is
    the shape of a filter that silently matches nothing.
    """
    out = frozenset(values)
    for value in out:
        if not isinstance(value, domain):
            msg = f"{name} holds {domain.__name__} members, not {type(value).__name__} ({value!r})"
            raise UsageError(msg, fix=f"ow doc show --{name} <member> d<doc_ord>")
    return out
