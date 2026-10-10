"""`op.cluster`: Louvain over the live graph, kept as a durable community tree. D690.

06-structure-extraction.md section 6.1 (clustering is core), section 6.4 (re-cluster always,
re-report only what moved) and STEP 6 of section 10.1 are the specification.
`omniweave.graph.louvain` holds the arithmetic and rulings 1-7. This module reads the store, maps
entities to node indices and back, and reconciles the tree with the `community` rows already there,
in the caller's transaction.

## Rulings (the ledger's D690, continued)

8. **The graph is the canonical heads and their live edges.** An edge counts while its observed
   block is live and both its ends are live entities. Each end is read as its `canonical_id`, so a
   merge folds its members' edges onto the survivor, and an edge whose two ends merged is a
   self-loop and drops. An entity with no such edge is in no community: a folder of unrelated PDFs
   is a forest of isolates, and a community of one gives a report nothing to say.
9. **A node's place is its natural identity**, `(scope, etype, key)`, with a document scope read as
   its `doc_key` (`canonical_projection()`'s reading 1). Surrogate ids order nothing, so a full and
   an incremental build of one graph give one partition.
10. **`member_digest` is over the members' natural identities**, not their `entity_id`s. 06:2008
    says "sorted canonical member ids", but GR8 compares the digest multiset across two stores
    whose ids differ, and 06:2416 excludes surrogate ids from that comparison. The digest is
    `ow128(b'ow.community.1', [[scope, etype, key], ...])` in identity order.
11. **"The last" duplicate is the last in natural order.** The rows for one node pair are sorted by
    `(relation, observed doc_key, addr, ts_a, weight)` before `normalise()` keeps the last, because
    `edge_id` is a surrogate.
12. **`community_id` is carried by `member_digest`, then by overlap.** A community whose digest a
    row already holds keeps that row's id, reviving it if it was retired. The rest are matched one
    to one with the unmatched live rows of the same level, greatest overlap first, ties to the lower
    id (graphify's `remap_communities_to_previous`). A matched row whose digest moves is the case
    06:2002's `UPDATE` exists for: its report goes `stale`. An unmatched row is retired (`state =
    1`, and a `graph_history` row holding its members). A new community is a new row with an
    `absent` report (06:1958).
13. **`trust` is the weakest internal edge's, and at most `INFERRED`**, because a grouping is
    inferred however its edges were observed. `taint` ORs its members' and its internal edges'.
    Taint ORs upward and never across edges, and a community sits above both.
14. **`cluster_run` counts the clustering runs that wrote, and `run_id` is the `derive_run` that
    last wrote the row.** A run that changes nothing writes nothing: no run row and no registry row.
    A retirement alone needs no run row, as `op.resolve`'s does not (D684 ruling 8).
15. **A retired community's report goes stale.** `community_report_fresh` (0002) joins `community`
    without reading `state`, so a `fresh` report of a retired row would still be served. Retirement
    is the row leaving, and its report leaves with it; a revival by digest finds it `stale`, and the
    next descent writes it again.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.canonical import canonical, ow128
from omniweave_core.errors import GraphError
from omniweave_core.limits import MAX_CLUSTER_EDGES
from omniweave_core.model.enums import Method, Trust, enum_val_rows

from omniweave.graph import louvain

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "OP_CLUSTER",
    "TOO_LARGE",
    "ClusterReport",
    "Planned",
    "cluster",
    "plan",
]

OP_CLUSTER: Final = "op.cluster"
CLUSTER_VERSION: Final = 1
CLUSTER_RANK: Final = 1
CLUSTER_PHASE: Final = 10
"""06:834's row 10: rank 1, phase 10 -- the first `local_compute` Pass, after every free one."""
TOO_LARGE: Final = "OW_GRAPH_TOO_LARGE"
RETIRED: Final = 1
"""`community.state` of a row no clustering holds any more (ruling 12)."""
DIGEST_DOMAIN: Final = b"ow.community.1"

_METHOD_ORD: Final = {
    name: ordinal for domain, ordinal, name in enum_val_rows() if domain == "method"
}

Identity = tuple[str, str, str]
"""`(scope, etype, key)`, a document scope as its `doc_key` in hex (ruling 9)."""


@dataclass(frozen=True, slots=True)
class Planned:
    """One community of this run's tree, in store terms."""

    members: tuple[int, ...]
    """`entity_id`s of canonical heads, in identity order."""
    digest: bytes
    level: int
    parent: int | None
    """Index of the parent in the plan, parents first."""
    component: int
    size: int
    cohesion: float
    trust: int
    taint: int
    split: str


@dataclass(frozen=True, slots=True)
class ClusterReport:
    """One `op.cluster` run, for `IngestReport`."""

    entities: int
    """Canonical heads with a live edge: the nodes."""
    edges: int
    """Node pairs after the fold, the direction normalised and duplicates dropped."""
    components: int
    communities: int
    levels: int
    added: int = 0
    changed: int = 0
    retired: int = 0
    split: int = 0
    """Leaves re-split for size or cohesion, or cut (rulings 4 and 5)."""
    stale: int = 0
    """Reports this run made stale: their community's `member_digest` moved."""

    def line(self) -> str:
        return (
            f"  cluster   {self.communities} communities over {self.entities} entities and "
            f"{self.edges} edges in {self.components} component(s), {self.levels} level(s): "
            f"{self.added} new, {self.changed} changed, {self.retired} retired"
            + (f"; {self.split} re-split" if self.split else "")
            + (f"; {self.stale} report(s) stale" if self.stale else "")
        )

    @property
    def shown(self) -> bool:
        return bool(self.communities or self.added or self.changed or self.retired)


def plan(
    identities: Mapping[int, Identity],
    taints: Mapping[int, int],
    rows: Sequence[tuple[int, int, float, tuple[object, ...], int, int]],
) -> tuple[list[Planned], int, int]:
    """Rulings 9-11 and 13 around `louvain.communities()`. Pure.

    `rows` are `(head, head, weight, natural, trust, taint)`, one per live edge, already folded
    onto canonical heads; `natural` is the row's place among its pair's duplicates. Returns the
    tree, the node count and the deduplicated edge count.

    Raises:
        GraphError: `OW_GRAPH_TOO_LARGE`, above `MAX_CLUSTER_EDGES` (06:1944).
    """
    used = sorted(
        {e for a, b, *_ in rows if a != b for e in (a, b)}, key=lambda e: (identities[e], e)
    )
    index = {entity_id: position for position, entity_id in enumerate(used)}
    ordered: list[tuple[int, int, tuple[object, ...], float]] = []
    trust: dict[tuple[int, int], int] = {}
    taint: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, weight, natural, edge_trust, edge_taint in rows:
        if a == b:
            continue
        lo, hi = sorted((index[a], index[b]))
        ordered.append((lo, hi, natural, weight))
        trust[(lo, hi)] = min(trust.get((lo, hi), edge_trust), edge_trust)
        taint[(lo, hi)] |= edge_taint
    ordered.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    edges = louvain.normalise((lo, hi, weight) for lo, hi, _natural, weight in ordered)
    if len(edges) > MAX_CLUSTER_EDGES:
        raise GraphError(
            f"op.cluster refuses {len(edges)} edges: above MAX_CLUSTER_EDGES = "
            f"{MAX_CLUSTER_EDGES}. omniweave-driver-leiden is the driver seam above the cap "
            "(06:1944), and pure-Python Louvain stops here",
            symbol=TOO_LARGE,
            fix="ow config set graph.passes.enable <the roster without the Pass writing the most "
            "edges>   # or omniweave-driver-leiden, the seam above MAX_CLUSTER_EDGES",
        )
    graph = louvain.csr(len(used), edges)
    out: list[Planned] = []
    for found in louvain.communities(graph):
        members = tuple(used[m] for m in found.members)
        inside = set(found.members)
        weakest, bits = int(Trust.INFERRED), 0
        for m in found.members:
            bits |= taints.get(used[m], 0)
            for p in range(graph.offsets[m], graph.offsets[m + 1]):
                other = graph.targets[p]
                if other > m and other in inside:
                    weakest = min(weakest, trust[(m, other)])
                    bits |= taint[(m, other)]
        out.append(
            Planned(
                members=members,
                digest=ow128(DIGEST_DOMAIN, [list(identities[e]) for e in members]),
                level=found.level,
                parent=found.parent,
                component=found.component,
                size=len(members),
                cohesion=found.cohesion,
                trust=weakest,
                taint=bits,
                split=found.split,
            )
        )
    return out, len(used), len(edges)


# ---------------------------------------------------------------------------------------------
# The store: one read, one reconciliation, in the caller's transaction.
# ---------------------------------------------------------------------------------------------

_HEADS_SQL: Final = """
SELECT e.entity_id, e.canonical_id,
       CASE WHEN e.scope = 0 THEN 'corpus' ELSE IFNULL(lower(hex(d.doc_key)), '') END,
       e.etype, e.key, e.taint
  FROM entity AS e LEFT JOIN doc AS d ON d.doc_ord = e.scope
 WHERE e.state = 0
"""
_EDGES_SQL: Final = """
SELECT g.src_entity, g.dst_entity, g.weight, g.relation, lower(hex(d.doc_key)), b.addr,
       IFNULL(g.ts_a, -1), g.trust, g.taint
  FROM edge AS g
  JOIN block AS b ON b.block_id = g.observed_block AND b.state = 0
  JOIN doc AS d ON d.doc_ord = b.doc_ord
"""
_ROWS_SQL: Final = """
SELECT community_id, member_digest, level, parent, component_ord, size, cohesion, trust, taint,
       state
  FROM community
"""
_MEMBERS_SQL: Final = """
SELECT m.community_id, m.entity_id FROM community_member AS m
  JOIN community AS c ON c.community_id = m.community_id
 WHERE c.state = 0
"""
_MEMBERS_OF_SQL: Final = (
    "SELECT entity_id FROM community_member WHERE community_id = :community_id ORDER BY 1"
)
_NEXT_ID_SQL: Final = "SELECT IFNULL(MAX(community_id), 0) + 1 FROM community"
_NEXT_RUN_SQL: Final = "SELECT IFNULL(MAX(cluster_run), 0) + 1 FROM community"
_INSERT_SQL: Final = """
INSERT INTO community(community_id, cite, level, parent, component_ord, cluster_run, size,
                      cohesion, member_digest, run_id, trust, taint, state)
VALUES(:community_id, :cite, :level, :parent, :component_ord, :cluster_run, :size, :cohesion,
       :member_digest, :run_id, :trust, :taint, 0)
"""
_UPDATE_SQL: Final = """
UPDATE community SET level = :level, parent = :parent, component_ord = :component_ord,
                     cluster_run = :cluster_run, size = :size, cohesion = :cohesion,
                     member_digest = :member_digest, run_id = :run_id, trust = :trust,
                     taint = :taint, state = 0
 WHERE community_id = :community_id
"""
_RETIRE_SQL: Final = "UPDATE community SET state = :state WHERE community_id = :community_id"
_MEMBER_SQL: Final = (
    "INSERT INTO community_member(community_id, entity_id) VALUES(:community_id, :entity_id)"
)
_UNMEMBER_SQL: Final = "DELETE FROM community_member WHERE community_id = :community_id"
_REPORT_SQL: Final = (
    "INSERT OR IGNORE INTO community_report(community_id, report_state) VALUES(:community_id,"
    " 'absent')"
)
_STALE_SQL: Final = """
UPDATE community_report SET report_state = 'stale'
 WHERE member_digest IS NOT NULL
   AND member_digest <> (SELECT member_digest FROM community c
                          WHERE c.community_id = community_report.community_id)
   AND report_state <> 'stale'
"""
"""06:2001-2006, verbatim but for its last line, which keeps a stale row from counting twice."""
_RETIRE_REPORT_SQL: Final = """
UPDATE community_report SET report_state = 'stale'
 WHERE community_id = :community_id AND report_state = 'fresh'
"""
"""Ruling 15: `community_report_fresh` joins `community` without reading its `state`."""
_HISTORY_SQL: Final = """
INSERT OR IGNORE INTO graph_history(kind, row_id, retired_gen, superseded_by, reason, payload)
VALUES('community', :row_id, :gen, :superseded_by, 'pass_replaced', :payload)
"""
_REGISTER_SQL: Final = """
INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, granularity,
                        card_sha256, schema_version)
VALUES(:pass_id, 'op', 'local_compute', :rank, :phase, '["community"]', 'corpus', :signature,
       :version)
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
VALUES(NULL, :pass_id, :gen, :producer_id, :method, :pass_id, :pass_id, :version, 'local_compute',
       NULL, :input_digest, :cache_key, :status, :n_items, 0, '{}')
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
        "pass": OP_CLUSTER,
        "version": CLUSTER_VERSION,
        "algorithm": "louvain",
        "seed": louvain.CLUSTER_SEED,
        "max_community_size": louvain.MAX_COMMUNITY_SIZE,
        "cohesion_split": louvain.COHESION_SPLIT,
        "cohesion_split_min": louvain.COHESION_SPLIT_MIN,
        "max_sweeps": louvain.MAX_SWEEPS,
        "sweep_order": "blake2b-8 keyed by the seed over depth:node",
    },
    sort_keys=True,
).encode()
"""What a partition is a function of besides the edges, for the `producer` row a run points at."""


@dataclass(frozen=True, slots=True)
class _Row:
    digest: bytes
    level: int
    parent: int | None
    component: int
    size: int
    cohesion: float | None
    trust: int
    taint: int
    state: int


def cluster(connection: Any, *, gen: int) -> ClusterReport:
    """Read the graph, cluster it, and reconcile the tree with the stored communities."""
    identities, taints, canon = _heads(connection)
    rows = []
    for src, dst, weight, relation, doc_key, addr, ts_a, trust, taint in connection.execute(
        _EDGES_SQL
    ).fetchall():
        a, b = canon.get(int(src)), canon.get(int(dst))
        if a is None or b is None:
            continue
        natural = (str(relation), str(doc_key), str(addr), int(ts_a), float(weight))
        rows.append((a, b, float(weight), natural, int(trust), int(taint)))
    tree, nodes, edges = plan(identities, taints, rows)
    stored = {
        int(r[0]): _Row(
            digest=bytes(r[1]),
            level=int(r[2]),
            parent=None if r[3] is None else int(r[3]),
            component=int(r[4]),
            size=int(r[5]),
            cohesion=None if r[6] is None else float(r[6]),
            trust=int(r[7]),
            taint=int(r[8]),
            state=int(r[9]),
        )
        for r in connection.execute(_ROWS_SQL).fetchall()
    }
    ids = _match(connection, tree, stored)
    writer = _Writer(connection, gen=gen, tree=tree)
    added = changed = 0
    for position, planned in enumerate(tree):
        parent = None if planned.parent is None else ids[planned.parent]
        community_id = ids[position]
        before = stored.get(community_id)
        if before is None:
            writer.insert(community_id, planned, parent)
            added += 1
        elif (
            before.digest,
            before.level,
            before.parent,
            before.component,
            before.cohesion,
            before.trust,
            before.taint,
            before.state,
        ) != (
            planned.digest,
            planned.level,
            parent,
            planned.component,
            planned.cohesion,
            planned.trust,
            planned.taint,
            0,
        ):
            writer.update(community_id, planned, parent, moved=before.digest != planned.digest)
            changed += 1
    kept = set(ids)
    retired = stale = 0
    for community_id, before in sorted(stored.items()):
        if before.state == 0 and community_id not in kept:
            stale += writer.retire(community_id)
            retired += 1
    if added or changed:
        stale += connection.execute(_STALE_SQL).rowcount
    return ClusterReport(
        entities=nodes,
        edges=edges,
        components=len({p.component for p in tree}),
        communities=len(tree),
        levels=max((p.level for p in tree), default=-1) + 1,
        added=added,
        changed=changed,
        retired=retired,
        split=sum(1 for p in tree if p.split),
        stale=stale,
    )


def _heads(connection: Any) -> tuple[dict[int, Identity], dict[int, int], dict[int, int]]:
    """Ruling 8: the live heads' identities and taints, and each live entity's live head."""
    identities: dict[int, Identity] = {}
    taints: dict[int, int] = {}
    heads: dict[int, int] = {}
    for entity_id, canonical_id, scope, etype, key, taint in connection.execute(
        _HEADS_SQL
    ).fetchall():
        heads[int(entity_id)] = int(canonical_id)
        if int(entity_id) == int(canonical_id):
            identities[int(entity_id)] = (str(scope), str(etype), str(key))
            taints[int(entity_id)] = int(taint)
    canon = {e: c for e, c in heads.items() if c in identities}
    return identities, taints, canon


def _match(connection: Any, tree: Sequence[Planned], stored: Mapping[int, _Row]) -> list[int]:
    """Ruling 12: each planned community's id -- by digest, then by overlap, then a new one."""
    by_digest: dict[bytes, int] = {}
    for community_id, row in sorted(stored.items(), key=lambda kv: (kv[1].state, kv[0])):
        by_digest.setdefault(row.digest, community_id)
    ids: list[int | None] = [None] * len(tree)
    taken: set[int] = set()
    for position, planned in enumerate(tree):
        community_id = by_digest.get(planned.digest)
        if community_id is not None and community_id not in taken:
            ids[position] = community_id
            taken.add(community_id)
    holders: dict[int, list[int]] = defaultdict(list)
    for community_id, entity_id in connection.execute(_MEMBERS_SQL).fetchall():
        if int(community_id) not in taken:
            holders[int(entity_id)].append(int(community_id))
    candidates: list[tuple[int, int, int]] = []
    for position, planned in enumerate(tree):
        if ids[position] is not None:
            continue
        overlap = Counter(
            community_id
            for entity_id in planned.members
            for community_id in holders.get(entity_id, ())
            if stored[community_id].level == planned.level
        )
        candidates.extend((-count, cid, position) for cid, count in overlap.items())
    for _count, community_id, position in sorted(candidates):
        if ids[position] is None and community_id not in taken:
            ids[position] = community_id
            taken.add(community_id)
    next_id = int(connection.execute(_NEXT_ID_SQL).fetchone()[0])
    out: list[int] = []
    for matched in ids:
        if matched is None:
            matched, next_id = next_id, next_id + 1  # noqa: PLW2901 -- a new row's id
        out.append(matched)
    return out


class _Writer:
    """The writes of one run, with the run row made the first time one needs it (ruling 14)."""

    def __init__(self, connection: Any, *, gen: int, tree: Sequence[Planned]) -> None:
        self._connection = connection
        self._gen = gen
        self._tree = tree
        self._run: tuple[int, int] | None = None

    def insert(self, community_id: int, planned: Planned, parent: int | None) -> None:
        run_id, cluster_run = self._open()
        self._connection.execute(
            _INSERT_SQL,
            {
                **self._columns(community_id, planned, parent, run_id, cluster_run),
                "cite": f"c{community_id}",
            },
        )
        self._members(community_id, planned)
        self._connection.execute(_REPORT_SQL, {"community_id": community_id})

    def update(
        self, community_id: int, planned: Planned, parent: int | None, *, moved: bool
    ) -> None:
        run_id, cluster_run = self._open()
        if moved:
            self._history(community_id, superseded_by=community_id)
            self._connection.execute(_UNMEMBER_SQL, {"community_id": community_id})
            self._members(community_id, planned)
        self._connection.execute(
            _UPDATE_SQL, self._columns(community_id, planned, parent, run_id, cluster_run)
        )

    def retire(self, community_id: int) -> int:
        """Ruling 15: the row leaves, and a report written for it goes stale with it."""
        self._history(community_id, superseded_by=None)
        self._connection.execute(_RETIRE_SQL, {"community_id": community_id, "state": RETIRED})
        return int(
            self._connection.execute(_RETIRE_REPORT_SQL, {"community_id": community_id}).rowcount
        )

    def _columns(
        self, community_id: int, planned: Planned, parent: int | None, run_id: int, run: int
    ) -> dict[str, object]:
        return {
            "community_id": community_id,
            "level": planned.level,
            "parent": parent,
            "component_ord": planned.component,
            "cluster_run": run,
            "size": planned.size,
            "cohesion": planned.cohesion,
            "member_digest": planned.digest,
            "run_id": run_id,
            "trust": planned.trust,
            "taint": planned.taint,
        }

    def _members(self, community_id: int, planned: Planned) -> None:
        self._connection.executemany(
            _MEMBER_SQL,
            [{"community_id": community_id, "entity_id": e} for e in sorted(planned.members)],
        )

    def _history(self, community_id: int, *, superseded_by: int | None) -> None:
        row = self._connection.execute(
            "SELECT member_digest, level, parent, size FROM community WHERE community_id = ?",
            (community_id,),
        ).fetchone()
        members = [
            int(r[0])
            for r in self._connection.execute(
                _MEMBERS_OF_SQL, {"community_id": community_id}
            ).fetchall()
        ]
        payload = {
            "member_digest": bytes(row[0]).hex(),
            "level": int(row[1]),
            "parent": None if row[2] is None else int(row[2]),
            "size": int(row[3]),
            "members": members,
        }
        self._connection.execute(
            _HISTORY_SQL,
            {
                "row_id": community_id,
                "gen": self._gen,
                "superseded_by": superseded_by,
                "payload": json.dumps(payload, sort_keys=True),
            },
        )

    def _open(self) -> tuple[int, int]:
        """The corpus-level `derive_run` and the `cluster_run` ordinal of this run's writes."""
        if self._run is not None:
            return self._run
        digest = hashlib.sha256(_SIGNATURE).digest()
        self._connection.execute(
            _REGISTER_SQL,
            {
                "pass_id": OP_CLUSTER,
                "rank": CLUSTER_RANK,
                "phase": CLUSTER_PHASE,
                "signature": digest.hex(),
                "version": CLUSTER_VERSION,
            },
        )
        producer = {"operator": OP_CLUSTER, "op_version": CLUSTER_VERSION, "options_digest": digest}
        self._connection.execute(_PRODUCER_INSERT_SQL, producer)
        producer_id = int(self._connection.execute(_PRODUCER_ID_SQL, producer).fetchone()[0])
        partition = canonical(sorted(p.digest.hex() for p in self._tree))
        params = {
            "pass_id": OP_CLUSTER,
            "gen": self._gen,
            "producer_id": producer_id,
            "method": _METHOD_ORD[Method.HEURISTIC.name.lower()],
            "version": CLUSTER_VERSION,
            "input_digest": hashlib.blake2b(partition, digest_size=16).digest(),
            "cache_key": hashlib.sha256(partition).hexdigest(),
            "status": "ok" if self._tree else "empty",
            "n_items": len(self._tree),
        }
        self._connection.execute(_RUN_SQL, params)
        run_id = int(self._connection.execute(_RUN_ID_SQL, params).fetchone()[0])
        self._connection.execute(_RUN_UPDATE_SQL, {**params, "run_id": run_id})
        cluster_run = int(self._connection.execute(_NEXT_RUN_SQL).fetchone()[0])
        self._run = (run_id, cluster_run)
        return self._run
