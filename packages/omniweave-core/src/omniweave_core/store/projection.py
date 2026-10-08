"""`canonical_projection()`: what a full and an incremental build must agree on. **D675.**

06-structure-extraction.md section 10.4 (:2402-2416) is the specification, and GR8 is its gate:

```text
canonical_projection(store) = a sorted (scope, etype, key) entity multiset
                            | sorted (src.key, dst.key, relation, observed cite, trust, method)
                            | sorted (subject.key, claim_type, predicate, object, t_start, t_end)
                            | a sorted community member_digest multiset
                            | a sorted ref_unresolved.name_norm multiset
                            | a sorted (doc, name_norm, akind) anchor multiset
# SURROGATE IDS ARE EXCLUDED. This is what full and incremental must agree on, byte for byte.
```

Read-only, one statement per member, every member sorted, so two stores holding the same graph
return equal values whatever order their rows were written in.

## The readings this module takes where the box is silent

1. **A document is its `doc_key`, never its `doc_ord`.** `doc_ord` is a surrogate (`doc_ord INTEGER
   PRIMARY KEY`, corpus-local): an edited file is a new document with a new ordinal in an
   incremental store and the first ordinal in a full rebuild of the same bytes. `doc_key` is
   `sha256(normalised source bytes)[:16]` (03:162) and is equal in both. So the entity member's
   `scope` is `"corpus"` or the owning document's `doc_key` in hex, and the anchor member's `doc`
   is the defining document's.
2. **An observed location is `(doc_key, addr)`, not a cite.** A cite (`d7#412`) carries the
   `doc_ord` and a counter that numbers parses, so it is a surrogate twice over; `addr` is
   type-free and a function of the parse (`block.addr`, 0001:240).
3. **Live rows only.** Entities through `ow_entity_head` (live, canonical); an edge or a claim
   only while its observed block is live; anchors at their document's head generation, as both
   reference views read them; communities with `state = 0`. A retired row is history, which a full
   rebuild of the current corpus never contains.
4. **`method` is the observing run's**, read off `derive_run`: `edge` carries `run_id`, not a
   method, and `derive_run.method` is the one place a run's method is stored.
5. **`ref_unresolved` is projected as its `name_norm` multiset**, exactly as printed -- not as
   occurrences, whose block ids are surrogates.

Members with no producer yet (edges, claims, communities at W8.3) are computed all the same and
are empty, so the day a Pass writes them the gate already compares them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from typing import Final

__all__ = ["CanonicalProjection", "canonical_projection"]


@dataclass(frozen=True, slots=True)
class CanonicalProjection:
    """06:2410-2415's six members, each a sorted tuple. Equality IS the GR8 comparison."""

    entities: tuple[tuple[str, str, str], ...]
    edges: tuple[tuple[object, ...], ...]
    claims: tuple[tuple[object, ...], ...]
    communities: tuple[str, ...]
    unresolved: tuple[str, ...]
    anchors: tuple[tuple[str, str, str], ...]

    def differences(
        self, other: CanonicalProjection
    ) -> dict[str, tuple[list[object], list[object]]]:
        """Per member that differs: what only `self` holds and what only `other` holds."""
        out: dict[str, tuple[list[object], list[object]]] = {}
        for member in fields(self):
            mine = list(getattr(self, member.name))
            theirs = list(getattr(other, member.name))
            if mine == theirs:
                continue
            left, right = list(mine), list(theirs)
            for row in mine:
                if row in right:
                    right.remove(row)
                    left.remove(row)
            out[member.name] = (left, right)
        return out


_ENTITIES: Final = """
SELECT CASE WHEN e.scope = 0 THEN 'corpus' ELSE lower(hex(d.doc_key)) END, e.etype, e.key
FROM ow_entity_head e LEFT JOIN doc d ON d.doc_ord = e.scope
ORDER BY 1, 2, 3
"""

_EDGES: Final = """
SELECT s.key, t.key, g.relation, lower(hex(d.doc_key)), b.addr, g.trust, r.method
FROM edge g
JOIN entity s ON s.entity_id = g.src_entity
JOIN entity t ON t.entity_id = g.dst_entity
JOIN block b ON b.block_id = g.observed_block AND b.state = 0
JOIN doc d ON d.doc_ord = b.doc_ord
LEFT JOIN derive_run r ON r.run_id = g.run_id
ORDER BY 1, 2, 3, 4, 5, 6, 7
"""

_CLAIMS: Final = """
SELECT s.key, c.claim_type, c.predicate, COALESCE(o.key, c.object_literal), c.t_start, c.t_end
FROM claim c
JOIN entity s ON s.entity_id = c.subject_entity
LEFT JOIN entity o ON o.entity_id = c.object_entity
JOIN block b ON b.block_id = c.observed_block AND b.state = 0
ORDER BY 1, 2, 3, 4, 5, 6
"""

_COMMUNITIES: Final = "SELECT lower(hex(member_digest)) FROM community WHERE state = 0 ORDER BY 1"

_UNRESOLVED: Final = "SELECT name_norm FROM ref_unresolved ORDER BY 1"

_ANCHORS: Final = """
SELECT lower(hex(d.doc_key)), n.name_norm, n.akind
FROM anchor n JOIN doc d ON d.doc_ord = n.doc_ord AND n.gen = d.gen
ORDER BY 1, 2, 3
"""


def canonical_projection(connection: sqlite3.Connection) -> CanonicalProjection:
    """The store's graph with every surrogate id taken out. Read-only."""

    def rows(sql: str) -> tuple[tuple[object, ...], ...]:
        return tuple(tuple(row) for row in connection.execute(sql))

    return CanonicalProjection(
        entities=tuple((str(a), str(b), str(c)) for a, b, c in rows(_ENTITIES)),
        edges=rows(_EDGES),
        claims=rows(_CLAIMS),
        communities=tuple(str(row[0]) for row in rows(_COMMUNITIES)),
        unresolved=tuple(str(row[0]) for row in rows(_UNRESOLVED)),
        anchors=tuple((str(a), str(b), str(c)) for a, b, c in rows(_ANCHORS)),
    )
