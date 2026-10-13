"""What every owsvg/1 rule shares: its finding's shape and the tree walk. D789."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from omniweave_core.out import Finding, Provenance, Severity

if TYPE_CHECKING:
    from omniweave_core.out import RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["CONSTRUCTS", "finding", "local", "walk"]

CONSTRUCTS: Final = "ow out constructs pptx --construct"


def finding(
    ctx: RuleCtx, n: CarrierNode, *, rule: str, code: str, construct: str, msg: str
) -> Finding:
    """An introduced error at `n`, whose fix is the construct's own documentation."""
    return Finding(
        code=code,
        severity=Severity.ERROR,
        provenance=Provenance.INTRODUCED,
        rule=rule,
        unit=ctx.unit.id if ctx.unit is not None else "",
        construct=construct,
        msg=msg,
        fix=f"{CONSTRUCTS} {construct}",
        at=n.at,
        el=n.el,
    )


def walk(root: CarrierNode) -> Iterator[CarrierNode]:
    """Every node under `root`, `root` excluded, in document order."""
    stack = list(reversed(list(root.children())))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(list(node.children())))


def local(tag: str) -> str:
    """`svg|rect` to `rect`."""
    return tag.partition("|")[2] or tag
