"""`worth()` -- the SECOND penalty, the one that is applied to bytes and not to rank.

charter.md:6666 is the sentence the whole module exists to keep true: *"RELEVANCE and WORTH are two
scores. Worth applies a SECOND penalty to BYTE SHARE."* Relevance is `FusedHit.score`, which W6.3
computed from ranks and nothing else; worth is a property of the block -- what layer it sits in,
what kind of thing it is, how the text was obtained and whether it can be quoted. A page footer that
lexically matches the query is as relevant as a body paragraph that matches identically and is worth
0.15 of it, and that difference is spent in characters rather than in position.

Keeping the two separate is what lets the Answer stay ordered by relevance while being SIZED by
worth. Folding worth into the fused score would reorder the evidence, and the `ow:provenance` table
prints the score a caller can reproduce from `channel_contributions`; a score with a silent worth
factor in it is not reproducible from the numbers the same Answer prints.

## Four tables, four questions

charter.md:6667-6673 is the whole vocabulary, transcribed here and nowhere else:

* `WORTH_LAYER` -- *where in the reading order*. `HIDDEN` is `0.0`, and 10:472 states the
  consequence rather than leaving it to arithmetic: `layers=` on `ow_open` is *"the **only** path to
  `Layer.HIDDEN`, whose `WORTH_LAYER` weight is `0.0` and which therefore never packs into an Answer
  through any other route."* A zero here is not a small number, it is an exclusion with a stated
  escape hatch.
* `WORTH_KIND` -- *what kind of thing*. FIVE members of a thirty-five-member enum, and every other
  kind is `1.00`. It is a penalty list, not a table: a `PARAGRAPH` and a `TABLE_CELL` and a
  `FORMULA` are all worth what they weigh, and the five listed are the ones a retrieval hit is
  routinely WRONG about -- a TOC entry matches every query about its own heading, and a running
  header matches on every page of the document.
* `WORTH_TRUST` -- *how it was obtained*, `EXTRACTED` 1.00 / `INFERRED` 0.80 / `AMBIGUOUS` 0.50.
* `WORTH_QUOTE` -- *whether it can be quoted*, and it is the only one of the four whose top rung is
  ABOVE 1.

## `VERBATIM` is 1.15, which is a boost and not a weight, and D270 is what that costs

charter.md:6672 scores `Quote.VERBATIM` at **1.15**. The other three tables top out at 1.00, so the
product's range is `[0.0, 1.15]` and `worth()` is not a multiplier into the unit interval. That is
deliberate -- a byte-exact block is worth MORE room than a merely normalised one, not merely
not-less -- and it makes one sentence in the plan read wrong.

07:1620 prices the alternative to `Filters.deny_methods` as *"a re-imported artefact still competes
at ... of a source Block's byte share for the same relevance"* on the arithmetic 07:1619 gives --
`RECONSTRUCTED` at 0.85 times `INFERRED` at 0.80 -- and 00:671 says the same.

`0.68` is the PRODUCT, not the RATIO: a source Block is `VERBATIM` x `EXTRACTED` = 1.15, so the
re-imported artefact competes at `0.68 / 1.15 = 0.591` of it. The down-weight is 41% and not
32%, which strengthens the argument those two passages are making and weakens nothing. D270
records it, because a document that prices a decision with a number should price it with its
own number.

## The product, and why an unlisted kind is 1.00 rather than a `KeyError`

`Kind` is closed and thirty-five members wide, and `WORTH_KIND` names five. A missing key is
therefore NOT a bug here -- which is the opposite of `Verdict.scanned`'s closed key set (07:2068) --
because the table is a list of penalties and the absence of a penalty is a real, intended value. The
default is written at the one call site rather than by filling the other thirty kinds in with
`1.00`, so a reader can see which five the charter chose.

`Layer`, `Trust` and `Quote` are total and their tables are total, and a missing key in any of the
three IS a bug: a new `Layer` member would be a `model_version` MINOR (03 section 4.2) and the
packer would have to be told what it is worth. Those three subscript directly and raise `KeyError`
if the enums ever move.

Specified in charter.md:6666-6673, 07-store-and-retrieval.md:1618, 00-vision.md:669 and
10-interfaces.md:472; scheduled by 16-roadmap.md:662.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.model.enums import Kind, Layer, Quote, Trust

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MAX_WORTH",
    "WORTH_KIND",
    "WORTH_KIND_DEFAULT",
    "WORTH_LAYER",
    "WORTH_QUOTE",
    "WORTH_TRUST",
    "worth",
]

WORTH_LAYER: Final[Mapping[Layer, float]] = MappingProxyType(
    {
        Layer.BODY: 1.00,
        Layer.NOTE: 0.90,
        Layer.ANNOTATION: 0.80,
        Layer.FURNITURE: 0.20,
        Layer.HIDDEN: 0.0,
    }
)
"""charter.md:6667. Total over `Layer`'s five members.

The order is not the enum's: the charter lists `BODY, NOTE, ANNOTATION, FURNITURE, HIDDEN` and
`Layer` declares `BODY, FURNITURE, NOTE, ANNOTATION, HIDDEN`. The charter's is the WORTH order and
the enum's is 03 section 5's role order; this table follows the charter's so the descent reads,
and a test asserts both spellings cover the same five members."""

WORTH_KIND: Final[Mapping[Kind, float]] = MappingProxyType(
    {
        Kind.TOC_ENTRY: 0.20,
        Kind.PAGE_HEADER: 0.15,
        Kind.PAGE_FOOTER: 0.15,
        Kind.BIBLIOGRAPHY: 0.40,
        Kind.REFERENCE: 0.40,
    }
)
"""charter.md:6669. FIVE of `Kind`'s thirty-five, and a penalty list rather than a table.

Every kind not named here is `WORTH_KIND_DEFAULT`. The five are the ones that match a query about
the thing they point at rather than the thing itself: a `TOC_ENTRY` carries the exact words of the
heading it indexes, and a `PAGE_HEADER` carries the document's title on every page of it, so both
rank against a title query as strongly as the section that answers it."""

WORTH_KIND_DEFAULT: Final[float] = 1.00
"""The worth of a kind `WORTH_KIND` does not name. Not a fallback -- the intended value."""

WORTH_TRUST: Final[Mapping[Trust, float]] = MappingProxyType(
    {
        Trust.EXTRACTED: 1.00,
        Trust.INFERRED: 0.80,
        Trust.AMBIGUOUS: 0.50,
    }
)
"""charter.md:6671. Total over `Trust`'s three members, monotone in the enum's own ordering.

`Trust` is an ordered `IntEnum` with the weakest lowest (03 section 8.2), and this table is
monotone in it, so `worth` never rewards a weaker provenance. A test asserts that rather than
trusting the transcription."""

WORTH_QUOTE: Final[Mapping[Quote, float]] = MappingProxyType(
    {
        Quote.VERBATIM: 1.15,
        Quote.NORMALIZED: 1.00,
        Quote.REFLOWED: 0.95,
        Quote.RECONSTRUCTED: 0.85,
        Quote.SYNTHETIC: 0.70,
    }
)
"""charter.md:6672. Total over `Quote`'s five rungs, and the one table whose top is above 1.

Monotone in `Quote`'s `IntEnum` ordering, which is what makes `min(quote)` over a rendered set the
weakest rung (03 section 8.3) *and* the cheapest. See the module docstring for D270, which is that
07:1620 reads the 0.85 x 0.80 product as a ratio against a source Block and a source Block is
1.15."""

MAX_WORTH: Final[float] = 1.15
"""The product's supremum: `BODY` x an unlisted kind x `EXTRACTED` x `VERBATIM`.

Named because the allocator's shares are relative and a reader checking them needs to know the
scale is not `[0, 1]`. A test derives it from the four tables rather than trusting this line."""


def worth(*, layer: Layer, kind: Kind, trust: Trust, quote: Quote) -> float:
    """The four tables multiplied. charter.md:6666-6673.

    Keyword-only on purpose: four arguments of four different enum types, and a positional call
    that transposed `trust` and `quote` would be caught by pyright but not by a reader. The names
    are the four columns `ow:provenance` prints for the same block, so a reviewer can read the
    provenance row and recompute the number.

    Returns `0.0` for `Layer.HIDDEN` whatever the other three say, which is 10:472's rule arriving
    as arithmetic rather than as a branch.

    Raises `KeyError` on an unknown `Layer`, `Trust` or `Quote` -- those three tables are total and
    a new enum member must be priced before it can pack. An unknown `Kind` returns
    `WORTH_KIND_DEFAULT`, because that table is a penalty list.
    """
    return (
        WORTH_LAYER[layer]
        * WORTH_KIND.get(kind, WORTH_KIND_DEFAULT)
        * WORTH_TRUST[trust]
        * WORTH_QUOTE[quote]
    )
