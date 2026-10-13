"""`lower.paint`: a shape's fill and line paint, and the alpha down its chain. D795, D798.

SVG's initial `fill` is black and its initial `stroke` is none. `fill-opacity` and
`stroke-opacity` inherit, and `opacity` multiplies down the chain (`_style`). Each opacity is
clamped to 0 to 1 before it composes, as SVG clamps every opacity property, so a product is
always a level `a:alpha` can hold.

D798: a `url(#id)` paint is the definition its id names in the slide (`definitions`): a linear or
a radial gradient (`lower.gradients`) or a pattern (`lower.patterns`), at the shape's alpha. An id
the slide does not define, or one that names no paint, is refused as `pptx.reference@1` refuses
it (`OW_TARGET_REFERENCE_UNRESOLVED`). `turn` is the rotation a freeform's points carry and its
box does not (`lower.gradients`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import TargetError

from omniweave_target_pptx.lower import gradients, patterns
from omniweave_target_pptx.lower._style import Chain, declared, element, inherited, number, solid

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["alpha", "fill", "fill_alpha", "line", "line_alpha"]

_BLACK: Final = "#000000"
_NONE: Final = "none"
_URL: Final = re.compile(r"url\(#([^)\s]+)\)")
NO_DEFINITIONS: Final[Mapping[str, CarrierNode]] = MappingProxyType({})


def alpha(chain: Chain) -> float:
    """`opacity`: each node's own, multiplied down the chain."""
    return math.prod(_level(declared(node, "opacity")) for node in chain)


def fill_alpha(chain: Chain) -> float:
    """`fill-opacity`, inherited, times the chain's `opacity`."""
    return _level(inherited(chain, "fill-opacity")) * alpha(chain)


def line_alpha(chain: Chain) -> float:
    """`stroke-opacity`, inherited, times the chain's `opacity`."""
    return _level(inherited(chain, "stroke-opacity")) * alpha(chain)


def fill(
    chain: Chain,
    parent: Any,
    *,
    definitions: Mapping[str, CarrierNode] = NO_DEFINITIONS,
    turn: float = 0.0,
) -> None:
    """The shape's fill: `a:noFill`, a solid colour or a paint server, at its alpha."""
    stated = inherited(chain, "fill") or _BLACK
    _paint(stated, fill_alpha(chain), parent, definitions, turn)


def line(
    chain: Chain,
    parent: Any,
    *,
    definitions: Mapping[str, CarrierNode] = NO_DEFINITIONS,
    turn: float = 0.0,
) -> bool:
    """The line's paint under `parent`, an `a:ln`; `False` when the stroke is none."""
    stated = inherited(chain, "stroke") or _NONE
    _paint(stated, line_alpha(chain), parent, definitions, turn)
    return stated != _NONE


def _level(text: str | None) -> float:
    """One opacity, 1 when unstated, clamped to 0 to 1."""
    return max(0.0, min(1.0, number(text, 1.0)))


def _paint(
    stated: str,
    level: float,
    parent: Any,
    definitions: Mapping[str, CarrierNode],
    turn: float,
) -> None:
    if stated == _NONE:
        element("a:noFill", parent)
    elif stated.startswith("url("):
        _server(stated, level, parent, definitions, turn)
    else:
        solid(stated, level, parent)


def _server(
    stated: str,
    level: float,
    parent: Any,
    definitions: Mapping[str, CarrierNode],
    turn: float,
) -> None:
    """A `url(#id)` paint: the gradient or pattern its id names."""
    m = _URL.fullmatch(stated.strip())
    found = None if m is None else definitions.get(m[1])
    tag = "" if found is None else found.tag
    if found is not None and tag == "svg|linearGradient":
        gradients.linear(found, level, parent, turn=turn)
    elif found is not None and tag == "svg|radialGradient":
        gradients.radial(found, level, parent)
    elif found is not None and tag == "svg|pattern":
        patterns.pattern(found, level, parent)
    else:
        named = "no id in this slide" if found is None else f"a <{tag.partition('|')[2]}>"
        raise TargetError(
            f"paint {stated} names {named}; a paint names a gradient or a pattern",
            symbol="OW_TARGET_REFERENCE_UNRESOLVED",
            fix="ow out check --stage final   # pptx.reference@1 names the same problem",
        )
