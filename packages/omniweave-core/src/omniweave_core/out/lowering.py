"""Preflight check 1, every target's: each construct a unit uses resolves in its `lower/`. **D795.**

09-generation.md section 5.2: *"`maps_to` is the whole mapping table ... There is no dispatch
dictionary maintained by hand and no `getattr` on a construct id"*, and section 5.1's preflight
check 1 refuses a construct whose `maps_to` names nothing before a byte is written (OUT1). docx
built this check for itself (D782). pptx needs the same check, so it lives here, once (INV-21).

## Rulings

1. **A `maps_to` resolves to a callable its family module exports.** `lower.shapes:rect` is the
   name `rect` in the `__all__` of the module the target registers as `lower.shapes`. A private
   name, a name the module does not export, and a non-callable all resolve to nothing. The
   target hands over its family modules, which it imports itself: `importlib.import_module` is
   the host's alone (INV-4, G8).
2. **Only the constructs a unit uses are asked.** A table may declare rows its lowering does not
   build yet, as pptx's does while its lowering lands a family at a time. A unit that uses one
   is refused with `OW_TARGET_CONSTRUCT_UNMAPPED`, naming every such construct and its
   `maps_to`, and a unit that does not compiles.
3. **A value a `normalize` row would rewrite does not reach the package** (09 section 5.3,
   `OW_TARGET_NORMALIZE_AT_COMPILE`). The compile is refused naming each such value's row and
   place, up to three, with the count. docx built this for itself (D782), and pptx needs it too.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import CarrierNode, Selector, parse_selector
from omniweave_core.out.constructs import Construct, ConstructTable, Disposition

__all__ = [
    "Row",
    "refuse_normalizable",
    "refuse_unmapped",
    "resolve",
    "rows_of",
    "unmapped",
    "walk",
]


@dataclass(frozen=True, slots=True)
class Row:
    """One native row with its selector parsed: what a node matches for the row's function."""

    construct: Construct
    selector: Selector


def rows_of(table: ConstructTable) -> tuple[Row, ...]:
    """The table's native rows, in table order."""
    return tuple(
        Row(row, parse_selector(row.selector, table.carrier))
        for row in table.rows
        if row.disposition is Disposition.NATIVE
    )


def resolve(maps_to: str, families: Mapping[str, ModuleType]) -> Callable[..., Any] | None:
    """Ruling 1: `lower.shapes:rect` to its function, or `None` when it is not built."""
    module, _, symbol = maps_to.partition(":")
    family = families.get(module)
    if family is None or symbol.startswith("_") or symbol not in getattr(family, "__all__", ()):
        return None
    found = getattr(family, symbol)  # a name the table holds and the module exports
    return found if callable(found) else None


def walk(root: CarrierNode) -> Iterator[CarrierNode]:
    """`root` and every element below it, in document order."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(list(node.children())))


def unmapped(
    roots: Sequence[CarrierNode], rows: Sequence[Row], families: Mapping[str, ModuleType]
) -> list[Construct]:
    """Ruling 2: each row the units use whose `maps_to` this `lower/` does not define."""
    used: dict[str, Construct] = {}
    for root in roots:
        for node in walk(root):
            for row in rows:
                if row.selector.matches(node):
                    used.setdefault(row.construct.id, row.construct)
    return [c for c in used.values() if resolve(c.maps_to or "", families) is None]


def refuse_unmapped(missing: Sequence[Construct], target: str) -> None:
    """Ruling 2: one refusal naming every construct the units use and the lowering lacks."""
    if missing:
        named = ", ".join(f"{c.id} ({c.maps_to})" for c in missing)
        raise TargetError(
            f"the units use constructs this compiler cannot lower: {named}",
            symbol="OW_TARGET_CONSTRUCT_UNMAPPED",
            fix=f"ow out constructs {target} --construct {missing[0].id}",
        )


def refuse_normalizable(
    roots: Sequence[CarrierNode],
    table: ConstructTable,
    normalizers: Mapping[str, Callable[[str], str]],
) -> None:
    """Ruling 3: a compile of values a `normalize` row would still rewrite is refused."""
    found: list[str] = []
    for row in table.rows:
        if row.disposition is not Disposition.NORMALIZE:
            continue
        name = parse_selector(row.selector, table.carrier).name
        settle = normalizers[row.normalizer or ""]
        for root in roots:
            for node in walk(root):
                value = node.attr(name)
                if value is not None and settle(value) != value:
                    found.append(f"{row.id} at {node.at}")
    if found:
        raise TargetError(
            f"{len(found)} value(s) are not in canonical form: {', '.join(found[:3])}",
            symbol="OW_TARGET_NORMALIZE_AT_COMPILE",
            fix="ow out normalize   # then check and compile again",
        )
