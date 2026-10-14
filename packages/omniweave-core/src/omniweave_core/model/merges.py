"""`ow graph merges`: the resolution decision log, one closure at a time. D696.

06:1891 prints the verb -- *"the decision log for one entity's closure, with guards"* -- and 06:1885
puts it first of the three user verbs, because a user deciding to merge or split reads this first.
Pure types; `store.merges` reads them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Decided", "Decision", "MergeClosure", "MergeLog"]


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


@dataclass(frozen=True, slots=True)
class Decided:
    """`graph.merge`'s and `graph.split`'s answer: what the decision wrote and the log after it."""

    polarity: int
    """`1` for a merge, `-1` for a split."""
    written: int
    """User rows this decision appended: none when the same live decision already stood."""
    retired: int
    """Opposing user rows it retired: a merge retires the split between the two, and back."""
    followed: bool
    """Whether the graph follows the decision: the closure holds both ends, for a merge; no side
    shares a head with another, for a split. False when another user decision keeps it from
    following."""
    log: MergeLog
    unassigned: tuple[str, ...] = ()
    """A split's members no side could claim, by a tie: with the head's side, or with none when
    the head is one of them (D698)."""
