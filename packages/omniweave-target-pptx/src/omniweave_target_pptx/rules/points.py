"""`pptx.points@1`: a point list is pairs, enough of them, on a polygon or polyline. D790.

ppt-master: at least 3 pairs for a polygon and 2 for a polyline (`drawingml/paths.py:299-316`).
A pair is two canonical numbers; commas and whitespace separate them, as SVG's grammar allows.
D796: `pairs()` is that grammar, read by this rule and by `lower.shapes:vertices`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import local, number, said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["SPEC", "pairs", "points"]

RULE: Final = "pptx.points@1"
CODE: Final = "OW_TARGET_GEOMETRY_INVALID"
PAIRS_MIN: Final = {"svg|polygon": 3, "svg|polyline": 2}
_SEPARATOR: Final = re.compile(r"\s*,\s*|\s+")


def pairs(text: str) -> list[tuple[float, float]] | None:
    """`text` as x,y pairs, or `None` when it is not an even list of canonical numbers."""
    stripped = text.strip()
    parts = _SEPARATOR.split(stripped) if stripped else []
    numbers = [number(p) for p in parts]
    if any(n is None for n in numbers) or len(numbers) % 2:
        return None
    floats = [float(n) for n in numbers if n is not None]
    return list(zip(floats[::2], floats[1::2], strict=True))


def points(ctx: RuleCtx) -> Iterator[Finding]:
    """Each `points` an even list of numbers, with its shape's minimum of pairs."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, ("points",)):
        least = PAIRS_MIN.get(v.node.tag)
        if least is None:
            yield said(ctx, v, rule=RULE, code=CODE, why="points belong to <polygon> or <polyline>")
            continue
        found = pairs(v.settled)
        if found is None:
            yield said(ctx, v, rule=RULE, code=CODE, why="write x,y pairs of decimal numbers")
        elif len(found) < least:
            yield said(
                ctx,
                v,
                rule=RULE,
                code=CODE,
                why=f"a {local(v.node.tag)} needs {least} points or more",
            )


SPEC: Final = RuleSpec(RULE, 43, "unit", frozenset({CODE}), points)
