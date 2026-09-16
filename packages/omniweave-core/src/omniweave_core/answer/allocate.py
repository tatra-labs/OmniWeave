"""`allocate()` -- reserve-then-render, and the 15% cliff that is called THE LEVER.

charter.md:6656 names the rule and the bug it replaces in one line: *"RESERVE-THEN-RENDER.
First-come-first-served lets the top two eat the envelope."* Every constant under it is one of two
kinds -- a bound on how much any one document may take, or a floor below which taking anything is
worse than taking nothing -- and the ordering between them is what this module is.

The stages, in the order they run:

1. **Group by document.** `DOC_OVERHEAD` is charged per document and `max_docs` is counted in
   documents, so the unit of allocation is a document and not a block.
2. **Weigh.** `weight(doc) = sum over its candidates of score x worth x spine`. Relevance and worth
   are the two scores charter.md:6666 keeps apart; `SPINE_BOOST` is the third factor and is neither.
3. **Cliff.** Below `CLIFF_FRACTION` of the top document's weight a document becomes a pointer
   and, 18:1730, *"does not consume a `max_docs` slot"*.
4. **Slot.** The first `max_docs` survivors by weight; the rest are pointers too.
5. **Reserve.** `DOC_OVERHEAD x docs + BLOCK_OVERHEAD x blocks`, taken off the envelope *before* a
   single character of evidence is allocated (10:723).
6. **Split.** What is left, in rank order with carry-forward, bounded by `chars_per_doc` and
   `MAX_SHARE`, with `MIN_CHARS` turning a document that would be cut short into a pointer.
7. **Buy.** `BUY_POOL` is held back from the split and spent, in rank order, to finish a section
   that is already `WHOLE_SECTION_BUY` packed.

## The cliff exempts an EXACT-CITE extracted hit, not every extracted hit -- D271

charter.md:6659 is `"CLIFF_EXEMPT_TRUST": Trust.EXTRACTED` with the comment *"an exact-cite
extracted hit is never cliffed"*, and 18:1731 repeats the comment verbatim. The constant names ONE
conjunct and the comment names TWO, and reading the constant alone disables the lever completely:
`MAX_TRUST_BY_METHOD` ceilings `NATIVE`, `NATIVE_XML`, `TEXT_LAYER`, `HEURISTIC` and `USER` at
`Trust.EXTRACTED`, which is every born-digital path, so on a born-digital corpus essentially every
block is `EXTRACTED` and a trust-only exemption exempts everything. The lever would never pull on
the corpus this framework is for.

So both conjuncts are evaluated: `CLIFF_EXEMPT_TRUST` **and** a rank from a Channel that matched an
exact thing. `CLIFF_EXEMPT_CHANNELS` is `{identity, exact}` because those are the two of 07:1202's
five whose match IS an exact cite -- `identity` resolves a named thing and `exact` a literal string,
while `lexical`, `semantic` and `structural` all match approximately. `channel_ranks` is the
carrier, and 07:2283 already makes that mapping the predicate a consumer partitions on. D271 records
that the second conjunct has no constant.

`SPINE_BOOST` is the other exemption and it is stated as one (18:1736: *"applied to a block
reachable by `rel` from another hit; cliff-exempt"*).

## `MIN_CHARS` refuses a CUT document, not a small one

charter.md:6660 is `"MIN_CHARS": 600` and *"A FRAGMENT IS WORSE THAN A POINTER"*. A fragment is a
document shown INCOMPLETELY: three paragraphs of a five-paragraph answer read as the answer, and
the reader has no way to know the other two exist. A document whose whole evidence is 200
characters -- one table cell, one caption -- is not a fragment, it is a complete small thing, and
turning it into a 110-character pointer to itself would cost a round trip to save 90 characters.

So the rule is `take < demand and take < MIN_CHARS`, and a document that fits entirely below
`MIN_CHARS` packs. The plan states only the constant, so the conjunct is this module's reading; the
alternative -- refusing any allocation below 600 -- makes the smallest tier unable to show a table
cell at all.

## Dropping a fragment reopens the split, so the loop is a fixpoint

Removing a document returns its entitlement AND its overhead to the pool, which can lift the next
document above `MIN_CHARS`. The split therefore runs to a fixpoint: split, find the
lowest-ranked document that fragments, drop it, split again. Each pass removes at least one
document and `max_docs` is at most 10, so it terminates in at most ten passes and usually one.

The lowest-ranked fragment is dropped first, never the highest: the whole point of reserve-then-
render is that the ranking decides who eats, and dropping from the top would let a mid-ranked
document survive at a top-ranked one's expense.

## Determinism

Documents are ordered on `(-weight, first_index)`, where `first_index` is the position of the
document's best candidate in the input. The input is totally ordered by ST7 (`(-score, block_id)`),
so `first_index` breaks every weight tie and the order is total -- the same shape, and for the same
reason, as W6.3's `FusedHit` sort. Weights are summed with `math.fsum` so grouping order cannot move
a tie.

## What `allocate()` is handed, and D269

02:502 runs the pipeline as `answer.worth -> allocate -> dedup -> untrusted -> render` over a
`Response(hits, verdict, cost)`, so on the page the allocator's input is a `Hit`. It cannot be.
07:2251's `Hit` has fourteen fields and carries neither `layer` nor `kind`, and two of `worth()`'s
four tables are keyed on exactly those, so `WORTH_LAYER` and `WORTH_KIND` have no input anywhere on
the shape the pipeline hands over. 07:2119 already routes around the same hole for one other number
-- `generated_share` reads `method(h)`, a function and not a field, because `Hit` has no `method`
either -- but `worth` has no such route, and `ow:provenance` separately needs `doc`, `page`, `kind`,
`method` and `driver`, none of which are `Hit` fields.

`Candidate` is therefore this module's own input: the six facts allocation reads, named at the one
site that reads them. It is not a competing shape for a block -- it carries no text, no span and no
provenance -- and 18:588's `RenderedBlock` remains the renderer's. D269 records the gap.

Specified in charter.md:6656-6665, 10-interfaces.md:722, 18-api-sketch.md:1730-1738 and
07-store-and-retrieval.md:2357; scheduled by 16-roadmap.md:662.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.answer.budget import effective_max_chars
from omniweave_core.model.enums import Trust

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from omniweave_core.answer.budget import BudgetTier

__all__ = [
    "BLOCK_OVERHEAD",
    "BUY_POOL",
    "CLIFF_EXEMPT_CHANNELS",
    "CLIFF_EXEMPT_TRUST",
    "CLIFF_FRACTION",
    "DOC_OVERHEAD",
    "MAX_SHARE",
    "MIN_CHARS",
    "SPINE_BOOST",
    "WHOLE_SECTION_BUY",
    "Allocation",
    "Candidate",
    "CliffReason",
    "Cliffed",
    "DocPlan",
    "allocate",
]

CLIFF_FRACTION: Final[float] = 0.15
"""18:1730 calls it **the lever**; charter.md:6657 prints it.

*"below 15% of the top document's weight -> POINTER ONLY (~110 chars vs ~4,500) AND it does not
consume a max_docs slot."* Both halves matter: the saving is 40x per document, and freeing the slot
is what lets a fifth relevant document in when the fourth was noise."""

CLIFF_EXEMPT_TRUST: Final[Trust] = Trust.EXTRACTED
"""charter.md:6659. The FIRST of the exemption's two conjuncts; see `CLIFF_EXEMPT_CHANNELS`."""

CLIFF_EXEMPT_CHANNELS: Final[frozenset[str]] = frozenset({"identity", "exact"})
"""The second conjunct of *"an exact-cite extracted hit is never cliffed"*, which has no constant.

Two of 07:1202's five Channels match an exact thing: `identity` resolves a named one and `exact` a
literal string. The other three are approximate, and a `lexical` hit at `Trust.EXTRACTED` is the
ordinary case rather than the exempt one. D271."""

MIN_CHARS: Final[int] = 600
"""charter.md:6660. *"A FRAGMENT IS WORSE THAN A POINTER."* Applied to a CUT document only."""

MAX_SHARE: Final[float] = 0.60
"""charter.md:6661. *"a valve against one god-document."* Bounds the split AND the buy."""

DOC_OVERHEAD: Final[int] = 180
"""charter.md:6662, 10:722. Charged per packed document before allocation."""

BLOCK_OVERHEAD: Final[int] = 95
"""charter.md:6662, 10:722. Charged per candidate block of a packed document, before allocation.

**It under-reserves against the plan's own worked Answer, and D273 is by how much.** 10:617-686's
three evidence blocks cost 200, 271 and 283 characters of non-text structure -- the `**<< ... >>**`
header, the quotability advisory, and the two fence lines -- for a mean of 251 against this 95. The
evidence section's total structure is 1,010 characters where `2 x 180 + 3 x 95` reserves 645. The
constant is config-visible (18:1734) and is transcribed here unchanged; the truncator is the real
bound, and D273 says so rather than this module quietly reserving a number the plan does not
print."""

SPINE_BOOST: Final[float] = 2.0
"""charter.md:6663, 18:1736. *"reachable by `rel` from another hit; cliff-exempt."*

A multiplier on the block's own contribution to its document's weight, not on the fused score:
07:1425's ranks are fusion's and this is packing's, and moving a block up the evidence order because
it neighbours a hit would reorder an Answer whose order the caller can reproduce."""

WHOLE_SECTION_BUY: Final[float] = 0.60
"""charter.md:6664. How much of a section must already be packed before it may buy the rest.

Read as a THRESHOLD and not as a pool fraction, because `BUY_POOL` beside it is the pool and two
pool fractions under one comment reading *"ONE shared pool"* would be two pools."""

BUY_POOL: Final[float] = 0.15
"""charter.md:6664. The fraction of the post-reserve pool held back from the split for section buys.

*"ONE shared pool, spent in rank order"* -- shared across every section of every packed document,
so a top-ranked document's half-packed section is finished before a lower-ranked one's."""

CliffReason = Literal["below_cliff", "no_slot", "fragment"]
"""Why a document became a pointer instead of evidence.

Three reasons and not one, because `ow:notseen` prints a sentence per pointer and 10:671's
*"matched, below the byte cliff"* is true of only the first. A document that lost a `max_docs`
slot was ranked above the cliff and one that fragmented would have been shown whole a tier up;
a surface that could not tell them apart would print the same sentence for three different facts."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """The six facts allocation reads about one block, and nothing else. See D269 above.

    `chars` is `length(block.text)` taken at hydration, which is 07:2118's rule for the same number
    in `generated_share`: *"`chars(h)` is `length(block.text)` taken at hydration, not
    `len(Hit.text)`"*, because `PackSpec.hydrate_text = False` makes the field `None` and an
    allocator that silently measured zero would pack everything.

    `worth` arrives computed rather than as four enums: `answer.worth` is its one home (INV-21) and
    passing the product keeps this module free of `Kind`, `Layer` and `Quote`. `trust` is the
    exception and is carried, because the cliff exemption is keyed on it.
    """

    doc_key: str
    cite: str
    chars: int
    score: float
    worth: float
    trust: Trust
    channels: frozenset[str] = frozenset()
    spine: bool = False
    section: str | None = None

    def __post_init__(self) -> None:
        if self.chars < 0:
            msg = f"Candidate({self.cite!r}).chars={self.chars} is negative"
            raise ValueError(msg)
        if self.worth < 0.0:
            msg = f"Candidate({self.cite!r}).worth={self.worth} is negative"
            raise ValueError(msg)

    @property
    def weight(self) -> float:
        """`score x worth x spine`. The block's contribution to its document's weight."""
        return self.score * self.worth * (SPINE_BOOST if self.spine else 1.0)

    @property
    def cliff_exempt(self) -> bool:
        """18:1731's two conjuncts, or 18:1736's one. See `CLIFF_EXEMPT_CHANNELS` and D271."""
        if self.spine:
            return True
        return self.trust >= CLIFF_EXEMPT_TRUST and bool(self.channels & CLIFF_EXEMPT_CHANNELS)


@dataclass(frozen=True, slots=True)
class DocPlan:
    """One packed document: what it was given, and what did not fit inside it."""

    doc_key: str
    weight: float
    chars: int
    blocks: tuple[Candidate, ...]
    dropped: tuple[Candidate, ...] = ()
    bought: int = 0

    @property
    def truncated(self) -> bool:
        """Blocks of this document were dropped for room. `ow:notseen` says so per document."""
        return bool(self.dropped)


@dataclass(frozen=True, slots=True)
class Cliffed:
    """One document that became a pointer, and the reason a surface must print."""

    doc_key: str
    reason: CliffReason
    weight: float
    blocks: tuple[Candidate, ...] = ()


@dataclass(frozen=True, slots=True)
class Allocation:
    """The byte plan: who packs, who points, and where every character of the envelope went."""

    packed: tuple[DocPlan, ...] = ()
    cliffed: tuple[Cliffed, ...] = ()
    envelope: int = 0
    reserved: int = 0
    pool: int = 0
    spent: int = 0
    buy_spent: int = 0
    tier_chars_per_doc: int = 0

    @property
    def unspent(self) -> int:
        """The pool the split did not reach.

        Not waste: 10:584's drop order gives `ow:provenance`, `ow:related` and `ow:notseen` *"from
        remaining room"*, and this is that room. An allocator that redistributed it to the packed
        documents would starve the three sections the plan funds from it."""
        return self.pool - self.spent

    @property
    def docs_used(self) -> int:
        """`AnswerBudget.docs_used`. Cliffed documents are not counted -- 18:1730's own rule."""
        return len(self.packed)


def _grouped(candidates: Iterable[Candidate], cap: int) -> dict[str, list[Candidate]]:
    """Group by `doc_key` in first-appearance order, keeping at most `cap` blocks per document.

    The cap is derived, not chosen: every packed block costs at least `BLOCK_OVERHEAD`, so a
    document can never show more than `chars_per_doc // BLOCK_OVERHEAD` of them and reserving for
    the rest would charge the envelope for blocks arithmetic has already excluded. At the smallest
    tier that is 3,500 // 95 = 36 blocks, comfortably above `PackSpec.max_blocks = 60` split across
    four documents.
    """
    groups: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        blocks = groups.setdefault(candidate.doc_key, [])
        if len(blocks) < cap:
            blocks.append(candidate)
    return groups


@dataclass(frozen=True, slots=True)
class _Doc:
    """A grouped document, ordered on `(-weight, first_index)` -- ST7's shape."""

    doc_key: str
    first_index: int
    blocks: tuple[Candidate, ...]
    weight: float = field(compare=False, default=0.0)

    @property
    def demand(self) -> int:
        return sum(block.chars for block in self.blocks)

    @property
    def exempt(self) -> bool:
        return any(block.cliff_exempt for block in self.blocks)


def _weigh(groups: dict[str, list[Candidate]]) -> list[_Doc]:
    docs: list[_Doc] = []
    for index, (doc_key, blocks) in enumerate(groups.items()):
        docs.append(
            _Doc(
                doc_key=doc_key,
                first_index=index,
                blocks=tuple(blocks),
                weight=math.fsum(block.weight for block in blocks),
            )
        )
    docs.sort(key=lambda doc: (-doc.weight, doc.first_index))
    return docs


def _fit(
    blocks: Sequence[Candidate], take: int
) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
    """Whole blocks, in rank order, until `take` is exhausted. Never a partial block.

    13:882's P-18 asserts that truncation *"cuts whole Answer sections and whole blocks, never
    mid-fence"*, and the allocator is where that first becomes true: a block the plan did not fund
    is never half-funded. A block that does not fit does NOT stop the scan -- a later, smaller block
    may still fit -- because the alternative wastes the tail of every document whose largest block
    happens to rank first.
    """
    kept: list[Candidate] = []
    dropped: list[Candidate] = []
    spent = 0
    for block in blocks:
        if spent + block.chars <= take:
            kept.append(block)
            spent += block.chars
        else:
            dropped.append(block)
    return tuple(kept), tuple(dropped)


def _split(docs: Sequence[_Doc], pool: int, tier: BudgetTier) -> dict[str, int]:
    """Rank order with carry-forward, bounded by `chars_per_doc` and `MAX_SHARE`.

    The entitlement is the document's weight share of the pool; the carry is what the documents
    above it did not take, because a top-ranked document that needed 400 characters should not
    strand its share. The three bounds are applied in one `min` so no order between them can matter.
    """
    total = math.fsum(doc.weight for doc in docs)
    share_cap = int(pool * MAX_SHARE)
    takes: dict[str, int] = {}
    carry = 0
    for doc in docs:
        entitlement = int(pool * (doc.weight / total)) if total > 0.0 else pool // len(docs)
        take = min(entitlement + carry, tier.chars_per_doc, share_cap, doc.demand)
        takes[doc.doc_key] = max(take, 0)
        carry += entitlement - takes[doc.doc_key]
    return takes


def _buy(
    docs: Sequence[_Doc],
    plans: dict[str, tuple[tuple[Candidate, ...], tuple[Candidate, ...]]],
    takes: dict[str, int],
    budget: int,
    share_cap: int,
) -> tuple[dict[str, int], int]:
    """Finish a section already `WHOLE_SECTION_BUY` packed, in rank order, from one shared pool.

    A section is `Candidate.section` -- the `block_sec` scope the block sits in. Blocks with no
    section never buy: an unsectioned block has no whole to complete.

    **The buy can only reach blocks that were RETRIEVED, and D274 is that the plan means more.**
    "Finishing a section" implies the section's other blocks, which did not match the query and are
    therefore not in `Response.hits` at all; reaching them needs a read of `block_sec` the allocator
    is not given and the snapshot may already have closed on. What is bought here is the section's
    remaining CANDIDATES -- the blocks that matched and that the split could not fund -- which is
    the same mechanism over the set the allocator actually holds.
    """
    bought: dict[str, int] = {}
    remaining = budget
    for doc in docs:
        kept, dropped = plans[doc.doc_key]
        if not dropped or remaining <= 0:
            continue
        by_section: dict[str, list[Candidate]] = {}
        for block in doc.blocks:
            if block.section is not None:
                by_section.setdefault(block.section, []).append(block)
        kept_cites = {block.cite for block in kept}
        ceiling = share_cap - takes[doc.doc_key] - bought.get(doc.doc_key, 0)
        for section_blocks in by_section.values():
            packed = sum(1 for block in section_blocks if block.cite in kept_cites)
            if packed / len(section_blocks) < WHOLE_SECTION_BUY:
                continue
            for block in section_blocks:
                if block.cite in kept_cites:
                    continue
                if block.chars > remaining or block.chars > ceiling:
                    continue
                kept = (*kept, block)
                kept_cites.add(block.cite)
                dropped = tuple(other for other in dropped if other.cite != block.cite)
                remaining -= block.chars
                ceiling -= block.chars
                bought[doc.doc_key] = bought.get(doc.doc_key, 0) + block.chars
        order = {block.cite: position for position, block in enumerate(doc.blocks)}
        plans[doc.doc_key] = (tuple(sorted(kept, key=lambda b: order[b.cite])), dropped)
    return bought, budget - remaining


def allocate(
    candidates: Iterable[Candidate],
    *,
    tier: BudgetTier,
    max_chars: int | None = None,
) -> Allocation:
    """The byte plan for one Answer. charter.md:6656's seven stages, in order.

    `max_chars` is the caller's request and is clamped by `effective_max_chars()` -- 10:479's
    `min(requested, tier.max_chars, HARD_CEILING)`, never raised above the tier.

    Returns an `Allocation` whose `packed` is in rank order and whose `cliffed` carries a reason per
    document. An empty candidate set returns an empty `Allocation` with the envelope recorded: an
    Answer with no evidence still has a budget, and `ow:trailer` prints it.
    """
    envelope = effective_max_chars(max_chars, tier)
    candidates = tuple(candidates)
    if not candidates:
        return Allocation(envelope=envelope, tier_chars_per_doc=tier.chars_per_doc)

    per_doc_cap = max(1, tier.chars_per_doc // BLOCK_OVERHEAD)
    docs = _weigh(_grouped(candidates, per_doc_cap))

    top = docs[0].weight
    cliffed: list[Cliffed] = []
    survivors: list[_Doc] = []
    for doc in docs:
        if doc.weight < CLIFF_FRACTION * top and not doc.exempt:
            cliffed.append(Cliffed(doc.doc_key, "below_cliff", doc.weight, doc.blocks))
        else:
            survivors.append(doc)
    for doc in survivors[tier.max_docs :]:
        cliffed.append(Cliffed(doc.doc_key, "no_slot", doc.weight, doc.blocks))
    kept = survivors[: tier.max_docs]

    plans: dict[str, tuple[tuple[Candidate, ...], tuple[Candidate, ...]]] = {}
    takes: dict[str, int] = {}
    reserved = pool = buy_budget = 0
    while kept:
        reserved = DOC_OVERHEAD * len(kept) + BLOCK_OVERHEAD * sum(len(doc.blocks) for doc in kept)
        pool = envelope - reserved
        buy_budget = int(pool * BUY_POOL)
        if pool <= 0:
            cliffed.append(Cliffed(kept[-1].doc_key, "no_slot", kept[-1].weight, kept[-1].blocks))
            kept = kept[:-1]
            continue
        # The fixpoint runs against the SPLIT pool and not the whole one: the buy pool is held
        # back before the split, so a document judged against `pool` would be told it had room
        # `BUY_POOL` of which is not its to spend, and the fragment it was cleared of would come
        # back at the real split.
        takes = _split(kept, pool - buy_budget, tier)
        fragments = [
            doc
            for doc in kept
            if takes[doc.doc_key] < doc.demand and takes[doc.doc_key] < MIN_CHARS
        ]
        if not fragments:
            break
        worst = fragments[-1]
        cliffed.append(Cliffed(worst.doc_key, "fragment", worst.weight, worst.blocks))
        kept = [doc for doc in kept if doc.doc_key != worst.doc_key]
    if not kept:
        return Allocation(
            cliffed=tuple(cliffed),
            envelope=envelope,
            tier_chars_per_doc=tier.chars_per_doc,
        )

    for doc in kept:
        plans[doc.doc_key] = _fit(doc.blocks, takes[doc.doc_key])
    bought, buy_spent = _buy(kept, plans, takes, buy_budget, int(pool * MAX_SHARE))

    packed = tuple(
        DocPlan(
            doc_key=doc.doc_key,
            weight=doc.weight,
            chars=sum(block.chars for block in plans[doc.doc_key][0]),
            blocks=plans[doc.doc_key][0],
            dropped=plans[doc.doc_key][1],
            bought=bought.get(doc.doc_key, 0),
        )
        for doc in kept
    )
    return Allocation(
        packed=packed,
        cliffed=tuple(cliffed),
        envelope=envelope,
        reserved=reserved,
        pool=pool,
        spent=sum(plan.chars for plan in packed),
        buy_spent=buy_spent,
        tier_chars_per_doc=tier.chars_per_doc,
    )
