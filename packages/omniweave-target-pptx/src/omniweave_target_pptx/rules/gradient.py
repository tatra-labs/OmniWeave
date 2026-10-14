"""`pptx.gradient@1`: a gradient DrawingML's `a:gradFill` can hold. D790.

ppt-master (`drawingml/utils.py:229-236`, `:1829-1863`, `:2420-2591`):
- a gradient is a definition, a direct child of `<defs>` with a non-empty id;
- it holds two `<stop>`s or more and nothing else, and a stop outside a gradient is refused;
- each stop states its `offset`, a fraction or a percentage within 0 to 1, never decreasing,
  and its `stop-color`;
- a linear gradient's `x1 y1 x2 y2` (default `0 0 1 0`) are fractions of its box within 0 to 1,
  and its two ends differ;
- a radial gradient's `cx cy r` (default `0.5 0.5 0.5`) and focus `fx fy` (default the centre)
  are fractions within 0 to 1, `r` is above zero, and the focus lies inside the circle.

ppt-master lets a linear end overshoot the box by a tenth; owsvg/1 writes the box, because the
canonical form has one spelling.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec
from omniweave_core.out.carrier import style_declarations

from omniweave_target_pptx.rules._common import finding, lineage, number

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["SPEC", "STOPS_MIN", "fraction", "gradient"]

RULE: Final = "pptx.gradient@1"
CODE: Final = "OW_TARGET_GRADIENT_INVALID"
STOPS_MIN: Final = 2
_PERCENT: Final = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?|\.[0-9]+)%\s*")
_HUNDRED: Final = Decimal(100)
_HALF: Final = Decimal("0.5")
_LINEAR: Final = "svg|linearGradient"
_RADIAL: Final = "svg|radialGradient"
_STOP: Final = "svg|stop"
LINEAR_DEFAULTS: Final[Mapping[str, Decimal]] = {
    "x1": Decimal(0),
    "y1": Decimal(0),
    "x2": Decimal(1),
    "y2": Decimal(0),
}
RADIAL_DEFAULTS: Final[Mapping[str, Decimal]] = {"cx": _HALF, "cy": _HALF, "r": _HALF}


def fraction(text: str) -> Decimal | None:
    """A gradient fraction: a canonical number, or a percentage over 100."""
    m = _PERCENT.fullmatch(text)
    if m is not None:
        return Decimal(m[1]) / _HUNDRED
    return number(text)


def gradient(ctx: RuleCtx) -> Iterator[Finding]:
    """Every gradient and every stop, against the structure DrawingML holds."""
    if ctx.doc is None or ctx.unit is None:
        return
    for n, above in lineage(ctx.doc.root()):
        if n.tag == _STOP and above[-1] not in (_LINEAR, _RADIAL):
            yield _said(ctx, n, "def.stop", "a <stop> belongs to a gradient")
        if n.tag not in (_LINEAR, _RADIAL):
            continue
        construct = "def.linear" if n.tag == _LINEAR else "def.radial"
        if above[-1] != "svg|defs":
            yield _said(ctx, n, construct, "a gradient is a direct child of <defs>")
        if not (n.attr("id") or "").strip():
            yield _said(ctx, n, construct, "a gradient has an id for url(#id) to name")
        yield from _stops(ctx, n, construct)
        yield from _coordinates(ctx, n, construct)


def _stops(ctx: RuleCtx, n: CarrierNode, construct: str) -> Iterator[Finding]:
    children = list(n.children())
    if any(c.tag != _STOP for c in children) or len(children) < STOPS_MIN:
        yield _said(ctx, n, construct, "a gradient holds two <stop>s or more and nothing else")
    previous = Decimal(0)
    for stop in (c for c in children if c.tag == _STOP):
        raw = stop.attr("offset")
        offset = None if raw is None else fraction(raw)
        if offset is None or not 0 <= offset <= 1:
            yield _said(ctx, stop, "def.offset", f"offset={raw!r}: write a fraction from 0 to 1")
        elif offset < previous:
            yield _said(ctx, stop, "def.offset", f"offset={raw!r} comes before the stop above it")
        else:
            previous = offset
        declared = {p for p, _ in style_declarations(stop.attr("style") or "")}
        if stop.attr("stop-color") is None and "stop-color" not in declared:
            yield _said(ctx, stop, "def.stop", "a stop states its stop-color")


def _coordinates(ctx: RuleCtx, n: CarrierNode, construct: str) -> Iterator[Finding]:
    defaults = LINEAR_DEFAULTS if n.tag == _LINEAR else RADIAL_DEFAULTS
    names = list(defaults) if n.tag == _LINEAR else [*defaults, "fx", "fy"]
    read: dict[str, Decimal] = {}
    for name in names:
        raw = n.attr(name)
        if raw is None:
            continue
        value = fraction(raw)
        if value is None or not 0 <= value <= 1:
            yield _said(ctx, n, construct, f"{name}={raw!r}: write a fraction from 0 to 1")
            return
        read[name] = value
    at = {**defaults, **read}
    if n.tag == _LINEAR:
        if (at["x1"], at["y1"]) == (at["x2"], at["y2"]):
            yield _said(ctx, n, construct, "the gradient's two ends are one point")
        return
    fx, fy = read.get("fx", at["cx"]), read.get("fy", at["cy"])
    if at["r"] <= 0:
        yield _said(ctx, n, construct, "a radial gradient's r is above 0")
    elif (fx - at["cx"]) ** 2 + (fy - at["cy"]) ** 2 > at["r"] ** 2:
        yield _said(ctx, n, construct, "the focus lies outside the gradient's circle")


def _said(ctx: RuleCtx, n: CarrierNode, construct: str, msg: str) -> Finding:
    return finding(ctx, n, rule=RULE, code=CODE, construct=construct, msg=msg)


SPEC: Final = RuleSpec(RULE, 49, "unit", frozenset({CODE}), gradient)
