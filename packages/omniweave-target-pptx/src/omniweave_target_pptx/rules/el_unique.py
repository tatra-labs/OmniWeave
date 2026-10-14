"""`pptx.el.unique@1`: `data-ow-el` is minted once and unique in the unit. D789, ruling 4."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["SPEC", "el_unique"]

RULE: Final = "pptx.el.unique@1"
CODE: Final = "OW_TARGET_EL_DUPLICATE"


def el_unique(ctx: RuleCtx) -> Iterator[Finding]:
    """OUT21: a second element carrying one address is refused, naming both."""
    if ctx.doc is None or ctx.unit is None:
        return
    seen: dict[str, str] = {}
    for n in ctx.doc.select("@data-ow-el"):
        el = n.attr("data-ow-el") or ""
        if el in seen:
            yield finding(
                ctx,
                n,
                rule=RULE,
                code=CODE,
                construct="ow.el",
                msg=f"data-ow-el={el!r} appears at {seen[el]} and {n.at}",
            )
        else:
            seen[el] = n.at


SPEC: Final = RuleSpec(RULE, 12, "unit", frozenset({CODE}), el_unique)
