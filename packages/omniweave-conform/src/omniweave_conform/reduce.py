"""Reductions: a document's deterministic, line-oriented projections. `shape` first. **D817.**

13-quality.md section 5.1: *"Never snapshot the document."* A committed parse output is 9,000
diff lines nobody reads and a geometry jitter that fails a build, so omniweave commits
**Reductions**: *"deterministic, sorted, LF-normalised, line-oriented projections, in exactly
three kinds"*. `shape` is the frozen one, a byte diff of which fails the build, and it holds
per-document counters only:

> block totals by kind and layer, page count, mark counts, `achieved` capability values, `diag`
> code counts, trust and quote histograms, `quad.present_frac` -- never text, per-corner geometry,
> any float that is not `%.4f`.

`pages` and `outline`, the two tracked kinds, are the next cell's. 16-roadmap.md W10.2 is the
work item.

## The input is the export's read, not a store

`archive.owdoc.ExportSource` is the read a stored document already answers -- the header with its
page count and `achieved`, the blocks, relations, grids and diags -- and its docstring says the
`Doc` handle satisfies it structurally the day `Doc` gains a store reader. `Reducible` is the five
of its nine methods a Reduction reads, so a reduction runs over a stored document, an archive or a
hand-written source alike.

## Rulings

1. **One counter per line, `key value`, sorted by key, LF, ending in a newline.** The charter
   prints `shape`'s body in two columns, which is a page layout: 13:632 requires a line-oriented
   projection, and a one-counter change is one changed line only when a line holds one counter.
   No padding either, because a new longer key would re-pad every line.
2. **The header is the charter's**, with its two-space separators:
   `owshape/1  corpus=<c>  doc=<doc_key>  driver=<id@version>  schema_v=<n>`. `doc` is the whole
   key, since a truncated one is not an identity. `schema_v` is `contract.SCHEMA`, the owdoc major
   whose bump section 5.6 says changes every frozen file on this line and no other.
3. **Fixed counters always print; histograms print their non-zero buckets.**
   - Always: `blocks.total`, `pages.total`, `quad.present_frac`, `grid.tables_with_merges` and
     every `achieved.*` field.
   - When non-zero: `blocks.kind.*`, `blocks.layer.*`, `trust.*`, `quote.*`, `marks.kind.*`,
     `diag.*` and `rel.kind.*`.

   A bucket's name is its enum's value, or for the two `IntEnum`s its member's lower-cased
   name, as the charter's `trust.extracted` and `quote.normalized` are.
4. **Every live block counts, the document root included**, because it is a block row; a
   tombstoned block is an edit, not a parse, and counts nowhere.
5. **Values have one spelling each.** A count is a decimal integer. A fraction is `%.4f`, and a
   fraction over no blocks is `none`, not `0.0000`. An `achieved` value that is a string prints
   bare, and anything else as compact canonical JSON (`true`, `[]`). `pages.total` is the header's
   `page_count`, or `none` when the document has none.

Specified in 13-quality.md sections 5.1 and 5.6, and 16-roadmap.md W10.2.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave_core.contract import SCHEMA

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_core.archive.owdoc import BlockExport, DocHeader, GridRow, RelRow

__all__ = ["SHAPE_FORMAT", "Reducible", "reduce_shape", "shape_counters"]

SHAPE_FORMAT: Final = "owshape/1"
NONE: Final = "none"


class Reducible(Protocol):
    """The five reads of `archive.owdoc.ExportSource` a Reduction needs."""

    def header(self) -> DocHeader: ...
    def blocks(self) -> Iterable[BlockExport]: ...
    def rels(self) -> Iterable[RelRow]: ...
    def grids(self) -> Iterable[GridRow]: ...
    def diags(self) -> Iterable[Mapping[str, Any]]: ...


def reduce_shape(source: Reducible, *, corpus: str, driver: str) -> str:
    """The frozen `shape` file for one `(corpus, driver, doc)` (rulings 1 and 2)."""
    header = source.header()
    head = "  ".join(
        (
            SHAPE_FORMAT,
            f"corpus={corpus}",
            f"doc={header.doc_key}",
            f"driver={driver}",
            f"schema_v={SCHEMA}",
        )
    )
    counters = shape_counters(source)
    return "".join(
        f"{line}\n" for line in (head, *(f"{k} {counters[k]}" for k in sorted(counters)))
    )


def shape_counters(source: Reducible) -> dict[str, str]:
    """Every `shape` counter, keyed and spelled (rulings 3-5)."""
    header = source.header()
    live = [row.block for row in source.blocks() if not row.block.tombstoned]
    tally: Counter[str] = Counter()
    for block in live:
        tally[f"blocks.kind.{block.kind.value}"] += 1
        tally[f"blocks.layer.{block.layer.value}"] += 1
        tally[f"trust.{block.trust.name.lower()}"] += 1
        tally[f"quote.{block.quote.name.lower()}"] += 1
        for mark in block.marks:
            tally[f"marks.kind.{mark.kind}"] += 1
    for rel in source.rels():
        tally[f"rel.kind.{rel.kind.value}"] += 1
    for diag in source.diags():
        tally[f"diag.{diag['code']}"] += 1
    out = {key: str(value) for key, value in tally.items()}
    with_quad = sum(1 for block in live if block.quad is not None)
    out["blocks.total"] = str(len(live))
    out["quad.present_frac"] = f"{with_quad / len(live):.4f}" if live else NONE
    out["grid.tables_with_merges"] = str(sum(1 for grid in source.grids() if grid.has_merges))
    page_count = header.source.get("page_count")
    out["pages.total"] = NONE if page_count is None else str(int(page_count))
    for name, value in header.achieved.items():
        out[f"achieved.{name}"] = _spelled(value)
    return out


def _spelled(value: object) -> str:
    """Ruling 5: a string bare, anything else as compact canonical JSON."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
