"""Louvain over an `array('i')` CSR: `op.cluster`'s arithmetic. D690.

06-structure-extraction.md section 6.1 and the charter's clustering constants (charter.md:5520-5533)
are the specification. graphrag's `cluster_graph.py:57-97` is the reference for determinism, and
graphify's `cluster.py` for the two re-splits. These are pure functions over integer node indices
and float weights; `omniweave.graph.cluster` maps the store's entities to indices and back.

## Rulings (the ledger's D690)

1. **The seed orders the sweep, through blake2b.** `random` is banned in this repository, so
   `CLUSTER_SEED` keys a blake2b digest of each node's index and the pass number, and a sweep visits
   the nodes in that digest's order. One `louvain()` call is a function of its graph alone.
2. **A move needs a strictly better gain**, by more than `MIN_GAIN`. A tie keeps the node where it
   is, and between two neighbour communities the first met in CSR order wins. Every move raises
   modularity, which is what ends a level; `MAX_SWEEPS` bounds what float noise could add.
3. **The hierarchy is the dendrogram, read from the top.** Louvain's last level holds the roots, at
   `level = 0`. A community's children are the previous level's communities inside it, at
   `level + 1`. A community the next pass left alone is the same set twice, and it is written once:
   the chain collapses. graphrag numbers its levels the same way (`hierarchical_leiden`, level 0 the
   root), and a descent from the roots is what `REPORT_LEVELS` bounds.
4. **A leaf is re-split for size or for cohesion**, graphify's two passes. A leaf above
   `MAX_COMMUNITY_SIZE` is split, and so is a leaf of `COHESION_SPLIT_MIN` members or more whose
   cohesion is under `COHESION_SPLIT`. A split is Louvain over the leaf's own subgraph, and its
   coarsest level becomes the leaf's children. A child is checked again.
5. **A leaf above the cap that Louvain cannot split is cut** into `ceil(n / cap)` pieces of a
   breadth-first order over its subgraph. 06:1594 makes the cap a bound on the worst case, and a
   community Louvain will not divide, such as a clique, would otherwise break it.
6. **Cohesion is graphify's**: internal edges over `n (n - 1) / 2`, and 1.0 for a single member.
7. **Edges arrive as rows in the caller's total order.** `normalise()` is graphrag's triple: the
   direction folded to `(lo, hi)`, duplicates dropped keeping the last, the list sorted. A self-loop
   (two ends that resolve to one node) is dropped.
"""

from __future__ import annotations

import hashlib
from array import array
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "CLUSTER_SEED",
    "COHESION_SPLIT",
    "COHESION_SPLIT_MIN",
    "MAX_COMMUNITY_SIZE",
    "Community",
    "Graph",
    "cohesion",
    "communities",
    "components",
    "csr",
    "induced",
    "louvain",
    "normalise",
]

CLUSTER_SEED: Final = 0xDEADBEEF
MAX_COMMUNITY_SIZE: Final = 512
"""06:1940: a split cap, not graphrag's 10. Louvain's natural size sets the leaf count; the cap
bounds the worst case (06:1594)."""
COHESION_SPLIT: Final = 0.05
COHESION_SPLIT_MIN: Final = 50
"""06:1951: graphify's second pass, to *"re-split low-cohesion communities caused by doc-hub
nodes"*."""
MAX_SWEEPS: Final = 64
"""Ruling 2: sweeps of one level's local moving. A level ends when a sweep moves nothing."""
MIN_GAIN: Final = 1e-10
"""Ruling 2: how much better a gain must be to move a node."""

_SEED_BYTES: Final = CLUSTER_SEED.to_bytes(8, "big")


@dataclass(frozen=True, slots=True)
class Graph:
    """An undirected weighted graph as a CSR, each edge stored at both of its ends.

    Node `i`'s neighbours are `targets[offsets[i]:offsets[i + 1]]`, ascending, with their weights
    at the same positions.
    """

    offsets: array[int]
    targets: array[int]
    weights: array[float]

    @property
    def n(self) -> int:
        return len(self.offsets) - 1

    @property
    def edges(self) -> int:
        """Undirected edges: each is stored twice."""
        return len(self.targets) // 2


@dataclass(frozen=True, slots=True)
class Community:
    """One community of the tree `communities()` returns, parents before their children."""

    members: tuple[int, ...]
    """Node indices, ascending."""
    level: int
    """Depth below its root: a root is 0 (ruling 3)."""
    parent: int | None
    """The parent's index in the returned list; `None` for a root."""
    component: int
    """The connected component's ordinal, in order of each component's smallest node."""
    cohesion: float
    split: str = ""
    """Why this community's children are a re-split of it (ruling 4): `size`, `cohesion` or `cut`;
    empty when they are the dendrogram's, or it has none."""


def normalise(rows: Iterable[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    """Ruling 7: `(lo, hi, weight)` per node pair, the last row's weight, sorted."""
    kept: dict[tuple[int, int], float] = {}
    for a, b, weight in rows:
        if a == b:
            continue
        kept[(a, b) if a < b else (b, a)] = float(weight)
    return [(lo, hi, weight) for (lo, hi), weight in sorted(kept.items())]


def csr(n: int, edges: Iterable[tuple[int, int, float]]) -> Graph:
    """The CSR over `n` nodes of `normalise()`'s output."""
    adjacency: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for lo, hi, weight in edges:
        adjacency[lo].append((hi, weight))
        adjacency[hi].append((lo, weight))
    offsets, targets, weights = array("i", [0]), array("i"), array("d")
    for row in adjacency:
        row.sort()
        for target, weight in row:
            targets.append(target)
            weights.append(weight)
        offsets.append(len(targets))
    return Graph(offsets=offsets, targets=targets, weights=weights)


def components(graph: Graph) -> list[list[int]]:
    """Connected components, each ascending, in order of their smallest node."""
    seen = bytearray(graph.n)
    out: list[list[int]] = []
    for start in range(graph.n):
        if seen[start]:
            continue
        seen[start] = 1
        found, frontier = [start], [start]
        while frontier:
            node = frontier.pop()
            for p in range(graph.offsets[node], graph.offsets[node + 1]):
                target = graph.targets[p]
                if not seen[target]:
                    seen[target] = 1
                    found.append(target)
                    frontier.append(target)
        out.append(sorted(found))
    return out


def induced(graph: Graph, members: Sequence[int]) -> Graph:
    """The subgraph on `members` (ascending); node `i` of it is `members[i]`."""
    local = {node: index for index, node in enumerate(members)}
    offsets, targets, weights = array("i", [0]), array("i"), array("d")
    for node in members:
        for p in range(graph.offsets[node], graph.offsets[node + 1]):
            target = local.get(graph.targets[p])
            if target is not None:
                targets.append(target)
                weights.append(graph.weights[p])
        offsets.append(len(targets))
    return Graph(offsets=offsets, targets=targets, weights=weights)


def cohesion(graph: Graph, members: Sequence[int]) -> float:
    """Ruling 6: internal edges over the most there could be."""
    size = len(members)
    if size <= 1:
        return 1.0
    inside = set(members)
    internal = sum(
        1
        for node in members
        for p in range(graph.offsets[node], graph.offsets[node + 1])
        if graph.targets[p] > node and graph.targets[p] in inside
    )
    return internal / (size * (size - 1) / 2)


def louvain(graph: Graph) -> list[list[int]]:
    """The dendrogram: `levels[k][node]` is `node`'s community after pass `k + 1`.

    Labels are dense and numbered in order of each community's smallest node, so the finest level
    comes first and the coarsest last. A graph in which no pass merges anything has no level.
    """
    offsets, targets, weights = graph.offsets, graph.targets, graph.weights
    loops = [0.0] * graph.n
    membership = list(range(graph.n))
    levels: list[list[int]] = []
    for depth in range(graph.n):  # each level merges two nodes at least, so this bounds it
        labels = _move(offsets, targets, weights, loops, depth=depth)
        count = max(labels, default=-1) + 1
        if count == len(labels):
            break
        membership = [labels[node] for node in membership]
        levels.append(membership)
        offsets, targets, weights, loops = _aggregate(offsets, targets, weights, loops, labels)
    return levels


def communities(graph: Graph) -> list[Community]:
    """Every component's tree (rulings 3-5), components in order, parents before children."""
    out: list[Community] = []
    for ordinal, nodes in enumerate(components(graph)):
        _tree(graph, nodes, ordinal, out)
    return out


# ---------------------------------------------------------------------------------------------
# Louvain's two phases
# ---------------------------------------------------------------------------------------------


def _rank(depth: int, node: int) -> bytes:
    """Ruling 1: where `node` falls in pass `depth`'s sweep order."""
    return hashlib.blake2b(f"{depth}:{node}".encode(), digest_size=8, key=_SEED_BYTES).digest()


def _move(
    offsets: array[int],
    targets: array[int],
    weights: array[float],
    loops: Sequence[float],
    *,
    depth: int,
) -> list[int]:
    """Local moving to a fixed point (ruling 2). Returns dense labels."""
    n = len(offsets) - 1
    strength = [sum(weights[offsets[i] : offsets[i + 1]]) + 2.0 * loops[i] for i in range(n)]
    total = sum(strength)
    community = list(range(n))
    if total <= 0.0:
        return community
    tot = list(strength)
    order = sorted(range(n), key=lambda node: _rank(depth, node))
    for _ in range(MAX_SWEEPS):
        moved = False
        for node in order:
            home = community[node]
            k = strength[node]
            links: dict[int, float] = {}
            for p in range(offsets[node], offsets[node + 1]):
                there = community[targets[p]]
                links[there] = links.get(there, 0.0) + weights[p]
            tot[home] -= k
            best = home
            best_gain = links.get(home, 0.0) - tot[home] * k / total
            for there, weight in links.items():
                if there == home:
                    continue
                gain = weight - tot[there] * k / total
                if gain > best_gain + MIN_GAIN:
                    best, best_gain = there, gain
            tot[best] += k
            if best != home:
                community[node] = best
                moved = True
        if not moved:
            break
    return _dense(community)


def _dense(labels: Sequence[int]) -> list[int]:
    """Relabel 0.. in order of each label's first node."""
    renamed: dict[int, int] = {}
    return [renamed.setdefault(label, len(renamed)) for label in labels]


def _aggregate(
    offsets: array[int],
    targets: array[int],
    weights: array[float],
    loops: Sequence[float],
    labels: Sequence[int],
) -> tuple[array[int], array[int], array[float], list[float]]:
    """Louvain's second phase: one node per community, internal weight carried as a loop."""
    count = max(labels, default=-1) + 1
    inner = [0.0] * count
    rows: list[dict[int, float]] = [{} for _ in range(count)]
    for node, home in enumerate(labels):
        inner[home] += loops[node]
        for p in range(offsets[node], offsets[node + 1]):
            there = labels[targets[p]]
            if there == home:
                inner[home] += weights[p] / 2.0  # each internal edge is met at both ends
            else:
                rows[home][there] = rows[home].get(there, 0.0) + weights[p]
    new_offsets, new_targets, new_weights = array("i", [0]), array("i"), array("d")
    for row in rows:
        for target in sorted(row):
            new_targets.append(target)
            new_weights.append(row[target])
        new_offsets.append(len(new_targets))
    return new_offsets, new_targets, new_weights, inner


# ---------------------------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------------------------


def _groups(members: Sequence[int], labels: Sequence[int]) -> list[list[int]]:
    """`members` grouped by `labels[member]`, each group ascending, in order of its first."""
    groups: dict[int, list[int]] = {}
    for member in members:
        groups.setdefault(labels[member], []).append(member)
    return list(groups.values())


def _tree(graph: Graph, nodes: list[int], ordinal: int, out: list[Community]) -> None:
    """One component: the dendrogram top-down (ruling 3), then the leaves re-split (4, 5)."""
    sub = induced(graph, nodes)
    levels = louvain(sub) or [list(range(len(nodes)))]

    def build(local: list[int], above: int, level: int, parent: int | None) -> None:
        below = above - 1
        while below >= 0 and len({levels[below][m] for m in local}) == 1:
            below -= 1  # ruling 3: a set the pass left alone is written once
        members = [nodes[m] for m in local]
        index = len(out)
        out.append(
            Community(
                members=tuple(members),
                level=level,
                parent=parent,
                component=ordinal,
                cohesion=cohesion(graph, members),
            )
        )
        if below < 0:
            _resplit(graph, index, out)
            return
        for group in _groups(local, levels[below]):
            build(group, below, level + 1, index)

    top = len(levels) - 1
    for group in _groups(range(len(nodes)), levels[top]):
        build(group, top, 0, None)


def _resplit(graph: Graph, index: int, out: list[Community]) -> None:
    """Ruling 4 and 5 for the leaf at `out[index]`, and again for each child it gets."""
    leaf = out[index]
    size = len(leaf.members)
    if size > MAX_COMMUNITY_SIZE:
        why = "size"
    elif size >= COHESION_SPLIT_MIN and leaf.cohesion < COHESION_SPLIT:
        why = "cohesion"
    else:
        return
    sub = induced(graph, leaf.members)
    levels = louvain(sub)
    parts = _groups(range(size), levels[-1]) if levels else []
    if len(parts) < 2:  # noqa: PLR2004 -- a split is two parts or more
        if why != "size":
            return
        why, parts = "cut", _cut(sub, MAX_COMMUNITY_SIZE)
    out[index] = Community(
        members=leaf.members,
        level=leaf.level,
        parent=leaf.parent,
        component=leaf.component,
        cohesion=leaf.cohesion,
        split=why,
    )
    for part in parts:
        members = [leaf.members[m] for m in sorted(part)]
        child = len(out)
        out.append(
            Community(
                members=tuple(members),
                level=leaf.level + 1,
                parent=index,
                component=leaf.component,
                cohesion=cohesion(graph, members),
            )
        )
        _resplit(graph, child, out)


def _cut(graph: Graph, cap: int) -> list[list[int]]:
    """Ruling 5: a breadth-first order cut into `ceil(n / cap)` pieces as equal as they can be."""
    seen = bytearray(graph.n)
    order: list[int] = []
    for start in range(graph.n):
        if seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        while queue:
            node = queue.popleft()
            order.append(node)
            for p in range(graph.offsets[node], graph.offsets[node + 1]):
                target = graph.targets[p]
                if not seen[target]:
                    seen[target] = 1
                    queue.append(target)
    pieces = -(-len(order) // cap)
    base, extra = divmod(len(order), pieces)
    out: list[list[int]] = []
    at = 0
    for piece in range(pieces):
        width = base + (1 if piece < extra else 0)
        out.append(order[at : at + width])
        at += width
    return out
