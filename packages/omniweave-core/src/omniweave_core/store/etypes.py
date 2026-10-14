"""The entity-type vocabulary, read and promoted. D706.

06 sections 1.6 and 4.7 are the specification and `model.etypes` the types. A proposed type is not
first-class -- *"`source='proposed'` rows are excluded from the rendered `etypes` array until an
operator promotes them, so a tuning run cannot change extraction output by itself"* (06:1675-1676)
-- and promotion is the operator's act that changes that.

## Rulings (the ledger's D706)

1. **The listing is every `etype_vocab` row**, builtin first, then user, then proposed, and by name
   within each. Each row carries its live entities, **counted**: `etype_vocab.n_entities` has no
   writer, so reading it would print zero for every type.
2. **`--promote` takes proposed rows only.** A builtin or user type is already first-class and is
   refused naming its source; a name with no row is not found. The names are checked before any is
   written, so a promotion is all of them or none.
3. **The reason is required and kept verbatim**, in `meta` under `graph.etype_promoted.<etype>` as
   canonical JSON `{"gen", "reason"}`. 06:1673's `route_decision` belongs to the billed run that
   proposes; an operator's promotion is no routed unit, and `etype_vocab` has no column for why.
   `ow graph types` prints it beside the type.
4. **`--propose` is not built here.** Its step 2 is one billed call per sampled Segment under the
   `derive.entity.llm` decision (06:1661-1662), which W8.8 builds; the verb refuses it by name.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from omniweave_core.canonical import canonical
from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.etypes import Etype, Promotion, TypeVocab

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

__all__ = ["PROMOTED_PREFIX", "promote", "type_vocab"]

PROMOTED_PREFIX: Final = "graph.etype_promoted."
"""Ruling 3: the `meta` key of a promotion is this prefix and the type's name."""

_ROWS: Final = """
SELECT v.etype, v.scope, v.resolution, v.source, v.compatible,
       (SELECT count(*) FROM entity AS e WHERE e.etype = v.etype AND e.state = 0)
  FROM etype_vocab AS v
 ORDER BY CASE v.source WHEN 'builtin' THEN 0 WHEN 'user' THEN 1 ELSE 2 END, v.etype
"""
_PROMOTIONS: Final = "SELECT k, v FROM meta WHERE k LIKE 'graph.etype_promoted.%'"
_SOURCE: Final = "SELECT source FROM etype_vocab WHERE etype = ?"
_PROMOTE: Final = "UPDATE etype_vocab SET source = 'user' WHERE etype = ? AND source = 'proposed'"
_RECORD: Final = "INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v"
_GENERATION: Final = "SELECT v FROM index_state WHERE k = 'generation'"
_FIX: Final = "ow graph types --promote defined_term,covenant --reason 'why they belong'"


def type_vocab(connection: sqlite3.Connection, *, promoted: Sequence[str] = ()) -> TypeVocab:
    """Ruling 1: every row, ordered by source and name, with its live entities and promotion."""
    records = {
        str(k)[len(PROMOTED_PREFIX) :]: json.loads(str(v))
        for k, v in connection.execute(_PROMOTIONS)
    }
    return TypeVocab(
        etypes=tuple(
            Etype(
                etype=str(etype),
                scope=str(scope),
                resolution=str(resolution),
                source=str(source),
                compatible=tuple(str(c) for c in json.loads(str(compatible))),
                entities=int(entities),
                promoted=(
                    Promotion(reason=str(records[etype]["reason"]), gen=int(records[etype]["gen"]))
                    if etype in records
                    else None
                ),
            )
            for etype, scope, resolution, source, compatible, entities in connection.execute(_ROWS)
        ),
        promoted=tuple(promoted),
    )


def promote(connection: sqlite3.Connection, *, etypes: Sequence[str], reason: str) -> TypeVocab:
    """Rulings 2 and 3, in the caller's transaction.

    Raises:
        UsageError: a blank reason, no type named, or a type that is not proposed.
        NotFoundError: a type `etype_vocab` has no row for.
    """
    if not reason.strip():
        raise UsageError("a promotion needs a reason", fix=_FIX)
    names = list(dict.fromkeys(name.strip() for name in etypes if name.strip()))
    if not names:
        raise UsageError("--promote names no type", fix=_FIX)
    for name in names:
        row = connection.execute(_SOURCE, (name,)).fetchone()
        if row is None:
            raise NotFoundError(f"no entity type {name!r}", fix="ow graph types   # the vocabulary")
        if str(row[0]) != "proposed":
            raise UsageError(
                f"{name} is {row[0]}, not proposed: it is already rendered into the prompt",
                fix="ow graph types   # the proposed ones are listed last",
            )
    stored = connection.execute(_GENERATION).fetchone()
    gen = 0 if stored is None else int(str(stored[0]))
    for name in names:
        connection.execute(_PROMOTE, (name,))
        record = canonical({"gen": gen, "reason": reason}).decode()
        connection.execute(_RECORD, (PROMOTED_PREFIX + name, record))
    return type_vocab(connection, promoted=names)
