"""The reverse walk: one block to every entity, edge and claim observed in it. D695.

06:2119-2121 is the specification, and `model.observed` the types. One block id in, three reads out,
each an index range scan: `mention_block` on `(block_id, ts_a)` for the mentions, `edge_obs` on
`observed_block` for the edges, and `claim.observed_block` for the claims.

## Rulings (the ledger's D695)

1. **Mentions are the live ones**, as `graph.locate` reads them (D694 ruling 2): a retired mention
   no longer says the block asserts anything. Each names its entity and that entity's head.
2. **Edges and claims are every row observed here**, whatever their ends' state: an edge or a
   claim has no state of its own, and a reader asking what a block asserted is owed every row that
   says it was this block.
3. **In span order**, then by id, so a paragraph reads left to right.
4. **An edge's span is `None` when it recorded none**: the whole block observed it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_core.model.observed import Observed, ObservedClaim, ObservedEdge, ObservedMention

if TYPE_CHECKING:
    import sqlite3

__all__ = ["observed"]

_CITE_SQL: Final = "SELECT cite, text FROM block WHERE block_id = ?"
_MENTIONS_SQL: Final = """
SELECT m.mention_id, e.cite, h.cite, e.etype, e.key, m.ts_a, m.ts_b, m.trust
  FROM mention AS m
  JOIN entity AS e ON e.entity_id = m.entity_id
  JOIN entity AS h ON h.entity_id = e.canonical_id
 WHERE m.block_id = ? AND m.state = 0
 ORDER BY m.ts_a, m.ts_b, m.mention_id
"""
_EDGES_SQL: Final = """
SELECT g.edge_id, s.cite, t.cite, g.relation, g.ts_a, g.ts_b, g.trust
  FROM edge AS g
  JOIN entity AS s ON s.entity_id = g.src_entity
  JOIN entity AS t ON t.entity_id = g.dst_entity
 WHERE g.observed_block = ?
 ORDER BY IFNULL(g.ts_a, -1), g.edge_id
"""
_CLAIMS_SQL: Final = """
SELECT c.cite, s.cite, c.claim_type, c.predicate, COALESCE(o.cite, c.object_literal), c.status,
       c.ts_a, c.ts_b, c.trust
  FROM claim AS c
  JOIN entity AS s ON s.entity_id = c.subject_entity
  LEFT JOIN entity AS o ON o.entity_id = c.object_entity
 WHERE c.observed_block = ?
 ORDER BY c.ts_a, c.claim_id
"""


def observed(connection: sqlite3.Connection, block_id: int) -> Observed | None:
    """What the graph says was asserted in one block, or `None` when there is no such block."""
    row = connection.execute(_CITE_SQL, (block_id,)).fetchone()
    if row is None:
        return None
    text = "" if row[1] is None else str(row[1])
    mentions = tuple(
        ObservedMention(
            mention=int(r[0]),
            entity=str(r[1]),
            head=str(r[2]),
            etype=str(r[3]),
            key=str(r[4]),
            span=(int(r[5]), int(r[6])),
            surface=text[int(r[5]) : int(r[6])],
            trust=int(r[7]),
        )
        for r in connection.execute(_MENTIONS_SQL, (block_id,)).fetchall()
    )
    edges = tuple(
        ObservedEdge(
            edge=int(r[0]),
            src=str(r[1]),
            dst=str(r[2]),
            relation=str(r[3]),
            span=None if r[4] is None or r[5] is None else (int(r[4]), int(r[5])),
            trust=int(r[6]),
        )
        for r in connection.execute(_EDGES_SQL, (block_id,)).fetchall()
    )
    claims = tuple(
        ObservedClaim(
            claim=str(r[0]),
            subject=str(r[1]),
            claim_type=str(r[2]),
            predicate=str(r[3]),
            object=str(r[4]),
            status=str(r[5]),
            span=(int(r[6]), int(r[7])),
            trust=int(r[8]),
        )
        for r in connection.execute(_CLAIMS_SQL, (block_id,)).fetchall()
    )
    return Observed(cite=str(row[0]), mentions=mentions, edges=edges, claims=claims)
