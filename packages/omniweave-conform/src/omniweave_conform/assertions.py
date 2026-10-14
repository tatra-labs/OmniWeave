"""The text evaluator: `present`, `absent` and `order` against a candidate's text. **D825.**

13-quality.md section 8.1 adopts olmOCR-Bench's record: an assertion is a claim about one page of
one document, run against a tool's output, returning *pass or fail and why*. `evaluable_in` says
which evaluator may run it; the **text** evaluator compares strings in a candidate's text, *"for
cross-tool comparability"*, under `normalize_eval` (section 8.2). This module is that evaluator for
the three string types olmOCR-Bench's `TextPresenceTest` and `TextOrderTest` define:

| type | spec | passes when |
|---|---|---|
| `present` | `text` | the normalised text occurs, within `max_diffs` edits |
| `absent` | `text` | it does not |
| `order` | `before`, `after` | both occur, a `before` match ending before an `after` one starts |

`max_diffs` is the assertion's fuzzy-match budget in edit distance (olmOCR-Bench `BasePDFTest`).
Every verdict carries an explanation, empty on a pass and naming both strings on a failure:
*"A pass/fail with no explanation is a number you cannot debug and therefore cannot improve"*
(13:1026-1028).

## Rulings

1. **Both sides are normalised by `normalize_eval`**, the comparison normaliser, case-sensitive:
   a parser that lower-cases a heading has not reproduced it.
2. **"Occurs within `max_diffs`" is approximate substring matching**: the least Levenshtein
   distance between the needle and any substring of the text (Sellers' algorithm), at most
   `max_diffs`. Insertions, deletions and substitutions each cost one. An empty needle is refused,
   since it occurs everywhere and asserts nothing.
3. **`order` compares the earliest end of `before` with the latest start of `after`**, each over
   every match within budget. A string that does not occur fails the assertion and says which.
4. **A type the text evaluator cannot judge is refused by name**, not passed and not failed:
   `table` and `math` need parsers this module does not hold yet, and `footnote`, `cell_rel`,
   `span`, `cite` and `roundtrip` are `owdoc`-only (13:1003-1013). An assertion whose
   `evaluable_in` is `owdoc` is refused for the same reason.
5. **The explanation of a failure prints both strings**: the asserted one and the nearest text
   found, with its distance. That is the shape section 8.5's fabricated-quote case asserts.

Specified in 13-quality.md sections 8.1 and 8.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import QualityError

from omniweave_conform.normalize import normalize_eval

if TYPE_CHECKING:
    from omniweave_core.store.oweval import Assertion

__all__ = ["OWDOC_ONLY", "TEXT_TYPES", "Match", "TextVerdict", "evaluate_text", "find", "nearest"]

TEXT_TYPES: Final = frozenset({"present", "absent", "order"})
"""The three this evaluator judges (rulings 2-3)."""

OWDOC_ONLY: Final = frozenset({"footnote", "cell_rel", "span", "cite", "roundtrip"})
"""13:1003-1013's `owdoc` rows: a text evaluator has no Layer, Grid, span, cite or address."""

_FIX: Final = "run the assertion through the evaluator its type and evaluable_in name"


@dataclass(frozen=True, slots=True)
class Match:
    """One alignment of the needle with a substring `text[start:end]`, and its edit distance."""

    distance: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TextVerdict:
    """Pass or fail, and why. The explanation is empty on a pass (13:1028)."""

    passed: bool
    explanation: str


def find(needle: str, text: str, max_diffs: int) -> tuple[Match, ...]:
    """Every alignment within `max_diffs`, by end position (ruling 2). Exact at a budget of 0."""
    if not needle:
        raise QualityError("an assertion's string is empty, and occurs everywhere", fix=_FIX)
    if max_diffs == 0:
        out, at = [], text.find(needle)
        while at >= 0:
            out.append(Match(0, at, at + len(needle)))
            at = text.find(needle, at + 1)
        return tuple(out)
    return tuple(m for m in _align(needle, text) if m.distance <= max_diffs)


def nearest(needle: str, text: str) -> Match | None:
    """The least-distance alignment anywhere in `text`, earliest on a tie; `None` for no text."""
    best = None
    for match in _align(needle, text):
        if best is None or match.distance < best.distance:
            best = match
    return best


def evaluate_text(assertion: Assertion, candidate: str) -> TextVerdict:
    """One text-evaluator verdict for `assertion` over `candidate`'s text (rulings 1-5)."""
    kind = assertion.type
    if assertion.evaluable_in == "owdoc" or kind in OWDOC_ONLY:
        raise QualityError(
            f"assertion {assertion.assertion_id} ({kind}) is owdoc-only; the text evaluator "
            "cannot judge it",
            fix=_FIX,
        )
    if kind not in TEXT_TYPES:
        raise QualityError(
            f"assertion {assertion.assertion_id}: the text evaluator does not judge {kind!r} yet",
            fix=_FIX,
        )
    text = normalize_eval(candidate)
    budget = assertion.max_diffs
    spec = assertion.spec
    if kind == "order":
        return _order(str(spec["before"]), str(spec["after"]), text, budget)
    needle = normalize_eval(str(spec["text"]))
    found = find(needle, text, budget)
    if kind == "present":
        if found:
            return TextVerdict(True, "")
        return TextVerdict(False, f"present {needle!r} not found: {_nearest_words(needle, text)}")
    if not found:
        return TextVerdict(True, "")
    first = found[0]
    return TextVerdict(
        False,
        f"absent {needle!r} occurs as {text[first.start : first.end]!r} at distance "
        f"{first.distance} <= max_diffs {budget}",
    )


def _order(before: str, after: str, text: str, budget: int) -> TextVerdict:
    """Ruling 3: the earliest end of `before` against the latest start of `after`."""
    a, b = normalize_eval(before), normalize_eval(after)
    first, second = find(a, text, budget), find(b, text, budget)
    if not first:
        return TextVerdict(False, f"order: before {a!r} not found: {_nearest_words(a, text)}")
    if not second:
        return TextVerdict(False, f"order: after {b!r} not found: {_nearest_words(b, text)}")
    earliest_end = min(m.end for m in first)
    latest_start = max(m.start for m in second)
    if earliest_end <= latest_start:
        return TextVerdict(True, "")
    return TextVerdict(
        False,
        f"order: {a!r} first ends at {earliest_end}, after {b!r} last starts at {latest_start}",
    )


def _nearest_words(needle: str, text: str) -> str:
    """Ruling 5: the nearest text, quoted, with its distance."""
    best = nearest(needle, text)
    if best is None:
        return "the candidate has no text"
    return f"nearest {text[best.start : best.end]!r} at distance {best.distance}"


def _align(needle: str, text: str) -> list[Match]:
    """Sellers' approximate substring matching: one best alignment ending at each position."""
    m = len(needle)
    prev = list(range(m + 1))
    prev_start = [0] * (m + 1)
    out = []
    for j in range(1, len(text) + 1):
        char = text[j - 1]
        cur = [0] * (m + 1)
        cur_start = [j] * (m + 1)
        for i in range(1, m + 1):
            options = (
                (prev[i - 1] + (needle[i - 1] != char), prev_start[i - 1]),
                (prev[i] + 1, prev_start[i]),
                (cur[i - 1] + 1, cur_start[i - 1]),
            )
            cur[i], cur_start[i] = min(options, key=lambda o: (o[0], -o[1]))
        out.append(Match(cur[m], cur_start[m], j))
        prev, prev_start = cur, cur_start
    return out
