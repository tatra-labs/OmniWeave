"""`pptx.effect@1`: one shadow or glow, a marker of one shape, a clip of one shape. D791.

DrawingML has one outer shadow and one glow, a line end of a preset shape, and a picture crop.
ppt-master (`drawingml/utils.py:244-265`, `:2000-2178`, `:2594-2939`; `elements.py:3499`,
`:3745-3858`):
- a `<filter>` holds one `<feDropShadow>` (an outer shadow) or one `<feGaussianBlur>` (a glow),
  and each states its `stdDeviation`, a number 0 or more; a primitive outside a filter is
  refused;
- a `<marker>` holds one `<circle>`, `<ellipse>`, `<path>` or `<polygon>`, its sizes are above
  zero, and only a `<line>` or a `<path>` takes `marker-start` or `marker-end`;
- a `<clipPath>` holds one `<circle>`, `<ellipse>`, `<rect>`, `<path>` or `<polygon>`, only an
  `<image>` takes `clip-path`, and an image takes a filter or a clip, not both.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding, lineage, local, number

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["CLIP_SHAPES", "MARKER_SHAPES", "PRIMITIVES", "SPEC", "effect"]

RULE: Final = "pptx.effect@1"
CODE: Final = "OW_TARGET_EFFECT_INVALID"
PRIMITIVES: Final = frozenset({"svg|feDropShadow", "svg|feGaussianBlur"})
MARKER_SHAPES: Final = frozenset({"svg|circle", "svg|ellipse", "svg|path", "svg|polygon"})
CLIP_SHAPES: Final = MARKER_SHAPES | {"svg|rect"}
_ENDED: Final = frozenset({"svg|line", "svg|path"})


def effect(ctx: RuleCtx) -> Iterator[Finding]:
    """Filters, markers and clips, each of the one shape DrawingML holds."""
    if ctx.doc is None or ctx.unit is None:
        return
    for n, above in lineage(ctx.doc.root()):
        if n.tag == "svg|filter":
            yield from _one(ctx, n, "effect.filter-def", PRIMITIVES)
        elif n.tag in PRIMITIVES:
            yield from _primitive(ctx, n, above[-1])
        elif n.tag == "svg|marker":
            yield from _one(ctx, n, "effect.marker-def", MARKER_SHAPES)
            yield from _marker_sizes(ctx, n)
        elif n.tag == "svg|clipPath":
            yield from _one(ctx, n, "effect.clip-def", CLIP_SHAPES)
        yield from _placed(ctx, n)


def _one(
    ctx: RuleCtx, n: CarrierNode, construct: str, allowed: frozenset[str]
) -> Iterator[Finding]:
    children = list(n.children())
    if len(children) != 1 or children[0].tag not in allowed:
        what = ", ".join(f"<{local(t)}>" for t in sorted(allowed))
        yield _said(ctx, n, construct, f"a <{local(n.tag)}> holds one of {what}, and nothing else")


def _primitive(ctx: RuleCtx, n: CarrierNode, parent: str) -> Iterator[Finding]:
    construct = "effect.shadow" if n.tag == "svg|feDropShadow" else "effect.blur"
    if parent != "svg|filter":
        yield _said(ctx, n, construct, f"a <{local(n.tag)}> belongs to a <filter>")
    raw = n.attr("stdDeviation")
    found = None if raw is None else number(raw)
    if found is None or found < 0:
        yield _said(ctx, n, construct, f"stdDeviation={raw!r}: write a number, 0 or more")
    if n.tag == "svg|feDropShadow":
        for side in ("dx", "dy"):
            offset = n.attr(side)
            if offset is not None and number(offset) is None:
                yield _said(ctx, n, construct, f"{side}={offset!r}: write a decimal number")


def _marker_sizes(ctx: RuleCtx, n: CarrierNode) -> Iterator[Finding]:
    for side in ("markerWidth", "markerHeight"):
        raw = n.attr(side)
        found = None if raw is None else number(raw)
        if raw is not None and (found is None or found <= 0):
            yield _said(ctx, n, "effect.marker-def", f"{side}={raw!r}: a marker's size is above 0")
    for side in ("refX", "refY"):
        raw = n.attr(side)
        if raw is not None and number(raw) is None:
            yield _said(ctx, n, "effect.marker-def", f"{side}={raw!r}: write a decimal number")


def _placed(ctx: RuleCtx, n: CarrierNode) -> Iterator[Finding]:
    """Line ends on lines and paths, clips on images, and an image's one effect."""
    for side in ("marker-start", "marker-end"):
        if n.attr(side) is not None and n.tag not in _ENDED:
            yield _said(
                ctx, n, f"effect.{side}",
                f"{side} on a <{local(n.tag)}>: a line end belongs to a <line> or <path>",
            )  # fmt: skip
    if n.attr("clip-path") is not None:
        if n.tag != "svg|image":
            yield _said(
                ctx, n, "effect.clip", f"clip-path on a <{local(n.tag)}>: a clip crops an <image>"
            )
        elif n.attr("filter") is not None:
            yield _said(ctx, n, "effect.clip", "an <image> takes a filter or a clip, not both")


def _said(ctx: RuleCtx, n: CarrierNode, construct: str, msg: str) -> Finding:
    return finding(ctx, n, rule=RULE, code=CODE, construct=construct, msg=msg)


SPEC: Final = RuleSpec(RULE, 51, "unit", frozenset({CODE}), effect)
