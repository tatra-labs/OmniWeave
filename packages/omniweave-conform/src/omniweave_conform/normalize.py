"""The evaluator's comparison normaliser -- the SECOND one, and the argument for why it exists.

13-quality.md:1054-1063 prints this module. The obvious move is to reuse `normalize_k`, and
13:1031-1049 spends a section on why it is wrong:

* `normalize_k()` is the **grounding** normaliser -- NFKC plus casefold plus the `Cf`, soft-hyphen,
  dash and whitespace operations 06-structure-extraction.md section 1.7 enumerates once. It
  casefolds, "which is correct for grounding a quote and wrong for a benchmark: a parser that
  lower-cases every heading would score identically to one that does not."
* `nfc()` is INV-10's **proof** normaliser, and is not this either. Borrowing it for the evaluator
  "would score a parser that emitted a curly quote where the reference has a straight one as
  wrong".

"The evaluator needs the fold between them, and that is the only reason it exists." So
`normalize_eval` folds MORE than `nfc` (it maps the quote families NFKC leaves alone) and LESS than
`normalize_k` (it does not casefold).

## It is a composition, not a second implementation

13:1050-1051 is explicit: "the evaluator gets its own entry point, and it is a **composition rather
than a second implementation**". `fold_common` lives in `omniweave_core.ident` beside `normalize_k`
and holds the shared table -- `Cf`, dashes, whitespace, NFKC -- and this module imports it rather
than re-listing it. 13:1072-1075 names the failure that rule prevents: "A dash added to one is added
to both -- which is the failure the collection actually exhibits, where two normalisers drift and a
comparison starts depending on which one ran."

## The three rules that follow, and each is a gate rather than a convention

1. **The owdoc evaluator uses `normalize_k` and never `normalize_eval`** (13:1069-1071). A Block's
   `text` contains no `<`-delimited markup by construction, "so there is nothing for `strip_md` to
   do and running it would only mask a serializer that emitted markup into `text`".
2. **The dash, `Cf` and whitespace table has one home**, and it is `fold_common`.
3. **The difference is asserted, not assumed** (13:1076-1079). `Q-G23` feeds case-varied,
   markup-varied strings through both and asserts `normalize_eval` is case-sensitive and
   `normalize_k` is not. "Two normalisers that quietly converge are one normaliser with two names."
   `test_conform_normalize.py` is that property.

Specified in 13-quality.md section 8.2.
"""

from __future__ import annotations

import re
from typing import Final

from omniweave_core.ident import fold_common

__all__ = ["normalize_eval", "strip_md"]

_BR: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
"""olmOCR-Bench `tests.py:47-81`: `<br>` and `<br/>` become a space."""

_PAIRED: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\*\*(?!\s)((?:(?!\*\*).)+?)(?<!\s)\*\*"),
    re.compile(r"__(?!\s)((?:(?!__).)+?)(?<!\s)__"),
    re.compile(r"<b>(.+?)</b>", re.IGNORECASE),
    re.compile(r"<i>(.+?)</i>", re.IGNORECASE),
    re.compile(r"(?<!\*)\*(?!\s|\*)((?:(?!\*).)+?)(?<!\s)\*(?!\*)"),
    re.compile(r"(?<!_)_(?!\s|_)((?:(?!_).)+?)(?<!\s)_(?!_)"),
)
r"""The six PAIRED emphasis forms olmOCR-Bench strips: `**bold**`, `__bold__`, `<b>`, `<i>`,
`*ital*` and `_ital_`.

**Paired**, which is the load-bearing word in 13:1055-1057: "PAIRED ... stripped (paired, so
`**a \n\n b**` is not matched)". TWO mechanisms make that sentence true and both are here:

* **No `re.DOTALL`.** `.` does not cross a newline, so a delimiter pair separated by a blank
  line cannot match at all. This is what the plan's own worked example turns on, and an
  earlier draft of this tuple set `DOTALL` and failed exactly that one case.
* **The `(?!\s)` and `(?<!\s)` guards.** A delimiter followed by whitespace, or preceded by
  it at the close, is a literal asterisk in prose rather than an emphasis marker, and
  stripping it would silently delete a character the reference text contains -- scoring a
  parser wrong for reproducing its input faithfully.

**Intra-word `_` IS stripped**, so `snake_case_name` folds to `snakecasename`. That is not
CommonMark, which requires `_` emphasis to sit at a word boundary, and it is left alone on
purpose: 13:1054 says "olmOCR-Bench tests.py:47-81, exactly", and the evaluator applies this
function to BOTH sides of every comparison, so a fold that is wrong in the same way on both
sides changes no verdict. If this ever grows a second caller that folds only one side, the
word-boundary guard is the first thing to add and this paragraph is the note saying so."""


def strip_md(text: str) -> str:
    """Markdown emphasis and `<br>` removed, per olmOCR-Bench `tests.py:47-81`, exactly.

    Applied repeatedly until it reaches a fixed point, because emphasis nests: `**bold *and
    italic* **` needs two passes and a single pass would leave the inner pair. Bounded, so a
    pathological input cannot spin here.
    """
    out = _BR.sub(" ", text)
    for _ in range(4):
        before = out
        for pattern in _PAIRED:
            out = pattern.sub(r"\1", out)
        if out == before:
            break
    return out


def normalize_eval(text: str) -> str:
    """The text evaluator's comparison normaliser. **NOT `normalize_k`: no casefold.**

    Plus the quote table NFKC does not perform: the three single-quote characters fold to `'` and
    the three double ones to `"`. `fold_common(..., quotes=True, casefold=False)` is where both of
    those live, and this function is the composition 13:1050-1063 specifies and nothing more.
    """
    return fold_common(strip_md(text), quotes=True, casefold=False)
