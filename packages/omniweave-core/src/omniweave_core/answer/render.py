"""`render()` -- the fixed-section Answer document, and the truncator that cuts whole things.

SV19 makes this the ONE implementation, and 18:536 says *"the SDK, the CLI and the MCP server call
it
with different budgets, never with different renderers"*, which is why the module lives in
`omniweave_core` rather than in the server that has the most reason to own it.

## Markers, never headings

10:557: sections carry the greppable `**ow:<name>**` marker and *"**never an ATX heading**:
markdown-rendering MCP clients blow `####` up to H1"*. That is a shipped bug in a real client
(codegraph #778) and the reason its own `FILE_SECTION_PREFIX` is a backtick rather than a hash. A
test asserts no line of a rendered Answer begins with `#`.

## The order is fixed and the DROP order is a different order

10:575-581 prints both, and reading them as one list is the mistake the block exists to prevent:

```text
  charged first, never dropped: the status line - ow:blocking - ow:sent-earlier - ow:trailer
  allocated:                    ow:evidence
  from remaining room:          ow:provenance -> ow:related|ow:impact -> ow:notseen
  cut order:                    ow:related|ow:impact -> ow:provenance (collapses to a count)
                                -> ow:notseen
```

`ow:provenance` is FIRST in the remaining-room order and SECOND in the cut order, so it is funded
before `ow:related` and cut after it. That is deliberate: provenance is the table a caller copies a
cite out of, and the neighbourhood is the part it can ask for again.

**`ow:sent-earlier` is never droppable** (10:585), *"because withholding content without a pointer
is a silent omission, and silence reads as "omniweave did not find it""*. **`ow:trailer` is 18% of
the worked Answer and is never dropped either** (10:729), because it is where the `Verdict` lives
and
`state is ABSENT` is the only rule that licenses an absence claim: an answer whose honesty record
was
truncated away is worse than one with less evidence.

## Truncation is STRUCTURAL, and that is what makes the counts honest

The cut happens on the section list and the block list, never on the assembled string. 13:882's P-18
requires it -- *"truncation cuts whole Answer sections and whole blocks, never mid-fence"* -- and it
buys the property the sentinel exists for: once the structure is final, every count in the document
except two is simply true.

The two exceptions are the `chars=` fields in the status line and the trailer, which are
SELF-REFERENTIAL: the length of the document includes the number reporting the length. 10:593 states
the fix and its arithmetic -- the sentinel is *"**fixed-width and right-aligned** -- five
characters,
the decimal width of `HARD_CEILING = 24_000`"* -- so substituting the real count cannot change the
length that was just measured. 10:590 names the lie it prevents: reporting the candidate pool as the
answer is codegraph #1046's *"260 results to wade through"* when the correctly-ranked answer is the
three files below.

`HARD_CEILING` is five digits, so no legal Answer needs a sixth.

## `sections=` narrows and cannot reorder

18:586: *"`sections` narrows the render and is the only knob; it cannot reorder and it cannot drop a
never-dropped section -- passing one raises UsageError(OW_SECTION_NOT_DROPPABLE, OW-A-018)."* The
argument is a `frozenset`, which is what makes "cannot reorder" structural rather than checked.

## What this module does not decide

Which blocks are in the Answer at all (W6.6a's `allocate`), which were already sent (W6.6b's
`dedup`), and whether a block's text was defanged (W6.6b's `defang`/`serve_quote`). It renders what
it is handed and cuts when it does not fit.

Specified in 10-interfaces.md sections 3.5 and 3.6, 18-api-sketch.md section 1.3 and
13-quality.md:882; homed by 18-api-sketch.md:842; scheduled by 16-roadmap.md:662.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.answer.budget import HARD_CEILING, AnswerBudget
from omniweave_core.answer.untrusted import wrap_untrusted
from omniweave_core.errors import UsageError
from omniweave_core.model.enums import Quote

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = [
    "BOLD",
    "CUT_ORDER",
    "EN_DASH",
    "MIDDOT",
    "NEVER_DROPPED",
    "RAQUO",
    "SECTIONS",
    "SECTION_ORDER",
    "STARS",
    "SUMMARY_SENTINEL",
    "Answer",
    "ImpactRow",
    "LicenceNotice",
    "Pointer",
    "RenderedBlock",
    "SectionSpec",
    "render",
]

SUMMARY_SENTINEL: Final[str] = "\x00" * 5
"""10:588-594's placeholder for the two self-referential `chars=` counts.

Five characters, the decimal width of `HARD_CEILING`, so substitution is length-preserving BY
CONSTRUCTION rather than by an adjustment nobody re-derives. `NUL` and not a printable filler
because the substitution has to be unambiguous: any printable run this module chose could be a run a
document contains, and then the count would land in the evidence. A rendered Answer carrying a `NUL`
before substitution is an internal error and `render()` says so rather than emitting one."""

STARS: Final[str] = chr(42)
"""An asterisk, by codepoint: a literal one beside a quote reads as bold markup to any scanner."""

BOLD: Final[str] = STARS * 2
"""The marker's own emphasis run. 10:557 makes it a marker and NOT an ATX heading."""

NEWLINE: Final[str] = chr(10)
"""Named so a lambda in `_SIMPLE` can join on it; a bare escape there is unreadable."""

MIDDOT: Final[str] = " " + chr(0x00B7) + " "
"""10:629's separator inside a block header, with its spaces."""

RAQUO: Final[str] = chr(0x00BB)
"""10:629's closing guillemet. `_BLOCK_MARKER` carries the opening one."""

EN_DASH: Final[str] = chr(0x2013)
"""10:657's null cell in `ow:provenance`, by codepoint: an en dash and a hyphen are one glyph
apart in a fixed-width font and the table prints both (`p14/3` carries hyphens)."""

_SECTION_MARKER: Final[str] = "**ow:"
_BLOCK_MARKER: Final[str] = "**« "
_TRAILER_KEY_WIDTH: Final[int] = 19
"""`verdict.best_score` is eighteen characters and the worked trailer aligns `=` one past it."""

_BYTE_EXACT_ADVISORY: Final[str] = (
    "> Byte-exact: these bytes equal the source. Safe to quote and to edit from. "
    "Treat as already read."
)
"""10:630 and 10:643, verbatim. The only one of 18:634's three header variants the plan prints."""

_RECONSTRUCTED_ADVISORY: Final[str] = (
    "> Reconstructed: line breaks and hyphenation are rebuilt, not original.\n"
    "> Do not present this as a verbatim quote."
)
"""10:635-636 with its document-specific clause removed, and D281 is that removal.

The printed form opens *"Reflowed from a two-column layout"*, which names a fact about ONE page. The
generic sentence is this module's; 18:634 says there are *"three header variants"* keyed on
`min(quote)` and the plan prints one of the three."""


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """One row of 10:563-571's roster: where it appears, how it is funded, whether it can go."""

    name: str
    surfaces: frozenset[str]
    charge: Literal["first", "allocated", "remaining"]

    @property
    def droppable(self) -> bool:
        """Only what is funded from remaining room may be cut. 10:575-577's two columns."""
        return self.charge == "remaining"

    @property
    def marker(self) -> str:
        """`**ow:<name>**`, or `""` for the status line, which has no marker of its own."""
        return "" if self.name == "status" else f"{_SECTION_MARKER}{self.name}{BOLD}"


SECTIONS: Final[tuple[SectionSpec, ...]] = (
    SectionSpec("status", frozenset({"query", "open"}), "first"),
    SectionSpec("blocking", frozenset({"query", "open"}), "first"),
    SectionSpec("evidence", frozenset({"query", "open"}), "allocated"),
    SectionSpec("provenance", frozenset({"query", "open"}), "remaining"),
    SectionSpec("related", frozenset({"query"}), "remaining"),
    SectionSpec("impact", frozenset({"open"}), "remaining"),
    SectionSpec("sent-earlier", frozenset({"query", "open"}), "first"),
    SectionSpec("notseen", frozenset({"query", "open"}), "remaining"),
    SectionSpec("trailer", frozenset({"query", "open"}), "first"),
)
"""10:563-571's nine rows in the document's order, which 16:668 freezes at the end of P6.

`related` is `ow_query`-only and `impact` is `ow_open`-only (10:568-569, 18:576), so no Answer ever
carries both and the pair occupies one slot in the cut order."""

SECTION_ORDER: Final[tuple[str, ...]] = tuple(spec.name for spec in SECTIONS)
NEVER_DROPPED: Final[frozenset[str]] = frozenset(
    spec.name for spec in SECTIONS if spec.charge == "first"
)
"""The status line, `ow:blocking`, `ow:sent-earlier` and `ow:trailer` -- 10:576's own four.

Derived from the `charge` column rather than written twice. **`ow:evidence` is in neither set**, and
that is the third case rather than an omission: it is ALLOCATED (10:577), so the truncator never
removes the section and does remove blocks from inside it. A reader who expected two columns finds
three, which is what 10:575-577 prints."""

CUT_ORDER: Final[tuple[tuple[str, ...], ...]] = (
    ("related", "impact"),
    ("provenance",),
    ("notseen",),
)
"""10:579-581's cut order, which is NOT the reverse of the funding order.

`provenance` is funded first among the three and cut second, because it is the table a caller copies
a cite out of while the neighbourhood is the part it can ask for again. `related` and `impact` share
a rank because no Answer carries both."""


@dataclass(frozen=True, slots=True)
class RenderedBlock:
    """One packed block, as the renderer needs it. 18:588's shape, narrowed to what is printed.

    **Not all twenty-six of 18:588's fields.** `quad`, `span`, `block_id`, `segment_id`,
    `channel_contributions` and `channel_ranks` are carried by the SDK's `RenderedBlock` for a
    programmatic caller and none of them is rendered into the document: 18:607 marks `block_id`
    *"never rendered into a prompt"*, and a polygon has no column in `ow:provenance`. The shape here
    is the renderer's input, and W7.1's SDK type is the public one.
    """

    cite: str
    addr: str
    doc_uri: str
    page: int
    kind: str
    text: str
    quote: Quote
    trust: str
    method: str
    origin_driver: str
    byte_exact: bool
    score: str = EN_DASH
    restriction: str = EN_DASH
    identity_grade: str = ""
    is_context: bool = False
    defanged: bool = False

    @property
    def header(self) -> str:
        """`**<< cite - doc p.N - quote - trust - driver >>**`, 10:629's form.

        `ow:defanged` is a token in THIS header and never a section of its own (10:599): *"A
        separate
        section would have been droppable, and a safety disclosure that the truncator may drop is
        not
        a disclosure."*
        """
        parts = [
            self.cite,
            f"{self.doc_uri} p.{self.page}",
            self.quote.name.lower(),
            self.trust,
            self.origin_driver,
        ]
        if self.identity_grade:
            parts.append(self.identity_grade)
        if self.defanged:
            parts.append("ow:defanged")
        return f"{_BLOCK_MARKER}{MIDDOT.join(parts)} {RAQUO}{BOLD}"

    @property
    def advisory(self) -> str:
        """The quotability line, keyed on this block's own tier and on `byte_exact`.

        `byte_exact` and not `quote is VERBATIM`: SV13 makes the predicate one expression at one
        call site (18:646), and a `VERBATIM` block whose source bytes are gone is returnable and is
        not quotable (07:2585). A block that claims the tier without the proof gets the weaker line.
        """
        if self.byte_exact and self.quote is Quote.VERBATIM:
            return _BYTE_EXACT_ADVISORY
        return _RECONSTRUCTED_ADVISORY

    def render(self) -> str:
        """Header, advisory, and the text inside a three-backtick fence. 10:629-634."""
        return f"{self.header}\n{self.advisory}\n```text\n{self.text}\n```"

    @property
    def chars(self) -> int:
        """What this block costs the document, structure included. D273's measured quantity."""
        return len(self.render()) + 1


@dataclass(frozen=True, slots=True)
class Pointer:
    """18:754's row: *"One `ow:notseen` or `ow:sent-earlier` row: ~110 characters instead of
    ~4,500."*"""

    doc_uri: str
    pages: tuple[int, ...]
    cites: tuple[str, ...]
    blocks: int
    fetch: str
    reason: Literal["cliffed", "sent_earlier", "truncated"]


@dataclass(frozen=True, slots=True)
class ImpactRow:
    """18:763's row. `ow_open` only, and only when `want_impact` was asked for (10:764)."""

    artifact: str
    artifact_gen: int
    unit: str
    el: str
    kind: str
    verbatim: bool
    doc_gen: int
    older_gen: bool


@dataclass(frozen=True, slots=True)
class LicenceNotice:
    """18:770's row: the tier, the driver, the requirement and the bits it sets."""

    tier: str
    driver: str
    requirement: str
    restriction_bits: int


@dataclass(frozen=True, slots=True)
class Answer:
    """One retrieval, packed and renderable.

    **A dataclass, and 18:544 says it is not one.** D279: `tools/schemagen.py`'s inventory generates
    `schema/answer-v1.json` from this symbol and the reflector takes dataclasses only, so the two
    requirements cannot both hold. The reason 18:544 gives for the non-dataclass -- *"`evidence` is
    an iterator over a pack plan materialised lazily"* -- does not force it: a frozen dataclass
    field
    holds a generator as happily as an attribute does, and the laziness is a property of what is
    assigned, not of how the class was declared.

    The fields here are the ones the DOCUMENT needs. `spend` is `micros` rather than 18:553's
    `Spend`, because `Spend` lives in `omniweave.route` and `tools/layers.toml` forbids core from
    importing it -- the same boundary `omniweave_core.operator.SpendVector` exists to answer. D280.
    """

    state: str
    corpus: str
    generation: int
    freshness: str
    evidence: tuple[RenderedBlock, ...] = ()
    pointers: tuple[Pointer, ...] = ()
    withheld: tuple[Pointer, ...] = ()
    impact: tuple[ImpactRow, ...] = ()
    blocking: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    trailer_extra: tuple[tuple[str, str], ...] = ()
    licence_notices: tuple[LicenceNotice, ...] = ()
    degradations: tuple[str, ...] = ()
    defanged_blocks: int = 0
    instruction_shaped: int = 0
    blocks_matched: int = 0
    docs_matched: int = 0
    spend_micros: int = 0
    scorer_version: int = 1
    surface: Literal["query", "open"] = "query"
    budget: AnswerBudget | None = None
    next_command: str = ""

    @property
    def documents(self) -> tuple[str, ...]:
        """The distinct `doc_uri`s in the rendered evidence, in first-appearance order."""
        seen: dict[str, None] = {}
        for block in self.evidence:
            seen.setdefault(block.doc_uri, None)
        return tuple(seen)


def _status(answer: Answer, max_chars: int) -> str:
    """10:617's status line, with the self-referential `chars=` field held by the sentinel."""
    return (
        f"ow/1 {answer.state} corpus={answer.corpus}@{answer.generation} {answer.freshness} "
        f"blocks={len(answer.evidence)}/{answer.blocks_matched} "
        f"docs={len(answer.documents)}/{answer.docs_matched} "
        f"chars={SUMMARY_SENTINEL}/{max_chars} "
        f"calls={_call_ord(answer)}/{_calls_allowed(answer)} "
        f"spend={answer.spend_micros}µ scorer={answer.scorer_version}"
    )


def _call_ord(answer: Answer) -> int:
    return answer.budget.call_ord if answer.budget else 1


def _calls_allowed(answer: Answer) -> int:
    return answer.budget.calls_allowed if answer.budget else 1


def _evidence(answer: Answer) -> str:
    """The blocks, grouped inside one `<ow:untrusted>` frame. W6.6b owns the frame; D272 owns
    why."""
    body = "\n".join(block.render() for block in answer.evidence)
    return wrap_untrusted(body, corpus=answer.corpus, gen=answer.generation)


_PROVENANCE_COLUMNS: Final[tuple[str, ...]] = (
    "cite",
    "doc",
    "page",
    "addr",
    "kind",
    "quote",
    "trust",
    "method",
    "driver",
    "score",
    "restr",
)
"""10:657's eleven columns, in the document's order."""


def _provenance(answer: Answer, *, collapsed: bool = False) -> str:
    """One row per rendered block, or 10:580's collapse to a count.

    The collapse is a CUT and not a drop: the caller still learns that the rows exist and how many,
    which is the difference between a narrowed answer and a silently different one.
    """
    if collapsed:
        return f"{len(answer.evidence)} rows omitted for room; re-run with a larger `max_chars`."
    header = f"| {' | '.join(_PROVENANCE_COLUMNS)} |"
    rule = "|" + "|".join("---" for _ in _PROVENANCE_COLUMNS) + "|"
    rows = [
        "| "
        + " | ".join(
            (
                block.cite,
                block.doc_uri,
                str(block.page),
                block.addr,
                block.kind + (" ctx" if block.is_context else ""),
                block.quote.name.lower(),
                block.trust,
                block.method,
                block.origin_driver,
                block.score,
                block.restriction,
            )
        )
        + " |"
        for block in answer.evidence
    ]
    return "\n".join([header, rule, *rows])


def _pointer_rows(pointers: Sequence[Pointer]) -> str:
    """10:671-673's `ow:notseen` form: one line of prose, one line carrying the `ow_open` call."""
    lines: list[str] = []
    for pointer in pointers:
        pages = ", ".join(f"p.{page}" for page in pointer.pages)
        cites = ", ".join(pointer.cites)
        lines.append(f"- {pointer.doc_uri} {pages} ({cites}) — matched, below the byte cliff.")
        if pointer.fetch:
            lines.append(f"  `{pointer.fetch}`")
    return "\n".join(lines)


def _sent_earlier(pointers: Sequence[Pointer]) -> str:
    """10:666-668's blockquote, which is charged first and is never droppable."""
    lines: list[str] = []
    for pointer in pointers:
        cites = EN_DASH.join(pointer.cites[:2]) if pointer.cites else ""
        pages = ", ".join(f"p.{page}" for page in pointer.pages)
        lines.append(
            f"> **Already sent earlier in this conversation:** `{pointer.doc_uri}` {cites} "
            f"({pages}) — the content digest is unchanged and the source has not been edited\n"
            f"> since, so that copy is still exact and is not repeated here. Use it from your "
            f"context; do NOT Read this file."
        )
    return "\n".join(lines)


def _impact(rows: Sequence[ImpactRow]) -> str:
    """10:764's form. `(proved)` is printed because a reader cannot tell it from a declaration."""
    lines: list[str] = []
    for row in rows:
        proof = "verbatim (proved)" if row.verbatim else row.kind
        older = "  ⚠ older gen" if row.older_gen else ""
        lines.append(
            f"- `{row.artifact}@{row.artifact_gen}` unit {row.unit}, el {row.el} — {proof}, "
            f"pinned at doc_gen {row.doc_gen}{older}"
        )
    return "\n".join(lines)


def _trailer(answer: Answer, max_chars: int) -> str:
    """The `Verdict` scalars and the budget line. 10:676-686's `key = value` block.

    The key column is left-justified to `_TRAILER_KEY_WIDTH`, which is what makes the `=` signs line
    up in every printed transcript. `budget` carries the second self-referential `chars=` count.
    """
    rows: list[tuple[str, str]] = [("verdict.state", answer.state), *answer.trailer_extra]
    rows.append(("degradations", "[" + ", ".join(answer.degradations) + "]"))
    rows.append(
        (
            "licence_notices",
            "[" + ", ".join(notice.driver for notice in answer.licence_notices) + "]",
        )
    )
    rows.append(
        (
            "defanged_blocks",
            f"{answer.defanged_blocks}   instruction_shaped = {answer.instruction_shaped}",
        )
    )
    deduped = answer.budget.chars_deduped if answer.budget else 0
    rows.append(
        (
            "budget",
            f" {SUMMARY_SENTINEL}/{max_chars} chars · call {_call_ord(answer)} of "
            f"{_calls_allowed(answer)} · dedup saved {deduped:,} chars",
        )
    )
    if answer.next_command:
        rows.append(("next", answer.next_command))
    return "\n".join(f"{key:<{_TRAILER_KEY_WIDTH}}= {value}" for key, value in rows)


_SIMPLE: Final[Mapping[str, Callable[[Answer], str]]] = MappingProxyType(
    {
        "blocking": lambda answer: NEWLINE.join(answer.blocking),
        "related": lambda answer: NEWLINE.join(answer.related),
        "impact": lambda answer: _impact(answer.impact),
        "sent-earlier": lambda answer: _sent_earlier(answer.withheld),
        "notseen": lambda answer: _pointer_rows(answer.pointers),
    }
)
"""The five sections whose body is a function of one field and of nothing else.

A table rather than five more branches in `_body`, for `tools/schemagen.py`'s reason: adding a
section should be one row, and no branch counter should decide what a document contains."""


def _body(answer: Answer, name: str, max_chars: int, *, collapsed: bool) -> str:
    """One section's body, or `""` where the Answer has nothing to put in it.

    An empty body drops the section's MARKER too (see `_assemble`), which is why `ow:related` is
    absent from an Answer with no neighbourhood rather than present and empty. A marker with nothing
    under it is a section a reader would try to interpret.
    """
    if name == "status":
        return _status(answer, max_chars)
    if name == "evidence":
        return _evidence(answer) if answer.evidence else ""
    if name == "provenance":
        return _provenance(answer, collapsed=collapsed) if answer.evidence else ""
    if name == "trailer":
        return _trailer(answer, max_chars)
    return _SIMPLE[name](answer)


def _assemble(
    answer: Answer, present: Sequence[str], collapsed: frozenset[str], max_chars: int
) -> str:
    """The sections in `SECTION_ORDER`, each separated by a blank line.

    10:705's partition depends on this and nothing else: *"every section boundary is a blank line"*,
    which is what makes the eight per-section counts sum to the whole and what lets a tokenizer's
    `\\n\\n` land inside the section above the cut rather than straddling it.
    """
    chunks: list[str] = []
    for spec in SECTIONS:
        if spec.name not in present:
            continue
        body = _body(answer, spec.name, max_chars, collapsed=spec.name in collapsed)
        if not body:
            continue
        chunks.append(f"{spec.marker}\n{body}" if spec.marker else body)
    return "\n\n".join(chunks) + "\n"


def _cut(present: list[str], collapsed: set[str], evidence: list[RenderedBlock]) -> bool:
    """Take one step down 10:579's cut order. Returns whether anything was given up.

    Sections first, in the document's own order, then whole evidence blocks from the END of the
    ranked list -- never from the front, because the front is the answer. The last block is never
    cut: an `ow:evidence` section with a marker and no block is worse than one block over budget,
    and the truncator's caller learns the document did not fit from `AnswerBudget.over_budget`.
    """
    for rank in CUT_ORDER:
        for name in rank:
            if name == "provenance" and name in present and name not in collapsed:
                collapsed.add(name)
                return True
            if name in present:
                present.remove(name)
                return True
    if len(evidence) > 1:
        evidence.pop()
        return True
    return False


def render(
    answer: Answer,
    *,
    max_chars: int = 22_000,
    sections: frozenset[str] | None = None,
) -> str:
    """The Answer document. 18:570's signature, and 10 section 3.5's contract.

    `sections` narrows and cannot reorder -- it is a `frozenset`, so there is no order in it to
    honour -- and it cannot drop a never-dropped section. 18:588 gives that refusal its code.

    The loop is: assemble, measure, cut one thing, repeat. It terminates because every `_cut()` that
    returns `True` removes a section or a block and both are finite, and because the never-dropped
    four and the top-ranked evidence block are never offered to it.

    The two `chars=` counts are substituted LAST, after every other count is already true, and the
    substitution is length-preserving -- so the number printed is the length of the document it is
    printed in.
    """
    if max_chars < 1:
        msg = f"max_chars={max_chars} is not a length"
        raise ValueError(msg)
    present = [
        spec.name
        for spec in SECTIONS
        if answer.surface in spec.surfaces and (sections is None or spec.name in sections)
    ]
    if sections is not None:
        missing = sorted(NEVER_DROPPED - sections)
        if missing:
            msg = (
                f"sections= omits {', '.join(missing)}, which 10:576 charges first and never drops"
            )
            raise UsageError(
                msg,
                symbol="OW_SECTION_NOT_DROPPABLE",
                fix=f"add {missing[0]!r} back to the sections= set, or drop the argument",
            )
    collapsed: set[str] = set()
    evidence = list(answer.evidence)
    while True:
        shown = replace(answer, evidence=tuple(evidence))
        document = _assemble(shown, present, frozenset(collapsed), max_chars)
        if len(document) <= max_chars or not _cut(present, collapsed, evidence):
            break
    return _substitute(document)


def _substitute(document: str) -> str:
    """Replace every `SUMMARY_SENTINEL` with the document's own length, right-aligned in five.

    Length-preserving, so measuring before substituting is measuring the final document. A document
    that already contains the sentinel could not be measured honestly, so that is an error rather
    than a silent mis-substitution -- see the constant.

    **The number printed is the TRUE length, never the budget.** 10:607-609's property test asserts
    that the never-dropped four survive at `max_chars = 1000`, not that the document fits there --
    the status line, `ow:blocking`, `ow:sent-earlier` and `ow:trailer` plus one evidence block can
    be longer than a thousand characters and none of them may go. So an Answer can be over its
    budget, and then `chars=` prints a number above the denominator beside it. Clamping to the
    budget would print exactly the lie 10:590 names, with the truncator's own overrun as the thing
    concealed; `AnswerBudget.over_budget` is the predicate a caller reads for the same fact.
    """
    count = document.count(SUMMARY_SENTINEL)
    stray = document.count("\x00") - count * len(SUMMARY_SENTINEL)
    if stray:
        msg = (
            f"the rendered Answer carries {stray} NUL character(s) outside SUMMARY_SENTINEL; "
            f"the post-truncation count cannot be substituted honestly"
        )
        raise ValueError(msg)
    length = len(document)
    if length > HARD_CEILING:
        msg = f"a rendered Answer of {length} characters is above HARD_CEILING={HARD_CEILING}"
        raise ValueError(msg)
    return document.replace(SUMMARY_SENTINEL, f"{length:>5}")


def sections_of(document: str) -> tuple[str, ...]:
    """The `ow:` section names a rendered document carries, in the order it carries them.

    Here rather than in the test because three surfaces parse an Answer back -- `ow explain`, the
    eval harness and the hook -- and a fourth spelling of this scan is a fourth thing to keep in
    step with `SECTION_ORDER`.
    """
    return tuple(
        line.strip().removeprefix(BOLD).removesuffix(BOLD).removeprefix("ow:")
        for line in document.splitlines()
        if line.startswith(_SECTION_MARKER)
    )


def blocks_of(document: str) -> tuple[str, ...]:
    """The `**<< ... >>**` block headers, in order. The boundary truncation is allowed to cut on."""
    return tuple(line for line in document.splitlines() if line.startswith(_BLOCK_MARKER))


def measure(document: str) -> Mapping[str, int]:
    """Per-section character counts, partitioned the way 10:693-702's table partitions.

    Every boundary is a blank line and the blank line belongs to the section ABOVE it, which is the
    partition 10:704 says *"sums exactly"* -- and which this repository reproduces over the worked
    Answer at 10:617-686, all eight counts and the 3,871 total.
    """
    lines = document.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith(_SECTION_MARKER)]
    names = [
        "status",
        *(
            line.strip().strip(STARS).removeprefix("ow:")
            for line in (lines[index] for index in starts)
        ),
    ]
    bounds = [0, *starts, len(lines)]
    return {
        name: len("".join(lines[a:b]))
        for name, a, b in zip(names, bounds[:-1], bounds[1:], strict=False)
    }


def charged_first(names: Iterable[str] = SECTION_ORDER) -> tuple[str, ...]:
    """The subset of `names` that 10:576 charges first and never drops, in document order."""
    return tuple(name for name in names if name in NEVER_DROPPED)
