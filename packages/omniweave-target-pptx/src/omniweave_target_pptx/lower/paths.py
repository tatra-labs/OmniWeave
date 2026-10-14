"""`lower.paths`: a `<path>` as one freeform, its data as absolute operations. D796.

`commands()` reads `d` with the gate's own grammar (`rules.path_data.segments`) and settles it
the way SVG 1.1 section 8.3 draws it:
- a lower-case command is relative to the current point at the start of its segment;
- `M`'s second and later pairs are lines;
- `H` and `V` are lines;
- `S` and `T` reflect the previous segment's control point when that segment was a cubic (`C` or
  `S`) or a quadratic (`Q` or `T`), and use the current point otherwise;
- `Z` returns the pen to the subpath's start, where a command other than a move starts the next
  subpath with an explicit move, since DrawingML's `a:close` leaves no current point to continue
  from.

An arc is cubics. DrawingML's `a:arcTo` has no axis rotation, and a matrix that turns or
stretches the arc moves its axes, so the arc is converted by SVG's implementation notes (F.6.5
and F.6.6): the endpoints are read as a centre and two angles, radii too small to reach are
scaled up until they do, and the sweep is cut into pieces of at most a quarter turn. Each piece is
the cubic `4/3 tan(delta/4)` from its ends, and the last ends at the arc's own end, exactly. An
arc to its own start draws nothing, and an arc with a zero radius is a line (F.6.2).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import TargetError

from omniweave_target_pptx.lower._freeform import Op, Point, custom
from omniweave_target_pptx.rules.path_data import problem, segments

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["commands", "freeform"]

QUARTER: Final = math.pi / 2
_TURN: Final = 2 * math.pi
_SLACK: Final = 1e-9
"""A sweep a hair over a quarter turn by rounding is still one piece."""
Cubic = tuple[Point, Point, Point]


def freeform(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<path>` as one `a:custGeom`."""
    custom(em, node, chain, commands(node))


def commands(node: CarrierNode) -> list[Op]:
    """`d` as absolute moves, lines, cubics, quadratics and closes (module docstring)."""
    d = node.attr("d") or ""
    why = problem(d)
    if why is not None:
        raise TargetError(
            f"<path> at {node.at}: {why}",
            symbol="OW_TARGET_PATH_INVALID",
            fix="ow out check --stage final   # pptx.path@1 names the same problem",
        )
    return absolute(segments(d))


@dataclass
class _Pen:
    """Where the pen is, where its subpath began, and the last control points."""

    ops: list[Op] = field(default_factory=list)
    at: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    cubic: Point | None = None
    quad: Point | None = None
    last: tuple[Point | None, Point | None] = (None, None)
    closed: bool = False

    def point(self, rel: bool, x: float, y: float) -> Point:
        return (self.at[0] + x, self.at[1] + y) if rel else (x, y)

    def mirror(self, control: Point | None) -> Point:
        """`control` reflected through the current point, or the current point."""
        if control is None:
            return self.at
        return (2 * self.at[0] - control[0], 2 * self.at[1] - control[1])

    def draw(self, kind: str, *points: Point) -> None:
        if self.closed:
            self.ops.append(("M", (self.start,)))
            self.closed = False
        self.ops.append((kind, points))
        self.at = points[-1]


def absolute(commands_: Iterable[tuple[str, Sequence[tuple[float, ...]]]]) -> list[Op]:
    """Each command's segments as absolute operations (module docstring)."""
    pen = _Pen()
    for command, runs in commands_:
        key, rel = command.lower(), command.islower()
        if key == "z":
            pen.ops.append(("Z", ()))
            pen.at, pen.closed = pen.start, True
            pen.cubic = pen.quad = None
            continue
        for n, numbers in enumerate(runs):
            pen.last = (pen.cubic, pen.quad)
            pen.cubic = pen.quad = None
            _STEPS[key](pen, rel, numbers, n == 0)
    return pen.ops


def _move(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    p = pen.point(rel, n[0], n[1])
    if not first:
        pen.draw("L", p)
        return
    pen.ops.append(("M", (p,)))
    pen.at = pen.start = p
    pen.closed = False


def _line(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    pen.draw("L", pen.point(rel, n[0], n[1]))


def _across(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    pen.draw("L", (n[0] + (pen.at[0] if rel else 0.0), pen.at[1]))


def _down(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    pen.draw("L", (pen.at[0], n[0] + (pen.at[1] if rel else 0.0)))


def _cubic(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    c1, c2 = pen.point(rel, n[0], n[1]), pen.point(rel, n[2], n[3])
    pen.draw("C", c1, c2, pen.point(rel, n[4], n[5]))
    pen.cubic = c2


def _smooth_cubic(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    c1, c2 = pen.mirror(pen.last[0]), pen.point(rel, n[0], n[1])
    pen.draw("C", c1, c2, pen.point(rel, n[2], n[3]))
    pen.cubic = c2


def _quad(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    control = pen.point(rel, n[0], n[1])
    pen.draw("Q", control, pen.point(rel, n[2], n[3]))
    pen.quad = control


def _smooth_quad(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    control = pen.mirror(pen.last[1])
    pen.draw("Q", control, pen.point(rel, n[0], n[1]))
    pen.quad = control


def _arc_to(pen: _Pen, rel: bool, n: tuple[float, ...], first: bool) -> None:
    del first
    end = pen.point(rel, n[5], n[6])
    if end == pen.at:
        return
    if not (n[0] and n[1]):
        pen.draw("L", end)
        return
    for c1, c2, p in arc(pen.at, end, n[0], n[1], n[2], large=bool(n[3]), sweep=bool(n[4])):
        pen.draw("C", c1, c2, p)


_STEPS: Final[dict[str, Callable[[_Pen, bool, tuple[float, ...], bool], None]]] = {
    "m": _move,
    "l": _line,
    "h": _across,
    "v": _down,
    "c": _cubic,
    "s": _smooth_cubic,
    "q": _quad,
    "t": _smooth_quad,
    "a": _arc_to,
}


def arc(
    start: Point,
    end: Point,
    rx: float,
    ry: float,
    rotation: float,
    *,
    large: bool,
    sweep: bool,
) -> list[Cubic]:
    """SVG's elliptical arc from `start` to `end` as cubics (module docstring)."""
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    half_x, half_y = (start[0] - end[0]) / 2, (start[1] - end[1]) / 2
    x1 = cos_phi * half_x + sin_phi * half_y
    y1 = -sin_phi * half_x + cos_phi * half_y
    rx, ry = abs(rx), abs(ry)
    reach = (x1 / rx) ** 2 + (y1 / ry) ** 2
    if reach > 1:
        rx, ry = rx * math.sqrt(reach), ry * math.sqrt(reach)
    spare = (rx * ry) ** 2 - (rx * y1) ** 2 - (ry * x1) ** 2
    scale = math.sqrt(max(0.0, spare / ((rx * y1) ** 2 + (ry * x1) ** 2)))
    if large == sweep:
        scale = -scale
    cx1, cy1 = scale * rx * y1 / ry, -scale * ry * x1 / rx
    centre = (
        cos_phi * cx1 - sin_phi * cy1 + (start[0] + end[0]) / 2,
        sin_phi * cx1 + cos_phi * cy1 + (start[1] + end[1]) / 2,
    )
    u = ((x1 - cx1) / rx, (y1 - cy1) / ry)
    v = ((-x1 - cx1) / rx, (-y1 - cy1) / ry)
    theta = _angle((1.0, 0.0), u)
    delta = _angle(u, v)
    if not sweep and delta > 0:
        delta -= _TURN
    elif sweep and delta < 0:
        delta += _TURN
    pieces = max(1, math.ceil(abs(delta) / QUARTER - _SLACK))
    step = delta / pieces
    k = 4 / 3 * math.tan(step / 4)

    def on(ux: float, uy: float) -> Point:
        """A point of the unit circle on the arc's ellipse."""
        x, y = rx * ux, ry * uy
        return (centre[0] + cos_phi * x - sin_phi * y, centre[1] + sin_phi * x + cos_phi * y)

    out: list[Cubic] = []
    for i in range(pieces):
        a1, a2 = theta + i * step, theta + (i + 1) * step
        cos1, sin1, cos2, sin2 = math.cos(a1), math.sin(a1), math.cos(a2), math.sin(a2)
        last = end if i == pieces - 1 else on(cos2, sin2)
        out.append(
            (on(cos1 - k * sin1, sin1 + k * cos1), on(cos2 + k * sin2, sin2 - k * cos2), last)
        )
    return out


def _angle(u: Point, v: Point) -> float:
    """The signed angle from `u` to `v`."""
    return math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
