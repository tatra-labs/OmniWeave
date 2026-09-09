"""The exactly-once cover map, the two limits that bound it, and the gfm trim.

Four assertions here are the work item and the rest support them
(03-document-model.md sections 10.1-10.3, 16-roadmap.md W2.1):

**The exactly-once invariant, over the plan's own worked table.** 03 section 10.3 prints a
four-row, three-column table with a `row_span=2` and a `col_span=2`, its ten `cell` rows, its
twelve `grid_slot` rows, and the answers to `up(2,1)`, `left(2,1)`, `top_heading(1)`,
`top_heading(2)` and `left_heading(2)`. Every one of those printed values is asserted here against
`build_grid`'s output, which makes the fixture the specification rather than a paraphrase of it.

**A merged cell is rendered exactly once.** The covered positions of `Segment` and `FY2024` render
as blank cells in `md`/`gfm` and emit nothing at all in `html`, so each cell's text appears once in
the view -- asserted by counting occurrences, because a cover map that resolved a covered position
to its origin's *content* would produce a correct-looking table with duplicated text, which is the
exact failure 03:1900 says a sparse-cell-plus-spans representation has.

**`MAX_EXPANSION` refuses rather than allocates.** The charge is against the DECLARED span area
before expanding, so `rowspan=99_999` in a three-row table raises on the cell that crosses the
budget with a cover map still holding the cells that came before it -- asserted by reading the
exception, not by measuring memory.

**`grid_slot` is a stored emptiness.** `has_merges = 0` yields zero `grid_slot` rows and
`has_merges = 1` yields all `sum(row_len)` of them, which is 03:1902-1907's own extension of the
charter and the only reading under which the charter's printed neighbour query answers anything.

Specified in 03-document-model.md section 10.1 (:1876-1907), section 10.2 (:1909-1951), section
10.3 (:1954-2049) and section 14's limits table (:2649-2652).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from omniweave_core.errors import ResourceLimit, UsageError
from omniweave_core.limits import MAX_EXPANSION, MAX_GRID_SLOTS, MAX_RESIDENT_CELLS
from omniweave_core.model.block import Addr, Block, BlockId, CellPos, Cite
from omniweave_core.model.enums import Kind, Layer, Method, Quote, TableKind, Trust
from omniweave_core.model.grid import (
    RECON_STRATEGIES,
    SYNTHETIC_TABLE,
    Covered,
    Grid,
    Origin,
    build_grid,
    render_grid,
)
from omniweave_core.model.spans import OriginNone

# ---------------------------------------------------------------------------
# Fixtures. 03 section 10.3's worked table, block ids and all.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Draft:
    """A stand-in for `CellDraft` (03:337-338), which `model/block.py` has not declared.

    `build_grid` reads `.id` and `.pos` structurally for exactly this reason (see
    `grid._cell_position`), so this local two-field record is what a `CellDraft` will be. When
    `block.py` lands the real one, this class is deleted and the import replaces it -- the tests
    below do not change, which is the point of reading the two attributes rather than the type.
    """

    id: BlockId
    pos: CellPos


#: 03:1963-1990's ten origin cells: `block_id`, `(r, c)`, `(row_span, col_span)` and `text`.
WORKED: tuple[tuple[int, int, int, int, int, str], ...] = (
    (9, 0, 0, 2, 1, "Segment"),
    (10, 0, 1, 1, 2, "FY2024"),
    (11, 1, 1, 1, 1, "Q1"),
    (12, 1, 2, 1, 1, "Q2"),
    (13, 2, 0, 1, 1, "Cloud"),
    (14, 2, 1, 1, 1, "1,204"),
    (15, 2, 2, 1, 1, "1,388"),
    (16, 3, 0, 1, 1, "Devices"),
    (17, 3, 1, 1, 1, "902"),
    (18, 3, 2, 1, 1, "871"),
)

#: 03:1998-2001's twelve `grid_slot` rows, `(r, c) -> origin_id`, exactly as printed.
WORKED_SLOTS: tuple[tuple[int, int, int], ...] = (
    (0, 0, 9),
    (0, 1, 10),
    (0, 2, 10),
    (1, 0, 9),
    (1, 1, 11),
    (1, 2, 12),
    (2, 0, 13),
    (2, 1, 14),
    (2, 2, 15),
    (3, 0, 16),
    (3, 1, 17),
    (3, 2, 18),
)


def a_cell(block: int, text: str | None) -> Block:
    """One `table_cell` Block. A cell IS an ordinary Block (03:826), so this is a real one."""
    return Block(
        id=BlockId(block),
        addr=Addr(f"p1/0/1/b{block}"),
        cite=Cite(f"d7#{block}"),
        doc_ord=7,
        gen=1,
        page=1,
        parent=BlockId(8),
        ord=block - 9,
        kind=Kind.TABLE_CELL,
        raw_kind=None,
        layer=Layer.BODY,
        label=None,
        text=text,
        content_digest=bytes(16),
        layout_digest=None,
        revision=1,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.NATIVE_XML,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
    )


class Fake:
    """A `GridReadSide` that records every read, so laziness and read counts are MEASURED."""

    def __init__(self, blocks: dict[BlockId, Block]) -> None:
        self.blocks = blocks
        self.reads: list[int] = []

    def block(self, block: BlockId) -> Block:
        self.reads.append(int(block))
        return self.blocks[block]


def worked_grid(**kw: object) -> Grid:
    """03 section 10.3's table, built in row-major order through the sole constructor."""
    drafts = [Draft(BlockId(block), CellPos(r, c, rs, cs)) for block, r, c, rs, cs, _ in WORKED]
    return build_grid(
        drafts,
        header_rows=2,
        header_cols=1,
        recon=("native_xml", 1.0),
        diag=_no_diag,
        **kw,  # type: ignore[arg-type]
    )


def worked_reader() -> Fake:
    return Fake({BlockId(block): a_cell(block, text) for block, *_, text in WORKED})


def _no_diag(_d: object) -> None:
    """A diag sink `build_grid` accepts and does not call. See `grid.py`'s docstring."""


def grid_of(
    cells: list[tuple[int, int, int, int, int]],
    **kw: object,
) -> Grid:
    """A grid from `(block, r, c, row_span, col_span)` tuples, in the order given."""
    drafts = [Draft(BlockId(b), CellPos(r, c, rs, cs)) for b, r, c, rs, cs in cells]
    return build_grid(drafts, diag=_no_diag, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. The worked table -- every value 03 section 10.3 prints.
# ---------------------------------------------------------------------------


def test_the_worked_tables_meta_is_what_the_plan_prints() -> None:
    """03:1972-1974: `n_rows=4 n_cols=3 row_len=[3,3,3,3] header_rows=2 header_cols=1 ...`."""
    g = worked_grid()
    assert (g.n_rows, g.n_cols, g.row_len) == (4, 3, (3, 3, 3, 3))
    assert (g.header_rows, g.header_cols) == (2, 1)
    assert g.kind is TableKind.DATA
    assert g.recon == ("native_xml", 1.0)
    assert g.has_merges is True
    assert g.clamps == 0


def test_the_cell_rows_are_the_ten_origins_and_not_the_twelve_positions() -> None:
    """03:1976-1990 lists ten `cell` rows; "there is **no** `cell` row at (1,0) or (0,2)"."""
    g = worked_grid()
    assert [(o.block, o.r, o.c, o.row_span, o.col_span) for o in g.cells()] == [
        (block, r, c, rs, cs) for block, r, c, rs, cs, _ in WORKED
    ]


def test_the_grid_slot_rows_are_the_twelve_the_plan_prints() -> None:
    """03:1996-2001, row for row, because `has_merges = 1` makes the map TOTAL."""
    g = worked_grid()
    assert tuple((r, c, int(block)) for r, c, block in g.grid_slots()) == WORKED_SLOTS


def test_every_covered_slot_resolves_to_its_owning_cell() -> None:
    """The exactly-once invariant, 03:1895-1897, asserted at every logical position."""
    g = worked_grid()
    owners = {(r, c): block for r, c, block in WORKED_SLOTS}
    for r in range(g.n_rows):
        for c in range(g.row_len[r]):
            found = g.origin(r, c)
            assert found is not None, (r, c)
            assert int(found.block) == owners[(r, c)]


def test_a_covered_position_is_a_Covered_naming_its_origin_coordinate() -> None:  # noqa: N802
    """03:1877 and 03:1999-2000: `(1,0)` and `(0,2)` are covered, not empty."""
    g = worked_grid()
    assert g.slot(1, 0) == Covered(origin_r=0, origin_c=0)
    assert g.slot(0, 2) == Covered(origin_r=0, origin_c=1)
    assert g.slot(0, 0) == Origin(BlockId(9), 0, 0, 2, 1)
    assert g.slot(0, 1) == Origin(BlockId(10), 0, 1, 1, 2)


def test_the_four_neighbours_answer_what_the_worked_example_prints() -> None:
    """03:2008-2010: `grid.up(2,1)` -> block 11 (`Q1`); `grid.left(2,1)` -> block 13 (`Cloud`)."""
    g = worked_grid()
    up = g.up(2, 1)
    left = g.left(2, 1)
    assert up is not None and int(up.block) == 11
    assert left is not None and int(left.block) == 13
    down = g.down(2, 1)
    right = g.right(2, 1)
    assert down is not None and int(down.block) == 17
    assert right is not None and int(right.block) == 15


def test_a_neighbour_outside_the_grid_is_None() -> None:  # noqa: N802
    g = worked_grid()
    assert g.up(0, 0) is None
    assert g.left(0, 0) is None
    assert g.down(3, 0) is None
    assert g.right(0, 2) is None


def test_the_header_chains_are_the_chains_the_plan_prints() -> None:
    """03:2016-2020: `top_heading(1)` is `[FY2024, Q1]`, `top_heading(2)` is `[FY2024, Q2]`.

    Both columns share the `FY2024` origin, "which is the whole point of the cover map", and
    `left_heading(2)` is `[Cloud]` from `header_cols = 1`.
    """
    g = worked_grid()
    assert [int(o.block) for o in g.top_heading(0)] == [9]
    assert [int(o.block) for o in g.top_heading(1)] == [10, 11]
    assert [int(o.block) for o in g.top_heading(2)] == [10, 12]
    assert [int(o.block) for o in g.left_heading(2)] == [13]
    assert [int(o.block) for o in g.left_heading(3)] == [16]


def test_the_top_heading_chain_is_outermost_first() -> None:
    """A CHAIN, outermost first (03:1890). Row 0 precedes row 1, never the other way."""
    chain = worked_grid().top_heading(1)
    assert [o.r for o in chain] == [0, 1]


def test_a_header_chain_is_empty_when_there_are_no_header_rows_or_cols() -> None:
    g = grid_of([(1, 0, 0, 1, 1), (2, 0, 1, 1, 1)])
    assert g.top_heading(0) == ()
    assert g.left_heading(0) == ()


# ---------------------------------------------------------------------------
# 2. `has_merges` -- the stored emptiness of `grid_slot`.
# ---------------------------------------------------------------------------


def test_a_merge_free_table_has_zero_grid_slot_rows() -> None:
    """03:1906-1907: "the table has **zero rows** of `grid_slot`" and `slot()` is arithmetic."""
    g = grid_of([(1, 0, 0, 1, 1), (2, 0, 1, 1, 1), (3, 1, 0, 1, 1), (4, 1, 1, 1, 1)])
    assert g.has_merges is False
    assert list(g.grid_slots()) == []
    assert g.cover == {}
    assert g.slot(1, 1) == Origin(BlockId(4), 1, 1, 1, 1)
    assert g.origin(1, 1) == Origin(BlockId(4), 1, 1, 1, 1)


def test_has_merges_is_discovered_on_the_first_cell_with_a_span_above_one() -> None:
    """03:1942-1943: "it is 1 as soon as any cell has a span > 1", never a parameter."""
    assert grid_of([(1, 0, 0, 1, 1)]).has_merges is False
    assert grid_of([(1, 0, 0, 1, 2)]).has_merges is True
    assert grid_of([(1, 0, 0, 2, 1)]).has_merges is True


def test_the_total_cover_map_maps_an_origin_position_to_itself() -> None:
    """03:1904-1905: "an origin position mapping to itself" -- which is why `up` answers at all."""
    g = worked_grid()
    assert g.cover[(0, 0)] == (0, 0)
    assert g.cover[(1, 0)] == (0, 0)
    assert len(g.cover) == sum(g.row_len)


# ---------------------------------------------------------------------------
# 3. The limits. 03:1922-1925, 03:1937-1939, 03:2649-2652.
# ---------------------------------------------------------------------------


def test_MAX_EXPANSION_refuses_an_oversized_grid_rather_than_allocating_it() -> None:  # noqa: N802
    """03:2657's attack, verbatim: `rowspan="99999"` in a three-row HTML table.

    The refusal must name the knob and must happen on the cell that crosses the budget, so the
    declared area is charged BEFORE the span is expanded (03:1922-1925). A row_span of
    `MAX_EXPANSION` is representable; one more slot is not.
    """
    with pytest.raises(ResourceLimit) as caught:
        grid_of([(1, 0, 0, MAX_EXPANSION + 1, 1)])
    assert caught.value.limit == "MAX_EXPANSION"
    assert str(MAX_EXPANSION) in str(caught.value)


def test_MAX_EXPANSION_is_charged_incrementally_across_cells() -> None:  # noqa: N802
    """03:1945-1946: "the refusal happens on the cell that crosses it", not on the first one."""
    half = MAX_EXPANSION // 2
    with pytest.raises(ResourceLimit) as caught:
        grid_of([(1, 0, 0, 1, half), (2, 1, 0, 1, half), (3, 2, 0, 1, 3)])
    assert caught.value.limit == "MAX_EXPANSION"
    assert "(r=2, c=0)" in str(caught.value)


def test_MAX_EXPANSION_equals_MAX_GRID_SLOTS_so_a_table_cannot_build_then_fail_to_store() -> None:  # noqa: N802
    """03:1946-1948 asserts the equality in as many words, "because a table that can be built and
    then cannot be stored is the worst of both numbers"."""
    assert MAX_EXPANSION == MAX_GRID_SLOTS


def test_a_row_major_violation_past_the_resident_buffer_is_refused() -> None:
    """03:1937-1939 and 03:2652: out-of-order cells get "a resident buffer bounded by
    `MAX_RESIDENT_CELLS = 65_536`, above which the table is `RESOURCE_LIMIT{MAX_RESIDENT_CELLS}`".

    The whole table is emitted in reverse row-major order, so every cell after the first is out of
    order and the buffer is the refusal path. The limit names itself, which is what makes the
    breach actionable rather than a mystery.
    """
    reverse = [(n, MAX_RESIDENT_CELLS + 1 - n, 0, 1, 1) for n in range(MAX_RESIDENT_CELLS + 2)]
    with pytest.raises(ResourceLimit) as caught:
        grid_of(reverse)
    assert caught.value.limit == "MAX_RESIDENT_CELLS"


def test_an_out_of_order_arrival_inside_the_buffer_is_admitted_and_placed() -> None:
    """The other half of 03:1937-1939: below the bound the driver is served, not refused.

    A shuffled stream with no overlapping spans produces the same grid as the sorted one, which is
    the property a bounded buffer buys and the reason the limit exists rather than a raise.
    """
    ordered = [(1, 0, 0, 1, 1), (2, 0, 1, 1, 1), (3, 1, 0, 1, 1), (4, 1, 1, 1, 1)]
    shuffled = [ordered[3], ordered[1], ordered[0], ordered[2]]
    assert grid_of(shuffled) == grid_of(ordered)


def test_a_cover_map_larger_than_MAX_GRID_SLOTS_is_refused() -> None:  # noqa: N802
    """The `grid_slot` cap, 03:1865-1867's DDL comment and 03:2649's limits row.

    Two cells and a span of 2 make `has_merges` true, so the map is materialised; a far-right cell
    makes `sum(row_len)` enormous while the charged span area stays tiny. Without this check the
    table would build and then fail at `add_grid`, which is exactly what 03:1946-1948 forbids.
    """
    with pytest.raises(ResourceLimit) as caught:
        grid_of([(1, 0, 0, 1, 2), (2, 0, MAX_GRID_SLOTS + 4, 1, 1)])
    assert caught.value.limit == "MAX_GRID_SLOTS"


def test_a_malformed_cell_a_negative_position_and_a_zero_span_are_usage_errors() -> None:
    with pytest.raises(UsageError, match="CellDraft"):
        build_grid([object()], diag=_no_diag)
    with pytest.raises(UsageError, match="non-negative"):
        grid_of([(1, -1, 0, 1, 1)])
    with pytest.raises(UsageError, match="at least 1"):
        grid_of([(1, 0, 0, 0, 1)])
    with pytest.raises(UsageError, match="header counts"):
        grid_of([(1, 0, 0, 1, 1)], header_rows=-1)


def test_a_diag_sink_that_is_not_callable_is_refused_before_any_cell_is_read() -> None:
    """`diag` is required and carries no default (03:1914). A value in its place is a usage error,
    and it is caught before the iterable is touched so the refusal costs nothing."""
    consumed: list[object] = []

    def watching() -> object:
        for item in ():  # pragma: no cover -- the point is that this never runs.
            consumed.append(item)
            yield item

    with pytest.raises(UsageError, match="diag"):
        build_grid(watching(), diag="not a sink")  # type: ignore[arg-type]
    assert consumed == []


def test_a_table_kind_outside_the_closed_domain_is_refused() -> None:
    """`table_kind` is one of the fifteen closed `enum_val` domains (03 section 2.1)."""
    assert grid_of([(1, 0, 0, 1, 1)], kind="layout").kind is TableKind.LAYOUT
    assert grid_of([(1, 0, 0, 1, 1)], kind=TableKind.LAYOUT).kind is TableKind.LAYOUT
    with pytest.raises(UsageError, match="table kind"):
        grid_of([(1, 0, 0, 1, 1)], kind="pivot")


# ---------------------------------------------------------------------------
# 4. Clamping. 03:1916-1925.
# ---------------------------------------------------------------------------


def test_an_overlapping_span_is_clamped_rather_than_raising() -> None:
    """03:1921-1925: "Fail-closed on common input is a bug."

    The overlap is the same table twice, in the two arrival orders, and neither raises:

    * cells `(0,0,colspan=3)` then `(0,2)` -- the span arrived first and owns `(0,2)` already, so
      the later cell "skips" it (03:1916-1917) and is dropped;
    * cells `(0,2)` then `(0,0,colspan=3)` -- the span is clamped to the two positions it can
      actually own, which is anydoc's `table.rs:179-197`.

    Both are counted, and in both the exactly-once invariant survives: no position resolves to
    two origins.
    """
    span_first = grid_of([(1, 0, 0, 1, 3), (2, 0, 2, 1, 1)])
    assert span_first.origins[(0, 0)] == Origin(BlockId(1), 0, 0, 1, 3)
    assert list(span_first.cells()) == [Origin(BlockId(1), 0, 0, 1, 3)]
    assert span_first.clamps == 1
    cell_first = grid_of([(2, 0, 2, 1, 1), (1, 0, 0, 1, 3)])
    assert cell_first.origins[(0, 0)] == Origin(BlockId(1), 0, 0, 1, 2)
    assert cell_first.clamps == 1
    owner = cell_first.origin(0, 2)
    assert owner is not None and int(owner.block) == 2


def test_a_row_span_is_clamped_against_the_already_clamped_width() -> None:
    """Columns first, then rows against the clamped width, so the result is a RECTANGLE.

    Clamping the two independently could leave an L-shape, which is not a span and which no
    `rowspan`/`colspan` pair can round-trip back into PPTX or DOCX (03:2030-2032).
    """
    g = grid_of([(1, 0, 1, 1, 1), (2, 1, 0, 1, 1), (3, 0, 0, 3, 3)])
    kept = g.origins[(0, 0)]
    assert (kept.row_span, kept.col_span) == (1, 1)
    assert g.clamps == 1


def test_a_cell_whose_own_position_is_taken_is_dropped_and_counted() -> None:
    """03:1916-1917: "later placements skip them". The origin can own nothing, so it is dropped
    rather than moved -- moving it would invent a position the source never stated."""
    g = grid_of([(1, 0, 0, 1, 2), (2, 0, 1, 1, 1)])
    assert list(g.cells()) == [Origin(BlockId(1), 0, 0, 1, 2)]
    assert g.clamps == 1


def test_the_clamp_count_reaches_the_grid_so_add_grid_can_force_trust() -> None:
    """03:1919-1921 forces the table's trust to `INFERRED` on any clamp, and `add_grid(b, g)`
    receives only the `Grid` -- so the count has to be on it. See `grid.py`'s divergence 3."""
    assert grid_of([(1, 0, 0, 1, 1)]).clamps == 0
    assert grid_of([(1, 0, 0, 1, 2), (2, 0, 1, 1, 1)]).clamps == 1


# ---------------------------------------------------------------------------
# 5. Degenerate grids.
# ---------------------------------------------------------------------------


def test_an_empty_grid_is_empty_and_answers_None_everywhere() -> None:  # noqa: N802
    g = grid_of([])
    assert (g.n_rows, g.n_cols, g.row_len) == (0, 0, ())
    assert g.has_merges is False
    assert list(g.cells()) == []
    assert list(g.grid_slots()) == []
    assert g.slot(0, 0) is None
    assert g.origin(0, 0) is None
    assert g.top_heading(0) == ()
    assert g.inside(0, 0) is False


def test_a_one_by_one_grid_has_one_origin_and_no_cover_map() -> None:
    g = grid_of([(1, 0, 0, 1, 1)])
    assert (g.n_rows, g.n_cols, g.row_len) == (1, 1, (1,))
    assert g.has_merges is False
    assert g.slot(0, 0) == Origin(BlockId(1), 0, 0, 1, 1)
    assert g.slot(0, 1) is None
    assert g.slot(1, 0) is None


def test_a_grid_that_is_all_merges_resolves_every_position_to_the_one_cell() -> None:
    """One cell spanning the whole 3x3 extent: eight covered positions, one origin, one render."""
    g = grid_of([(1, 0, 0, 3, 3)])
    assert (g.n_rows, g.n_cols, g.row_len) == (3, 3, (3, 3, 3))
    assert g.has_merges is True
    assert len(list(g.cells())) == 1
    assert len(list(g.grid_slots())) == 9
    for r in range(3):
        for c in range(3):
            found = g.origin(r, c)
            assert found is not None and int(found.block) == 1
    assert g.slot(0, 0) == Origin(BlockId(1), 0, 0, 3, 3)
    assert g.slot(2, 2) == Covered(0, 0)


def test_a_ragged_row_keeps_its_own_length_and_is_not_padded() -> None:
    """03:2042-2045: "A ragged HTML table is not padded with phantom cells and is not rejected."""
    g = grid_of([(1, 0, 0, 1, 1), (2, 0, 1, 1, 1), (3, 1, 0, 1, 1)])
    assert g.row_len == (2, 1)
    assert g.n_cols == 2
    assert g.inside(1, 1) is False
    assert g.slot(1, 1) is None


def test_a_gap_inside_the_extent_resolves_to_None_rather_than_a_phantom_cell() -> None:  # noqa: N802
    """A driver that skipped `(0,1)`. `slot()` says nothing is there; `build_grid` invents no cell,
    because inventing one is precisely what 03:2042-2045 forbids."""
    g = grid_of([(1, 0, 0, 1, 1), (2, 0, 2, 1, 1)])
    assert g.row_len == (3,)
    assert g.inside(0, 1) is True
    assert g.slot(0, 1) is None
    assert g.origin(0, 1) is None


# ---------------------------------------------------------------------------
# 6. `render_grid`. 03:1892, 03:2035-2040.
# ---------------------------------------------------------------------------


def test_a_merged_cell_is_rendered_exactly_once_in_every_format() -> None:
    """The covered positions render blank (`md`/`gfm`) or emit nothing (`html`, `otsl`).

    Counting occurrences is what distinguishes a cover map from a duplicating one: resolving a
    covered position to its origin's CONTENT would produce a table that looks right and says
    `Segment` twice, which is the failure 03:1898-1900 attributes to sparse cells plus spans.
    """
    g = worked_grid()
    for fmt in ("md", "gfm", "html", "text", "otsl"):
        view, _ = render_grid(g, worked_reader(), fmt)
        assert view.count("Segment") == 1, fmt
        assert view.count("FY2024") == 1, fmt
        assert view.count("1,204") == 1, fmt
    # The pipe render in full, because "rendered once" and "rendered in the right place" are two
    # claims: `Segment` owns (0,0) and (1,0) and appears on the first row, `FY2024` owns (0,1) and
    # (0,2), and the three positions those two cover are the three blanks.
    md, _ = render_grid(g, worked_reader(), "md")
    assert md.splitlines() == [
        "| Segment | FY2024 |  |",
        "|  | Q1 | Q2 |",
        "| --- | --- | --- |",
        "| Cloud | 1,204 | 1,388 |",
        "| Devices | 902 | 871 |",
    ]


def test_the_html_render_carries_the_spans_and_skips_covered_positions() -> None:
    """03:2877: `html` preserves `rowspan`/`colspan`; a covered position emits nothing at all."""
    view, _ = render_grid(worked_grid(), worked_reader(), "html")
    assert '<th rowspan="2">Segment</th>' in view
    assert '<th colspan="2">FY2024</th>' in view
    assert view.count("<tr>") == 4


def test_the_span_map_marks_every_table_token_synthetic_and_owns_every_cell_character() -> None:
    """The pair is the point (03:2863-2864): a pipe is text no Block said, and the map says so."""
    view, smap = render_grid(worked_grid(), worked_reader(), "gfm")
    for offset in range(len(view)):
        owned = smap.block_at(offset)
        assert (owned is None) is smap.is_synthetic(offset)
    pipe = view.index("|")
    assert smap.is_synthetic(pipe)
    word = view.index("Segment")
    at = smap.block_at(word)
    assert at is not None and at[0] == 9


def test_render_grid_reads_each_cell_exactly_once() -> None:
    """A cover map holds ids, so the render's cost is one read per ORIGIN -- ten, not twelve.

    Measured off the fake rather than asserted about the output, because a render that re-read a
    covered position would produce the same string and twelve reads.
    """
    reader = worked_reader()
    render_grid(worked_grid(), reader, "gfm")
    assert sorted(reader.reads) == [block for block, *_ in WORKED]


def test_gfm_pops_trailing_all_blank_rows() -> None:
    """03:2036: the first of the two trimming rules.

    Rows 2 and 3 hold cells whose text is empty, so both go; the surviving view has two rows plus
    the synthetic delimiter. `md` is given no such rule by 03:2874-2879 and keeps them.
    """
    cells = [(1, 0, 0, 1, 1), (2, 1, 0, 1, 1), (3, 2, 0, 1, 1), (4, 3, 0, 1, 1)]
    g = grid_of(cells)
    reader = Fake(
        {
            BlockId(1): a_cell(1, "keep"),
            BlockId(2): a_cell(2, "also"),
            BlockId(3): a_cell(3, ""),
            BlockId(4): a_cell(4, "   "),
        }
    )
    gfm, _ = render_grid(g, reader, "gfm")
    assert gfm.splitlines() == ["|  |", "| --- |", "| keep |", "| also |"]
    md, _ = render_grid(g, Fake(dict(reader.blocks)), "md")
    assert md.splitlines() == ["|  |", "| --- |", "| keep |", "| also |", "|  |", "|     |"]


def test_gfm_truncates_trailing_all_blank_columns() -> None:
    """03:2036-2037: the second rule. Column 2 is blank in every row, so it is truncated."""
    cells = [
        (1, 0, 0, 1, 1),
        (2, 0, 1, 1, 1),
        (3, 0, 2, 1, 1),
        (4, 1, 0, 1, 1),
        (5, 1, 1, 1, 1),
        (6, 1, 2, 1, 1),
    ]
    reader = Fake(
        {
            BlockId(1): a_cell(1, "a"),
            BlockId(2): a_cell(2, "b"),
            BlockId(3): a_cell(3, ""),
            BlockId(4): a_cell(4, "c"),
            BlockId(5): a_cell(5, "d"),
            BlockId(6): a_cell(6, None),
        }
    )
    g = grid_of(cells)
    assert g.gfm_extent(lambda b: bool((reader.blocks[b].text or "").strip())) == (2, 2)
    gfm, _ = render_grid(g, reader, "gfm")
    assert gfm.splitlines() == ["|  |  |", "| --- | --- |", "| a | b |", "| c | d |"]
    md, _ = render_grid(g, Fake(dict(reader.blocks)), "md")
    assert md.splitlines()[2] == "| a | b |  |"


def test_a_span_reaching_into_a_trimmed_row_is_clamped_to_the_surviving_extent() -> None:
    """A `row_span=2` whose lower half falls in a popped row keeps only the row that survived.

    The trim is applied to the SCOPE and not to the string, so the `SpanMap` stays honest -- a
    trim performed on the output would leave the map pointing past the end of the view.
    """
    g = grid_of([(1, 0, 0, 2, 1), (2, 0, 1, 1, 1), (3, 1, 1, 1, 1)])
    reader = Fake(
        {
            BlockId(1): a_cell(1, "tall"),
            BlockId(2): a_cell(2, "top"),
            BlockId(3): a_cell(3, ""),
        }
    )
    gfm, smap = render_grid(g, reader, "gfm")
    assert gfm.splitlines() == ["|  |  |", "| --- | --- |", "| tall | top |"]
    assert "rowspan" not in gfm
    for offset in range(len(gfm)):
        assert (smap.block_at(offset) is None) is smap.is_synthetic(offset)


def test_gfm_emits_a_synthetic_header_row_when_there_are_no_header_rows() -> None:
    """03:2037-2038: "GFM requires a delimiter row", so one is invented and marked synthetic."""
    g = grid_of([(1, 0, 0, 1, 1)])
    gfm, smap = render_grid(g, Fake({BlockId(1): a_cell(1, "x")}), "gfm")
    assert gfm.splitlines()[1] == "| --- |"
    assert smap.is_synthetic(gfm.index("---"))


def test_the_wrapper_block_defaults_to_an_id_no_row_can_hold() -> None:
    """`SYNTHETIC_TABLE` is `0`, and SQLite's implicit rowid sequence starts at 1."""
    assert int(SYNTHETIC_TABLE) == 0
    reader = worked_reader()
    render_grid(worked_grid(), reader, "html")
    assert 0 not in reader.reads


def test_a_named_table_block_is_read_and_used_as_the_wrapper() -> None:
    """A caller holding the table's own `BlockId` gets the real block read and used as the frame.

    Block 8 is the table of 03 section 10.3 (`cite = d7#8`, 03:1968), and naming it is what makes
    the render's spans attributable to a row rather than to the synthetic frame.
    """
    reader = worked_reader()
    reader.blocks[BlockId(8)] = replace(a_cell(8, None), kind=Kind.TABLE, parent=None)
    view, smap = render_grid(worked_grid(), reader, "html", table=BlockId(8))
    assert view.startswith("<table>")
    assert 8 in reader.reads
    # The wrapper owns no character of the view: every offset is either a cell's or synthetic.
    assert all((smap.block_at(i) is None) is smap.is_synthetic(i) for i in range(len(view)))
    assert {smap.block_at(i)[0] for i in range(len(view)) if smap.block_at(i)}.isdisjoint({8})


def test_render_grid_refuses_an_unknown_format_before_reading_anything() -> None:
    reader = worked_reader()
    with pytest.raises(UsageError, match="fmt must be one of"):
        render_grid(worked_grid(), reader, "docx")
    assert reader.reads == []


def test_an_empty_grid_renders_to_an_empty_gfm_view() -> None:
    view, smap = render_grid(grid_of([]), Fake({}), "gfm")
    assert view == ""
    assert smap.is_synthetic(0) is False
    assert smap.block_at(0) is None


# ---------------------------------------------------------------------------
# 7. The shape rules a value cannot state about itself.
# ---------------------------------------------------------------------------


def test_the_grid_is_frozen_all_the_way_down() -> None:
    """A `Grid` a caller could mutate would let a render disagree with the rows `add_grid` wrote."""
    g = worked_grid()
    with pytest.raises(Exception, match="assign"):
        g.n_rows = 9  # type: ignore[misc]
    with pytest.raises(TypeError):
        g.origins[(9, 9)] = Origin(BlockId(1), 9, 9)  # type: ignore[index]
    with pytest.raises(TypeError):
        g.cover[(9, 9)] = (9, 9)  # type: ignore[index]


def test_no_model_class_here_carries_an_html_or_markdown_field() -> None:
    """INV-1, and 03:1892's own note. A render is a function; `render_grid` is the only one."""
    for cls in (Grid, Origin, Covered):
        fields = set(getattr(cls, "__annotations__", {}))
        assert fields.isdisjoint({"html", "markdown", "md", "text"})


def test_the_recon_strategy_register_is_the_nine_tokens_the_ddl_comments() -> None:
    """03:1852's comment, transcribed. Not a CHECK and not an `enum_val` domain, so `build_grid`
    records an unlisted token rather than refusing it -- which this asserts both halves of."""
    assert RECON_STRATEGIES == (
        "native_xml",
        "span_x0",
        "span_center",
        "proj_1",
        "proj_3",
        "proj_10",
        "tableformer",
        "vlm",
        "human",
    )
    assert grid_of([(1, 0, 0, 1, 1)], recon=("something_new", None)).recon == (
        "something_new",
        None,
    )


def test_native_reaches_the_grid_so_a_passthrough_export_is_representable() -> None:
    """`Grid.native` is a printed field (03:1886) and `build_grid` is its only writer."""
    digest = bytes(range(32))
    g = grid_of([(1, 0, 0, 1, 1)], native=("word/document.xml", digest))
    assert g.native == ("word/document.xml", digest)
    assert grid_of([(1, 0, 0, 1, 1)]).native is None
