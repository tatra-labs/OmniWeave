"""`pptx.opacity@1`: an opacity is a number from 0 to 1. D790.

ppt-master clamps (`drawingml/utils.py:466-483`); owsvg/1 refuses, because a clamp silently
writes a value the author did not. A percentage on an attribute is the normalize row's warning,
and this rule reads the fraction it leaves, so `150%` is `1.5` here and refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import number, said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["OPACITIES", "SPEC", "opacity"]

RULE: Final = "pptx.opacity@1"
CODE: Final = "OW_TARGET_OPACITY_INVALID"
OPACITIES: Final = ("opacity", "fill-opacity", "stroke-opacity", "stop-opacity", "flood-opacity")


def opacity(ctx: RuleCtx) -> Iterator[Finding]:
    """Each opacity a canonical number in [0, 1]."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, OPACITIES):
        found = number(v.settled)
        if found is None or not 0 <= found <= 1:
            yield said(ctx, v, rule=RULE, code=CODE, why="write a number from 0 to 1")


SPEC: Final = RuleSpec(RULE, 41, "unit", frozenset({CODE}), opacity)
