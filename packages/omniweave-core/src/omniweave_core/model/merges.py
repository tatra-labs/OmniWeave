"""`ow graph merges`: the resolution decision log, one closure at a time. D696.

06:1891 prints the verb -- *"the decision log for one entity's closure, with guards"* -- and 06:1885
puts it first of the three user verbs, because a user deciding to merge or split reads this first.
Pure types; `store.merges` reads them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Decision", "MergeClosure", "MergeLog"]


@dataclass(frozen=True, slots=True)
class Decision:
    """One `entity_merge` row, its two ends as cites and its method by name."""

    merge: int
    loser: str
    winner: str
    polarity: int
    """`1` merged, `-1` a user's split: these two must not merge."""
    stage: str
    method: str
    trust: int
    score: float | None
    score_kind: str | None
    guards: tuple[str, ...]
    """The guards that PASSED (0002:442)."""
    reason: str | None
    decided_at_gen: int
    retired_at_gen: int | None
    """`None` while the decision is live."""


@dataclass(frozen=True, slots=True)
class MergeClosure:
    """One canonical cluster: its head, its members, and the decisions that touch them."""

    head: str
    members: tuple[str, ...]
    decisions: tuple[Decision, ...]


@dataclass(frozen=True, slots=True)
class MergeLog:
    """`graph.merges`' answer: the closure an entity is in, or every closure of two or more."""

    entity: str | None
    """The cite asked about, or `None` for the whole log."""
    closures: tuple[MergeClosure, ...]
