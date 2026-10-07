"""The host half of a Segment-grained `derive/1` Pass: its view, its answer, its run. **D667.**

D666 shipped `derive.anchor.defterm` and ruled both wires it speaks: it reads the Segment form of
`owgraph-segment/1` and prints Draft-shaped item frames on `owgraph-items/1`. This module is both
ends on the host's side, as `segments.py` is for the segmenter:

* `build_segment_view` -- one live Segment as the Segment form (06:1305-1334): a `segment` header,
  then its members in `segment_block.ord` order, addressed by `cite` only.
* `decode_items` -- the driver's frames, unit by unit, rebuilt into the seven Drafts of
  `store/graph.py` plus the `cover`, `cover_empty` and `diag` control frames.
* `drive_items` -- one `derive_run` per Segment through `SqliteGraphSink`, inside the caller's
  `Unit`, so the run and every row it writes commit together (06:373).

## Rulings this module makes (the ledger's D667)

1. **A malformed ITEM is data; a malformed BODY is a refusal.** An item frame whose kind is known
   but whose fields are wrong becomes `quarantine(row_kind, OW_GRAPH_UNPARSED_ITEM, frame)` with the
   frame kept verbatim -- 06:694's "an unparseable response body" code, applied where there is a
   row kind to file it under. A line that is not JSON, a frame kind nobody declared, an item before
   any `seg` frame, or `seg` frames that do not name the views in order cannot be attributed to a
   row kind or a Segment, so the whole answer is `GraphError` and nothing is written.
2. **A cover cite outside the Segment refuses the answer.** `GraphSink.cover` raises on one because
   a cover set is the runner's to build (`QUARANTINE_ROW_KINDS` has no `cover`); here the runner is
   relaying a driver's set, so the decoder checks it first and refuses before any run opens.
3. **A diag frame naming a cite outside the Segment keeps the cite in `detail` with no block.** A
   diagnostic is not an L3 row and has nothing to forge, so it is recorded rather than refused.
4. **`trust` absent means `ambiguous`** (03 section 8.2, *"Absent on the wire means AMBIGUOUS, and
   it is counted"*) and an unknown name quarantines the item.
5. **The run's status is `ok` when the answer held an item and `empty` when it held only cover**,
   and the sink overrides it to `quarantined` on a dangling `tmp`. `partial` and `failed` are a
   runner's to report about a run it cut short; this function always finishes the run it opens.
6. **The view's `defaults` are the modal `layer` and `page`, and `covered: false`.** A free Pass
   has no floor (06:345), so nothing is covered for it; a billed Pass's view will mark the bits of
   `SegmentRef.uncovered` when one exists.

`import sqlite3` is for the `Connection` type, as in `segments.py`; this module opens no connection
and starts no transaction (07:2717).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, NoReturn, cast

from omniweave_core.errors import GraphError
from omniweave_core.model.block import BlockId, Cite
from omniweave_core.model.enums import AnchorKind, Trust
from omniweave_core.model.records import Diag
from omniweave_core.model.spans import TextSpan
from omniweave_core.store.graph import (
    OW_GRAPH_UNPARSED_ITEM,
    AliasDraft,
    AnchorDraft,
    ClaimDraft,
    EdgeDraft,
    EntityDraft,
    Grounded,
    MentionDraft,
    PassIdentity,
    RunReport,
    SegmentRef,
    SpendVector,
    SqliteGraphSink,
    TmpRef,
    XrefDraft,
)

if TYPE_CHECKING:
    from omniweave_core.drivers.card import DriverCard

__all__ = [
    "ITEM_LANES",
    "Cover",
    "ItemView",
    "Rejected",
    "UnitItems",
    "build_segment_view",
    "decode_items",
    "document_body",
    "document_views",
    "drive_items",
    "register_pass",
]

_ITEM_KINDS: Final = frozenset({"entity", "alias", "mention", "edge", "claim", "anchor", "xref"})
_CONTROL_KINDS: Final = frozenset({"cover", "cover_empty", "diag"})
_SEVERITIES: Final = frozenset({"error", "warning", "info"})
_SCOPES: Final = frozenset({"document", "corpus"})
_TRUST_NAMES: Final = {member.name.lower(): member for member in Trust}
_AKINDS: Final = {member.value: member for member in AnchorKind}
_CLAIM_STATUSES: Final = ("asserted", "denied", "suspected", "superseded")
"""`ClaimDraft.status`'s Literal (06:459), which is also `ClaimStatus`'s four values."""
_PRECISIONS: Final = ("year", "month", "day", "datetime")
"""`ClaimDraft.t_precision`'s Literal (06:462)."""
_FIX: Final = "ow drivers explain <the pass>; the frame shapes are D666's"


@dataclass(frozen=True, slots=True)
class ItemView:
    """One Segment as a Pass reads it, and the index its answer is resolved against."""

    ref: SegmentRef
    seg: str
    """`"seg:" + hex(content_digest)[:16]` (04:727) -- what the driver echoes."""
    body: bytes
    cites: Mapping[str, int]
    """Every member's cite to its `block_id`: the `allowed_cites` of the run."""


@dataclass(frozen=True, slots=True)
class Cover:
    lane: str
    cites: tuple[Cite, ...]
    empty_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Rejected:
    """An item frame of a known kind that does not decode: quarantined, never dropped."""

    row_kind: str
    frame: Mapping[str, Any]
    reason: str


Item = (
    EntityDraft
    | AliasDraft
    | MentionDraft
    | EdgeDraft
    | ClaimDraft
    | AnchorDraft
    | XrefDraft
    | Rejected
    | Cover
    | Diag
)


@dataclass(frozen=True, slots=True)
class UnitItems:
    """One unit's answer, in the order the driver wrote it."""

    view: ItemView
    items: tuple[Item, ...]

    @property
    def has_items(self) -> bool:
        return any(not isinstance(i, Cover | Diag) for i in self.items)


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------

_READ_SEGMENT: Final = (
    "SELECT doc_ord, gen, heading_path, layer, atom, n_blocks, n_tokens, content_digest, state "
    "FROM segment WHERE segment_id = ?"
)
_READ_MEMBERS: Final = (
    "SELECT sb.ord, b.block_id, b.cite, b.kind, b.layer, b.page, b.text, b.label, "
    "t.cite, c.r, c.c, m.header_rows, m.n_cols "
    "FROM segment_block sb JOIN block b ON b.block_id = sb.block_id "
    "LEFT JOIN cell c ON c.block_id = b.block_id "
    "LEFT JOIN block t ON t.block_id = c.table_id "
    "LEFT JOIN table_meta m ON m.block_id = c.table_id "
    "WHERE sb.segment_id = ? ORDER BY sb.ord"
)
_READ_MARKS: Final = (
    "SELECT k.block_id, k.a, k.b, k.kind, k.value FROM mark k "
    "JOIN segment_block sb ON sb.block_id = k.block_id "
    "WHERE sb.segment_id = ? ORDER BY k.block_id, k.a, k.b, k.mark_id"
)
"""06:1316 prints a block frame's `marks` as `[[a, b, kind, value]]`; `value` is the stored JSON
decoded. D670 sends them because `derive.anchor.native` reads the `anchor` marks a parse driver
recorded -- a bookmark, a heading's own id -- and a billed Pass reads the rest."""


def build_segment_view(connection: sqlite3.Connection, segment_id: int) -> ItemView:
    """One live Segment as the Segment form of `owgraph-segment/1` (06:1305, D666)."""
    row = connection.execute(_READ_SEGMENT, (segment_id,)).fetchone()
    if row is None or int(row[8]) != 0:
        raise GraphError(
            f"segment {segment_id} is not a live Segment",
            symbol="OW_GRAPH_STALE_SEGMENT",
            fix="re-select the Segments after the document's latest generation is segmented",
        )
    doc_ord, gen, path, layer_code, atom, n_blocks, n_tokens, digest, _ = row
    kinds = _names(connection, "kind")
    layers = _names(connection, "layer")
    members = connection.execute(_READ_MEMBERS, (segment_id,)).fetchall()
    marks: dict[int, list[list[Any]]] = {}
    for block_id, a, b, kind, value in connection.execute(_READ_MARKS, (segment_id,)):
        marks.setdefault(int(block_id), []).append(
            [int(a), int(b), str(kind), None if value is None else json.loads(value)]
        )
    defaults = {
        "layer": _modal([layers[int(m[4])] for m in members], layers[int(layer_code)]),
        "page": _modal([int(m[5]) for m in members], 0),
    }
    digest = bytes(digest)
    seg = f"seg:{digest.hex()[:16]}"
    frames: list[dict[str, Any]] = [
        {
            "t": "segment",
            "seg": seg,
            "heading_path": json.loads(path),
            "n_blocks": int(n_blocks),
            "n_tokens": int(n_tokens),
            "layer": layers[int(layer_code)],
            "atom": atom,
            "defaults": {**defaults, "covered": False},
        }
    ]
    cites: dict[str, int] = {}
    for ordinal, block_id, cite, kind, layer, page, text, label, *cell in members:
        table, r, c, header, n_cols = cell
        frame: dict[str, Any] = {"t": "block", "cite": cite, "kind": kinds[int(kind)]}
        frame["ord"] = int(ordinal)
        if layers[int(layer)] != defaults["layer"]:
            frame["layer"] = layers[int(layer)]
        if int(page) != defaults["page"]:
            frame["page"] = int(page)
        if text is not None:
            frame["text"] = text
        if label is not None:
            frame["label"] = label
        if int(block_id) in marks:
            frame["marks"] = marks[int(block_id)]
        if table is not None:
            frame["table"] = {
                "table_cite": table,
                "r": int(r),
                "c": int(c),
                "header_rows": int(header or 0),
                "n_cols": int(n_cols or 0),
            }
        frames.append(frame)
        cites[str(cite)] = int(block_id)
    body = "".join(json.dumps(f, separators=(",", ":"), ensure_ascii=False) + "\n" for f in frames)
    return ItemView(
        ref=SegmentRef(
            segment_id=segment_id,
            doc_ord=int(doc_ord),
            gen=int(gen),
            content_digest=digest,
            uncovered=None,
        ),
        seg=seg,
        body=body.encode("utf-8"),
        cites=cites,
    )


_LIVE_SEGMENTS: Final = (
    "SELECT segment_id FROM segment WHERE doc_ord = ? AND gen = ? AND state = 0 ORDER BY ord"
)


def document_views(connection: sqlite3.Connection, doc_ord: int, gen: int) -> tuple[ItemView, ...]:
    """Every live Segment of one generation, in `segment.ord` order. **D668.**"""
    return tuple(
        build_segment_view(connection, int(r[0]))
        for r in connection.execute(_LIVE_SEGMENTS, (doc_ord, gen)).fetchall()
    )


def document_body(views: Sequence[ItemView]) -> bytes:
    """A document-granularity Pass's one unit: its Segments' views, one after another (D668)."""
    return b"".join(v.body for v in views)


ITEM_LANES: Final[Mapping[str, str]] = {
    "anchor": "anchor",
    "xref": "xref",
    "entity": "entity",
    "alias": "entity",
    "mention": "entity",
    "edge": "entity",
    "claim": "claim",
    "summary": "summary",
}
"""`[capability.derive] items` to the derive lanes they serve. **D668.**

`derive_pass.lanes` is *"a JSON array over the `lane` domain"* (0002:112) and the card has no
`lanes` key -- 06:648's sample prints one, 04:620's table and `drivers/card.py` read `items` -- so
the lanes are derived from the items: an anchor is the anchor lane's, a reference occurrence the
xref lane's, an entity and everything addressing one (alias, mention, edge) the entity lane's, a
claim the claim lane's. `segment` serves no lane (06:825) and `field` has no producer at release 1.
"""

_COST_RANKS: Final = {"free": 0, "local_compute": 1, "billed_api": 2}
_REGISTRY_UPSERT: Final = """
INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, granularity,
                        card_sha256, schema_version)
VALUES(?, 'derive/1', ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(pass_id) DO UPDATE SET
  cost_class = excluded.cost_class, cost_rank = excluded.cost_rank, phase = excluded.phase,
  lanes = excluded.lanes, granularity = excluded.granularity,
  card_sha256 = excluded.card_sha256, schema_version = excluded.schema_version
"""


def register_pass(connection: sqlite3.Connection, card: DriverCard) -> None:
    """The `derive_pass` row a run of this card's Pass points at. **D668.**

    Upserted from the card every time the Pass runs, so the registry is the card that last ran,
    which is what `derive_run.pass_id` means. `enabled` is never written: it is an operator's.
    `cost_rank` is derived from `cost_class` and never read off the card (06:713).
    """
    cost = "free" if card.cost_model is None else str(card.cost_model.cost_class)
    items = card.derive.items if card.derive is not None else frozenset()
    lanes = sorted({ITEM_LANES[i] for i in items if i in ITEM_LANES})
    phase = card.derive_sibling.phase if card.derive_sibling is not None else 50
    connection.execute(
        _REGISTRY_UPSERT,
        (
            card.identity.id,
            cost,
            _COST_RANKS[cost],
            phase,
            json.dumps(lanes, separators=(",", ":")),
            card.identity.granularity,
            card.card_sha256,
            card.identity.schema_version,
        ),
    )


def _modal(values: Sequence[Any], fallback: Any) -> Any:
    return Counter(values).most_common(1)[0][0] if values else fallback


def _names(connection: sqlite3.Connection, domain: str) -> Mapping[int, str]:
    return {
        int(o): str(n)
        for n, o in connection.execute("SELECT name, ord FROM enum_val WHERE domain = ?", (domain,))
    }


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


def decode_items(body: bytes, views: Sequence[ItemView]) -> tuple[UnitItems, ...]:
    """The driver's `owgraph-items/1` answer, split per unit and rebuilt into Drafts.

    Raises:
        GraphError: the body cannot be attributed (ruling 1) or names cover outside its Segment
            (ruling 2). Nothing has been written when it raises.
    """
    groups: list[list[Item]] = []
    for number, frame in enumerate(_frames(body), start=1):
        kind = frame.get("t")
        if kind == "seg":
            if len(groups) >= len(views) or frame.get("seg") != views[len(groups)].seg:
                _refuse(f"seg frame {number} does not name unit {len(groups) + 1}'s Segment")
            groups.append([])
            continue
        if kind not in _ITEM_KINDS and kind not in _CONTROL_KINDS:
            _refuse(f"frame {number} is a {kind!r} frame; no Segment-grained Pass prints one")
        if not groups:
            _refuse(f"frame {number} comes before any seg frame")
        groups[-1].append(_item(frame, number, views[len(groups) - 1]))
    if len(groups) != len(views):
        _refuse(f"the answer covers {len(groups)} of {len(views)} Segments")
    return tuple(UnitItems(view=v, items=tuple(g)) for v, g in zip(views, groups, strict=True))


def _frames(body: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for number, line in enumerate(body.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            _refuse(f"line {number} is not JSON")
        if not isinstance(frame, dict):
            _refuse(f"line {number} is not an object")
        out.append(frame)
    return out


def _item(frame: dict[str, Any], number: int, view: ItemView) -> Item:
    kind = frame["t"]
    if kind == "diag":
        return _diag(frame, number, view)
    if kind in {"cover", "cover_empty"}:
        return _cover(frame, number, view)
    try:
        return _DECODERS[kind](frame)
    except (_MalformedError, ValueError, TypeError) as exc:
        return Rejected(row_kind=kind, frame=frame, reason=str(exc))


def _cover(frame: Mapping[str, Any], number: int, view: ItemView) -> Cover:
    lane = frame.get("lane")
    if not isinstance(lane, str):
        _refuse(f"cover frame {number} names no lane")
    if frame["t"] == "cover_empty":
        reason = frame.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            _refuse(f"cover_empty frame {number} gives no reason (GR3)")
        return Cover(lane=lane, cites=(), empty_reason=reason)
    cites = frame.get("cites")
    if not isinstance(cites, list) or not cites or not all(isinstance(c, str) for c in cites):
        _refuse(f"cover frame {number} names no cites; an empty cover is cover_empty")
    stray = [c for c in cites if c not in view.cites]
    if stray:
        _refuse(
            f"cover frame {number} claims {stray[0]!r}, which is not a member of {view.seg}",
            symbol="OW_GRAPH_OUT_OF_SCOPE_BLOCK",
        )
    return Cover(lane=lane, cites=tuple(Cite(c) for c in cites))


def _diag(frame: Mapping[str, Any], number: int, view: ItemView) -> Diag:
    cite = frame.get("cite")
    severity = frame.get("severity")
    detail = frame.get("detail", {})
    if severity not in _SEVERITIES or not isinstance(detail, dict):
        _refuse(f"diag frame {number} is malformed")
    block = view.cites.get(cite) if isinstance(cite, str) else None
    page = frame.get("page")
    return Diag(
        code=str(frame.get("code")),
        severity=severity,
        component=str(frame.get("component")),
        message=str(frame.get("message")),
        page=page if type(page) is int else None,
        block=None if block is None else BlockId(block),
        detail={**detail, **({"cite": cite} if cite is not None else {})},
        fatal=False,
    )


class _MalformedError(Exception):
    """One field of one item frame is wrong. Becomes a `Rejected`, never an exception out."""


def _str(frame: Mapping[str, Any], key: str) -> str:
    value = frame.get(key)
    if not isinstance(value, str):
        raise _MalformedError(f"{key} is not a string")
    return value


def _opt_str(frame: Mapping[str, Any], key: str) -> str | None:
    value = frame.get(key)
    if value is not None and not isinstance(value, str):
        raise _MalformedError(f"{key} is not a string")
    return value


def _opt_float(frame: Mapping[str, Any], key: str) -> float | None:
    value = frame.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _MalformedError(f"{key} is not a number")
    return float(value)


def _trust(frame: Mapping[str, Any]) -> Trust:
    name = frame.get("trust", "ambiguous")
    if name not in _TRUST_NAMES:
        raise _MalformedError(f"trust {name!r} is not a Trust member's name")
    return _TRUST_NAMES[name]


def _scope(frame: Mapping[str, Any]) -> Any:
    scope = frame.get("scope")
    if scope not in _SCOPES:
        raise _MalformedError(f"scope {scope!r} is neither document nor corpus")
    return scope


def _akind(frame: Mapping[str, Any]) -> AnchorKind:
    akind = frame.get("akind")
    if akind not in _AKINDS:
        raise _MalformedError(f"akind {akind!r} is not an AnchorKind member")
    return _AKINDS[akind]


def _literal(
    frame: Mapping[str, Any], key: str, allowed: tuple[str, ...], *, optional: bool = False
) -> Any:
    value = frame.get(key)
    if value is None and optional:
        return None
    if value not in allowed:
        raise _MalformedError(f"{key} {value!r} is not one of {allowed}")
    return value


def _grounded(frame: Mapping[str, Any]) -> Grounded:
    """`cite` plus exactly one of `span` or `quote` (D666 ruling 2)."""
    cite = _str(frame, "cite")
    span, quote = frame.get("span"), frame.get("quote")
    if (span is None) == (quote is None):
        raise _MalformedError("exactly one of span and quote is set")
    if quote is not None:
        if not isinstance(quote, str):
            raise _MalformedError("quote is not a string")
        return (Cite(cite), quote)
    if (
        not isinstance(span, list)
        or len(span) != 2  # noqa: PLR2004 -- a pair
        or not all(type(v) is int for v in span)
    ):
        raise _MalformedError("span is not [ts_a, ts_b]")
    return (Cite(cite), TextSpan(span[0], span[1]))


def _observed(frame: Mapping[str, Any]) -> Grounded:
    observed = frame.get("observed")
    if not isinstance(observed, dict):
        raise _MalformedError("observed is not an object")
    return _grounded(observed)


def _entity(f: Mapping[str, Any]) -> EntityDraft:
    tmp = _opt_str(f, "tmp")
    return EntityDraft(
        key=_str(f, "key"),
        etype=_str(f, "etype"),
        title=_str(f, "title"),
        scope=_scope(f),
        trust_claim=_trust(f),
        raw_etype=_opt_str(f, "raw_etype"),
        description=_opt_str(f, "description"),
        score=_opt_float(f, "score"),
        score_kind=_opt_str(f, "score_kind"),
        tmp=None if tmp is None else TmpRef(tmp),
    )


def _alias(f: Mapping[str, Any]) -> AliasDraft:
    return AliasDraft(
        entity=TmpRef(_str(f, "entity")),
        surface=_str(f, "surface"),
        alias_kind=cast("Any", _str(f, "alias_kind")),
        trust_claim=_trust(f),
    )


def _mention(f: Mapping[str, Any]) -> MentionDraft:
    return MentionDraft(
        entity=TmpRef(_str(f, "entity")),
        at=_grounded(f),
        surface=_str(f, "surface"),
        trust_claim=_trust(f),
        score=_opt_float(f, "score"),
        score_kind=_opt_str(f, "score_kind"),
    )


def _edge(f: Mapping[str, Any]) -> EdgeDraft:
    weight = _opt_float(f, "weight")
    return EdgeDraft(
        src=TmpRef(_str(f, "src")),
        dst=TmpRef(_str(f, "dst")),
        relation=_str(f, "relation"),
        observed=_observed(f),
        trust_claim=_trust(f),
        role=_opt_str(f, "role"),
        weight=1.0 if weight is None else weight,
        score=_opt_float(f, "score"),
        score_kind=_opt_str(f, "score_kind"),
        bound_by=_opt_str(f, "bound_by"),
    )


def _claim(f: Mapping[str, Any]) -> ClaimDraft:
    obj = _opt_str(f, "object_entity")
    return ClaimDraft(
        subject=TmpRef(_str(f, "subject")),
        object_entity=None if obj is None else TmpRef(obj),
        object_literal=_opt_str(f, "object_literal"),
        object_datatype=_opt_str(f, "object_datatype"),
        claim_type=_str(f, "claim_type"),
        predicate=_str(f, "predicate"),
        description=_str(f, "description"),
        status=_literal(f, "status", _CLAIM_STATUSES),
        observed=_observed(f),
        trust_claim=_trust(f),
        t_start=_opt_str(f, "t_start"),
        t_end=_opt_str(f, "t_end"),
        t_precision=_literal(f, "t_precision", _PRECISIONS, optional=True),
        score=_opt_float(f, "score"),
        score_kind=_opt_str(f, "score_kind"),
    )


def _anchor(f: Mapping[str, Any]) -> AnchorDraft:
    return AnchorDraft(
        name=_str(f, "name"),
        akind=_akind(f),
        at=_grounded(f),
        scope=_scope(f),
        surface=_str(f, "surface"),
    )


def _xref(f: Mapping[str, Any]) -> XrefDraft:
    return XrefDraft(
        name=_str(f, "name"), akind=_akind(f), at=_grounded(f), surface=_str(f, "surface")
    )


_DECODERS: Final = {
    "entity": _entity,
    "alias": _alias,
    "mention": _mention,
    "edge": _edge,
    "claim": _claim,
    "anchor": _anchor,
    "xref": _xref,
}


def _refuse(message: str, *, symbol: str = OW_GRAPH_UNPARSED_ITEM) -> NoReturn:
    raise GraphError(f"the Pass's answer is refused: {message}", symbol=symbol, fix=_FIX)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def drive_items(
    connection: sqlite3.Connection,
    unit: UnitItems,
    identity: PassIdentity,
    spend: SpendVector,
) -> RunReport:
    """One `derive_run` for one Segment: every item through the sink, in the driver's order.

    Call inside the store thread's `Unit`; the sink writes through `connection` and the `Unit`'s
    `COMMIT` lands the run and its rows together.
    """
    sink = SqliteGraphSink(connection)
    sink.begin_run(unit.view.ref, identity, frozenset(Cite(c) for c in unit.view.cites))
    for item in unit.items:
        _apply(sink, item)
    return sink.end_run("ok" if unit.has_items else "empty", spend)


def _apply(sink: SqliteGraphSink, item: Item) -> None:
    match item:
        case Rejected():
            sink.quarantine(
                item.row_kind, OW_GRAPH_UNPARSED_ITEM, item.frame, detail={"reason": item.reason}
            )
        case Cover():
            sink.cover(item.lane, item.cites, empty_reason=item.empty_reason)
        case Diag():
            sink.diag(item)
        case EntityDraft():
            sink.entity(item)
        case AliasDraft():
            sink.alias(item)
        case MentionDraft():
            sink.mention(item)
        case EdgeDraft():
            sink.edge(item)
        case ClaimDraft():
            sink.claim(item)
        case AnchorDraft():
            sink.anchor(item)
        case XrefDraft():
            sink.xref(item)
