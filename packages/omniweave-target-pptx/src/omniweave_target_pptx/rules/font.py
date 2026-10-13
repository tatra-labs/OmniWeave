"""`pptx.font@1`: a font size, weight, spacing and family DrawingML can hold. D790.

ppt-master (`drawingml/utils.py:44-46`, `:312-330`; `text_properties.py:130-139`, `:264-376`):
- a size becomes `sz`, hundredths of a point, `px x 75` rounded, and `sz` runs 100 to 400000,
  1 to 4000 pt; a size is a number above zero in user units, `px` on the attribute being the
  normalize row's warning;
- a weight is `normal`, `bold`, or 100 to 900 in hundreds; `medium` and `semibold` are refused,
  because a named weight between the two is a guess;
- letter spacing becomes `spc`, also `px x 75`, within +/-400000;
- a family list names at least one family, and each entry is non-empty.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["HUNDREDTHS_PER_UNIT", "SIZE_MAX", "SIZE_MIN", "SPACING_MAX", "SPEC", "font"]

RULE: Final = "pptx.font@1"
CODE: Final = "OW_TARGET_FONT_INVALID"
HUNDREDTHS_PER_UNIT: Final = Decimal(75)
"""A user unit is a px, three quarters of a point: 75 hundredths of a point."""
SIZE_MIN: Final = Decimal(100)
SIZE_MAX: Final = Decimal(400_000)
SPACING_MAX: Final = Decimal(400_000)
WEIGHTS: Final = frozenset({"normal", "bold", *(str(w) for w in range(100, 1000, 100))})


def font(ctx: RuleCtx) -> Iterator[Finding]:
    """Size, weight, spacing and family, each within DrawingML's range."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, ("font-size",)):
        size = v.number()
        if size is None or size <= 0:
            yield said(ctx, v, rule=RULE, code=CODE, why="write a number above 0, user units")
        elif not SIZE_MIN <= size * HUNDREDTHS_PER_UNIT <= SIZE_MAX:
            yield said(ctx, v, rule=RULE, code=CODE, why="DrawingML holds 1 to 4000 pt")
    for v in values(ctx, ("font-weight",)):
        if v.settled.strip() not in WEIGHTS:
            yield said(ctx, v, rule=RULE, code=CODE, why="write normal, bold, or 100 to 900 by 100")
    for v in values(ctx, ("letter-spacing",)):
        spacing = v.number()
        if spacing is None:
            yield said(ctx, v, rule=RULE, code=CODE, why="write a decimal number, user units")
        elif abs(spacing * HUNDREDTHS_PER_UNIT) > SPACING_MAX:
            yield said(ctx, v, rule=RULE, code=CODE, why="DrawingML holds +/-4000 pt of spacing")
    for v in values(ctx, ("font-family",)):
        families = [f.strip().strip("'\"").strip() for f in v.settled.split(",")]
        if not all(families):
            yield said(ctx, v, rule=RULE, code=CODE, why="name one family or more, none empty")


SPEC: Final = RuleSpec(RULE, 48, "unit", frozenset({CODE}), font)
