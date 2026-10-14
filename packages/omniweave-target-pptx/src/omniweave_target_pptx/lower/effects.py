"""`lower.effects`: a filter's one shadow or glow, and a marker as a line's end. D799.

`pptx.effect@1` holds each to what DrawingML draws: a `<filter>` holds one `<feDropShadow>` or one
`<feGaussianBlur>`, and a `<marker>` holds one shape and ends a `<line>` or a `<path>`.

- **A filter** is the shape's `a:effectLst`: a shape's in `p:spPr`, a group's in `p:grpSpPr`, and
  a text's in each run's `a:rPr`, since a text box's shape is unfilled. `filter` is the node's own
  property, never inherited. Its `stdDeviation` (2 by default) is a Gaussian's, whose visible
  reach is about two deviations, so a blur radius is twice it. Each length grows with the matrix's
  scale.
  - `<feDropShadow>` is an `a:outerShdw`: `dx` and `dy` (2 each by default) are its distance and
    direction, and `flood-color` and `flood-opacity` (black and 1) its colour. SVG reads a filter
    in the shape's own space, so the shadow turns with the shape: `rotWithShape="1"` turns it with
    a preset's `rot`, and a freeform's direction is turned by its matrix (`turn`).
  - `<feGaussianBlur>` is an `a:glow`, DrawingML's one soft halo, of the radius above. Its
    colour is the primitive's `flood-color` where it states one, else the shape's own solid
    fill, settled as its fill is, else black.
- **A marker** is the line's `a:headEnd` (`marker-start`) or `a:tailEnd` (`marker-end`), both
  inherited. Its type is the shape it holds: a circle or an ellipse is `oval`, a four-point
  polygon `diamond`, an unfilled shape `arrow`, and any other `triangle`. Its `markerWidth` is the
  end's length along the line and its `markerHeight` its width across it (3 each by default), in
  stroke widths unless `markerUnits="userSpaceOnUse"`; DrawingML holds three sizes, so up to 2.5
  widths is `sm`, up to 4 `med`, and more `lg`. A DrawingML end points away from its line, as
  `orient="auto-start-reverse"` draws a start; `auto` at the start is drawn the same. `refX` and
  `refY` have no DrawingML equivalent: an end sits at its line's end.
- **A clip** (D800) crops a picture, the one shape `pptx.effect@1` lets take one: `clip-path` is
  the picture's own property, never inherited, and names a `<clipPath>` that holds one shape,
  read in `clipPathUnits`, `userSpaceOnUse` by default (`lower.media`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from omniweave_target_pptx.lower._geometry import emu, rotation
from omniweave_target_pptx.lower._style import (
    colour,
    declared,
    element,
    inherited,
    named,
    number,
)
from omniweave_target_pptx.rules.points import pairs

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._style import Chain

__all__ = [
    "apply",
    "crop",
    "crop_picture",
    "crop_units",
    "effect",
    "end_anchor",
    "end_size",
    "end_units",
    "glow",
    "head",
    "line_end",
    "orient",
    "outer_shadow",
    "radius",
    "shadow_alpha",
    "shadow_colour",
    "tail",
    "units",
]

DEVIATION: Final = 2.0
"""SVG's initial `stdDeviation` for `<feDropShadow>`, and `dx` and `dy`'s."""
REACH: Final = 2.0
"""A Gaussian's visible reach, in deviations: a blur radius is this many of them."""
MARKER_SIZE: Final = 3.0
"""SVG's initial `markerWidth` and `markerHeight`."""
SIZES: Final = ((2.5, "sm"), (4.0, "med"))
"""Up to each bound in stroke widths, that size; past the last, `lg`."""
_BLACK: Final = "#000000"
_DIAMOND: Final = 4
_FILTERS: Final = frozenset({"svg|filter"})
_MARKERS: Final = frozenset({"svg|marker"})
_CLIPS: Final = frozenset({"svg|clipPath"})


def apply(node: CarrierNode, definitions: Mapping[str, CarrierNode]) -> CarrierNode | None:
    """The `<filter>` the node's own `filter` names, or `None`."""
    stated = node.attr("filter")
    if stated is None or stated.strip() == "none":
        return None
    return named(stated, definitions, _FILTERS, what="a <filter>")


def effect(found: CarrierNode, parent: Any, *, scale: float, turn: float, fill: str | None) -> None:
    """A `<filter>`'s one primitive as `a:effectLst` under `parent`."""
    made = element("a:effectLst", parent)
    for primitive in found.children():
        if primitive.tag == "svg|feDropShadow":
            outer_shadow(primitive, made, scale=scale, turn=turn)
        elif primitive.tag == "svg|feGaussianBlur":
            glow(primitive, made, scale=scale, fill=fill)


def outer_shadow(node: CarrierNode, parent: Any, *, scale: float, turn: float) -> None:
    """`<feDropShadow>` as `a:outerShdw` (module docstring)."""
    dx, dy = number(node.attr("dx"), DEVIATION), number(node.attr("dy"), DEVIATION)
    made = element(
        "a:outerShdw",
        parent,
        blurRad=str(emu(radius(node) * scale)),
        dist=str(emu(math.hypot(dx, dy) * scale)),
        dir=str(rotation(math.degrees(math.atan2(dy, dx)) + turn)),
        rotWithShape="1",
    )
    colour(shadow_colour(node) or _BLACK, shadow_alpha(node), made)


def glow(node: CarrierNode, parent: Any, *, scale: float, fill: str | None) -> None:
    """`<feGaussianBlur>` as `a:glow` (module docstring)."""
    made = element("a:glow", parent, rad=str(emu(radius(node) * scale)))
    solid_fill = fill if fill is not None and fill.strip().startswith("#") else None
    colour(shadow_colour(node) or solid_fill or _BLACK, shadow_alpha(node), made)


def radius(node: CarrierNode) -> float:
    """A blur's radius: `REACH` deviations, `stdDeviation` 2 by default."""
    return REACH * number(node.attr("stdDeviation"), DEVIATION)


def shadow_colour(node: CarrierNode) -> str | None:
    """`flood-color`, attribute or `style`, or `None` when unstated."""
    return declared(node, "flood-color")


def shadow_alpha(node: CarrierNode) -> float:
    """`flood-opacity`, attribute or `style`, clamped to 0 to 1."""
    return max(0.0, min(1.0, number(declared(node, "flood-opacity"), 1.0)))


def units(node: CarrierNode) -> str:
    """`primitiveUnits`: `userSpaceOnUse`, the only units `pptx.enum@1` admits."""
    return node.attr("primitiveUnits") or "userSpaceOnUse"


def head(chain: Chain, definitions: Mapping[str, CarrierNode]) -> CarrierNode | None:
    """The `<marker>` `marker-start` names, inherited, or `None`."""
    return _marker(chain, "marker-start", definitions)


def tail(chain: Chain, definitions: Mapping[str, CarrierNode]) -> CarrierNode | None:
    """The `<marker>` `marker-end` names, inherited, or `None`."""
    return _marker(chain, "marker-end", definitions)


def line_end(marker: CarrierNode, parent: Any, tag: str, *, width: float) -> None:
    """A `<marker>` as the line's `a:headEnd` or `a:tailEnd` (module docstring)."""
    element(
        tag,
        parent,
        type=_type(marker),
        w=_bucket(end_size(marker, "markerHeight", width)),
        len=_bucket(end_size(marker, "markerWidth", width)),
    )


def end_size(marker: CarrierNode, side: str, width: float) -> float:
    """`markerWidth` or `markerHeight`, in stroke widths of a line `width` across."""
    size = number(marker.attr(side), MARKER_SIZE)
    if end_units(marker) == "userSpaceOnUse":
        return size / width if width else size
    return size


def end_units(marker: CarrierNode) -> str:
    """`markerUnits`: `strokeWidth` by default, or `userSpaceOnUse`."""
    return (marker.attr("markerUnits") or "strokeWidth").strip()


def orient(marker: CarrierNode) -> str:
    """`orient`: `auto` or `auto-start-reverse`, both drawn pointing away (module docstring)."""
    return (marker.attr("orient") or "auto").strip()


def end_anchor(marker: CarrierNode) -> tuple[float, float]:
    """`refX` and `refY`, which DrawingML cannot hold (module docstring)."""
    return (number(marker.attr("refX"), 0.0), number(marker.attr("refY"), 0.0))


def crop_picture(node: CarrierNode, definitions: Mapping[str, CarrierNode]) -> CarrierNode | None:
    """The `<clipPath>` the node's own `clip-path` names, or `None`."""
    stated = node.attr("clip-path")
    if stated is None or stated.strip() == "none":
        return None
    return named(stated, definitions, _CLIPS, what="a <clipPath>")


def crop(clip: CarrierNode) -> CarrierNode | None:
    """The one shape a `<clipPath>` holds, or `None` for an empty one."""
    return next(iter(clip.children()), None)


def crop_units(clip: CarrierNode) -> str:
    """`clipPathUnits`: `userSpaceOnUse` by default, or `objectBoundingBox`."""
    return (clip.attr("clipPathUnits") or "userSpaceOnUse").strip()


def _marker(chain: Chain, prop: str, definitions: Mapping[str, CarrierNode]) -> CarrierNode | None:
    stated = inherited(chain, prop)
    if stated is None or stated.strip() == "none":
        return None
    return named(stated, definitions, _MARKERS, what="a <marker>")


def _type(marker: CarrierNode) -> str:
    shape = next(iter(marker.children()), None)
    if shape is None:
        return "triangle"
    if shape.tag in ("svg|circle", "svg|ellipse"):
        return "oval"
    if (declared(shape, "fill") or "").strip() == "none":
        return "arrow"
    if shape.tag == "svg|polygon" and len(pairs(shape.attr("points") or "") or ()) == _DIAMOND:
        return "diamond"
    return "triangle"


def _bucket(widths: float) -> str:
    for bound, name in SIZES:
        if widths <= bound:
            return name
    return "lg"
