"""`pptx.paint@1`: a paint is `#RRGGBB`, and a shape's may be `none` or `url(#id)`. D790.

ppt-master's canonical paint (`drawingml/utils.py:1758-1766`). It accepts `#rgb`, named colours,
`rgb()` and `hsl()` with an advisory, and refuses `currentColor` and `inherit`. owsvg/1 holds the
one spelling. Short and lower-case hex on an attribute is the normalize row's warning, so this
rule sees the value that row leaves. In `style` there is no normalize row, so the value must be
canonical as written. A colour's alpha belongs in the matching `*-opacity` property.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["SPEC", "paint"]

RULE: Final = "pptx.paint@1"
CODE: Final = "OW_TARGET_FILL_INVALID"
_HEX: Final = re.compile(r"#[0-9A-F]{6}")
_REF: Final = re.compile(r"url\(#[^)\s]+\)")
SHAPE_PAINTS: Final = ("fill", "stroke")
COLOURS: Final = ("stop-color", "flood-color", "data-ow-fg", "data-ow-bg")


def paint(ctx: RuleCtx) -> Iterator[Finding]:
    """Each paint against its row's grammar."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, SHAPE_PAINTS):
        value = v.settled.strip()
        if value != "none" and not _HEX.fullmatch(value) and not _REF.fullmatch(value):
            yield said(
                ctx, v, rule=RULE, code=CODE, why="write #RRGGBB in upper case, none or url(#id)"
            )
    for v in values(ctx, COLOURS):
        if not _HEX.fullmatch(v.settled.strip()):
            yield said(ctx, v, rule=RULE, code=CODE, why="write #RRGGBB in upper case")


SPEC: Final = RuleSpec(RULE, 40, "unit", frozenset({CODE}), paint)
