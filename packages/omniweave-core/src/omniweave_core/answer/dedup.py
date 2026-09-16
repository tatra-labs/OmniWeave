"""The emission ledger: never send the same block twice in one conversation, and say when you
didn't.

charter.md:6681 gives the key and it is five components, not one:
`LedgerKey = tuple[str, bytes, int, str, bytes]` over `(corpus_id, doc_key, gen, cite,
content_digest)`. 12:975 calls the mechanism *"the **Emission ledger**, which never re-delivers a
Block already sent in this session"*, and the worked Answer's trailer prints what it bought --
`dedup saved 3,912 chars` against a 3,871-character document, so the ledger was worth more than the
answer it appears in.

## Withholding requires TWO facts, and the second is the one that makes the sentence true

18:480 is the whole of the rule: *"`content_digest` proves "the same content as we sent";
`doc_fresh` -- the same fact absence gate 6 computes -- proves "still matches disk", which is the
claim the back-reference sentence actually makes. A document edited since indexing is RE-SENT under
the staleness banner rather than pointed at."*

Read the sentence the renderer prints at 10:666 and the reason is obvious: *"the content digest is
unchanged and the source has not been edited since, so that copy is still exact"*. Two clauses, two
facts. A ledger that checked only the digest would print the second clause without having checked
it.

## The digest is in the KEY and is compared as a VALUE, and that is not a contradiction

`get()` looks up on FOUR components and compares `content_digest` afterwards, although the key has
five. Folding the digest into the lookup would produce the same emission -- a changed block would
simply miss and be re-sent -- but it would lose a distinction: "we never sent this cite" and "we
sent
this cite and its content has changed" are different facts, and the second is the one a reviewer
chasing a suspicious re-send wants. The key is the identity of an EMISSION; the lookup is the
identity of a BLOCK.

## No session, no dedup, and the trade is disclosed rather than absorbed

18:474: *"Without a session DEDUP IS OFF, deliberately: re-sending costs a few hundred characters
and
withholding costs a round trip."* 10:2393 repeats it for `--stateless` and adds the disclosure -- a
`Degradation` whose `kind` is `ledger_reset_by_compaction` because `DegradationKind` is closed at
twenty-seven members (15:988) and none of them names a ledger that was never opened. 10:2390 owes
the
register a twenty-eighth, `ledger_disabled`, and refuses to coin it in the wrong document; this
module refuses for the same reason and carries the message that says what really happened.

## Eviction always falls in the safe direction

`SESSION_LIMITS` bounds the ledger at four corpora, eight retained calls, twenty-four documents per
call and sixty-four blocks per document, and every one of those bounds can drop an emission for a
block that really was sent. That is safe BY CONSTRUCTION and only in one direction: forgetting an
emission re-sends content the agent already has, which costs a few hundred characters; inventing one
withholds content the agent does not have, which costs a round trip and reads as absence. Every
bound here therefore forgets rather than refuses, and the asymmetry is the reason the numbers can be
this small.

## D277: this runs BEFORE the allocator, and 02:502's arrow order says after

02:502 writes pipeline row 8 as `worth -> allocate -> dedup -> untrusted -> render`. 10:585 writes
*"**`ow:sent-earlier` is charged before allocation and is never droppable**"*. Both cannot hold: a
section charged before allocation must be KNOWN before allocation, and it is not known until the
withholding decision is made. The arrow order is also wasteful on its own terms -- allocating bytes
to blocks that are then withheld spends the envelope on nothing. So dedup filters the candidate set
and the allocator sizes what is left, which is the order 10:585 implies and the one this package
uses.

Specified in charter.md:6680-6697, 18-api-sketch.md:471-490, 10-interfaces.md:585 and 2374;
scheduled by 16-roadmap.md:662.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "DEDUP_OFF_MESSAGE",
    "LEDGER_KEY_FIELDS",
    "LEDGER_RESET_KIND",
    "MAX_BLOCKS_PER_DOC",
    "MAX_CALLS_RETAINED",
    "MAX_CORPORA",
    "MAX_DOCS_IN_POINTER",
    "MAX_DOCS_PER_CALL",
    "MAX_SPANS_IN_POINTER",
    "MIN_COVERED_CHARS",
    "MIN_DELTA_CHARS",
    "POINTER_CHARS",
    "Emission",
    "LedgerKey",
    "Partition",
    "SessionLedger",
    "Withheld",
    "partition",
    "withhold",
    "worth_withholding",
]

LedgerKey = tuple[str, bytes, int, str, bytes]
"""charter.md:6681, verbatim: `(corpus_id, doc_key, gen, cite, content_digest)`.

`doc_key` and `content_digest` are `bytes` and the other three are not, which is the charter's own
typing: a digest is a digest and rendering it hex to key a dict would make the ledger's memory a
function of a display choice."""

LEDGER_KEY_FIELDS: Final[tuple[str, ...]] = (
    "corpus_id",
    "doc_key",
    "gen",
    "cite",
    "content_digest",
)
"""The five names, in the charter's order, so a test can assert the tuple against the document."""

MAX_CORPORA: Final[int] = 4
"""18:485's `SESSION_LIMITS`. A fifth corpus evicts the least recently recorded one."""

MAX_CALLS_RETAINED: Final[int] = 8
"""18:485. The ledger remembers eight calls; a ninth forgets the first."""

MAX_DOCS_PER_CALL: Final[int] = 24
"""18:485. One call records at most twenty-four documents' emissions."""

MAX_BLOCKS_PER_DOC: Final[int] = 64
"""18:485. And at most sixty-four blocks of any one of them.

Not `omniweave_core.limits.MAX_BLOCKS_PER_DOC`, which is 8,388,608 and is the document model's bound
on how many blocks a document may HAVE. One name, two scopes, and this one is the session's."""

MIN_COVERED_CHARS: Final[int] = 400
"""18:486, with its own argument: *"a table cell is eight characters and below 400 the ~140-char
pointer is bigger than the content it replaces"*.

10:719 adds the half that is easy to miss -- the constant *"is set with that discount already
applied"*, the discount being that pointers tokenise badly (2.83 chars/token against evidence's
3.37), so 400 characters of prose replaced by 140 of pointer saves ~66 tokens where a flat divisor
predicts ~83. A retune must re-measure rather than reason in characters."""

MIN_DELTA_CHARS: Final[int] = 200
"""18:486's second threshold, and D278 is that only the first has a stated meaning.

The reading here is the one that makes both numbers do work and makes them agree at their own
boundary: `covered - pointer_chars >= MIN_DELTA_CHARS` is the NET saving, and at the plan's own
figures 400 - 140 = 260, comfortably above 200 and below what 500 covered characters would give. A
reading under which 200 is a second floor on `covered` would make it dead, because 400 already
dominates it."""

MAX_SPANS_IN_POINTER: Final[int] = 4
"""charter.md:6686 and 18:758: a `Pointer` names at most four cites."""

MAX_DOCS_IN_POINTER: Final[int] = 5
"""charter.md:6686. At most five documents per pointer row."""

POINTER_CHARS: Final[int] = 140
"""10:718's *"140-character pointer"*, which is what `MIN_DELTA_CHARS` is measured against.

18:756 sizes the same row at *"~110 characters instead of ~4,500"* and 18:1730 at ~110 for the
cliffed kind. 140 is the larger and therefore the conservative one to subtract: over-estimating the
pointer withholds less, and withholding less is the safe direction."""

LEDGER_RESET_KIND: Final[str] = "ledger_reset_by_compaction"
"""15:988's member, carried as a STRING on charter erratum E15's precedent (D248).

`omniweave_core.observe.degradation` does not exist, and 15 section 6.3 is the closed set's sole
home; a second literal here would be a twenty-eighth member coined in the wrong document, which is
exactly what 10:2390 refuses to do."""

DEDUP_OFF_MESSAGE: Final[str] = (
    "no session id: --stateless. Re-sent content is not deduplicated. "
    "Use a stateful transport for multi-call sessions."
)
"""10:2381-2383's message, which carries the real cause the `kind` cannot.

10:2386: *"That `kind` is the nearest legal member, not the right one."* The consequence is
identical
-- the next Answer re-sends evidence it would otherwise have withheld -- and the cause is not, so it
goes here where a reader will see it."""


@dataclass(frozen=True, slots=True)
class Emission:
    """One block, as the ledger sees it: the five key components plus what sending it cost.

    **This is not `RenderedBlock`, and D276 is why.** charter.md:6688 types `withhold()` as taking a
    `RenderedBlock`, and 18:588's `RenderedBlock` has twenty-six fields of which the ledger key
    needs
    five and finds ONE -- `cite`. There is no `corpus_id` (derivable from a QUALIFIED cite, and
    section 6.1 only qualifies cites when the deployment holds more than one corpus), no `doc_key`,
    no `gen` (`Answer.generation` is the SNAPSHOT generation, not the document's parse generation),
    and no `content_digest`. The function as typed cannot be written.

    `chars` is the evidence length the emission cost, which is what `MIN_COVERED_CHARS` is measured
    in and what the trailer's `dedup saved N chars` sums.
    """

    corpus_id: str
    doc_key: bytes
    gen: int
    cite: str
    content_digest: bytes
    chars: int = 0

    def __post_init__(self) -> None:
        if self.chars < 0:
            msg = f"Emission({self.cite!r}).chars={self.chars} is negative"
            raise ValueError(msg)
        if not self.cite:
            msg = "an Emission with no cite cannot be looked up"
            raise ValueError(msg)

    @property
    def lookup(self) -> tuple[str, bytes, int, str]:
        """The four components that identify a BLOCK. See the module docstring."""
        return (self.corpus_id, self.doc_key, self.gen, self.cite)

    @property
    def key(self) -> LedgerKey:
        """charter.md:6681's five, which identify an EMISSION."""
        return (self.corpus_id, self.doc_key, self.gen, self.cite, self.content_digest)


@dataclass(frozen=True, slots=True)
class Withheld:
    """One document's withheld blocks -- the raw material for an `ow:sent-earlier` row.

    Not a `Pointer` (18:754). A `Pointer` carries `doc_uri`, `pages` and the `fetch` command that
    re-opens it, none of which is a ledger fact: the ledger keys on `doc_key`, which is a digest,
    and
    the renderer holds the block that knows its own URI and page. This is what dedup can say; W6.6c
    turns it into the row the agent reads.
    """

    corpus_id: str
    doc_key: bytes
    cites: tuple[str, ...]
    covered_chars: int

    @property
    def blocks(self) -> int:
        """18:759's `Pointer.blocks` -- the count, which survives the four-cite cap."""
        return len(self.cites)

    @property
    def shown_cites(self) -> tuple[str, ...]:
        """At most `MAX_SPANS_IN_POINTER`, which is why `blocks` is a separate number."""
        return self.cites[:MAX_SPANS_IN_POINTER]


def worth_withholding(covered_chars: int, pointer_chars: int = POINTER_CHARS) -> bool:
    """18:486's two thresholds. Both must clear; see `MIN_DELTA_CHARS` for D278.

    `pointer_chars` is a parameter rather than a constant read because only the renderer knows how
    long the row it is about to write really is -- a document with a long URI and four long cites
    costs more than 140 characters, and withholding 420 characters behind a 300-character pointer is
    the failure this function exists to prevent.
    """
    return covered_chars >= MIN_COVERED_CHARS and covered_chars - pointer_chars >= MIN_DELTA_CHARS


class SessionLedger:
    """The emission ledger for one caller. Not a dataclass: it mutates (18:786).

    In memory and for the life of the `with` block. 18:476: *"there is no on-disk session state on
    the SDK path, because a library that wrote files into a user's project as a side effect of a
    read
    would be a surprise nobody asked for."* The server's on-disk half is the `PreCompact` marker,
    which is read by `stat` on every call (10:1950) and reaches this object as `clear()`.
    """

    __slots__ = ("_calls", "_corpora", "key")

    def __init__(self, key: str) -> None:
        if not key:
            msg = "a SessionLedger with no key is a ledger dedup is off for; do not build one"
            raise ValueError(msg)
        self.key = key
        self._calls: list[dict[tuple[str, bytes, int, str], Emission]] = []
        self._corpora: list[str] = []

    def get(self, corpus_id: str, doc_key: bytes, gen: int, cite: str) -> Emission | None:
        """The most recent emission of this block, or `None`. Four components, not five."""
        needle = (corpus_id, doc_key, gen, cite)
        for call in reversed(self._calls):
            found = call.get(needle)
            if found is not None:
                return found
        return None

    def record(self, emissions: Iterable[Emission]) -> int:
        """Record one call's emissions, bounded by `SESSION_LIMITS`. Returns how many were kept.

        Bounded in three places and forgetting at every one of them: `MAX_BLOCKS_PER_DOC` per
        document, `MAX_DOCS_PER_CALL` documents, `MAX_CALLS_RETAINED` calls. A fourth bound,
        `MAX_CORPORA`, evicts a whole corpus's emissions from every retained call.

        Order is preserved: the first `MAX_DOCS_PER_CALL` documents by first appearance, and within
        each the first `MAX_BLOCKS_PER_DOC` blocks. The caller hands them in rank order, so what
        survives a bound is what ranked highest, which is also what the agent is most likely to
        still
        be holding.
        """
        per_doc: dict[tuple[str, bytes], list[Emission]] = {}
        for emission in emissions:
            group = per_doc.setdefault((emission.corpus_id, emission.doc_key), [])
            if len(group) < MAX_BLOCKS_PER_DOC:
                group.append(emission)
        call: dict[tuple[str, bytes, int, str], Emission] = {}
        for group in list(per_doc.values())[:MAX_DOCS_PER_CALL]:
            for emission in group:
                call[emission.lookup] = emission
        if not call:
            return 0
        self._calls.append(call)
        del self._calls[:-MAX_CALLS_RETAINED]
        for emission in call.values():
            if emission.corpus_id in self._corpora:
                self._corpora.remove(emission.corpus_id)
            self._corpora.append(emission.corpus_id)
        self._evict_corpora()
        return len(call)

    def _evict_corpora(self) -> None:
        """Drop every emission of a corpus past `MAX_CORPORA`, least recently recorded first."""
        while len(self._corpora) > MAX_CORPORA:
            stale = self._corpora.pop(0)
            for call in self._calls:
                for key in [k for k, e in call.items() if e.corpus_id == stale]:
                    del call[key]
            self._calls = [call for call in self._calls if call]

    def clear(self) -> None:
        """Forget everything. 10:1947: *"not bookkeeping -- it is the correctness condition"*.

        The caller is the one that read the `PreCompact` marker, and the caller is the one that
        records `Degradation(kind=LEDGER_RESET_KIND)`: this object cannot tell a compaction from a
        session reap (10:2395) and would have to be told which, so it is told neither and does the
        one thing both mean.
        """
        self._calls.clear()
        self._corpora.clear()

    def stats(self) -> Mapping[str, int]:
        """18:788's `Session.stats()`: calls, docs, blocks, chars_sent."""
        blocks = [emission for call in self._calls for emission in call.values()]
        return {
            "calls": len(self._calls),
            "corpora": len(self._corpora),
            "docs": len({(e.corpus_id, e.doc_key) for e in blocks}),
            "blocks": len(blocks),
            "chars_sent": sum(e.chars for e in blocks),
        }


def withhold(prior: SessionLedger, blk: Emission, doc_fresh: bool) -> bool:
    """charter.md:6688's predicate, over the shape it can actually read. D276.

    Three conjuncts and the charter prints all three: the document is fresh, we sent this block
    before, and what we sent is byte-identical to what we would send now.

    `doc_fresh` FIRST, although the cheap test is the lookup. It is the conjunct a reader is most
    likely to drop as redundant, and 18:482 says what dropping it costs -- *"A document edited since
    indexing is RE-SENT under the staleness banner rather than pointed at"* -- so it is written
    where
    it cannot be skimmed past.
    """
    sent = prior.get(*blk.lookup)
    return doc_fresh and sent is not None and sent.content_digest == blk.content_digest


@dataclass(frozen=True, slots=True)
class Partition:
    """What dedup hands the allocator: what to pack, and what to point at."""

    kept: tuple[Emission, ...] = ()
    withheld: tuple[Withheld, ...] = ()
    chars_deduped: int = 0

    @property
    def documents_withheld(self) -> int:
        """`MAX_DOCS_IN_POINTER` bounds what one row names; this is how many there were."""
        return len(self.withheld)


def partition(
    ledger: SessionLedger | None,
    blocks: Sequence[Emission],
    *,
    fresh_docs: frozenset[bytes] = frozenset(),
    pointer_chars: int = POINTER_CHARS,
) -> Partition:
    """Split one call's blocks into what to send and what to point at. Runs BEFORE allocation
    (D277).

    `ledger is None` is the no-session case and returns everything as `kept` with no withheld rows
    and `chars_deduped == 0` -- 18:475's *"Without a session DEDUP IS OFF, deliberately"*. It is not
    an error and the caller does not need a branch; the disclosure is the caller's `Degradation`.

    A document whose withheld blocks do not clear `worth_withholding()` is UN-withheld in full: its
    blocks go back into `kept` rather than being split across a pointer and the evidence, because a
    row reading *"already sent earlier"* beside the same document's text says two things at once.
    Grouping is by `(corpus_id, doc_key)`, which is the ledger's own document identity.
    """
    if ledger is None:
        return Partition(kept=tuple(blocks))
    kept: list[tuple[int, Emission]] = []
    candidates: dict[tuple[str, bytes], list[tuple[int, Emission]]] = {}
    for index, block in enumerate(blocks):
        if withhold(ledger, block, block.doc_key in fresh_docs):
            candidates.setdefault((block.corpus_id, block.doc_key), []).append((index, block))
        else:
            kept.append((index, block))
    withheld: list[Withheld] = []
    for (corpus_id, doc_key), group in candidates.items():
        covered = sum(block.chars for _, block in group)
        if not worth_withholding(covered, pointer_chars):
            kept.extend(group)
            continue
        withheld.append(
            Withheld(
                corpus_id=corpus_id,
                doc_key=doc_key,
                cites=tuple(block.cite for _, block in group),
                covered_chars=covered,
            )
        )
    kept.sort(key=lambda row: row[0])
    return Partition(
        kept=tuple(block for _, block in kept),
        withheld=tuple(withheld),
        chars_deduped=sum(row.covered_chars for row in withheld),
    )
