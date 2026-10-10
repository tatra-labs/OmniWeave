"""`ow graph review`: the rows the graph holds below `EXTRACTED`, weakest first. D700.

06:85-87 makes the three `*_review` partial indexes (`WHERE trust < 2 OR taint <> 0`) *"the review
surface"*, 06:90-92 adopts graphify's `order = {AMBIGUOUS: 0, INFERRED: 1, EXTRACTED: 2}` as its
ordering, and 06:2520 prints the verb. Pure types; `store.review` reads them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Review", "ReviewClosure", "ReviewEdge", "ReviewEntity", "ReviewMention"]


@dataclass(frozen=True, slots=True)
class ReviewClosure:
    """A closure of two or more whose resolution is below `EXTRACTED`: one fuzzy merge in it."""

    head: str
    title: str
    etype: str
    members: int
    resolution_trust: int


@dataclass(frozen=True, slots=True)
class ReviewEntity:
    """A live entity witnessed by a tainted source, or one `op.resolve` found overloaded."""

    entity: str
    title: str
    etype: str
    trust: int
    taint: int
    overloaded: bool
    """`OW_GRAPH_ENTITY_OVERLOADED` (06:171): kept, its mentions kept, out of resolution."""


@dataclass(frozen=True, slots=True)
class ReviewMention:
    """A live mention below `EXTRACTED` or tainted, where it was witnessed and as what."""

    mention: int
    entity: str
    cite: str
    surface: str
    trust: int
    taint: int


@dataclass(frozen=True, slots=True)
class ReviewEdge:
    """An edge observed in a live block, below `EXTRACTED` or tainted."""

    edge: int
    src: str
    dst: str
    relation: str
    cite: str
    trust: int
    taint: int


@dataclass(frozen=True, slots=True)
class Review:
    """`graph.review`'s answer: four lists, each weakest first and cut at `limit`, with totals."""

    limit: int
    closures: tuple[ReviewClosure, ...]
    closures_total: int
    entities: tuple[ReviewEntity, ...]
    entities_total: int
    mentions: tuple[ReviewMention, ...]
    mentions_total: int
    edges: tuple[ReviewEdge, ...]
    edges_total: int
