"""`pptx.type.budget@1`: an undeclared type size may stay a one-off, never a pattern. D794.

09 section 12.1's document band: "the third occurrence of an undeclared type size is an error,
the second a warning, the first silent (`RuleCtx.limits["undeclared_size_max"] = 2`, counted
across units in `DocIndex.value_occurrences`)". Section 13.2 gives the drift budget: "a declared
typographic anchor may be used at the anchor or within `±2px`", and "one-off exceptions are fine;
a *pattern* of exceptions means the contract is wrong and must be amended". ppt-master's check 9
is the same budget (`checker.py:813-814`, `:5960-5989`, `:6271-6309`).

- The anchors are the Brief's `## typography` values that are numbers (`body: 20`,
  `title: 44`). A Brief that declares none sets no budget, as ppt-master's check runs only when
  its spec declares sizes.
- A size within 2 user units of an anchor is declared.
- Any other size is counted across the deck by the framework (`omniweave_core.out.rules` ruling
  13): the first occurrence is silent, the next up to the limit a warning, and past it an
  error. The limit is `RuleCtx.limits["undeclared_size_max"]`, 2 unless the check names another.
- The rule needs the Brief, which `ow out check` gives at the final stage, so it runs there.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from omniweave_core.out import Finding, Provenance, RuleSpec, Severity
from omniweave_core.out.rules import TYPE_SIZE

from omniweave_target_pptx.rules._common import number

if TYPE_CHECKING:
    from omniweave_core.out import RuleCtx

__all__ = ["LIMIT", "LIMIT_DEFAULT", "ONE_OFF", "SPEC", "TOLERANCE", "type_budget"]

RULE: Final = "pptx.type.budget@1"
CODE: Final = "OW_TARGET_TYPE_SIZE_UNDECLARED"
LIMIT: Final = "undeclared_size_max"
LIMIT_DEFAULT: Final = 2
TOLERANCE: Final = Decimal(2)
"""09 section 13.2: an anchor "may be used at the anchor or within `±2px`"."""
ONE_OFF: Final = 1
"""An undeclared size's first occurrence, which is silent."""


def type_budget(ctx: RuleCtx) -> Iterator[Finding]:
    """Each undeclared size past its first occurrence, a warning to the limit and an error past."""
    brief = ctx.brief
    if brief is None:
        return
    found = (number(v) for v in brief.sections.get("typography", {}).values())
    anchors = sorted({a for a in found if a is not None})
    if not anchors:
        return
    limit = ctx.limits.get(LIMIT, LIMIT_DEFAULT)
    named = ", ".join(format(a, "f") for a in anchors)
    for value, count in sorted(ctx.index.value_occurrences.get(TYPE_SIZE, {}).items()):
        if count <= ONE_OFF or any(abs(Decimal(value) - a) <= TOLERANCE for a in anchors):
            continue
        yield Finding(
            code=CODE,
            severity=Severity.ERROR if count > limit else Severity.WARNING,
            provenance=Provenance.INTRODUCED,
            rule=RULE,
            unit="",
            construct="text.font-size",
            msg=(
                f"font-size {value} appears {count} times across the deck and is within 2 of no "
                f"typography anchor in the Brief ({named}); past {limit} it needs a named role"
            ),
            fix="ow out check --stage final   # after naming the size in brief.md's ## typography",
        )


SPEC: Final = RuleSpec(RULE, 90, "document", frozenset({CODE}), type_budget, final_only=True)
