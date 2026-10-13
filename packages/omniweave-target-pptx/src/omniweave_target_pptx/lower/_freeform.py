"""One freeform: absolute path operations as a DrawingML `a:custGeom`. D796.

`lower.paths` and `lower.shapes`' polygons and polylines both end here. Every point, control
points included, goes through the node's matrix to EMU, so a freeform keeps no rotation or flip
of its own: an affine map carries a line and a Bézier curve exactly, by its points. The shape's
box is the points' box, control points included, which always holds the curve, and the path's
coordinate space is that box in EMU, so a point is written at its offset from the box's corner.
A box with no extent on an axis gets a path one EMU across, so no renderer divides by zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final

from omniweave_target_pptx.lower._geometry import Placed, emu
from omniweave_target_pptx.lower._style import element
from omniweave_target_pptx.lower.transform import transform

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["Op", "Point", "custom", "drawn"]

Point = tuple[float, float]
Op = tuple[str, tuple[Point, ...]]
"""`("M", (p,))`, `("L", (p,))`, `("C", (c1, c2, p))`, `("Q", (c, p))` or `("Z", ())`, absolute."""

STEPS: Final = {"M": "a:moveTo", "L": "a:lnTo", "C": "a:cubicBezTo", "Q": "a:quadBezTo"}
_GUIDES: Final = ("a:avLst", "a:gdLst", "a:ahLst", "a:cxnLst")


def custom(em: Emitter, node: CarrierNode, chain: Chain, ops: Sequence[Op]) -> None:
    """`ops` through the node's matrix as one shape whose box is the points' box."""
    m = transform(chain)
    placed_ops = [
        (kind, tuple((emu(x), emu(y)) for x, y in (m.apply(*p) for p in points)))
        for kind, points in ops
    ]
    every = [p for _, points in placed_ops for p in points]
    left, top = min(x for x, _ in every), min(y for _, y in every)
    placed = Placed(left, top, max(x for x, _ in every) - left, max(y for _, y in every) - top)
    local = [(kind, tuple((x - left, y - top) for x, y in points)) for kind, points in placed_ops]
    em.shape(node, chain, placed, m, lambda parent: drawn(parent, local, placed.cx, placed.cy))


def drawn(
    parent: Any, ops: Sequence[tuple[str, tuple[tuple[int, int], ...]]], width: int, height: int
) -> None:
    """`a:custGeom` of `ops`, each point in EMU from the box's corner, in a box `width` by
    `height` (one EMU across an axis with no extent)."""
    made = element("a:custGeom", parent)
    for tag in _GUIDES:
        element(tag, made)
    element("a:rect", made, l="l", t="t", r="r", b="b")
    path = element("a:path", element("a:pathLst", made), w=str(width or 1), h=str(height or 1))
    for kind, points in ops:
        if kind == "Z":
            element("a:close", path)
            continue
        step = element(STEPS[kind], path)
        for x, y in points:
            element("a:pt", step, x=str(x), y=str(y))
