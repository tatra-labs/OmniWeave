"""The graph's residue, read and grouped. D699.

06:885-887 is the specification and `model.residue` the types: **residue** is *"`ref_unresolved`
plus `quarantine`"*, the operability number, and `ow graph residue [--akind <k>]` (06:2521) prints
it grouped. `store.inspect.residue()` is `ow store residue`'s report on INV-25's growth, folded to
`name_norm` across kinds; this one is the graph's, kept per kind, because 06:1091 makes the verb
*"the surface an operator uses to add a negative fixture"* and a fixture belongs to one kind's
pattern.

## Rulings (the ledger's D699)

1. **`ref_unresolved` is grouped by `(akind, name_norm)`**, ranked by sites, worst first, then by
   kind and name so the order is total. A group carries the documents it spans and one occurrence
   as written, the least in code-point order so two reads agree.
2. **The groups are cut at `inspect.DEFAULT_GROUP_LIMIT`** with a `take(N+1)` read, and `truncated`
   says when the ceiling bound (INV-25: *"every ceiling at `take(N+1)`"*). The site count is never
   cut.
3. **`quarantine` is grouped by `(code, row_kind)`**: rows, distinct runs, and the first and last
   generation. It is not cut: the codes and the row kinds are closed vocabularies, so the groups
   are bounded by their product.
4. **`--akind` narrows both halves.** A `ref_site` by its column; a quarantined row by the `akind`
   of the draft it keeps verbatim, so only anchor and xref drafts, the two that carry one. A kind
   outside `AnchorKind` is refused naming the fourteen.
5. **The report carries its denominator**: every `ref_site` row under the same filter, resolved or
   not, so 06:891's share is two numbers in one answer rather than a ratio to trust.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_core.model.enums import AnchorKind
from omniweave_core.model.residue import GraphResidue, QuarantineGroup, UnresolvedGroup
from omniweave_core.store.inspect import DEFAULT_GROUP_LIMIT

if TYPE_CHECKING:
    import sqlite3

__all__ = ["graph_residue"]

_SITES_SQL: Final = "SELECT count(*) FROM ref_site WHERE :akind IS NULL OR akind = :akind"
_UNRESOLVED_SQL: Final = (
    "SELECT count(*) FROM ref_unresolved WHERE :akind IS NULL OR akind = :akind"
)
_GROUPS_SQL: Final = """
SELECT akind, name_norm, count(*) AS sites, count(DISTINCT doc_ord), min(surface)
  FROM ref_unresolved
 WHERE :akind IS NULL OR akind = :akind
 GROUP BY akind, name_norm
 ORDER BY sites DESC, akind, name_norm
 LIMIT :take
"""
_QUARANTINE_SQL: Final = """
SELECT code, row_kind, count(*) AS n, count(DISTINCT run_id), min(at_gen), max(at_gen)
  FROM quarantine
 WHERE :akind IS NULL OR (json_valid(payload) AND json_extract(payload, '$.akind') = :akind)
 GROUP BY code, row_kind
 ORDER BY n DESC, code, row_kind
"""


def graph_residue(
    connection: sqlite3.Connection, *, akind: str | None = None, limit: int = DEFAULT_GROUP_LIMIT
) -> GraphResidue:
    """Rulings 1-5.

    Raises:
        ValueError: `akind` is not an `AnchorKind`.
    """
    if akind is not None and akind not in {kind.value for kind in AnchorKind}:
        kinds = ", ".join(kind.value for kind in AnchorKind)
        msg = f"{akind!r} is not an anchor kind: {kinds}"
        raise ValueError(msg)
    params = {"akind": akind}
    [(sites,)] = connection.execute(_SITES_SQL, params).fetchall()
    [(unresolved,)] = connection.execute(_UNRESOLVED_SQL, params).fetchall()
    rows = connection.execute(_GROUPS_SQL, {**params, "take": limit + 1}).fetchall()
    groups = tuple(
        UnresolvedGroup(
            akind=str(kind), name_norm=str(name), sites=int(n), docs=int(docs), surface=str(seen)
        )
        for kind, name, n, docs, seen in rows[:limit]
    )
    quarantine = tuple(
        QuarantineGroup(
            code=str(code),
            row_kind=str(row_kind),
            rows=int(n),
            runs=int(runs),
            first_gen=int(first),
            last_gen=int(last),
        )
        for code, row_kind, n, runs, first, last in connection.execute(_QUARANTINE_SQL, params)
    )
    return GraphResidue(
        akind=akind,
        sites=int(sites),
        unresolved_sites=int(unresolved),
        unresolved=groups,
        truncated=len(rows) > limit,
        quarantined=sum(group.rows for group in quarantine),
        quarantine=quarantine,
    )
