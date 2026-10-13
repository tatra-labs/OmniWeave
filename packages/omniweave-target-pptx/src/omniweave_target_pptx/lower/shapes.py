"""`lower.shapes`: rectangles, ellipses and lines as DrawingML preset shapes. D795.

- **A rectangle** is `rect`, or `roundRect` when it states `rx` or `ry`. DrawingML rounds every
  corner alike, by `adj`, the radius as a share of the shorter side in thousandths of a percent,
  which SVG caps at half the side; the larger of `rx` and `ry` is the radius.
- **A circle or an ellipse** is `ellipse`, its box the centre less and plus each radius.
- **A line** is `line`, its two ends taken through the matrix: the box spans them, and a flip
  says which way the line runs across it. A line has no fill, and draws nothing without a
  stroke, as SVG's does.

A preset shape keeps its own box and takes the matrix as `_geometry.place` decomposes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave_target_pptx.lower._geometry import Placed, emu, place
from omniweave_target_pptx.lower._style import declared, element, number
from omniweave_target_pptx.lower.geometry import extent, offset
from omniweave_target_pptx.lower.transform import transform

if TYPE_CHECKING:
    from collections.abc import Callable

    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["centre", "corner", "ellipse", "endpoint", "line", "radius", "rect"]

_ADJ_FULL: Final = 100_000
_ADJ_MAX: Final = 50_000
"""A radius of half the shorter side: SVG's own cap on `rx` and `ry`."""


def corner(node: CarrierNode) -> float:
    """`rx` and `ry`: the larger, 0 when neither is stated."""
    return max(number(declared(node, "rx"), 0.0), number(declared(node, "ry"), 0.0))


def centre(node: CarrierNode, name: str) -> float:
    """`cx` or `cy`: a circle's or an ellipse's centre on its axis."""
    return number(declared(node, name), 0.0)


def radius(node: CarrierNode) -> float:
    """`r`: a circle's radius."""
    return number(declared(node, "r"), 0.0)


def endpoint(node: CarrierNode, name: str) -> float:
    """`x1`, `y1`, `x2` or `y2`: one end of a line."""
    return number(declared(node, name), 0.0)


def rect(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<rect>` as `rect` or `roundRect`."""
    x, y = offset(node, "x"), offset(node, "y")
    w, h = extent(node, "width"), extent(node, "height")
    m = transform(chain)
    r = corner(node)
    short = min(w, h)
    adj = min(round(r / short * _ADJ_FULL), _ADJ_MAX) if r and short else 0
    em.shape(node, chain, place(m, x, y, w, h), m, _preset("roundRect" if adj else "rect", adj))


def ellipse(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<circle>` or an `<ellipse>` as `ellipse`."""
    cx, cy = centre(node, "cx"), centre(node, "cy")
    if node.tag == "svg|circle":
        rx = ry = radius(node)
    else:
        rx, ry = number(declared(node, "rx"), 0.0), number(declared(node, "ry"), 0.0)
    m = transform(chain)
    em.shape(node, chain, place(m, cx - rx, cy - ry, 2 * rx, 2 * ry), m, _preset("ellipse", 0))


def line(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<line>` as `line`, its ends through the matrix."""
    m = transform(chain)
    x1, y1 = m.apply(endpoint(node, "x1"), endpoint(node, "y1"))
    x2, y2 = m.apply(endpoint(node, "x2"), endpoint(node, "y2"))
    placed = Placed(
        x=emu(min(x1, x2)),
        y=emu(min(y1, y2)),
        cx=emu(abs(x2 - x1)),
        cy=emu(abs(y2 - y1)),
        flip_h=x2 < x1,
        flip_v=y2 < y1,
    )
    em.shape(node, chain, placed, m, _preset("line", 0), filled=False)


def _preset(name: str, adj: int) -> Callable[[Any], None]:
    def geometry(parent: Any) -> None:
        made = element("a:prstGeom", parent, prst=name)
        guides = element("a:avLst", made)
        if adj:
            element("a:gd", guides, name="adj", fmla=f"val {adj}")

    return geometry
