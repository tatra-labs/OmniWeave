"""`pptx.points@1`: a point list is pairs, enough of them, on a polygon or polyline. D790.

ppt-master: at least 3 pairs for a polygon and 2 for a polyline (`drawingml/paths.py:299-316`).
A pair is two canonical numbers; commas and whitespace separate them, as SVG's grammar allows.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import local, number, said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["SPEC", "points"]

RULE: Final = "pptx.points@1"
CODE: Final = "OW_TARGET_GEOMETRY_INVALID"
PAIRS_MIN: Final = {"svg|polygon": 3, "svg|polyline": 2}
_SEPARATOR: Final = re.compile(r"\s*,\s*|\s+")


def points(ctx: RuleCtx) -> Iterator[Finding]:
    """Each `points` an even list of numbers, with its shape's minimum of pairs."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, ("points",)):
        least = PAIRS_MIN.get(v.node.tag)
        if least is None:
            yield said(ctx, v, rule=RULE, code=CODE, why="points belong to <polygon> or <polyline>")
            continue
        text = v.settled.strip()
        parts = _SEPARATOR.split(text) if text else []
        if any(number(p) is None for p in parts) or len(parts) % 2:
            yield said(ctx, v, rule=RULE, code=CODE, why="write x,y pairs of decimal numbers")
        elif len(parts) // 2 < least:
            yield said(
                ctx,
                v,
                rule=RULE,
                code=CODE,
                why=f"a {local(v.node.tag)} needs {least} points or more",
            )


SPEC: Final = RuleSpec(RULE, 43, "unit", frozenset({CODE}), points)
