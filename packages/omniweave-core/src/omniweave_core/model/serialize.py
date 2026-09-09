"""`serialize(scope, fmt) -> (str, SpanMap)` -- the one serializer, over the five core formats.

Implements 03-document-model.md section 16.1 (the signature at :2809-2811, the five-step traversal
at :2825-2843, run-splitting at :2846-2852, the concrete `SpanMap` at :2855-2861 and the
five-format table at :2871-2882), section 16.2 (`view_id`, :2887-2893) and section 16.5's
projection law (:2960-2971). `ViewScope` is declared here because section 16.1 **is** its sole home
(03:3048, closing 03 section 18 Q1 / ADR-1 decision 7); charter D6's runtime `Scope` keeps the bare
name and is a different type in a different layer.

**The one thing this module is for.** A projection is a *function* over the model, never a parallel
representation (INV-1, 03:2776-2779). So there is no `Block.md`, no `Doc.html`, nothing cached back
onto a model object, and `serialize()` reads its argument and returns a string it does not keep.
02:248's semgrep rule asserts the field half; this module's contribution is not to give it anything
to find.

**Every serializer returns `(str, SpanMap)`; there is no text-only entry point** (03:2863-2864,
16-roadmap.md:421: "There is deliberately no text-only serializer: if you have the text you have
the map"). That absence is load-bearing rather than tidy: a caller who can get the text without the
map can quote a serialized view and call the quote verbatim, and a synthetic region -- a `## `, an
`<td>`, a table pipe -- is exactly the text no block ever said. `SERIALIZER_CAPS` is the table that
decides citability, and `spanmap` is deliberately **not** a sixteenth `Capabilities` field
(03:530-534) because a parse driver never calls this function, so the field would have had no
writer and nothing for the conform `capability` suite to assert.

**What this module does NOT reach.** It never imports `omniweave_core.store`: `Snapshot.token` is
opaque by construction (07:72-78) and a projection that typed its reader would make the T3 swap
unrepresentable. `ViewScope` therefore carries an already-resolved block sequence plus the
satellite facts the traversal branches on, and the RESOLVE query that fills it -- the pre-order
walk over `block_parent` restricted to `state = 0` -- is the store's half of W2.8. The same
boundary is why `Grid` is not a parameter here: `Grid` is built only by `build_grid` and is still
owed by P2 (03 section 10.1), so a serializer that took one could not be written yet; the two
`table_meta` columns the traversal actually branches on travel as `TableFacts`, and
`render_grid`'s `Grid`-shaped signature (03:1892) is left to the item that owns `Grid`.

**Determinism is structural, not incidental** (projection law rule 4, 03:2970). Nothing here reads
a clock, an environment variable, `id()` or a set's iteration order: `layers` is consumed only
through `sorted()`, every child list is ordered by `(ord, block_id)`, the root order is the
resolved order the scope carries, and the mark boundary walk is ordered by `(a, b, kind)` exactly
as 03:383 stores them. The only digest is `sha256_canonical`, and `random` is banned in this repo
outright.

Stdlib only (INV-2), and this module lives in one of the nine LAZY subpackages, so nothing eager
may import it (G17).

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal, NamedTuple

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import PolicyRefusal, ResourceLimit, UsageError
from omniweave_core.limits import MAX_EXPANSION, MAX_VIEW_BYTES
from omniweave_core.model.block import Block, BlockId, CellPos, Mark
from omniweave_core.model.enums import Kind, Layer, TableKind
from omniweave_core.model.spans import SERIALIZER_CAPS, RenderSpan, TextSpan

__all__ = [
    "FORMATS",
    "SERIALIZER_VERSION",
    "ArraySpanMap",
    "TableFacts",
    "ViewScope",
    "serialize",
]

#: The `<serializer_version>` component of `view_id`. 03:2887 prints `md/1/7c3f`, so release 1 is
#: version 1. It is part of the view identity precisely so a serializer change invalidates every
#: pinned `RenderSpan` rather than silently re-aiming it at different bytes (03:2890-2893).
SERIALIZER_VERSION: Final = 1

#: The five formats, in `SERIALIZER_CAPS` declaration order. Read off that mapping rather than
#: retyped: the caps table is what decides citability, and a second list of the same five names
#: would be a second place to forget one (INV-21).
FORMATS: Final[tuple[str, ...]] = tuple(SERIALIZER_CAPS)

#: The `fmt` argument's type, spelled as 03:2809 spells it: a `Literal`, not a `str`. The five
#: formats are core's own and closed, so a sixth is a plan change rather than a caller's string.
Fmt = Literal["md", "gfm", "html", "text", "otsl"]

#: The five scope kinds 03:2814-2816 enumerates: a document, a page range, a subtree under one
#: `BlockId`, a Segment, or an explicit tuple from a retrieval result. They are five VALUES of one
#: field rather than five constructors, because the query that resolves each one lives in the store
#: and this module must not import it.
SCOPE_KINDS: Final[tuple[str, ...]] = ("document", "pages", "subtree", "segment", "explicit")

_EMPTY_MAP: Final[Mapping[Any, Any]] = MappingProxyType({})
_NO_ESCAPE: Final[Mapping[str, str]] = MappingProxyType({})
_HEADING_MAX: Final = 6


# ---------------------------------------------------------------------------
# 1. `TableFacts` and `ViewScope` -- what the traversal is given.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TableFacts:
    """The `table_meta` columns section 16.1 actually reads, and no more.

    Step 2 of the traversal reads `kind` -- "a `table` whose `table_meta.kind = 'layout'` and
    `fmt != 'otsl'` is replaced by its cells" (03:2828) -- and the `gfm` row of the format table
    reads `header_rows`: "synthetic delimiter row when `header_rows == 0`" (03:2876).
    `header_cols` comes with it because it is the other half of the same DDL pair (03:1850) and
    because OTSL distinguishes a column header cell from a row header cell.

    This is deliberately not a `Grid`, for the reason the module docstring gives.
    """

    kind: TableKind = TableKind.DATA
    header_rows: int = 0
    header_cols: int = 0


_DEFAULT_TABLE: Final = TableFacts()


@dataclass(frozen=True, slots=True)
class ViewScope:
    """The block selection a projection runs over. 03:2814-2816; sole home 03:3048.

    "It resolves to an ordered, duplicate-free block sequence and carries the corpus and the
    generation it was resolved at" -- so this type **is** that resolution, not a query that would
    have to hold a `Snapshot`. `blocks` is the resolved sequence in resolved order, `kind` records
    which of the five selections produced it, and the satellite mappings carry the facts the
    traversal reads that are not columns of `block`.

    **Why the satellites are mappings and not a reader protocol.** Every one of them is a join the
    RESOLVE query can do in the same `Snapshot` -- `payload`, `table_meta`, `cell`,
    `rel(continues)` and L3's `heading_path` -- and materialising them makes `serialize()` a pure
    function of its arguments, which is projection-law rule 4 (03:2970) expressed in the type
    rather than asserted about it. A reader protocol would put a live cursor inside a function the
    law says has no environment.

    `heading_paths` is L3's: `heading_path` belongs to structure extraction (03:2904), so an absent
    entry means an empty path and `contextualize=True` over a scope with no paths is a no-op rather
    than an error. That is the only way core can honour step 5 without reimplementing an L3
    algorithm it does not own.

    `layers` is NOT a field: it is an argument of `serialize()` (03:2810), so one resolved scope
    serialises to a body view and to a body-plus-notes view without being re-resolved.
    """

    blocks: tuple[Block, ...] = ()
    kind: str = "explicit"
    corpus_id: str = ""
    gen: int = 0
    payloads: Mapping[BlockId, Mapping[str, Any]] = _EMPTY_MAP
    tables: Mapping[BlockId, TableFacts] = _EMPTY_MAP
    cells: Mapping[BlockId, CellPos] = _EMPTY_MAP
    continues: Mapping[BlockId, BlockId] = _EMPTY_MAP
    heading_paths: Mapping[BlockId, tuple[str, ...]] = _EMPTY_MAP

    def __post_init__(self) -> None:
        if not isinstance(self.blocks, tuple):
            msg = f"ViewScope.blocks is the RESOLVED tuple, not {type(self.blocks).__name__}"
            raise TypeError(msg)
        if self.kind not in SCOPE_KINDS:
            msg = f"ViewScope.kind must be one of {SCOPE_KINDS}, not {self.kind!r}"
            raise ValueError(msg)
        seen: set[int] = set()
        for b in self.blocks:
            if not isinstance(b, Block):
                msg = f"ViewScope.blocks holds Block, not {type(b).__name__}"
                raise TypeError(msg)
            if int(b.id) in seen:
                msg = f"ViewScope.blocks is duplicate-free (03:2815); block {int(b.id)} repeats"
                raise ValueError(msg)
            seen.add(int(b.id))

    def payload(self, b: BlockId) -> Mapping[str, Any]:
        """One block's `payload`, or an empty mapping -- never `None`, so no call site branches."""
        got = self.payloads.get(b, _EMPTY_MAP)
        return got if isinstance(got, Mapping) else _EMPTY_MAP

    def table(self, b: BlockId) -> TableFacts:
        """One table's facts. An unrecorded table is a `data` table with no headers, which is the
        DDL's own default (`header_rows INTEGER NOT NULL DEFAULT 0`, 03:1850)."""
        return self.tables.get(b, _DEFAULT_TABLE)


# ---------------------------------------------------------------------------
# 2. `ArraySpanMap` -- the concrete `SpanMap` 03:2855-2861 specifies.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArraySpanMap:
    """Two parallel arrays plus a dict, exactly as 03:2855-2861 prescribes.

    `starts` is strictly increasing and the intervals **partition** `[0, view_len)` with no gap,
    which is what makes `block_at` a `bisect_right(starts, offset) - 1` plus one array read, and
    what makes projection-law rule 3 -- "every character either lifts to exactly one
    `(BlockId, TextSpan)` or is marked synthetic; there is no third case" (03:2967-2969) -- true by
    construction rather than by inspection. `owners[i] is None` marks a synthetic interval: text
    this serializer INVENTED, which therefore belongs to no block.

    `first_last` is 03:2859's `dict[BlockId, tuple[int, int]]`. **It is half-open `[first, end)`**,
    and the plan's phrase "the view's first and last offset" (03:211) does not say which. Every
    other range in this framework is half-open, so an inclusive `last` here would be the single
    off-by-one convention in the model and `view[first:last]` would silently drop a character.
    Recorded as a plan silence, decided here.

    A block that was visited but placed no characters -- an empty `text`, a pure container, a
    `rule` -- carries a zero-length `(pos, pos)`, so `offsets_of` is total over the resolved scope
    and a caller never has to distinguish "no such block" from "contributed nothing".

    Size is the plan's 24 B per interval: three arrays of one machine word each, which is what
    prices a 600k-block view's map at ~14 MB (03:2861, 03:2600).
    """

    view_id: str
    view_len: int
    starts: tuple[int, ...]
    owners: tuple[int | None, ...]
    text_spans: tuple[TextSpan | None, ...]
    first_last: Mapping[int, tuple[int, int]]

    def __post_init__(self) -> None:
        # The one validator for a `view_id` lives in `spans.py` and is reached through the type
        # that carries the rule rather than copied: a second regex would be a second place for the
        # shape to drift from 03:2887.
        RenderSpan(self.view_id, 0, 0)
        if len(self.starts) != len(self.owners) or len(self.starts) != len(self.text_spans):
            msg = "ArraySpanMap's three arrays are parallel and must be the same length"
            raise ValueError(msg)

    @property
    def n_intervals(self) -> int:
        """How many intervals the view decomposed into -- the quantity 03:2861 prices at 24 B."""
        return len(self.starts)

    def _index(self, offset: int) -> int | None:
        """The interval containing `offset`, or `None` when the offset is not in the view.

        Out of range returns `None` rather than raising, which is 03:225's rule applied to the
        probe both public methods share: an offset outside `[0, view_len)` is not a character of
        the view, so it is neither owned nor synthetic and rule 3 does not speak about it.
        """
        if isinstance(offset, bool) or not isinstance(offset, int):
            msg = f"a view offset is an int, not {type(offset).__name__}"
            raise TypeError(msg)
        if offset < 0 or offset >= self.view_len or not self.starts:
            return None
        return bisect_right(self.starts, offset) - 1

    def block_at(self, offset: int) -> tuple[int, TextSpan] | None:
        """The block owning `offset`, and the range of ITS OWN `text` this interval rendered.

        `None` for a synthetic offset and `None` out of range -- **never** an exception (03:225).
        The returned `TextSpan` is the whole interval's span rather than one narrowed to the single
        character, because an interval is the unit the map stores and narrowing would invent a
        precision the substitution cases (one source character rendered `&amp;`) do not have.
        """
        i = self._index(offset)
        if i is None:
            return None
        owner, span = self.owners[i], self.text_spans[i]
        if owner is None or span is None:
            return None
        return (owner, span)

    def is_synthetic(self, offset: int) -> bool:
        """Whether `offset` is text the serializer invented -- a `## `, a `<td>`, a table pipe.

        This is why a quote lifted off a serialized view is not automatically verbatim, and it is
        the half of section 16.5's law a three-method Protocol could not express (03:224-226).
        """
        i = self._index(offset)
        return i is not None and self.owners[i] is None

    def offsets_of(self, b: int) -> tuple[int, int]:
        """The view range `[first, end)` this block contributed to. One dict read (03:2860).

        A block that is not in this view raises the dict's own `KeyError`: the plan spells this as
        one dict read, and asking for a block the view never rendered is a caller bug rather than a
        model condition with an `OW-*` code of its own.
        """
        return self.first_last[int(b)]

    def to_text(self, s: RenderSpan) -> list[tuple[int, TextSpan]]:
        """Clip a `RenderSpan` to the owned intervals it overlaps, in `block.text` coordinates.

        Lifting a span whose `view_id` differs is a `TypeError`, not a silent mis-lift (03:2890),
        and the comparison is `RenderSpan.require_view` so every `SpanMap` raises it the same way.

        An interval whose view length equals its text length is clipped proportionally. One whose
        lengths differ is a single source character rendered as a substitution (`&` as `&amp;`, a
        newline as `<br>`), and a partial overlap of a substitution lifts to the whole source
        character -- there is no fractional character to name.
        """
        s.require_view(self.view_id)
        out: list[tuple[int, TextSpan]] = []
        for i, start in enumerate(self.starts):
            end = self.starts[i + 1] if i + 1 < len(self.starts) else self.view_len
            owner, span = self.owners[i], self.text_spans[i]
            if owner is None or span is None or end <= s.a or start >= s.b:
                continue
            if end - start == span.b - span.a:
                lo = span.a + max(s.a, start) - start
                hi = span.a + min(s.b, end) - start
                out.append((owner, TextSpan(lo, hi)))
            else:
                out.append((owner, span))
        return out


# ---------------------------------------------------------------------------
# 3. The view builder. Every character in the output goes through exactly one of its two
#    entry points, `synthetic()` and `owned()`, which is the mechanism behind rule 3.
# ---------------------------------------------------------------------------


class _View:
    """An append-only string plus the interval arrays, built in one pass.

    Two entry points and no third: `synthetic(text)` for text the serializer invented and
    `owned(text, block, ts_base)` for a range of one block's own `text`. Because there is no way
    to append without choosing, "never neither" is a property of this class rather than an
    assertion about the emitters -- and "never both" follows from the intervals partitioning the
    view.

    `MAX_VIEW_BYTES` is checked **as the serializer appends**, not after the memory is spent
    (03:2604-2607), which is why the byte counter lives here and not at the return.

    The line-prefix stack is how `md`'s `> ` per blockquote line and a list item's continuation
    indent are emitted: a prefix is pushed for the duration of a subtree and flushed lazily at the
    first content of each new line, so no prefix is ever left dangling after the final newline.
    """

    __slots__ = (
        "_bytes",
        "_first_last",
        "_len",
        "_owners",
        "_parts",
        "_pending",
        "_placeholders",
        "_prefix",
        "_prefixes",
        "_spans",
        "_starts",
        "_view_id",
    )

    def __init__(self, view_id: str) -> None:
        self._view_id = view_id
        self._parts: list[str] = []
        self._len = 0
        self._bytes = 0
        self._starts: list[int] = []
        self._owners: list[int | None] = []
        self._spans: list[TextSpan | None] = []
        self._first_last: dict[int, tuple[int, int]] = {}
        self._placeholders: dict[int, int] = {}
        self._prefixes: list[str] = []
        self._prefix = ""
        self._pending = True  # offset 0 is a line start

    # -- prefixes ---------------------------------------------------------

    def push_prefix(self, prefix: str) -> None:
        self._prefixes.append(prefix)
        self._prefix = "".join(self._prefixes)

    def pop_prefix(self) -> None:
        self._prefixes.pop()
        self._prefix = "".join(self._prefixes)

    def _flush_prefix(self) -> None:
        if self._pending:
            self._pending = False
            if self._prefix:
                self._put(self._prefix, None, None)

    # -- appending --------------------------------------------------------

    def _put(self, text: str, owner: int | None, span: TextSpan | None) -> None:
        """The only place the view grows. Merges into the previous interval when it can."""
        if not text:
            return
        self._bytes += len(text.encode("utf-8"))
        if self._bytes > MAX_VIEW_BYTES:
            msg = (
                f"this view reached {self._bytes} bytes, past MAX_VIEW_BYTES={MAX_VIEW_BYTES}; "
                f"serialize a page range instead of a whole document (03:2604)"
            )
            raise ResourceLimit(
                msg,
                limit="MAX_VIEW_BYTES",
                fix="ow open <cite> --pages A-B  # serialize a page range",
            )
        merged = self._merge_into_last(owner, span, len(text))
        if not merged:
            self._starts.append(self._len)
            self._owners.append(owner)
            self._spans.append(span)
        self._parts.append(text)
        self._len += len(text)
        if owner is not None:
            first, _ = self._first_last.get(owner, (self._len - len(text), 0))
            self._first_last[owner] = (first, self._len)

    def _merge_into_last(self, owner: int | None, span: TextSpan | None, n: int) -> bool:
        """Adjacent intervals collapse when they say the same thing.

        Two synthetic runs are one synthetic run. Two owned runs of one block collapse only when
        the second continues the first in `block.text` -- so a JOIN seam stays two intervals
        (03:2839-2841: "a RenderSpan across the seam lifts to two blocks, which is correct,
        because it is two blocks"), and so does a mark boundary that split a block's own text.

        **A substitution interval never merges, in either direction.** `&` rendered `&amp;` is one
        source character in five view characters, and folding it into a length-preserving
        neighbour would leave an interval whose view length and text length disagree for a reason
        `to_text` cannot recover -- which is precisely the class of bug D3 in
        `_notes/s10-fix-ledger.md` was: two integer pairs in different coordinate spaces, and
        nothing in the types able to see it.
        """
        if not self._starts:
            return False
        last_owner, last_span = self._owners[-1], self._spans[-1]
        if owner is None and last_owner is None:
            return True
        if owner is None or last_owner != owner or last_span is None or span is None:
            return False
        if last_span.b != span.a or n != span.b - span.a:
            return False
        if self._len - self._starts[-1] != last_span.b - last_span.a:
            return False
        self._spans[-1] = TextSpan(last_span.a, span.b)
        return True

    def synthetic(self, text: str) -> None:
        """Append text no block owns: a heading marker, a tag, a pipe, a separator."""
        self._write(text, None, 0, _NO_ESCAPE)

    def owned(
        self,
        text: str,
        owner: int,
        ts_base: int,
        *,
        escape: Mapping[str, str] = _NO_ESCAPE,
    ) -> None:
        """Append `text`, which is `block.text[ts_base : ts_base + len(text)]` of `owner`.

        `escape` maps a source character to what the format writes instead. Such a character
        becomes its OWN interval, so the map never claims a length-preserving correspondence it
        does not have, and everything between two escaped characters stays one interval.
        """
        self._write(text, owner, ts_base, escape)

    def _write(self, text: str, owner: int | None, ts_base: int, escape: Mapping[str, str]) -> None:
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            sub = escape.get(ch)
            if sub is not None:
                self._flush_prefix()
                self._put(sub, owner, _span(owner, ts_base + i, ts_base + i + 1))
                i += 1
            elif ch == "\n":
                self._put("\n", owner, _span(owner, ts_base + i, ts_base + i + 1))
                self._pending = True
                i += 1
            else:
                j = i
                while j < n and text[j] != "\n" and text[j] not in escape:
                    j += 1
                self._flush_prefix()
                self._put(text[i:j], owner, _span(owner, ts_base + i, ts_base + j))
                i = j

    def touch(self, owner: int) -> None:
        """Record where a block was visited, so a block that renders nothing still has a span."""
        if owner not in self._first_last and owner not in self._placeholders:
            self._placeholders[owner] = self._len

    def finish(self) -> tuple[str, ArraySpanMap]:
        view = "".join(self._parts)
        for owner, pos in self._placeholders.items():
            self._first_last.setdefault(owner, (pos, pos))
        return view, ArraySpanMap(
            view_id=self._view_id,
            view_len=len(view),
            starts=tuple(self._starts),
            owners=tuple(self._owners),
            text_spans=tuple(self._spans),
            first_last=MappingProxyType(dict(self._first_last)),
        )


def _span(owner: int | None, a: int, b: int) -> TextSpan | None:
    return None if owner is None else TextSpan(a, b)


# ---------------------------------------------------------------------------
# 4. The per-format token tables. Nothing below invents a rule the plan states.
# ---------------------------------------------------------------------------

#: 03:2873-2880's block separator column, verbatim. `html` has none, "block elements".
_SEPARATOR: Final[Mapping[str, str]] = MappingProxyType(
    {"md": "\n\n", "gfm": "\n\n", "html": "", "text": "\n\n", "otsl": "\n"}
)

#: HTML must escape the three characters that would otherwise be markup. P5 asserts a block's
#: `text` never contains `<`-delimited markup, but `&` and a bare `<` are still legal text and an
#: unescaped one changes what a browser renders.
_HTML_ESCAPE: Final[Mapping[str, str]] = MappingProxyType({"&": "&amp;", "<": "&lt;", ">": "&gt;"})

#: The markdown pipe-table cell escape. A `|` inside a cell ends the cell, and a newline ends the
#: row, so both are substituted -- `md` joins a cell's lines with a space and `gfm` with `<br>`,
#: which is the one difference 03:2876 states between the two.
_MD_CELL_ESCAPE: Final[Mapping[str, str]] = MappingProxyType({"|": "\\|", "\n": " "})
_GFM_CELL_ESCAPE: Final[Mapping[str, str]] = MappingProxyType({"|": "\\|", "\n": "<br>"})
#: `text` is "rows joined by tab" (03:2878), so a tab inside a cell would forge a column.
_TEXT_CELL_ESCAPE: Final[Mapping[str, str]] = MappingProxyType({"\t": " ", "\n": " "})
_HTML_CELL_ESCAPE: Final[Mapping[str, str]] = _HTML_ESCAPE
#: OTSL is a token stream over `\n`-terminated rows, so a cell's own newline must not end a row.
_OTSL_CELL_ESCAPE: Final[Mapping[str, str]] = MappingProxyType({"\n": " "})

_CELL_ESCAPE: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        "md": _MD_CELL_ESCAPE,
        "gfm": _GFM_CELL_ESCAPE,
        "html": _HTML_CELL_ESCAPE,
        "text": _TEXT_CELL_ESCAPE,
        "otsl": _OTSL_CELL_ESCAPE,
    }
)

#: The markdown open/close pair for a kind whose markdown syntax is not a function of its payload.
#: A kind absent from this table renders as its own text with no tokens, which is what "lossy in:
#: spans, layout tables unwrapped" (03:2874) leaves markdown responsible for and no more.
_MD_TAGS: Final[Mapping[Kind, tuple[str, str]]] = MappingProxyType(
    {
        Kind.TITLE: ("# ", ""),
        Kind.RULE: ("---", ""),
        Kind.FORMULA: ("$$\n", "\n$$"),
        Kind.CAPTION: ("*", "*"),
        Kind.TOC_ENTRY: ("- ", ""),
        Kind.REFERENCE: ("- ", ""),
    }
)

#: The HTML element per kind. 03:2877 fixes only "block elements" and the table's `rowspan` /
#: `colspan`, so the choice of element is this module's; every one is the semantic HTML element
#: for that kind, and a kind with no obvious element gets `<div>` rather than an invented tag.
_HTML_TAGS: Final[Mapping[Kind, tuple[str, str]]] = MappingProxyType(
    {
        Kind.DOCUMENT: ("<article>", "</article>"),
        Kind.SECTION: ("<section>", "</section>"),
        Kind.TITLE: ("<h1>", "</h1>"),
        Kind.PARAGRAPH: ("<p>", "</p>"),
        Kind.LIST_ITEM: ("<li>", "</li>"),
        Kind.BLOCKQUOTE: ("<blockquote>", "</blockquote>"),
        Kind.CODE: ("<pre><code>", "</code></pre>"),
        Kind.FIGURE: ("<figure>", "</figure>"),
        Kind.PICTURE: ("<img>", ""),  # a void element, so no close tag
        Kind.CAPTION: ("<figcaption>", "</figcaption>"),
        Kind.FORMULA: ('<div class="formula">', "</div>"),
        Kind.RULE: ("<hr>", ""),
        Kind.PAGE_HEADER: ("<header>", "</header>"),
        Kind.PAGE_FOOTER: ("<footer>", "</footer>"),
        Kind.FOOTNOTE: ('<aside class="footnote">', "</aside>"),
        Kind.ENDNOTE: ('<aside class="endnote">', "</aside>"),
        Kind.SPEAKER_NOTE: ('<aside class="speaker-note">', "</aside>"),
        Kind.COMMENT: ('<aside class="comment">', "</aside>"),
        Kind.FORM: ("<form>", "</form>"),
        Kind.TOC: ('<nav class="toc">', "</nav>"),
        Kind.TOC_ENTRY: ("<li>", "</li>"),
        Kind.BIBLIOGRAPHY: ('<section class="bibliography">', "</section>"),
        Kind.REFERENCE: ("<li>", "</li>"),
    }
)
_HTML_DEFAULT: Final[tuple[str, str]] = ("<div>", "</div>")

#: Inline mark tokens. 03:353-363's release-1 vocabulary; a kind absent from a format's table has
#: no syntax in that format and contributes no token -- which is not "dropping a mark" (P31): the
#: run is still SPLIT at the mark's boundaries, so no character moves and no character is lost.
#: `text` and `otsl` are "lossy in: all structure" (03:2878) and have no inline syntax at all.
_MD_MARKS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "bold": ("**", "**"),
        "italic": ("*", "*"),
        "strike": ("~~", "~~"),
        "code": ("`", "`"),
        "underline": ("<u>", "</u>"),
        "sub": ("<sub>", "</sub>"),
        "sup": ("<sup>", "</sup>"),
        "math": ("$", "$"),
    }
)
_HTML_MARKS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "bold": ("<strong>", "</strong>"),
        "italic": ("<em>", "</em>"),
        "strike": ("<s>", "</s>"),
        "code": ("<code>", "</code>"),
        "underline": ("<u>", "</u>"),
        "sub": ("<sub>", "</sub>"),
        "sup": ("<sup>", "</sup>"),
        "math": ('<span class="math">', "</span>"),
        "redaction": ('<span class="redaction">', "</span>"),
    }
)
_MARKS_BY_FMT: Final[Mapping[str, Mapping[str, tuple[str, str]]]] = MappingProxyType(
    {
        "md": _MD_MARKS,
        "gfm": _MD_MARKS,
        "html": _HTML_MARKS,
        "text": _NO_ESCAPE,
        "otsl": _NO_ESCAPE,
    }
)

#: The OTSL cell-token vocabulary. **The plan names OTSL and never defines its tokens**: 03:2879
#: calls a table "an OTSL cell-token sequence" and 03:2039 calls it "the lossless table
#: serialization for a model context", while `_notes/mine-parse.md:322` identifies it as docling's
#: `Table.otsl_seq` -- "OTSL (Optimized Table Structure Language)". So the vocabulary is docling's
#: published one, not one invented here: `fcel` a filled cell, `ecel` an empty cell, `lcel` a
#: left-looking span continuation, `ucel` an up-looking one, `xcel` a cross (both) continuation,
#: `ched` a column-header cell, `rhed` a row-header cell, and `nl` end of row. `srow`, docling's
#: section row, is deliberately not emitted: `owdoc` has no full-width section-row concept on a
#: table, and emitting a token the model cannot mean would be a lossy claim in a format whose
#: whole point is that it is lossless. Reported.
_OTSL_FCEL: Final = "<fcel>"
_OTSL_ECEL: Final = "<ecel>"
_OTSL_LCEL: Final = "<lcel>"
_OTSL_UCEL: Final = "<ucel>"
_OTSL_XCEL: Final = "<xcel>"
_OTSL_CHED: Final = "<ched>"
_OTSL_RHED: Final = "<rhed>"
_OTSL_NL: Final = "<nl>"


# ---------------------------------------------------------------------------
# 5. Step 1, RESOLVE: the layer filter and the containment forest.
# ---------------------------------------------------------------------------


def _resolve(scope: ViewScope, layers: frozenset[Layer]) -> tuple[Block, ...]:
    """Step 1 (03:2826-2828): restrict to `state = 0` and `layer in layers`.

    Both are per-block predicates, and the layer one is a predicate rather than an ancestor walk
    only because layer is INHERITED (M-INV-5, 03:1025-1033). That is the whole argument the plan
    makes for `Layer` being a column: without inheritance this filter would have to decide what to
    do with a `body` paragraph inside an `annotation` comment, and there is no right answer.
    """
    return tuple(b for b in scope.blocks if not b.tombstoned and b.layer in layers)


def _forest(blocks: Sequence[Block]) -> tuple[Mapping[int, tuple[Block, ...]], tuple[Block, ...]]:
    """The containment spine of the resolved set, as `(children, roots)`.

    A block whose `parent` is not in the resolved set is a root. That is not a fallback: because
    layer is inherited, the filter can only remove whole subtrees plus the page roots above them,
    so an orphan is a subtree whose parent left the view and rendering it at top level is exactly
    what `layers={NOTE}` means.

    Children are ordered by `(ord, block_id)` -- `ord` IS reading order (03:239) and the id breaks
    a tie that P3 says cannot happen, so the order never depends on dict or set iteration.
    Roots keep the scope's resolved order, which is what `ViewScope` carries (03:2815).
    """
    present = {int(b.id) for b in blocks}
    kids: dict[int, list[Block]] = {}
    roots: list[Block] = []
    for b in blocks:
        if b.parent is not None and int(b.parent) in present:
            kids.setdefault(int(b.parent), []).append(b)
        else:
            roots.append(b)
    ordered = {
        parent: tuple(sorted(group, key=lambda c: (c.ord, int(c.id))))
        for parent, group in kids.items()
    }
    return MappingProxyType(ordered), tuple(roots)


# ---------------------------------------------------------------------------
# 6. Run-splitting for marks. 03:2846-2852.
# ---------------------------------------------------------------------------


class _Step(NamedTuple):
    """One boundary of the run-split walk: what closes, what opens, and the run that follows."""

    closes: tuple[int, ...]
    zeros: tuple[int, ...]
    opens: tuple[int, ...]
    a: int
    b: int


def _usable_marks(block: Block) -> tuple[Mark, ...]:
    """The block's marks in `(a, b, kind)` order -- the order they are stored in (03:383).

    A mark outside `[0, len(text)]` is skipped rather than clamped: P9 asserts every stored mark is
    in range, so an out-of-range one is a store the conformance suite already failed, and clamping
    would render a token over characters the driver never marked.
    """
    n = len(block.text or "")
    fit = [m for m in block.marks if 0 <= m.a <= m.b <= n]
    return tuple(sorted(fit, key=lambda m: (m.a, m.b, m.kind)))


def _boundaries(marks: Sequence[Mark], n: int) -> tuple[int, ...]:
    """`0 = b0 < b1 < ... < bn = len(text)`, every mark endpoint included (03:2846-2847)."""
    points = {0, n}
    for m in marks:
        points.add(m.a)
        points.add(m.b)
    return tuple(sorted(points))


def _renest(
    stack: tuple[int, ...], active: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """`(closes, opens, new_stack)` at one boundary.

    03:2848 says "close the format tokens for marks that ended (in reverse open order) and open
    those that began". With arbitrarily overlapping marks that is not sufficient on its own: if the
    mark that ended is *below* one that continues, closing only it would cross the tags. So
    everything above the lowest ended mark closes with it and reopens, which is the "well-nested
    render by splitting runs" the same paragraph promises and is why `**bold *both* **` can come
    out as two nested runs with no mark dropped.
    """
    live = set(active)
    cut = len(stack)
    for i, j in enumerate(stack):
        if j not in live:
            cut = i
            break
    kept = stack[:cut]
    closes = tuple(reversed(stack[cut:]))
    opens = tuple(j for j in active if j not in kept)
    return closes, opens, kept + opens


def _plan_runs(marks: Sequence[Mark], n: int) -> tuple[_Step, ...]:
    """The whole boundary walk, as a tuple of steps. `O(m log m)` for `m` marks (03:2851)."""
    bounds = _boundaries(marks, n)
    stack: tuple[int, ...] = ()
    steps: list[_Step] = []
    for i, pos in enumerate(bounds):
        nxt = bounds[i + 1] if i + 1 < len(bounds) else None
        active = (
            ()
            if nxt is None
            else tuple(j for j, m in enumerate(marks) if m.a <= pos and m.b >= nxt and m.a < m.b)
        )
        closes, opens, stack = _renest(stack, active)
        zeros = tuple(j for j, m in enumerate(marks) if m.a == m.b == pos)
        steps.append(_Step(closes, zeros, opens, pos, nxt if nxt is not None else pos))
    return tuple(steps)


def _mark_tokens(fmt: str, mark: Mark) -> tuple[str, str]:
    """The open/close pair one mark contributes in one format. Both are SYNTHETIC.

    `link`, `anchor` and `note_ref` read their `value`, which is why they are not table rows: the
    token depends on the mark's payload (03:357-360). A malformed `value` yields no token rather
    than an exception -- a serializer is a read path, and a mark whose value a driver wrote badly
    must not make a document unreadable.
    """
    table = _MARKS_BY_FMT[fmt]
    if mark.kind in table:
        return table[mark.kind]
    if fmt not in ("md", "gfm", "html"):
        return ("", "")
    value = mark.value if isinstance(mark.value, Mapping) else _EMPTY_MAP
    return _value_mark_tokens(fmt, mark.kind, value)


def _value_mark_tokens(fmt: str, kind: str, value: Mapping[str, Any]) -> tuple[str, str]:
    """The four marks whose token is a function of the mark's own `value` (03:357-360).

    One assignment per arm and one return, because the arms are a table and a linter counting
    returns is right that eight of them is a table written as control flow.
    """
    if kind == "link":
        target = str(value.get("target", ""))
        pair = (f'<a href="{_attr(target)}">', "</a>") if fmt == "html" else ("[", f"]({target})")
    elif kind == "note_ref":
        label = str(value.get("label", ""))
        pair = (
            (f'<sup class="note-ref">{label}', "</sup>") if fmt == "html" else (f"[^{label}]", "")
        )
    elif fmt != "html":
        pair = ("", "")
    elif kind == "anchor":
        pair = (f'<a id="{_attr(str(value.get("name", "")))}">', "</a>")
    elif kind == "lang":
        pair = (f'<span lang="{_attr(str(value.get("bcp47", "")))}">', "</span>")
    else:
        pair = ("", "")
    return pair


def _attr(value: str) -> str:
    """Minimal HTML attribute escaping. An attribute is synthetic text, so it carries no span."""
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


# ---------------------------------------------------------------------------
# 7. The cover map. Step 3's table branch, without a `Grid`.
# ---------------------------------------------------------------------------


class _Grid(NamedTuple):
    """The materialised cover map of one table, for the duration of one render.

    `origin[(r, c)]` is the cell block whose content lives at that position; `cover[(r, c)]` is the
    origin coordinate a covered position points back at. That is 03:1900-1904's exactly-once
    invariant, and it is built here rather than read off a `Grid` for the reason the module
    docstring gives. `MAX_EXPANSION` is charged against the spanned area, "equal to
    `MAX_GRID_SLOTS` and asserted equal, so a table cannot build and then fail to store"
    (03:2620) -- checked before the map is materialised, not after.
    """

    n_rows: int
    n_cols: int
    origin: Mapping[tuple[int, int], Block]
    cover: Mapping[tuple[int, int], tuple[int, int]]


def _cover_map(cells: Sequence[Block], positions: Mapping[BlockId, CellPos]) -> _Grid:
    origin: dict[tuple[int, int], Block] = {}
    cover: dict[tuple[int, int], tuple[int, int]] = {}
    n_rows = n_cols = charged = 0
    for index, cell in enumerate(cells):
        # A driver that emitted no `cell` row for a cell still has a reading order, so the fallback
        # is one cell per row in `ord` order rather than a refusal: `tables = "flat_html"` is a
        # declared capability rung (03:490) and a flat table has no (r, c).
        pos = positions.get(cell.id) or CellPos(r=index, c=0)
        charged += max(1, pos.row_span) * max(1, pos.col_span)
        if charged > MAX_EXPANSION:
            msg = f"this table charges {charged} span slots, past MAX_EXPANSION={MAX_EXPANSION}"
            raise ResourceLimit(
                msg, limit="MAX_EXPANSION", fix="ow doc verify <cite>  # find the clamped table"
            )
        if (pos.r, pos.c) in origin or (pos.r, pos.c) in cover:
            continue  # an overlap is CLAMPED, first writer wins; `build_grid` records the Diag.
        origin[(pos.r, pos.c)] = cell
        for dr in range(max(1, pos.row_span)):
            for dc in range(max(1, pos.col_span)):
                key = (pos.r + dr, pos.c + dc)
                if key != (pos.r, pos.c) and key not in origin and key not in cover:
                    cover[key] = (pos.r, pos.c)
        n_rows = max(n_rows, pos.r + max(1, pos.row_span))
        n_cols = max(n_cols, pos.c + max(1, pos.col_span))
    return _Grid(n_rows, n_cols, MappingProxyType(origin), MappingProxyType(cover))


# ---------------------------------------------------------------------------
# 8. The emitter -- step 3's "in this order and no other", step 4's JOIN, step 5's CONTEXT.
# ---------------------------------------------------------------------------


class _Emitter:
    """One render of one scope in one format.

    Every method here is step 3 of 03:2830-2838 in the order the plan prints it: OPEN token, the
    block's OWN `text` run-split by its marks, each child recursively in `ord` order, CLOSE token,
    then the separator unless the next block is joined. **A block renders its own text and then its
    children**, which is where M-INV-4 earns its place (03:2845): there is no de-duplication pass
    and there will not be one, so a `list_item` whose `text` is copied into a child `paragraph`
    renders the sentence twice and the model forbids the duplication instead.
    """

    __slots__ = ("children", "contextualize", "fmt", "scope", "sep", "view")

    def __init__(
        self,
        *,
        fmt: str,
        scope: ViewScope,
        view: _View,
        children: Mapping[int, tuple[Block, ...]],
        contextualize: bool,
    ) -> None:
        self.fmt = fmt
        self.scope = scope
        self.view = view
        self.children = children
        self.contextualize = contextualize
        self.sep = _SEPARATOR[fmt]

    # -- sequences, JOIN and UNWRAP --------------------------------------

    def kids(self, b: Block) -> tuple[Block, ...]:
        return self.children.get(int(b.id), ())

    def unwrap(self, nodes: Sequence[Block]) -> tuple[Block, ...]:
        """Step 2 (03:2828-2830): a layout table becomes its cells in row-major origin order.

        "The model never unwraps; only this step does." A layout table is a positioning scaffold --
        DOCX text placement, an HTML layout table -- and rendering it as a data table is pure noise
        in a chunk (03:2044). `otsl` is exempt because a table-only serialization has nothing else
        to say about a table.
        """
        out: list[Block] = []
        for node in nodes:
            if node.kind is Kind.TABLE and not self.as_table(node):
                out.extend(self.row_major(node))
            else:
                out.append(node)
        return tuple(out)

    def as_table(self, b: Block) -> bool:
        return self.fmt == "otsl" or self.scope.table(b.id).kind is not TableKind.LAYOUT

    def row_major(self, table: Block) -> tuple[Block, ...]:
        """A table's cells in row-major origin order. A cell with no `cell` row sorts last, by
        `ord`, so the order is total and never depends on dict iteration."""
        cells = self.kids(table)
        return tuple(
            sorted(
                cells,
                key=lambda c: (
                    (0, self.scope.cells[c.id].r, self.scope.cells[c.id].c, c.ord)
                    if c.id in self.scope.cells
                    else (1, 0, 0, c.ord)
                ),
            )
        )

    def emit_sequence(self, nodes: Sequence[Block], *, top: bool = False) -> None:
        """Steps 3e and 4: the separator between siblings, suppressed across a `continues` seam."""
        items = self.unwrap(nodes)
        for i, node in enumerate(items):
            joined_prev = i > 0 and self.scope.continues.get(items[i - 1].id) == node.id
            joined_next = (
                i + 1 < len(items) and self.scope.continues.get(node.id) == items[i + 1].id
            )
            if i > 0 and not joined_prev:
                self.view.synthetic(self.sep)
            if top:
                self.emit_context(node)
            self.emit_block(node, open_token=not joined_prev, close_token=not joined_next)

    def emit_context(self, node: Block) -> None:
        """Step 5 (03:2842): prefix each top-level unit with its `heading_path`, as SYNTHETIC.

        Synthetic is not a detail -- the heading path is text this block never said, so a quote
        taken across it is not that block's words, which is the whole reason `is_synthetic` exists.
        """
        if not self.contextualize:
            return
        path = self.scope.heading_paths.get(node.id, ())
        if path:
            self.view.synthetic(" > ".join(path) + "\n")

    # -- one block --------------------------------------------------------

    def emit_block(self, b: Block, *, open_token: bool = True, close_token: bool = True) -> None:
        if b.kind is Kind.TABLE and self.as_table(b):
            self.view.touch(int(b.id))
            self.emit_table(b)
            return
        opening, closing = self.tokens(b)
        prefix = self.line_prefix(b)
        if open_token:
            self.view.synthetic(opening)
        if prefix:
            self.view.push_prefix(prefix)
        self.view.touch(int(b.id))
        self.emit_text(b, self.body_escape())
        kids = self.kids(b)
        if kids:
            if b.text:
                self.view.synthetic(self.sep)
            self.emit_sequence(kids)
        if prefix:
            self.view.pop_prefix()
        if close_token:
            self.view.synthetic(closing)

    def tokens(self, b: Block) -> tuple[str, str]:
        if self.fmt == "html":
            return self.html_tokens(b)
        if self.fmt in ("md", "gfm"):
            return self.md_tokens(b)
        return ("", "")  # `text` and `otsl` emit non-table blocks as bare lines (03:2878, :2881).

    def html_tokens(self, b: Block) -> tuple[str, str]:
        if b.kind is Kind.HEADING:
            level = self.heading_level(b)
            return (f"<h{level}>", f"</h{level}>")
        if b.kind is Kind.LIST:
            return ("<ol>", "</ol>") if self.ordered(b) else ("<ul>", "</ul>")
        return _HTML_TAGS.get(b.kind, _HTML_DEFAULT)

    def md_tokens(self, b: Block) -> tuple[str, str]:
        if b.kind is Kind.HEADING:
            return ("#" * self.heading_level(b) + " ", "")
        if b.kind is Kind.CODE:
            lang = str(self.scope.payload(b.id).get("lang", "") or "")
            return (f"```{lang}\n", "\n```")
        if b.kind is Kind.LIST_ITEM:
            return (self.list_marker(b), "")
        return _MD_TAGS.get(b.kind, ("", ""))

    def line_prefix(self, b: Block) -> str:
        """`md`'s two per-line prefixes: `> ` for a blockquote and a list item's continuation
        indent. 03:2832 names the blockquote one explicitly ("`> ` per line for blockquote")."""
        if self.fmt not in ("md", "gfm"):
            return ""
        if b.kind is Kind.BLOCKQUOTE:
            return "> "
        if b.kind is Kind.LIST_ITEM:
            return " " * len(self.list_marker(b))
        return ""

    def list_marker(self, item: Block) -> str:
        """`1. ` inside an ordered list, `- ` otherwise. The number is the item's position among
        its parent's `list_item` children plus `payload.start`, so it is a function of the spine
        and not of a counter carried across the walk."""
        parent = item.parent
        if parent is None or not self.ordered_parent(parent):
            return "- "
        siblings = [c for c in self.children.get(int(parent), ()) if c.kind is Kind.LIST_ITEM]
        index = siblings.index(item) if item in siblings else 0
        start = self.scope.payload(parent).get("start", 1)
        base = start if isinstance(start, int) and not isinstance(start, bool) else 1
        return f"{base + index}. "

    def ordered_parent(self, parent: BlockId) -> bool:
        return bool(self.scope.payload(parent).get("ordered", False))

    def ordered(self, b: Block) -> bool:
        return bool(self.scope.payload(b.id).get("ordered", False))

    def heading_level(self, b: Block) -> int:
        """`payload.level` is 1-based (03:819), clamped to the six levels both markdown and HTML
        have. A `title` has no level at all, which is why it is a separate kind (03:818)."""
        raw = self.scope.payload(b.id).get("level", 1)
        level = raw if isinstance(raw, int) and not isinstance(raw, bool) else 1
        return max(1, min(_HEADING_MAX, level))

    def body_escape(self) -> Mapping[str, str]:
        return _HTML_ESCAPE if self.fmt == "html" else _NO_ESCAPE

    # -- step 3b: the block's own text, run-split by its marks ------------

    def emit_text(self, b: Block, escape: Mapping[str, str]) -> None:
        text = b.text
        if not text:
            return
        owner = int(b.id)
        marks = _usable_marks(b)
        if not marks:
            self.view.owned(text, owner, 0, escape=escape)
            return
        for step in _plan_runs(marks, len(text)):
            for j in step.closes:
                self.view.synthetic(_mark_tokens(self.fmt, marks[j])[1])
            for j in step.zeros:
                opening, closing = _mark_tokens(self.fmt, marks[j])
                self.view.synthetic(opening + closing)
            for j in step.opens:
                self.view.synthetic(_mark_tokens(self.fmt, marks[j])[0])
            if step.b > step.a:
                self.view.owned(text[step.a : step.b], owner, step.a, escape=escape)

    # -- step 3's table branch -------------------------------------------

    def emit_table(self, b: Block) -> None:
        facts = self.scope.table(b.id)
        grid = _cover_map(self.row_major(b), self.scope.cells)
        if self.fmt == "html":
            self.html_table(grid, facts)
        elif self.fmt == "otsl":
            self.otsl_table(grid, facts)
        elif self.fmt == "text":
            self.text_table(grid)
        else:
            self.pipe_table(grid, facts)

    def cell_content(self, cell: Block) -> None:
        """A cell's own text plus its descendants', on one line.

        A cell IS an ordinary Block (03:826) and may carry a subtree, but every one of the five
        formats puts a cell on one line, so the descendants are joined by the format's cell join
        and every newline inside a cell is substituted -- as its own interval, so the map never
        claims a correspondence it does not have.
        """
        escape = _CELL_ESCAPE[self.fmt]
        first = True
        for node in self.descend(cell):
            self.view.touch(int(node.id))
            if not node.text:
                continue
            if not first:
                self.view.synthetic(" " if self.fmt != "gfm" else "<br>")
            self.emit_text(node, escape)
            first = False

    def descend(self, b: Block) -> Iterator[Block]:
        yield b
        for child in self.kids(b):
            yield from self.descend(child)

    def pipe_table(self, grid: _Grid, facts: TableFacts) -> None:
        """`md` and `gfm`: a pipe table with spans flattened (03:2874-2876).

        A covered position renders as a blank cell -- "GFM has no span syntax" (03:2035) -- and the
        delimiter row is synthetic. 03:2876 states the synthetic-header rule under `gfm`; `md`
        follows it because a pipe table with no delimiter row is not a table in any markdown
        renderer, and 03:2874 asks md for "pipe table" without qualification. The one difference
        kept between the two is the cell line join: a space for `md`, `<br>` for `gfm`.
        """
        header_rows = max(0, facts.header_rows)
        if header_rows == 0 and grid.n_rows:
            self.view.synthetic("|" + "  |" * grid.n_cols + "\n")
            self.view.synthetic(self.delimiter_row(grid.n_cols))
        for r in range(grid.n_rows):
            if r:
                self.view.synthetic("\n")
            self.view.synthetic("|")
            for c in range(grid.n_cols):
                self.view.synthetic(" ")
                cell = grid.origin.get((r, c))
                if cell is not None:
                    self.cell_content(cell)
                self.view.synthetic(" |")
            if header_rows and r == header_rows - 1:
                self.view.synthetic("\n" + self.delimiter_row(grid.n_cols).rstrip("\n"))

    def delimiter_row(self, n_cols: int) -> str:
        return "|" + " --- |" * n_cols + "\n"

    def html_table(self, grid: _Grid, facts: TableFacts) -> None:
        """`html`: `rowspan` / `colspan` preserved (03:2877). Covered positions emit nothing."""
        self.view.synthetic("<table>")
        for r in range(grid.n_rows):
            self.view.synthetic("<tr>")
            for c in range(grid.n_cols):
                cell = grid.origin.get((r, c))
                if cell is None:
                    continue
                tag = "th" if r < facts.header_rows or c < facts.header_cols else "td"
                self.view.synthetic("<" + tag + self.span_attrs(cell) + ">")
                self.cell_content(cell)
                self.view.synthetic(f"</{tag}>")
            self.view.synthetic("</tr>")
        self.view.synthetic("</table>")

    def span_attrs(self, cell: Block) -> str:
        pos = self.scope.cells.get(cell.id)
        if pos is None:
            return ""
        out = ""
        if pos.row_span > 1:
            out += f' rowspan="{pos.row_span}"'
        if pos.col_span > 1:
            out += f' colspan="{pos.col_span}"'
        return out

    def text_table(self, grid: _Grid) -> None:
        """`text`: cells joined by tab, rows by newline.

        03:2878 reads "rows joined by tab, cells by newline", which is the two nouns in each
        other's slots: the row is what a tab joins and the newline is what ends it. TSV is also
        what "for BM25 fixtures, diffing, plain export" needs, and a table whose rows were joined
        by tabs into one line would put every cell of a 40-row table on one BM25 line. Reported as
        a plan defect; this is the reading implemented.
        """
        for r in range(grid.n_rows):
            if r:
                self.view.synthetic("\n")
            for c in range(grid.n_cols):
                if c:
                    self.view.synthetic("\t")
                cell = grid.origin.get((r, c))
                if cell is not None:
                    self.cell_content(cell)

    def otsl_table(self, grid: _Grid, facts: TableFacts) -> None:
        """`otsl`: the lossless one -- spans and headers preserved, "nothing" lost (03:2879)."""
        for r in range(grid.n_rows):
            for c in range(grid.n_cols):
                cell = grid.origin.get((r, c))
                if cell is not None:
                    self.view.synthetic(self.otsl_open(cell, r, c, facts))
                    self.cell_content(cell)
                else:
                    self.view.synthetic(self.otsl_cover(grid, r, c))
            self.view.synthetic(_OTSL_NL)

    def otsl_open(self, cell: Block, r: int, c: int, facts: TableFacts) -> str:
        if not cell.text and not self.kids(cell):
            return _OTSL_ECEL
        if r < facts.header_rows:
            return _OTSL_CHED
        if c < facts.header_cols:
            return _OTSL_RHED
        return _OTSL_FCEL

    def otsl_cover(self, grid: _Grid, r: int, c: int) -> str:
        """A covered position names WHICH way it is covered, which is what makes OTSL lossless."""
        at = grid.cover.get((r, c))
        if at is None:
            return _OTSL_ECEL
        origin_r, origin_c = at
        if origin_r < r and origin_c < c:
            return _OTSL_XCEL
        if origin_r < r:
            return _OTSL_UCEL
        return _OTSL_LCEL


# ---------------------------------------------------------------------------
# 9. `view_id`, and the one public function.
# ---------------------------------------------------------------------------


def _view_id(scope: ViewScope, fmt: str, *, layers: frozenset[Layer], contextualize: bool) -> str:
    """`"<fmt>/<serializer_version>/<options_digest[:4]>"` -- 03:2887-2889.

    `options_digest` is `sha256_canonical` over "(layers sorted, contextualize, scope kind and its
    resolved block ids' digest, gen)", which is that list exactly. The corpus is deliberately not
    in it: the plan's list omits it, and a view id is a projection identity rather than a global
    address -- `manifest.views[]` pins the bytes with a sha256 and a byte length (03:2892).

    The block ids go in as their own digest rather than inline, so the option digest is a fixed
    cost for a 600k-block scope.
    """
    digest = sha256_canonical(
        {
            "layers": sorted(str(layer) for layer in layers),
            "contextualize": bool(contextualize),
            "scope_kind": scope.kind,
            "blocks": sha256_canonical([int(b.id) for b in scope.blocks]),
            "gen": int(scope.gen),
        }
    )
    return f"{fmt}/{SERIALIZER_VERSION}/{digest[:4]}"


def _check_fmt(fmt: object) -> str:
    if not isinstance(fmt, str) or fmt not in SERIALIZER_CAPS:
        msg = f"fmt must be one of {FORMATS}, not {fmt!r}"
        raise UsageError(msg, symbol="OW_USAGE", fix=f"ow open <cite> --format {FORMATS[0]}")
    if not SERIALIZER_CAPS[fmt]:
        # 03:2866 and 18:393: the refusal names the SERIALIZER, never a driver, because a parse
        # driver never calls this function and could not have written or tested such a claim. At
        # release 1 no format has a `False` entry, so this branch is a live guard for the day one
        # does rather than a dead one.
        msg = (
            f"serializer {fmt!r} at version {SERIALIZER_VERSION} declares "
            f"SERIALIZER_CAPS[{fmt!r}] is False, so a view in it may never be cited from"
        )
        raise PolicyRefusal(
            msg,
            symbol="OW_SPANMAP_UNAVAILABLE",
            fix=f"ow open <cite> --format {FORMATS[0]}",
        )
    return fmt


def _check_layers(layers: object) -> frozenset[Layer]:
    if not isinstance(layers, frozenset):
        msg = f"layers is a frozenset[Layer] (03:1014), not {type(layers).__name__}"
        raise TypeError(msg)
    if not layers:
        msg = "layers must name at least one Layer; the default is frozenset({Layer.BODY})"
        raise ValueError(msg)
    for layer in layers:
        if not isinstance(layer, Layer):
            msg = f"layers holds Layer members, not {type(layer).__name__} ({layer!r})"
            raise TypeError(msg)
    return layers


def serialize(
    scope: ViewScope,
    fmt: Fmt,
    *,
    layers: frozenset[Layer] = frozenset({Layer.BODY}),
    contextualize: bool = False,
) -> tuple[str, ArraySpanMap]:
    """The one serializer. 03:2809-2811.

    Returns `(view, map)` and **only ever that pair**: there is no sibling that returns the string
    alone (03:2863, 16-roadmap.md:421). The map is the back-map from the rendered view to the
    `Block` that produced each region, and `is_synthetic()` reports the regions this function
    invented -- which is why a quote taken off a serialized view is not automatically verbatim.

    `layers` defaults to `frozenset({Layer.BODY})`; "a caller who wants footnotes inline asks for
    `{BODY, NOTE}` and gets a `SpanMap` covering both" (03:1014-1016).

    `contextualize=True` prefixes each top-level unit with its `heading_path`, recorded synthetic
    (03:2842). The path itself is L3's (03:2904), so it travels on the scope.

    An empty scope returns `("", <empty map>)`. A projection over a page range with no body blocks
    is an empty page, not an error.

    Raises:
        UsageError    -- `fmt` is not one of the five (`OW_USAGE`).
        PolicyRefusal -- `SERIALIZER_CAPS[fmt] is False` (`OW_SPANMAP_UNAVAILABLE`, `OW-A-012`).
        ResourceLimit -- `MAX_VIEW_BYTES`, checked as the view is appended (03:2604); or
                         `MAX_EXPANSION` on a table's charged span area (03:2620).
    """
    chosen = _check_fmt(fmt)
    wanted = _check_layers(layers)
    if not isinstance(scope, ViewScope):
        msg = f"serialize takes a ViewScope (03:2814), not {type(scope).__name__}"
        raise TypeError(msg)
    view = _View(_view_id(scope, chosen, layers=wanted, contextualize=contextualize))
    resolved = _resolve(scope, wanted)
    children, roots = _forest(resolved)
    emitter = _Emitter(
        fmt=chosen,
        scope=scope,
        view=view,
        children=children,
        contextualize=contextualize,
    )
    emitter.emit_sequence(roots, top=True)
    # Every resolved block gets a span, so `offsets_of` is total over the scope. A block the
    # format placed nowhere -- a cell whose position an overlap clamped away -- gets a zero-length
    # span rather than a `KeyError`, and the totality property in `test_model_serialize.py` is
    # what stops that becoming a way to lose a block quietly: it asserts that the concatenation of
    # each block's owned intervals reproduces its `text`, which an unplaced block fails.
    for b in resolved:
        view.touch(int(b.id))
    return view.finish()
