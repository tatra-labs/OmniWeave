"""`pptx.enum@1`: a keyword property is one of its words, and stands where it means something.
D790.

Each value set is ppt-master's (`drawingml/utils.py:192-208`, `:501-536`, `:2000-2178`,
`elements.py:3745-3858`; `text_properties.py:279-327`). `text-anchor` is the text box's, so it
is refused on a `<tspan>`, and `baseline-shift` is a run's, so it stands on a `<tspan>` only.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["KEYWORDS", "SPEC", "keywords"]

RULE: Final = "pptx.enum@1"
STROKE: Final = "OW_TARGET_STROKE_INVALID"
FONT: Final = "OW_TARGET_FONT_INVALID"
TEXT: Final = "OW_TARGET_TEXT_INVALID"
GRADIENT: Final = "OW_TARGET_GRADIENT_INVALID"
EFFECT: Final = "OW_TARGET_EFFECT_INVALID"
GEOMETRY: Final = "OW_TARGET_GEOMETRY_INVALID"
KEYWORDS: Final[Mapping[str, tuple[frozenset[str], str]]] = {
    "stroke-linecap": (frozenset({"butt", "round", "square"}), STROKE),
    "stroke-linejoin": (frozenset({"miter", "round", "bevel"}), STROKE),
    "vector-effect": (frozenset({"none", "non-scaling-stroke"}), STROKE),
    "font-style": (frozenset({"normal", "italic"}), FONT),
    "text-anchor": (frozenset({"start", "middle", "end"}), FONT),
    "text-decoration": (
        frozenset({"none", "underline", "line-through", "underline line-through"}),
        FONT,
    ),
    "baseline-shift": (frozenset({"super", "sub"}), FONT),
    "xml:space": (frozenset({"default", "preserve"}), TEXT),
    "gradientUnits": (frozenset({"objectBoundingBox"}), GRADIENT),
    "orient": (frozenset({"auto", "auto-start-reverse"}), EFFECT),
    "markerUnits": (frozenset({"strokeWidth", "userSpaceOnUse"}), EFFECT),
    "clipPathUnits": (frozenset({"userSpaceOnUse", "objectBoundingBox"}), EFFECT),
    "primitiveUnits": (frozenset({"userSpaceOnUse"}), EFFECT),
}
_ASPECT: Final = re.compile(r"none|x(?:Min|Mid|Max)Y(?:Min|Mid|Max)(?: (?:meet|slice))?")
_TSPAN: Final = "svg|tspan"
_TEXT_NODES: Final = frozenset({"svg|text", _TSPAN})


def keywords(ctx: RuleCtx) -> Iterator[Finding]:
    """Each keyword in its set; `text-anchor`, `baseline-shift` and `xml:space` where they hold."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, KEYWORDS):
        allowed, code = KEYWORDS[v.prop]
        value = v.settled.strip()
        if value not in allowed:
            words = " | ".join(sorted(allowed))
            yield said(ctx, v, rule=RULE, code=code, why=f"write one of {words}")
        elif v.prop == "text-anchor" and v.node.tag == _TSPAN:
            yield said(
                ctx, v, rule=RULE, code=code, why="text-anchor is the text box's: set it on <text>"
            )
        elif v.prop == "baseline-shift" and v.node.tag != _TSPAN:
            yield said(
                ctx, v, rule=RULE, code=code, why="baseline-shift is a run's: set it on <tspan>"
            )
        elif v.prop == "xml:space" and v.node.tag not in _TEXT_NODES:
            yield said(ctx, v, rule=RULE, code=code, why="xml:space belongs to <text> or <tspan>")
    for v in values(ctx, ("preserveAspectRatio",)):
        if _ASPECT.fullmatch(v.settled.strip()) is None:
            yield said(
                ctx,
                v,
                rule=RULE,
                code=GEOMETRY,
                why="write none, or xMinYMin to xMaxYMax with meet or slice",
            )


SPEC: Final = RuleSpec(
    RULE,
    46,
    "unit",
    frozenset({STROKE, FONT, TEXT, GRADIENT, EFFECT, GEOMETRY}),
    keywords,
)
