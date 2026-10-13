"""`pptx.canvas@1`: the root's `viewBox` is the slide, inside PowerPoint's bounds and the Brief's
format. D789, ruling 3."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["EMU_PER_UNIT", "SPEC", "UNITS_MAX", "UNITS_MIN", "canvas"]

RULE: Final = "pptx.canvas@1"
CODE: Final = "OW_TARGET_CANVAS_MISMATCH"
EMU_PER_UNIT: Final = 9525
"""One user unit is one CSS px, and a px is 9525 EMU (914400 EMU an inch, 96 px an inch)."""
UNITS_MIN: Final = 914_400 // EMU_PER_UNIT
"""96: PowerPoint's smallest slide side, one inch."""
UNITS_MAX: Final = 51_206_400 // EMU_PER_UNIT
"""5376: PowerPoint's largest slide side, 56 inches."""
_VIEWBOX: Final = re.compile(r"0 0 ([1-9][0-9]*) ([1-9][0-9]*)")
_RATIO: Final = re.compile(r"([1-9][0-9]*):([1-9][0-9]*)")
_LENGTH: Final = re.compile(r"([0-9]+)(?:px)?")


def canvas(ctx: RuleCtx) -> Iterator[Finding]:
    """`canvas.viewbox`: the grammar, the bounds, the root's own geometry, then the Brief."""
    if ctx.doc is None or ctx.unit is None:
        return
    root = ctx.doc.root()
    if root.attr("transform") is not None:
        yield _said(ctx, root, "a transform on the root moves the slide off its canvas")
    raw = root.attr("viewBox")
    m = None if raw is None else _VIEWBOX.fullmatch(raw)
    if m is None:
        yield _said(ctx, root, f"viewBox={raw!r} is not '0 0 W H' in positive integers")
        return
    width, height = int(m[1]), int(m[2])
    for side, value in (("width", width), ("height", height)):
        if not UNITS_MIN <= value <= UNITS_MAX:
            yield _said(
                ctx,
                root,
                f"the viewBox {side} {value} is outside a slide's {UNITS_MIN}-{UNITS_MAX} user "
                "units (1 to 56 inches)",
            )
        declared = root.attr(side)
        if declared is not None and _length(declared) != value:
            yield _said(
                ctx, root, f"{side}={declared!r} scales the slide; the canvas is the viewBox"
            )
    brief = ctx.brief
    stated = None if brief is None else brief.value("canvas", "format")
    if stated is None:
        return
    ratio = _RATIO.fullmatch(stated.strip())
    if ratio is None:
        yield _said(ctx, root, f"the Brief's canvas format {stated!r} is not a W:H ratio")
    elif width * int(ratio[2]) != height * int(ratio[1]):
        yield _said(
            ctx, root, f"the viewBox is {width}x{height}, and the Brief's canvas format is {stated}"
        )


def _length(value: str) -> int | None:
    m = _LENGTH.fullmatch(value.strip())
    return None if m is None else int(m[1])


def _said(ctx: RuleCtx, root: CarrierNode, msg: str) -> Finding:
    return finding(ctx, root, rule=RULE, code=CODE, construct="canvas.viewbox", msg=msg)


SPEC: Final = RuleSpec(RULE, 11, "unit", frozenset({CODE}), canvas)
