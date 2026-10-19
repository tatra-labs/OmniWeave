"""`cell_rel`: the `table` relation, asserted against a document's own `Grid`. **D877.**

13-quality.md:1007: *"the same relation as `table`, but asserted against
`Grid.up/down/left_heading` in O(1) rather than by re-parsing a markdown table"*, and `owdoc`-only.
`assertions.py` judges `table` over a candidate's text and names `cell_rel` as not its to judge
(its ruling 4). This module is the owdoc half: it reads the document's TABLE Blocks, each one's
`Grid` and each cell's Block, and nothing rendered.

Section 8.5's transposed table is the case it exists for: *"every `table` and `cell_rel`
assertion fails while every `present` assertion still passes, because the strings are all
there"*.

## Rulings

1. **The spec is `table`'s**: `cell` and any of `up`, `down`, `left`, `right`, `top_heading`,
   `left_heading`, under `normalize_eval` and `assertions.py`'s threshold,
   `max(0.5, 1 - max_diffs / len(cell))` over a Levenshtein similarity. One relation, two
   readers: a `cell_rel` that agreed with `table` on a text table and differed on a grid would be
   measuring the reader, not the parser.
2. **The four neighbours are the Grid's own** (`Grid.up(r, c)` and its siblings), asked from the
   edge of the cell the relation faces: `up` and `left` from its origin, `down` from its last row
   and `right` from its last column. `Grid.down` steps literally one row, so from a `row_span = 2`
   origin it answers that same cell (its own docstring), and the cell below the span is one step
   past the span. A covered slot is the origin that covers it (03 section 10).
3. **A heading is the Grid's header chain, not row 0.** `top_heading` is `Grid.top_heading(c)`
   and `left_heading` is `Grid.left_heading(r)`, each without the cell itself, and the relation
   holds when any origin in the chain matches: a `header_rows = 2` table has two headings above a
   cell, and an assertion names one. A table that declares no header rows has no `top_heading`,
   which is where `cell_rel` and `table` part: the text evaluator reads row 0 as a heading
   because a markdown table always has one.
4. **The page is the assertion's**, compared with `Block.page` as the same integer. An assertion
   with no page reads every TABLE Block in the document.
5. **A failure names the table by its Block id and the cell by `r<r>c<c>`**, with the relations
   it missed, both strings quoted, or says no cell matched, or that the page has no table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.errors import QualityError
from omniweave_core.model.enums import Kind

from omniweave_conform.assertions import RELATIONS, TextVerdict, distance
from omniweave_conform.normalize import normalize_eval

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from omniweave_core.model.block import Block, BlockId
    from omniweave_core.model.grid import Grid, Origin
    from omniweave_core.store.oweval import Assertion

__all__ = ["TYPE", "TableSource", "evaluate_cell_rel"]

TYPE: Final = "cell_rel"
_FIX: Final = "give cell_rel a non-empty `cell`, as `table` takes"


class TableSource(Protocol):
    """What `cell_rel` reads of a document: `omniweave_core.model.doc.Doc` is one."""

    def blocks(
        self, *, pages: range | None = None, kinds: Iterable[Kind] | None = None
    ) -> Iterator[Block]: ...

    def block(self, id: BlockId) -> Block: ...  # noqa: A002 -- Doc.block's own parameter name.

    def grid(self, id: BlockId) -> Grid: ...  # noqa: A002 -- Doc.grid's own parameter name.


def evaluate_cell_rel(assertion: Assertion, doc: TableSource) -> TextVerdict:
    """One `cell_rel` verdict over `doc`'s tables (rulings 1-5)."""
    if assertion.type != TYPE:
        raise QualityError(
            f"assertion {assertion.assertion_id} is {assertion.type!r}, not {TYPE}", fix=_FIX
        )
    spec = assertion.spec
    cell = normalize_eval(str(spec.get("cell", "")))
    if not cell:
        raise QualityError(f"assertion {assertion.assertion_id}: an empty `cell`", fix=_FIX)
    threshold = max(0.5, 1.0 - assertion.max_diffs / len(cell))
    wanted = {rel: normalize_eval(str(spec[rel])) for rel in RELATIONS if spec.get(rel)}
    page = assertion.page
    pages = range(page, page + 1) if page is not None else None
    tables = list(doc.blocks(pages=pages, kinds=(Kind.TABLE,)))
    if not tables:
        where = f"page {page}" if page is not None else "the document"
        return TextVerdict(False, f"cell_rel: {where} has no table for cell {cell!r}")
    texts: dict[int, str] = {}

    def text(origin: Origin) -> str:
        if origin.block not in texts:
            texts[origin.block] = normalize_eval(doc.block(origin.block).text or "")
        return texts[origin.block]

    best: tuple[int, str] | None = None
    for table in tables:
        grid = doc.grid(table.id)
        for origin in sorted(grid.origins.values(), key=lambda o: (o.r, o.c)):
            if not _similar(text(origin), cell, threshold):
                continue
            misses = []
            for rel, want in wanted.items():
                found = _neighbours(grid, origin, rel)
                if not any(_similar(text(o), want, threshold) for o in found):
                    got = [text(o) for o in found]
                    misses.append(f"{rel} {want!r} but {got[0] if len(got) == 1 else got!r}")
            if not misses:
                return TextVerdict(True, "")
            if best is None or len(misses) < best[0]:
                at = f"table {table.id} r{origin.r}c{origin.c}"
                best = (len(misses), f"{at}: " + "; ".join(misses))
    if best is None:
        return TextVerdict(False, f"cell_rel: cell {cell!r} not found in {len(tables)} table(s)")
    return TextVerdict(False, f"cell_rel: cell {cell!r} found, relations missed at {best[1]}")


def _neighbours(grid: Grid, origin: Origin, relation: str) -> tuple[Origin, ...]:
    """Rulings 2 and 3: the origins a relation names, the cell itself never among them."""
    r, c = origin.r, origin.c
    last_r, last_c = r + origin.row_span - 1, c + origin.col_span - 1
    if relation == "top_heading":
        chain = grid.top_heading(c)
    elif relation == "left_heading":
        chain = grid.left_heading(r)
    else:
        one = {
            "up": lambda: grid.up(r, c),
            "down": lambda: grid.down(last_r, c),
            "left": lambda: grid.left(r, c),
            "right": lambda: grid.right(r, last_c),
        }[relation]()
        chain = () if one is None else (one,)
    return tuple(o for o in chain if (o.r, o.c) != (r, c))


def _similar(got: str, want: str, threshold: float) -> bool:
    """Ruling 1: `assertions.py`'s similarity, `1 - distance / len(want)`."""
    return 1.0 - distance(got, want) / max(len(want), 1) >= threshold
