"""Affine transforms and EMU: the arithmetic every lowering function shares. D795.

An owsvg/1 user unit is a CSS px, and a px is 9525 EMU. A transform is SVG's `matrix(a b c d e f)`,
composed nearest last: a node's matrix is its ancestors' then its own, the slide root's excluded,
since `pptx.canvas@1` refuses one. The grammar band admits translate, scale, rotate and matrix,
with no skew and no shear (`pptx.transform@1`), so every matrix here is a rotation of a scale and
decomposes exactly.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_target_pptx.lower._style import declared, number
from omniweave_target_pptx.rules.transform import operations

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = [
    "EMU_PER_UNIT",
    "IDENTITY",
    "Matrix",
    "Placed",
    "angle",
    "chain",
    "emu",
    "fitting",
    "place",
    "rotation",
]

EMU_PER_UNIT: Final = 9525
ALIGN: Final = {"Min": 0.0, "Mid": 0.5, "Max": 1.0}
_ASPECT: Final = re.compile(r"x(Min|Mid|Max)Y(Min|Mid|Max)(?: (meet|slice))?")
_SEPARATOR: Final = re.compile(r"[\s,]+")
FULL_TURN: Final = 21_600_000
"""DrawingML's `rot` runs 0 to 21,600,000: a degree is 60,000."""


@dataclass(frozen=True, slots=True)
class Matrix:
    """SVG's `matrix(a b c d e f)`: x' = a x + c y + e, y' = b x + d y + f."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def then(self, inner: Matrix) -> Matrix:
        """`self` applied after `inner`: SVG's `self inner` in one transform list."""
        return Matrix(
            self.a * inner.a + self.c * inner.b,
            self.b * inner.a + self.d * inner.b,
            self.a * inner.c + self.c * inner.d,
            self.b * inner.c + self.d * inner.d,
            self.a * inner.e + self.c * inner.f + self.e,
            self.b * inner.e + self.d * inner.f + self.f,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    @property
    def scale(self) -> float:
        """How much a length grows: the root of the determinant's magnitude."""
        return math.sqrt(abs(self.a * self.d - self.b * self.c))


IDENTITY: Final = Matrix()


def _parsed(text: str) -> Matrix:
    ops = operations(text)
    if isinstance(ops, str):
        return IDENTITY  # pptx.transform@1 refused it; the gate does not pass to here
    out = IDENTITY
    for name, raw in ops:
        args = [float(v) for v in raw]
        if name == "translate":
            step = Matrix(e=args[0], f=args[1] if len(args) > 1 else 0.0)
        elif name == "scale":
            step = Matrix(a=args[0], d=args[1] if len(args) > 1 else args[0])
        elif name == "rotate":
            radians = math.radians(args[0])
            cos, sin = math.cos(radians), math.sin(radians)
            step = Matrix(cos, sin, -sin, cos)
            if len(args) == 3:  # noqa: PLR2004 -- rotate(a, cx, cy)
                cx, cy = args[1], args[2]
                step = Matrix(e=cx, f=cy).then(step).then(Matrix(e=-cx, f=-cy))
        else:
            step = Matrix(*args)
        out = out.then(step)
    return out


def chain(nodes: Sequence[CarrierNode]) -> Matrix:
    """The matrix of `nodes`, outermost first, the slide root's own transform left out. A
    `<use>`'s `x` and `y` move what it clones, and a `<symbol>` maps its `viewBox` into the box
    of the `<use>` before it (D801)."""
    out = IDENTITY
    for n, node in enumerate(nodes):
        stated = node.attr("transform")
        if stated is not None and n:
            out = out.then(_parsed(stated))
        if node.tag == "svg|use":
            moved = Matrix(e=number(declared(node, "x"), 0.0), f=number(declared(node, "y"), 0.0))
            out = out.then(moved)
        elif node.tag == "svg|symbol" and n:
            out = out.then(_viewed(node, nodes[n - 1]))
    return out


def fitting(node: CarrierNode) -> tuple[float, float, str]:
    """`preserveAspectRatio`: the x and y alignment, 0, 0.5 or 1, and `meet`, `slice` or `none`,
    `xMidYMid meet` when unstated or unread."""
    stated = (node.attr("preserveAspectRatio") or "").strip()
    if stated == "none":
        return (0.0, 0.0, "none")
    m = _ASPECT.fullmatch(stated)
    if m is None:
        return (0.5, 0.5, "meet")
    return (ALIGN[m[1]], ALIGN[m[2]], m[3] or "meet")


def _viewed(symbol: CarrierNode, use: CarrierNode) -> Matrix:
    """A `<symbol>`'s `viewBox` fitted into its `<use>`'s `width` and `height`, which default to
    the `viewBox`'s own size; a symbol with no `viewBox` maps nothing."""
    parts = _SEPARATOR.split((symbol.attr("viewBox") or "").strip())
    try:
        left, top, wide, tall = [float(p) for p in parts]
    except ValueError:  # not four numbers
        return IDENTITY
    if not (wide and tall):
        return IDENTITY
    w, h = number(declared(use, "width"), wide), number(declared(use, "height"), tall)
    across, down, mode = fitting(symbol)
    if mode == "none":
        sx, sy = w / wide, h / tall
    else:
        sx = sy = (min if mode == "meet" else max)(w / wide, h / tall)
    return Matrix(
        a=sx, d=sy, e=across * (w - wide * sx) - left * sx, f=down * (h - tall * sy) - top * sy
    )


def emu(value: float) -> int:
    """User units to EMU, rounded to the nearest integer: no `repr(float)` reaches the XML."""
    return round(value * EMU_PER_UNIT)


def angle(m: Matrix) -> float:
    """The matrix's rotation in degrees, as `place()` reads it."""
    return math.degrees(math.atan2(m.b, m.a))


def rotation(degrees: float) -> int:
    """Degrees to DrawingML's `rot`, within one turn."""
    return round(degrees * 60_000) % FULL_TURN


@dataclass(frozen=True, slots=True)
class Placed:
    """A box's place on the slide in EMU: offset, extent, rotation and flips."""

    x: int
    y: int
    cx: int
    cy: int
    rot: int = 0
    flip_h: bool = False
    flip_v: bool = False


def place(m: Matrix, x: float, y: float, w: float, h: float) -> Placed:
    """The box `x y w h` under `m`: scaled, flipped where the scale is negative, then turned about
    its centre, which is where DrawingML turns a shape."""
    sx = math.hypot(m.a, m.b)
    sy = (m.a * m.d - m.b * m.c) / sx if sx else 0.0
    turned = angle(m)
    cx, cy = m.apply(x + w / 2, y + h / 2)
    width, height = w * sx, h * abs(sy)
    return Placed(
        x=emu(cx - width / 2),
        y=emu(cy - height / 2),
        cx=emu(width),
        cy=emu(height),
        rot=rotation(turned),
        flip_v=sy < 0,
    )
