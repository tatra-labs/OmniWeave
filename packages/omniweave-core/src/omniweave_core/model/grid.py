"""`Grid`, `build_grid` and `render_grid` -- the exactly-once table cover map. 03 section 10.

Implements 03-document-model.md section 10.1 (`Origin`, `Covered`, `Slot` and `Grid` at
:1876-1893; the exactly-once invariant at :1895-1900; `grid_slot`'s totality at :1902-1907),
section 10.2 (`build_grid`'s printed signature at :1912-1914, the clamp rule at :1916-1925 and
the streaming contract at :1936-1948) and section 10.3's rendering paragraph (:2035-2040), which
is `render_grid`'s whole specification.

**A cell is an ordinary Block; the cover map is derived and lazily materialised** (03:1840-1842).
So nothing here holds text: `Origin.block` is a `BlockId` and `render_grid` is handed a reader,
which is 03:1892's own note -- "no `.html` and no `.markdown`. Those are renders:
`render_grid(g, reader, fmt)`".

**`grid_slot` exists only when `has_merges = 1`, and then it is TOTAL** (03:1902-1907). The
charter's own neighbour query is `SELECT origin_id FROM grid_slot WHERE table_id=?1 AND c=?2 AND
r=?3-1`, which answers nothing for an unmerged position unless the map covers every position; so
`grid_slots()` yields `sum(row_len)` rows with an origin position mapping to itself when there are
merges, and yields nothing at all when there are none -- "a merge-free 4M-cell spreadsheet is
4,000,000 ordinary Blocks and zero `grid_slot` rows".

**Why `Grid` is not `serialize.py`'s `_Grid`.** `model/serialize.py` builds its own cover map from
`CellPos` (its section 7) because `Grid` did not exist when the serializer landed, and its module
docstring says so. The two must not stay parallel: `serialize._cover_map` is the same algorithm
with the clamp count and the `grid_slot` half missing, and what it should now do is call
`build_grid` and read `Grid.slot()` / `Grid.gfm_extent()`. Reported as a required edit rather than
performed here -- `serialize.py` is not this item's file.

**Three deliberate divergences from the printed shapes, each with its reason.**

1. `kind` is a `TableKind`, not the printed `Literal["data","layout"]` (03:1884). `table_kind` is
   one of the fifteen closed `enum_val` domains (03 section 2.1) and `serialize.TableFacts.kind`
   already carries the enum; a second spelling of one closed domain is INV-21's second home.
   `build_grid` still accepts the plan's bare `"data"` string and coerces it.
2. `build_grid` grows a keyword-only `native=` (03:1912-1914 omits it). `Grid.native` is a printed
   FIELD (03:1886) whose job is "`(part, sha256)` => passthrough export", and `build_grid` is the
   sole constructor (03:1880), so without the parameter the field can never be anything but
   `None` and 03:2029's byte-passthrough round-trip is unrepresentable. Reported.
3. `Grid` grows `clamps`, the count of spans 03:1916-1921 clamped. "Every clamp emits
   `Diag(OW_TABLE_SPAN_CLAMPED)` and forces the table's **trust** to `INFERRED`" -- and the thing
   that writes trust is `DocSink.add_grid(b, g)` (03:557, :580), whose only argument carrying
   information about the table is the `Grid`. A clamp count that reached only the `diag` callback
   would be invisible to the method the plan makes responsible for acting on it. Reported.

**`Diag` is section 9's (03:1798-1804) and has no module yet**, so `build_grid`'s `diag` parameter
is accepted, checked callable, and never called: the one call site that would fire is
`OW_TABLE_SPAN_CLAMPED`, and constructing that record here would put 03 section 9's type in 03
section 10's home. The clamp itself still happens and is still counted -- `Grid.clamps` -- so
nothing is lost silently, which is the property that mattered. Reported as a required edit.

Stdlib only (INV-2 / G1), and **nothing here imports `omniweave_core.store`**: the dependency runs
the other way (`store/types.py`:34-36 waits on this module), so what `render_grid` needs from a
store arrives as `GridReadSide`, a structural Protocol declared here -- the same decision, for the
same reason, that `model/rebind.py` records for `RebindReadSide`. One of the nine LAZY subpackages
(G17).

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Protocol

from omniweave_core.errors import ResourceLimit, UsageError
from omniweave_core.limits import MAX_EXPANSION, MAX_GRID_SLOTS, MAX_RESIDENT_CELLS
from omniweave_core.model.block import Addr, Block, BlockId, CellPos, Cite
from omniweave_core.model.enums import Kind, Layer, Method, Quote, TableKind, Trust
from omniweave_core.model.serialize import (
    FORMATS,
    ArraySpanMap,
    TableFacts,
    ViewScope,
    serialize,
)
from omniweave_core.model.spans import OriginNone

__all__ = [
    "RECON_STRATEGIES",
    "Covered",
    "Grid",
    "GridReadSide",
    "Origin",
    "Slot",
    "build_grid",
    "render_grid",
]

#: The nine `recon_strategy` tokens 03:1852 prints. A COMMENT in the DDL and not a CHECK, and not
#: an `enum_val` domain either (03 section 2.1 lists fifteen and `recon_strategy` is not among
#: them), so `build_grid` records the token it is handed and does NOT reject an unlisted one. The
#: tuple is here because a reader comparing this module to the DDL needs the list, and because the
#: day it becomes a closed domain this is the line that moves.
RECON_STRATEGIES: tuple[str, ...] = (
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

#: The synthetic table wrapper `render_grid` uses when the caller names no table block. SQLite's
#: implicit rowid sequence starts at 1 and `block_id` IS that rowid (03:2364), so `0` is a value no
#: `block` row can hold -- which is what makes it safe as "this Block is the render's own frame,
#: not a row". It owns no `text`, so it contributes only synthetic intervals to the `SpanMap`.
SYNTHETIC_TABLE: BlockId = BlockId(0)


# ---------------------------------------------------------------------------
# 1. `Origin`, `Covered`, `Slot` -- 03:1876-1878.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Origin:
    """A cell that OWNS its position. 03:1876.

    `block` is the cell's already-minted `BlockId` -- the host minted it, its `addr`
    (`.../r<r>c<c>`) and its `cite` at `add_block`, exactly as for any other block (03:1950), so
    this type never mints anything. `row_span`/`col_span` are what the origin ACTUALLY owns after
    03:1916-1921's clamp, never what the source declared: the declared value is what
    `MAX_EXPANSION` was charged for and the clamped value is what the cover map holds, and keeping
    the declared one here would let a reader reconstruct an overlap the invariant forbids.
    """

    block: BlockId
    r: int
    c: int
    row_span: int = 1
    col_span: int = 1


@dataclass(frozen=True, slots=True)
class Covered:
    """A position an `Origin` reaches into. 03:1877.

    This is anydoc's `CellSlot::Covered { origin_row, origin_col }`
    (`anydoc/src/model/table.rs`), and it is "strictly better than a sparse cell list with spans
    because every coordinate is addressable -- which is precisely what 'which cell is above this
    one' needs" (03:1898-1900). It carries the origin's COORDINATE and not its `BlockId`, exactly
    as printed: a coordinate is what `grid_slot`'s primary key resolves against, and `origin()`
    is the one step that turns it into a cell.
    """

    origin_r: int
    origin_c: int


#: 03:1878. Two arms and no third: a position inside the grid is owned, or it is covered.
Slot = Origin | Covered


# ---------------------------------------------------------------------------
# 2. `Grid` -- 03:1880-1893.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Grid:
    """One table's derived cover map. **PRIVATE ctor: `build_grid()` is the only way in** (03:1880).

    Enforcement of the private constructor is LEXICAL, which is the same call `model/spans.py`
    records for `Quad.from_driver`: a frozen dataclass cannot make `__init__` private, the plan
    prints `class Grid:` with the note rather than a factory-only type, and the gate is a grep for
    `Grid(` outside `build_grid`. That semgrep rule is not in `tools/semgrep/omniweave.yaml`;
    reported.

    The nine printed fields are 03:1881-1887 in the printed order. `row_len` is the per-row length
    and `n_cols = max(row_len)`, because **raggedness is explicit** (03:2042-2045): a ragged table
    is neither padded with phantom cells nor rejected, and the projection pads at render time
    because GFM requires it.

    `origins` is the `cell` table -- origin cells only, ten rows for 03 section 10.3's twelve
    positions. `cover` is the `grid_slot` table: EMPTY when `has_merges` is false, and otherwise
    TOTAL over `sum(row_len)` positions with an origin mapping to itself (03:1902-1907). Both are
    `MappingProxyType`, so a frozen `Grid` is frozen all the way down, and both are named rather
    than hidden because `DocSink.add_grid` writes exactly these two tables (03:580) and reaches
    them through `cells()` and `grid_slots()`.

    **A gap inside the declared extent resolves to `None`, and that is not a bug.** The
    exactly-once invariant (03:1895-1897) says every position with `r < n_rows` and
    `c < row_len[r]` resolves to exactly one `Origin`; a driver that emitted `(0,0)` and `(0,2)`
    and nothing at `(0,1)` has broken it, and `build_grid` neither invents a phantom cell there
    (03:2042-2045 forbids exactly that) nor refuses the table. `slot()` returns `None`, the render
    emits a blank, and `owcheck` over the staged generation is where the missing cell is reported.
    """

    n_rows: int
    n_cols: int
    row_len: tuple[int, ...]
    header_rows: int
    header_cols: int
    kind: TableKind
    recon: tuple[str, float | None] | None
    has_merges: bool
    native: tuple[str, bytes] | None
    origins: Mapping[tuple[int, int], Origin]
    cover: Mapping[tuple[int, int], tuple[int, int]]
    clamps: int

    # -- the coordinate system ------------------------------------------

    def inside(self, r: int, c: int) -> bool:
        """Whether `(r, c)` is a logical position of this grid. 03:1895-1896's own predicate."""
        return 0 <= r < self.n_rows and 0 <= c < self.row_len[r]

    def slot(self, r: int, c: int) -> Slot | None:
        """`O(1)`; the position resolved to exactly one `Origin`, or the `Covered` pointing at it.

        `None` for a position outside the grid and for a gap inside it -- see the class docstring.
        When `has_merges` is false this is one dict hit on `cell`, which is 03:1906's "`slot(r, c)`
        is arithmetic against `cell`" with the arithmetic already done at build time.
        """
        if not self.inside(r, c):
            return None
        owned = self.origins.get((r, c))
        if owned is not None:
            return owned
        if not self.has_merges:
            return None
        at = self.cover.get((r, c))
        if at is None or at == (r, c):
            return None
        return Covered(at[0], at[1])

    def origin(self, r: int, c: int) -> Origin | None:
        """The cell whose CONTENT lives at `(r, c)` -- one step through the cover map. 03:1888."""
        if not self.inside(r, c):
            return None
        if not self.has_merges:
            return self.origins.get((r, c))
        at = self.cover.get((r, c))
        return None if at is None else self.origins.get(at)

    # -- the four neighbours -- 03:1889, 03:2008-2010 --------------------

    def up(self, r: int, c: int) -> Origin | None:
        """The origin one row above. 03:2008 prints the SQL: `... AND c=?2 AND r=?3-1`.

        Literally one row, which is why `up` on the lower half of a `row_span=2` cell answers that
        same cell: the charter's query is a single indexed read against `grid_slot` and has no
        notion of stepping over a span. 03 gives no other rule and this one is printed, so it is
        what ships; a caller wanting the cell above the SPAN compares `Origin.r` and steps again.
        """
        return self.origin(r - 1, c)

    def down(self, r: int, c: int) -> Origin | None:
        """The origin one row below. The mirror of `up`, with the same one-row step."""
        return self.origin(r + 1, c)

    def left(self, r: int, c: int) -> Origin | None:
        """The origin one column left. `grid.left(2,1)` -> `Cloud` in 03:2010's worked table."""
        return self.origin(r, c - 1)

    def right(self, r: int, c: int) -> Origin | None:
        """The origin one column right."""
        return self.origin(r, c + 1)

    # -- the two header chains -- 03:1890-1891, 03:2012-2021 -------------

    def top_heading(self, c: int) -> tuple[Origin, ...]:
        """The CHAIN of distinct origins covering rows `0 .. header_rows-1` of column `c`.

        Outermost first, which for a column header means row 0 first. A chain and not a single
        cell "because `header_rows > 1` is exactly the case that matters" (03:2014-2015), and the
        worked example is the assertion: with `header_rows = 2`, `top_heading(1)` is
        `[FY2024, Q1]` and `top_heading(2)` is `[FY2024, Q2]` -- both columns share the `FY2024`
        origin, "which is the whole point of the cover map" (03:2018-2019). **Extends the
        charter**: D2 gives the signature and not the return type (03:2020-2021).

        Distinctness is by origin COORDINATE, which is the cover map's own key; two cells of one
        table cannot share a `BlockId`, so the two spellings agree and this one needs no read.
        """
        return self._chain((r, c) for r in range(min(self.header_rows, self.n_rows)))

    def left_heading(self, r: int) -> tuple[Origin, ...]:
        """The CHAIN of distinct origins covering columns `0 .. header_cols-1` of row `r`.

        Outermost first. `left_heading(2)` is `[Cloud]` from `header_cols = 1` (03:2019-2020).
        """
        return self._chain((r, c) for c in range(self.header_cols))

    def _chain(self, positions: Iterable[tuple[int, int]]) -> tuple[Origin, ...]:
        seen: set[tuple[int, int]] = set()
        out: list[Origin] = []
        for r, c in positions:
            found = self.origin(r, c)
            if found is None or (found.r, found.c) in seen:
                continue
            seen.add((found.r, found.c))
            out.append(found)
        return tuple(out)

    # -- what `add_grid` writes -- 03:580 --------------------------------

    def cells(self) -> Iterator[Origin]:
        """Every origin, row-major. The `cell` rows `add_grid` writes (03:580).

        Row-major and not arrival order: 03:1993-1994 requires the ten origins' `ord` values among
        the table's children to be "0-9 in that order -- row-major over origins, dense from 0", so
        the order this yields is the order that fact is written in. A stream that arrived in order
        is already sorted and the sort is then a linear scan.
        """
        for key in sorted(self.origins):
            yield self.origins[key]

    def grid_slots(self) -> Iterator[tuple[int, int, BlockId]]:
        """Every `(r, c, origin_id)` row of `grid_slot`, row-major. EMPTY unless `has_merges`.

        03:1904-1907: the map "holds all `sum(row_len)` positions, an origin position mapping to
        itself" when there are merges, and the table has "**zero rows** of `grid_slot`" when there
        are none. That is why this reads `cover` rather than re-deriving the walk: the emptiness
        is a stored fact, not a recomputation.
        """
        if not self.has_merges:
            return
        for key in sorted(self.cover):
            owner = self.origins[self.cover[key]]
            yield key[0], key[1], owner.block

    # -- the gfm trim -- 03:2035-2038 ------------------------------------

    def gfm_extent(self, nonblank: Callable[[BlockId], bool]) -> tuple[int, int]:
        """`(rows, cols)` after 03:2036-2037's two trimming rules, and nothing else.

        "pops trailing all-blank rows, truncates trailing all-blank columns". A position renders
        blank when no `Origin` owns it -- a `Covered` slot "renders as a blank cell" because "GFM
        has no span syntax" (03:2035-2036) -- so blankness is decided over origins alone and
        `nonblank` is asked only about cells that exist. Rows are popped BEFORE columns are
        truncated, so a column kept alive only by a row that is about to be popped goes too; the
        plan prints the two rules in that order.

        This is a pure function of the grid plus one predicate, which is what lets
        `model/serialize.py` delegate to it instead of keeping a second trim.
        """
        rows = self.n_rows
        while rows and self._row_blank(rows - 1, self.n_cols, nonblank):
            rows -= 1
        cols = self.n_cols
        while cols and self._col_blank(cols - 1, rows, nonblank):
            cols -= 1
        return rows, cols

    def _row_blank(self, r: int, cols: int, nonblank: Callable[[BlockId], bool]) -> bool:
        for c in range(min(self.row_len[r], cols)):
            owned = self.origins.get((r, c))
            if owned is not None and nonblank(owned.block):
                return False
        return True

    def _col_blank(self, c: int, rows: int, nonblank: Callable[[BlockId], bool]) -> bool:
        for r in range(rows):
            owned = self.origins.get((r, c))
            if owned is not None and nonblank(owned.block):
                return False
        return True


# ---------------------------------------------------------------------------
# 3. `build_grid` -- the sole constructor, and it streams. 03 section 10.2.
# ---------------------------------------------------------------------------


class _Builder:
    """The resident state of one `build_grid` call, and nothing else is held.

    03:1940-1942 prices it: `row_len` (one integer per row), a covered map for the rows still
    reachable by an open `row_span`, and "the origin map **only for merged origins**". This holds
    the origin map for EVERY origin instead, and the difference is deliberate and priced: a
    `Grid` must answer `origin(r, c)` for an unmerged 4M-cell sheet too, and an `Origin` is the
    only place its `BlockId` lives. 03:1931 is the same arithmetic and calls it tolerable --
    "4M x 24 B of position data plus 4M `BlockId`s". What the plan refuses is buffering the
    cells' DRAFTS, at 4.4 GB, and that is what the `Iterable` parameter avoids.

    The covered map is a dict rather than the printed bitmap. Same bound, because a key exists
    only for a position some span actually reaches, and it carries the origin coordinate the
    bitmap would have had to look up separately.
    """

    __slots__ = ("charged", "clamps", "cover", "has_merges", "n_rows", "origins", "row_len")

    def __init__(self) -> None:
        self.origins: dict[tuple[int, int], Origin] = {}
        self.cover: dict[tuple[int, int], tuple[int, int]] = {}
        self.row_len: dict[int, int] = {}
        self.charged = 0
        self.clamps = 0
        self.n_rows = 0
        self.has_merges = False

    def taken(self, r: int, c: int) -> bool:
        return (r, c) in self.origins or (r, c) in self.cover

    def place(self, block: BlockId, pos: CellPos) -> None:
        """One cell, charged then clamped then registered. The order is the specification."""
        self.charge(pos)
        if self.taken(pos.r, pos.c):
            # The origin can own NOTHING, so it is dropped rather than moved: moving it would
            # invent a position the source never stated. 03:1916-1917's "later placements skip
            # them", counted as a clamp because the span it declared was reduced to zero.
            self.clamps += 1
            return
        rows, cols = self.clamped(pos)
        if rows != pos.row_span or cols != pos.col_span:
            self.clamps += 1
        self.origins[(pos.r, pos.c)] = Origin(block, pos.r, pos.c, rows, cols)
        if rows > 1 or cols > 1:
            self.has_merges = True
        for dr in range(rows):
            row = pos.r + dr
            for dc in range(cols):
                if dr or dc:
                    self.cover[(row, pos.c + dc)] = (pos.r, pos.c)
            self.row_len[row] = max(self.row_len.get(row, 0), pos.c + cols)
        self.n_rows = max(self.n_rows, pos.r + rows)

    def charge(self, pos: CellPos) -> None:
        """`MAX_EXPANSION` against the DECLARED span area, BEFORE expanding it. 03:1922-1925.

        The declared area and not the clamped one, because the attack this stops is
        `rowspan="99999"` in a three-row table (03:2657) and a clamp is computed by walking the
        very positions the charge exists to prevent walking. anydoc's own pre-check refuses with
        "table span expansion exceeds the content budget" (`table.rs:175`) for the same reason,
        and the charge is incremental "so the refusal happens on the cell that crosses it, not
        after 4M allocations" (03:1945-1946).
        """
        self.charged += pos.row_span * pos.col_span
        if self.charged > MAX_EXPANSION:
            msg = (
                f"this table charges {self.charged} span slots at cell "
                f"(r={pos.r}, c={pos.c}), past MAX_EXPANSION={MAX_EXPANSION}"
            )
            raise ResourceLimit(
                msg,
                limit="MAX_EXPANSION",
                fix="ow doc verify <cite>  # find the table whose spans exceed the budget",
            )

    def clamped(self, pos: CellPos) -> tuple[int, int]:
        """The spans this origin can ACTUALLY own. 03:1916-1921, anydoc `table.rs:179-197`.

        anydoc's own comment states the reason: "Clamp the spans to positions this origin can
        actually own -- an overlap with an earlier span would break the exactly-once invariant".
        Columns are clamped first and rows against the clamped width, so the result is a
        rectangle; clamping the two independently could leave an L-shape, which is not a span.

        Clamping rather than raising is deliberate (03:1921-1925): "overlapping rowspans are
        routine in hand-written HTML, so raising would be fail-closed on **common** input, which
        is a different thing from fail-closed on adversarial input."
        """
        cols = pos.col_span
        for dc in range(1, pos.col_span):
            if self.taken(pos.r, pos.c + dc):
                cols = dc
                break
        rows = pos.row_span
        for dr in range(1, pos.row_span):
            if any(self.taken(pos.r + dr, pos.c + dc) for dc in range(cols)):
                rows = dr
                break
        return rows, cols

    def finish(
        self,
        *,
        header_rows: int,
        header_cols: int,
        kind: TableKind,
        recon: tuple[str, float | None] | None,
        native: tuple[str, bytes] | None,
    ) -> Grid:
        """`row_len`, `n_cols`, and the ONE pass that materialises `grid_slot`. 03:1943-1944.

        "`grid_slot` rows are written only after `has_merges` is known to be 1, in one pass over
        the completed `row_len` -- which is why `add_grid` is called once, at the end." So the
        total cover map is built here and only here, and only when there are merges.
        """
        row_len = tuple(self.row_len.get(r, 0) for r in range(self.n_rows))
        n_cols = max(row_len, default=0)
        total: dict[tuple[int, int], tuple[int, int]] = {}
        if self.has_merges:
            slots = sum(row_len)
            if slots > MAX_GRID_SLOTS:
                msg = (
                    f"this table's cover map is {slots} slots, past MAX_GRID_SLOTS={MAX_GRID_SLOTS}"
                )
                raise ResourceLimit(
                    msg,
                    limit="MAX_GRID_SLOTS",
                    fix="ow doc verify <cite>  # find the table whose cover map exceeds the cap",
                )
            for r in range(self.n_rows):
                for c in range(row_len[r]):
                    if (r, c) in self.origins:
                        total[(r, c)] = (r, c)
                    elif (r, c) in self.cover:
                        total[(r, c)] = self.cover[(r, c)]
        return Grid(
            n_rows=self.n_rows,
            n_cols=n_cols,
            row_len=row_len,
            header_rows=header_rows,
            header_cols=header_cols,
            kind=kind,
            recon=recon,
            has_merges=self.has_merges,
            native=native,
            origins=MappingProxyType(dict(self.origins)),
            cover=MappingProxyType(total),
            clamps=self.clamps,
        )


def _cell_position(cell: object) -> tuple[BlockId, CellPos]:
    """`(id, pos)` off one `CellDraft` (03:337-338), read structurally.

    `CellDraft` is 03 section 2.6's -- it is printed inside `BlockDraft`'s own fence, beside
    `CellPos` -- and section 2.6 is `model/block.py`'s cluster, which has not declared it.
    Declaring it here would give one name two homes (INV-21), so this reads the two attributes
    the plan gives it and names what is missing when they are absent. Reported as a required edit
    to `block.py`.
    """
    block = getattr(cell, "id", None)
    pos = getattr(cell, "pos", None)
    if not isinstance(block, int) or not isinstance(pos, CellPos):
        msg = (
            f"build_grid takes CellDraft (03:337: `id: BlockId; pos: CellPos`), not "
            f"{type(cell).__name__}"
        )
        raise UsageError(msg, fix="ow doc verify <cite>  # the driver emitted a malformed cell")
    return BlockId(block), pos


def _validated(pos: CellPos) -> CellPos:
    """A position is non-negative and a span is at least 1. Local, so it is checked locally.

    `Block` deliberately validates nothing in `__post_init__` (see that class) because every rule
    it obeys is relational. These two are not: a negative row or a zero span is unrepresentable in
    the grid regardless of what else the table holds, and the `cell` DDL carries no CHECK that
    would catch it later.
    """
    if pos.r < 0 or pos.c < 0:
        msg = f"a cell position is non-negative, not (r={pos.r}, c={pos.c})"
        raise UsageError(msg, fix="ow doc verify <cite>  # the driver emitted a negative position")
    if pos.row_span < 1 or pos.col_span < 1:
        msg = (
            f"a span is at least 1, not (row_span={pos.row_span}, col_span={pos.col_span}) "
            f"at (r={pos.r}, c={pos.c})"
        )
        raise UsageError(msg, fix="ow doc verify <cite>  # the driver emitted a zero span")
    return pos


def _as_table_kind(kind: str | TableKind) -> TableKind:
    """`"data"` or `TableKind.DATA`, one closed domain. See the module docstring's divergence 1."""
    try:
        return TableKind(kind)
    except ValueError as exc:
        members = tuple(member.value for member in TableKind)
        msg = f"a table kind is one of {members}, not {kind!r}"
        raise UsageError(msg, fix="ow doc verify <cite>  # fix the table's kind") from exc


def build_grid(
    cells: Iterable[CellDraft],  # noqa: F821 -- 03:337's, `block.py`'s; see `_cell_position`.
    *,
    header_rows: int = 0,
    header_cols: int = 0,
    kind: str | TableKind = TableKind.DATA,
    recon: tuple[str, float | None] | None = None,
    native: tuple[str, bytes] | None = None,
    diag: Callable[[Diag], None],  # noqa: F821 -- 03:1800's; section 9 has no module yet.
) -> Grid:
    """The sole constructor, and it streams. 03:1912-1914.

    **The parameter is an `Iterable`, not a `Sequence`, and 03:1927-1935 calls that "the fix for
    the hardest scale problem in the section".** The charter celebrates a merge-free 4M-cell sheet
    while typing this input as resident; buffering the cells' drafts is 4.4 GB. So cells are
    consumed one at a time and the resident state is `_Builder`'s.

    **Cells arrive in row-major origin order** -- non-decreasing `r`, and within a row increasing
    `c` (03:1937). A cell that arrives out of that order is held in a resident buffer "bounded by
    `MAX_RESIDENT_CELLS = 65_536`, above which the table is `RESOURCE_LIMIT{MAX_RESIDENT_CELLS}`"
    (03:1937-1939), and 03:2652 homes that limit here in as many words: "out-of-order cells in
    `build_grid`". The buffer is flushed, sorted, after the stream ends -- so an in-order stream
    never allocates it, and a shuffled stream produces the same grid as the sorted one whenever
    no two spans overlap. With overlaps the in-order arrivals win the clamp, because "first
    writer wins" is over arrival order and nothing can undo a placement.

    **`has_merges` is discovered incrementally**: 1 as soon as any cell has a span > 1
    (03:1942-1943). It is never a parameter, which is what makes "a merge-free sheet has zero
    `grid_slot` rows" a property of the data rather than a claim a caller can get wrong.

    `diag` is required and carries no default, exactly as printed. It is not called yet; the
    module docstring says why, and `Grid.clamps` carries the fact it would have reported.

    Raises:
        UsageError    -- a malformed cell, a negative position, a zero span, a negative header
                         count, or a `kind` outside the closed `table_kind` domain (`OW_SURFACE`).
        ResourceLimit -- `MAX_EXPANSION` on the charged span area, charged on the cell that
                         crosses it; `MAX_RESIDENT_CELLS` on out-of-order arrivals;
                         `MAX_GRID_SLOTS` on the materialised cover map (`OW_RESOURCE_LIMIT`).
    """
    if not callable(diag):
        msg = "build_grid's `diag` is the sink a clamp is recorded on (03:1914), not a value"
        raise UsageError(msg, fix="ow doc verify <cite>  # pass a callable diag sink")
    if header_rows < 0 or header_cols < 0:
        msg = f"header counts are non-negative, not ({header_rows}, {header_cols})"
        raise UsageError(msg, fix="ow doc verify <cite>  # fix the table's header counts")
    table_kind = _as_table_kind(kind)
    builder = _Builder()
    buffered: list[tuple[tuple[int, int], BlockId, CellPos]] = []
    last = (-1, -1)
    for cell in cells:
        block, raw = _cell_position(cell)
        pos = _validated(raw)
        key = (pos.r, pos.c)
        if key <= last:
            buffered.append((key, block, pos))
            if len(buffered) > MAX_RESIDENT_CELLS:
                msg = (
                    f"{len(buffered)} cells arrived outside row-major order at (r={pos.r}, "
                    f"c={pos.c}), past MAX_RESIDENT_CELLS={MAX_RESIDENT_CELLS}"
                )
                raise ResourceLimit(
                    msg,
                    limit="MAX_RESIDENT_CELLS",
                    fix="ow doc verify <cite>  # the driver must emit cells in row-major order",
                )
            continue
        last = key
        builder.place(block, pos)
    for _key, block, pos in sorted(buffered, key=lambda item: item[0]):
        builder.place(block, pos)
    return builder.finish(
        header_rows=header_rows,
        header_cols=header_cols,
        kind=table_kind,
        recon=recon,
        native=native,
    )


# ---------------------------------------------------------------------------
# 4. `render_grid` -- 03:1892, and 03:2035-2040 is the whole of its specification.
# ---------------------------------------------------------------------------


class GridReadSide(Protocol):
    """What `render_grid` reads. One method, because a cover map holds ids and not text.

    Structural, and deliberately not `omniweave_core.store.Reader` (07:63-68): that Protocol is
    the retrieval boundary, its six methods are frozen, and `model` may not import `store` at all
    -- the dependency runs the other way (`store/types.py`:34-36 waits on this module).
    `model/rebind.py` records the same decision for `RebindReadSide`, and
    `omniweave_core.model.doc.Doc` satisfies this one by carrying a `block` method with this
    signature, which is what makes 03:2035's `render_grid(g, reader, "gfm")` read naturally with
    a `Doc` in the middle.
    """

    def block(self, block: BlockId) -> Block:
        """One cell's Block.

        Raises rather than returning `None`: `Origin.block` names a cell the same `build_grid`
        call placed, so an absent row is a torn store and not a miss.
        """
        ...


def render_grid(
    g: Grid,
    reader: GridReadSide,
    fmt: str,
    *,
    table: BlockId = SYNTHETIC_TABLE,
) -> tuple[str, ArraySpanMap]:
    """Render one table. 03:1892 -- "no `.html` and no `.markdown`. Those are renders."

    Returns `(str, SpanMap)` and never the string alone, which is the framework's one-serializer
    rule (03:2863-2864, 16-roadmap.md:421: "if you have the text you have the map"). Every pipe,
    every `<td>` and every OTSL token is synthetic in that map, so a quote lifted off a rendered
    table is not automatically verbatim -- which is the property the pair exists to preserve.

    **It delegates to `omniweave_core.model.serialize`** rather than carrying a second table
    renderer: INV-1 makes a projection a function, and two functions rendering one table in one
    format is exactly the second representation the invariant forbids. What this adds is the two
    things a `ViewScope` cannot express -- 03:2036-2037's gfm trim, computed by
    `Grid.gfm_extent()`, and the wrapper Block the cells hang under.

    **The gfm trim is applied to the SCOPE, not to the output**, because a trim performed on the
    rendered string could not keep the `SpanMap` honest. Cells outside the trimmed extent are
    dropped and surviving spans are clamped to it, so the scope the serializer receives already
    has the trimmed `n_rows`/`n_cols`. `fmt != "gfm"` trims nothing: 03:2035 states the rule for
    `render_grid(g, reader, "gfm")` and 03:2874-2879's format table gives `md`, `html`, `text`
    and `otsl` no such rule.

    **Blankness is a cell's own `text`.** A cell may carry a subtree (03:826) and `serialize`
    descends it, but this function is handed a cover map and a one-method reader, so a cell's
    children are not in view; a table whose cells have subtrees renders through `Doc.serialize`,
    which resolves the whole scope. Recorded rather than silently approximated.

    `table` names the table's own `BlockId` and defaults to `SYNTHETIC_TABLE`. 03:2035 prints
    three positional arguments and `Grid` carries no table id -- `add_grid(b, g)` passes it
    alongside (03:557) -- so a caller that has the id passes it and the render's spans are
    attributed to the real block; a caller that does not gets a frame Block at id `0`, which no
    row can hold. Either way the wrapper carries no `text`, so it owns no character of the view.

    Raises:
        UsageError -- `fmt` is not one of the five (`OW_SURFACE`), checked BEFORE any read so a
                      typo does not cost a scan of the table.
    """
    if fmt not in FORMATS:
        msg = f"fmt must be one of {FORMATS}, not {fmt!r}"
        raise UsageError(msg, fix="ow doc render --format md <cite>")
    blocks: dict[BlockId, Block] = {}
    for origin in g.cells():
        blocks[origin.block] = reader.block(origin.block)
    if table != SYNTHETIC_TABLE and table not in blocks:
        blocks[table] = reader.block(table)
    if fmt == "gfm":
        rows, cols = g.gfm_extent(lambda b: bool((blocks[b].text or "").strip()))
    else:
        rows, cols = g.n_rows, g.n_cols
    scope = _grid_scope(g, blocks, table, rows, cols)
    return serialize(scope, fmt)  # type: ignore[arg-type]


def _grid_scope(
    g: Grid,
    blocks: Mapping[BlockId, Block],
    table: BlockId,
    rows: int,
    cols: int,
) -> ViewScope:
    """The `ViewScope` one table renders over: the wrapper, then its cells row-major.

    `ord` is dense from 0 in row-major order over origins, which is 03:1993-1994's requirement
    restated as a render input. A cell whose position falls outside the trimmed extent is absent
    from the scope entirely rather than present with an empty span, because `serialize()` gives
    every block in a scope a span and an unplaced block would be a zero-length one.
    """
    wrapper = blocks.get(table) or _wrapper(table)
    kept: list[Block] = []
    positions: dict[BlockId, CellPos] = {}
    # A cell whose id is also the named table's would appear twice and `ViewScope` refuses a
    # duplicate (03:2815). That is a caller error rather than a shape to repair, so the cell is
    # the one dropped: the wrapper is the frame the render needs and a table cannot be its own cell.
    inside = (o for o in g.cells() if o.r < rows and o.c < cols and o.block != wrapper.id)
    for order, origin in enumerate(inside):
        cell = blocks[origin.block]
        kept.append(_reparent(cell, wrapper.id, order))
        positions[origin.block] = CellPos(
            r=origin.r,
            c=origin.c,
            row_span=min(origin.row_span, rows - origin.r),
            col_span=min(origin.col_span, cols - origin.c),
        )
    facts = TableFacts(
        kind=g.kind,
        header_rows=min(g.header_rows, rows),
        header_cols=min(g.header_cols, cols),
    )
    return ViewScope(
        blocks=(wrapper, *kept),
        kind="subtree",
        tables=MappingProxyType({wrapper.id: facts}),
        cells=MappingProxyType(positions),
    )


def _reparent(cell: Block, parent: BlockId, order: int) -> Block:
    """The cell as the render's own child. `parent` and `ord` are the only fields touched.

    A cell IS an ordinary Block (03:826) and this render places it under one wrapper, so its
    stored `parent`/`ord` -- which point at the real table in the real document -- would make the
    scope's forest disagree with itself. Nothing else is rewritten: `text`, `marks`, `trust`,
    `quote` and every identity field are the store's, so the `SpanMap` attributes each character
    to the block that really said it.
    """
    if cell.parent == parent and cell.ord == order:
        return cell
    return replace(cell, parent=parent, ord=order)


def _wrapper(table: BlockId) -> Block:
    """The frame Block a render hangs its cells under when the caller named no table.

    Every provenance axis is the LOWEST value in its ladder rather than a plausible one:
    `Trust.AMBIGUOUS` is "absent trust, and it is COUNTED" (03:1613) and `Quote.SYNTHETIC` is the
    bottom of the byte-exactness ladder. That is the honest reading -- this Block was invented by
    a render, so it may not claim a trust or a quote it did not earn. The closed `method` domain
    has no synthetic member, and `Method.NATIVE` is the one that means "read from the container's
    own structure", which is where a grid comes from.
    """
    return Block(
        id=table,
        addr=Addr(""),
        cite=Cite(""),
        doc_ord=0,
        gen=0,
        page=0,
        parent=None,
        ord=0,
        kind=Kind.TABLE,
        raw_kind=None,
        layer=Layer.BODY,
        label=None,
        text=None,
        content_digest=b"",
        layout_digest=None,
        revision=0,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=0,
        method=Method.NATIVE,
        trust=Trust.AMBIGUOUS,
        quote=Quote.SYNTHETIC,
    )
