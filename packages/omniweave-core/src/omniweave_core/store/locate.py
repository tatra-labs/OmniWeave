"""`locate()`'s L3 half: an entity, a claim, an edge or a mention, to one `Locus` per witness. D694.

06-structure-extraction.md section 8 is the specification: *"The path is fixed-length -- `edge ->
edge_evidence -> mention -> block`, then `block.quad`/`page`/`os_*` -- with no search step and no
synthesized geometry (INV-9)."* The last hop, the Block, is `store.doc.locate_block()`, which W7
built for V01-6; this module is the walk above it, and every `Locus` it returns is that function's,
with the witness's span in the block's own text.

## Rulings (the ledger's D694)

1. **An entity is located through its closure.** A cite for a merged-away entity resolves to the
   canonical row (06:281), so `e997` merged into `e412` locates the mentions of both: the entity
   the caller holds is the one an answer showed, and an answer shows the head. Each witness names
   the member it mentions.
2. **Only what is live is a witness of an entity or an edge**: a live mention in a live block. A
   mention named by its own id is located whatever its state, because the caller asked for that
   row, and a retired block still has a page and a quad.
3. **An edge with no `edge_evidence` is located at its own observed span** (`kind = 'edge'`), the
   whole block when it recorded none. 06:203 makes `edge_evidence` *"why locate() returns one Locus
   PER WITNESS"*; an edge a Pass wrote without it still says where it was observed, and a blank
   answer would be the silence INV-9 forbids.
4. **A claim is its own witness**: `observed_block` and its span (06:2122-2123, *"steps 2-3 with
   the claim row substituting for the mention"*).
5. **Witnesses are in reading order**: document, page, the block id (minted in parse order), then
   the span.
6. **`precision` is `block`** for every witness, as `locate_block()` says: narrowing a span to the
   covering line-child Blocks (`line`) or to a glyph run (`char`) is a query this build does not
   run, and 06:2103 makes sub-block precision the query's to compute, never assumed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import NotFoundError
from omniweave_core.model.locus import Located, Witness
from omniweave_core.model.spans import TextSpan
from omniweave_core.store.doc import locate_block

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence

__all__ = ["locate"]

_CITE: Final = re.compile(r"(?P<sigil>[ek]?)(?P<number>\d+)")
"""`e412`, `k9001`, or the bare number. 10:2547: `e` is an entity's sigil and `k` a claim's."""

_ENTITY_SQL: Final = "SELECT entity_id, canonical_id, cite FROM entity WHERE entity_id = ?"
_ENTITY_MENTIONS_SQL: Final = """
SELECT m.mention_id, m.block_id, m.ts_a, m.ts_b, e.cite
  FROM entity AS e
  JOIN mention AS m ON m.entity_id = e.entity_id AND m.state = 0
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
 WHERE e.canonical_id = ? AND e.state IN (0, 1)
 ORDER BY b.doc_ord, b.page, b.block_id, m.ts_a, m.mention_id
"""
_CLAIM_SQL: Final = (
    "SELECT claim_id, cite, observed_block, ts_a, ts_b FROM claim WHERE claim_id = ?"
)
_EDGE_SQL: Final = "SELECT edge_id, observed_block, ts_a, ts_b FROM edge WHERE edge_id = ?"
_EDGE_MENTIONS_SQL: Final = """
SELECT m.mention_id, m.block_id, m.ts_a, m.ts_b, e.cite, v.slot
  FROM edge_evidence AS v
  JOIN mention AS m ON m.mention_id = v.mention_id AND m.state = 0
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
  JOIN entity AS e ON e.entity_id = m.entity_id
 WHERE v.edge_id = ?
 ORDER BY b.doc_ord, b.page, b.block_id, m.ts_a, m.mention_id, v.slot
"""
_MENTION_SQL: Final = """
SELECT m.mention_id, m.block_id, m.ts_a, m.ts_b, e.cite
  FROM mention AS m JOIN entity AS e ON e.entity_id = m.entity_id
 WHERE m.mention_id = ?
"""


def locate(
    connection: sqlite3.Connection,
    *,
    entity: str | None = None,
    claim: str | None = None,
    edge: int | None = None,
    mention: int | None = None,
) -> Located:
    """One `Witness` per place the named row was observed. Exactly one selector is given.

    Raises:
        NotFoundError: the selector names no row (exit 2).
        ValueError: not exactly one selector, or a cite of another kind -- the caller's usage.
    """
    given = [name for name, value in (("entity", entity), ("claim", claim), ("edge", edge),
                                      ("mention", mention)) if value is not None]  # fmt: skip
    if len(given) != 1:
        msg = f"locate takes exactly one of entity, claim, edge and mention; got {given or 'none'}"
        raise ValueError(msg)
    if entity is not None:
        return _entity(connection, entity)
    if claim is not None:
        return _claim(connection, claim)
    if edge is not None:
        return _edge(connection, edge)
    return _mention(connection, int(mention or 0))


def _number(text: str, sigil: str, what: str) -> int:
    found = _CITE.fullmatch(text.strip())
    if found is None or found["sigil"] not in ("", sigil):
        msg = f"{text!r} is not {what} cite: `{sigil}412` or a number"
        raise ValueError(msg)
    return int(found["number"])


def _entity(connection: sqlite3.Connection, ref: str) -> Located:
    row = connection.execute(_ENTITY_SQL, (_number(ref, "e", "an entity"),)).fetchone()
    if row is None:
        raise NotFoundError(f"no entity {ref}", fix="ow query <its name>   # an answer cites it")
    head = connection.execute(_ENTITY_SQL, (int(row[1]),)).fetchone()
    rows = connection.execute(_ENTITY_MENTIONS_SQL, (int(row[1]),)).fetchall()
    witnesses = _witnesses(
        connection, "mention", ((r[0], r[1], r[2], r[3], r[4], None) for r in rows)
    )
    return Located(subject=str(head[2]), witnesses=witnesses)


def _claim(connection: sqlite3.Connection, ref: str) -> Located:
    row = connection.execute(_CLAIM_SQL, (_number(ref, "k", "a claim"),)).fetchone()
    if row is None:
        raise NotFoundError(f"no claim {ref}", fix="ow query <its subject>   # an answer cites it")
    witnesses = _witnesses(connection, "claim", [(row[0], row[2], row[3], row[4], None, None)])
    return Located(subject=str(row[1]), witnesses=witnesses)


def _edge(connection: sqlite3.Connection, edge_id: int) -> Located:
    row = connection.execute(_EDGE_SQL, (edge_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no edge {edge_id}", fix="ow graph locate --entity <an end's cite>")
    rows = connection.execute(_EDGE_MENTIONS_SQL, (edge_id,)).fetchall()
    if rows:
        witnesses = _witnesses(connection, "mention", rows)
    else:  # ruling 3
        witnesses = _witnesses(connection, "edge", [(row[0], row[1], row[2], row[3], None, None)])
    return Located(subject=f"edge {edge_id}", witnesses=witnesses)


def _mention(connection: sqlite3.Connection, mention_id: int) -> Located:
    row = connection.execute(_MENTION_SQL, (mention_id,)).fetchone()
    if row is None:
        raise NotFoundError(
            f"no mention {mention_id}", fix="ow graph locate --entity <the entity's cite>"
        )
    witnesses = _witnesses(connection, "mention", [(*row, None)])
    return Located(subject=f"mention {mention_id}", witnesses=witnesses)


def _witnesses(
    connection: sqlite3.Connection, kind: str, rows: Iterable[Sequence[Any]]
) -> tuple[Witness, ...]:
    """Each `(id, block_id, ts_a, ts_b, entity_cite, slot)` row through `locate_block()`."""
    out: list[Witness] = []
    for row_id, block_id, ts_a, ts_b, cite, slot in rows:
        span = None if ts_a is None or ts_b is None else TextSpan(int(ts_a), int(ts_b))
        locus = locate_block(connection, int(block_id), span=span)
        if locus is None:  # a row whose block the store lost: the FK makes it unreachable
            continue
        text = connection.execute(
            "SELECT text FROM block WHERE block_id = ?", (int(block_id),)
        ).fetchone()
        whole = "" if text is None or text[0] is None else str(text[0])
        out.append(
            Witness(
                kind=kind,
                id=int(row_id),
                slot=None if slot is None else str(slot),
                entity=None if cite is None else str(cite),
                surface=whole[locus.span.a : locus.span.b],
                locus=locus,
            )
        )
    return tuple(out)
