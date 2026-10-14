"""Construct conformance, generated from the table: `table_pack()`. **D781.**

09-generation.md section 4.4's band table puts *"one rule per ConstructTable disposition class"*
at orders 20-39, and section 3.5 item 1 makes `unknown_construct = "forbidden"` the table's
own promise: *"A construct not in the table is an error."* Neither needs a target's judgement,
only its table, so the rules are built from the table here rather than hand-written per target,
where a second copy of a row's selector could disagree with the row.

## Rulings

1. **Four rules, each present only when the table has rows for it.** Order 20 reports every node a
   `forbidden` row's selector matches, with the row's code and `msg`. Order 21 reports every node
   a `forbidden_when` row's selector matches in a unit where the condition holds, through
   `ConstructTable.conditional()`, so the condition is evaluated in one place (09 section 3.1
   rule 5). Order 22 is the closed set. Order 23 is one folded warning per `normalize` row.
2. **The closed set is three questions about each node.** Does an element row match the element?
   Does an attribute row, or the qualifier of an element row that matched, name each attribute?
   Does a `@style|<prop>` row name each property its `style` declares? A table with no
   sub-property row declares `style` only through an `@style` row. A node no element row matches
   is reported once, and its attributes are not, because they belong to a construct that does not
   exist. Its children are still checked.
3. **An `ignore` selector removes what it matches from the question.** An ignored element is
   skipped with its subtree, since its content is no construct of the artefact (`svg|metadata`
   holds RDF in other namespaces). An ignored attribute or property is skipped where it occurs.
4. **The closed set's code is `OW_TARGET_CONSTRUCT_NOT_IN_TABLE`** (`OW-T-412`, appended). Its
   fix lists the table, `ow out constructs <target>`, because no row exists to name.
5. **A `normalize` row's warning reads the attribute its selector names.** The rule reports
   every value the normalizer would change, folded to one finding a row a unit with a count, at
   most three examples and the row's `canonical`, which is the value-rewrite `ow out normalize`
   applies (D768 ruling 4). A `normalize` row whose inherited selector is an element or a style
   property names no value, and `ow out normalize` refuses it, so `table_pack()` refuses it too,
   as `OW_TARGET_CONSTRUCTS_INVALID`, when the pack is built.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Final

from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import CarrierNode, Selector, parse_selector, style_declarations
from omniweave_core.out.constructs import Construct, ConstructTable, Disposition
from omniweave_core.out.finding import Finding, Provenance, Severity
from omniweave_core.out.rules import RuleCtx, RuleSpec

__all__ = ["NOT_IN_TABLE", "table_pack", "undeclared"]

NOT_IN_TABLE: Final = "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"
_STYLE: Final = "style"


def table_pack(
    table: ConstructTable, target: str, normalizers: Mapping[str, Callable[[str], str]]
) -> tuple[RuleSpec, ...]:
    """Ruling 1's rules for one table, in order. `normalizers` is the target's by name."""
    forbidden = tuple(r for r in table.rows if r.disposition is Disposition.FORBIDDEN)
    conditional = tuple(r for r in table.rows if r.forbidden_when is not None)
    normalize = tuple(r for r in table.rows if r.disposition is Disposition.NORMALIZE)
    for row in normalize:
        if parse_selector(row.selector, table.carrier).kind != "attribute":
            raise TargetError(
                f"construct {row.id!r} normalizes {row.selector!r}, which names no attribute "
                "value to rewrite (ruling 5)",
                symbol="OW_TARGET_CONSTRUCTS_INVALID",
                fix="ow explain OW-T-009",
            )
    specs: list[RuleSpec] = []
    if forbidden:
        specs.append(
            RuleSpec(
                f"ow.{target}.forbidden@1",
                20,
                "unit",
                frozenset(r.code for r in forbidden),
                _rows_rule(forbidden, target, f"ow.{target}.forbidden@1"),
            )
        )
    if conditional:
        specs.append(
            RuleSpec(
                f"ow.{target}.forbidden-when@1",
                21,
                "unit",
                frozenset(r.code for r in conditional),
                _conditional_rule(table, target, f"ow.{target}.forbidden-when@1"),
            )
        )
    specs.append(
        RuleSpec(
            f"ow.{target}.closed@1",
            22,
            "unit",
            frozenset({NOT_IN_TABLE}),
            _closed_rule(table, target, f"ow.{target}.closed@1"),
        )
    )
    if normalize:
        specs.append(
            RuleSpec(
                f"ow.{target}.normalize@1",
                23,
                "unit",
                frozenset(r.code for r in normalize),
                _normalize_rule(table, normalize, normalizers, f"ow.{target}.normalize@1"),
            )
        )
    return tuple(specs)


def undeclared(table: ConstructTable, root: CarrierNode) -> Iterator[tuple[CarrierNode, str]]:
    """Ruling 2: each node under `root` no row declares, with what is undeclared about it."""
    rows = [parse_selector(r.selector, table.carrier) for r in table.rows]
    ignored = [parse_selector(s, table.carrier) for s in table.ignore]
    elements = [s for s in rows if s.kind == "element"]
    attributes = {s.name for s in rows if s.kind == "attribute"}
    props = {s.prop for s in rows if s.kind == "subproperty"}
    skip_elements = [s for s in ignored if s.kind == "element"]
    skip_attributes = {s.name for s in ignored if s.kind == "attribute"}
    skip_props = {s.prop for s in ignored if s.kind == "subproperty"}
    stack = [root]
    while stack:
        node = stack.pop()
        if any(s.matches(node) for s in skip_elements):
            continue
        stack.extend(reversed(list(node.children())))
        matched = [s for s in elements if s.matches(node)]
        if not matched:
            yield node, f"<{_local(node.tag)}>"
            continue
        named = attributes | {s.name for s in matched if s.name}
        yield from _attributes(node, named, skip_attributes, props, skip_props)


def _attributes(
    node: CarrierNode,
    named: set[str],
    skip: set[str],
    props: set[str],
    skip_props: set[str],
) -> Iterator[tuple[CarrierNode, str]]:
    for name, value in node.attrs().items():
        if name in named or name in skip:
            continue
        if name == _STYLE and props:
            for prop, _ in style_declarations(value):
                if prop not in props and prop not in skip_props:
                    yield node, f"style property {prop!r}"
            continue
        yield node, f"attribute {name!r}"


def _rows_rule(
    rows: Sequence[Construct], target: str, rule: str
) -> Callable[[RuleCtx], Iterable[Finding]]:
    def fn(ctx: RuleCtx) -> Iterator[Finding]:
        if ctx.doc is None or ctx.unit is None:
            return
        for row in rows:
            for n in ctx.doc.select(row.selector):
                yield _row_finding(
                    row, n, unit=ctx.unit.id, target=target, rule=rule, msg=row.msg or row.id
                )

    return fn


def _conditional_rule(
    table: ConstructTable, target: str, rule: str
) -> Callable[[RuleCtx], Iterable[Finding]]:
    def fn(ctx: RuleCtx) -> Iterator[Finding]:
        if ctx.doc is None or ctx.unit is None:
            return
        for row in table.conditional(ctx.doc):
            why = row.msg or f"{row.id} is forbidden in a unit holding {row.forbidden_when}"
            for n in ctx.doc.select(row.selector):
                yield _row_finding(row, n, unit=ctx.unit.id, target=target, rule=rule, msg=why)

    return fn


def _closed_rule(
    table: ConstructTable, target: str, rule: str
) -> Callable[[RuleCtx], Iterable[Finding]]:
    def fn(ctx: RuleCtx) -> Iterator[Finding]:
        if ctx.doc is None or ctx.unit is None:
            return
        for n, what in undeclared(table, ctx.doc.root()):
            where = what if what.startswith("<") else f"{what} on <{_local(n.tag)}>"
            yield Finding(
                code=NOT_IN_TABLE,
                severity=Severity.ERROR,
                provenance=Provenance.INTRODUCED,
                rule=rule,
                unit=ctx.unit.id,
                msg=f'{where} is no construct of {table.il}, and unknown_construct = "forbidden"',
                fix=f"ow out constructs {target}   # the constructs {table.il} has",
                at=n.at,
                el=n.el,
            )

    return fn


def _normalize_rule(
    table: ConstructTable,
    rows: Sequence[Construct],
    normalizers: Mapping[str, Callable[[str], str]],
    rule: str,
) -> Callable[[RuleCtx], Iterable[Finding]]:
    selectors: dict[str, Selector] = {r.id: parse_selector(r.selector, table.carrier) for r in rows}

    def fn(ctx: RuleCtx) -> Iterator[Finding]:
        if ctx.doc is None or ctx.unit is None:
            return
        for row in rows:
            name = selectors[row.id].name
            normalizer = normalizers[row.normalizer or ""]
            bad = [
                (n, value)
                for n in ctx.doc.select(row.selector)
                if (value := n.attr(name) or "") != normalizer(value)
            ]
            if not bad:
                continue
            first = bad[0][0]
            yield Finding(
                code=row.code,
                severity=Severity.WARNING,
                provenance=Provenance.INTRODUCED,
                rule=rule,
                unit=ctx.unit.id,
                construct=row.id,
                canonical=row.canonical,
                msg=f"{len(bad)} {name} value(s) are not in canonical form",
                fix=f"ow out normalize --unit {ctx.unit.id} --construct {row.id}",
                count=len(bad),
                examples=tuple(value for _, value in bad[:3]),
                at=first.at,
                el=first.el,
            )

    return fn


def _row_finding(
    row: Construct, n: CarrierNode, *, unit: str, target: str, rule: str, msg: str
) -> Finding:
    return Finding(
        code=row.code,
        severity=Severity.ERROR,
        provenance=Provenance.INTRODUCED,
        rule=rule,
        unit=unit,
        construct=row.id,
        msg=f"<{_local(n.tag)}>: {msg}",
        fix=f"ow out constructs {target} --construct {row.id}",
        at=n.at,
        el=n.el,
    )


def _local(tag: str) -> str:
    return tag.partition("|")[2] or tag
