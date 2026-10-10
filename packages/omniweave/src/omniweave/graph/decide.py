"""`ow graph merge`: a user's decision, appended to the log, and the graph settled again. D697.

06 section 5.5 is the specification: *"three verbs, and the crucial property is that all three are
append-only log writes followed by a re-closure, never a re-index"*. `merge` writes
`entity_merge(polarity = +1, stage = 'user', reason = <required>)`; `op.resolve` applies user rows
last and a pass never overwrites one (D684); the closure, the communities and the salience are then
settled again exactly as `ow ingest` settles them (`graph.settle`, `graph.salience`), in the one
transaction the decision is made in.

## Rulings (the ledger's D697)

1. **A decision is made at the store's current generation**: `decided_at_gen` is the generation
   the last ingest committed, and its `run_id` is that generation's `op.resolve` run
   (`resolve.run_row`). A decision between two ingests belongs to the state it was made against,
   and it mints no run of its own.
2. **Both ends must be live entities.** A retired one is history, and an overloaded one takes no
   part in resolution (D693), so a merge naming either is refused, naming why.
3. **The row orders its ends as the pass does**: `winner_id` is the end first in identity order
   `(key, etype, scope)` (D684 ruling 7). A user row never names the survivor; the closure does.
4. **A merge retires the user split between the same two** (either direction), at this generation:
   the newer decision wins, which is what makes 06:1904's `merge -> split -> merge` round trip land
   where it started.
5. **The same live decision is not written twice.** `entity_merge_pair` is unique on the live
   `(loser, winner, polarity)`, and a second identical merge is a no-op that says so.
6. **A merge another user split keeps from taking effect is still written, and reported.** A split
   between other members of the two closures blocks the union (D684 ruling 5 applies to user rows
   too), and `joined` says the graph did not follow. Retiring a decision the user did not name
   would be a guess.
7. **`--reason` is required and kept verbatim**, as 0002:443 makes it the writer's duty.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.enums import Method, Trust, enum_val_rows
from omniweave_core.model.merges import Decided
from omniweave_core.store.merges import merge_log

from omniweave.graph import cluster as op_cluster
from omniweave.graph import resolve as op_resolve
from omniweave.graph import salience
from omniweave.graph.settle import settle

if TYPE_CHECKING:
    from omniweave.graph.settle import Settled

__all__ = ["GRAPH_ROUNDS", "current_generation", "merge"]

GRAPH_ROUNDS: Final = 4
"""The settle bound, `ow ingest`'s (D691)."""

_CITE: Final = re.compile(r"e?(?P<number>\d+)")
_METHOD_ORD: Final = {
    name: ordinal for domain, ordinal, name in enum_val_rows() if domain == "method"
}
_ENTITY_SQL: Final = (
    "SELECT entity_id, cite, state, key, etype, scope FROM entity WHERE entity_id = ?"
)
_GENERATION_SQL: Final = "SELECT v FROM index_state WHERE k = 'generation'"
_LIVE_USER_SQL: Final = """
SELECT merge_id FROM entity_merge
 WHERE stage = 'user' AND polarity = :polarity AND retired_at_gen IS NULL
   AND ((loser_id = :a AND winner_id = :b) OR (loser_id = :b AND winner_id = :a))
"""
_RETIRE_SQL: Final = "UPDATE entity_merge SET retired_at_gen = :gen WHERE merge_id = :merge_id"
_INSERT_SQL: Final = """
INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, score, score_kind,
                         guards, reason, run_id, decided_at_gen)
VALUES(:loser, :winner, :polarity, 'user', :method, :trust, NULL, NULL, '[]', :reason, :run_id,
       :gen)
"""
_HEAD_SQL: Final = "SELECT canonical_id FROM entity WHERE entity_id = ?"
_STATES: Final = {1: "overloaded", 2: "retired"}


def current_generation(connection: Any) -> int:
    """The generation the last ingest committed (ruling 1)."""
    row = connection.execute(_GENERATION_SQL).fetchone()
    return 0 if row is None else int(str(row[0]))


def merge(connection: Any, *, first: str, second: str, reason: str) -> Decided:
    """Rulings 1-7: append the user's merge, retire the split it contradicts, and settle.

    Raises:
        UsageError: one entity twice, a blank reason, or an entity that is not live.
        NotFoundError: a cite that names no entity.
    """
    if not reason.strip():
        raise UsageError(
            "a user decision needs a reason", fix='ow graph merge e1 e2 --reason "why"'
        )
    a, b = _live(connection, first), _live(connection, second)
    if a[0] == b[0]:
        raise UsageError(
            f"{first} and {second} are one entity", fix="ow graph merges --entity " + a[1]
        )
    gen = current_generation(connection)
    params = {"a": a[0], "b": b[0]}
    retired = 0
    for (merge_id,) in connection.execute(_LIVE_USER_SQL, {**params, "polarity": -1}).fetchall():
        connection.execute(_RETIRE_SQL, {"gen": gen, "merge_id": int(merge_id)})
        retired += 1
    written = 0
    if connection.execute(_LIVE_USER_SQL, {**params, "polarity": 1}).fetchone() is None:
        winner, loser = sorted((a, b), key=lambda e: (e[3], e[4], e[5]))
        connection.execute(
            _INSERT_SQL,
            {
                "loser": loser[0],
                "winner": winner[0],
                "polarity": 1,
                "method": _METHOD_ORD[Method.USER.name.lower()],
                "trust": int(Trust.EXTRACTED),
                "reason": reason,
                "run_id": op_resolve.run_row(connection, gen),
                "gen": gen,
            },
        )
        written = 1
    _settle(connection, gen)
    joined = _head(connection, a[0]) == _head(connection, b[0])
    return Decided(
        polarity=1,
        written=written,
        retired=retired,
        joined=joined,
        log=merge_log(connection, a[1]),
    )


def _live(connection: Any, ref: str) -> tuple[int, str, int, str, str, int]:
    """Ruling 2: the entity a cite names, refused unless it is live."""
    found = _CITE.fullmatch(ref.strip())
    if found is None:
        raise UsageError(
            f"{ref!r} is not an entity cite: `e412` or a number", fix="ow graph merges"
        )
    row = connection.execute(_ENTITY_SQL, (int(found["number"]),)).fetchone()
    if row is None:
        raise NotFoundError(f"no entity {ref}", fix="ow graph merges   # the whole log")
    entity_id, cite, state, key, etype, scope = row
    if int(state) != 0:
        raise UsageError(
            f"{cite} is {_STATES.get(int(state), 'not live')}, and takes no part in resolution",
            fix=f"ow graph merges --entity {cite}",
        )
    return int(entity_id), str(cite), int(state), str(key), str(etype), int(scope)


def _head(connection: Any, entity_id: int) -> int:
    return int(connection.execute(_HEAD_SQL, (entity_id,)).fetchone()[0])


def _settle(connection: Any, gen: int) -> Settled:
    """The graph after the decision as `ow ingest` leaves it: closure, communities, salience."""
    settled = settle(
        lambda: op_resolve.resolve(connection, gen=gen),
        lambda: op_cluster.cluster(connection, gen=gen),
        bound=GRAPH_ROUNDS,
    )
    salience.recount_and_check(connection)
    return settled
