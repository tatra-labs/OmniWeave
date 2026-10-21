"""`pptx.reference@1`: every local reference resolves, to a definition of the kind it needs.
D791.

09 section 12.1's reference band: "every `use` reference resolves locally; every `asset-slot:`
resolves". ppt-master's paint contexts (`drawingml/utils.py:2226-2347`) and use targets
(`use_expander.py:39`, `:65-69`):
- an id is defined once in the slide;
- a `fill` names a linear or radial gradient or a pattern, and a `stroke` a gradient;
- `filter`, `marker-start`, `marker-end` and `clip-path` are `url(#id)` naming a `<filter>`, a
  `<marker>` and a `<clipPath>`;
- a `<use>` names a local shape, group, text, image or symbol, and an `<image>` names its
  picture as `asset-slot:<sha256>` (`OW_TARGET_IL_ASSET_URI`, the same grammar docx holds);
- an `<a>` links to a slide of the deck, `#u<NN>` naming a unit of its roster (D911), or to an
  `https:` page.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding, lineage, local, said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.rules._common import Value

__all__ = ["SPEC", "reference"]

RULE: Final = "pptx.reference@1"
CODE: Final = "OW_TARGET_REFERENCE_UNRESOLVED"
ASSET: Final = "OW_TARGET_IL_ASSET_URI"
_URL: Final = re.compile(r"url\(#([^)\s]+)\)")
_SLOT: Final = re.compile(r"asset-slot:[0-9a-f]{64}")
_LINK: Final = re.compile(r"#u[0-9]{2,}|https:\S+")
"""A slide in the deck, or an `https:` page: docx's link spelling, less `http:` and `mailto:`."""
_GRADIENTS: Final = frozenset({"svg|linearGradient", "svg|radialGradient"})
NAMED: Final[Mapping[str, frozenset[str]]] = {
    "fill": _GRADIENTS | {"svg|pattern"},
    "stroke": _GRADIENTS,
    "filter": frozenset({"svg|filter"}),
    "marker-start": frozenset({"svg|marker"}),
    "marker-end": frozenset({"svg|marker"}),
    "clip-path": frozenset({"svg|clipPath"}),
}
"""What each `url(#id)` property may name."""
USE_TARGETS: Final = frozenset(
    f"svg|{t}"
    for t in (
        "symbol", "g", "use", "rect", "circle", "ellipse", "line", "path", "polygon", "polyline",
        "text", "image",
    )
)  # fmt: skip


def reference(ctx: RuleCtx) -> Iterator[Finding]:
    """Ids once each; every `url(#id)` and `href` resolving to what it needs."""
    if ctx.doc is None or ctx.unit is None:
        return
    root = ctx.doc.root()
    defined: dict[str, CarrierNode] = {}
    for n in (root, *(m for m, _ in lineage(root))):
        name = n.attr("id")
        if name is None:
            continue
        if name in defined:
            yield finding(
                ctx, n, rule=RULE, code=CODE, construct="geom.id",
                msg=f"id={name!r} is defined twice in the slide; url(#id) and href need one",
            )  # fmt: skip
        else:
            defined[name] = n
    for v in values(ctx, NAMED):
        m = _URL.fullmatch(v.settled.strip())
        if m is None:
            if v.prop not in ("fill", "stroke"):  # pptx.paint@1 holds a paint's grammar
                yield said(ctx, v, rule=RULE, code=CODE, why="write url(#id)")
            continue
        yield from _named(ctx, v, defined.get(m[1]), NAMED[v.prop])
    for v in values(ctx, ("href",)):
        yield from _href(ctx, v, defined)
    for tag, attr in (("svg|use", "href"), ("svg|image", "href")):
        for n in ctx.doc.select(tag):
            if n.attr(attr) is None:
                code = ASSET if tag == "svg|image" else CODE
                what = "its picture as href=asset-slot:<sha256>" if code == ASSET else "href=#id"
                yield finding(
                    ctx, n, rule=RULE, code=code, construct="geom.href",
                    msg=f"a <{local(tag)}> names {what}",
                )  # fmt: skip


def _named(
    ctx: RuleCtx, v: Value, target: CarrierNode | None, kinds: frozenset[str]
) -> Iterator[Finding]:
    wanted = " or ".join(f"<{local(k)}>" for k in sorted(kinds))
    if target is None:
        yield said(
            ctx, v, rule=RULE, code=CODE, why=f"names no id in this slide; it needs {wanted}"
        )
    elif target.tag not in kinds:
        yield said(
            ctx, v, rule=RULE, code=CODE,
            why=f"names a <{local(target.tag)}>, and {v.prop} takes {wanted}",
        )  # fmt: skip


def _href(ctx: RuleCtx, v: Value, defined: Mapping[str, CarrierNode]) -> Iterator[Finding]:
    tag, value = v.node.tag, v.settled.strip()
    if tag == "svg|image":
        if _SLOT.fullmatch(value) is None:
            yield said(
                ctx, v, rule=RULE, code=ASSET,
                why="a picture is asset-slot:<sha256 hex>; freeze the asset and write its slot",
            )  # fmt: skip
    elif tag == "svg|use":
        if not value.startswith("#"):
            yield said(ctx, v, rule=RULE, code=CODE, why="a <use> names a local id, #id")
            return
        yield from _named(ctx, v, defined.get(value[1:]), USE_TARGETS)
    elif tag == "svg|a":
        if _LINK.fullmatch(value) is None:
            yield said(ctx, v, rule=RULE, code=CODE, why="a link is #u<NN>, a slide, or https:")
        elif value.startswith("#") and value[1:] not in ctx.index.units:
            #  D911: `lower()` refuses a jump to a slide the deck does not hold, so the gate does
            #  first: a passed gate whose compile refuses is OUT23's promise broken.
            yield said(
                ctx, v, rule=RULE, code=CODE,
                why=f"names no slide in this deck; its units are {', '.join(ctx.index.units)}",
            )  # fmt: skip
    else:
        yield said(ctx, v, rule=RULE, code=CODE, why="href belongs to <use>, <image> or <a>")


SPEC: Final = RuleSpec(RULE, 50, "unit", frozenset({CODE, ASSET}), reference)
