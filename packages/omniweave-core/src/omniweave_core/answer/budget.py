"""The five budget tiers, keyed on INDEXED BLOCKS, and the one ceiling every tool shares.

charter.md:6641 homes this file and names its subject in the same breath as its error:
*"three budget layers, ALL TIERED ON INDEXED BLOCKS, not documents: cells are blocks, so a
137-document corpus is 41k blocks or 4M."* The table under it has FIVE rows, not three, and
02-architecture.md:252 and 18-api-sketch.md:1739 both say five; the count in that comment is stale
and the rows are what this module transcribes.

12:403 is the argument for the key: *"ten spreadsheet-heavy documents can be 40k Blocks and land
two tiers up, which is why the tier boundaries are re-keyed onto Block counts (F20)."* A
document-keyed table would give a 4M-cell workbook the same envelope as a four-page memo.

## The table is `config`'s and this module parses it

`BUDGET_TIERS` is not a second literal. 18:1739 declares `serve.packing.tier` a `list[list]` whose
default is the five rows, charter.md:6678 says *"All constants live in omniweave.toml
[serve.packing] WITH THE FIXTURES AS TESTS"*, and `omniweave_core.config.PACKING_TIER` already
carries them. Writing the numbers again here would be two homes for one table and the second one
would be the one nobody edits (INV-21). So `tiers()` reads the config shape -- eight positional
cells, `Scalar`-typed -- and returns typed rows; `BUDGET_TIERS` is `tiers()` over the shipped
default, and an operator's override goes through the same function and the same checks.

## SV4 is checked in the parser, because that is where an operator's table arrives

02:1201 makes monotonicity a startup invariant: *"`[serve.packing] tier` is monotone in
`chars_per_doc` (SV4)"*, and 13:882 makes P-18 the property test -- *"a larger tier never receives
fewer chars/doc"*. `tiers()` refuses a non-monotone table rather than sorting it: a table whose
rows have been reordered is a table whose author meant something, and silently re-sorting it would
serve a tier nobody wrote. The refusal is a `ConfigError` and it names the two rows.

Monotonicity is checked on FOUR columns, not one. The document states it of `chars_per_doc`, which
is the one a reviewer would get wrong; `max_chars`, `max_docs` and `calls` are monotone in the
shipped table for the same reason and a table that inverts any of them gives a larger corpus a
smaller answer. `blocks_below` is checked STRICTLY increasing, because two rows with one threshold
make the second unreachable. The three flag columns are NOT checked: `related`, `pointers` and
`meta_text` are latches that turn on and stay on in the shipped table, but 12:402's argument for
`meta_text` -- *"prose is overhead when one call is the whole story"* -- is about call count and
not about size, so an operator turning one off at the top is expressing a policy rather than an
error.

## `HARD_CEILING` is a ceiling on the table too

18:1729: *"`HARD_CEILING`, one ceiling for every tool. Above the host's ~25,000-char inline cap the
result is externalised to a file the agent must Read back, reintroducing exactly the Read the tool
exists to remove"*, and charter.md:6646 records the shipped bug it prevents -- *"codegraph shipped
15,000 AND 24,000 for one wire"*. A tier row above it is refused here rather than clamped, because
a clamp would make `omniweave.toml` say one number and the trailer print another.

10:478's clamp is the other direction and it is `effective_max_chars()`: *"Clamps **below** the
budget tier's `max_chars`; it can never raise it ... `min(requested, tier.max_chars,
HARD_CEILING)` is the effective value, which the trailer prints. A request above the tier is
honoured at the tier and disclosed, never refused."*

## What the tiers buy, in tokens

10:710 fixes the conversion the whole char-based budget rests on: 3.15 chars/token, so the 500k
tier's 22,000 chars is ~6,980 tokens and `HARD_CEILING` is ~7,620. That number is measured over
the worked Answer at 10:617-686 and this repository re-measures it: the 70 rendered lines are
3,871 characters, and the eight per-section counts in 10:693-702 reproduce exactly. The tiers are
therefore a token budget spelled in characters, which is what makes them tokenizer-free.

Specified in charter.md:6640-6654, 02-architecture.md:252, 10-interfaces.md:478 and 710,
12-performance.md:400 and 18-api-sketch.md:773; scheduled by 16-roadmap.md:662.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.config import PACKING_TIER
from omniweave_core.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_core.config import Scalar

__all__ = [
    "BUDGET_TIERS",
    "HARD_CEILING",
    "MIN_REQUESTABLE_CHARS",
    "TIER_COLUMNS",
    "AnswerBudget",
    "BudgetTier",
    "effective_max_chars",
    "tier_for",
    "tiers",
]

HARD_CEILING: Final[int] = 24_000
"""charter.md:6643, 18:1729. ONE ceiling for every tool, and the width of `SUMMARY_SENTINEL`.

Five decimal digits, which is why 10:594 makes the post-truncation count sentinel *"fixed-width and
right-aligned -- five characters, the decimal width of `HARD_CEILING = 24_000`"*. W6.6c spends that
property; it is recorded here because this is the constant it is a property of."""

MIN_REQUESTABLE_CHARS: Final[int] = 1_000
"""10:476's lower bound on the `max_chars` argument (`1,000-24,000`).

Below it the never-dropped set is the whole document and `ow:evidence` gets nothing, which is the
condition 10:607's property test asserts survives rather than the condition a caller should ask
for. `effective_max_chars()` refuses below it instead of clamping up, because a caller who asked
for 200 characters and got 1,000 was not told."""

TIER_COLUMNS: Final[tuple[str, ...]] = (
    "blocks_below",
    "max_chars",
    "max_docs",
    "chars_per_doc",
    "calls",
    "related",
    "pointers",
    "meta_text",
)
"""18:1739's column order, which is the wire order of every `serve.packing.tier` row."""

_MONOTONE_COLUMNS: Final[tuple[str, ...]] = ("max_chars", "max_docs", "chars_per_doc", "calls")


@dataclass(frozen=True, slots=True)
class BudgetTier:
    """One row of `serve.packing.tier`, typed. 18:1739's eight cells in their wire order.

    `blocks_below` is an EXCLUSIVE upper bound on indexed blocks: a corpus of exactly 5,000 blocks
    is the second tier's, not the first's. The shipped last row carries `sys.maxsize`, which is
    charter.md:6652's `INF` in the only spelling a TOML integer has.
    """

    blocks_below: int
    max_chars: int
    max_docs: int
    chars_per_doc: int
    calls: int
    related: bool
    pointers: bool
    meta_text: bool

    def __post_init__(self) -> None:
        if self.max_chars > HARD_CEILING:
            msg = (
                f"a packing tier declares max_chars={self.max_chars}, above "
                f"HARD_CEILING={HARD_CEILING}"
            )
            raise ConfigError(
                msg,
                fix=f"lower serve.packing.tier's max_chars column to at most {HARD_CEILING}",
            )
        for name in ("blocks_below", "max_chars", "max_docs", "chars_per_doc", "calls"):
            if getattr(self, name) <= 0:
                msg = f"a packing tier declares {name}={getattr(self, name)}, which is not positive"
                raise ConfigError(
                    msg,
                    fix=f"give serve.packing.tier's {name} column a value above zero",
                )


def _int_cell(row: Sequence[Scalar], index: int) -> int:
    """One integer cell, refusing a bool -- `True` is an `int` in Python and not a tier bound."""
    value = row[index]
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"serve.packing.tier column {TIER_COLUMNS[index]!r} is {value!r}, not an integer"
        raise ConfigError(msg, fix=f"write an integer in the {TIER_COLUMNS[index]} column")
    return value


def _bool_cell(row: Sequence[Scalar], index: int) -> bool:
    """One boolean cell. `1` is refused for the reason `True` is: a latch is not a count."""
    value = row[index]
    if not isinstance(value, bool):
        msg = f"serve.packing.tier column {TIER_COLUMNS[index]!r} is {value!r}, not a boolean"
        raise ConfigError(msg, fix=f"write true or false in the {TIER_COLUMNS[index]} column")
    return value


def tiers(rows: Sequence[Sequence[Scalar]] = PACKING_TIER) -> tuple[BudgetTier, ...]:
    """Parse `serve.packing.tier` into typed rows, refusing a table SV4 would not accept.

    Four refusals, each of which is a table an operator could write and none of which a sort would
    repair:

    * a row that is not eight cells, or whose cells are not `[int]*5 + [bool]*3`;
    * `blocks_below` not strictly increasing -- two rows at one threshold make the second
      unreachable, and `tier_for()` would silently never return it;
    * any of `max_chars`, `max_docs`, `chars_per_doc` or `calls` decreasing, which is SV4
      (02:1201) generalised from the one column 13:882 names to the four that carry size;
    * an empty table, because `tier_for()` must return a row for every block count.
    """
    if not rows:
        msg = "serve.packing.tier is empty; there is no tier to serve any corpus from"
        raise ConfigError(msg, fix="restore serve.packing.tier, or remove the key to take five")
    parsed: list[BudgetTier] = []
    for ordinal, row in enumerate(rows):
        if len(row) != len(TIER_COLUMNS):
            msg = (
                f"serve.packing.tier row {ordinal} has {len(row)} cells, not {len(TIER_COLUMNS)} "
                f"({', '.join(TIER_COLUMNS)})"
            )
            raise ConfigError(msg, fix="write all eight columns in every row")
        parsed.append(
            BudgetTier(
                blocks_below=_int_cell(row, 0),
                max_chars=_int_cell(row, 1),
                max_docs=_int_cell(row, 2),
                chars_per_doc=_int_cell(row, 3),
                calls=_int_cell(row, 4),
                related=_bool_cell(row, 5),
                pointers=_bool_cell(row, 6),
                meta_text=_bool_cell(row, 7),
            )
        )
    for ordinal, (lower, upper) in enumerate(itertools.pairwise(parsed)):
        if upper.blocks_below <= lower.blocks_below:
            msg = (
                f"serve.packing.tier row {ordinal + 1} has blocks_below={upper.blocks_below}, "
                f"not above row {ordinal}'s {lower.blocks_below}; it can never be selected"
            )
            raise ConfigError(msg, fix="sort serve.packing.tier by a rising blocks_below")
        for column in _MONOTONE_COLUMNS:
            if getattr(upper, column) < getattr(lower, column):
                msg = (
                    f"serve.packing.tier is not monotone in {column}: row {ordinal} gives "
                    f"{getattr(lower, column)} and row {ordinal + 1} gives "
                    f"{getattr(upper, column)}. SV4: a larger tier may never receive less"
                )
                raise ConfigError(
                    msg,
                    fix=f"raise row {ordinal + 1}'s {column} to at least {getattr(lower, column)}",
                )
    return tuple(parsed)


BUDGET_TIERS: Final[tuple[BudgetTier, ...]] = tiers()
"""charter.md:6647's five rows, parsed from the shipped `serve.packing.tier` default.

Checked at import, which is the earliest moment SV4 can fire and earlier than 02:1201's startup:
a table this module cannot parse is a table no surface can serve from, and finding that out at the
first query rather than at the first import would put a `ConfigError` inside a retrieval."""


def tier_for(
    indexed_blocks: int, table: Sequence[BudgetTier] = BUDGET_TIERS
) -> tuple[int, BudgetTier]:
    """The first row whose `blocks_below` exceeds the corpus's INDEXED BLOCK count.

    Returns `(index, row)` because `AnswerBudget.tier_index` is a field 18:775 prints and a caller
    holding only the row cannot recover it.

    A negative count is a `ValueError` rather than tier 0: blocks are counted, not measured, and a
    negative count is a caller bug that would otherwise be served the smallest envelope and look
    like a small corpus. A count above the last row's threshold takes the last row, which the
    shipped table makes unreachable (`sys.maxsize`) and an operator's table may not.
    """
    if indexed_blocks < 0:
        msg = f"indexed_blocks={indexed_blocks} is negative; a block count cannot be"
        raise ValueError(msg)
    for index, row in enumerate(table):
        if indexed_blocks < row.blocks_below:
            return index, row
    return len(table) - 1, table[-1]


def effective_max_chars(requested: int | None, tier: BudgetTier) -> int:
    """10:479's `min(requested, tier.max_chars, HARD_CEILING)`, and it never raises the tier.

    `None` is the caller who did not ask, and takes the tier. A request above the tier is honoured
    at the tier *and disclosed* (10:480) -- the disclosure is the trailer's `chars=` field, which
    prints this number beside the request, so this function returns the clamp and does not report
    it.

    Below `MIN_REQUESTABLE_CHARS` is a `UsageError`-shaped refusal rather than a clamp; see that
    constant. It is raised as a `ValueError` here because `answer.budget` is called from three
    surfaces and the surface -- not the allocator -- owns the exit code.
    """
    if requested is None:
        return min(tier.max_chars, HARD_CEILING)
    if requested < MIN_REQUESTABLE_CHARS:
        msg = (
            f"max_chars={requested} is below MIN_REQUESTABLE_CHARS={MIN_REQUESTABLE_CHARS}; "
            f"10:476 bounds the argument at 1,000-24,000"
        )
        raise ValueError(msg)
    return min(requested, tier.max_chars, HARD_CEILING)


@dataclass(frozen=True, slots=True)
class AnswerBudget:
    """18:773's eleven fields: which tier applied, and what it spent.

    Two fields are the tier's identity (`tier_index`, `blocks_below`), six are a bound beside its
    use (`max_chars`/`chars_used`, `max_docs`/`docs_used`, `calls_allowed`/`call_ord`), one is the
    ledger's saving (`chars_deduped`) and two are the reserve (`doc_overhead`, `block_overhead`,
    *"charged BEFORE allocation (reserve-then-render)"*).

    The pairs are the point. A budget that carried only `chars_used` would say what was spent and
    not what was available, and 10:588's `chars=` field prints both halves -- `chars= 3871/22000`
    in the worked Answer. Reading one without the other is the `260 results to wade through`
    failure 10:590 names.

    `call_ord` is 1-based, like the fusion ranks (07:1425): the worked Answer's trailer prints
    `call 1 of 3`.
    """

    tier_index: int
    blocks_below: int
    max_chars: int
    chars_used: int
    max_docs: int
    docs_used: int
    calls_allowed: int
    call_ord: int
    chars_deduped: int
    doc_overhead: int
    block_overhead: int

    def __post_init__(self) -> None:
        if self.call_ord < 1:
            msg = f"call_ord={self.call_ord} is not 1-based"
            raise ValueError(msg)
        for name in ("chars_used", "docs_used", "chars_deduped"):
            if getattr(self, name) < 0:
                msg = f"AnswerBudget.{name}={getattr(self, name)} is negative"
                raise ValueError(msg)

    @property
    def over_budget(self) -> bool:
        """`chars_used` above `max_chars`. The truncator's own post-condition, as a predicate.

        It is a property rather than a refusal in `__post_init__` because W6.6c builds an
        `AnswerBudget` from a rendered document and a renderer that overran must be able to SAY so:
        a constructor that refused the over-budget case would leave the surface with nothing to
        report but an exception.
        """
        return self.chars_used > self.max_chars
