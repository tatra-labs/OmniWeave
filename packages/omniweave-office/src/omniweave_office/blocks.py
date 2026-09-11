"""anydoc's document model, mapped onto `owdoc-fragment/1`.

`driver.py` owns the Port contract, the refusals and the card; this module owns the one thing that
is neither -- the translation between two document models, which is where W3.4's estimation basis
says the work is: *"the decoder is someone else's wheel; the work is mapping anydoc's nine `Block`
variants ..., the exactly-once grid, and the twelve limit constants"* (16-roadmap.md:484).

## The eight variants, and the one thing none of them has

`vendor/anydoc/src/model/block.rs` defines `Block` as **eight** variants -- `Heading`, `Paragraph`,
`List`, `Table`, `BlockQuote`, `CodeBlock`, `Rule`, `Math` -- and **not one of them carries a source
address of any kind**. `Asset` alone carries `origin_part` (`src/model/asset.rs:14-15`). That single
fact decides the card: `origin_span = "none"`, every block `os = {"k": "none"}`, every block
`quote = "normalized"`, and `verbatim` unreachable on the office path at release 1
(03-document-model.md:1561, 05-ingest-and-routing.md:3224-3229). It is not a gap this module can
close by cleverness -- see the note under `_MARK_NOTE_REF` on why re-deriving an address here would
be worse than having none.

(The roadmap cell says "nine" and then lists eight; 03 §18 Q10 already records the miscount and its
resolution -- state the verified number, do not propagate it.)

## Where each variant lands

| anydoc | `Kind` | carried how |
|---|---|---|
| `Heading{level, anchor, content}` | `heading` | `payload.level`; an `anchor` becomes a |
| | | zero-width `anchor` mark at offset 0 |
| `Paragraph{content}` | `paragraph` | text plus marks |
| `List{marker, start, items}` | `list` + `list_item` | `payload.marker`, `payload.start`; |
| | | `ListItem.marker_label` is the item's `label` |
| `Table{grid, header_rows, kind}` | `table` + `table_cell` | `payload.header_rows`, `kind`; |
| | | one cell block per ORIGIN slot |
| `BlockQuote{blocks}` | `blockquote` + children | nesting |
| `CodeBlock{lang, text}` | `code` | `payload.lang`; text verbatim, never re-wrapped |
| `Rule` | `rule` | no text |
| `Math{tex}` | `formula` | `payload = {notation: "latex", src: tex}` |
| `Note{id, kind, blocks}` | `footnote` / `endnote` | `layer = "note"` |
| `Asset{media_type, origin_part, data}` | an `asset` record | plus a `picture` block; the |
| | | `block_asset` role from the media type |

## The exactly-once grid, which is the reason this driver declares `cells_with_spans`

anydoc's `Table.grid` is already canonical: *"every logical grid position appears exactly once.
Content and spans live on the origin slot, and each position a span covers holds a `covered` slot
pointing back at that origin."* 03-document-model.md:1897 adopts that shape by name -- it IS
`CellSlot::Covered { origin_row, origin_col }` -- and calls it *"strictly better than a sparse cell
list with spans because every coordinate is addressable"*.

So this module emits **one `table_cell` block per ORIGIN slot** carrying `cell = {r, c, row_span,
col_span}`, and emits nothing for a covered slot. That is not a loss: `build_grid` registers covered
positions from the origins' spans and 03:1908 says `grid_slot` is written only when `has_merges`, so
re-emitting them would hand the host a second copy of something it derives. Cells arrive in
**row-major origin order**, which is `add_grid`'s asserted precondition (03:1941) and which this
walk satisfies by construction because it iterates the grid in row order.

## Text, and why offsets are computed over normalised runs

A block's `text` is the concatenation of its inline runs, each NFC-normalised *before*
concatenation, and every mark range is a half-open offset pair into that concatenation
(`0 <= a <= b <= len(text)`, 03:373). Normalising per run rather than once at the end is what keeps
the offsets exact: NFC over the whole string can change its length, which would silently shift every
mark computed before it.

The cost is stated rather than hidden: NFC is not closed under concatenation, so a run that *begins*
with a combining mark can leave the joined text one composition short of globally-NFC. OOXML run
splitting can produce that, no consumer can distinguish it from the source's own encoding, and the
alternative -- normalise last, then re-derive every offset -- is a second address space to get
wrong. `quote = "normalized"` is the claim being made either way.

Specified in 16-roadmap.md W3.4; 03-document-model.md §§2.6, 2.7 and 10;
05-ingest-and-routing.md §10.2.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = [
    "ASSET_ROLES",
    "BLOCK_KINDS",
    "NOTE_LAYER",
    "Walk",
    "nfc",
]

NOTE_LAYER: Final = "note"
"""`Layer.NOTE`. A footnote body leaves the body reading order and is never deleted, which is the
whole reason `layer` is a column on `block` rather than a filter applied at parse time (03 §5)."""

BODY_LAYER: Final = "body"

BLOCK_KINDS: Final[dict[str, str]] = {
    "heading": "heading",
    "paragraph": "paragraph",
    "list": "list",
    "table": "table",
    "block_quote": "blockquote",
    "code_block": "code",
    "rule": "rule",
    "math": "formula",
}
"""anydoc's eight `Block.kind` values -> `omniweave_core.model.Kind` members.

Two renames and both are the plan's: `block_quote` -> `blockquote` because `Kind` was renamed off
`QUOTE` (the tier enum owns that word in a framework whose central promise is about quoting, 03:823
and charter §5 X17), and `math` -> `formula` because 05:3224's worked trace says this driver's math
"emits 9 `formula` blocks".

A kind anydoc adds that is not here becomes `unknown` with `raw_kind` set, which is 03 §2.1's
asymmetry seen from the producing side: a DRIVER emitting a kind core does not recognise gets
`unknown` plus a warning, while a READER loading an unrecognised stored kind fails closed."""

ASSET_ROLES: Final[dict[str, str]] = {
    "application/vnd.ms-ole-object": "ole",
}
"""`block_asset.role` for media types that are not plain images. 03:2080's vocabulary is
`image|thumbnail|source_crop|ole|chart_data|bake|font`; everything anydoc retains that is not an
embedded OLE payload is an `image`, which is the default rather than a row here."""

_UNKNOWN_KIND: Final = "unknown"
_QUOTE: Final = "normalized"
_TRUST: Final = "extracted"
_METHOD: Final = "native_xml"
_ORIGIN_NONE: Final[dict[str, str]] = {"k": "none"}
_MARK_NOTE_REF: Final = "note_ref"
_LINK_TARGET_KINDS: Final[dict[str, str]] = {
    "external": "external",
    "anchor": "anchor",
    "relative": "internal",
}
"""anydoc's `LinkTarget.kind` -> the `link` mark's `kind` (03:360, `external|internal|anchor`).

`relative` -> `internal` is the only judgement here. anydoc documents `relative` as a "scheme-less
relative reference, preserved as written", which is a link to another document rather than to a
position inside this one; `internal` is the vocabulary's word for a target inside the corpus and is
the nearest true statement. The target string is preserved exactly as anydoc gives it, so a host
that later disagrees can re-decide from the value rather than from this mapping."""


def nfc(text: str) -> str:
    """NFC, and never `normalize_k`, which casefolds.

    The same one-line function the rest of the framework carries, repeated here because this
    package may import only `omniweave_ports` (`tools/layers.toml`) and `nfc` lives in core. That
    is a real duplication and it is the cheaper of the two available wrongs: the alternative is a
    dependency edge from a driver distribution to core, which INV-2 and layers rule 3 forbid
    outright.
    """
    return unicodedata.normalize("NFC", text)


class Walk:
    """One document's walk: mints `tmp` ids, yields records, and tallies what `achieved` reads.

    A CLASS rather than a generator function because two things outlive any single record -- the
    tmp-id counter and the tallies -- and threading them through a recursive generator as mutable
    arguments is the shape that produces an off-by-one nobody can see.

    The walk is **iterative**, with an explicit stack. anydoc bounds source nesting at
    `max_xml_depth = 256` so recursion would not actually blow Python's limit, but a driver whose
    depth safety depends on a constant in someone else's crate is one upstream patch release away
    from a `RecursionError` that reads as a crash rather than as a refusal.
    """

    __slots__ = (
        "_asset_roles",
        "_counter",
        "_note_refs",
        "_notes",
        "asset_origins",
        "assets",
        "has_marks",
        "has_spans",
        "headings",
        "notations",
        "part",
        "tables",
    )

    def __init__(self, part: str) -> None:
        self.part = part
        self._counter = 0
        self._notes: dict[str, str] = {}
        self._note_refs: set[str] = set()
        self._asset_roles: dict[int, str] = {}
        self.assets = 0
        self.asset_origins = 0
        self.has_marks = False
        self.has_spans = False
        self.headings = 0
        self.notations: set[str] = set()
        self.tables = 0

    # -- ids ---------------------------------------------------------------

    def _tmp(self, prefix: str = "b") -> str:
        """The next `tmp` id. Per-invocation and never durable: no `block_id` crosses this wire.

        03:47 -- the host "mints `block_id`, `addr`, `cite`, `producer_id`, `origin_*` and
        `restriction_bits` itself", and "no `block_id` ever crosses the driver wire, which is what
        makes a fragment portable between stores".
        """
        self._counter += 1
        return f"{prefix}{self._counter}"

    # -- the walk ----------------------------------------------------------

    def records(self, document: Any) -> Iterator[dict[str, Any]]:
        """Every record for one document: assets first, then body blocks, then note bodies.

        **Assets first** because a `picture` block references an asset by its tmp id, and a host
        reading the stream line by line (03:2575) should never meet a forward reference. **Notes
        last** because a `note_ref` mark names the note's tmp, so the reference sites are all known
        by the time the bodies arrive -- which is what lets `achieved.notes` distinguish `linked`
        from `inline` without a second pass over the fragment.
        """
        yield from self._assets(document.assets)
        yield from self._blocks(document.blocks, parent=None, layer=BODY_LAYER)
        yield from self._notes_records(document.notes)

    def _assets(self, assets: Sequence[Any]) -> Iterator[dict[str, Any]]:
        """One `asset` record per retained binary, in `Asset.id` order.

        The bytes do not travel in this record. They travel as `ArtifactRef(kind="asset")` entries
        in `DriverResult.produced`, in this same order, because `ArtifactRef.of()` is the single
        site that meters `max_output_bytes` (04 §6.5) and a record carrying base64 would evade it.
        `sha256` is the driver's CLAIM and the host re-hashes the stream itself -- 03:2130, "the
        digest the driver claims is not the digest we store" -- so it is a cross-check on the
        pairing, not the identity.
        """
        for index, asset in enumerate(assets):
            media_type = str(asset.media_type)
            role = ASSET_ROLES.get(media_type, "image")
            tmp = self._tmp("a")
            self._asset_roles[int(asset.id)] = tmp
            origin_part = str(asset.origin_part)
            self.assets += 1
            if origin_part:
                self.asset_origins += 1
            yield {
                "t": "asset",
                "tmp": tmp,
                "ord": index,
                "media_type": media_type,
                "origin_part": origin_part or None,
                "byte_len": len(asset.data),
                "role": role,
            }

    def _notes_records(self, notes: Sequence[Any]) -> Iterator[dict[str, Any]]:
        """Footnote and endnote bodies, each a container block at `layer = "note"`.

        `Kind.FOOTNOTE` and `Kind.ENDNOTE` are separate members, so anydoc's `Note.kind` maps
        straight through. The body blocks hang under the note block and inherit `layer` -- 03:1030
        makes layer inheritance the reason the filter is "a pure per-block predicate on an indexed
        column" instead of a subtree walk.
        """
        for note in notes:
            note_id = str(note.id)
            kind = str(note.kind)
            tmp = self._notes.get(note_id) or self._tmp()
            self._notes[note_id] = tmp
            yield self._block(
                tmp=tmp,
                parent=None,
                kind=kind if kind in {"footnote", "endnote"} else _UNKNOWN_KIND,
                layer=NOTE_LAYER,
                text="",
                raw_kind=None if kind in {"footnote", "endnote"} else kind,
                payload={"note_id": note_id},
            )
            yield from self._blocks(note.blocks, parent=tmp, layer=NOTE_LAYER)

    def _blocks(
        self, blocks: Sequence[Any], *, parent: str | None, layer: str
    ) -> Iterator[dict[str, Any]]:
        """The iterative walk. A frame is `(block, parent, layer)`; children push in reverse.

        Reverse, because a stack pops last-first and a document's reading order is the one thing a
        `reading_order = "source"` driver may not get wrong.
        """
        stack: list[tuple[Any, str | None, str]] = [
            (block, parent, layer) for block in reversed(blocks)
        ]
        while stack:
            block, block_parent, block_layer = stack.pop()
            kind = str(block.kind)
            tmp = self._tmp()
            children = self._emit(block, kind, tmp, block_parent, block_layer)
            yield from children.records
            stack.extend(reversed(children.pending))

    def _emit(  # noqa: PLR0911 -- one arm per anydoc Block variant; see BLOCK_KINDS.
        self, block: Any, kind: str, tmp: str, parent: str | None, layer: str
    ) -> _Emitted:
        """One anydoc Block -> its records plus the frames its children need.

        Seven returns, one per variant that needs its own shape. The dispatch IS the mapping this
        module exists to be, and collapsing it behind a table of callables would hide the table a
        reader came here to read -- the same argument `omniweave_core.config`'s ten-arm
        `ConfigKind` dispatch already carries in `pyproject.toml`'s per-file ignores.
        """
        mapped = BLOCK_KINDS.get(kind, _UNKNOWN_KIND)
        raw_kind = None if mapped != _UNKNOWN_KIND else kind
        if kind == "table":
            return self._table(block, tmp, parent, layer)
        if kind == "list":
            return self._list(block, tmp, parent, layer)
        if kind == "block_quote":
            return _Emitted(
                [self._block(tmp=tmp, parent=parent, kind="blockquote", layer=layer, text="")],
                [(child, tmp, layer) for child in (block.blocks or ())],
            )
        if kind == "code_block":
            return _Emitted(
                [
                    self._block(
                        tmp=tmp,
                        parent=parent,
                        kind="code",
                        layer=layer,
                        text=nfc(str(block.text or "")),
                        payload={"lang": block.lang} if block.lang else None,
                    )
                ],
                [],
            )
        if kind == "math":
            source = str(block.text or "")
            self.notations.add("latex")
            return _Emitted(
                [
                    self._block(
                        tmp=tmp,
                        parent=parent,
                        kind="formula",
                        layer=layer,
                        text=nfc(source),
                        payload={"notation": "latex", "src": source},
                    )
                ],
                [],
            )
        if kind == "rule":
            return _Emitted(
                [self._block(tmp=tmp, parent=parent, kind="rule", layer=layer, text="")], []
            )
        return self._textual(block, mapped, raw_kind, tmp, parent, layer)

    def _textual(  # noqa: PLR0917 -- six positionals, and they are one frame of the walk.
        self,
        block: Any,
        mapped: str,
        raw_kind: str | None,
        tmp: str,
        parent: str | None,
        layer: str,
    ) -> _Emitted:
        """`heading` and `paragraph`: the two variants whose whole content is inlines.

        A paragraph whose inlines are ALL images emits no paragraph at all -- the pictures take its
        place under its own parent. An empty `paragraph` wrapping one `picture` is a block with no
        text, no address and no meaning, and `is_valid_nonempty()` would still see a block record
        and call the document non-empty.
        """
        run = _Inlines(self).read(block.content or ())
        payload: dict[str, Any] | None = None
        if mapped == "heading":
            self.headings += 1
            payload = {"level": int(block.level) if block.level is not None else None}
            if block.anchor:
                run.marks.insert(0, _anchor_mark(str(block.anchor), "section"))
        if not run.text and mapped == "paragraph":
            return _Emitted(list(self._pictures(run.images, parent)), [])
        records = [
            self._block(
                tmp=tmp,
                parent=parent,
                kind=mapped,
                layer=layer,
                text=run.text,
                marks=run.marks,
                payload=payload,
                raw_kind=raw_kind,
            )
        ]
        records.extend(self._pictures(run.images, tmp))
        records.extend(self._checkboxes(run.checkboxes, tmp))
        return _Emitted(records, [])

    def _pictures(
        self, images: Sequence[tuple[str, int | None, str | None]], parent: str | None
    ) -> Iterator[dict[str, Any]]:
        """An image inline becomes a `picture` BLOCK, because an image is not a mark.

        03 §2.7's mark vocabulary has seven character-formatting kinds plus `link`, `math`,
        `anchor`, `note_ref`, `dehyphenated`, `raw_style`, `lang` and `redaction` -- and no image,
        deliberately, because a mark is a range over text and an image occupies no text. The
        binding to bytes is `block_asset`, whose FK is a block; so the block is what must exist.

        `alt` is the block's `label` rather than its `text`: alt text is a description OF the
        picture, and putting it in `text` would make it quotable as document content.
        """
        for alt, asset_id, external in images:
            links = []
            if asset_id is not None and asset_id in self._asset_roles:
                links.append({"tmp": self._asset_roles[asset_id], "role": "image"})
            payload = {"src": external} if external else None
            yield self._block(
                tmp=self._tmp(),
                parent=parent,
                kind="picture",
                layer=BODY_LAYER,
                text="",
                label=alt or None,
                payload=payload,
                assets=links or None,
            )

    def _checkboxes(self, states: Sequence[bool], parent: str | None) -> Iterator[dict[str, Any]]:
        """A checkbox inline becomes a `checkbox` block carrying its state.

        `Kind.CHECKBOX` exists precisely because "docling separates CHECKBOX_SELECTED/UNSELECTED
        and a boolean is not a label" (03:840). The boolean has nowhere else to go: it is not a
        range over text, so it is not a mark, and rendering it as `[x]` inside the text would put a
        control's state into quotable document content.
        """
        for checked in states:
            yield self._block(
                tmp=self._tmp(),
                parent=parent,
                kind="checkbox",
                layer=BODY_LAYER,
                text="",
                payload={"checked": bool(checked)},
            )

    def _list(self, block: Any, tmp: str, parent: str | None, layer: str) -> _Emitted:
        """A `list` block plus one `list_item` per item; each item's blocks hang under it."""
        source = block.list
        records = [
            self._block(
                tmp=tmp,
                parent=parent,
                kind="list",
                layer=layer,
                text="",
                payload={"marker": str(source.marker), "start": int(source.start)},
            )
        ]
        pending: list[tuple[Any, str, str]] = []
        for item in source.items:
            item_tmp = self._tmp()
            records.append(
                self._block(
                    tmp=item_tmp,
                    parent=tmp,
                    kind="list_item",
                    layer=layer,
                    text="",
                    label=item.marker_label or None,
                )
            )
            pending.extend((child, item_tmp, layer) for child in item.blocks)
        return _Emitted(records, pending)

    def _table(self, block: Any, tmp: str, parent: str | None, layer: str) -> _Emitted:
        """A `table` block plus one `table_cell` per ORIGIN slot, in row-major origin order.

        Covered slots emit nothing. `build_grid` "registers covered positions, later placements
        skip them" (03:1935) from the origins' spans, so emitting them here would hand the host a
        second copy of a derivation it owns -- and a second copy is exactly what INV-21 forbids.

        `cell is not None` implies `kind == table_cell` and a `parent` of kind `table`, both
        asserted at `add_block` (03:349). Both hold by construction here.
        """
        table = block.table
        self.tables += 1
        spans = False
        records = [
            self._block(
                tmp=tmp,
                parent=parent,
                kind="table",
                layer=layer,
                text="",
                payload={
                    "header_rows": int(table.header_rows),
                    "header_cols": 0,
                    "kind": str(table.kind),
                },
            )
        ]
        pending: list[tuple[Any, str, str]] = []
        for r, row in enumerate(table.grid):
            for c, slot in enumerate(row):
                if str(slot.kind) != "origin" or slot.cell is None:
                    continue
                cell = slot.cell
                row_span, col_span = int(cell.row_span), int(cell.col_span)
                spans = spans or row_span > 1 or col_span > 1
                cell_tmp = self._tmp()
                records.append(
                    self._block(
                        tmp=cell_tmp,
                        parent=tmp,
                        kind="table_cell",
                        layer=layer,
                        text="",
                        cell={"r": r, "c": c, "row_span": row_span, "col_span": col_span},
                    )
                )
                pending.extend((child, cell_tmp, layer) for child in cell.blocks)
        self.has_spans = self.has_spans or spans
        return _Emitted(records, pending)

    # -- one record --------------------------------------------------------

    def _block(
        self,
        *,
        tmp: str,
        parent: str | None,
        kind: str,
        layer: str,
        text: str,
        marks: list[dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
        label: str | None = None,
        raw_kind: str | None = None,
        cell: dict[str, int] | None = None,
        assets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """One `block` record. `os` is `{"k": "none"}` on every one of them, always.

        Not "usually" and not "unless the driver can do better": the eight variants carry no source
        address, so there is no document and no block for which this driver could write anything
        else. 16-roadmap.md:484 names `os = {"k": "none"}` as half of what makes this card the
        **honest** one, and the conform `capability` suite's P14 clause for
        `origin_span = "none"` fails the run if any block carries an address.

        `quote = "normalized"` follows from the same fact rather than from a measurement of the
        text: with no address, no block can ever be re-proved against the source, so `verbatim` is
        unreachable and 05:3225 states the consequence for the corpus -- "every block is
        quote='normalized' and `verbatim` is unreachable on the office path at release 1".
        """
        if marks:
            self.has_marks = True
        record: dict[str, Any] = {
            "t": "block",
            "tmp": tmp,
            "parent": parent,
            "page": 0,
            "kind": kind,
            "layer": layer,
            "text": text,
            "quote": _QUOTE,
            "trust": _TRUST,
            "method": _METHOD,
            "os": dict(_ORIGIN_NONE),
            "quad": None,
            "marks": marks or [],
            "payload": payload,
        }
        if label is not None:
            record["label"] = label
        if raw_kind is not None:
            record["raw_kind"] = raw_kind
        if cell is not None:
            record["cell"] = cell
        if assets is not None:
            record["assets"] = assets
        return record

    # -- what `achieved` reads ---------------------------------------------

    def note_ref(self, note_id: str) -> str:
        """The tmp id a `note_ref` mark points at, minted on first reference.

        A reference can precede its body in the stream, so the id is minted here and reused when
        the body is written. The alternative -- two passes so bodies always come first -- would
        double the walk to save a dictionary.
        """
        tmp = self._notes.get(note_id)
        if tmp is None:
            tmp = self._tmp()
            self._notes[note_id] = tmp
        self._note_refs.add(note_id)
        return tmp

    @property
    def notes_rung(self) -> str:
        """`none | inline | linked`, computed exactly as 03:532's rollup computes it.

        "`none` if no `layer = note` block; `linked` if every note body has an inbound
        `rel(note_ref)`; `inline` otherwise." The inbound edge here is the `note_ref` mark that
        named the note, which is the fragment's form of that rel.
        """
        if not self._notes:
            return "none"
        return "linked" if self._note_refs >= set(self._notes) else "inline"


class _Emitted:
    """What one anydoc Block produced: records to yield, and child frames to push."""

    __slots__ = ("pending", "records")

    def __init__(
        self, records: list[dict[str, Any]], pending: Sequence[tuple[Any, str | None, str]]
    ) -> None:
        self.records = records
        self.pending = list(pending)


class _Run:
    """One block's inline content, flattened: its text, its marks, and what became blocks."""

    __slots__ = ("checkboxes", "images", "marks", "text")

    def __init__(self) -> None:
        self.text = ""
        self.marks: list[dict[str, Any]] = []
        self.images: list[tuple[str, int | None, str | None]] = []
        self.checkboxes: list[bool] = []


class _Inlines:
    """The inline reader: `Inline[]` -> text plus marks, with a link's children read in place.

    A link's `content` is itself a list of inlines, so the reader is re-entrant over that one
    field. It is bounded -- anydoc does not nest links inside links -- and the alternative, a
    second stack for a one-level structure, would be machinery with no case.
    """

    __slots__ = ("_run", "_walk")

    def __init__(self, walk: Walk) -> None:
        self._walk = walk
        self._run = _Run()

    def read(self, inlines: Sequence[Any]) -> _Run:
        for inline in inlines:
            self._one(inline)
        return self._run

    def _one(self, inline: Any) -> None:  # noqa: PLR0911 -- one arm per Inline kind.
        kind = str(inline.kind)
        start = len(self._run.text)
        if kind == "text":
            self._run.text += nfc(str(inline.text or ""))
            self._style(inline.style, start, len(self._run.text))
            return
        if kind == "line_break":
            self._run.text += "\n"
            return
        if kind == "math":
            source = str(inline.text or "")
            self._run.text += nfc(source)
            self._walk.notations.add("latex")
            self._run.marks.append(
                {
                    "kind": "math",
                    "a": start,
                    "b": len(self._run.text),
                    "notation": "latex",
                    "src": source,
                }
            )
            return
        if kind == "link":
            for child in inline.content or ():
                self._one(child)
            target = inline.target
            if target is not None and str(target.value):
                self._run.marks.append(
                    {
                        "kind": "link",
                        "a": start,
                        "b": len(self._run.text),
                        "target": str(target.value),
                        "target_kind": _LINK_TARGET_KINDS.get(str(target.kind), "external"),
                    }
                )
            return
        if kind == "anchor":
            self._run.marks.append(_anchor_mark(str(inline.anchor or ""), "bookmark", start))
            return
        if kind == "note_ref":
            note_id = str(inline.note_id or "")
            self._run.marks.append(
                {
                    "kind": _MARK_NOTE_REF,
                    "a": start,
                    "b": start,
                    "target_tmp": self._walk.note_ref(note_id),
                    "label": note_id,
                }
            )
            return
        if kind == "image":
            source = inline.source
            asset_id = getattr(source, "asset_id", None) if source is not None else None
            url = getattr(source, "url", None) if source is not None else None
            self._run.images.append((str(inline.alt or ""), asset_id, url))
            return
        if kind == "checkbox":
            self._run.checkboxes.append(bool(inline.checked))

    def _style(self, style: Any, start: int, end: int) -> None:
        """Four booleans -> up to four marks over the same range.

        Four separate marks and not one combined record, because "overlapping ranges are
        representable" is the property 03:369 buys against marker's collapse of formatting into one
        `formats: List[Literal[...]]` per span, "which cannot express bold ending mid-italic". A
        combined record here would re-introduce exactly that at the wire.
        """
        if style is None or start == end:
            return
        for attribute, mark_kind in (
            ("bold", "bold"),
            ("italic", "italic"),
            ("strike", "strike"),
            ("code", "code"),
        ):
            if getattr(style, attribute, False):
                self._run.marks.append({"kind": mark_kind, "a": start, "b": end})


def _anchor_mark(name: str, akind: str, at: int = 0) -> dict[str, Any]:
    """A zero-width `anchor` mark. `a == b` is legal and meaningful here (03:372).

    `akind` is `AnchorKind`'s: a heading's own id is a `section`, a `w:bookmarkStart` or
    `text:bookmark` is a `bookmark`. Both are members of the fourteen, and the vocabulary is the
    same on both sides of L3's join, so a driver picking a word outside it would break the join
    rather than merely mislabel a row.
    """
    return {"kind": "anchor", "a": at, "b": at, "name": name, "akind": akind}
