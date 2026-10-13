"""`pptx.transform@1`: a transform DrawingML can hold, where it can hold it. D790.

ppt-master's grammar (`drawingml/utils.py:674-890`):
- the operations are `matrix` (6 numbers), `translate` (1 or 2), `scale` (1 or 2) and `rotate`
  (1 or 3). `skewX` and `skewY` are refused, as is a matrix whose axes are not perpendicular (a
  shear) and a scale or matrix of zero, which collapses the shape;
- text takes a translation or one rotation, and nothing else, because a DrawingML text box has
  an offset and a rotation and no matrix. A group holding text is held to the same;
- nothing inside a `<clipPath>`, `<marker>` or `<pattern>` is transformed (`:1255-1262`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import lineage, local, said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["SPEC", "operations", "transform"]

RULE: Final = "pptx.transform@1"
CODE: Final = "OW_TARGET_TRANSFORM_INVALID"
ARITY: Final = {"matrix": (6,), "translate": (1, 2), "scale": (1, 2), "rotate": (1, 3)}
_OPERATION: Final = re.compile(r"\s*([A-Za-z]+)\s*\(([^)]*)\)\s*,?")
_NUMBER: Final = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_ARGUMENT_SEPARATOR: Final = re.compile(r"\s*,\s*|\s+")
_TEXT: Final = frozenset({"svg|text", "svg|tspan"})
_UNTRANSFORMED: Final = frozenset({"svg|clipPath", "svg|marker", "svg|pattern"})


def operations(text: str) -> list[tuple[str, list[Decimal]]] | str:
    """The transform list, or why it is not one DrawingML can hold."""
    found: list[tuple[str, list[Decimal]]] = []
    pos = 0
    while pos < len(text):
        if not text[pos:].strip():
            break
        m = _OPERATION.match(text, pos)
        if m is None:
            return f"{text[pos:].strip()[:12]!r} is not name(numbers)"
        name, inner = m[1], m[2].strip()
        if name in ("skewX", "skewY"):
            return f"{name}: DrawingML has no skew"
        arity = ARITY.get(name)
        if arity is None:
            return f"{name!r} is not matrix, translate, scale or rotate"
        parts = _ARGUMENT_SEPARATOR.split(inner) if inner else []
        if any(_NUMBER.fullmatch(p) is None for p in parts) or len(parts) not in arity:
            counts = " or ".join(str(n) for n in arity)
            return f"{name} takes {counts} numbers"
        found.append((name, [Decimal(p) for p in parts]))
        pos = m.end()
    if not found:
        return "the transform is empty"
    return found


def _degenerate(ops: Sequence[tuple[str, list[Decimal]]]) -> str | None:
    for name, args in ops:
        if name == "scale" and 0 in args:
            return "a scale of zero collapses the shape"
        if name == "matrix":
            a, b, c, d = args[:4]
            if a * d - b * c == 0:
                return "a matrix of determinant zero collapses the shape"
            if a * c + b * d != 0:
                return "a matrix whose axes are not perpendicular is a shear, which DrawingML lacks"
    return None


def transform(ctx: RuleCtx) -> Iterator[Finding]:
    """Each `transform` grammatical, not degenerate, and allowed where it stands."""
    if ctx.doc is None or ctx.unit is None:
        return
    root = ctx.doc.root()
    texts = _holding_text(root)
    above = {id(n): tags for n, tags in lineage(root)}
    for v in values(ctx, ("transform",)):
        if v.node is root:
            continue  # pptx.canvas@1 refuses a transform on the slide itself
        ops = operations(v.settled)
        if isinstance(ops, str):
            yield said(ctx, v, rule=RULE, code=CODE, why=ops)
            continue
        why = _degenerate(ops)
        if why is not None:
            yield said(ctx, v, rule=RULE, code=CODE, why=why)
            continue
        inside = next((t for t in above.get(id(v.node), ()) if t in _UNTRANSFORMED), None)
        if inside is not None:
            yield said(
                ctx, v, rule=RULE, code=CODE, why=f"nothing inside <{local(inside)}> is transformed"
            )
        elif id(v.node) in texts and not _text_safe(ops):
            yield said(
                ctx,
                v,
                rule=RULE,
                code=CODE,
                why="text takes a translate or one rotate, and nothing else",
            )


def _holding_text(root: CarrierNode) -> set[int]:
    """The ids of every text node and every group with text under it."""
    held: set[int] = set()
    for n, _ in lineage(root):
        text = n.tag in _TEXT
        if text or (n.tag == "svg|g" and any(c.tag == "svg|text" for c, _ in lineage(n))):
            held.add(id(n))
    return held


def _text_safe(ops: Sequence[tuple[str, list[Decimal]]]) -> bool:
    names = [name for name, _ in ops]
    return all(n == "translate" for n in names) or names == ["rotate"]


SPEC: Final = RuleSpec(RULE, 45, "unit", frozenset({CODE}), transform)
