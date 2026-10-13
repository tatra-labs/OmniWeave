"""`lower.stroke`: a line's width, dash, cap and join, as `a:ln` holds them. D795.

ppt-master's mappings (`drawingml/utils.py:185-196`, `styles.py:438-504`): `butt`, `round` and
`square` caps are `flat`, `rnd` and `sq`, and the three joins are `a:miter`, `a:round` and
`a:bevel`. Five dash arrays are DrawingML presets: `4 4` and `6 3` are `dash`, `2 2` is `sysDot`,
`8 4` is `lgDash` and `8 4 2 4` is `lgDashDot`. Any other array is a custom dash of its first dash
and gap, in thousandths of a percent of the line's width, as `a:custDash` measures them. A width
grows with the transform's scale unless `vector-effect="non-scaling-stroke"` says it does not.
"""

from __future__ import annotations

import re
from typing import Any, Final

from omniweave_target_pptx.lower._style import Chain, declared, element, inherited, number

__all__ = ["cap", "dash", "join", "scaling", "width"]

CAPS: Final = {"butt": "flat", "round": "rnd", "square": "sq"}
JOINS: Final = {"miter": "a:miter", "round": "a:round", "bevel": "a:bevel"}
PRESETS: Final = {
    (4.0, 4.0): "dash",
    (6.0, 3.0): "dash",
    (2.0, 2.0): "sysDot",
    (8.0, 4.0): "lgDash",
    (8.0, 4.0, 2.0, 4.0): "lgDashDot",
}
_PERCENT: Final = 100_000
_SEPARATOR: Final = re.compile(r"\s*,\s*|\s+")
_MITER_LIMIT: Final = "800000"
"""PowerPoint's own miter limit, 800%, in DrawingML's thousandths of a percent."""


def width(chain: Chain) -> float:
    """`stroke-width`, inherited, 1 by default, in user units."""
    return number(inherited(chain, "stroke-width"), 1.0)


def scaling(chain: Chain) -> bool:
    """`True` unless the node itself says `vector-effect="non-scaling-stroke"`."""
    return declared(chain[-1], "vector-effect") != "non-scaling-stroke"


def cap(chain: Chain) -> str:
    """`stroke-linecap` as `a:ln`'s `cap`."""
    return CAPS.get(inherited(chain, "stroke-linecap") or "butt", "flat")


def join(chain: Chain, parent: Any) -> None:
    """`stroke-linejoin` as the line's join element."""
    tag = JOINS.get(inherited(chain, "stroke-linejoin") or "miter", "a:miter")
    made = element(tag, parent)
    if tag == "a:miter":
        made.set("lim", _MITER_LIMIT)


def dash(chain: Chain, parent: Any) -> None:
    """`stroke-dasharray` as a preset or custom dash; nothing for a solid line."""
    stated = inherited(chain, "stroke-dasharray")
    if stated is None or stated == "none":
        return
    values = tuple(float(v) for v in _SEPARATOR.split(stated.strip()))
    preset = PRESETS.get(values)
    if preset is not None:
        element("a:prstDash", parent, val=preset)
        return
    line = width(chain) or 1.0
    custom = element("a:custDash", parent)
    element(
        "a:ds",
        custom,
        d=str(round(values[0] / line * _PERCENT)),
        sp=str(round(values[1] / line * _PERCENT)),
    )
