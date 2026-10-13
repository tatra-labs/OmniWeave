"""`pptx.text.lines@1`: a positioned line is a paragraph of its own text box. D793.

A `<tspan>` with `x` or `dy` starts a line (09 section 3.1's `svg` row, and `measure.py`). A
DrawingML text box holds paragraphs that share its position and its alignment, so a line cannot
start at another `x`, and cannot start inside a run, where there is no paragraph to begin. A
positioned `<tspan>` is therefore a direct child of its `<text>`, and its `x`, where it states
one, is the text's own (0 where the text states none). A `y` sets the line's baseline and is
held to nothing here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding, number, walk

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["SPEC", "text_lines"]

RULE: Final = "pptx.text.lines@1"
CODE: Final = "OW_TARGET_TEXT_INVALID"
_TSPAN: Final = "svg|tspan"


def text_lines(ctx: RuleCtx) -> Iterator[Finding]:
    """Each positioned line a direct child of its text, at the text's `x`."""
    if ctx.doc is None or ctx.unit is None:
        return
    for text in ctx.doc.select("svg|text"):
        base = number(text.attr("x") or "0")
        for child in text.children():
            if _positioned(child):
                stated = child.attr("x")
                at = None if stated is None else number(stated)
                if base is not None and at is not None and at != base:
                    yield _said(
                        ctx, child,
                        f"x={stated!r}: a line of a text box starts at the text's x, "
                        f"{text.attr('x') or '0'}",
                    )  # fmt: skip
            for deeper in walk(child):
                if _positioned(deeper):
                    yield _said(ctx, deeper, "a line starts in its <text>, never inside a run")


def _positioned(n: CarrierNode) -> bool:
    return n.tag == _TSPAN and (n.attr("x") is not None or n.attr("dy") is not None)


def _said(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return finding(ctx, n, rule=RULE, code=CODE, construct="text.tspan", msg=msg)


SPEC: Final = RuleSpec(RULE, 53, "unit", frozenset({CODE}), text_lines)
