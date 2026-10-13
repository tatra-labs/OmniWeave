"""`pptx.unit.root@1`: the slide is one `<svg>` root, never nested. D789, ruling 2."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding, local, walk

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["SPEC", "unit_root"]

RULE: Final = "pptx.unit.root@1"
CODE: Final = "OW_TARGET_UNIT_MALFORMED"
_ROOT: Final = "svg|svg"


def unit_root(ctx: RuleCtx) -> Iterator[Finding]:
    """`ow.unit`: the root is `<svg>`, and no other `<svg>` is inside it."""
    if ctx.doc is None or ctx.unit is None:
        return
    root = ctx.doc.root()
    if root.tag != _ROOT:
        yield finding(
            ctx,
            root,
            rule=RULE,
            code=CODE,
            construct="ow.unit",
            msg=f"the unit root is <{local(root.tag)}>; an owsvg/1 slide is one <svg>",
        )
    for n in walk(root):
        if n.tag == _ROOT:
            yield finding(
                ctx,
                n,
                rule=RULE,
                code=CODE,
                construct="ow.unit",
                msg="an <svg> inside the slide: one unit is one <svg>; crop with clip-path",
            )


SPEC: Final = RuleSpec(RULE, 10, "unit", frozenset({CODE}), unit_root)
