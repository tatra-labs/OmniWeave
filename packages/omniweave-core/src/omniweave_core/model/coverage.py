"""Per-lane coverage, as the billed Pass's selector reads it. D705. `store.coverage` reads it.

06:879-881: *"The mean is what `ow graph plan` reports as coverage; the billed share is what you are
billed for."* Both are here, with the mean uncovered fraction of the billed set that 06:950 adds.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["GraphPlan", "LaneCoverage", "LanePlan"]


@dataclass(frozen=True, slots=True)
class LaneCoverage:
    """One lane's live Segments against one billed Pass and one floor."""

    lane: str
    segments: int
    """Live Segments at their document's head generation."""
    rows: int
    """The joined rows the selector streamed (06:788)."""
    mean_covered: float
    """The mean `covered_frac`: what the plan reports as coverage (06:879)."""
    billed: int
    """Segments below the floor, each handed to the billed Pass whole (06:854)."""
    mean_uncovered_billed: float | None
    """The mean `1 - covered_frac` over the billed Segments, `None` when none is billed (06:950)."""

    @property
    def billed_share(self) -> float:
        """The billed Segments as a share of the live ones: 06:2629's **billed share**."""
        return self.billed / self.segments if self.segments else 0.0


@dataclass(frozen=True, slots=True)
class LanePlan:
    """One billed Pass's lane: its coverage, and the `Spend` its billed Segments project."""

    pass_id: str
    coverage: LaneCoverage
    calls: int
    tokens_in: int
    tokens_out: int
    """`Spend`'s three provider units for the billed Segments, at 06:837-838's per-Segment
    projection. Never micros: those need an operator's `PriceBook` (06:821-823)."""


@dataclass(frozen=True, slots=True)
class GraphPlan:
    """`graph.plan`'s answer: per billed lane, before anything runs (06:2518)."""

    floor: float
    """`[graph] llm_coverage_floor`, the bar a Segment's `covered_frac` must reach."""
    lanes: tuple[LanePlan, ...]
