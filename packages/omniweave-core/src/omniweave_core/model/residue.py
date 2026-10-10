"""`ow graph residue`: what the graph could not place, grouped. D699.

06:2521 prints the verb -- *"`ref_unresolved` plus `quarantine`, grouped"* -- and 06:885-887 names
the quantity: **residue** is *"`ref_unresolved` plus `quarantine` ... the operability number, not
the cost number. `ow graph residue` reports it and `ow graph doctor` thresholds it."* Pure types;
`store.graph_residue` reads them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["GraphResidue", "QuarantineGroup", "UnresolvedGroup"]


@dataclass(frozen=True, slots=True)
class UnresolvedGroup:
    """One name no anchor defines, in one anchor kind: how often, and in how many documents."""

    akind: str
    name_norm: str
    sites: int
    docs: int
    """A name unresolved in one document is a typo; in forty, a missing corpus-scope anchor."""
    surface: str
    """One occurrence as written, to read the group by. Displayed, never matched (0003:225)."""


@dataclass(frozen=True, slots=True)
class QuarantineGroup:
    """One code's quarantined rows of one kind: how many, from how many runs, and when."""

    code: str
    row_kind: str
    rows: int
    runs: int
    first_gen: int
    last_gen: int


@dataclass(frozen=True, slots=True)
class GraphResidue:
    """`graph.residue`'s answer: both halves of 06:885's residue, each grouped and ranked."""

    akind: str | None
    """The anchor kind asked about, or `None` for every kind."""
    sites: int
    """Every `ref_site` row of that kind, resolved or not: the denominator 06:891 shares against."""
    unresolved_sites: int
    unresolved: tuple[UnresolvedGroup, ...]
    """Ranked worst first, and cut at the ceiling; `truncated` says when it cut."""
    truncated: bool
    quarantined: int
    quarantine: tuple[QuarantineGroup, ...]
