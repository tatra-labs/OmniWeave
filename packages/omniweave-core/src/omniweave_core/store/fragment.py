"""`owdoc-fragment/1` -> `DocSink`: the host's reading of what a `parse/1` driver proposed.

03-document-model.md:47 is the principle and this module is its mechanism: *"The host writes; the
driver proposes. A `parse/1` driver emits an `owdoc-fragment/1` NDJSON [stream] ... addressing
blocks by a per-invocation `tmp` id"*, and 02-architecture.md section 4.1 hop 16 is the step --
*"`omniweave_core.model.DocSink` (host-side) | the decoded fragment, block by block | `BlockId`s,
minting `addr` and `cite` from `doc.next_cite_n` | `doc`, `page`, `block`, `part`, `mark`, `rel`,
`diag`. `end_page()` commits **one transaction**"* (02:486). `DocSink` has existed since P2 and has
never been driven by a real driver's output; the conform kit's `decode_fragment` splits records by
kind for the `capability` suite and writes nothing. This is the first reader that writes.

## What the decoder owns, and what it refuses to own

It owns **translation**: record `t` to one of `DocSink`'s eleven calls, a wire string to its
`omniweave_core.model` member, a `tmp` id to the `BlockId` `add_block` returned, and an asset's
position in `produced` to its bytes. It owns **the two fragment refusals** 04:1797-1798 name:

* `OW_FRAGMENT_OUT_OF_SCOPE` -- *"a fragment naming a page outside the `PartSelector` | refused at
  decode; nothing is committed"*. Checked on each `page` record, before `begin_page`.
* `OW_FRAGMENT_DANGLING_TMP` -- *"a `tmp` id referenced and never defined ... fails the **whole
  document**"*. A `parent` must be defined before its child (`add_block` needs the parent's
  `BlockId`), a `rel` endpoint may be defined later on any page, and 03:2985's P1 adds that *"no
  `tmp` is defined twice"*. The check fires before `end_doc`, so a dangling fragment never
  becomes a visible generation: its pages are durable and invisible, exactly 03:2581's crash
  state, and `ow doc diff` can still show them.

It owns **nothing `DocSink` already enforces**: trust and quote ceilings, payload shapes, the cell
and table pairing, layer inheritance, the mark bounds. A second check here would be a second home
for each (INV-21), so a draft that `add_block` refuses raises out of `add_block`.

## Three things the fragment carries that the sink has no call for

1. **`block_asset`.** `store/doc.py`'s module docstring already records that *"`block_asset` has no
   writer among the eleven, and that is a plan defect, not a choice here"*. So an office block's
   `assets` links, and any `block_asset` record, are **counted and not written**:
   `Decoded.asset_links_dropped` carries the number and the ingest report prints it (D586).
2. **`note_ref`'s `target_addr`.** 03 section 2.7 prints the mark's value as `{"target_addr":
   "...", "label": "3"}`. The address is minted inside `add_block` and `add_block` returns only a
   `BlockId`, so a mark cannot name its target's `addr` through the eleven -- and the target is
   usually defined *after* the reference, on a later line. The link is not lost: it is written as
   what 03 section 2.9's `notes` rollup actually counts, a `rel` of kind `NOTE_REF` from the
   referencing block to the note body, and the mark keeps its `label` with `target_addr` absent
   (D586).
3. **The `document` root.** `DocSink` requires exactly one parentless block, of kind `document`,
   whose addr is the literal `doc` (03:1098), and 04's worked driver emits its top-level blocks with
   `"parent": None` and no root at all (04:2268). A driver cannot know the root's `BlockId` and
   has no business proposing a block whose page "is meaningless" (03:1099). So the decoder mints
   it on the first `page` record -- `quote = SYNTHETIC`, `trust = EXTRACTED`, the page's method --
   and a fragment's `parent: null` means a page root, a child of that block. A fragment that sends
   a `document` block itself is refused (D586).
4. **A table's grid.** `add_grid` must run in the transaction of the table's last page (03:580)
   and the fragment has no "table ends here" record. Every table's grid is therefore built when
   the fragment's last page closes, which is the last page of every table in it. For the office
   path (one `stream` page) the two are the same transaction.

Specified in 03-document-model.md sections 2.7, 2.10, 13.5 and 17 (P1, P2), 04-driver-system.md
section 6.5, and 02-architecture.md section 4.1 row 16.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, BinaryIO, Final, Literal

from omniweave_ports.types import ArtifactRef, PartSelector

from omniweave_core.blobs import parse_ref
from omniweave_core.errors import ModelError
from omniweave_core.model.block import BlockDraft, CellPos, Mark
from omniweave_core.model.enums import Kind, Layer, Method, PageKind, Quote, RelKind, Trust
from omniweave_core.model.grid import build_grid
from omniweave_core.model.records import AssetDraft, Diag, DocRecord, PageRecord
from omniweave_core.model.spans import OriginNone

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_core.model.block import BlockId, Capabilities
    from omniweave_core.store import DocSink

__all__ = [
    "DANGLING_TMP",
    "OUT_OF_SCOPE",
    "RECORD_KINDS",
    "Decoded",
    "FragmentDoc",
    "decode",
    "records_of",
]

DANGLING_TMP: Final[str] = "OW_FRAGMENT_DANGLING_TMP"
"""04:1798 and 03:2985's P1. `codes.toml` row OW-M-033."""

OUT_OF_SCOPE: Final[str] = "OW_FRAGMENT_OUT_OF_SCOPE"
"""04:1797 and 03:2986's P2. `codes.toml` row OW-M-034."""

RECORD_KINDS: Final[frozenset[str]] = frozenset(
    {"doc", "part", "page", "block", "asset", "block_asset", "diag", "end"}
)
"""03:635's seven discriminators, plus `end`, which 04's worked driver (04:2294) and both
first-party parse drivers emit as the fragment's last record. A record outside the set is refused:
the discriminator is closed, and a record nobody reads is a proposal silently declined."""

_FIX: Final[str] = "ow conform --suite contract   # the driver emitted this fragment"
_PLAIN_MARKS: Final[frozenset[str]] = frozenset(
    {"bold", "italic", "underline", "strike", "sub", "sup", "code"}
)
_MARK_SHAPE: Final[frozenset[str]] = frozenset({"kind", "a", "b"})
_NOTE_REF: Final[str] = "note_ref"
_SEVERITY: Final[dict[str, Literal["error", "warning", "info"]]] = {
    "error": "error",
    "warning": "warning",
    "info": "info",
}


@dataclass(frozen=True, slots=True)
class FragmentDoc:
    """What the HOST knows about the document before the fragment is read. Never the driver's.

    `doc_key` is `sha256(NORMALIZED source bytes)[:16]` (03:162), `source_sha256` the raw digest
    beside it, `declared` the card's `[capability.parse]` copied at parse time (03 section 2.9).
    The fragment's `doc` record supplies `format`, `media_type` and `page_count`, which are the
    driver's reading of the bytes and are cross-checked by nothing here -- detection already wrote
    the unit's own, and `route_decision` recorded which the router believed.
    """

    doc_key: bytes
    source_sha256: bytes
    normalizer: str | None
    uri: str
    source_bytes: int
    declared: Capabilities
    model_version: str
    format_evidence: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Decoded:
    """One fragment's outcome: the committed `DocRecord` and the counts a report prints."""

    record: DocRecord
    pages: int
    blocks: int
    assets: int
    rels: int
    diags: int
    asset_links_dropped: int
    status: str


@dataclass(slots=True)
class _State:
    """The decoder's resident state: the `tmp` map and whatever waits on a later record."""

    ids: dict[str, BlockId] = field(default_factory=dict)
    root: BlockId | None = None
    page: int | None = None
    pages: int = 0
    pending_parts: list[Mapping[str, Any]] = field(default_factory=list)
    pending_assets: list[Mapping[str, Any]] = field(default_factory=list)
    pending_rels: list[tuple[BlockId, str]] = field(default_factory=list)
    tables: dict[BlockId, tuple[Mapping[str, Any], list[_Cell]]] = field(default_factory=dict)
    assets: int = 0
    rels: int = 0
    diags: int = 0
    dropped: int = 0
    ended: str | None = None
    page_stats: Mapping[str, Any] = field(default_factory=dict)


class _Cell:
    """03:337's `CellDraft` -- `id: BlockId; pos: CellPos` -- read structurally by `build_grid`."""

    __slots__ = ("id", "pos")

    def __init__(self, ident: BlockId, pos: CellPos) -> None:
        self.id = ident
        self.pos = pos


def records_of(body: bytes | Iterable[bytes]) -> Iterable[Mapping[str, Any]]:
    """One JSON object per line, lazily. A blank line is skipped; anything else is a record."""
    lines = io.BytesIO(body) if isinstance(body, bytes) else body
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise _refuse("OW_MODEL", f"owdoc-fragment/1 line {number} is not JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise _refuse("OW_MODEL", f"owdoc-fragment/1 line {number} is not an object")
        yield record


def decode(
    records: Iterable[Mapping[str, Any]],
    *,
    sink: DocSink,
    doc: FragmentDoc,
    assets: Sequence[ArtifactRef] = (),
    open_ref: Callable[[ArtifactRef], BinaryIO] | None = None,
    selector: PartSelector = PartSelector(),  # noqa: B008 -- frozen, fieldless-by-default
) -> Decoded:
    """Drive `sink` through one fragment, in the fragment's own order. Returns after `end_doc`.

    `assets` is `produced` minus the fragment, in the driver's order: an `asset` record's `ord` is
    its position here. `open_ref` reads a blob-backed ref's bytes; an inline ref needs none.
    """
    state = _State()
    iterator = iter(records)
    first = next(iterator, None)
    if first is None or first.get("t") != "doc":
        raise _refuse("OW_MODEL", "an owdoc-fragment/1 stream begins with its `doc` record")
    record = sink.begin_doc(_doc_record(first, doc))
    blocks = 0
    for item in iterator:
        blocks += _one_record(
            item, sink=sink, state=state, assets=assets, open_ref=open_ref, selector=selector
        )
    if state.ended is None:
        raise _refuse("OW_MODEL", "the fragment has no `end` record; it was truncated")
    if state.page is None:
        raise _refuse("OW_MODEL", "the fragment has no `page` record; every block is on a page")
    _flush(sink, state, assets, open_ref)
    _close(sink, state)
    committed = sink.end_doc(state.ended)
    return Decoded(
        record=committed if committed is not None else record,
        pages=state.pages,
        blocks=blocks,
        assets=state.assets,
        rels=state.rels,
        diags=state.diags,
        asset_links_dropped=state.dropped,
        status=state.ended,
    )


# ---------------------------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------------------------


def _one_record(
    item: Mapping[str, Any],
    *,
    sink: DocSink,
    state: _State,
    assets: Sequence[ArtifactRef],
    open_ref: Callable[[ArtifactRef], BinaryIO] | None,
    selector: PartSelector,
) -> int:
    """One record after the `doc` record, dispatched on `t`. Returns the blocks it added (0/1)."""
    kind = item.get("t")
    if kind not in RECORD_KINDS:
        raise _refuse("OW_MODEL", f"record kind {kind!r} is not one of {sorted(RECORD_KINDS)}")
    if state.ended is not None:
        raise _refuse("OW_MODEL", f"a {kind!r} record after `end`; `end` is the last record")
    if kind == "doc":
        raise _refuse("OW_MODEL", "a second `doc` record; a fragment is one document")
    if kind == "block":
        _flush(sink, state, assets, open_ref)
        _block(item, sink=sink, state=state)
        return 1
    if kind == "part":
        state.pending_parts.append(item)
    elif kind == "asset":
        state.pending_assets.append(item)
    elif kind == "page":
        _page(item, sink=sink, state=state, selector=selector)
    elif kind == "block_asset":
        state.dropped += 1
    elif kind == "diag":
        _require_open(state, "diag")
        sink.diag(_diag(item, state))
        state.diags += 1
    else:  # "end"
        state.ended = str(item.get("status", "ok"))
        stats = item.get("page_stats") or {}
        state.page_stats = stats if isinstance(stats, dict) else {}
    return 0


def _doc_record(first: Mapping[str, Any], doc: FragmentDoc) -> DocRecord:
    page_count = first.get("page_count")
    return DocRecord(
        doc_ord=0,
        doc_key=doc.doc_key,  # type: ignore[arg-type]
        gen=0,
        source_sha256=doc.source_sha256,
        normalizer=doc.normalizer,
        uri=doc.uri,
        media_type=str(first.get("media_type") or ""),
        format=str(first.get("format") or ""),
        format_evidence=MappingProxyType(dict(doc.format_evidence)),
        source_bytes=doc.source_bytes,
        status="ok",
        page_count=None if page_count is None else int(page_count),
        model_version=doc.model_version,
        declared=doc.declared,
        achieved=doc.declared,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({}),
    )


def _page(item: Mapping[str, Any], *, sink: DocSink, state: _State, selector: PartSelector) -> None:
    number = int(item.get("page", -1))
    if selector.pages and number not in selector.pages:
        raise _refuse(
            OUT_OF_SCOPE,
            f"page {number} is outside the PartSelector's pages {list(selector.pages)} (04:1797)",
        )
    if state.page is not None:
        sink.end_page(_stats(state, state.page))
    sink.begin_page(
        PageRecord(
            page=number,
            page_kind=_member(PageKind, item.get("page_kind"), "page_kind"),
            label=item.get("label"),
            w_mpt=item.get("w_mpt"),
            h_mpt=item.get("h_mpt"),
            rotation=int(item.get("rotation") or 0),
            quad_origin=item.get("quad_origin"),
            method=_member(Method, item.get("method"), "method"),
            status=str(item.get("status") or "ok"),
        )
    )
    state.page = number
    state.pages += 1
    if state.root is None:
        state.root = sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=_member(Method, item.get("method"), "method"),
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )


def _block(item: Mapping[str, Any], *, sink: DocSink, state: _State) -> None:
    _require_open(state, "block")
    tmp = _tmp(item.get("tmp"))
    if tmp in state.ids:
        raise _refuse(DANGLING_TMP, f"tmp {tmp!r} is defined twice (03:2985 P1)")
    page = item.get("page", state.page)
    if page != state.page:
        raise _refuse(
            "OW_MODEL", f"block {tmp!r} names page {page} while page {state.page} is open"
        )
    parent_tmp = item.get("parent")
    parent = state.root
    if parent_tmp is not None:
        parent = state.ids.get(str(parent_tmp))
        if parent is None:
            raise _refuse(
                DANGLING_TMP,
                f"block {tmp!r} names parent {parent_tmp!r}, which no earlier record defined",
            )
    raw_kind = str(item.get("kind") or "")
    if raw_kind == Kind.DOCUMENT.value:
        raise _refuse(
            "OW_MODEL", f"block {tmp!r} is a `document`; the host mints the root (03:1098)"
        )
    known = raw_kind in {member.value for member in Kind}
    cell = item.get("cell")
    draft = BlockDraft(
        kind=Kind(raw_kind) if known else Kind.UNKNOWN,
        layer=_member(Layer, item.get("layer"), "layer"),
        method=_member(Method, item.get("method"), "method"),
        trust=_named(Trust, item.get("trust"), "trust"),
        quote=_named(Quote, item.get("quote"), "quote"),
        parent=parent,
        text=item.get("text") or None,
        label=item.get("label"),
        raw_kind=None if known else raw_kind,
        origin=_origin(item.get("os"), tmp),
        payload=item.get("payload"),
        cell=None if cell is None else CellPos(**cell),
    )
    block = sink.add_block(draft)
    state.ids[tmp] = block
    marks = [_mark(raw, block, state) for raw in item.get("marks") or ()]
    sink.add_marks(block, marks)
    links = item.get("assets") or ()
    state.dropped += len(links)
    if draft.kind is Kind.TABLE:
        state.tables[block] = (draft.payload or {}, [])
    if draft.cell is not None and parent is not None and parent in state.tables:
        state.tables[parent][1].append(_Cell(block, draft.cell))
    _resolve_rels(sink, state)


def _mark(raw: Mapping[str, Any], block: BlockId, state: _State) -> Mark:
    """One wire mark as a `Mark`, its `value` in 03 section 2.7's shape for its kind."""
    kind = str(raw.get("kind") or "")
    a, b = int(raw.get("a", 0)), int(raw.get("b", 0))
    if kind in _PLAIN_MARKS:
        return Mark(a=a, b=b, kind=kind)
    if kind == "link":
        return Mark(
            a=a, b=b, kind=kind, value={"target": raw.get("target"), "kind": raw.get("target_kind")}
        )
    if kind == _NOTE_REF:
        target = raw.get("target_tmp")
        if target is not None:
            state.pending_rels.append((block, str(target)))
        return Mark(a=a, b=b, kind=kind, value={"label": raw.get("label")})
    rest = {key: value for key, value in raw.items() if key not in _MARK_SHAPE}
    return Mark(a=a, b=b, kind=kind, value=rest or None)


def _resolve_rels(sink: DocSink, state: _State) -> None:
    """Write every pending `NOTE_REF` rel whose target is now minted. Needs an open page."""
    waiting: list[tuple[BlockId, str]] = []
    for src, target in state.pending_rels:
        dst = state.ids.get(target)
        if dst is None:
            waiting.append((src, target))
            continue
        sink.add_rel(src, dst, RelKind.NOTE_REF, trust=Trust.EXTRACTED)
        state.rels += 1
    state.pending_rels = waiting


def _flush(
    sink: DocSink,
    state: _State,
    assets: Sequence[ArtifactRef],
    open_ref: Callable[[ArtifactRef], BinaryIO] | None,
) -> None:
    """Parts and assets need an open page (`add_part`, `add_asset`); write whatever waited."""
    if state.page is None:
        return
    for part in state.pending_parts:
        sink.add_part(
            str(part.get("path") or ""),
            None,
            bytes.fromhex(str(part.get("sha256") or "")),
            int(part.get("byte_len") or 0),
        )
    state.pending_parts.clear()
    for asset in state.pending_assets:
        ref = _asset_ref(asset, assets)
        body = _read(ref, open_ref)
        sink.add_asset(
            AssetDraft(
                media_type=str(asset.get("media_type") or "application/octet-stream"),
                sha256=hashlib.sha256(body).digest() if ref.blob is None else parse_ref(ref.blob),
                byte_len=ref.byte_len,
                origin_part=asset.get("origin_part"),
                width=asset.get("width"),
                height=asset.get("height"),
            ),
            io.BytesIO(body),
        )
        state.assets += 1
    state.pending_assets.clear()


def _close(sink: DocSink, state: _State) -> None:
    """The last page's transaction: the dangling check, every grid, then `end_page`."""
    if state.pending_rels:
        missing = sorted({target for _src, target in state.pending_rels})
        raise _refuse(
            DANGLING_TMP,
            f"note references name {missing}, which no record defined (04:1798); the whole "
            f"document fails",
        )
    for table, (payload, cells) in state.tables.items():
        if not cells:
            continue
        sink.add_grid(
            table,
            build_grid(
                cells,
                header_rows=int(payload.get("header_rows") or 0),
                header_cols=int(payload.get("header_cols") or 0),
                kind=str(payload.get("kind") or "data"),
                diag=lambda _d: None,
            ),
        )
    assert state.page is not None  # noqa: S101 -- decode() checked it before calling.
    sink.end_page(_stats(state, state.page))


# ---------------------------------------------------------------------------------------------
# Small translations
# ---------------------------------------------------------------------------------------------


def _stats(state: _State, page: int) -> Mapping[str, Any]:
    stats = state.page_stats.get(str(page)) if state.page_stats else None
    return stats if isinstance(stats, dict) else {}


def _asset_ref(asset: Mapping[str, Any], assets: Sequence[ArtifactRef]) -> ArtifactRef:
    ordinal = asset.get("ord")
    if not isinstance(ordinal, int) or not 0 <= ordinal < len(assets):
        raise _refuse(
            DANGLING_TMP,
            f"asset {asset.get('tmp')!r} names produced position {ordinal!r} of {len(assets)}",
        )
    ref = assets[ordinal]
    if ref.kind != "asset":
        raise _refuse("OW_MODEL", f"produced position {ordinal} is a {ref.kind}, not an asset")
    return ref


def _read(ref: ArtifactRef, open_ref: Callable[[ArtifactRef], BinaryIO] | None) -> bytes:
    if ref.inline is not None:
        return ref.inline
    if open_ref is None:
        raise _refuse("OW_MODEL", f"{ref.blob} is blob-backed and no reader was supplied")
    with open_ref(ref) as handle:
        return handle.read()


def _origin(raw: object, tmp: str) -> OriginNone:
    """`os` -> an `OriginSpan`. `none` only, until a driver that records an address is routed.

    The office driver's every block is `{"k": "none"}` (its card's `origin_span = "none"`). The
    four addressed variants need their part's bytes to be re-verifiable (INV-10), which the PDF
    driver's cell will bring with it; refusing them here is the fail-closed direction -- a block
    that claimed `bytes` and was silently stored as `none` would be a quote tier nobody earned.
    """
    kind = raw.get("k") if isinstance(raw, dict) else None
    if kind not in (None, "none"):
        raise _refuse("OW_MODEL", f"block {tmp!r} carries os.k={kind!r}; this decoder reads none")
    return OriginNone()


def _diag(item: Mapping[str, Any], state: _State) -> Diag:
    return Diag(
        code=str(item.get("code") or "OW_MODEL"),
        severity=_SEVERITY.get(str(item.get("severity")), "info"),
        component=str(item.get("component") or "fragment"),
        message=str(item.get("message") or item.get("detail") or ""),
        page=state.page,
    )


def _tmp(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise _refuse(DANGLING_TMP, f"a block's tmp is {raw!r}, not a non-empty string")
    return raw


def _member(enum: Any, raw: object, what: str) -> Any:
    try:
        return enum(raw)
    except ValueError as exc:
        raise _refuse("OW_MODEL", f"{what} {raw!r} is not a {enum.__name__} member") from exc


def _named(enum: Any, raw: object, what: str) -> Any:
    """An `IntEnum` spelled by its lower-case NAME on the wire (`"extracted"`, `"normalized"`)."""
    try:
        return enum[str(raw).upper()]
    except KeyError as exc:
        raise _refuse("OW_MODEL", f"{what} {raw!r} is not a {enum.__name__} member") from exc


def _require_open(state: _State, what: str) -> None:
    if state.page is None:
        raise _refuse("OW_MODEL", f"a {what} record before any `page` record")


def _refuse(symbol: str, message: str) -> ModelError:
    return ModelError(message, symbol=symbol, fix=_FIX)
