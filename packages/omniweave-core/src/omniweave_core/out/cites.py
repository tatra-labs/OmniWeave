"""`CiteResolver`, the block a cite names, and the verbatim predicate. **D754.**

09-generation.md section 4.4 gives `RuleCtx.cites: CiteResolver`, and section 10 says what it may
do: "`by_cites(tuple[Cite, ...]) -> Mapping[Cite, Block | None]` as well as `by_cite`, and the
`order = 80` cross-reference rule calls the batch form once per unit. The resolver holds no store
handle beyond the read: no writes, no retrieval, no `Filters`." The API sketch's reference target
writes that rule (`owtext.attr.ow-cite@1`) against `ctx.cites.by_cite()`. So the rule is the
target's, and this module is the framework's half: the interface, the value a resolver returns,
and the predicate 09 section 10 states once for both the rule and the seal.
`omniweave_core.store.cites.SqliteCiteResolver` is the store-backed resolver.

## Rulings

1. **A resolver returns a `CitedBlock`, not a `Block`.** A rule needs five facts to judge a cite:
   the block's id, its document and that document's head generation (the `doc_gen` the artefact
   pins), its text and its quote tier. It also needs the block's `restriction_bits` for the
   aggregate. A hydrated `Block` would hand a rule the store's whole row model and an `Answer`'s
   provenance, which section 10 forbids ("no store handle beyond the read").
2. **An unmet `cites` need is a resolver that refuses.** `RuleCtx.cites` is never `None`. Without a
   resolver it is `NO_CITES`, whose methods raise. A rule that reads cites without declaring
   `needs={"cites"}` therefore fails loudly as `OW_TARGET_RULE_RAISED`, instead of passing on an
   empty answer. A rule that declares the need is a recorded skip, and never runs against
   `NO_CITES`.
3. **`verbatim()` is section 10's predicate, whole.** It requires
   `block.quote == Quote.VERBATIM` and `nfc(visible) == nfc(block.text[a:b])` over a span that lies
   inside the block's text. `nfc` is `omniweave_core.ident.nfc`, the proof normaliser, which folds
   nothing but canonical composition. A rule proves verbatimness with it, and the seal sets
   `artifact_cite.verbatim` only where it holds, so "proved, never claimed" has one definition.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from omniweave_core.errors import TargetError
from omniweave_core.ident import nfc
from omniweave_core.model.enums import Quote

__all__ = ["NO_CITES", "CiteResolver", "CitedBlock", "verbatim"]


@dataclass(frozen=True, slots=True)
class CitedBlock:
    """Ruling 1: what a cite names, as a rule and the seal read it."""

    cite: str
    """The canonical, unqualified cite: `d7#412`."""
    block_id: int
    doc_ord: int
    doc_gen: int
    """The document's head generation: the `doc_gen` an `artifact_cite` row pins."""
    text: str | None
    quote: Quote
    restriction_bits: int


class CiteResolver(Protocol):
    """09 section 10: two reads, and nothing else."""

    def by_cite(self, cite: str) -> CitedBlock | None: ...

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]: ...


class _NoCites:
    """Ruling 2: the resolver of a check that was handed none."""

    __slots__ = ()

    def by_cite(self, cite: str) -> CitedBlock | None:
        raise _undeclared(cite)

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]:
        raise _undeclared(", ".join(cites[:3]))


def _undeclared(what: str) -> TargetError:
    return TargetError(
        f"a rule read cites ({what}) in a check that was given no CiteResolver; a rule that reads "
        'cites declares needs={"cites"} and is a recorded skip without one',
        symbol="OW_TARGET_RULE_RAISED",
        fix='add "cites" to the rule\'s RuleSpec.needs',
    )


NO_CITES: Final[CiteResolver] = _NoCites()


def verbatim(visible: str, block: CitedBlock, span: tuple[int, int] | None) -> bool:
    """Ruling 3: the block is `VERBATIM` and the visible text is its span, under `nfc`."""
    if block.quote is not Quote.VERBATIM or block.text is None or span is None:
        return False
    a, b = span
    if not 0 <= a < b <= len(block.text):
        return False
    return nfc(visible) == nfc(block.text[a:b])
