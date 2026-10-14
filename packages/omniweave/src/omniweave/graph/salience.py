"""STEP 7: salience over each canonical closure, all four columns, and GR16's recount. D692.

06-structure-extraction.md section 1.5 and STEP 7 of section 10.1 are the specification, and GR16
(charter.md:5673) the gate: *"A post-run assertion FAILS THE RUN when `entity.degree`, `frequency`,
`doc_count` or `edge.combined_degree` disagree with a recount."*

- `entity.frequency` is `COUNT(DISTINCT mention.segment_id)` -- corpus salience;
- `entity.degree` is edge degree -- graph salience;
- `entity.doc_count` is corpus spread, the documents a name is mentioned in;
- `edge.combined_degree` is `src.degree + dst.degree`, the edge prior.

The first three are computed over the whole `canonical_id` closure and stamped on every member, so
any member row is a usable answer and `entity_rank` cannot rank cluster fragments (06:270).

## Rulings (the ledger's D692)

1. **What counts is what is live.** A mention counts while it is live and its block is live. An
   edge counts while its observed block is live and both its ends are entities that are not
   retired; each end is read as its `canonical_id`, as `op.cluster` reads it (D690 ruling 8). An
   overloaded entity (`state = 1`) is counted and stamped: `op.resolve` decides overload ON these
   numbers (06:165), so they must not stop at the decision.
2. **`degree` is the number of distinct other closures an edge joins this one to**: the closure's
   degree in the folded simple graph, graphrag's node degree over unique `(source, target)`
   relationships. Two edges to one neighbour are one, and an edge inside one closure (a loop after
   a merge) is none.
3. **`combined_degree` is per edge row**, the sum of its two ends' closure degrees, and 0 for an
   edge that does not count (a retired block or a retired end): it joins nothing live.
4. **A retired entity (`state = 2`) keeps its last numbers.** Its rows are history; a retirement
   zeroing them would erase what it last held.
5. **Only what differs is written,** so an unchanged corpus writes nothing (the property
   `test_free_passes_at_ingest` asserts of every pass).
6. **GR16's recount is SQL, the write is Python,** so the assertion is two derivations agreeing and
   not one derivation read back. A disagreement raises `InternalError`: it is this code's bug, and
   the run must fail rather than ship a ranking it cannot reproduce.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final

from omniweave_core.errors import InternalError

__all__ = ["SalienceReport", "check", "recount", "recount_and_check"]

_REPORT_FIX: Final = (
    "ow doctor --deep --render json   # attach the report: this is an omniweave bug"
)
_HEADS_SQL: Final = "SELECT entity_id, canonical_id FROM entity WHERE state IN (0, 1)"
_STORED_SQL: Final = (
    "SELECT entity_id, frequency, degree, doc_count FROM entity WHERE state IN (0, 1)"
)
_MENTIONS_SQL: Final = """
SELECT e.canonical_id, COUNT(DISTINCT m.segment_id), COUNT(DISTINCT b.doc_ord)
  FROM mention AS m
  JOIN entity AS e ON e.entity_id = m.entity_id AND e.state IN (0, 1)
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
 WHERE m.state = 0
 GROUP BY e.canonical_id
"""
_EDGES_SQL: Final = """
SELECT g.edge_id, g.src_entity, g.dst_entity, g.combined_degree, b.state
  FROM edge AS g LEFT JOIN block AS b ON b.block_id = g.observed_block
"""
_ENTITY_SQL: Final = """
UPDATE entity SET frequency = :frequency, degree = :degree, doc_count = :doc_count
 WHERE entity_id = :entity_id
"""
_EDGE_SQL: Final = "UPDATE edge SET combined_degree = :combined WHERE edge_id = :edge_id"

_RECOUNT_SQL: Final = """
WITH live AS (
  SELECT entity_id, canonical_id FROM entity WHERE state IN (0, 1)
), mentions AS (
  SELECT l.canonical_id AS head, COUNT(DISTINCT m.segment_id) AS frequency,
         COUNT(DISTINCT b.doc_ord) AS doc_count
    FROM mention AS m
    JOIN live AS l ON l.entity_id = m.entity_id
    JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
   WHERE m.state = 0
   GROUP BY l.canonical_id
), ends AS (
  SELECT s.canonical_id AS a, t.canonical_id AS b
    FROM edge AS g
    JOIN block AS k ON k.block_id = g.observed_block AND k.state = 0
    JOIN live AS s ON s.entity_id = g.src_entity
    JOIN live AS t ON t.entity_id = g.dst_entity
   WHERE s.canonical_id <> t.canonical_id
), pairs AS (
  SELECT a AS head, b AS other FROM ends UNION SELECT b, a FROM ends
), degrees AS (
  SELECT head, COUNT(*) AS degree FROM pairs GROUP BY head
)
SELECT 'entity', l.entity_id,
       IFNULL(m.frequency, 0) || ',' || IFNULL(d.degree, 0) || ',' || IFNULL(m.doc_count, 0),
       e.frequency || ',' || e.degree || ',' || e.doc_count
  FROM live AS l
  JOIN entity AS e ON e.entity_id = l.entity_id
  LEFT JOIN mentions AS m ON m.head = l.canonical_id
  LEFT JOIN degrees AS d ON d.head = l.canonical_id
UNION ALL
SELECT 'edge', g.edge_id,
       CASE WHEN k.state = 0 AND s.entity_id IS NOT NULL AND t.entity_id IS NOT NULL
            THEN IFNULL(ds.degree, 0) + IFNULL(dt.degree, 0) ELSE 0 END,
       g.combined_degree
  FROM edge AS g
  LEFT JOIN block AS k ON k.block_id = g.observed_block
  LEFT JOIN live AS s ON s.entity_id = g.src_entity
  LEFT JOIN live AS t ON t.entity_id = g.dst_entity
  LEFT JOIN degrees AS ds ON ds.head = s.canonical_id
  LEFT JOIN degrees AS dt ON dt.head = t.canonical_id
"""
"""Ruling 6: the same four numbers as `recount()` writes, derived in SQL."""


@dataclass(frozen=True, slots=True)
class SalienceReport:
    """One STEP 7 pass, for `IngestReport`."""

    closures: int
    entities: int
    """Entity rows whose numbers this pass wrote."""
    edges: int
    """Edge rows whose `combined_degree` this pass wrote."""

    @property
    def moved(self) -> bool:
        return bool(self.entities or self.edges)

    def line(self) -> str:
        return (
            f"  salience  {self.closures} closure(s): {self.entities} entity row(s) and "
            f"{self.edges} edge row(s) recounted"
        )


def recount(connection: Any) -> SalienceReport:
    """Compute the four columns (rulings 1-4) and write the ones that differ (5)."""
    canonical = {int(e): int(c) for e, c in connection.execute(_HEADS_SQL).fetchall()}
    counted: dict[int, tuple[int, int]] = {
        int(head): (int(frequency), int(docs))
        for head, frequency, docs in connection.execute(_MENTIONS_SQL).fetchall()
    }
    neighbours: dict[int, set[int]] = defaultdict(set)
    edges = connection.execute(_EDGES_SQL).fetchall()
    for _edge_id, src, dst, _combined, block_state in edges:
        a, b = canonical.get(int(src)), canonical.get(int(dst))
        if block_state != 0 or a is None or b is None or a == b:
            continue
        neighbours[a].add(b)
        neighbours[b].add(a)
    stored = {
        int(r[0]): (int(r[1]), int(r[2]), int(r[3]))
        for r in connection.execute(_STORED_SQL).fetchall()
    }
    entities = 0
    for entity_id, head in sorted(canonical.items()):
        frequency, docs = counted.get(head, (0, 0))
        wanted = (frequency, len(neighbours.get(head, ())), docs)
        if stored.get(entity_id) != wanted:
            connection.execute(
                _ENTITY_SQL,
                {
                    "entity_id": entity_id,
                    "frequency": wanted[0],
                    "degree": wanted[1],
                    "doc_count": wanted[2],
                },
            )
            entities += 1
    written = 0
    for edge_id, src, dst, combined, block_state in edges:
        a, b = canonical.get(int(src)), canonical.get(int(dst))
        counts = block_state == 0 and a is not None and b is not None
        wanted_edge = (
            len(neighbours.get(a, ())) + len(neighbours.get(b, ()))
            if counts and a is not None and b is not None
            else 0
        )
        if int(combined) != wanted_edge:
            connection.execute(_EDGE_SQL, {"edge_id": int(edge_id), "combined": wanted_edge})
            written += 1
    return SalienceReport(closures=len(set(canonical.values())), entities=entities, edges=written)


def check(connection: Any) -> None:
    """GR16: every stored column against an SQL recount (ruling 6).

    Raises:
        InternalError: the first row whose stored numbers disagree with the recount.
    """
    for kind, row_id, recounted, stored in connection.execute(_RECOUNT_SQL).fetchall():
        if str(recounted) != str(stored):
            what = "(frequency, degree, doc_count)" if kind == "entity" else "combined_degree"
            raise InternalError(
                f"GR16: {kind} {row_id} stores {what} = {stored} and a recount gives {recounted}",
                fix=_REPORT_FIX,
            )


def recount_and_check(connection: Any) -> SalienceReport:
    """STEP 7 and GR16 in one transaction: the write, then the recount that must agree with it."""
    report = recount(connection)
    check(connection)
    return report
