"""`ow graph merge` and `split`: a user's decision appended, and the graph settled. D697, D698.

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
   too), and `followed` says the graph did not follow. Retiring a decision the user did not name
   would be a guess.
7. **`--reason` is required and kept verbatim**, as 0002:443 makes it the writer's duty.

## `split` (the ledger's D698)

06:1907-1913: *"`--into` takes block cites rather than entity cites ... The verb resolves each cite
to the mentions in that block, partitions the cluster's mentions by which side they are closer to
under the same Jaro-Winkler function, and writes one `polarity=-1` row per cross-partition pair."*
A mention belongs to exactly one entity and an entity id is durable, so the unit partitioned is the
closure's member entity: the mentions of one member cannot go two ways without re-extraction.

8. **A side is anchored by the closure members its block mentions.** Each `--into` ref resolves as
   `ow open` resolves it, to exactly one block; the closure's members with a live mention there
   are that side's anchors. Fewer than two refs, a block that mentions no member, and a member
   two blocks mention are usage errors naming the ref.
9. **Every other member goes to the side whose anchor its key is closest to** under `fuzzy`'s
   Jaro-Winkler on labels: the best anchor of each side, then the best side. A tie is unassigned
   and *"stays with the survivor and is reported"* (06:1911): it takes the head's side. When the
   head is itself unassigned, the unassigned members are reported and left out of every pair,
   because guessing is worse than a stated incompleteness.
10. **A `-1` row for every cross-side pair of members**, not one per pair of anchors. Union-find
    checks a split only between the two components it is joining (D684 ruling 5), so a pass pair
    between two unanchored members on different sides would otherwise join them before either met
    its anchor. A pair a live user split already keeps apart is not written again. Each row orders
    its ends by identity, as ruling 3.
11. **A split retires the user merges it contradicts**: every live `+1` user row between members on
    different sides, at this generation -- ruling 4 the other way, which is what lets
    `merge -> split -> merge` come back.
12. **`followed` for a split is whether the sides stayed apart**: no two anchors of different sides
    share a head once the graph has settled.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.enums import Method, Trust, enum_val_rows
from omniweave_core.model.merges import Decided
from omniweave_core.store.merges import merge_log
from omniweave_core.store.resolve import Missed, resolve_one

from omniweave.graph import cluster as op_cluster
from omniweave.graph import fuzzy, salience
from omniweave.graph import resolve as op_resolve
from omniweave.graph.settle import settle

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave.graph.settle import Settled

__all__ = ["GRAPH_ROUNDS", "current_generation", "merge", "partition", "split"]

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
_MEMBERS_SQL: Final = (
    "SELECT entity_id, key, etype, scope FROM entity WHERE canonical_id = ? AND state = 0"
)
_MENTIONED_SQL: Final = "SELECT DISTINCT entity_id FROM mention WHERE block_id = ? AND state = 0"
_LAYERS_SQL: Final = "SELECT name, ord FROM enum_val WHERE domain = 'layer'"
_CITE_SQL: Final = "SELECT cite FROM entity WHERE entity_id = ?"
_STATES: Final = {1: "overloaded", 2: "retired"}
_SPLIT_FIX: Final = 'ow graph split e412 --into d7#412,d19#88 --reason "why they are two"'


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
    return Decided(
        polarity=1,
        written=written,
        retired=retired,
        followed=_head(connection, a[0]) == _head(connection, b[0]),
        log=merge_log(connection, a[1]),
    )


def split(connection: Any, *, entity: str, into: Sequence[str], reason: str) -> Decided:
    """Rulings 8-12: anchor the sides, place the rest, write the cross pairs, and settle.

    Raises:
        UsageError: a blank reason, fewer than two refs, a ref naming more than one block, a block
            that anchors nothing, a member two blocks mention, a closure of one, or an entity that
            is not live.
        NotFoundError: an entity or a ref that names nothing.
    """
    if not reason.strip():
        raise UsageError("a user decision needs a reason", fix=_SPLIT_FIX)
    refs = [ref.strip() for ref in into if ref.strip()]
    if len(refs) < 2:  # noqa: PLR2004 -- a split has two sides
        raise UsageError("a split names two blocks or more, one per side", fix=_SPLIT_FIX)
    target = _live(connection, entity)
    head = _head(connection, target[0])
    members = {
        int(row[0]): (str(row[1]), str(row[2]), int(row[3]))
        for row in connection.execute(_MEMBERS_SQL, (head,)).fetchall()
    }
    if len(members) < 2:  # noqa: PLR2004 -- a pair is two
        raise UsageError(
            f"{target[1]}'s closure is one entity, so there is nothing to split",
            fix=f"ow graph merges --entity {target[1]}",
        )
    anchored = _anchors(connection, refs, members, target[1])
    side_of, unassigned = partition(
        {member: identity[0] for member, identity in members.items()}, anchored, head=head
    )
    gen = current_generation(connection)
    written = retired = 0
    ordered = sorted(side_of)
    for index, x in enumerate(ordered):
        for y in ordered[index + 1 :]:
            if side_of[x] == side_of[y]:
                continue
            params = {"a": x, "b": y}
            for (merge_id,) in connection.execute(
                _LIVE_USER_SQL, {**params, "polarity": 1}
            ).fetchall():
                connection.execute(_RETIRE_SQL, {"gen": gen, "merge_id": int(merge_id)})
                retired += 1
            if connection.execute(_LIVE_USER_SQL, {**params, "polarity": -1}).fetchone():
                continue
            winner, loser = sorted((x, y), key=members.__getitem__)
            connection.execute(
                _INSERT_SQL,
                {
                    "loser": loser,
                    "winner": winner,
                    "polarity": -1,
                    "method": _METHOD_ORD[Method.USER.name.lower()],
                    "trust": int(Trust.EXTRACTED),
                    "reason": reason,
                    "run_id": op_resolve.run_row(connection, gen),
                    "gen": gen,
                },
            )
            written += 1
    _settle(connection, gen)
    first = [min(m for m, side in anchored.items() if side == s) for s in range(len(refs))]
    return Decided(
        polarity=-1,
        written=written,
        retired=retired,
        followed=len({_head(connection, m) for m in first}) == len(first),
        log=merge_log(connection, target[1]),
        unassigned=tuple(
            str(connection.execute(_CITE_SQL, (m,)).fetchone()[0]) for m in unassigned
        ),
    )


def partition(
    keys: Mapping[int, str], anchored: Mapping[int, int], *, head: int
) -> tuple[dict[int, int], tuple[int, ...]]:
    """Ruling 9: each member's side, and the members no side could claim (by a tie).

    `keys` is every closure member's key, `anchored` the anchors' sides, `head` the closure's.
    The unassigned take the head's side when the head has one, and no side when it has none.
    """
    sides = sorted(set(anchored.values()))
    side_of = dict(anchored)
    tied: list[int] = []
    for member in sorted(set(keys) - set(anchored)):
        label = fuzzy.label(keys[member])
        best = {
            side: max(
                fuzzy.jaro_winkler(label, fuzzy.label(keys[anchor]))
                for anchor, at in anchored.items()
                if at == side
            )
            for side in sides
        }
        top = max(best.values())
        winners = [side for side in sides if best[side] == top]
        if len(winners) == 1:
            side_of[member] = winners[0]
        else:
            tied.append(member)
    if head in side_of:
        side_of.update(dict.fromkeys(tied, side_of[head]))
    return side_of, tuple(tied)


def _anchors(
    connection: Any, refs: Sequence[str], members: Mapping[int, object], name: str
) -> dict[int, int]:
    """Ruling 8: the members each ref's block mentions, keyed to that ref's side."""
    layers = {str(n): int(o) for n, o in connection.execute(_LAYERS_SQL).fetchall()}
    anchored: dict[int, int] = {}
    for side, ref in enumerate(refs):
        found = resolve_one(
            connection, ref, context=0, layers=frozenset(layers.values()), hidden=layers["hidden"]
        )
        if isinstance(found, Missed):
            raise found.error
        if len(found.block_ids) != 1:
            raise UsageError(
                f"{ref} names {len(found.block_ids)} blocks, and a side is one block",
                fix=_SPLIT_FIX,
            )
        mentioned = sorted(
            int(row[0])
            for row in connection.execute(_MENTIONED_SQL, (found.block_ids[0],)).fetchall()
            if int(row[0]) in members
        )
        if not mentioned:
            raise UsageError(
                f"{ref} mentions no member of {name}'s closure",
                fix=f"ow graph why --cite {ref}   # what it does mention",
            )
        for member in mentioned:
            if anchored.setdefault(member, side) != side:
                raise UsageError(
                    f"{refs[anchored[member]]} and {ref} mention one member of {name}'s closure, "
                    "which cannot be on both sides",
                    fix=_SPLIT_FIX,
                )
    return anchored


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
