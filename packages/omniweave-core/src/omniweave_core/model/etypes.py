"""`ow graph types`: the entity-type vocabulary, and an operator's promotions. D706.

06:289-290 makes `etype_vocab` data, not code: fifteen builtin rows, `ow graph types --propose`
writing `source = 'proposed'`, and *"an operator promotes it to `'user'`"*. 06:1667-1668 prints the
promotion: `ow graph types --promote defined_term,covenant --reason '<why>'`. Pure types;
`store.etypes` reads and writes them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Etype", "Promotion", "TypeVocab"]


@dataclass(frozen=True, slots=True)
class Promotion:
    """An operator's promotion of a proposed type: why, and at which generation."""

    reason: str
    gen: int


@dataclass(frozen=True, slots=True)
class Etype:
    """One `etype_vocab` row, with the live entities of that type and its promotion, if any."""

    etype: str
    scope: str
    resolution: str
    source: str
    """`builtin`, `user` or `proposed`: a proposed type is not rendered into a prompt (06:1675)."""
    compatible: tuple[str, ...]
    entities: int
    promoted: Promotion | None


@dataclass(frozen=True, slots=True)
class TypeVocab:
    """`graph.types`' answer: every row, builtin first, then user, then proposed."""

    etypes: tuple[Etype, ...]
    promoted: tuple[str, ...] = ()
    """The types this call promoted, in the order they were named."""
