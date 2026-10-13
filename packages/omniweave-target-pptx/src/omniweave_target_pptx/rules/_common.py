"""What every owsvg/1 rule shares: its finding's shape, the tree walk, and a property's values.
D789, and D790's grammar band."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from omniweave_core.out import Finding, Provenance, Severity
from omniweave_core.out.carrier import style_declarations
from omniweave_core.out.constructs import Disposition

from omniweave_target_pptx.normalizers import BY_NAME

if TYPE_CHECKING:
    from omniweave_core.out import ConstructTable, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = [
    "CONSTRUCTS",
    "NUMBER",
    "Value",
    "finding",
    "lineage",
    "local",
    "number",
    "said",
    "values",
    "walk",
]

CONSTRUCTS: Final = "ow out constructs pptx --construct"
NUMBER: Final = r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
"""ppt-master's canonical number (`drawingml/paths.py:53-55`): no `+`, no exponent, no bare `.`"""
_NUMBER: Final = re.compile(NUMBER)
_STYLE_PX: Final = re.compile(f"({NUMBER})(?:px)?")


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


def lineage(root: CarrierNode) -> Iterator[tuple[CarrierNode, tuple[str, ...]]]:
    """Every node under `root`, `root` excluded, with its ancestors' tags, nearest last."""
    stack: list[tuple[CarrierNode, tuple[str, ...]]] = [
        (child, (root.tag,)) for child in reversed(list(root.children()))
    ]
    while stack:
        node, above = stack.pop()
        yield node, above
        stack.extend((child, (*above, node.tag)) for child in reversed(list(node.children())))


def local(tag: str) -> str:
    """`svg|rect` to `rect`."""
    return tag.partition("|")[2] or tag


@dataclass(frozen=True, slots=True)
class Value:
    """One written value of a property: an attribute, or a declaration in `style`."""

    node: CarrierNode
    prop: str
    raw: str
    construct: str
    styled: bool
    settled: str
    """`raw` as its `normalize` rows leave it; `raw` itself for a style declaration."""

    def where(self) -> str:
        if self.styled:
            return f"<{local(self.node.tag)}> style {self.prop}: {self.raw!r}"
        return f"<{local(self.node.tag)}> {self.prop}={self.raw!r}"

    def number(self) -> Decimal | None:
        """The settled value as a canonical number; a style length may carry `px`."""
        if self.styled:
            m = _STYLE_PX.fullmatch(self.settled.strip())
            return None if m is None else Decimal(m[1])
        return number(self.settled)


def number(text: str) -> Decimal | None:
    """`text` as a canonical number, surrounding whitespace aside, or `None`."""
    stripped = text.strip()
    if _NUMBER.fullmatch(stripped) is None:
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:  # pragma: no cover -- the pattern admits only decimals.
        return None


def values(ctx: RuleCtx, props: Iterable[str]) -> Iterator[Value]:
    """Every value of each property, attribute and `style` form, in document order a form.

    An attribute value is settled through the `normalize` rows that target its row, because a
    value one of them rewrites is that row's warning. A `style` declaration has no normalize row
    (D781 ruling 5), so it is read as written.
    """
    if ctx.doc is None:
        return
    rows = _rows(ctx.constructs)
    for prop in props:
        attribute = rows.get(f"@{prop}")
        if attribute is not None:
            for n in ctx.doc.select(f"@{prop}"):
                raw = n.attr(prop) or ""
                yield Value(n, prop, raw, attribute, False, _settle(ctx.constructs, attribute, raw))
        styled = rows.get(f"@style|{prop}")
        if styled is not None:
            for n in ctx.doc.select(f"@style|{prop}"):
                for name, raw in style_declarations(n.attr("style") or ""):
                    if name == prop:
                        yield Value(n, prop, raw, styled, True, raw)


def said(ctx: RuleCtx, v: Value, *, rule: str, code: str, why: str) -> Finding:
    """A finding about one value, naming where it is written and what it should be."""
    return finding(
        ctx, v.node, rule=rule, code=code, construct=v.construct, msg=f"{v.where()}: {why}"
    )


_INDEX: dict[int, tuple[ConstructTable, dict[str, str]]] = {}


def _rows(table: ConstructTable) -> dict[str, str]:
    """The native rows' selectors to their ids, built once a table."""
    kept = _INDEX.get(id(table))
    if kept is not None and kept[0] is table:
        return kept[1]
    built = {r.selector: r.id for r in table.rows if r.disposition is Disposition.NATIVE}
    _INDEX[id(table)] = (table, built)
    return built


def _settle(table: ConstructTable, construct: str, raw: str) -> str:
    value = raw
    for row in table.rows:
        if row.normalizes_to == construct and row.normalizer is not None:
            value = BY_NAME[row.normalizer](value)
    return value
