"""`Locus`: where on the page a cited Block is, or the stated reason nothing can say (INV-9).

00:45 (L-1) and 06:2088-2111 give the type its fields: `cite`, `doc_ord`, `gen`, `page`, `addr`, a
`TextSpan`, a `quad` that may be `None` **only** with a non-`None` `reason`, the `OriginSpan`, and a
`precision` in `char | line | block | page | none`, so an answer says how tight the box is instead
of implying char precision from a block rectangle. V01-6 asserts the biconditional over every
fixture, and `Locus.__post_init__` is where it holds: a `Locus` that breaks it cannot be built.

**`locate()` here is the Block half.** 06 section 8's `locate()` walks `edge -> edge_evidence ->
mention -> block` and returns one `Locus` per witness. That walk needs the knowledge graph, which is
P8's. Its last hop, *"into L2. THIS is the only hop that touches geometry"* (06:2075), is a Block
and nothing else, and it is this function: 03:1560 and conformance P32 (03:3016) already call it
as `locate(block)`.

**What it computes, and what it does not.**
- `quad` is the Block's own, decoded from the store; nothing is assembled (INV-9, 01:1191).
- `reason` names the driver and its declared `spatial` when there is no quad. 06:2109's own example
  is *"parse.office.anydoc declares spatial=none"*.
- `precision` is `block`: the location is the whole Block. `char` and `line` need the span narrowed
  to a glyph run or to the covering line-child Blocks, which is a query this build does not run, so
  a sub-block `span` does not tighten it (06:2103-2106: sub-block precision is computed by the
  query, never assumed). `page` and `none` describe a location with no Block, which a Block's
  locate never is.

Pure: no store, no clock. `omniweave_core.store.doc.locate_block()` reads the Block and its
document's declared `spatial` and calls it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from omniweave_core.model.spans import OriginSpan, Quad, TextSpan

if TYPE_CHECKING:
    from omniweave_core.model.block import Addr, Block, Cite

__all__ = ["NO_SPATIAL", "Locus", "LocusPrecision", "locate"]

NO_SPATIAL: Final[str] = "none"
"""`Capabilities.spatial`'s value for a driver that supplies no geometry (03:1556-1561)."""


class LocusPrecision(StrEnum):
    """How tight a `Locus` is, tightest first (06:2103-2106). Computed by the query, never stored.

    Not `enum_val`'s `precision` domain, which is claim time precision (`TimePrecision`): two
    vocabularies under one name is the INV-21 defect `enums.TimePrecision`'s docstring records.
    """

    CHAR = "char"
    LINE = "line"
    BLOCK = "block"
    PAGE = "page"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Locus:
    """One resolved location. **`reason` is non-`None` iff `quad is None`** (INV-9, V01-6).

    So "where on the page" is never a blank and never an invented box: a `Locus` with neither a
    quad nor a reason, or with both, raises here and is never returned.
    """

    cite: Cite
    doc_ord: int
    gen: int
    page: int
    addr: Addr
    span: TextSpan
    quad: Quad | None
    precision: LocusPrecision
    origin: OriginSpan
    reason: str | None

    def __post_init__(self) -> None:
        if (self.quad is None) != (self.reason is not None):
            msg = (
                f"Locus.reason must be non-None iff quad is None (INV-9); got quad="
                f"{'None' if self.quad is None else 'set'} and reason={self.reason!r}"
            )
            raise ValueError(msg)
        if self.reason is not None and not self.reason.strip():
            msg = "Locus.reason must name why there is no quad, not be blank (INV-9)"
            raise ValueError(msg)


def locate(block: Block, *, declared_spatial: str, span: TextSpan | None = None) -> Locus:
    """The `Locus` of one Block: its own quad, or a reason naming its driver's declared `spatial`.

    `declared_spatial` is the document's `declared.spatial`, the card's claim (03:1556-1561).
    `span` is a range in `block.text` and defaults to the whole of it; `slice_of` refuses one past
    its end (P8).
    """
    text = block.text or ""
    chosen = TextSpan(0, len(text)) if span is None else span
    chosen.slice_of(text)
    reason = None
    if block.quad is None:
        #  A stored Block always names its driver; a hand-built one may not, and the reason says so.
        driver = block.origin_driver or "an unnamed driver"
        reason = (
            f"{driver} declares spatial={NO_SPATIAL}"
            if declared_spatial == NO_SPATIAL
            else f"{driver} declares spatial={declared_spatial} and stored no quad for this "
            f"{block.kind.value} block"
        )
    return Locus(
        cite=block.cite,
        doc_ord=block.doc_ord,
        gen=block.gen,
        page=block.page,
        addr=block.addr,
        span=chosen,
        quad=block.quad,
        precision=LocusPrecision.BLOCK,
        origin=block.origin,
        reason=reason,
    )
