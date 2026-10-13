"""`lower.media`: an `<image>` as a DrawingML picture, fitted, cropped and clipped. D800.

An `<image>` names a frozen asset by `href="asset-slot:<sha256>"` (`pptx.reference@1`), and
preflight check 2 (`lower._pack`) reads each slot's bytes from the ledger and its size in pixels,
a user unit each, as SVG sizes a raster. Three boxes, each in user units, place it:

- **the viewport** is the `<image>`'s own `x y width height`;
- **the shown image** is its pixels fitted to the viewport by `preserveAspectRatio` (`xMidYMid
  meet` by default): `meet` scales it to fit inside, `slice` to cover, and `none` stretches it,
  each aligned at its `xMin`, `xMid` or `xMax` and `yMin`, `yMid` or `yMax`;
- **what is seen** is the clip's box where `clip-path` names one, else the viewport and the shown
  image's overlap.

The picture is placed at what is seen, and `a:srcRect` crops the shown image to it, in thousandths
of a percent of each side; a negative crop pads, where the seen box runs past the image. So `meet`
crops nothing, `slice` crops what spills past the viewport, and a clip crops to its shape's box.
The clip's shape is the picture's geometry within that box: a circle or an ellipse is `ellipse`,
a rectangle `rect` or `roundRect`, and a polygon or a path a freeform. `clipPathUnits=
"objectBoundingBox"` reads the shape in fractions of the viewport. A picture's `opacity` is its
blip's `a:alphaModFix`, and its filter its effect list (`lower.effects`); `pptx.effect@1` lets it
take a filter or a clip, not both.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final

from pptx.oxml.ns import qn

from omniweave_target_pptx.lower import effects, paint
from omniweave_target_pptx.lower._emit import xfrm
from omniweave_target_pptx.lower._freeform import Op, Point, drawn
from omniweave_target_pptx.lower._geometry import angle, place
from omniweave_target_pptx.lower._style import ALPHA_FULL, declared, element, number
from omniweave_target_pptx.lower.defs import reference
from omniweave_target_pptx.lower.geometry import extent, offset
from omniweave_target_pptx.lower.ids import shape_name
from omniweave_target_pptx.lower.paths import commands
from omniweave_target_pptx.lower.shapes import (
    centre,
    corner,
    preset,
    radius,
    rounding,
    vertices,
)
from omniweave_target_pptx.lower.transform import transform

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._geometry import Placed
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["aspect", "picture"]

Box = tuple[float, float, float, float]
ALIGN: Final = {"Min": 0.0, "Mid": 0.5, "Max": 1.0}
CROP_FULL: Final = 100_000
_ASPECT: Final = re.compile(r"x(Min|Mid|Max)Y(Min|Mid|Max)(?: (meet|slice))?")
_ROUND: Final = frozenset({"svg|circle", "svg|ellipse"})


def picture(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """An `<image>` as `p:pic` (module docstring)."""
    asset = em.assets[reference(node)]
    viewport = (offset(node, "x"), offset(node, "y"), extent(node, "width"), extent(node, "height"))
    shown = _shown(node, viewport, asset.width, asset.height)
    clip = effects.crop_picture(node, em.definitions)
    shape = None if clip is None else effects.crop(clip)
    seen = (
        _overlap(viewport, shown) if shape is None or clip is None else _box(shape, clip, viewport)
    )
    m = transform(chain)
    placed = place(m, *seen)
    picture_id = em.take_id()
    made = element("p:pic")
    properties = element("p:nvPicPr", made)
    element("p:cNvPr", properties, id=str(picture_id), name=shape_name(node, picture_id))
    element("a:picLocks", element("p:cNvPicPr", properties), noChangeAspect="1")
    element("p:nvPr", properties)
    fill = element("p:blipFill", made)
    blip = element("a:blip", fill)
    blip.set(qn("r:embed"), em.embed(asset.blob))
    level = round(paint.alpha(chain) * ALPHA_FULL)
    if level < ALPHA_FULL:
        element("a:alphaModFix", blip, amt=str(level))
    crop = _crop(shown, seen)
    if any(crop.values()):
        element("a:srcRect", fill, **{side: str(v) for side, v in crop.items() if v})
    element("a:fillRect", element("a:stretch", fill))
    body = element("p:spPr", made)
    xfrm(placed, body)
    if shape is None or clip is None:
        preset("rect", 0)(body)
    else:
        _geometry(shape, clip, viewport, seen, placed)(body)
    found = effects.apply(node, em.definitions)
    if found is not None:
        turn = 0.0 if placed.rot else angle(m)
        effects.effect(found, body, scale=m.scale, turn=turn, fill=None)
    em.add(made, placed)


def aspect(node: CarrierNode) -> tuple[float, float, str]:
    """`preserveAspectRatio`: the x and y alignment, 0, 0.5 or 1, and `meet`, `slice` or `none`."""
    stated = (node.attr("preserveAspectRatio") or "").strip()
    if stated == "none":
        return (0.0, 0.0, "none")
    m = _ASPECT.fullmatch(stated)
    if m is None:
        return (0.5, 0.5, "meet")
    return (ALIGN[m[1]], ALIGN[m[2]], m[3] or "meet")


def _shown(node: CarrierNode, viewport: Box, width: int, height: int) -> Box:
    """The image's pixels fitted to the viewport (module docstring)."""
    across, down, mode = aspect(node)
    x, y, w, h = viewport
    if mode == "none" or not (width and height):
        return viewport
    fit = min if mode == "meet" else max
    scale = fit(w / width, h / height)
    shown_w, shown_h = width * scale, height * scale
    return (x + across * (w - shown_w), y + down * (h - shown_h), shown_w, shown_h)


def _overlap(a: Box, b: Box) -> Box:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (left, top, max(0.0, right - left), max(0.0, bottom - top))


def _crop(shown: Box, seen: Box) -> dict[str, int]:
    """`a:srcRect`'s four sides: how far each side of what is seen lies inside the shown image."""
    x, y, w, h = shown
    sx, sy, sw, sh = seen

    def part(length: float, whole: float) -> int:
        return round(length / whole * CROP_FULL) if whole else 0

    return {
        "l": part(sx - x, w),
        "t": part(sy - y, h),
        "r": part(x + w - sx - sw, w),
        "b": part(y + h - sy - sh, h),
    }


def _box(shape: CarrierNode, clip: CarrierNode, viewport: Box) -> Box:
    """The clip shape's box in user units."""
    points = _points(shape, clip, viewport)
    left, top = min(x for x, _ in points), min(y for _, y in points)
    return (left, top, max(x for x, _ in points) - left, max(y for _, y in points) - top)


def _points(shape: CarrierNode, clip: CarrierNode, viewport: Box) -> list[Point]:
    """The points that bound the clip shape, in user units."""
    if shape.tag == "svg|rect":
        x, y = offset(shape, "x"), offset(shape, "y")
        raw = [(x, y), (x + extent(shape, "width"), y + extent(shape, "height"))]
    elif shape.tag in _ROUND:
        cx, cy = centre(shape, "cx"), centre(shape, "cy")
        rx, ry = _radii(shape)
        raw = [(cx - rx, cy - ry), (cx + rx, cy + ry)]
    else:
        raw = [p for _, points in _ops(shape) for p in points]
    return [_user(p, clip, viewport) for p in raw]


def _radii(shape: CarrierNode) -> Point:
    if shape.tag == "svg|circle":
        return (radius(shape), radius(shape))
    return (number(declared(shape, "rx"), 0.0), number(declared(shape, "ry"), 0.0))


def _ops(shape: CarrierNode) -> list[Op]:
    if shape.tag == "svg|polygon":
        first, *rest = vertices(shape)
        return [("M", (first,)), *(("L", (p,)) for p in rest), ("Z", ())]
    return commands(shape)


def _user(point: Point, clip: CarrierNode, viewport: Box) -> Point:
    """A clip point in user units: `objectBoundingBox` reads it in fractions of the viewport."""
    if effects.crop_units(clip) != "objectBoundingBox":
        return point
    x, y, w, h = viewport
    return (x + point[0] * w, y + point[1] * h)


def _geometry(
    shape: CarrierNode, clip: CarrierNode, viewport: Box, seen: Box, placed: Placed
) -> Any:
    """The clip shape as the picture's geometry within what is seen."""
    if shape.tag in _ROUND:
        return preset("ellipse", 0)
    if shape.tag == "svg|rect":
        scale = viewport[2] if effects.crop_units(clip) == "objectBoundingBox" else 1.0
        adj = rounding(corner(shape) * scale, seen[2], seen[3])
        return preset("roundRect" if adj else "rect", adj)
    x, y, w, h = seen

    def local(point: Point) -> tuple[int, int]:
        px, py = _user(point, clip, viewport)
        across = round((px - x) / w * placed.cx) if w else 0
        down = round((py - y) / h * placed.cy) if h else 0
        return (across, down)

    ops: Sequence[tuple[str, tuple[tuple[int, int], ...]]] = [
        (kind, tuple(local(p) for p in points)) for kind, points in _ops(shape)
    ]
    return lambda parent: drawn(parent, ops, placed.cx, placed.cy)
