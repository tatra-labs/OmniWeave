"""`pptx.length@1`: a geometry length is a canonical number in user units. D790.

ppt-master refuses a non-canonical number spelling in a geometry attribute outright, `1e3` or
`+5` (`drawingml/utils.py:440-447`), and requires a size to be non-negative (`:368`). A `px`
suffix on an attribute is the normalize row's warning, since a user unit is a px. In `style`,
where CSS writes lengths with units, `px` is part of the canonical spelling. A gradient's
coordinates are fractions of its box, and `pptx.gradient@1` reads them.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["LENGTHS", "SIZES", "SPEC", "length"]

RULE: Final = "pptx.length@1"
CODE: Final = "OW_TARGET_GEOMETRY_INVALID"
LENGTHS: Final = (
    "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "x1", "y1", "x2", "y2", "dx", "dy",
)  # fmt: skip
SIZES: Final = frozenset({"width", "height", "rx", "ry", "r"})
"""The lengths that are sizes, and so never negative."""
_GRADIENTS: Final = frozenset({"svg|linearGradient", "svg|radialGradient"})


def length(ctx: RuleCtx) -> Iterator[Finding]:
    """Each length a canonical number; each size not negative."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, LENGTHS):
        if v.node.tag in _GRADIENTS:
            continue
        found = v.number()
        if found is None:
            yield said(ctx, v, rule=RULE, code=CODE, why="write a decimal number in user units")
        elif v.prop in SIZES and found < 0:
            yield said(ctx, v, rule=RULE, code=CODE, why=f"a {v.prop} is never negative")


SPEC: Final = RuleSpec(RULE, 42, "unit", frozenset({CODE}), length)
