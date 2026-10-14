"""`op.resolve`, then `op.cluster`, again while the communities move: one fixed point. D691, D697.

The community boost (06:1722) reads the communities, and a merge moves the graph they are cut from,
so one run of each in a fixed order leaves the graph one step behind itself (D691). This is the loop
that settles it, written once for its two callers: `ow ingest`, which runs each pass in its own
store unit, and a user decision (`graph.decide`), which runs both inside its own transaction.

A round ends the loop when `op.resolve` writes nothing, or when `op.cluster` moves no community. The
counts are summed over the rounds; `bound` caps them, and `Settled.settled` says whether the graph
stopped moving inside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from omniweave.graph.cluster import ClusterReport
    from omniweave.graph.resolve import ResolveReport

__all__ = ["Settled", "settle"]


@dataclass(frozen=True, slots=True)
class Settled:
    resolved: ResolveReport
    clustered: ClusterReport
    rounds: int
    settled: bool


def settle(
    resolve: Callable[[], ResolveReport], cluster: Callable[[], ClusterReport], *, bound: int
) -> Settled:
    """Run the two to a fixed point, at most `bound` rounds."""
    resolved = resolve()
    latest = clustered = cluster()
    rounds = 1
    while latest.moved:  # the latest round's: a cluster that moved nothing is a fixed point
        if rounds == bound:
            return Settled(resolved, clustered, rounds, settled=False)
        again = resolve()
        if not again.moved:
            break
        rounds += 1
        resolved = again.after(resolved)
        latest = cluster()
        clustered = latest.after(clustered)
    return Settled(resolved, clustered, rounds, settled=True)
