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

## `--over-merge` (the ledger's D701)

06:1870: *"`ow graph review --over-merge` ranks entities whose `community_member` rows span >= 2
top-level components"*, the detection for *"two people, one name"*.

6. **What spans is the members' own neighbourhoods.** `op.cluster` clusters the heads (D690
   ruling 8), so a closure is in one community per level and its own `community_member` rows
   cannot span two. An edge keeps the durable ids of the two entities it was observed between,
   so each member has its own neighbours; a member *reaches* the top-level community (a live root,
   `parent IS NULL`) of each neighbour's head, its own closure excepted.
7. **A closure is suspect when two members reach disjoint, non-empty sets.** A member that
   reaches both sides is a hub, not evidence of two things. The suspects are ranked by how many
   top-level communities their members reach between them, then by members, then by head.
8. **Each member carries a witness**: the first live block, by id, that mentions it and no other
   member of the closure, since `ow graph split --into` refuses a block naming two (D698 ruling 8).
   `apart` names the first disjoint pair, whose two witnesses are the split to try.
9. **`--over-merge` adds a fifth list, not a mode.** It reads every live edge, so it is asked for;
   the four lists are the same with it or without.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave_core.model.review import (
    OverMerge,
    OverMergeMember,
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


def review(
    connection: sqlite3.Connection, *, limit: int = REVIEW_LIMIT, over_merge: bool = False
) -> Review:
    """Rulings 1-5: four lists, each weakest first, cut at `limit`, with its total; 6-9 with
    `over_merge`."""
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
        **_over_merges(connection, limit) if over_merge else {},
    )


_HEADS: Final = (
    "SELECT entity_id, canonical_id, cite, title, etype, doc_count FROM entity WHERE state = 0"
)
_ROOTS: Final = """
SELECT m.entity_id, c.cite
  FROM community_member AS m JOIN community AS c ON c.community_id = m.community_id
 WHERE c.state = 0 AND c.parent IS NULL
"""
_LIVE_EDGES: Final = """
SELECT g.src_entity, g.dst_entity
  FROM edge AS g JOIN block AS b ON b.block_id = g.observed_block AND b.state = 0
"""
_WITNESSES: Final = """
SELECT m.entity_id, m.block_id, b.cite
  FROM mention AS m JOIN block AS b ON b.block_id = m.block_id
 WHERE m.state = 0
 ORDER BY m.block_id
"""


def _over_merges(connection: sqlite3.Connection, limit: int) -> dict[str, Any]:
    """Rulings 6-8: the suspect closures, ranked, cut at `limit`, with their total."""
    head_of: dict[int, int] = {}
    row_of: dict[int, tuple[str, str, str, int]] = {}
    for entity_id, canonical_id, cite, title, etype, doc_count in connection.execute(_HEADS):
        head_of[int(entity_id)] = int(canonical_id)
        row_of[int(entity_id)] = (str(cite), str(title), str(etype), int(doc_count))
    root_of = {int(e): str(c) for e, c in connection.execute(_ROOTS)}
    reach: dict[int, set[str]] = {}
    for src, dst in connection.execute(_LIVE_EDGES):
        a, b = int(src), int(dst)
        if a not in head_of or b not in head_of or head_of[a] == head_of[b]:
            continue
        for member, neighbour in ((a, b), (b, a)):
            root = root_of.get(head_of[neighbour])
            if root is not None:
                reach.setdefault(member, set()).add(root)
    closures: dict[int, list[int]] = {}
    for entity_id in sorted(head_of):
        closures.setdefault(head_of[entity_id], []).append(entity_id)
    suspects: list[tuple[int, list[int], tuple[int, int]]] = []
    for head, members in closures.items():
        pair = _apart(members, reach)
        if pair is not None:
            suspects.append((head, members, pair))
    suspects.sort(
        key=lambda s: (-len(set().union(*(reach.get(m, set()) for m in s[1]))), -len(s[1]), s[0])
    )
    witness = _witnesses(
        connection, [m for _, members, _ in suspects[:limit] for m in members], head_of
    )
    found = []
    for head, members, (a, b) in suspects[:limit]:
        cite, title, etype, doc_count = row_of[head]
        found.append(
            OverMerge(
                head=cite,
                title=title,
                etype=etype,
                doc_count=doc_count,
                communities=len(set().union(*(reach.get(m, set()) for m in members))),
                members=tuple(
                    OverMergeMember(
                        entity=row_of[m][0],
                        communities=tuple(sorted(reach.get(m, set()))),
                        witness=witness.get(m),
                    )
                    for m in members
                ),
                apart=(row_of[a][0], row_of[b][0]),
            )
        )
    return {"over_merges": tuple(found), "over_merges_total": len(suspects)}


def _apart(members: list[int], reach: dict[int, set[str]]) -> tuple[int, int] | None:
    """Ruling 7: the first two members, in id order, whose reaches are non-empty and disjoint."""
    for index, a in enumerate(members):
        for b in members[index + 1 :]:
            left, right = reach.get(a), reach.get(b)
            if left and right and not left & right:
                return a, b
    return None


def _witnesses(
    connection: sqlite3.Connection, members: list[int], head_of: dict[int, int]
) -> dict[int, str]:
    """Ruling 8: per member, the first live block naming it and no other member of its closure."""
    wanted = set(members)
    named: dict[int, set[int]] = {}
    cites: dict[int, str] = {}
    for entity_id, block_id, cite in connection.execute(_WITNESSES):
        if int(entity_id) in wanted:
            named.setdefault(int(block_id), set()).add(int(entity_id))
            cites[int(block_id)] = str(cite)
    witness: dict[int, str] = {}
    for block_id in sorted(named):
        heads = [head_of[m] for m in named[block_id]]
        for member in named[block_id]:
            if member not in witness and heads.count(head_of[member]) == 1:
                witness[member] = cites[block_id]
    return witness


def _page(connection: sqlite3.Connection, sql: str, limit: int) -> tuple[list[Any], int]:
    """The first `limit` rows of `sql`, and how many it has in all."""
    [(total,)] = connection.execute(f"SELECT count(*) FROM ({sql})").fetchall()  # noqa: S608
    rows = connection.execute(f"{sql} LIMIT ?", (limit,)).fetchall()
    return rows, int(total)
