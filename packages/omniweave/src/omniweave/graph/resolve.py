"""`op.resolve`: the funnel's exact stage, and the closure every later stage writes into.

**D684.** 06-structure-extraction.md section 5 is the specification. The funnel has ten stages;
this cell builds the two that every other stage stands on:

* **stage [1], the exact key, with stage [2]'s type gate** -- entities in one scope that share a
  normalised name, and whose etypes may merge, are one thing (`stage='exact'`, `EXTRACTED`, no
  score); and
* **stages [9] and the closure** -- union-find over the whole live positive pair set in the total
  order, the survivor rule, `polarity = -1` as a blocking pair, `stage='user'` applied last, and
  `entity.canonical_id` and `entity.resolution_trust` recomputed from the log.

**D685 adds stages [3]-[5], [7] and [10]**: the entropy gate, MinHash blocking over bands
persisted in `entity_band`, Jaro-Winkler verification at 92.0, the guards, and the cohesion
re-check (`omniweave.graph.fuzzy` holds the arithmetic and its rulings). Stage [6], the community
boost, waits for `op.cluster`; stage [8], the LLM band, is billed and not built -- a pair scoring
in `[75, 92)` is counted and left, never merged.

**Pure over its inputs** (06:1696). `funnel()` and `closure()` take plain records and return plain
records; `resolve()` is the one function that reads and writes the store, in the caller's
transaction. It writes `entity_merge` rows, retires the ones its pass no longer produces, and
updates two derived columns on `entity`. It never inserts or deletes an entity.

## Rulings the plan leaves open (the ledger's D684)

1. **An entity's names are its key and its admitted aliases.** `key` is `normalize_key` of the
   canonical surface and the canonical alias's `name_norm` is the same string, so the key is
   always a name even when an alias row is missing.
2. **The untrusted-key rule** (0002:304, 06:1872) is applied at the exact stage too. An alias with
   `taint & UNTRUSTED_SOURCE` and `doc_count = 1` is never a blocking key, and exact grouping is
   blocking by key. The entity's own key stays a name.
3. **A group of N entities yields N-1 pairs, not N(N-1)/2.** Within one `(scope, name)` group in
   identity order, each member pairs with the first earlier member its etype may merge with. That
   is connected, deterministic and linear. Every pair the plan's union-find needs is in it, and
   the log does not grow quadratically on a common name.
4. **The union direction.** 06:1755 defines `merge_hops` as depth in the forest before path
   compression, but not which root goes under which. Here a pair's endpoints are ordered by
   identity `(key, etype, scope)` -- the durable attributes 06:1878 names as the tie-breaks -- and
   the second endpoint's root goes under the first's. So the forest, and every `merge_hops`, is a
   function of the sorted pair set alone.
5. **A pass's pair that a user split blocks is not written.** A live positive row joining two
   entities a `polarity = -1` row keeps apart would contradict the closure, and `ow store verify`
   clause 12 refuses exactly that. The report counts them.
6. **`resolution_trust` of an entity in no merge is `AMBIGUOUS` (0),** the value the sink mints.
   06:1854 defines it as a `MIN` over the closure's merge rows, and the `MIN` of no rows is the
   column's default.
7. **`loser_id` and `winner_id` order the pair, not the cluster.** `winner_id` is the endpoint
   first in identity order. The survivor is the closure's, and a row never names it, because the
   survivor of a cluster can change when a later pair joins it while the row stays as it was.
9. **Fuzzy evidence is the entity's live mentions** (D685). Two entities are cross-document --
   so a long label is scored with plain Jaro -- when no document holds a live mention of both;
   an entity with no live mention is cross-document to everything. They co-occur, and need 97,
   when one Segment holds a live mention of each.
10. **`scoped_label_crossdoc` blocks two document-scoped entities of different documents** at
    the fuzzy stage too; the exact stage never meets the pair, because it groups by scope.
11. **The cohesion re-check drops fuzzy pairs only** (D685). 06:1784 drops every pair scoring
    below 82 against the survivor, but an `exact` or `user` pair joins two entities whose keys
    may share nothing (`ibm` / `international_business_machines`, by an alias); scoring those
    against a key would split what the exact stage and a human decided. So a member whose key
    scores below 82 against the survivor's loses its `lsh_jw` pairs, union-find runs again, and
    the check repeats until nothing drops -- which is what makes it idempotent. A dropped pair is
    one `quarantine` row (`OW_GRAPH_COHESION_SPLIT`, `row_kind='merge'`), written once.
8. **A run row only when there is a new merge to point it at.** `entity_merge.run_id` needs
   one; nothing else does. An unchanged corpus therefore writes nothing at all -- the
   property `test_free_passes_at_ingest` asserts of every Pass -- and a retirement or a
   closure update is a derived write the generation already dates.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import ResourceLimit
from omniweave_core.model.enums import Method, Taint, Trust, enum_val_rows

from omniweave.graph import fuzzy

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "MAX_CANDIDATE_PAIRS",
    "OP_RESOLVE",
    "Closure",
    "Node",
    "Pair",
    "ResolveReport",
    "TypeGate",
    "closure",
    "funnel",
    "resolve",
    "total_order",
]

OP_RESOLVE: Final = "op.resolve"
RESOLVE_VERSION: Final = 2
"""2 since D685: the fuzzy stages."""
RESOLVE_PHASE: Final = 50
"""06:832's row 9: rank 0, phase 50 -- after `op.lexicon`'s 40."""
MAX_CANDIDATE_PAIRS: Final = 5_000_000
"""06:1789. A refusal with a named remedy, never a truncation: a truncated pair set would make
resolution depend on which pairs came first, which is what GR6 exists to rule out."""
SCORE_WHEN_NULL: Final = 100.0
"""06:1735's `COALESCE(score, 100.0)`: an exact merge has no score and is the most certain."""
SIGNATURE_KEY: Final = "graph.resolve_signature"
"""`meta`'s key (0001:63, 06:1811): what the persisted bands were built under."""
COHESION_CODE: Final = "OW_GRAPH_COHESION_SPLIT"

_METHOD_ORD: Final = {
    name: ordinal for domain, ordinal, name in enum_val_rows() if domain == "method"
}


@dataclass(frozen=True, slots=True)
class Node:
    """One live entity, as the funnel sees it."""

    entity_id: int
    scope: int
    etype: str
    key: str
    names: frozenset[str]

    @property
    def identity(self) -> tuple[str, str, int]:
        """Ruling 4: the durable attributes, in the order the total order compares them."""
        return (self.key, self.etype, self.scope)


@dataclass(frozen=True, slots=True)
class Pair:
    """One positive decision: `a` before `b` in identity order (ruling 7)."""

    a: int
    b: int
    stage: str
    trust: Trust
    method: Method
    score: float | None = None
    score_kind: str | None = None
    guards: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TypeGate:
    """`etype_vocab`'s `resolution` and `compatible` columns: stage [2]."""

    resolution: Mapping[str, str]
    compatible: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def admits(self, left: str, right: str) -> bool:
        """06:1709: equal or in each other's `compatible` set, and neither `none`."""
        if "none" in (self.resolution.get(left, "none"), self.resolution.get(right, "none")):
            return False
        if left == right:
            return True
        return right in self.compatible.get(left, ()) and left in self.compatible.get(right, ())


@dataclass(frozen=True, slots=True)
class Closure:
    canonical: Mapping[int, int]
    """`entity_id` -> its survivor's, for every node."""
    kept: tuple[Pair, ...]
    """The pass's pairs that are live decisions, in total order."""
    blocked: tuple[Pair, ...]
    """The pass's pairs a user split keeps apart (ruling 5). Never written."""
    hops: Mapping[int, int]
    """`merge_hops`: depth in the forest before path compression (06:1755)."""


def funnel(nodes: Sequence[Node], gate: TypeGate) -> list[Pair]:
    """Stages [1] and [2]: the exact-key pairs (rulings 1-3).

    Raises:
        ResourceLimit: more than `MAX_CANDIDATE_PAIRS` pairs (06:1789).
    """
    groups: dict[tuple[int, str], list[Node]] = defaultdict(list)
    for node in nodes:
        for name in node.names:
            groups[(node.scope, name)].append(node)
    pairs: dict[tuple[int, int], Pair] = {}
    for _scope_name, members in sorted(groups.items()):
        if len(members) < 2:  # noqa: PLR2004 -- a pair is two
            continue
        ordered = sorted(members, key=lambda n: n.identity)
        for index, member in enumerate(ordered):
            first = next((o for o in ordered[:index] if gate.admits(o.etype, member.etype)), None)
            if first is None or (first.entity_id, member.entity_id) in pairs:
                continue
            pairs[(first.entity_id, member.entity_id)] = Pair(
                a=first.entity_id,
                b=member.entity_id,
                stage="exact",
                trust=Trust.EXTRACTED,
                method=Method.HEURISTIC,
                guards=("scoped_label_crossdoc",),
            )
            if len(pairs) > MAX_CANDIDATE_PAIRS:
                raise ResourceLimit(
                    f"op.resolve found more than {MAX_CANDIDATE_PAIRS} candidate pairs",
                    limit="MAX_CANDIDATE_PAIRS",
                    fix="set etype_vocab.resolution = 'exact_only' or 'none' for the etype with "
                    "the most shared names, then ow ingest again",
                )
    return list(pairs.values())


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where an entity is mentioned (ruling 9): its live mentions' documents and Segments."""

    docs: frozenset[int] = frozenset()
    segments: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class Fuzzy:
    """Stages [3]-[5] and [7] over the band candidates."""

    pairs: tuple[Pair, ...]
    candidates: int
    ambiguous: int
    """Pairs in `[75, threshold)`: the LLM band's, not built, so left (D685)."""
    guarded: Mapping[str, int]
    """Guard name -> candidate pairs it blocked."""


def eligible(node: Node, gate: TypeGate) -> bool:
    """Stage [3] and the type's policy: a `fuzzy` etype and a key of `ENTROPY_MIN` or more."""
    return (
        gate.resolution.get(node.etype) == "fuzzy" and fuzzy.entropy(node.key) >= fuzzy.ENTROPY_MIN
    )


def fuzzy_stage(
    nodes: Mapping[int, Node],
    gate: TypeGate,
    candidates: Iterable[tuple[int, int]],
    evidence: Mapping[int, Evidence],
    *,
    exact: Iterable[Pair] = (),
) -> Fuzzy:
    """Verify each band candidate: type gate, scope, guards, then the score (rulings 9-10)."""
    joined = {frozenset((p.a, p.b)) for p in exact}
    pairs: list[Pair] = []
    guarded: dict[str, int] = defaultdict(int)
    ambiguous = 0
    seen = 0
    none = Evidence()
    for left_id, right_id in sorted(set(candidates)):
        if left_id not in nodes or right_id not in nodes or left_id == right_id:
            continue
        seen += 1
        first, second = sorted((nodes[left_id], nodes[right_id]), key=lambda n: n.identity)
        if frozenset((first.entity_id, second.entity_id)) in joined:
            continue
        if not (eligible(first, gate) and eligible(second, gate)):
            continue
        if not gate.admits(first.etype, second.etype):
            continue
        if first.scope and second.scope and first.scope != second.scope:
            guarded["scoped_label_crossdoc"] += 1
            continue
        left, right = fuzzy.label(first.key), fuzzy.label(second.key)
        guard = fuzzy.blocked_by(left, right)
        if guard is not None:
            guarded[guard] += 1
            continue
        here, there = evidence.get(first.entity_id, none), evidence.get(second.entity_id, none)
        score = round(fuzzy.verify(left, right, cross_document=not (here.docs & there.docs)), 4)
        together = bool(here.segments & there.segments)
        threshold = fuzzy.COOCCURRENCE_THRESHOLD if together else fuzzy.MERGE_THRESHOLD
        if score < threshold:
            if score >= fuzzy.AMBIGUOUS_LOW:
                ambiguous += 1
            if together and score >= fuzzy.MERGE_THRESHOLD:
                guarded["cooccurrence_in_segment"] += 1
            continue
        pairs.append(
            Pair(
                a=first.entity_id,
                b=second.entity_id,
                stage="lsh_jw",
                trust=Trust.INFERRED,
                method=Method.HEURISTIC,
                score=score,
                score_kind="jaro_winkler",
                guards=(
                    *(name for name, _ in fuzzy.GUARDS),
                    "scoped_label_crossdoc",
                    "cooccurrence_in_segment",
                ),
            )
        )
    return Fuzzy(pairs=tuple(pairs), candidates=seen, ambiguous=ambiguous, guarded=dict(guarded))


def cohesive(
    nodes: Sequence[Node],
    pairs: Sequence[Pair],
    *,
    user_merges: Iterable[Pair] = (),
    user_splits: Iterable[tuple[int, int]] = (),
) -> tuple[Closure, tuple[tuple[Pair, int, float], ...]]:
    """Stages [9] and [10] (ruling 11): the closure, re-run until no fuzzy pair drops.

    Returns the final closure and every dropped pair with the member it was dropped for and that
    member's score against its survivor.
    """
    by_id = {node.entity_id: node for node in nodes}
    users = tuple(user_merges)
    splits = tuple(user_splits)
    live = list(pairs)
    dropped: list[tuple[Pair, int, float]] = []
    floor = fuzzy.MERGE_THRESHOLD - fuzzy.COHESION_SPLIT_DELTA
    for _ in range(len(live) + 1):
        found = closure(nodes, live, user_merges=users, user_splits=splits)
        loose: dict[int, float] = {}
        for member, survivor in sorted(found.canonical.items()):
            if member == survivor or not any(
                p.stage == "lsh_jw" and member in (p.a, p.b) for p in found.kept
            ):
                continue
            score = fuzzy.verify(
                fuzzy.label(by_id[member].key),
                fuzzy.label(by_id[survivor].key),
                cross_document=False,
            )
            if score < floor:
                loose[member] = round(score, 4)
        if not loose:
            return found, tuple(dropped)
        keep: list[Pair] = []
        for pair in live:
            member = pair.a if pair.a in loose else pair.b if pair.b in loose else None
            if pair.stage == "lsh_jw" and member is not None:
                dropped.append((pair, member, loose[member]))
            else:
                keep.append(pair)
        live = keep
    return closure(nodes, live, user_merges=users, user_splits=splits), tuple(dropped)


def total_order(pairs: Iterable[Pair], nodes: Mapping[int, Node]) -> list[Pair]:
    """06:1733: `(-COALESCE(score, 100.0), min(identity), max(identity))`."""

    def rank(pair: Pair) -> tuple[float, tuple[str, str, int], tuple[str, str, int]]:
        left, right = nodes[pair.a].identity, nodes[pair.b].identity
        score = SCORE_WHEN_NULL if pair.score is None else pair.score
        return (-score, min(left, right), max(left, right))

    return sorted(pairs, key=rank)


def closure(
    nodes: Sequence[Node],
    pairs: Iterable[Pair],
    *,
    user_merges: Iterable[Pair] = (),
    user_splits: Iterable[tuple[int, int]] = (),
) -> Closure:
    """Stage [9]: union-find over the whole live pair set, rebuilt every time (06:1762).

    The pass's pairs go first, in the total order; then the user's merges, in theirs (06:1740 --
    *"`stage='user'` rows are excluded from this pass entirely and applied afterwards"*). A user
    split is a blocking pair for both: a union that would put its two ends in one set is skipped.
    """
    by_id = {node.entity_id: node for node in nodes}
    parent: dict[int, int] = {}
    members: dict[int, set[int]] = {node.entity_id: {node.entity_id} for node in nodes}
    apart: dict[int, set[int]] = defaultdict(set)
    for left, right in user_splits:
        apart[left].add(right)
        apart[right].add(left)

    def root(entity_id: int) -> int:
        while entity_id in parent:
            entity_id = parent[entity_id]
        return entity_id

    def union(pair: Pair) -> bool:
        first, second = sorted((pair.a, pair.b), key=lambda e: by_id[e].identity)
        top, under = root(first), root(second)
        if top == under:
            return True
        if any(apart[e] & members[under] for e in members[top]):
            return False
        parent[under] = top
        members[top] |= members.pop(under)
        return True

    kept: list[Pair] = []
    blocked: list[Pair] = []
    for pair in total_order([p for p in pairs if p.a in by_id and p.b in by_id], by_id):
        (kept if union(pair) else blocked).append(pair)
    for pair in total_order([p for p in user_merges if p.a in by_id and p.b in by_id], by_id):
        union(pair)

    def depth(entity_id: int) -> int:
        hops = 0
        while entity_id in parent:
            entity_id = parent[entity_id]
            hops += 1
        return hops

    hops = {entity_id: depth(entity_id) for entity_id in by_id}
    canonical: dict[int, int] = {}
    for group in members.values():
        survivor = min(
            group,
            key=lambda e: (hops[e], -len(by_id[e].names), by_id[e].identity),
        )
        for entity_id in group:
            canonical[entity_id] = survivor
    return Closure(canonical=canonical, kept=tuple(kept), blocked=tuple(blocked), hops=hops)


# ---------------------------------------------------------------------------------------------
# The store: one read, one write, in the caller's transaction.
# ---------------------------------------------------------------------------------------------

_NODES_SQL: Final = "SELECT entity_id, scope, etype, key FROM entity WHERE state = 0"
_ALIASES_SQL: Final = """
SELECT a.entity_id, a.name_norm FROM entity_alias AS a JOIN entity AS e ON e.entity_id = a.entity_id
 WHERE e.state = 0 AND NOT (a.taint & :untrusted AND a.doc_count = 1)
"""
_VOCAB_SQL: Final = "SELECT etype, resolution, compatible FROM etype_vocab"
_EVIDENCE_SQL: Final = """
SELECT m.entity_id, m.segment_id, b.doc_ord FROM mention AS m
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
 WHERE m.state = 0
"""
_META_SQL: Final = "SELECT v FROM meta WHERE k = :k"
_META_SET_SQL: Final = (
    "INSERT INTO meta(k, v) VALUES(:k, :v) ON CONFLICT(k) DO UPDATE SET v = excluded.v"
)
_BANDED_SQL: Final = "SELECT DISTINCT entity_id FROM entity_band"
_UNBAND_SQL: Final = "DELETE FROM entity_band WHERE entity_id = :entity_id"
_UNBAND_ALL_SQL: Final = "DELETE FROM entity_band"
_BAND_SQL: Final = (
    "INSERT OR IGNORE INTO entity_band(band, bucket, etype, entity_id)"
    " VALUES(:band, :bucket, :etype, :entity_id)"
)
_CANDIDATES_SQL: Final = """
SELECT DISTINCT a.entity_id, b.entity_id FROM entity_band AS a
  JOIN entity_band AS b ON b.band = a.band AND b.bucket = a.bucket AND b.entity_id > a.entity_id
"""
_QUARANTINED_SQL: Final = "SELECT payload FROM quarantine WHERE code = :code"
_QUARANTINE_SQL: Final = """
INSERT INTO quarantine(code, run_id, row_kind, payload, block_id, detail, at_gen)
VALUES(:code, :run_id, 'merge', :payload, NULL, :detail, :gen)
"""
_USER_SQL: Final = """
SELECT loser_id, winner_id, polarity, trust FROM entity_merge
 WHERE stage = 'user' AND retired_at_gen IS NULL
"""
_LIVE_SQL: Final = """
SELECT merge_id, loser_id, winner_id, stage FROM entity_merge
 WHERE stage <> 'user' AND polarity = 1 AND retired_at_gen IS NULL
"""
_RETIRE_SQL: Final = "UPDATE entity_merge SET retired_at_gen = :gen WHERE merge_id = :merge_id"
_INSERT_SQL: Final = """
INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, score, score_kind,
                         guards, reason, run_id, decided_at_gen)
VALUES(:loser, :winner, 1, :stage, :method, :trust, :score, :score_kind, :guards, NULL, :run_id,
       :gen)
"""
_CANONICAL_SQL: Final = """
UPDATE entity SET canonical_id = :canonical, resolution_trust = :trust
 WHERE entity_id = :entity_id AND (canonical_id <> :canonical OR resolution_trust <> :trust)
"""
_REGISTER_SQL: Final = """
INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, granularity,
                        card_sha256, schema_version)
VALUES(:pass_id, 'op', 'free', 0, :phase, '["entity"]', 'corpus', :signature, :version)
ON CONFLICT(pass_id) DO UPDATE SET phase = excluded.phase, card_sha256 = excluded.card_sha256,
                                   schema_version = excluded.schema_version
"""
_PRODUCER_INSERT_SQL: Final = """
INSERT OR IGNORE INTO producer(operator, op_version, code_fingerprint, options_digest)
VALUES(:operator, :op_version, '', :options_digest)
"""
_PRODUCER_ID_SQL: Final = """
SELECT producer_id FROM producer
 WHERE operator = :operator AND op_version = :op_version AND code_fingerprint = ''
   AND options_digest = :options_digest AND model_id IS NULL AND model_rev IS NULL
   AND runtime IS NULL AND runtime_version IS NULL AND prompt_fp IS NULL
"""
_RUN_SQL: Final = """
INSERT OR IGNORE INTO derive_run(segment_id, pass_id, at_gen, producer_id, method, origin_operator,
                                 origin_driver, driver_schema_v, cost_class, decision_id,
                                 input_digest, cache_key, status, n_items, n_quarantined, spend)
VALUES(NULL, :pass_id, :gen, :producer_id, :method, :pass_id, :pass_id, :version, 'free', NULL,
       :input_digest, :cache_key, :status, :n_items, 0, '{}')
"""
_RUN_ID_SQL: Final = (
    "SELECT run_id FROM derive_run"
    " WHERE pass_id = :pass_id AND segment_id IS NULL AND at_gen = :gen"
)
_RUN_UPDATE_SQL: Final = """
UPDATE derive_run SET status = :status, n_items = :n_items, input_digest = :input_digest,
                      cache_key = :cache_key
 WHERE run_id = :run_id
"""
_SIGNATURE: Final = json.dumps(
    {
        "pass": OP_RESOLVE,
        "version": RESOLVE_VERSION,
        "stages": ["exact", "lsh_jw"],
        "entropy_min": fuzzy.ENTROPY_MIN,
        "num_perm": fuzzy.NUM_PERM,
        "bands": fuzzy.BANDS,
        "lsh_threshold": fuzzy.LSH_THRESHOLD,
        "shingle_k": fuzzy.SHINGLE_K,
        "merge_threshold": fuzzy.MERGE_THRESHOLD,
        "minhash": "blake2b-8, (a*x+b) mod 2**61-1",
    },
    sort_keys=True,
).encode()
"""What this pass's decisions are a function of besides the rows: its stages. A new stage is a new
signature, so the `producer` row a run points at says which funnel decided."""


@dataclass(frozen=True, slots=True)
class ResolveReport:
    """One `op.resolve` run, for `IngestReport`."""

    entities: int
    clusters: int
    """Components of two or more entities."""
    merged: int
    """Entities whose `canonical_id` is another's."""
    added: int
    retired: int
    kept: int
    blocked: int
    changed: int
    """Entities whose `canonical_id` or `resolution_trust` this run rewrote."""
    fuzzy: int = 0
    """Live `lsh_jw` merges (D685)."""
    candidates: int = 0
    ambiguous: int = 0
    guarded: Mapping[str, int] = field(default_factory=dict)
    split: int = 0
    """Fuzzy pairs the cohesion re-check dropped this run."""
    rebanded: bool = False
    """The bands were rebuilt: the stored signature was another's, or there was none."""

    def line(self) -> str:
        guards = ", ".join(f"{k} {v}" for k, v in sorted(self.guarded.items()))
        return (
            f"  resolve   {self.entities} entities, {self.clusters} cluster(s) holding "
            f"{self.merged} merged; {self.kept} live merge(s) ({self.fuzzy} fuzzy): {self.added} "
            f"new, {self.retired} retired"
            + (f", {self.blocked} blocked by a user split" if self.blocked else "")
            + (f"; {self.candidates} fuzzy candidate(s)" if self.candidates else "")
            + (f", {self.ambiguous} left in the unbuilt LLM band" if self.ambiguous else "")
            + (f", guarded: {guards}" if guards else "")
            + (f", {self.split} split for cohesion" if self.split else "")
        )

    @property
    def shown(self) -> bool:
        return bool(self.kept or self.added or self.retired or self.blocked or self.changed)


def resolve(connection: Any, *, gen: int) -> ResolveReport:
    """Read the live entities, run the funnel and the closure, write the log and the closure."""
    nodes = _nodes(connection)
    gate = _gate(connection)
    users = connection.execute(_USER_SQL).fetchall()
    user_merges = [
        Pair(a=int(r[1]), b=int(r[0]), stage="user", trust=Trust(int(r[3])), method=Method.USER)
        for r in users
        if int(r[2]) == 1
    ]
    splits = [(int(r[0]), int(r[1])) for r in users if int(r[2]) == -1]
    by_id = {node.entity_id: node for node in nodes}
    exact = funnel(nodes, gate)
    rebanded = _bands(connection, nodes, gate)
    candidates = [(int(a), int(b)) for a, b in connection.execute(_CANDIDATES_SQL).fetchall()]
    if len(candidates) > MAX_CANDIDATE_PAIRS:
        raise ResourceLimit(
            f"op.resolve's bands produced {len(candidates)} candidate pairs",
            limit="MAX_CANDIDATE_PAIRS",
            fix="set etype_vocab.resolution = 'exact_only' for the etype with the most entities, "
            "then ow ingest again",
        )
    fuzzed = fuzzy_stage(by_id, gate, candidates, _evidence(connection), exact=exact)
    found, dropped = cohesive(
        nodes, [*exact, *fuzzed.pairs], user_merges=user_merges, user_splits=splits
    )
    wanted = {(p.b, p.a, p.stage): p for p in found.kept}
    live = {
        (int(r[1]), int(r[2]), str(r[3])): int(r[0])
        for r in connection.execute(_LIVE_SQL).fetchall()
    }
    retired = 0
    for identity, merge_id in sorted(live.items(), key=lambda kv: kv[1]):
        if identity not in wanted:
            connection.execute(_RETIRE_SQL, {"gen": gen, "merge_id": merge_id})
            retired += 1
    added = 0
    run_id: int | None = None
    for identity, pair in wanted.items():
        if identity in live:
            continue
        if run_id is None:  # ruling 8: a run row only for a run that decides something
            run_id = _run(connection, gen, found.kept)
        connection.execute(
            _INSERT_SQL,
            {
                "loser": pair.b,
                "winner": pair.a,
                "stage": pair.stage,
                "method": _METHOD_ORD[pair.method.name.lower()],
                "trust": int(pair.trust),
                "score": pair.score,
                "score_kind": pair.score_kind,
                "guards": json.dumps(list(pair.guards)),
                "run_id": run_id,
                "gen": gen,
            },
        )
        added += 1
    split = 0
    if dropped:
        known = {str(r[0]) for r in connection.execute(_QUARANTINED_SQL, {"code": COHESION_CODE})}
        for pair, member, score in dropped:
            payload = json.dumps(
                {"a": by_id[pair.a].key, "b": by_id[pair.b].key, "etype": by_id[pair.a].etype,
                 "score": pair.score},
                sort_keys=True,
            )  # fmt: skip
            split += 1
            if payload in known:
                continue
            if run_id is None:
                run_id = _run(connection, gen, found.kept)
            detail = {"member": by_id[member].key, "survivor_score": score}
            connection.execute(
                _QUARANTINE_SQL,
                {"code": COHESION_CODE, "run_id": run_id, "payload": payload,
                 "detail": json.dumps(detail, sort_keys=True), "gen": gen},
            )  # fmt: skip
            known.add(payload)
    trust = _resolution_trust(found, user_merges)
    changed = 0
    for entity_id in sorted(by_id):
        changed += connection.execute(
            _CANONICAL_SQL,
            {
                "entity_id": entity_id,
                "canonical": found.canonical[entity_id],
                "trust": int(trust.get(found.canonical[entity_id], Trust.AMBIGUOUS)),
            },
        ).rowcount
    sizes: dict[int, int] = defaultdict(int)
    for survivor in found.canonical.values():
        sizes[survivor] += 1
    return ResolveReport(
        entities=len(nodes),
        clusters=sum(1 for size in sizes.values() if size > 1),
        merged=sum(1 for e, c in found.canonical.items() if e != c),
        added=added,
        retired=retired,
        kept=len(found.kept),
        blocked=len(found.blocked),
        changed=changed,
        fuzzy=sum(1 for p in found.kept if p.stage == "lsh_jw"),
        candidates=fuzzed.candidates,
        ambiguous=fuzzed.ambiguous,
        guarded=fuzzed.guarded,
        split=split,
        rebanded=rebanded,
    )


def _evidence(connection: Any) -> dict[int, Evidence]:
    docs: dict[int, set[int]] = defaultdict(set)
    segments: dict[int, set[int]] = defaultdict(set)
    for entity_id, segment_id, doc_ord in connection.execute(_EVIDENCE_SQL).fetchall():
        docs[int(entity_id)].add(int(doc_ord))
        if segment_id is not None:
            segments[int(entity_id)].add(int(segment_id))
    return {
        e: Evidence(docs=frozenset(docs[e]), segments=frozenset(segments.get(e, ()))) for e in docs
    }


def _bands(connection: Any, nodes: Sequence[Node], gate: TypeGate) -> bool:
    """Keep `entity_band` the bands of exactly the eligible live entities. Returns whether it was
    rebuilt whole: 06:1811 -- a signature mismatch REBUILDS rather than warns.

    Incremental otherwise, and that is the point of persisting them: an entity's key never changes
    (it is the `UNIQUE (scope, etype, key)` identity), so its bands never do, and a run that added
    no entity computes no signature and writes no row.
    """
    current = hashlib.sha256(_SIGNATURE).hexdigest()
    stored = connection.execute(_META_SQL, {"k": SIGNATURE_KEY}).fetchone()
    rebuilt = stored is None or str(stored[0]) != current
    if rebuilt:
        connection.execute(_UNBAND_ALL_SQL)
        connection.execute(_META_SET_SQL, {"k": SIGNATURE_KEY, "v": current})
    banded = {int(r[0]) for r in connection.execute(_BANDED_SQL).fetchall()}
    wanted = {node.entity_id: node for node in nodes if eligible(node, gate)}
    for entity_id in sorted(banded - set(wanted)):
        connection.execute(_UNBAND_SQL, {"entity_id": entity_id})
    for entity_id in sorted(set(wanted) - banded):
        node = wanted[entity_id]
        sig = fuzzy.signature(fuzzy.shingles(fuzzy.label(node.key)))
        for band, bucket in enumerate(fuzzy.bands(sig)):
            connection.execute(
                _BAND_SQL,
                {"band": band, "bucket": bucket, "etype": node.etype, "entity_id": entity_id},
            )
    return rebuilt


def _nodes(connection: Any) -> list[Node]:
    names: dict[int, set[str]] = defaultdict(set)
    params = {"untrusted": int(Taint.UNTRUSTED_SOURCE)}
    for entity_id, name in connection.execute(_ALIASES_SQL, params).fetchall():
        names[int(entity_id)].add(str(name))
    return [
        Node(
            entity_id=int(e),
            scope=int(s),
            etype=str(t),
            key=str(k),
            names=frozenset({str(k), *names.get(int(e), ())}),
        )
        for e, s, t, k in connection.execute(_NODES_SQL).fetchall()
    ]


def _gate(connection: Any) -> TypeGate:
    resolution: dict[str, str] = {}
    compatible: dict[str, frozenset[str]] = {}
    for etype, how, raw in connection.execute(_VOCAB_SQL).fetchall():
        resolution[str(etype)] = str(how)
        try:
            listed = json.loads(str(raw))
        except ValueError:
            listed = []
        compatible[str(etype)] = frozenset(str(x) for x in listed if isinstance(x, str))
    return TypeGate(resolution=resolution, compatible=compatible)


def _resolution_trust(found: Closure, user_merges: Sequence[Pair]) -> dict[int, Trust]:
    """06:1854: `MIN` over the merge rows in the cluster, per survivor (ruling 6)."""
    out: dict[int, Trust] = {}
    for pair in (*found.kept, *user_merges):
        if pair.a not in found.canonical:
            continue
        survivor = found.canonical[pair.a]
        if found.canonical.get(pair.b) != survivor:
            continue  # a user merge a split blocked
        out[survivor] = min(out.get(survivor, pair.trust), pair.trust)
    return out


def _run(connection: Any, gen: int, kept: Sequence[Pair]) -> int:
    """The corpus-level `derive_run` every row this pass writes points at (`segment_id` NULL)."""
    digest = hashlib.sha256(_SIGNATURE).digest()
    connection.execute(
        _REGISTER_SQL,
        {
            "pass_id": OP_RESOLVE,
            "phase": RESOLVE_PHASE,
            "signature": digest.hex(),
            "version": RESOLVE_VERSION,
        },
    )
    producer = {"operator": OP_RESOLVE, "op_version": RESOLVE_VERSION, "options_digest": digest}
    connection.execute(_PRODUCER_INSERT_SQL, producer)
    producer_id = int(connection.execute(_PRODUCER_ID_SQL, producer).fetchone()[0])
    decided = json.dumps(sorted([p.a, p.b, p.stage] for p in kept)).encode()
    params = {
        "pass_id": OP_RESOLVE,
        "gen": gen,
        "producer_id": producer_id,
        "method": _METHOD_ORD[Method.HEURISTIC.name.lower()],
        "version": RESOLVE_VERSION,
        "input_digest": hashlib.blake2b(decided, digest_size=16).digest(),
        "cache_key": hashlib.sha256(decided).hexdigest(),
        "status": "ok" if kept else "empty",
        "n_items": len(kept),
    }
    connection.execute(_RUN_SQL, params)
    run_id = int(connection.execute(_RUN_ID_SQL, params).fetchone()[0])
    connection.execute(_RUN_UPDATE_SQL, {**params, "run_id": run_id})
    return run_id
