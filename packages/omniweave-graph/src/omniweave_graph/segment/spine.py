"""`derive.segment.spine`'s algorithm: one document's blocks in, its Segments out. **D662.**

Pure: no I/O, no clock, no store. `driver.py` decodes the host's view into `Block`s and encodes
`Spine` as `owgraph-items/1`; everything between is here, so the rules can be tested without a
wire.

06-structure-extraction.md section 3.2 is the specification:

    emit on: n_tokens >= SEGMENT_TARGET_TOKENS (1200)
           | n_blocks + 1 >= MAX_SEGMENT_BLOCKS (512)      <- BEFORE the 513th block
           | appending the next block would push n_tokens past MAX_SEGMENT_TOKENS (2048)
           | the heading ancestor changes
           | the next block is kind TABLE

## The readings this module takes where the plan is silent

1. **A member is a block with text.** A container (`text` NULL: a `table`, a `list`, a `section`,
   a `picture`) belongs to no Segment and is reached through its children; a `segment_block` row
   per container would spend cover bits on blocks no lane can read. "A Block belongs to exactly one
   Segment" (16-roadmap.md W8.1) therefore reads as *at most* one, which is also what the synopsis
   rule already requires of the 20,001 cells it does not carry.
2. **"The heading ancestor changes" is "`sec_path` changes".** `block_sec` gives every block the
   path of the section it lives in, and a heading block carries its own section's path, so a
   heading always opens the Segment of its section and `heading_path` is that section's chain.
3. **Layers are segmented separately, in a fixed order** -- body, furniture, note, annotation,
   hidden, then any other value in first-seen order -- so a footnote's text never shares a Segment
   with the body (06:988) and a segment's `ord` does not depend on where the first page header fell.
4. **A table is packed in whole rows under `TABLE_SEGMENT_TOKENS` as a ceiling, with the header rows
   counted in every Segment's cost and stored as members of the first only.** "Header rows
   REPEATED" (06:989) is a property of what the extraction prompt shows; `segment_block` has
   `block_id` as its primary key, so a header cell can be a member once. A Segment always takes at
   least one data row, so a header never stands alone unless the block cap forces it.
5. **`TABLE_SYNOPSIS_CELLS` is the only path to a synopsis; `TABLE_MAX_SEGMENTS` is met by growing
   the Segments.** 06:989 bounds a table "by TABLE_SEGMENT_TOKENS 400 / TABLE_MAX_SEGMENTS 32" and
   names a remedy only past 20,000 cells. The two cannot both be hard below that: 32 x 400 tokens
   is passed by every table of 12,801 one-token cells, and 32 x 511 blocks by every table of 16,353
   cells, so either reading of the count as a synopsis trigger would leave `TABLE_SYNOPSIS_CELLS`
   unreachable. So a table is packed at `max(TABLE_SEGMENT_TOKENS, ceil(tokens / 32))`, again at
   `MAX_SEGMENT_TOKENS` if row granularity still overflows 32, and where the block cap still
   forces more (about 16k to 20k cells, at most 40 Segments) every row is kept with
   `Diag(OW_RESOURCE_LIMIT, {limit: "TABLE_MAX_SEGMENTS"})`. The synopsis Segment's members are the
   header rows and eight evenly spaced data rows, packed until a cap would be crossed. The
   dimensions and per-column type and range 06:990 lists are derived from the stored grid by
   whoever assembles the extraction prompt, not stored here -- `segment` has no column for them
   and every input is a stored field.
6. **A row is the table's atom, and only the block cap splits one.** A row wider than
   `MAX_SEGMENT_BLOCKS - 1` cells is cut into runs of that many, with
   `Diag(OW_RESOURCE_LIMIT, {limit: "MAX_SEGMENT_BLOCKS"})`; a row whose tokens alone pass
   `MAX_SEGMENT_TOKENS` is its own Segment with the `MAX_SEGMENT_TOKENS` Diag, as a block is.
7. **A cell outside its table's run is prose.** Cells arrive immediately after their `table` block;
   one that does not (a nested table's outer cells, resumed) is segmented as an ordinary block
   rather than refused.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from omniweave_graph.tokens import count_tokens

__all__ = [
    "LAYER_ORDER",
    "MAX_SEGMENT_BLOCKS",
    "MAX_SEGMENT_TOKENS",
    "SEGMENT_TARGET_TOKENS",
    "SYNOPSIS_SAMPLE_ROWS",
    "TABLE_MAX_SEGMENTS",
    "TABLE_SEGMENT_TOKENS",
    "TABLE_SYNOPSIS_CELLS",
    "Block",
    "Grid",
    "Notice",
    "Params",
    "Segment",
    "Spine",
    "heading_path",
    "segment",
]

SEGMENT_TARGET_TOKENS: Final = 1200
"""A target, not a ceiling: a Segment is emitted once it reaches this (01-principles.md:624)."""
MAX_SEGMENT_TOKENS: Final = 2048
"""The ceiling. Equal to `omniweave_core.limits.MAX_SEGMENT_TOKENS`, which this package may not
import; `tests/unit/test_segment_spine.py` holds the two equal."""
MAX_SEGMENT_BLOCKS: Final = 512
"""Exact: `derive_cover.cover_bits` is `ceil(512 / 8) = 64` bytes. A Segment holds at most 511."""
TABLE_SEGMENT_TOKENS: Final = 400
"""A table Segment's ceiling, lower than prose's because repeated header rows are overhead."""
TABLE_MAX_SEGMENTS: Final = 32
"""A table's Segments grow toward `MAX_SEGMENT_TOKENS` to stay at or under this many (reading 5)."""
TABLE_SYNOPSIS_CELLS: Final = 20_000
"""Past this many cells a table is ONE synopsis Segment plus `Diag(OW_TABLE_SYNOPSIS_ONLY)`."""
SYNOPSIS_SAMPLE_ROWS: Final = 8
"""06:990's "eight sampled rows"."""

LAYER_ORDER: Final = ("body", "furniture", "note", "annotation", "hidden")
"""`Layer`'s members in declaration order: the order Segments are numbered in (reading 3)."""

_COMPONENT: Final = "derive.segment.spine"
_RESOURCE_LIMIT: Final = "OW_RESOURCE_LIMIT"
_SYNOPSIS_ONLY: Final = "OW_TABLE_SYNOPSIS_ONLY"


@dataclass(frozen=True, slots=True)
class Params:
    """The segmenter's flat parameters. Their canonical digest is `segmenter.params_digest`.

    A value above its framework ceiling is refused: an operator may segment finer, never coarser
    than the cover bitmap and the prompt budget were sized for.
    """

    target_tokens: int = SEGMENT_TARGET_TOKENS
    max_tokens: int = MAX_SEGMENT_TOKENS
    max_blocks: int = MAX_SEGMENT_BLOCKS
    table_tokens: int = TABLE_SEGMENT_TOKENS
    table_max_segments: int = TABLE_MAX_SEGMENTS
    table_synopsis_cells: int = TABLE_SYNOPSIS_CELLS

    def __post_init__(self) -> None:
        ceilings = {
            "max_tokens": MAX_SEGMENT_TOKENS,
            "max_blocks": MAX_SEGMENT_BLOCKS,
            "table_max_segments": TABLE_MAX_SEGMENTS,
            "table_synopsis_cells": TABLE_SYNOPSIS_CELLS,
        }
        for name in (
            "target_tokens",
            "max_tokens",
            "max_blocks",
            "table_tokens",
            "table_max_segments",
            "table_synopsis_cells",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer, not {value!r}")
            if name in ceilings and value > ceilings[name]:
                raise ValueError(f"{name} = {value} is above its ceiling {ceilings[name]}")
        if self.max_blocks < 2:  # noqa: PLR2004 -- a Segment holds max_blocks - 1 >= 1 block
            raise ValueError("max_blocks must be at least 2: a Segment holds max_blocks - 1")
        for name in ("target_tokens", "table_tokens"):
            if getattr(self, name) > self.max_tokens:
                raise ValueError(f"{name} must not exceed max_tokens = {self.max_tokens}")


@dataclass(frozen=True, slots=True)
class Grid:
    """A `table` block's shape, from `table_meta`."""

    n_rows: int
    n_cols: int
    header_rows: int = 0


@dataclass(frozen=True, slots=True)
class Block:
    """One block of the host's view, in reading order. Addressed by `cite` only -- no `block_id`."""

    cite: str
    kind: str
    layer: str = "body"
    page: int = 1
    sec: str = "/"
    text: str | None = None
    grid: Grid | None = None
    table: str | None = None
    """The `table` block's cite when this block is one of its cells."""
    r: int = 0
    c: int = 0


@dataclass(frozen=True, slots=True)
class Segment:
    """One Segment: what the driver decides. The host derives every other `segment` column."""

    layer: str
    heading_path: tuple[str, ...]
    blocks: tuple[str, ...]
    n_tokens: int
    atom: str | None = None
    synopsis_of: str | None = None


@dataclass(frozen=True, slots=True)
class Notice:
    """A Diag the segmenter owes the operator: a disclosed refusal, never a silent one."""

    code: str
    message: str
    cite: str
    page: int
    detail: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Spine:
    segments: tuple[Segment, ...]
    notices: tuple[Notice, ...]


def heading_path(sec: str, sections: Mapping[str, str]) -> tuple[str, ...]:
    """The heading texts of `sec` and its ancestors, outermost first.

    `'/0001/0004'` walks `'/0001'` then `'/0001/0004'`; a path with no heading text in `sections`
    (the implicit root, or a section the host did not name) contributes nothing.
    """
    if sec in {"", "/"}:
        return ()
    parts = sec.strip("/").split("/")
    prefixes = ("/" + "/".join(parts[: i + 1]) for i in range(len(parts)))
    return tuple(sections[p] for p in prefixes if p in sections)


def segment(
    blocks: Iterable[Block], sections: Mapping[str, str], params: Params | None = None
) -> Spine:
    """Partition one document's blocks into Segments. Deterministic in its input order."""
    run = _Run(params or Params(), sections)
    layers: dict[str, list[Block]] = {}
    for block in blocks:
        layers.setdefault(block.layer, []).append(block)
    ordered = [name for name in LAYER_ORDER if name in layers]
    ordered += [name for name in layers if name not in LAYER_ORDER]
    for name in ordered:
        run.layer(layers[name])
    return Spine(tuple(run.segments), tuple(run.notices))


@dataclass(slots=True)
class _Run:
    params: Params
    sections: Mapping[str, str]
    segments: list[Segment] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)

    def layer(self, blocks: list[Block]) -> None:
        open_: list[Block] = []
        tokens = 0
        p = self.params
        i = 0
        while i < len(blocks):
            block = blocks[i]
            i += 1
            if block.kind == "table":
                self._prose(open_, tokens)
                open_, tokens = [], 0
                cells: list[Block] = []
                while i < len(blocks) and blocks[i].table == block.cite:
                    cells.append(blocks[i])
                    i += 1
                self._table(block, cells)
                continue
            if block.text is None:
                continue
            if open_ and block.sec != open_[0].sec:
                self._prose(open_, tokens)
                open_, tokens = [], 0
            size = count_tokens(block.text)
            if size > p.max_tokens:
                self._prose(open_, tokens)
                open_, tokens = [], 0
                self._prose([block], size)
                self.notices.append(self._too_big(block, size))
                continue
            if open_ and (tokens + size > p.max_tokens or len(open_) + 1 >= p.max_blocks):
                self._prose(open_, tokens)
                open_, tokens = [], 0
            open_.append(block)
            tokens += size
            if tokens >= p.target_tokens:
                self._prose(open_, tokens)
                open_, tokens = [], 0
        self._prose(open_, tokens)

    def _prose(self, members: list[Block], tokens: int) -> None:
        if members:
            self.segments.append(
                Segment(
                    layer=members[0].layer,
                    heading_path=heading_path(members[0].sec, self.sections),
                    blocks=tuple(b.cite for b in members),
                    n_tokens=tokens,
                )
            )

    def _too_big(self, block: Block, size: int) -> Notice:
        return Notice(
            code=_RESOURCE_LIMIT,
            message=(
                f"{block.cite} is {size} tokens, above MAX_SEGMENT_TOKENS = "
                f"{self.params.max_tokens}; it is its own Segment and was not split"
            ),
            cite=block.cite,
            page=block.page,
            detail={"limit": "MAX_SEGMENT_TOKENS", "n_tokens": size},
        )

    def _table(self, table: Block, cells: list[Block]) -> None:
        p = self.params
        header_rows = table.grid.header_rows if table.grid else 0
        rows = _rows([c for c in cells if c.text is not None])
        header = [cell for r, row in rows if r < header_rows for cell in row]
        body = [row for r, row in rows if r >= header_rows]
        if len(cells) > p.table_synopsis_cells:
            self._synopsis(table, cells, header, body)
            return
        total = sum(count_tokens(c.text or "") for c in header) + sum(
            count_tokens(c.text or "") for row in body for c in row
        )
        ceiling = min(p.max_tokens, max(p.table_tokens, -(-total // p.table_max_segments)))
        segments, notices = self._pack(table, header, body, ceiling)
        if len(segments) > p.table_max_segments and ceiling < p.max_tokens:
            segments, notices = self._pack(table, header, body, p.max_tokens)
        if len(segments) > p.table_max_segments:
            notices.append(
                Notice(
                    code=_RESOURCE_LIMIT,
                    message=(
                        f"table {table.cite} needs {len(segments)} Segments even at "
                        f"MAX_SEGMENT_TOKENS, above TABLE_MAX_SEGMENTS = "
                        f"{p.table_max_segments}; every row is kept"
                    ),
                    cite=table.cite,
                    page=table.page,
                    detail={"limit": "TABLE_MAX_SEGMENTS", "segments": len(segments)},
                )
            )
        self.segments.extend(segments)
        self.notices.extend(notices)

    def _pack(
        self, table: Block, header: list[Block], body: list[list[Block]], ceiling: int
    ) -> tuple[list[Segment], list[Notice]]:
        """Whole rows under `ceiling`, the header's tokens charged to every Segment.

        The notices are returned rather than recorded: a packing past `table_max_segments` is
        discarded, and its notices with it.
        """
        p = self.params
        cap = p.max_blocks - 1
        header_tokens = sum(count_tokens(c.text or "") for c in header)
        atoms = [(header[i : i + cap], True) for i in range(0, len(header), cap)]
        notices: list[Notice] = []
        for row in body:
            if len(row) > cap:
                notices.append(self._split_row(row, cap))
            atoms += [(row[i : i + cap], False) for i in range(0, len(row), cap)]
        out: list[Segment] = []
        open_: list[Block] = []
        tokens = 0
        has_row = False
        for atom, is_header in atoms:
            size = sum(count_tokens(c.text or "") for c in atom)
            repeated = header_tokens if out else 0
            over_tokens = repeated + tokens + size > ceiling
            over_blocks = len(open_) + len(atom) > cap
            if open_ and ((has_row and over_tokens) or over_blocks):
                out.append(self._table_segment(table, open_, tokens, repeated, notices))
                open_, tokens, has_row = [], 0, False
            open_ += atom
            tokens += size
            has_row = has_row or not is_header
        if open_:
            repeated = header_tokens if out else 0
            out.append(self._table_segment(table, open_, tokens, repeated, notices))
        return out, notices

    def _table_segment(
        self, table: Block, members: list[Block], tokens: int, repeated: int, notices: list[Notice]
    ) -> Segment:
        if repeated + tokens > self.params.max_tokens:
            notices.append(self._too_big(members[0], repeated + tokens))
        return Segment(
            layer=table.layer,
            heading_path=heading_path(table.sec, self.sections),
            blocks=tuple(c.cite for c in members),
            n_tokens=tokens,
            atom="table",
        )

    def _split_row(self, row: list[Block], cap: int) -> Notice:
        first = row[0]
        return Notice(
            code=_RESOURCE_LIMIT,
            message=(
                f"row {first.r} of {first.table} has {len(row)} cells, more than a Segment "
                f"holds ({cap}); it is split into runs of {cap}"
            ),
            cite=first.cite,
            page=first.page,
            detail={"limit": "MAX_SEGMENT_BLOCKS", "cells": len(row)},
        )

    def _synopsis(
        self,
        table: Block,
        cells: list[Block],
        header: list[Block],
        body: list[list[Block]],
    ) -> None:
        p = self.params
        n = len(body)
        cap = p.max_blocks - 1
        picks = sorted({i * n // SYNOPSIS_SAMPLE_ROWS for i in range(SYNOPSIS_SAMPLE_ROWS)})
        members: list[Block] = []
        tokens = 0
        sampled: list[int] = []
        for is_header, row in [(True, header), *((False, body[i]) for i in picks)]:
            run = row[:cap]
            size = sum(count_tokens(c.text or "") for c in run)
            if members and (len(members) + len(run) > cap or tokens + size > p.max_tokens):
                break
            members += run
            tokens += size
            if not is_header:
                sampled.append(run[0].r)
        if tokens > p.max_tokens:
            self.notices.append(self._too_big(members[0], tokens))
        if members:
            self.segments.append(
                Segment(
                    layer=table.layer,
                    heading_path=heading_path(table.sec, self.sections),
                    blocks=tuple(c.cite for c in members),
                    n_tokens=tokens,
                    atom="table",
                    synopsis_of=table.cite,
                )
            )
        grid = table.grid
        self.notices.append(
            Notice(
                code=_SYNOPSIS_ONLY,
                message=(
                    f"table {table.cite} has {len(cells)} cells > TABLE_SYNOPSIS_CELLS="
                    f"{p.table_synopsis_cells}; one synopsis Segment stands for it"
                ),
                cite=table.cite,
                page=table.page,
                detail={
                    "limit": "TABLE_SYNOPSIS_CELLS",
                    "cells": len(cells),
                    "n_rows": grid.n_rows if grid else len(body),
                    "n_cols": grid.n_cols if grid else 0,
                    "sampled_rows": sampled,
                },
            )
        )


def _rows(cells: list[Block]) -> list[tuple[int, list[Block]]]:
    """Cells grouped by their origin row, rows ascending, cells in the order they arrived."""
    rows: dict[int, list[Block]] = {}
    for cell in cells:
        rows.setdefault(cell.r, []).append(cell)
    return sorted(rows.items())
