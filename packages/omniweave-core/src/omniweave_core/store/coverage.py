"""Per-lane coverage of the live Segments, as a billed Pass's selector would read it. D705.

06 section 2.1 is the specification: `eligible()` (06:744-775) ORs, for each live Segment, the
`cover_bits` of every run on the lane whose Pass sorts before the billed one in
`(cost_rank, phase)`, and a Segment whose covered share of its blocks falls below
`llm_coverage_floor` is handed to the billed Pass whole. `ow graph plan` *"runs exactly this query
and prints its row count"* (06:786-788). The arithmetic lives here so W8.8's selector and the plan
read one function.

## Rulings (the ledger's D705)

1. **A Segment's `covered_frac` on a lane is `popcount(cheaper & member) / n_blocks`**, where
   `cheaper` ORs the lane's cover rows from runs of Passes before the billed one and `member` is
   the top `n_blocks` bits of the big-endian blob (06:776, D703). A Segment with no such cover row
   is uncovered: `0.0`.
2. **Every live Segment at its document's head generation is in scope.** The layer, kind and
   restriction filters of `eligible()` are the billed Pass's card's (`p.layers`, `LANE_KINDS`,
   `p.deny_bits`), and they arrive with that Pass at W8.8.
3. **A Pass's place is its `derive_pass` row's `(cost_rank, phase)`.** A run whose Pass has no
   row orders nowhere and is not counted: cover the ledger cannot place is not cheaper.
4. **The row count is the joined rows the query streamed**, the number 06:788 says the plan
   prints so a selector scanning more than it should is visible.
5. **The billed Passes are 06:837-838's two Segment-grained ones**: `derive.entity.llm` on the
   `entity` lane at `(2, 10)` and `derive.claim.llm` on `claim` at `(2, 20)`. A `derive_pass` row of
   either name places it instead. Their per-Segment `Spend` -- calls, tokens in, tokens out -- is
   06's projection (§4.5), multiplied by the billed Segments, with calls rounded half up. Never
   micros (06:821-823).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model.coverage import GraphPlan, LaneCoverage, LanePlan

if TYPE_CHECKING:
    import sqlite3

__all__ = ["BILLED_PASSES", "BilledPass", "cheaper_cover", "graph_plan", "lane_coverage"]


@dataclass(frozen=True, slots=True)
class BilledPass:
    """Ruling 5: a Segment-grained billed Pass, its lane, its place, and its per-Segment Spend."""

    pass_id: str
    lane: str
    place: tuple[int, int]
    calls: Decimal
    tokens_in: int
    tokens_out: int


BILLED_PASSES: Final = (
    BilledPass("derive.entity.llm", "entity", (2, 10), Decimal("1.35"), 3989, 806),
    BilledPass("derive.claim.llm", "claim", (2, 20), Decimal("1.0"), 3100, 480),
)
"""06:837-838, rows 11 and 12: the two billed Passes that write cover, at their projected Spend."""

_PLACE: Final = "SELECT cost_rank, phase FROM derive_pass WHERE pass_id = ?"
_SEGMENT_COVER: Final = """
SELECT dc.cover_bits, dp.cost_rank, dp.phase
  FROM derive_cover AS dc
  JOIN derive_run AS dr ON dr.run_id = dc.run_id
  JOIN derive_pass AS dp ON dp.pass_id = dr.pass_id
 WHERE dc.segment_id = ? AND dc.lane = ?
"""

_SELECTOR: Final = """
SELECT s.segment_id, s.n_blocks, dc.cover_bits, dp.cost_rank, dp.phase
  FROM segment AS s
  JOIN doc AS d ON d.doc_ord = s.doc_ord AND d.gen = s.gen
  LEFT JOIN derive_cover AS dc ON dc.segment_id = s.segment_id AND dc.lane = :lane
  LEFT JOIN derive_run AS dr ON dr.run_id = dc.run_id
  LEFT JOIN derive_pass AS dp ON dp.pass_id = dr.pass_id
 WHERE s.state = 0
 ORDER BY s.segment_id
"""


def lane_coverage(
    connection: sqlite3.Connection, *, lane: str, before: tuple[int, int], floor: float
) -> LaneCoverage:
    """Rulings 1-4 for one lane: `before` is the billed Pass's `(cost_rank, phase)`."""
    rows = 0
    fractions: list[float] = []
    segment: int | None = None
    n_blocks = 0
    cheaper = 0

    def close() -> None:
        if segment is not None:
            member = ((1 << n_blocks) - 1) << (MAX_SEGMENT_BLOCKS - n_blocks)
            fractions.append((cheaper & member).bit_count() / n_blocks if n_blocks else 1.0)

    for segment_id, n, bits, rank, phase in connection.execute(_SELECTOR, {"lane": lane}):
        rows += 1
        if segment_id != segment:
            close()
            segment, n_blocks, cheaper = int(segment_id), int(n), 0
        if bits is not None and rank is not None and (int(rank), int(phase)) < before:
            cheaper |= int.from_bytes(bytes(bits), "big")
    close()
    billed = [f for f in fractions if f < floor]
    return LaneCoverage(
        lane=lane,
        segments=len(fractions),
        rows=rows,
        mean_covered=sum(fractions) / len(fractions) if fractions else 0.0,
        billed=len(billed),
        mean_uncovered_billed=sum(1 - f for f in billed) / len(billed) if billed else None,
    )


def cheaper_cover(
    connection: sqlite3.Connection, segment_id: int, *, lane: str, before: tuple[int, int]
) -> int:
    """Ruling 1's `cheaper` for one Segment (D709): its lane's cover from Passes placed before.

    The integer reading of the big-endian blob, so ord `k` is bit `511 - k` (06:776, D703). A cover
    row whose Pass has no `derive_pass` row orders nowhere and is not counted (ruling 3).
    """
    cheaper = 0
    for bits, rank, phase in connection.execute(_SEGMENT_COVER, (segment_id, lane)):
        if (int(rank), int(phase)) < before:
            cheaper |= int.from_bytes(bytes(bits), "big")
    return cheaper


def graph_plan(connection: sqlite3.Connection, *, floor: float) -> GraphPlan:
    """Ruling 5: each billed Pass's lane at `floor`, and the Spend its billed Segments project."""
    lanes = []
    for billed in BILLED_PASSES:
        row = connection.execute(_PLACE, (billed.pass_id,)).fetchone()
        place = billed.place if row is None else (int(row[0]), int(row[1]))
        coverage = lane_coverage(connection, lane=billed.lane, before=place, floor=floor)
        n = coverage.billed
        lanes.append(
            LanePlan(
                pass_id=billed.pass_id,
                coverage=coverage,
                calls=int((billed.calls * n).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                tokens_in=billed.tokens_in * n,
                tokens_out=billed.tokens_out * n,
            )
        )
    return GraphPlan(floor=floor, lanes=tuple(lanes))
