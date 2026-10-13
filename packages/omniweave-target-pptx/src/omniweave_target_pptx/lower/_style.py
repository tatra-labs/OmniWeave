"""A node's presentation properties, read as SVG reads them, and their DrawingML. D795.

A `chain` is the slide root, each ancestor, then the node, outermost first. A property is read
from a node's `style` declaration before its attribute (CSS outranks a presentation attribute),
and an inherited property from the nearest node in the chain that states it. `opacity` is not
inherited: a group's composes with its children's, so a node's is the product down its chain,
the alpha ppt-master pushes down to a group's children (`svg_contracts.py:449-471`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final

from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.out.carrier import style_declarations
from pptx.oxml.ns import qn

from omniweave_target_pptx.normalizers import opacity_fraction, px_length, upper_hex

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = [
    "ALPHA_FULL",
    "declared",
    "element",
    "inherited",
    "number",
    "solid",
]

ALPHA_FULL: Final = 100_000
"""DrawingML's `a:alpha` is in thousandths of a percent."""

Chain = Sequence["CarrierNode"]


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


def number(text: str | None, default: float) -> float:
    """A length or opacity as a float, `px` and a percentage settled as their normalizers do."""
    if text is None:
        return default
    try:
        return float(opacity_fraction(px_length(text)))
    except ValueError:
        return default


def solid(colour: str, alpha: float, parent: Any = None) -> Any:
    """`a:solidFill` of `#RRGGBB`, with `a:alpha` when `alpha`, 0 to 1, is not opaque."""
    fill = element("a:solidFill", parent)
    rgb = element("a:srgbClr", fill, val=upper_hex(colour).removeprefix("#"))
    level = round(alpha * ALPHA_FULL)
    if level < ALPHA_FULL:
        element("a:alpha", rgb, val=str(level))
    return fill
