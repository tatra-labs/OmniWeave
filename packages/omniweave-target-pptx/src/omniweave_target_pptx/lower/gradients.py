"""`lower.gradients`: a `url(#id)` paint naming a gradient, as DrawingML's `a:gradFill`. D798.

`pptx.gradient@1` holds a gradient to what `a:gradFill` can draw: stops in order, coordinates that
are fractions of the shape's box (`gradientUnits="objectBoundingBox"`, the only units it admits),
and a focus inside a radial's circle.

- **A linear gradient** is `a:lin` with `scaled="1"`, whose angle is read in the unit box and
  stretched with the shape, as SVG stretches a box's gradient. DrawingML runs a linear gradient
  across the whole box along its angle, and SVG runs it from `(x1, y1)` to `(x2, y2)`, so each
  stop's offset is moved to where it falls on DrawingML's run: the two ends are projected onto the
  angle, and an offset `o` sits at `t1 + o (t2 - t1)` of the box's own projection.
- **A radial gradient** is `a:path path="circle"`, whose focus is `a:fillToRect` at `(fx, fy)`.
  DrawingML's circle runs from the focus to the box's edge, so a stop at offset `o` is placed `o x
  2r` of that run: `r = 0.5`, the default, maps one to one, and a stop past the edge is clamped to
  it.
- **A stop** is an `a:gs` of its `stop-color`, with an `a:alpha` of its `stop-opacity` times the
  shape's own alpha (`lower.paint`). Its position is in thousandths of a percent.

`rotWithShape="1"` turns the gradient with a preset shape's `rot`. A freeform keeps no turn of its
own (`_freeform`), so its linear angle is turned by the matrix's rotation instead (`turn`).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Final

from omniweave_target_pptx.lower._geometry import rotation
from omniweave_target_pptx.lower._style import colour, declared, element, number
from omniweave_target_pptx.rules.gradient import fraction

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = [
    "focus",
    "linear",
    "position",
    "radial",
    "stop",
    "stop_alpha",
    "stop_colour",
    "units",
]

POSITION_FULL: Final = 100_000
"""`a:gs`'s `pos` and `a:fillToRect`'s edges are thousandths of a percent."""
STOP: Final = "svg|stop"
_LINEAR_ENDS: Final = (("x1", 0.0), ("y1", 0.0), ("x2", 1.0), ("y2", 0.0))
_BLACK: Final = "#000000"


def linear(node: CarrierNode, alpha: float, parent: Any, *, turn: float = 0.0) -> None:
    """A `<linearGradient>` as `a:gradFill` with `a:lin` (module docstring)."""
    x1, y1, x2, y2 = (_coordinate(node, name, default) for name, default in _LINEAR_ENDS)
    theta = math.atan2(y2 - y1, x2 - x1)
    across, down = math.cos(theta), math.sin(theta)
    corners = (0.0, across, down, across + down)
    low, high = min(corners), max(corners)
    start, end = x1 * across + y1 * down, x2 * across + y2 * down
    made = element("a:gradFill", parent, rotWithShape="1")
    stops = element("a:gsLst", made)
    for s in _stops(node):
        stop(s, alpha, stops, (start + position(s) * (end - start) - low) / (high - low))
    element("a:lin", made, ang=str(rotation(math.degrees(theta) + turn)), scaled="1")


def radial(node: CarrierNode, alpha: float, parent: Any) -> None:
    """A `<radialGradient>` as `a:gradFill` with a circle path (module docstring)."""
    radius = _coordinate(node, "r", 0.5)
    fx, fy = focus(node)
    made = element("a:gradFill", parent, rotWithShape="1")
    stops = element("a:gsLst", made)
    for s in _stops(node):
        stop(s, alpha, stops, position(s) * 2 * radius)
    path = element("a:path", made, path="circle")
    element(
        "a:fillToRect",
        path,
        l=str(_part(fx)),
        t=str(_part(fy)),
        r=str(_part(1 - fx)),
        b=str(_part(1 - fy)),
    )


def stop(node: CarrierNode, alpha: float, parent: Any, at: float) -> None:
    """One `a:gs` at `at`, 0 to 1 of the run, its colour at its opacity times `alpha`."""
    made = element("a:gs", parent, pos=str(_part(at)))
    colour(stop_colour(node), stop_alpha(node) * alpha, made)


def position(node: CarrierNode) -> float:
    """A stop's `offset`, a fraction or a percentage, 0 when unstated."""
    found = fraction(node.attr("offset") or "0")
    return 0.0 if found is None else float(found)


def stop_colour(node: CarrierNode) -> str:
    """`stop-color`, attribute or `style`, SVG's black when unstated."""
    return declared(node, "stop-color") or _BLACK


def stop_alpha(node: CarrierNode) -> float:
    """`stop-opacity`, attribute or `style`, clamped to 0 to 1."""
    return max(0.0, min(1.0, number(declared(node, "stop-opacity"), 1.0)))


def focus(node: CarrierNode) -> tuple[float, float]:
    """A radial's `(fx, fy)`, each its centre's `cx` or `cy` when unstated."""
    cx, cy = _coordinate(node, "cx", 0.5), _coordinate(node, "cy", 0.5)
    return (_coordinate(node, "fx", cx), _coordinate(node, "fy", cy))


def units(node: CarrierNode) -> str:
    """`gradientUnits`: `objectBoundingBox`, the only units `pptx.enum@1` admits."""
    return node.attr("gradientUnits") or "objectBoundingBox"


def _stops(node: CarrierNode) -> list[CarrierNode]:
    return [child for child in node.children() if child.tag == STOP]


def _coordinate(node: CarrierNode, name: str, default: float) -> float:
    found = fraction(node.attr(name) or "")
    return default if found is None else float(found)


def _part(share: float) -> int:
    """`share`, 0 to 1, in thousandths of a percent, clamped to the run."""
    return round(max(0.0, min(1.0, share)) * POSITION_FULL)
