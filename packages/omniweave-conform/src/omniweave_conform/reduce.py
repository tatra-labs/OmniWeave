"""Reductions: a document's deterministic, line-oriented projections. **D817, D818.**

13-quality.md section 5.1: *"Never snapshot the document."* A committed parse output is 9,000
diff lines nobody reads and a geometry jitter that fails a build, so omniweave commits
**Reductions**: *"deterministic, sorted, LF-normalised, line-oriented projections, in exactly
three kinds"*:

- **`shape`** (D817) is **frozen**: a byte diff fails the build. One file per
  `(corpus, driver, doc)`, never holding text, per-corner geometry or a float not `%.4f`.
- **`pages`** (D818) is **tracked**: a diff merges with a blessed reason. One line per page, no
  text.
- **`outline`** (D818) is **tracked** and suppressed by the byte cap. One line per block, no full
  text and no geometry.

16-roadmap.md W10.2 is the work item.

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
   whose bump section 5.6 says changes every frozen file on this line and no other. `pages` and
   `outline` carry the same header under `owpages/1` and `owoutline/1`.
3. **Fixed counters always print; histograms print their non-zero buckets.**
   - Always: `blocks.total`, `pages.total`, `quad.present_frac`, `grid.tables_with_merges` and
     every `achieved.*` field.
   - When non-zero: `blocks.kind.*`, `blocks.layer.*`, `trust.*`, `quote.*`, `marks.kind.*`,
     `diag.*` and `rel.kind.*`.

   A bucket's name is its enum's value, or for the two `IntEnum`s its member's lower-cased
   name, as the charter's `trust.extracted` and `quote.normalized` are.
4. **Every live block counts, the document root included**, because it is a block row; a
   tombstoned block is an edit, not a parse, and counts nowhere, in any of the three.
5. **Values have one spelling each.** A count is a decimal integer. A fraction is `%.4f`, and a
   fraction over no blocks is `none`, not `0.0000`. An `achieved` value that is a string prints
   bare, and anything else as compact canonical JSON (`true`, `[]`). `pages.total` is the header's
   `page_count`, or `none` when the document has none.
6. **`pages` is one line per page, in numeric page order**, a page being any page a live block or
   a paged diag stands on. The label is `p` and the page zero-padded to four digits, growing past
   9,999 rather than wrapping, so the order is the pages' and never a sort of the labels.
7. **A page line is the charter's fields in its order**:
   `p0014 n=87 kind{..} layer{..} trust{..} quote{..} cdig=.. ldig=.. diag{..}`, one line, each
   histogram's keys sorted.
   - **Bucket names are `shape`'s, in full.** The charter prints `para`, `furn` and numeric trust,
     but the churn classifier compares `pages` with `shape` counter by counter (section 5.4), and
     two vocabularies would need a table to join them.
   - **`cdig` and `ldig` are the first 8 hex of a sha256** over the page's blocks, one
     `addr hex-digest` line each, in the source's order; a block with no layout digest gives an
     empty one.
   - **A diag with no page counts in `shape` and on no page line.**
8. **An `outline` line is `addr kind layer trust quote cdig[:8] ldig[:8] preview`**, single-spaced,
   the preview last because it may hold spaces. The preview is the block's text with every
   whitespace run collapsed to one space, cut at 48 characters; a block with no text has none, and
   one with no layout digest prints `-`. Lines follow the source's order, which `ExportSource`
   fixes as frame order, so a reordering is a real diff.
9. **Above 500 pages, `outline` is suppressed before a line is built.** 13:686 makes the page rule
   a performance guard and *"not a second threshold"*, so the file is the one line
   `owoutline/1 SUPPRESSED reason=pages pages=N blocks=M`.
10. **Above `MAX_REDUCTION_BYTES`, a tracked Reduction is one line**:
    `<format> SUPPRESSED reason=bytes <unit>=N would_be_bytes=M`, never a truncation (13:701,
    *"A truncated reduction is silent loss"*). The cap binds `pages` as it binds `outline`: 13:695
    puts `pages` at ~1,190 pages, and Q-G2 fails a file over 256 KiB whichever kind it is. `shape`
    is fixed-size and uncapped.

Specified in 13-quality.md sections 5.1, 5.2 and 5.6, and 16-roadmap.md W10.2.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave_core.contract import SCHEMA
from omniweave_core.limits import MAX_REDUCTION_BYTES

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from omniweave_core.archive.owdoc import BlockExport, DocHeader, GridRow, RelRow
    from omniweave_core.model import Block

__all__ = [
    "OUTLINE_FORMAT",
    "OUTLINE_MAX_PAGES",
    "PAGES_FORMAT",
    "PREVIEW_CHARS",
    "SHAPE_FORMAT",
    "Reducible",
    "reduce_outline",
    "reduce_pages",
    "reduce_shape",
    "shape_counters",
]

SHAPE_FORMAT: Final = "owshape/1"
PAGES_FORMAT: Final = "owpages/1"
OUTLINE_FORMAT: Final = "owoutline/1"
NONE: Final = "none"
OUTLINE_MAX_PAGES: Final = 500
"""13:686's performance guard, never a second threshold (ruling 9)."""
PREVIEW_CHARS: Final = 48
DIGEST_HEX: Final = 8
"""`cdig[:8]` and `ldig[:8]` (13:640): 32 bits of a digest, a line's identity and not its proof."""
NO_DIGEST: Final = "-"


class Reducible(Protocol):
    """The five reads of `archive.owdoc.ExportSource` a Reduction needs."""

    def header(self) -> DocHeader: ...
    def blocks(self) -> Iterable[BlockExport]: ...
    def rels(self) -> Iterable[RelRow]: ...
    def grids(self) -> Iterable[GridRow]: ...
    def diags(self) -> Iterable[Mapping[str, Any]]: ...


def reduce_shape(source: Reducible, *, corpus: str, driver: str) -> str:
    """The frozen `shape` file for one `(corpus, driver, doc)` (rulings 1 and 2)."""
    head = _header(SHAPE_FORMAT, source.header(), corpus=corpus, driver=driver)
    counters = shape_counters(source)
    return _lines((head, *(f"{key} {counters[key]}" for key in sorted(counters))))


def shape_counters(source: Reducible) -> dict[str, str]:
    """Every `shape` counter, keyed and spelled (rulings 3-5)."""
    header = source.header()
    live = list(_live(source))
    tally: Counter[str] = Counter()
    for block in live:
        tally[f"blocks.kind.{block.kind.value}"] += 1
        tally[f"blocks.layer.{block.layer.value}"] += 1
        tally[f"trust.{_trust(block)}"] += 1
        tally[f"quote.{_quote(block)}"] += 1
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


def reduce_pages(
    source: Reducible, *, corpus: str, driver: str, max_bytes: int = MAX_REDUCTION_BYTES
) -> str:
    """The tracked `pages` file: one line per page, in page order (rulings 6, 7 and 10)."""
    head = _header(PAGES_FORMAT, source.header(), corpus=corpus, driver=driver)
    by_page: dict[int, list[Block]] = defaultdict(list)
    for block in _live(source):
        by_page[block.page].append(block)
    diags: dict[int, Counter[str]] = defaultdict(Counter)
    for diag in source.diags():
        if diag.get("page") is not None:
            diags[int(diag["page"])][str(diag["code"])] += 1
    pages = sorted({*by_page, *diags})
    lines = [_page_line(page, by_page.get(page, []), diags.get(page, Counter())) for page in pages]
    return _capped(PAGES_FORMAT, head, lines, unit="pages", count=len(pages), max_bytes=max_bytes)


def reduce_outline(
    source: Reducible,
    *,
    corpus: str,
    driver: str,
    max_bytes: int = MAX_REDUCTION_BYTES,
    max_pages: int = OUTLINE_MAX_PAGES,
) -> str:
    """The tracked `outline` file: one line per block, in the source's order (rulings 8-10)."""
    header = source.header()
    page_count = header.source.get("page_count")
    if page_count is not None and int(page_count) > max_pages:
        blocks = sum(1 for _ in _live(source))
        return _lines(
            (f"{OUTLINE_FORMAT} SUPPRESSED reason=pages pages={int(page_count)} blocks={blocks}",)
        )
    head = _header(OUTLINE_FORMAT, header, corpus=corpus, driver=driver)
    lines = [_outline_line(block) for block in _live(source)]
    return _capped(
        OUTLINE_FORMAT, head, lines, unit="blocks", count=len(lines), max_bytes=max_bytes
    )


def _live(source: Reducible) -> Iterator[Block]:
    """Ruling 4: every live block, in the source's own order."""
    return (row.block for row in source.blocks() if not row.block.tombstoned)


def _header(fmt: str, header: DocHeader, *, corpus: str, driver: str) -> str:
    """Ruling 2: the charter's header, two-space separated, the same for all three kinds."""
    fields = (fmt, f"corpus={corpus}", f"doc={header.doc_key}", f"driver={driver}")
    return "  ".join((*fields, f"schema_v={SCHEMA}"))


def _page_line(page: int, blocks: list[Block], diags: Counter[str]) -> str:
    """Ruling 7: a page's label, count, four histograms, two digests and its diags."""
    kinds = Counter(block.kind.value for block in blocks)
    layers = Counter(block.layer.value for block in blocks)
    trusts = Counter(_trust(block) for block in blocks)
    quotes = Counter(_quote(block) for block in blocks)
    content = _rollup((block.addr, block.content_digest) for block in blocks)
    layout = _rollup((block.addr, block.layout_digest or b"") for block in blocks)
    return " ".join(
        (
            f"p{page:04d}",
            f"n={len(blocks)}",
            f"kind{_histogram(kinds)}",
            f"layer{_histogram(layers)}",
            f"trust{_histogram(trusts)}",
            f"quote{_histogram(quotes)}",
            f"cdig={content}",
            f"ldig={layout}",
            f"diag{_histogram(diags)}",
        )
    )


def _outline_line(block: Block) -> str:
    """Ruling 8: the address, four columns, two digest prefixes, and the preview last."""
    layout = NO_DIGEST if block.layout_digest is None else block.layout_digest.hex()[:DIGEST_HEX]
    fields = (
        str(block.addr),
        block.kind.value,
        block.layer.value,
        _trust(block),
        _quote(block),
        block.content_digest.hex()[:DIGEST_HEX],
        layout,
    )
    preview = " ".join((block.text or "").split())[:PREVIEW_CHARS]
    return " ".join((*fields, preview)) if preview else " ".join(fields)


def _capped(fmt: str, head: str, lines: list[str], *, unit: str, count: int, max_bytes: int) -> str:
    """Ruling 10: the whole file, or one line saying why it is not here."""
    text = _lines((head, *lines))
    size = len(text.encode("utf-8"))
    if size <= max_bytes:
        return text
    return _lines((f"{fmt} SUPPRESSED reason=bytes {unit}={count} would_be_bytes={size}",))


def _rollup(rows: Iterable[tuple[str, bytes]]) -> str:
    """A page's digest over its blocks' `addr` and hex digest, one LF line each, in order."""
    hasher = hashlib.sha256()
    for addr, digest in rows:
        hasher.update(f"{addr} {digest.hex()}\n".encode())
    return hasher.hexdigest()[:DIGEST_HEX]


def _histogram(tally: Counter[str]) -> str:
    """`{a:1,b:2}`, keys sorted, nothing for an empty tally but the braces."""
    return "{" + ",".join(f"{key}:{tally[key]}" for key in sorted(tally)) + "}"


def _trust(block: Block) -> str:
    return block.trust.name.lower()


def _quote(block: Block) -> str:
    return block.quote.name.lower()


def _lines(lines: Iterable[str]) -> str:
    """Ruling 1: LF after every line, the last included."""
    return "".join(f"{line}\n" for line in lines)


def _spelled(value: object) -> str:
    """Ruling 5: a string bare, anything else as compact canonical JSON."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
