"""`ow graph why --cite`: every entity, edge and claim observed in one block. D695.

06:2119-2121: *"The reverse direction is equally short and is what an agent actually uses:
`ow graph why --cite d7#412` runs `mention_block` on `(block_id, ts_a)` to list every entity, edge
and claim observed in that block, each with its span, so 'what does this paragraph assert' is one
index range scan."* `graph.locate` (D694) is the forward walk, from an assertion to its pages; this
is the reverse, from a block to the assertions it witnesses. Pure types; `store.observed` reads
them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Observed", "ObservedClaim", "ObservedEdge", "ObservedMention"]


@dataclass(frozen=True, slots=True)
class ObservedMention:
    """One live mention in the block: the entity it names and where in the block's text."""

    mention: int
    entity: str
    """The mentioned entity's cite."""
    head: str
    """Its canonical head's cite: the entity an answer would show."""
    etype: str
    key: str
    span: tuple[int, int]
    surface: str
    trust: int


@dataclass(frozen=True, slots=True)
class ObservedEdge:
    """One edge whose relationship this block was the observation of."""

    edge: int
    src: str
    dst: str
    relation: str
    span: tuple[int, int] | None
    """`None` when the edge recorded no span: the whole block observed it."""
    trust: int


@dataclass(frozen=True, slots=True)
class ObservedClaim:
    """One claim observed in this block, its object an entity cite or a literal."""

    claim: str
    subject: str
    claim_type: str
    predicate: str
    object: str
    status: str
    span: tuple[int, int]
    trust: int


@dataclass(frozen=True, slots=True)
class Observed:
    """`graph.why`'s answer: one block, and what the graph says was asserted in it."""

    cite: str
    mentions: tuple[ObservedMention, ...]
    edges: tuple[ObservedEdge, ...]
    claims: tuple[ObservedClaim, ...]
