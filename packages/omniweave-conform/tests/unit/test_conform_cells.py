"""`omniweave_conform.cells`: `cell_rel` over a document's own Grid. D877.

The document is a hand-written `TableSource` over real `Block`s and a real `Grid` from
`build_grid()`, the sole constructor, so every neighbour and header chain is the model's own.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from omniweave_conform.cells import TableSource, evaluate_cell_rel
from omniweave_conform.judge import judge
from omniweave_core.errors import QualityError
from omniweave_core.model.block import Addr, Block, BlockId, CellPos, Cite
from omniweave_core.model.doc import Doc
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.model.grid import Grid, build_grid
from omniweave_core.model.spans import OriginNone
from omniweave_core.store.oweval import Assertion

DOC_ORD, GEN = 7, 1


def _block(block: int, page: int, text: str, kind: Kind = Kind.TABLE_CELL) -> Block:
    return Block(
        id=BlockId(block),
        addr=Addr(f"p{page}/b{block}"),
        cite=Cite(f"d{DOC_ORD}#{block}"),
        doc_ord=DOC_ORD,
        gen=GEN,
        page=page,
        parent=None,
        ord=block,
        kind=kind,
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
        method=Method.TEXT_LAYER,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
    )


@dataclass(frozen=True, slots=True)
class _Draft:
    id: BlockId
    pos: CellPos


@dataclass
class _Doc:
    """A `TableSource`: TABLE Blocks, their Grids and every cell's Block."""

    tables: list[Block] = field(default_factory=list)
    grids: dict[int, Grid] = field(default_factory=dict)
    cells: dict[int, Block] = field(default_factory=dict)

    def add(
        self,
        rows: list[list[str]],
        *,
        page: int = 1,
        header_rows: int = 1,
        header_cols: int = 1,
        spans: dict[tuple[int, int], tuple[int, int]] | None = None,
    ) -> int:
        """A table of `rows`; a `None`-free slot is an origin unless a span covers it."""
        table = 1000 * (len(self.tables) + 1)
        covered: set[tuple[int, int]] = set()
        drafts = []
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if (r, c) in covered:
                    continue
                rs, cs = (spans or {}).get((r, c), (1, 1))
                covered |= {(r + i, c + j) for i in range(rs) for j in range(cs)}
                block = table + 10 * r + c + 1
                self.cells[block] = _block(block, page - 1, value)
                drafts.append(_Draft(BlockId(block), CellPos(r, c, rs, cs)))
        #  D932: `page` is a label's, 1-based; a Doc numbers its pages from 0, as this does.
        self.tables.append(_block(table, page - 1, "", Kind.TABLE))
        self.grids[table] = build_grid(
            drafts, header_rows=header_rows, header_cols=header_cols, diag=lambda _d: None
        )
        return table

    def blocks(
        self,
        *,
        pages: range | None = None,
        kinds: Iterable[Kind] | None = None,
        under: BlockId | None = None,
    ) -> Iterator[Block]:
        del under  # a hand-built cell carries its own text, so nothing reads under it
        wanted = set(kinds) if kinds is not None else None
        for block in self.tables:
            if pages is not None and block.page not in pages:
                continue
            if wanted is None or block.kind in wanted:
                yield block

    def block(self, id: BlockId) -> Block:  # noqa: A002 -- Doc.block's own name.
        return self.cells[id]

    def grid(self, id: BlockId) -> Grid:  # noqa: A002 -- Doc.grid's own name.
        return self.grids[id]


def _assertion(spec: dict[str, Any], *, aid: str = "c", page: int | None = 1) -> Assertion:
    return Assertion(
        assertion_id=aid,
        corpus_id="golden",
        corpus_version="2026.09",
        doc="xlsx-merged-4m-cells",
        page=page,
        type="cell_rel",
        spec=spec,
        addr=None,
        evaluable_in="owdoc",
        checked="verified",
        derived_from_sha256="sha256:" + "cd" * 32,
        max_diffs=0,
        slices=("xlsx",),
    )


QUARTERS = [["Item", "Q1", "Q2"], ["Cloud", "1.1", "1.2"], ["Edge", "2.1", "2.2"]]


def test_a_cell_with_its_four_neighbours_and_both_headings_passes() -> None:
    doc = _Doc()
    doc.add(QUARTERS)
    spec = {
        "cell": "1.2",
        "up": "Q2",
        "down": "2.2",
        "left": "1.1",
        "top_heading": "Q2",
        "left_heading": "Cloud",
    }
    assert evaluate_cell_rel(_assertion(spec), doc).passed


def test_a_miss_names_the_table_the_cell_and_both_strings() -> None:
    doc = _Doc()
    table = doc.add(QUARTERS)
    got = evaluate_cell_rel(_assertion({"cell": "1.2", "left_heading": "Edge"}), doc)
    assert not got.passed
    assert got.explanation == (
        f"cell_rel: cell '1.2' found, relations missed at table {table} r1c2: "
        "left_heading 'Edge' but 'Cloud'"
    )
    lost = evaluate_cell_rel(_assertion({"cell": "9.9"}), doc)
    assert lost.explanation == "cell_rel: cell '9.9' not found in 1 table(s)"


def _transposed(rows: list[list[str]]) -> list[list[str]]:
    return [list(col) for col in zip(*rows, strict=True)]


def test_a_transposed_table_fails_every_cell_rel_on_the_owdoc_evaluator() -> None:
    """13:1261, *"every `table` and `cell_rel` assertion fails (`0/18`) while every `present`
    assertion still passes"*: the `cell_rel` half, through `judge()` with the document given."""
    header = ["Item", *[f"Q{q}" for q in range(1, 4)]]
    rows = [header, *[[f"r{r}", *[f"{r}.{q}" for q in range(1, 4)]] for r in range(1, 7)]]
    cells = [
        _assertion(
            {"cell": f"{r}.{q}", "left_heading": f"r{r}", "top_heading": f"Q{q}"}, aid=f"c{r}{q}"
        )
        for r in range(1, 7)
        for q in range(1, 4)
    ]
    original, swapped = _Doc(), _Doc()
    original.add(rows)
    swapped.add(_transposed(rows))
    before = judge(cells, {}, run_id="r", docs={"xlsx-merged-4m-cells": original})
    after = judge(cells, {}, run_id="r", docs={"xlsx-merged-4m-cells": swapped})
    assert len(cells) == 18
    assert (before.passed, after.passed, len(after.verdicts)) == (18, 0, 18)
    assert {v.evaluator for v in after.verdicts} == {"owdoc"}
    assert after.not_run == ()


def test_without_its_document_a_cell_rel_is_still_not_run() -> None:
    got = judge([_assertion({"cell": "1.1"})], {("xlsx-merged-4m-cells", 1): "1.1"}, run_id="r")
    assert (got.verdicts, [aid for aid, _ in got.not_run]) == ((), ["c"])


def test_a_spanned_cells_down_is_past_its_span_and_a_covered_slot_is_its_origin() -> None:
    """Ruling 2: `down` from the last row of a `row_span = 2` cell; `left` of a covered slot."""
    doc = _Doc()
    rows = [["Item", "Q1"], ["Cloud", "1.1"], ["Cloud", "2.1"], ["Total", "3.1"]]
    doc.add(rows, spans={(1, 0): (2, 1)})
    assert evaluate_cell_rel(
        _assertion({"cell": "Cloud", "down": "Total", "up": "Item"}), doc
    ).passed
    assert evaluate_cell_rel(_assertion({"cell": "2.1", "left": "Cloud"}), doc).passed


def test_a_heading_is_the_header_chain_and_a_table_with_none_has_none() -> None:
    """Ruling 3: two header rows give two headings; zero header rows give no `top_heading`."""
    doc = _Doc()
    rows = [["", "FY2024", "FY2024"], ["", "Q1", "Q2"], ["Cloud", "1.1", "1.2"]]
    doc.add(rows, header_rows=2, spans={(0, 1): (1, 2)})
    for heading in ("FY2024", "Q2"):
        assert evaluate_cell_rel(_assertion({"cell": "1.2", "top_heading": heading}), doc).passed
    flat = _Doc()
    flat.add(QUARTERS, header_rows=0)
    got = evaluate_cell_rel(_assertion({"cell": "1.2", "top_heading": "Q2"}), flat)
    assert not got.passed
    assert got.explanation.endswith("top_heading 'Q2' but []")


def test_a_column_spans_right_is_past_it_and_a_header_is_never_its_own_heading() -> None:
    """Rulings 2 and 3: `right` from a `col_span = 2` cell's last column, and the cell is
    dropped from its own header chain, as `table` has no heading for a cell already there."""
    doc = _Doc()
    rows = [["", "FY2024", "FY2024", "FY2025"], ["", "Q1", "Q2", "Q1"], ["Cloud", "1", "2", "3"]]
    doc.add(rows, header_rows=2, spans={(0, 1): (1, 2)})
    assert evaluate_cell_rel(_assertion({"cell": "FY2024", "right": "FY2025"}), doc).passed
    assert evaluate_cell_rel(_assertion({"cell": "Q2", "top_heading": "FY2024"}), doc).passed
    itself = evaluate_cell_rel(_assertion({"cell": "Q2", "top_heading": "Q2"}), doc)
    assert not itself.passed


def test_only_the_assertions_page_is_read() -> None:
    doc = _Doc()
    doc.add(QUARTERS, page=2)
    got = evaluate_cell_rel(_assertion({"cell": "1.2"}, page=1), doc)
    assert got.explanation == "cell_rel: page 1 has no table for cell '1.2'"
    assert evaluate_cell_rel(_assertion({"cell": "1.2"}, page=None), doc).passed


@pytest.mark.parametrize(
    ("spec", "kind", "said"),
    [({"cell": "  "}, "cell_rel", "empty"), ({"cell": "1.1"}, "table", "not cell_rel")],
)
def test_an_empty_cell_or_another_type_is_refused(
    spec: dict[str, Any], kind: str, said: str
) -> None:
    wrong = replace(_assertion(spec), type=kind)
    with pytest.raises(QualityError, match=said):
        evaluate_cell_rel(wrong, _Doc())


def _a_doc_is_a_table_source(doc: Doc) -> TableSource:
    """Checked by pyright, never run: `omniweave_core.model.doc.Doc` satisfies the Protocol."""
    return doc
