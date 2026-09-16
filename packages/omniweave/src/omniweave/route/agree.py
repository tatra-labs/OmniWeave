"""`agree.decode_vs_page` -- the free quality channel, and the one label nothing was writing.

16:609 is the cell: *"`agree.decode_vs_page` as the free quality channel,
`TruthKind = "agreement"` plumbing, and the rule that it may **never** populate an accuracy
column"*. 12:1097 is the whole argument in two sentences: *"When a part escalates, **you have
already paid for two independent readings of it**. The normalised edit distance between them
therefore costs zero additional inference, and it lands exactly on the population where the cheap
driver is suspect."*

It is the last cell of P5 because it closes a loop the four before it opened. 05:2990 gives
`ow route propose` its label -- *"the label is `1 - agree.decode_vs_page` on the decisions that
escalated"* -- and W5.5b shipped that fitter over a `route_quality` table nothing wrote; W5.6
shipped the second reading the distance is taken against. FE3 (16-roadmap.md:32) is the ordering
rule and this is its last step here: a mechanism built before the recording it reads ships as a stub
that always reports clean, which is INV-12's failure mode with a green test suite on top.

## NOT COMPUTED is a value, and it is the common case on the population that matters

05:3296 and 05:3136 both print the same line in the worked run -- *"`agree.decode_vs_page` NOT
COMPUTED: it requires DECODE, and DECODE produced nothing"* -- and 12:1104 says what that costs:
*"the signal is unavailable on exactly the population that motivates escalation most"*. On the
plan's own 188-page document, 12 of the 13 escalated parts are scanned exhibits with no text layer
and yield nothing; the one reading is part 177, the known false positive, at **0.94**.

So `agreement()` returns `None` -- never `0.0` -- when either reading is empty. A part whose text
layer is blank has not disagreed with the VLM; it has said nothing, and 05:2122 is the rule in the
registry's own words: *"Uncomputable is None; NEVER a default value."* Scoring the blank half as
total disagreement would write the largest label in the corpus onto every scanned page, and the
fitter reads that label directly.

## Words, not characters, and the reason is a measurement

*"Normalised edit distance"* (05:2251) names neither unit. Upstream picks characters and pays for
it with a C extension: `_collections/olmocr/olmocr/bench/miners/pick_mediod.py:31` is
`fuzz_distance.Levenshtein.normalized_distance(text1, text2)` over `rapidfuzz`, a compiled wheel.
This distribution cannot follow it there -- `rapidfuzz` would be a third-party dependency on the
default install path of the distribution 11-repo-layout.md calls the CLI, which is the edge F33
already has one written question about -- so the choice is which pure-Python distance to take.

Measured here, on generated pages at the sizes the plan's own document runs at, with the same
two-row DP both cases use:

```text
  page       chars   words   character-level   word-level
  half        542      83          39.8 ms        0.9 ms
  one page  1,075     166         176.6 ms        3.3 ms
  dense     2,155     333         741.5 ms       13.8 ms
  full      4,170     666       3,141.4 ms       62.7 ms
```

A character-level distance on one full page costs **more than the 2,400 ms olmOCR call it is
measuring** -- the signal declared FREE would be the most expensive thing in the settle phase. The
word-level one is 50x cheaper and still 52x over its own declared budget, which is D229 and is
filed rather than papered over: 05:2175 registers this key at `1.2 ms`, and 05:2104 makes `est`
*"a DECLARED BUDGET, overwritten into `signals.lock` by `ow conform --bench`. A measured p50 above
2x `est` fails `ow drivers check`."* The registration in `signals.toml` is left at the plan's
number, because a registration edited to match the implementation is a budget that can never fail.

The unit also has to be the same unit everywhere or slices stop being comparable, which is why
`distance()` is generic over sequences and `agreement()` is not: a caller may take a character
distance, and no caller may store one under `norm_edit_agreement`.

## The normaliser folds, and the one fold it cannot reach is a defect

Both readings are folded through `fold_common(text, casefold=False, quotes=True)` -- NFKC, `Cf`
stripped, dashes and the quote families folded, whitespace collapsed -- which is exactly the fold
`omniweave_conform.normalize.normalize_eval` composes (13:1050). It is **not** `normalize_k`, which
casefolds: a VLM that restores the capital a broken text layer lost has read the page better, and a
casefolding comparison would score that as agreement.

What it cannot reach is `strip_md`. `normalize_eval` is `fold_common(strip_md(s), ...)` and
`strip_md` lives in `omniweave_conform`, which `tools/layers.toml` forbids this distribution from
importing; re-implementing it here would be the second copy 13:1072 exists to prevent. The
consequence is measurable and one-directional: `parse.page.olmocr` emits markdown and
`driver.py:424` strips only the leading `#` of a heading, so a `**bold**` run in the VLM reading
disagrees with a text layer that has no asterisks, on every page that has one. D230.

## What this module writes, and the three things it does not

One row per escalated decision, `source = 'agree'`, `metric = 'norm_edit_agreement'` (05:2861),
and nothing else. `audit` is the sampler's and is not scheduled here, `feedback` arrives over
10-interfaces' surface, and `self` comes off the driver's own confidence at settle -- three writers
with three producers, and none of the three has one yet. A writer built for a producer that does
not exist is FE3 facing the other way.

The write is **insert-if-absent**. 05:2653 makes `route_decision.decision_id`
*"'dec_' || sha256_canonical(identity)[:24]"* -- deterministic -- so a re-run of the same
unit under the same policy produces the same decision, and a second agree row for it would be the
same measurement recorded twice. `route_scoreboard`'s `q` CTE counts rows (`SUM(source='agree')`),
so the duplicate would weight that decision twice in its slice's `escalation_divergence` while
adding no evidence. Nothing in the schema forbids it -- there is no `UNIQUE(decision_id, source)` --
which is D233; the discipline is this writer's until there is one.

Specified in 05-ingest-and-routing.md sections 5.1, 8.1 and 12-performance.md section 5.12;
scheduled by 16-roadmap.md:609.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.canonical import canonical
from omniweave_core.errors import RouteError
from omniweave_core.ident import fold_common
from omniweave_core.quality import AGREEMENT, truth_kind_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave.route.ledger import Connection

__all__ = [
    "MAX_CELLS",
    "METRIC",
    "SIGNAL",
    "SOURCE",
    "TRUTH_KIND",
    "UNIT",
    "Agreement",
    "Entry",
    "agreement",
    "distance",
    "record",
    "scoreboard_legend",
    "tokens",
]

SIGNAL: Final[str] = "agree.decode_vs_page"
"""The registered `SignalSpec` key (05:2175). `requires = (DECODE, PAGE)`, `cost_class = FREE`, and
one of the three keys 05:2188 registers *"and read by no shipped rule, deliberately"*."""

SOURCE: Final[str] = "agree"
"""`route_quality.source`. 05:2838 gives this row's cost as `0` and its scoreboard column as
`escalation_divergence`."""

METRIC: Final[str] = "norm_edit_agreement"
"""`route_quality.metric`, the first of the three the DDL's comment names (05:2861). It names the
unit as well as the shape -- an agreement, so `1.0` is identical, and the scoreboard *"reports
1.0 - agreement"* (05:2862)."""

TRUTH_KIND: Final[str] = AGREEMENT
"""Bound from `omniweave_core.quality` rather than spelled, so the string exists once."""

UNIT: Final[str] = "word"
"""What the distance counts, recorded in `detail` on every row. A slice fitted on word distance and
one fitted on character distance are not comparable, and a column that does not say which it holds
is one migration away from silently mixing them."""

MAX_CELLS: Final[int] = 2_000_000
"""The DP budget, past which `agreement()` returns `None` with a reason instead of running.

A quadratic cost with no ceiling is an unbounded pause inside a settle phase: two 20,000-word parts
are 4x10^8 cells, which is minutes. The number is ~0.3 s at the measured 7.1M cells/s and sits far
above any page -- the densest page measured above is 666 words, and the budget admits a pair 1,414
words on each side after trimming. Above it the answer is `None`, which is 05:2122's rule again:
the value was not computed, and no number is the truthful record of that."""

_FIX = "uv run ow route scoreboard"


def tokens(text: str) -> tuple[str, ...]:
    """One reading, folded and split into comparison tokens.

    `fold_common` already collapses whitespace runs to a single U+0020 and strips, so the split is
    on that one character and the join a caller used -- newline, space, or a paragraph break --
    cannot change the result. That property is what lets the caller concatenate a part's blocks
    however it likes and still get the same distance.
    """
    folded = fold_common(text, casefold=False, quotes=True)
    return tuple(folded.split(" ")) if folded else ()


def distance(first: Sequence[object], second: Sequence[object]) -> int:
    """Levenshtein distance over two sequences. Exact, unbounded, and generic on purpose.

    Two rows rather than a matrix, and a common prefix and suffix trimmed first: the trim is exact
    (a shared prefix contributes nothing to an optimal alignment) and it is what makes the near-
    identical pair -- the case this signal exists to detect -- cost close to nothing.

    Generic over `Sequence[object]` so a test can pass strings and get the character distance the
    plan's `rapidfuzz` precedent computes. `agreement()` passes words, and it is the only thing
    that may name the result `norm_edit_agreement`.
    """
    left, right = _trim(first, second)
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for row, item in enumerate(left, 1):
        current = [row]
        append = current.append
        for column, other in enumerate(right, 1):
            append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (item != other),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True)
class Agreement:
    """One part's reading of the signal: the value, the two lengths, and why when there is none.

    `value is None` is a first-class outcome and `reason` is always populated beside it, because
    the two absences the plan distinguishes -- 05:3136's *"it requires DECODE, and DECODE produced
    nothing"* and a comparison too large to run -- are different facts about the part and a caller
    that reports "no reading" for both has lost the one that is a defect.

    `edits`, `decode_words` and `page_words` travel into `detail` rather than being recomputed: a
    stored `0.94` with no `n` behind it is a number whose weight nobody can check, which is INV-19's
    whole subject.
    """

    value: float | None
    edits: int
    decode_words: int
    page_words: int
    reason: str = ""

    def __post_init__(self) -> None:
        if self.value is None:
            if not self.reason:
                raise RouteError(
                    "an uncomputed agreement carries the reason it was not computed",
                    fix=_FIX,
                )
        elif not 0.0 <= self.value <= 1.0:
            raise RouteError(
                f"agree.decode_vs_page = {self.value!r} is outside its registered domain "
                "[0.0, 1.0] (05:2175)",
                fix=_FIX,
            )

    @property
    def computed(self) -> bool:
        return self.value is not None

    @property
    def detail(self) -> str:
        """`route_quality.detail`: canonical JSON, so two runs of the same part diff to nothing."""
        return canonical(
            {
                "edits": self.edits,
                "decode_words": self.decode_words,
                "page_words": self.page_words,
                "signal": SIGNAL,
                "truth_kind": TRUTH_KIND,
                "unit": UNIT,
            }
        ).decode()

    def render(self) -> str:
        if self.value is None:
            return f"{SIGNAL} NOT COMPUTED: {self.reason}"
        return (
            f"{SIGNAL} = {self.value:.4f}  ({self.edits} {UNIT} edit(s) over "
            f"{self.decode_words}/{self.page_words} {UNIT}s; {TRUTH_KIND}, not accuracy)"
        )


def agreement(decode_text: str, page_text: str) -> Agreement:
    """The two readings of one part, as `1 - normalised edit distance` or as a reason there is none.

    Normalised by the longer of the two readings, which is `rapidfuzz`'s
    `Levenshtein.normalized_distance` and therefore the same scale upstream's own mediod miner
    works on. Dividing by the decode side instead would make the score depend on which reading is
    called the reference, and neither of these two is one.
    """
    left = tokens(decode_text)
    right = tokens(page_text)
    if not left or not right:
        empty = "DECODE" if not left else "PAGE"
        return Agreement(
            None,
            0,
            len(left),
            len(right),
            reason=f"{empty} produced no text, so there is one reading and not two",
        )
    cells = _trimmed_cells(left, right)
    if cells > MAX_CELLS:
        return Agreement(
            None,
            0,
            len(left),
            len(right),
            reason=(
                f"the comparison is {cells:,} cells after trimming, above MAX_CELLS "
                f"{MAX_CELLS:,}; the distance was not computed rather than guessed"
            ),
        )
    edits = distance(left, right)
    return Agreement(1.0 - edits / max(len(left), len(right)), edits, len(left), len(right))


def _trim(
    first: Sequence[object], second: Sequence[object]
) -> tuple[Sequence[object], Sequence[object]]:
    """The two sequences with their common prefix and suffix removed. Exact, not an approximation.

    A shared prefix contributes nothing to an optimal alignment and neither does a shared suffix,
    so the distance over the trimmed pair IS the distance over the pair. One home for the loop,
    because `_trimmed_cells()` has to measure exactly the work `distance()` will do.
    """
    start = 0
    limit = min(len(first), len(second))
    while start < limit and first[start] == second[start]:
        start += 1
    end = 0
    while end < limit - start and first[len(first) - 1 - end] == second[len(second) - 1 - end]:
        end += 1
    return first[start : len(first) - end], second[start : len(second) - end]


def _trimmed_cells(first: Sequence[object], second: Sequence[object]) -> int:
    """The DP size `distance()` runs, so the guard measures the work and not the input length.

    Two identical 50,000-word readings trim to nothing and cost nothing; refusing them on their raw
    length would refuse the cheapest comparison there is.
    """
    left, right = _trim(first, second)
    return len(left) * len(right)


@dataclass(frozen=True, slots=True)
class Entry:
    """What `record()` did with one `Agreement`, and why when it did nothing."""

    agreement: Agreement
    written: bool
    reason: str = ""

    def render(self) -> str:
        verb = "wrote" if self.written else f"wrote nothing ({self.reason})"
        return f"{verb}: {self.agreement.render()}"


_EXISTS: Final[str] = (
    "SELECT quality_id FROM route_quality WHERE decision_id = ? AND source = 'agree' LIMIT 1"
)
_INSERT: Final[str] = (
    "INSERT INTO route_quality (decision_id, source, metric, agreement, polarity, ref_driver, "
    "detail, created_at) VALUES (?, 'agree', ?, ?, NULL, NULL, ?, ?)"
)
"""`polarity` and `ref_driver` are written NULL and named rather than omitted. 05:2863-2864 scopes
them -- *"`feedback` only"* and *"`audit` only"* -- and a column list that left them out would let a
later edit add one to this statement without a reviewer seeing which source it belonged to."""


def record(
    conn: Connection,
    *,
    decision_id: str,
    decode_text: str,
    page_text: str,
    created_at: int,
) -> Entry:
    """Compute the agreement for one decision and write it, unless there is nothing to write.

    Two reasons to write nothing, and both are outcomes rather than failures: the signal was NOT
    COMPUTED, or this decision already carries an agree row. Neither raises, because both are
    ordinary states of a settle phase the caller is iterating.

    `created_at` is a parameter and not a clock read. Every other timestamp in this package arrives
    the same way -- a module that called `time.time()` would be one a purity gate has to carve an
    exception for, and 08:280's `Clock` exists so the process that holds the write lock owns the
    one read.

    The connection is `ledger.Connection`, reused rather than re-declared: INV-17 puts the only
    `sqlite3.connect` in `store/sqlite.py`, and one structural protocol for "a connection this
    package was handed" is the whole of what either module needs.
    """
    reading = agreement(decode_text, page_text)
    if not reading.computed:
        return Entry(reading, written=False, reason=reading.reason)
    if conn.execute(_EXISTS, (decision_id,)).fetchall():
        return Entry(
            reading,
            written=False,
            reason=(
                f"{decision_id} already carries an agree row; a decision_id is a digest over the "
                "decision's identity, so a second row is the same measurement counted twice"
            ),
        )
    conn.execute(
        _INSERT,
        (decision_id, METRIC, reading.value, reading.detail, created_at),
    )
    return Entry(reading, written=True)


def scoreboard_legend() -> tuple[str, ...]:
    """The line `ow route scoreboard` prints over its `esc` column. Three sites ask for it.

    01:946, 12:1101 and 13:1459 all say the same thing in the same words -- the signal gets
    *"its own column, headed "Agreement (not accuracy)""* -- and the column the scoreboard
    actually prints is `escalation_divergence`, which is `1.0 - agreement` (05:2862). So the
    heading has to say both, or an operator reads a divergence of 0.06 as an accuracy of 94%.

    A tuple of lines rather than a block string because the command writes line by line, and a
    function rather than a constant because `truth_kind_of()` is the assertion that the mapping
    it prints is the one core holds.
    """
    kind = truth_kind_of(SOURCE)
    return (
        f"esc = escalation_divergence = 1.0 - {SIGNAL} over the decisions that escalated.",
        f"      TruthKind = {kind!r}: AGREEMENT, NOT ACCURACY. Two readings agreeing is not",
        "      evidence that either is right, and this column may never anchor an accuracy",
        "      metric (13:1230). div = audit divergence, and only audit may demote (F23).",
    )
