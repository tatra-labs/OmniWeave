"""The resolution decision log, read one closure at a time. D696.

06:1885-1894 is the specification, and `model.merges` the types. `entity_merge` is append-only: a
decision a later pass no longer produces is retired (`retired_at_gen`), never deleted (D684), so the
log answers both "why are these one" and "why did they stop being one".

## Rulings (the ledger's D696)

1. **An entity names its closure.** `--entity e412` reads the closure `e412` is in -- its head and
   every entity whose `canonical_id` is that head -- and every decision with an end in it, live or
   retired, oldest first: the history of how the cluster came to be what it is. A merged-away cite
   names the same closure as its head.
2. **Without an entity, the log is every closure of two or more, and only its live decisions**:
   what the resolution currently says, closure by closure. History is per closure, on request.
3. **A user split is in the closure of either end.** A `polarity = -1` row joins nothing, so its two
   ends are in two closures, and each closure's log shows the split that keeps it apart.
4. **Members are the entities that are not retired.** An overloaded entity is its own head (D693)
   and a closure of one, so it appears only when asked for by name.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import NotFoundError
from omniweave_core.model.enums import enum_val_rows
from omniweave_core.model.merges import Decision, MergeClosure, MergeLog

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence

__all__ = ["merge_log"]

_CITE: Final = re.compile(r"e?(?P<number>\d+)")
_METHOD: Final = {ordinal: name for domain, ordinal, name in enum_val_rows() if domain == "method"}

_ENTITY_SQL: Final = "SELECT entity_id, canonical_id, cite FROM entity WHERE entity_id = ?"
_MEMBERS_SQL: Final = """
SELECT entity_id, canonical_id, cite FROM entity WHERE state IN (0, 1) ORDER BY entity_id
"""
_DECISIONS_SQL: Final = """
SELECT m.merge_id, l.cite, w.cite, m.polarity, m.stage, m.method, m.trust, m.score, m.score_kind,
       m.guards, m.reason, m.decided_at_gen, m.retired_at_gen, m.loser_id, m.winner_id
  FROM entity_merge AS m
  JOIN entity AS l ON l.entity_id = m.loser_id
  JOIN entity AS w ON w.entity_id = m.winner_id
 ORDER BY m.decided_at_gen, m.merge_id
"""


def merge_log(connection: sqlite3.Connection, entity: str | None = None) -> MergeLog:
    """Rulings 1-4.

    Raises:
        NotFoundError: `entity` names no entity.
        ValueError: `entity` is not an entity cite or a number.
    """
    heads: dict[int, int] = {}
    cites: dict[int, str] = {}
    for entity_id, canonical_id, cite in connection.execute(_MEMBERS_SQL).fetchall():
        heads[int(entity_id)] = int(canonical_id)
        cites[int(entity_id)] = str(cite)
    rows = connection.execute(_DECISIONS_SQL).fetchall()
    if entity is not None:
        found = _CITE.fullmatch(entity.strip())
        if found is None:
            msg = f"{entity!r} is not an entity cite: `e412` or a number"
            raise ValueError(msg)
        row = connection.execute(_ENTITY_SQL, (int(found["number"]),)).fetchone()
        if row is None:
            raise NotFoundError(f"no entity {entity}", fix="ow graph merges   # the whole log")
        head = int(row[1])
        members = sorted(e for e, h in heads.items() if h == head) or [int(row[0])]
        closure = _closure(head, members, cites, rows, live_only=False)
        return MergeLog(entity=str(row[2]), closures=(closure,))
    grouped: dict[int, list[int]] = defaultdict(list)
    for entity_id, head in heads.items():
        grouped[head].append(entity_id)
    closures = tuple(
        _closure(head, sorted(members), cites, rows, live_only=True)
        for head, members in sorted(grouped.items())
        if len(members) > 1
    )
    return MergeLog(entity=None, closures=closures)


def _closure(
    head: int,
    members: Sequence[int],
    cites: dict[int, str],
    rows: Iterable[Sequence[object]],
    *,
    live_only: bool,
) -> MergeClosure:
    inside = set(members)
    decisions = tuple(
        _decision(r)
        for r in rows
        if (int(str(r[13])) in inside or int(str(r[14])) in inside)
        and not (live_only and r[12] is not None)
    )
    return MergeClosure(
        head=cites.get(head, f"e{head}"),
        members=tuple(cites.get(m, f"e{m}") for m in members),
        decisions=decisions,
    )


def _decision(r: Sequence[object]) -> Decision:
    guards = json.loads(str(r[9]))
    return Decision(
        merge=int(str(r[0])),
        loser=str(r[1]),
        winner=str(r[2]),
        polarity=int(str(r[3])),
        stage=str(r[4]),
        method=_METHOD.get(int(str(r[5])), str(r[5])),
        trust=int(str(r[6])),
        score=None if r[7] is None else float(str(r[7])),
        score_kind=None if r[8] is None else str(r[8]),
        guards=tuple(str(g) for g in guards) if isinstance(guards, list) else (),
        reason=None if r[10] is None else str(r[10]),
        decided_at_gen=int(str(r[11])),
        retired_at_gen=None if r[12] is None else int(str(r[12])),
    )
