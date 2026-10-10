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

## The selector (D714)

`eligible()` is 06:744-773's query, scoped to one document, with the filters ruling 2 deferred:

6. **A lane's Kinds are 03 section 4.1's, read off its "text" column** (`LANE_KINDS`, core-side and
   not a card key, 06:722). `anchor` and `entity` take every Kind whose `block.text` is not NULL,
   plus `unknown`, which is "either". `xref` is prose and cells. Prose is the Kinds that hold
   running text: title, heading, paragraph, list item, caption, the three note kinds, comment and
   handwriting. `claim` adds the four form Kinds. A Segment is in a lane's scope when any member's
   Kind is.
7. **The layers are the reader's default, `body`** (03:1014-1016, `DEFAULT_LAYERS`). 06:734 takes
   them from a `[graph.passes]` policy that no config key declares yet, and a billed Pass is the
   place furniture costs money, so it is excluded until a key asks for it.
8. **No restriction bit is denied** until a policy sets one (14:101, B6): `deny_bits` is 0.
9. **The answer is the Segment, its part and what is uncovered.** The part is `seg:` and the first
   sixteen hex of its `content_digest` (06:807, 04:727), the work row's `unit_part`. `uncovered`
   is `member & ~cheaper`, the 64-byte blob the sink's covered-ground gate reads (D709).
   `covered` is the Segment's `covered_frac`, the reading its decision records (D715).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model.coverage import GraphPlan, LaneCoverage, LanePlan
from omniweave_core.model.doc import DEFAULT_LAYERS
from omniweave_core.model.enums import Kind, Layer, enum_val_rows

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Iterator, Mapping

__all__ = [
    "BILLED_LAYERS",
    "BILLED_PASSES",
    "FORM_KINDS",
    "LANE_KINDS",
    "PROSE_KINDS",
    "TEXT_KINDS",
    "BilledPass",
    "Eligible",
    "cheaper_cover",
    "eligible",
    "graph_plan",
    "kind_bits",
    "lane_coverage",
    "place_of",
]


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


TEXT_KINDS: Final = frozenset(
    {
        Kind.TITLE, Kind.HEADING, Kind.PARAGRAPH, Kind.LIST_ITEM, Kind.CODE, Kind.TABLE_CELL,
        Kind.CAPTION, Kind.FORMULA, Kind.PAGE_HEADER, Kind.PAGE_FOOTER, Kind.FOOTNOTE,
        Kind.ENDNOTE, Kind.SPEAKER_NOTE, Kind.COMMENT, Kind.FORM_FIELD, Kind.TOC_ENTRY,
        Kind.REFERENCE, Kind.HANDWRITING, Kind.CHEMICAL, Kind.UNKNOWN,
    }
)  # fmt: skip
"""Ruling 6: 03 section 4.1's Kinds whose `block.text` is not NULL, and `unknown` ("either")."""
PROSE_KINDS: Final = frozenset(
    {
        Kind.TITLE, Kind.HEADING, Kind.PARAGRAPH, Kind.LIST_ITEM, Kind.CAPTION, Kind.FOOTNOTE,
        Kind.ENDNOTE, Kind.SPEAKER_NOTE, Kind.COMMENT, Kind.HANDWRITING,
    }
)  # fmt: skip
"""Ruling 6: the text-bearing Kinds that hold running text, and no code, math, entry or field."""
FORM_KINDS: Final = frozenset({Kind.FORM, Kind.FORM_FIELD, Kind.KEY_VALUE, Kind.CHECKBOX})
"""06:723: what `claim` adds to `xref`'s prose and cells."""


def _ords(domain: str) -> dict[str, int]:
    return {name: ord_ for found, ord_, name in enum_val_rows() if found == domain}


def kind_bits(kinds: Iterable[Kind]) -> int:
    """The `segment.kind_mask` bits of `kinds`: `1 << enum_val.ord`, as the segmenter sets them."""
    ords = _ords("kind")
    bits = 0
    for kind in kinds:
        bits |= 1 << ords[kind.value]
    return bits


LANE_KINDS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "anchor": kind_bits(TEXT_KINDS),
        "entity": kind_bits(TEXT_KINDS),
        "xref": kind_bits(PROSE_KINDS | {Kind.TABLE_CELL}),
        "claim": kind_bits(PROSE_KINDS | {Kind.TABLE_CELL} | FORM_KINDS),
    }
)
"""Ruling 6: the Kind bitmask each lane can apply to (06:722). Core-side, never a card key."""
BILLED_LAYERS: Final = frozenset(DEFAULT_LAYERS)
"""Ruling 7: the reader's default, `body`, until a `[graph.passes]` key names others."""


@dataclass(frozen=True, slots=True)
class Eligible:
    """Ruling 9: one Segment a billed Pass may run on, and what in it no cheaper Pass covered."""

    segment_id: int
    part: str
    uncovered: bytes
    covered: float


_ELIGIBLE: Final = """
SELECT s.segment_id, s.n_blocks, s.content_digest, dc.cover_bits, dp.cost_rank, dp.phase
  FROM segment AS s
  JOIN doc AS d ON d.doc_ord = s.doc_ord AND d.gen = s.gen
  LEFT JOIN derive_cover AS dc ON dc.segment_id = s.segment_id AND dc.lane = :lane
  LEFT JOIN derive_run AS dr ON dr.run_id = dc.run_id
  LEFT JOIN derive_pass AS dp ON dp.pass_id = dr.pass_id
 WHERE s.state = 0 AND s.doc_ord = :doc_ord AND s.layer IN ({layers})
   AND (s.kind_mask & :want_kinds) <> 0 AND (s.restriction_bits & :deny) = 0
 ORDER BY s.segment_id
"""


def eligible(
    connection: sqlite3.Connection,
    *,
    doc_ord: int,
    lane: str,
    before: tuple[int, int],
    floor: float,
    layers: frozenset[Layer] = BILLED_LAYERS,
    deny_bits: int = 0,
) -> Iterator[Eligible]:
    """06:744-773 for one document's live Segments at its head generation: those a billed Pass
    placed at `before` may run on, because cheaper cover leaves them under `floor`.

    Rulings 6-9. The layer codes are inlined as integer literals, as 06:748 does, because SQLite
    cannot expand a list parameter; they come from `enum_val`, never from the caller's text.
    """
    codes = _ords("layer")
    inlined = ",".join(str(codes[layer.value]) for layer in sorted(layers)) or "NULL"
    params = {"lane": lane, "doc_ord": doc_ord, "want_kinds": LANE_KINDS[lane], "deny": deny_bits}
    segment: int | None = None
    n_blocks = 0
    digest = b""
    cheaper = 0

    def closed() -> Eligible | None:
        if segment is None or not n_blocks:
            return None
        member = ((1 << n_blocks) - 1) << (MAX_SEGMENT_BLOCKS - n_blocks)
        covered = (cheaper & member).bit_count() / n_blocks
        if covered >= floor:
            return None
        uncovered = (member & ~cheaper).to_bytes(MAX_SEGMENT_BLOCKS // 8, "big")
        return Eligible(segment, f"seg:{digest.hex()[:16]}", uncovered, covered)

    for segment_id, n, found, bits, rank, phase in connection.execute(
        _ELIGIBLE.format(layers=inlined), params
    ):
        if segment_id != segment:
            done = closed()
            if done is not None:
                yield done
            segment, n_blocks, digest, cheaper = int(segment_id), int(n), bytes(found), 0
        if bits is not None and rank is not None and (int(rank), int(phase)) < before:
            cheaper |= int.from_bytes(bytes(bits), "big")
    done = closed()
    if done is not None:
        yield done


def place_of(connection: sqlite3.Connection, billed: BilledPass) -> tuple[int, int]:
    """Ruling 5: the Pass's `derive_pass` row's `(cost_rank, phase)`, else its projected place."""
    row = connection.execute(_PLACE, (billed.pass_id,)).fetchone()
    return billed.place if row is None else (int(row[0]), int(row[1]))


def graph_plan(connection: sqlite3.Connection, *, floor: float) -> GraphPlan:
    """Ruling 5: each billed Pass's lane at `floor`, and the Spend its billed Segments project."""
    lanes = []
    for billed in BILLED_PASSES:
        place = place_of(connection, billed)
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
