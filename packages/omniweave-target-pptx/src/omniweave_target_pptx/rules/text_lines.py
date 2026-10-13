"""`pptx.text.lines@1`: a positioned line is a paragraph of its own text box. D793.

A `<tspan>` with `x` or `dy` starts a line (09 section 3.1's `svg` row, and `measure.py`). A
DrawingML text box holds paragraphs that share its position and its alignment, so a line cannot
start at another `x`, and cannot start inside a run, where there is no paragraph to begin. A
positioned `<tspan>` is therefore a direct child of its `<text>`, and its `x`, where it states
one, is the text's own (0 where the text states none).

D797 holds the rest of a line's place to what one text box draws, since `lower.text` writes each
line as a paragraph. A line's baseline is its `y`, else the line before's baseline, plus its
`dy`, and a text's first baseline is its own `y` plus its `dy`. Each must sit below the line
before, because a text box's paragraphs run down it. A `dx` moves a run along its line, and a `y`
on a `<tspan>` that starts no line moves a run off it. A DrawingML run can do neither, so a
non-zero `dx` and such a `y` are refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
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
        last = _baseline(text, None)
        yield from _offsets(ctx, text)
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
                here = _baseline(child, last)
                if last is not None and here is not None and here <= last:
                    yield _said(
                        ctx, child,
                        f"its baseline, {here}, is not below the line before's, {last}: "
                        "a text box's lines run down it",
                    )  # fmt: skip
                last = here
            for deeper in walk(child):
                if _positioned(deeper):
                    yield _said(ctx, deeper, "a line starts in its <text>, never inside a run")


def _baseline(n: CarrierNode, last: Decimal | None) -> Decimal | None:
    """`n`'s baseline: its `y`, else `last` (0 for a text), plus its `dy`."""
    y, dy = n.attr("y"), n.attr("dy")
    start = number(y) if y is not None else Decimal(0) if last is None else last
    shift = number(dy) if dy is not None else Decimal(0)
    return None if start is None or shift is None else start + shift


def _offsets(ctx: RuleCtx, text: CarrierNode) -> Iterator[Finding]:
    """A run's `dx`, and a `y` on a `<tspan>` that starts no line."""
    for n in (text, *walk(text)):
        dx = n.attr("dx")
        if dx is not None and number(dx) != 0:
            yield finding(
                ctx, n, rule=RULE, code=CODE, construct="geom.dx",
                msg=f"dx={dx!r}: a DrawingML run has no offset; move the text's x or split it",
            )  # fmt: skip
        if n.tag == _TSPAN and n.attr("y") is not None and not _positioned(n):
            yield finding(
                ctx, n, rule=RULE, code=CODE, construct="geom.y",
                msg="a y on a run that starts no line moves it off its line; give it dy or x",
            )  # fmt: skip


def _positioned(n: CarrierNode) -> bool:
    return n.tag == _TSPAN and (n.attr("x") is not None or n.attr("dy") is not None)


def _said(ctx: RuleCtx, n: CarrierNode, msg: str) -> Finding:
    return finding(ctx, n, rule=RULE, code=CODE, construct="text.tspan", msg=msg)


SPEC: Final = RuleSpec(RULE, 53, "unit", frozenset({CODE}), text_lines)
