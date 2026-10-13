"""`pptx.stroke@1`: a stroke width is a size, and a dash array is dashes and gaps. D790.

ppt-master (`drawingml/utils.py:539-566`): a dash array is `none`, or at least two numbers
separated by spaces or a comma, each dash and gap greater than zero. DrawingML's presets cover
four arrays and a custom dash takes the rest. A width is a size and never negative; `px` on the
attribute is the normalize row's warning.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import number, said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["DASHES_MIN", "SPEC", "stroke"]

RULE: Final = "pptx.stroke@1"
CODE: Final = "OW_TARGET_STROKE_INVALID"
DASHES_MIN: Final = 2
_SEPARATOR: Final = re.compile(r"\s*,\s*|\s+")


def stroke(ctx: RuleCtx) -> Iterator[Finding]:
    """Each stroke width a size; each dash array `none` or two or more positive numbers."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, ("stroke-width",)):
        found = v.number()
        if found is None or found < 0:
            yield said(ctx, v, rule=RULE, code=CODE, why="write a decimal number, 0 or more")
    for v in values(ctx, ("stroke-dasharray",)):
        text = v.settled.strip()
        if text == "none":
            continue
        parts = _SEPARATOR.split(text) if text else []
        found = [number(p) for p in parts]
        if len(parts) < DASHES_MIN or any(n is None or n <= 0 for n in found):
            yield said(
                ctx, v, rule=RULE, code=CODE, why="write none, or two or more numbers above 0"
            )


SPEC: Final = RuleSpec(RULE, 47, "unit", frozenset({CODE}), stroke)
