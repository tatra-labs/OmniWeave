"""A community report's context, assembled by the host from the store. **D732.**

06 section 6.3 is the specification. A report is cached on `member_digest`, so its context must be a
function of the store alone: assembled in a fixed order, within `REPORT_CONTEXT_TOKENS`, and with no
identifier in it. This module builds that context and the view the report lane reads (D731).
Nothing here calls a model or writes a row.

## Rulings (the ledger's D732)

1. **The budget is counted in `ow.bytes4/1` tokens over each record as sent**: the framework's own
   count (D662), restated here because `omniweave` may not import `omniweave-graph`. A test holds
   the two to one answer.
2. **Three passes, each stopping at a whole record** (06:2003). Members first, by degree, frequency
   and key; then the community's internal edges, by weight, combined degree and id; then the
   members' claims, by the subject's degree and the claim's id. A pass stops at the first record
   that does not fit, and the next pass has what is left. A record is never cut to fit, and one
   identical to a record already taken is skipped: two documents observing one relationship is
   one line of context.
3. **An edge is internal when both its ends' heads are members, and they are two.** An edge whose
   ends merged into one head says nothing about the community. It renders the heads' titles, and
   its quote is the observed block's text over the edge's span, or the block's text when it has
   none, at most `QUOTE_CHARS`. Only an edge, claim or mention on a live block is read, as
   `op.cluster` reads them.
4. **A claim's object is its entity's head title, or its literal.**
5. **A parent is written from its children's fresh reports** (06:2017): one `child` record per live
   child whose report is fresh, the largest first. Its coverage is the share of its children
   rendered. A parent with no child reported yet has no context: its children are written first.
6. **Every string passes `sanitize_label`** (06:2186's layer 7), which also bounds it at 200
   characters, and no cite, id or address reaches a record (INV-8). A description is cut at
   `DESCRIPTION_CHARS` first.
7. **The witness is every document holding a live mention of a member**, as
   `(unit_uri, "", key)`, the band's shape (D728 ruling 4).
8. **The community is named `com:` and the first 16 hex of its `member_digest`**: the name its
   report is filed under, durable across re-clusters with the digest (06:2049).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.answer.untrusted import sanitize_label

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DESCRIPTION_CHARS",
    "QUOTE_CHARS",
    "REPORT_CONTEXT_TOKENS",
    "REPORT_LEVELS",
    "Context",
    "context",
    "count_tokens",
]

REPORT_CONTEXT_TOKENS: Final = 8000
"""06:2674: the context budget, filled in three ordered passes."""
REPORT_LEVELS: Final = 2
"""06:1989: how deep a descent materialises."""
DESCRIPTION_CHARS: Final = 200
QUOTE_CHARS: Final = 120

_COMMUNITY_SQL: Final = (
    "SELECT level, size, member_digest FROM community WHERE community_id = ? AND state = 0"
)
_CHILDREN_SQL: Final = """
SELECT c.community_id, c.size, r.title, r.summary
  FROM community AS c
  LEFT JOIN community_report_fresh AS r ON r.community_id = c.community_id
 WHERE c.parent = ? AND c.state = 0
 ORDER BY c.size DESC, c.community_id
"""
_MEMBERS_SQL: Final = """
SELECT e.entity_id, e.key, e.title, e.etype, e.description FROM community_member AS m
  JOIN ow_entity_head AS e ON e.entity_id = m.entity_id
 WHERE m.community_id = ?
 ORDER BY e.degree DESC, e.frequency DESC, e.key
"""
_EDGES_SQL: Final = """
SELECT s.title, g.relation, d.title, b.text, g.ts_a, g.ts_b
  FROM edge AS g
  JOIN block AS b ON b.block_id = g.observed_block AND b.state = 0
  JOIN entity AS se ON se.entity_id = g.src_entity
  JOIN entity AS de ON de.entity_id = g.dst_entity
  JOIN entity AS s ON s.entity_id = se.canonical_id
  JOIN entity AS d ON d.entity_id = de.canonical_id
  JOIN community_member AS ms ON ms.community_id = :community AND ms.entity_id = s.entity_id
  JOIN community_member AS md ON md.community_id = :community AND md.entity_id = d.entity_id
 WHERE s.entity_id <> d.entity_id
 ORDER BY g.weight DESC, g.combined_degree DESC, g.edge_id
"""
_CLAIMS_SQL: Final = """
SELECT s.title, c.predicate, o.title, c.object_literal, c.status, c.t_start
  FROM claim AS c
  JOIN block AS b ON b.block_id = c.observed_block AND b.state = 0
  JOIN entity AS se ON se.entity_id = c.subject_entity
  JOIN entity AS s ON s.entity_id = se.canonical_id
  JOIN community_member AS m ON m.community_id = :community AND m.entity_id = s.entity_id
  LEFT JOIN entity AS oe ON oe.entity_id = c.object_entity
  LEFT JOIN entity AS o ON o.entity_id = oe.canonical_id
 ORDER BY s.degree DESC, c.claim_id
"""
_WITNESS_SQL: Final = """
SELECT DISTINCT u.unit_uri, h.key FROM community_member AS cm
  JOIN entity AS h ON h.entity_id = cm.entity_id
  JOIN entity AS e ON e.canonical_id = h.entity_id
  JOIN mention AS m ON m.entity_id = e.entity_id AND m.state = 0
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
  JOIN doc AS d ON d.doc_ord = b.doc_ord
  JOIN unit AS u ON u.unit_uri = d.uri
 WHERE cm.community_id = ? AND u.state <> 'out_of_scope'
 ORDER BY u.unit_uri, h.key
"""


def count_tokens(text: str) -> int:
    """Ruling 1: `ow.bytes4/1`, `ceil(len(text.encode("utf-8")) / 4)`."""
    size = len(text) if text.isascii() else len(text.encode("utf-8"))
    return (size + 3) // 4


@dataclass(frozen=True, slots=True)
class Context:
    """One community's report context, and the view the report lane reads."""

    community_id: int
    name: str
    level: int
    coverage: float
    records: tuple[Mapping[str, Any], ...]
    witness: tuple[tuple[str, str, str], ...]
    tokens: int
    """The records' tokens, by ruling 1's count: at most `REPORT_CONTEXT_TOKENS`."""

    @property
    def body(self) -> bytes:
        """The view D731's `read_community` reads: the header, then the records."""
        header = {
            "t": "community",
            "community": self.name,
            "level": self.level,
            "coverage": self.coverage,
            "witness": [{"unit_uri": u, "unit_part": p, "token": t} for u, p, t in self.witness],
        }
        return b"".join(_line(f).encode("utf-8") + b"\n" for f in (header, *self.records))


def context(
    connection: Any, community_id: int, *, budget: int = REPORT_CONTEXT_TOKENS
) -> Context | None:
    """Rulings 1-8: the community's context, or `None` when it is gone or a parent with no child
    reported."""
    found = connection.execute(_COMMUNITY_SQL, (community_id,)).fetchone()
    if found is None:
        return None
    level, size, digest = int(found[0]), int(found[1]), bytes(found[2])
    children = connection.execute(_CHILDREN_SQL, (community_id,)).fetchall()
    fill = _Fill(budget)
    if children:
        reported = [(str(t), str(s)) for _c, _n, t, s in children if t is not None]
        if not reported:
            return None
        rendered = fill.pass_(
            {"t": "child", "title": _clean(t), "summary": _clean(s)} for t, s in reported
        )
        coverage = rendered / len(children)
    else:
        members = connection.execute(_MEMBERS_SQL, (community_id,)).fetchall()
        rendered = fill.pass_(
            (
                {"t": "member", "title": _clean(title), "etype": str(etype),
                 "description": _clean(str(description or "")[:DESCRIPTION_CHARS])}
                for _e, _k, title, etype, description in members
            ),
            once=False,
        )  # fmt: skip
        fill.pass_(
            {"t": "edge", "src": _clean(src), "relation": str(relation), "dst": _clean(dst),
             "quote": _clean(_quote(text, a, b))}
            for src, relation, dst, text, a, b in connection.execute(
                _EDGES_SQL, {"community": community_id}
            )
        )  # fmt: skip
        fill.pass_(
            {"t": "claim", "subject": _clean(subject), "predicate": _clean(predicate),
             "object": _clean(str(entity if entity is not None else literal)),
             "status": str(status), "t_start": t_start}
            for subject, predicate, entity, literal, status, t_start in connection.execute(
                _CLAIMS_SQL, {"community": community_id}
            )
        )  # fmt: skip
        coverage = rendered / size if size else 0.0
    witness = tuple(
        (str(uri), "", str(key))
        for uri, key in connection.execute(_WITNESS_SQL, (community_id,)).fetchall()
    )
    return Context(
        community_id=community_id,
        name=f"com:{digest.hex()[:16]}",
        level=level,
        coverage=round(coverage, 4),
        records=tuple(fill.records),
        witness=witness,
        tokens=fill.used,
    )


class _Fill:
    """Ruling 2: records taken whole, in order, while they fit."""

    __slots__ = ("budget", "records", "seen", "used")

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.records: list[Mapping[str, Any]] = []
        self.seen: set[str] = set()
        self.used = 0

    def pass_(self, candidates: Any, *, once: bool = True) -> int:
        """Take records until one does not fit; return how many this pass took. With `once`, a
        record identical to one taken is skipped (ruling 2); members are distinct entities and
        are all counted, so their pass takes every one."""
        taken = 0
        for record in candidates:
            line = _line(record)
            if once and line in self.seen:
                continue
            cost = count_tokens(line)
            if self.used + cost > self.budget:
                break
            self.records.append(record)
            self.seen.add(line)
            self.used += cost
            taken += 1
        return taken


def _quote(text: Any, a: Any, b: Any) -> str:
    """Ruling 3: the span the edge was observed over, or the block's text, `QUOTE_CHARS` long."""
    body = str(text or "")
    if a is not None and b is not None and 0 <= int(a) <= int(b) <= len(body):
        body = body[int(a) : int(b)]
    return body[:QUOTE_CHARS]


def _clean(text: Any) -> str:
    return sanitize_label(str(text))


def _line(frame: Mapping[str, Any]) -> str:
    return json.dumps(frame, separators=(",", ":"), ensure_ascii=False)
