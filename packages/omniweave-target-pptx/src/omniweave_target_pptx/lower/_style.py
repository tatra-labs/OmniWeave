"""A node's presentation properties, read as SVG reads them, and their DrawingML. D795.

A `chain` is the slide root, each ancestor, then the node, outermost first. A property is read
from a node's `style` declaration before its attribute (CSS outranks a presentation attribute),
and an inherited property from the nearest node in the chain that states it. `opacity` is not
inherited: a group's composes with its children's, so a node's is the product down its chain,
the alpha ppt-master pushes down to a group's children (`svg_contracts.py:449-471`).

`named()` (D799) resolves a `url(#id)` property, a paint, a filter or a marker, to the definition
its id names in the slide, and refuses an id that names nothing or the wrong kind of definition,
as `pptx.reference@1` does (`OW_TARGET_REFERENCE_UNRESOLVED`).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import style_declarations
from pptx.oxml.ns import qn

from omniweave_target_pptx.normalizers import opacity_fraction, px_length, upper_hex

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = [
    "ALPHA_FULL",
    "colour",
    "declared",
    "element",
    "inherited",
    "named",
    "number",
    "solid",
]

ALPHA_FULL: Final = 100_000
"""DrawingML's `a:alpha` is in thousandths of a percent."""

Chain = Sequence["CarrierNode"]
_URL: Final = re.compile(r"url\(#([^)\s]+)\)|#(\S+)")
"""`url(#id)`, a property's spelling, or `#id`, an `href`'s (D801)."""


def element(tag: str, parent: Any = None, **attrs: str) -> Any:
    """`a:off` as an lxml element, under `parent` when one is given."""
    made = etree.Element(qn(tag)) if parent is None else etree.SubElement(parent, qn(tag))
    for key, value in sorted(attrs.items()):
        made.set(key, value)
    return made


def declared(node: CarrierNode, prop: str) -> str | None:
    """`prop` on `node` itself: its `style` declaration, else its attribute."""
    for name, value in style_declarations(node.attr("style") or ""):
        if name == prop:
            return value.strip()
    stated = node.attr(prop)
    return None if stated is None else stated.strip()


def inherited(chain: Chain, prop: str) -> str | None:
    """`prop` from the nearest node in `chain` that states it."""
    for node in reversed(chain):
        found = declared(node, prop)
        if found is not None:
            return found
    return None


def named(
    stated: str,
    definitions: Mapping[str, CarrierNode],
    tags: Collection[str],
    *,
    what: str,
) -> CarrierNode:
    """The definition `url(#id)` names, of one of `tags`; refused when it names nothing else."""
    m = _URL.fullmatch(stated.strip())
    found = None if m is None else definitions.get(m[1] or m[2])
    if found is None or found.tag not in tags:
        named_ = "no id in this slide" if found is None else f"a <{found.tag.partition('|')[2]}>"
        raise TargetError(
            f"{stated} names {named_}; it must name {what}",
            symbol="OW_TARGET_REFERENCE_UNRESOLVED",
            fix="ow out check --stage final   # pptx.reference@1 names the same problem",
        )
    return found


def number(text: str | None, default: float) -> float:
    """A length or opacity as a float, `px` and a percentage settled as their normalizers do."""
    if text is None:
        return default
    try:
        return float(opacity_fraction(px_length(text)))
    except ValueError:
        return default


def solid(value: str, alpha: float, parent: Any = None) -> Any:
    """`a:solidFill` of `colour()`."""
    fill = element("a:solidFill", parent)
    colour(value, alpha, fill)
    return fill


def colour(value: str, alpha: float, parent: Any) -> Any:
    """`a:srgbClr` of `#RRGGBB`, with `a:alpha` when `alpha`, 0 to 1, is not opaque: a solid
    fill's colour, a gradient stop's and a pattern's."""
    rgb = element("a:srgbClr", parent, val=upper_hex(value).removeprefix("#"))
    level = round(alpha * ALPHA_FULL)
    if level < ALPHA_FULL:
        element("a:alpha", rgb, val=str(level))
    return rgb
