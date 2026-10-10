"""The graph's review surface: what it holds below `EXTRACTED`, weakest first. D700.

06:85-87 is the specification -- the `entity_review`/`mention_review`/`edge_review` partial indexes
(`WHERE trust < 2 OR taint <> 0`) *"are the review surface and work while `trust` is still
uncalibrated"* -- and `model.review` the types. 06:90-92 orders it: graphify's
`order = {AMBIGUOUS: 0, INFERRED: 1, EXTRACTED: 2}`, *"the ordering of the review surface and never
a retrieval ranking term"*.

## Rulings (the ledger's D700)

1. **Resolution is reviewed by closure, not by entity.** `entity_review`'s `resolution_trust < 2`
   holds for every entity in no merge, whose `AMBIGUOUS` is the `MIN` of no rows (D684 ruling 6)
   and not a judgement. So the closure half is the closures of two or more live members whose
   resolution is below `EXTRACTED` -- *"one fuzzy merge anywhere makes the whole cluster's
   resolution `INFERRED`"* (06:1858) -- one line per closure, named by its head.
2. **The entity half is `entity_review`'s other clause and the overloaded.** A live entity with
   `taint <> 0`, and every overloaded one (06:171, `OW_GRAPH_ENTITY_OVERLOADED`), overloaded
   first, because an overloaded entity has left resolution and is the one a reader must act on.
3. **Mentions and edges are their indexes' predicates exactly, over live rows**: a mention whose
   `state` is 0, and an edge whose observed block is live -- `op.cluster`'s reading (D690 ruling 8).
   An edge's ends are its own cites, not their heads: the edge was observed between those two.
4. **Weakest first** (06:90-92): trust ascending, then taint descending, a tainted row before a
   clean one of the same trust, then an edge's relation, then the row's id so the order is total.
5. **Each list is cut at `REVIEW_LIMIT` and carries its total**, counted separately, as
   `store.graph_residue` does (INV-25's ceilings).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave_core.model.review import (
    Review,
    ReviewClosure,
    ReviewEdge,
    ReviewEntity,
    ReviewMention,
)
from omniweave_core.store.inspect import DEFAULT_GROUP_LIMIT

if TYPE_CHECKING:
    import sqlite3

__all__ = ["REVIEW_LIMIT", "review"]

REVIEW_LIMIT: Final = DEFAULT_GROUP_LIMIT
"""Rows per list. `ow store residue`'s ceiling, for the same reason (INV-25)."""

_CLOSURES: Final = """
SELECT h.cite, h.title, h.etype, count(*) AS members, h.resolution_trust
  FROM entity AS e JOIN entity AS h ON h.entity_id = e.canonical_id
 WHERE e.state = 0 AND h.resolution_trust < 2
 GROUP BY h.entity_id
HAVING count(*) >= 2
 ORDER BY h.resolution_trust, members DESC, h.entity_id
"""
_ENTITIES: Final = """
SELECT cite, title, etype, trust, taint, state = 1 AS overloaded
  FROM entity
 WHERE state = 1 OR (state = 0 AND taint <> 0)
 ORDER BY overloaded DESC, trust, taint DESC, entity_id
"""
_MENTIONS: Final = """
SELECT m.mention_id, e.cite, b.cite, m.surface, m.trust, m.taint
  FROM mention AS m
  JOIN entity AS e ON e.entity_id = m.entity_id
  JOIN block AS b ON b.block_id = m.block_id
 WHERE m.state = 0 AND (m.trust < 2 OR m.taint <> 0)
 ORDER BY m.trust, m.taint DESC, m.mention_id
"""
_EDGES: Final = """
SELECT g.edge_id, s.cite, t.cite, g.relation, b.cite, g.trust, g.taint
  FROM edge AS g
  JOIN block AS b ON b.block_id = g.observed_block AND b.state = 0
  JOIN entity AS s ON s.entity_id = g.src_entity
  JOIN entity AS t ON t.entity_id = g.dst_entity
 WHERE g.trust < 2 OR g.taint <> 0
 ORDER BY g.trust, g.taint DESC, g.relation, g.edge_id
"""


def review(connection: sqlite3.Connection, *, limit: int = REVIEW_LIMIT) -> Review:
    """Rulings 1-5: four lists, each weakest first, cut at `limit`, with its total."""
    closures, closures_total = _page(connection, _CLOSURES, limit)
    entities, entities_total = _page(connection, _ENTITIES, limit)
    mentions, mentions_total = _page(connection, _MENTIONS, limit)
    edges, edges_total = _page(connection, _EDGES, limit)
    return Review(
        limit=limit,
        closures=tuple(
            ReviewClosure(
                head=str(head),
                title=str(title),
                etype=str(etype),
                members=int(n),
                resolution_trust=int(trust),
            )
            for head, title, etype, n, trust in closures
        ),
        closures_total=closures_total,
        entities=tuple(
            ReviewEntity(
                entity=str(cite),
                title=str(title),
                etype=str(etype),
                trust=int(trust),
                taint=int(taint),
                overloaded=bool(overloaded),
            )
            for cite, title, etype, trust, taint, overloaded in entities
        ),
        entities_total=entities_total,
        mentions=tuple(
            ReviewMention(
                mention=int(mention),
                entity=str(entity),
                cite=str(cite),
                surface=str(surface),
                trust=int(trust),
                taint=int(taint),
            )
            for mention, entity, cite, surface, trust, taint in mentions
        ),
        mentions_total=mentions_total,
        edges=tuple(
            ReviewEdge(
                edge=int(edge),
                src=str(src),
                dst=str(dst),
                relation=str(relation),
                cite=str(cite),
                trust=int(trust),
                taint=int(taint),
            )
            for edge, src, dst, relation, cite, trust, taint in edges
        ),
        edges_total=edges_total,
    )


def _page(connection: sqlite3.Connection, sql: str, limit: int) -> tuple[list[Any], int]:
    """The first `limit` rows of `sql`, and how many it has in all."""
    [(total,)] = connection.execute(f"SELECT count(*) FROM ({sql})").fetchall()  # noqa: S608
    rows = connection.execute(f"{sql} LIMIT ?", (limit,)).fetchall()
    return rows, int(total)
