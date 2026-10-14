"""`pptx.text.canvas@1`: a text's measured lines stay on the slide. D793.

09 section 12.1's measurement band: "text capacity per positioned line under `measure.py`'s
uharfbuzz shaping — and the rule's `msg` states its model". The model is ppt-master's:
**single-line width per positioned line; vertical wrapping is not modeled.** A DrawingML text box
does not wrap what the IL positioned, so a line measured past the canvas is a line the slide
crops.

- The horizontal extent is the widest line's advance placed by `text-anchor`, inherited:
  `start` at `x`, `middle` centred on it, `end` ending at it. `pptx.text.lines@1` holds every
  line to the text's `x`, so the widest line bounds them all.
- The vertical extent runs from the first baseline less the ascent to the last baseline plus the
  descent. A positioned `<tspan>`'s `y` sets its baseline, and its `dy` moves it.
- A text translated by its own or its ancestors' `transform` is placed by the sum of the
  translations. A text that is rotated or scaled is outside the model and is not measured here.
- A text the estimator cannot measure is the framework's recorded skip (`rules` ruling 12),
  never a pass.

Positions are rounded to whole user units in the message, because a report is compared byte for
byte and `repr(float)` is not portable (09 section 4.4).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import ancestry, finding, number
from omniweave_target_pptx.rules.transform import operations

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["MODEL", "SPEC", "text_canvas"]

RULE: Final = "pptx.text.canvas@1"
CODE: Final = "OW_TARGET_TEXT_OFF_CANVAS"
MODEL: Final = "single-line width per positioned line; vertical wrapping is not modeled"
_VIEWBOX: Final = re.compile(r"0 0 ([1-9][0-9]*) ([1-9][0-9]*)")
_SHIFT: Final = {"start": 0.0, "middle": 0.5, "end": 1.0}


def text_canvas(ctx: RuleCtx) -> Iterator[Finding]:
    """Each measured text's box against the slide's `viewBox`."""
    if ctx.doc is None or ctx.unit is None:
        return
    root = ctx.doc.root()
    canvas = _VIEWBOX.fullmatch(root.attr("viewBox") or "")
    if canvas is None:
        return  # pptx.canvas@1 refuses the slide itself
    width, height = int(canvas[1]), int(canvas[2])
    for text, above in ancestry(root):
        if text.tag != "svg|text":
            continue
        moved = _translation((*above, text))
        x, y = number(text.attr("x") or "0"), number(text.attr("y") or "0")
        if moved is None or x is None or y is None:
            continue
        box = ctx.measure(text)
        if box is None:
            continue
        tx, ty = moved
        left = float(x) + tx - _SHIFT.get(_anchor((*above, text)), 0.0) * box.advance
        right = left + box.advance
        top = float(y) + ty - box.ascent
        bottom = _last_baseline(text, float(y)) + ty + box.descent
        edges = [
            side
            for side, past in (
                ("left", left < 0),
                ("right", right > width),
                ("top", top < 0),
                ("bottom", bottom > height),
            )
            if past
        ]
        if edges:
            yield finding(
                ctx, text, rule=RULE, code=CODE, construct="text.text",
                msg=(
                    f"<text> measures {round(left)}..{round(right)} by "
                    f"{round(top)}..{round(bottom)} on a {width}x{height} slide, past its "
                    f"{' and '.join(edges)} edge ({MODEL})"
                ),
            )  # fmt: skip


def _translation(chain: Sequence[CarrierNode]) -> tuple[float, float] | None:
    """The summed translation of `chain`'s transforms, or `None` when any rotates or scales."""
    tx = ty = 0.0
    for node in chain:
        stated = node.attr("transform")
        if stated is None or node is chain[0]:
            continue  # the slide root's transform is pptx.canvas@1's
        ops = operations(stated)
        if isinstance(ops, str):
            return None
        for name, args in ops:
            if name != "translate":
                return None
            tx += float(args[0])
            ty += float(args[1]) if len(args) > 1 else 0.0
    return tx, ty


def _anchor(chain: Sequence[CarrierNode]) -> str:
    """`text-anchor`, inherited: the nearest node stating it, `start` where none does."""
    for node in reversed(chain):
        stated = node.attr("text-anchor")
        if stated is not None:
            return stated.strip()
    return "start"


def _last_baseline(text: CarrierNode, first: float) -> float:
    """The last positioned line's baseline: each line's `y`, or the line before moved by `dy`."""
    baseline = first
    for child in text.children():
        if child.tag != "svg|tspan":
            continue
        at, moved = child.attr("y"), child.attr("dy")
        if at is not None and (value := number(at)) is not None:
            baseline = float(value)
        if moved is not None and (shift := number(moved)) is not None:
            baseline += float(shift)
    return baseline


SPEC: Final = RuleSpec(
    RULE, 60, "unit", frozenset({CODE}), text_canvas, needs=frozenset({"measure"})
)
