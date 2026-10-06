"""`segmenter`, `segment`, `segment_block`: the host half of `derive.segment.spine`. **D663.**

D662 shipped the driver and ruled its two wire forms: it reads `owgraph-segment/1` in a document
form and prints `segment` frames on `owgraph-items/1`. This module is both ends of that wire on the
host's side, and the only writer of the three tables:

* `build_view` -- one generation's blocks as the document form, in reading order, with the
  `block_sec` paths, the heading texts and the table geometry the segmenter reads.
* `decode_segments` -- the driver's frames, checked against the view they answer. The driver
  addresses blocks by `cite` only (glossary.md `owgraph-segment/1`), so every cite is resolved
  here, and every rule the schema cannot state is checked here.
* `write_segments` -- the rows. Everything the driver did not decide is derived from the members:
  `content_digest` (06:1002), `n_chars`, the pages, the trust and quote minima, the kind mask,
  `restriction_bits` and the layer's `enum_val` code.

## Rulings this module makes (the ledger's D663)

1. **A view carries blocks with text and tables; nothing else.** The segmenter skips every other
   container (D662 reading 1), so sending one would cost bytes and change nothing.
2. **Reading order is the pre-order walk over `parent_id` and `(ord, block_id)`**, the walk
   `sections.plan_sections` already makes. `block_id` order is not reading order once `rebind()`
   has carried a block into a later generation.
3. **The output is refused whole, never trimmed.** A cite outside the view, a block in two
   Segments, a Segment out of reading order or across layers, or a text-bearing block left out
   while its table has no synopsis is `GraphError`, and nothing is written. The segmenter is the
   framework's own and deterministic; a wrong answer from it is a bug to surface, not data to
   quarantine row by row.
4. **A new generation keeps every Segment whose `content_digest` did not move** -- its
   `segment_id`, and so every L3 row hanging off it -- and moves it to the new `gen` and `ord`.
   That is 06 section 10.1 STEP 1's *"S = { Segments whose content_digest moved }"*, made the
   writer's own rule so a re-parse that changes nothing re-bills nothing. A Segment no new one
   matches is retired: `state = 1`, its `segment_block` rows released (the table's key is
   `block_id`, and a carried block must be free to join its new Segment), and `ord` set to
   `-segment_id` so `UNIQUE(doc_ord, gen, ord)` holds when a generation is segmented twice.
   Nothing is deleted from `segment`.
5. **The digest's member order is 06:1002's `(page, ord)`, ties kept in `segment_block.ord`
   order** -- exactly what `ow store verify`'s `segment_digest` clause recomputes, so a store this
   module writes verifies clean.

`import sqlite3` is for the `Connection` type, as in `sections.py`; this module opens no connection
and starts no transaction (07:2717) -- the caller's `Unit` is the transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, NoReturn

from omniweave_core.canonical import ow128, sha256_canonical
from omniweave_core.errors import GraphError
from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model.block import BlockId
from omniweave_core.model.records import Diag

__all__ = [
    "SEGMENT_DOMAIN",
    "DecodedSegments",
    "SegmentDraft",
    "SegmentReport",
    "SegmentView",
    "SegmenterIdentity",
    "build_view",
    "decode_segments",
    "write_segments",
]

SEGMENT_DOMAIN: Final = b"ow.segment.1"
"""06:1002's domain, and `verify.py`'s `_SEGMENT_DOMAIN`."""

_FIX: Final = "ow drivers explain derive.segment.spine"
_TABLE: Final = "table"
_SEVERITIES: Final = frozenset({"error", "warning", "info"})


@dataclass(frozen=True, slots=True)
class SegmenterIdentity:
    """What `segmenter` rows are unique on. `params` are the driver's flat config."""

    driver_id: str
    driver_schema_v: int
    params: Mapping[str, int | float | str | bool]

    def params_digest(self) -> bytes:
        """`sha256_canonical` of the params, as the 32 raw bytes the BLOB column holds."""
        return bytes.fromhex(sha256_canonical(dict(self.params)))


@dataclass(frozen=True, slots=True)
class _Member:
    """One text-bearing block of the view: what a Segment's derived columns are computed from."""

    block_id: int
    cite: str
    position: int
    page: int
    ord: int
    layer: str
    layer_code: int
    kind_code: int
    trust: int
    quote: int
    restriction_bits: int
    content_digest: bytes
    n_chars: int
    table: str | None


@dataclass(frozen=True, slots=True)
class SegmentView:
    """The bytes the driver reads, and the index the decoder resolves its answer against."""

    doc_ord: int
    gen: int
    body: bytes
    members: Mapping[str, _Member]
    tables: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SegmentDraft:
    """One decoded `segment` frame, its cites resolved."""

    layer: str
    atom: str | None
    heading_path: tuple[str, ...]
    members: tuple[_Member, ...]
    n_tokens: int
    tokenizer: str
    synopsis_of: int | None


@dataclass(frozen=True, slots=True)
class DecodedSegments:
    segments: tuple[SegmentDraft, ...]
    diags: tuple[Diag, ...]


@dataclass(frozen=True, slots=True)
class SegmentReport:
    """What `write_segments` did: Segments kept across generations, created, and retired."""

    segmenter_id: int
    kept: int
    created: int
    retired: int
    diags: int


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------

_READ_BLOCKS: Final = (
    "SELECT b.block_id, b.parent_id, b.ord, b.cite, b.kind, b.layer, b.page, b.text, b.label, "
    "b.trust, b.quote, b.restriction_bits, b.content_digest, s.sec_id, s.sec_path "
    "FROM block b LEFT JOIN block_sec s ON s.block_id = b.block_id "
    "WHERE b.doc_ord = ? AND b.gen = ? AND b.state = 0"
)
_READ_TABLES: Final = (
    "SELECT t.block_id, t.n_rows, t.n_cols, t.header_rows FROM table_meta t "
    "JOIN block b ON b.block_id = t.block_id WHERE b.doc_ord = ? AND b.gen = ? AND b.state = 0"
)
_READ_CELLS: Final = (
    "SELECT c.block_id, c.table_id, c.r, c.c FROM cell c "
    "JOIN block b ON b.block_id = c.block_id WHERE b.doc_ord = ? AND b.gen = ? AND b.state = 0"
)


@dataclass(frozen=True, slots=True)
class _Row:
    block_id: int
    parent_id: int | None
    ord: int
    cite: str
    kind: str
    kind_code: int
    layer: str
    layer_code: int
    page: int
    text: str | None
    label: str | None
    trust: int
    quote: int
    restriction_bits: int
    content_digest: bytes
    sec_id: int | None
    sec: str


def build_view(connection: sqlite3.Connection, doc_ord: int, gen: int) -> SegmentView:
    """One generation as `owgraph-segment/1`'s document form (D662), plus the resolving index."""
    kinds = _names(connection, "kind")
    layers = _names(connection, "layer")
    rows = {
        int(r[0]): _Row(
            block_id=int(r[0]),
            parent_id=None if r[1] is None else int(r[1]),
            ord=int(r[2]),
            cite=str(r[3]),
            kind=kinds[int(r[4])],
            kind_code=int(r[4]),
            layer=layers[int(r[5])],
            layer_code=int(r[5]),
            page=int(r[6]),
            text=r[7],
            label=r[8],
            trust=int(r[9]),
            quote=int(r[10]),
            restriction_bits=int(r[11]),
            content_digest=bytes(r[12]),
            sec_id=None if r[13] is None else int(r[13]),
            sec=str(r[14]) if r[14] is not None else "/",
        )
        for r in connection.execute(_READ_BLOCKS, (doc_ord, gen))
    }
    grids = {
        int(r[0]): (int(r[1]), int(r[2]), int(r[3]))
        for r in connection.execute(_READ_TABLES, (doc_ord, gen))
    }
    cells = {
        int(r[0]): (int(r[1]), int(r[2]), int(r[3]))
        for r in connection.execute(_READ_CELLS, (doc_ord, gen))
    }
    sections = {
        row.sec: (row.text if row.text is not None else row.label or "")
        for row in rows.values()
        if row.sec_id == row.block_id and row.sec != "/"
    }

    shown = [row for row in _reading_order(rows) if row.text is not None or row.block_id in grids]
    defaults = {
        key: Counter(getattr(row, key) for row in shown).most_common(1)[0][0] if shown else fallback
        for key, fallback in (("layer", "body"), ("page", 0), ("sec", "/"))
    }
    frames: list[dict[str, Any]] = [
        {
            "t": "doc",
            "doc": f"d{doc_ord}",
            "sections": dict(sorted(sections.items())),
            "defaults": defaults,
        }
    ]
    members: dict[str, _Member] = {}
    tables: dict[str, int] = {}
    for row in shown:
        frame: dict[str, Any] = {"t": "block", "cite": row.cite, "kind": row.kind}
        frame.update(
            {key: getattr(row, key) for key in defaults if getattr(row, key) != defaults[key]}
        )
        table: str | None = None
        if row.block_id in grids:
            n_rows, n_cols, header_rows = grids[row.block_id]
            frame["grid"] = {"n_rows": n_rows, "n_cols": n_cols, "header_rows": header_rows}
            tables[row.cite] = row.block_id
        if row.block_id in cells and cells[row.block_id][0] in rows:
            table_id, r, c = cells[row.block_id]
            table = rows[table_id].cite
            frame["table"] = {"table_cite": table, "r": r, "c": c}
        if row.text is not None:
            frame["text"] = row.text
            members[row.cite] = _Member(
                block_id=row.block_id,
                cite=row.cite,
                position=len(members),
                page=row.page,
                ord=row.ord,
                layer=row.layer,
                layer_code=row.layer_code,
                kind_code=row.kind_code,
                trust=row.trust,
                quote=row.quote,
                restriction_bits=row.restriction_bits,
                content_digest=row.content_digest,
                n_chars=len(row.text),
                table=table,
            )
        frames.append(frame)
    body = "".join(json.dumps(f, separators=(",", ":"), ensure_ascii=False) + "\n" for f in frames)
    return SegmentView(
        doc_ord=doc_ord, gen=gen, body=body.encode("utf-8"), members=members, tables=tables
    )


def _reading_order(rows: Mapping[int, _Row]) -> list[_Row]:
    """Pre-order over `parent_id`, siblings by `(ord, block_id)`, roots by `(page, ord, block_id)`.

    A parent outside the generation makes its child a root, as `sections._child_lists` does, so a
    damaged tree loses no block from the view.
    """
    children: dict[int | None, list[_Row]] = {}
    for row in rows.values():
        parent = row.parent_id if row.parent_id in rows else None
        children.setdefault(parent, []).append(row)
    for parent, kids in children.items():
        kids.sort(
            key=(lambda r: (r.page, r.ord, r.block_id))
            if parent is None
            else (lambda r: (r.ord, r.block_id))
        )
    out: list[_Row] = []
    seen: set[int] = set()
    work = list(reversed(children.get(None, [])))
    while work:
        row = work.pop()
        if row.block_id in seen:
            continue
        seen.add(row.block_id)
        out.append(row)
        work.extend(reversed(children.get(row.block_id, [])))
    return out


def _names(connection: sqlite3.Connection, domain: str) -> Mapping[int, str]:
    """`{ord: name}` for one `enum_val` domain, off the store's own seed (as `sections.py`)."""
    return {
        int(o): str(n)
        for n, o in connection.execute("SELECT name, ord FROM enum_val WHERE domain = ?", (domain,))
    }


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


def decode_segments(body: bytes, view: SegmentView) -> DecodedSegments:
    """The driver's `owgraph-items/1`, checked against `view`. Refused whole on any violation."""
    frames = _frames(body)
    if not frames or frames[0] != {"t": "doc", "doc": f"d{view.doc_ord}"}:
        _refuse(f"the answer must open with the doc frame of d{view.doc_ord}")
    segments: list[SegmentDraft] = []
    diags: list[Diag] = []
    placed: set[str] = set()
    for number, frame in enumerate(frames[1:], start=2):
        kind = frame.get("t")
        if kind == "segment":
            segments.append(_segment(frame, number, view, placed))
        elif kind == "diag":
            diags.append(_diag(frame, number, view))
        else:
            _refuse(f"frame {number} is {kind!r}; this answer carries segment and diag frames only")
    summarised = {s.synopsis_of for s in segments if s.synopsis_of is not None}
    for cite, member in view.members.items():
        if cite not in placed and (
            member.table is None or view.tables[member.table] not in summarised
        ):
            _refuse(
                f"{cite} is in no Segment and its table, if any, has no synopsis",
                symbol="OW_GRAPH_COVERED_GROUND",
            )
    return DecodedSegments(tuple(segments), tuple(diags))


def _frames(body: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for number, line in enumerate(body.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            _refuse(f"frame {number} is not JSON")
        if not isinstance(frame, dict):
            _refuse(f"frame {number} is not an object")
        out.append(frame)
    return out


def _segment(
    frame: Mapping[str, Any], number: int, view: SegmentView, placed: set[str]
) -> SegmentDraft:
    cites = frame.get("blocks")
    if not isinstance(cites, list) or not cites or not all(isinstance(c, str) for c in cites):
        _refuse(f"segment frame {number} names no blocks")
    if len(cites) > MAX_SEGMENT_BLOCKS - 1:
        _refuse(
            f"segment frame {number} has {len(cites)} blocks; a Segment holds "
            f"{MAX_SEGMENT_BLOCKS - 1}"
        )
    members: list[_Member] = []
    for cite in cites:
        member = view.members.get(cite)
        if member is None:
            _refuse(
                f"segment frame {number} names {cite!r}, which is no text block of the view",
                symbol="OW_GRAPH_OUT_OF_SCOPE_BLOCK",
            )
        if cite in placed:
            _refuse(f"{cite} is in two Segments; overlap is unrepresentable (segment_block's key)")
        if members and member.position <= members[-1].position:
            _refuse(f"segment frame {number} lists {cite} out of reading order")
        placed.add(cite)
        members.append(member)
    layer = frame.get("layer")
    if any(m.layer != layer for m in members):
        _refuse(f"segment frame {number} says layer {layer!r} and its members disagree")
    atom = frame.get("atom")
    if atom not in {None, _TABLE}:
        _refuse(f"segment frame {number} has atom {atom!r}")
    synopsis = frame.get("synopsis_of")
    if synopsis is not None and (synopsis not in view.tables or atom != _TABLE):
        _refuse(
            f"segment frame {number} is a synopsis of {synopsis!r}, which is no table of the view"
        )
    path = frame.get("heading_path")
    tokens = frame.get("n_tokens")
    tokenizer = frame.get("tokenizer")
    if not isinstance(path, list) or not all(isinstance(p, str) for p in path):
        _refuse(f"segment frame {number}: heading_path is not a list of strings")
    if type(tokens) is not int or tokens < 0:
        _refuse(f"segment frame {number}: n_tokens is not a count")
    if not isinstance(tokenizer, str) or not tokenizer:
        _refuse(f"segment frame {number} names no tokenizer")
    return SegmentDraft(
        layer=str(layer),
        atom=atom,
        heading_path=tuple(path),
        members=tuple(members),
        n_tokens=tokens,
        tokenizer=tokenizer,
        synopsis_of=None if synopsis is None else view.tables[synopsis],
    )


def _diag(frame: Mapping[str, Any], number: int, view: SegmentView) -> Diag:
    cite = frame.get("cite")
    block: int | None = None
    if cite is not None:
        if cite in view.members:
            block = view.members[cite].block_id
        elif cite in view.tables:
            block = view.tables[cite]
        else:
            _refuse(
                f"diag frame {number} names {cite!r}, which is not in the view",
                symbol="OW_GRAPH_DANGLING_CITE",
            )
    severity = frame.get("severity")
    detail = frame.get("detail", {})
    if severity not in _SEVERITIES or not isinstance(detail, dict):
        _refuse(f"diag frame {number} is malformed")
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


def _refuse(message: str, *, symbol: str = "OW_GRAPH") -> NoReturn:
    raise GraphError(
        f"derive.segment.spine's answer is refused: {message}", symbol=symbol, fix=_FIX
    )


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------

_INSERT_SEGMENT: Final = (
    "INSERT INTO segment(doc_ord, gen, ord, segmenter_id, layer, atom, heading_path, n_blocks, "
    "n_tokens, n_chars, tokenizer_id, first_page, last_page, trust, quote_min, kind_mask, "
    "restriction_bits, content_digest, origin_operator, origin_driver, driver_schema_v, "
    "synopsis_of) VALUES(:doc_ord, :gen, :ord, :segmenter_id, :layer, :atom, :heading_path, "
    ":n_blocks, :n_tokens, :n_chars, :tokenizer_id, :first_page, :last_page, :trust, :quote_min, "
    ":kind_mask, :restriction_bits, :content_digest, :origin_operator, :origin_driver, "
    ":driver_schema_v, :synopsis_of)"
)
_UPDATE_SEGMENT: Final = (
    "UPDATE segment SET gen = :gen, ord = :ord, segmenter_id = :segmenter_id, layer = :layer, "
    "atom = :atom, heading_path = :heading_path, n_blocks = :n_blocks, n_tokens = :n_tokens, "
    "n_chars = :n_chars, tokenizer_id = :tokenizer_id, first_page = :first_page, "
    "last_page = :last_page, trust = :trust, quote_min = :quote_min, kind_mask = :kind_mask, "
    "restriction_bits = :restriction_bits, origin_operator = :origin_operator, "
    "origin_driver = :origin_driver, driver_schema_v = :driver_schema_v, "
    "synopsis_of = :synopsis_of WHERE segment_id = :segment_id"
)
_DIAG_INSERT: Final = (
    "INSERT INTO diag(doc_ord, gen, page, block_id, part, code, severity, component, message, "
    "detail, fatal) VALUES(?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 0)"
)


def write_segments(
    connection: sqlite3.Connection,
    view: SegmentView,
    identity: SegmenterIdentity,
    decoded: DecodedSegments,
    *,
    origin_operator: str,
) -> SegmentReport:
    """Write one document's Segments for `view.gen`, keeping every one whose digest held."""
    doc_ord, gen = view.doc_ord, view.gen
    params_digest = identity.params_digest()
    connection.execute(
        "INSERT OR IGNORE INTO segmenter(driver_id, driver_schema_v, params_digest) "
        "VALUES(?, ?, ?)",
        (identity.driver_id, identity.driver_schema_v, params_digest),
    )
    segmenter_id = int(
        connection.execute(
            "SELECT segmenter_id FROM segmenter "
            "WHERE driver_id = ? AND driver_schema_v = ? AND params_digest = ?",
            (identity.driver_id, identity.driver_schema_v, params_digest),
        ).fetchone()[0]
    )
    pool: dict[bytes, list[int]] = {}
    for segment_id, digest in connection.execute(
        "SELECT segment_id, content_digest FROM segment "
        "WHERE doc_ord = ? AND state = 0 ORDER BY gen, ord",
        (doc_ord,),
    ):
        pool.setdefault(bytes(digest), []).append(int(segment_id))
    live = [s for ids in pool.values() for s in ids]
    _release(connection, live)

    kept = created = 0
    for ord_, draft in enumerate(decoded.segments):
        digest = _digest(identity, params_digest, draft)
        values = _columns(
            draft,
            doc_ord=doc_ord,
            gen=gen,
            ord_=ord_,
            segmenter_id=segmenter_id,
            identity=identity,
            origin_operator=origin_operator,
        )
        reuse = pool.get(digest)
        if reuse:
            segment_id = reuse.pop(0)
            connection.execute(_UPDATE_SEGMENT, {**values, "segment_id": segment_id})
            kept += 1
        else:
            cursor = connection.execute(_INSERT_SEGMENT, {**values, "content_digest": digest})
            segment_id = int(cursor.lastrowid or 0)
            created += 1
        connection.executemany(
            "INSERT INTO segment_block(block_id, segment_id, ord) VALUES(?, ?, ?)",
            [(m.block_id, segment_id, k) for k, m in enumerate(draft.members)],
        )
    retired = [s for ids in pool.values() for s in ids]
    connection.executemany(
        "UPDATE segment SET state = 1 WHERE segment_id = ?", [(s,) for s in retired]
    )

    connection.execute(
        "DELETE FROM diag WHERE doc_ord = ? AND gen = ? AND component = ?",
        (doc_ord, gen, identity.driver_id),
    )
    connection.executemany(
        _DIAG_INSERT,
        [
            (
                doc_ord,
                gen,
                d.page,
                d.block,
                d.code,
                d.severity,
                d.component,
                d.message,
                json.dumps(dict(d.detail), sort_keys=True, separators=(",", ":")),
            )
            for d in decoded.diags
        ],
    )
    return SegmentReport(
        segmenter_id=segmenter_id,
        kept=kept,
        created=created,
        retired=len(retired),
        diags=len(decoded.diags),
    )


def _release(connection: sqlite3.Connection, segment_ids: Sequence[int]) -> None:
    """Park every live Segment of the document at `ord = -segment_id` and free its blocks.

    Both are what lets a block carried into the new generation join its new Segment, and a
    Segment kept across generations take its new `ord`, without tripping `segment_block`'s key or
    `UNIQUE(doc_ord, gen, ord)` halfway through the rewrite.
    """
    connection.executemany(
        "UPDATE segment SET ord = -segment_id WHERE segment_id = ?", [(s,) for s in segment_ids]
    )
    connection.executemany(
        "DELETE FROM segment_block WHERE segment_id = ?", [(s,) for s in segment_ids]
    )


def _digest(identity: SegmenterIdentity, params_digest: bytes, draft: SegmentDraft) -> bytes:
    """06:1002, with `verify.py`'s member order: `(page, ord)`, ties in `segment_block.ord`."""
    members = sorted(draft.members, key=lambda m: (m.page, m.ord))
    return ow128(
        SEGMENT_DOMAIN,
        [
            identity.driver_id,
            identity.driver_schema_v,
            params_digest.hex(),
            list(draft.heading_path),
            [m.content_digest.hex() for m in members],
        ],
    )


def _columns(
    draft: SegmentDraft,
    *,
    doc_ord: int,
    gen: int,
    ord_: int,
    segmenter_id: int,
    identity: SegmenterIdentity,
    origin_operator: str,
) -> dict[str, Any]:
    members = draft.members
    kind_mask = 0
    restriction = 0
    for m in members:
        kind_mask |= 1 << m.kind_code
        restriction |= m.restriction_bits
    return {
        "doc_ord": doc_ord,
        "gen": gen,
        "ord": ord_,
        "segmenter_id": segmenter_id,
        "layer": members[0].layer_code,
        "atom": draft.atom,
        "heading_path": json.dumps(
            list(draft.heading_path), ensure_ascii=False, separators=(",", ":")
        ),
        "n_blocks": len(members),
        "n_tokens": draft.n_tokens,
        "n_chars": sum(m.n_chars for m in members),
        "tokenizer_id": draft.tokenizer,
        "first_page": min(m.page for m in members),
        "last_page": max(m.page for m in members),
        "trust": min(m.trust for m in members),
        "quote_min": min(m.quote for m in members),
        "kind_mask": kind_mask,
        "restriction_bits": restriction,
        "origin_operator": origin_operator,
        "origin_driver": identity.driver_id,
        "driver_schema_v": identity.driver_schema_v,
        "synopsis_of": draft.synopsis_of,
    }
