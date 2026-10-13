"""`omniweave_core.out.conformance`: construct conformance, built from the table. D781.

Each test parses one unit with the `html` carrier and calls a rule `table_pack()` built, through a
`RuleCtx` holding only what these rules read. The table is small and synthetic, so every row
kind the pack reads (forbidden, `forbidden_when`, normalize, a sub-property, an element
qualifier, an `ignore`) is in it once.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.model.enums import Quote
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.cites import CitedBlock
from omniweave_core.out.conformance import (
    CITE_FACTS,
    CITE_UNRESOLVED,
    NOT_IN_TABLE,
    cite_pack,
    table_pack,
    undeclared,
)
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import Finding, Severity
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.rules import RuleSpec


def _upper(value: str) -> str:
    return value.upper()


NORMALIZERS: Mapping[str, Callable[[str], str]] = {"upper": _upper}


def _native(id_: str, selector: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "selector": selector,
        "disposition": "native",
        "round_trip": "exact",
        "canonical": "as written",
        "maps_to": f"lower.x:{id_.replace('.', '_')}",
        "code": "OW_TARGET_TEXT_INVALID",
        "since": "0.1.0",
        **extra,
    }


def _raw(**top: Any) -> dict[str, Any]:
    return {
        "schema": "omniweave.out-constructs/1",
        "carrier": "html",
        "il": "owtest/1",
        "version": 1,
        "unknown_construct": "forbidden",
        "ignore": ["html|template", "@data-scratch", "@style|caret-color"],
        "construct": [
            _native("ow.cite", "@data-ow-cite"),
            _native("ow.el", "@data-ow-el"),
            _native("ow.manual", "html|div[data-ow-manual]"),
            _native("ow.unit", "html|section"),
            _native("block.p", "html|p"),
            _native("link.a", "html|a[href]"),
            _native("style.align", "@style|text-align"),
            _native("attr.id", "@id", forbidden_when="html|style", msg="an id beside a cascade"),
            _native("attr.lang", "@lang"),
            {
                "id": "attr.lang.case",
                "normalizes_to": "attr.lang",
                "disposition": "normalize",
                "normalizer": "upper",
                "round_trip": "normalized",
                "canonical": "upper case",
                "severity": "warning",
                "code": "OW_TARGET_LANG_CASE",
                "since": "0.1.0",
            },
            {
                "id": "forbid.script",
                "selector": "html|script",
                "disposition": "forbidden",
                "round_trip": "dropped",
                "msg": "no scripts",
                "code": "OW_TARGET_SCRIPT_FORBIDDEN",
                "since": "0.1.0",
            },
            {
                "id": "pos.float",
                "selector": "@style|float",
                "disposition": "forbidden",
                "round_trip": "dropped",
                "msg": "no geometry",
                "code": "OW_TARGET_POSITIONING_FORBIDDEN",
                "since": "0.1.0",
            },
            {
                "id": "forbid.style",
                "selector": "html|style",
                "disposition": "forbidden",
                "round_trip": "dropped",
                "msg": "no cascade",
                "code": "OW_TARGET_CONSTRUCT_FORBIDDEN",
                "since": "0.1.0",
            },
        ],
        **top,
    }


TABLE = ConstructTable.parse(_raw(), NORMALIZERS, source="test.toml")
PACK = table_pack(TABLE, "owtest", NORMALIZERS)
UNIT = OutUnit(id="u01", ord=1, il_path="il/u01.html")


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None = UNIT
    limits: Mapping[str, int] = field(default_factory=dict)


def _run(rule: RuleSpec, text: str) -> list[Finding]:
    doc = html_carrier("il/u01.html", text, strict=True)
    return list(rule.fn(_Ctx(doc)))  # type: ignore[arg-type]


def _rule(suffix: str) -> RuleSpec:
    [spec] = [s for s in PACK if s.id == f"ow.owtest.{suffix}@1"]
    return spec


def _all(text: str) -> list[Finding]:
    return [f for spec in PACK for f in _run(spec, text)]


# ---------------------------------------------------------------------------------------------
# ruling 1: the pack's shape
# ---------------------------------------------------------------------------------------------


def test_the_pack_is_four_rules_in_the_construct_band_with_every_code_declared() -> None:
    assert [(s.id, s.order, s.scope) for s in PACK] == [
        ("ow.owtest.forbidden@1", 20, "unit"),
        ("ow.owtest.forbidden-when@1", 21, "unit"),
        ("ow.owtest.closed@1", 22, "unit"),
        ("ow.owtest.normalize@1", 23, "unit"),
    ]
    assert _rule("forbidden").codes == {
        "OW_TARGET_SCRIPT_FORBIDDEN",
        "OW_TARGET_POSITIONING_FORBIDDEN",
        "OW_TARGET_CONSTRUCT_FORBIDDEN",
    }
    assert _rule("forbidden-when").codes == {"OW_TARGET_TEXT_INVALID"}
    assert _rule("closed").codes == {NOT_IN_TABLE}
    assert _rule("normalize").codes == {"OW_TARGET_LANG_CASE"}


def test_a_table_without_those_rows_gets_only_the_closed_set() -> None:
    raw = _raw()
    raw["construct"] = [r for r in raw["construct"] if r["disposition"] == "native"]
    for row in raw["construct"]:
        row.pop("forbidden_when", None)
    table = ConstructTable.parse(raw, NORMALIZERS, source="bare.toml")
    assert [s.id for s in table_pack(table, "bare", NORMALIZERS)] == ["ow.bare.closed@1"]


def test_a_clean_unit_meets_every_rule() -> None:
    clean = (
        '<section data-ow-el="u01/e1"><p data-ow-el="u01/e2" lang="EN" '
        'style="text-align: center" data-ow-cite="d1#1">x <a href="#u01/e2">y</a></p>'
        '<div data-ow-manual="unverifiable_data">z</div></section>'
    )
    assert _all(clean) == []


# ---------------------------------------------------------------------------------------------
# order 20 and 21: the forbidden rows, unconditional and conditional
# ---------------------------------------------------------------------------------------------


def test_a_forbidden_row_reports_each_node_with_its_own_code_and_message() -> None:
    found = _run(
        _rule("forbidden"),
        '<section><p style="float: left">x</p><script>1</script><script>2</script></section>',
    )
    assert [(f.code, f.construct) for f in found] == [
        ("OW_TARGET_SCRIPT_FORBIDDEN", "forbid.script"),
        ("OW_TARGET_SCRIPT_FORBIDDEN", "forbid.script"),
        ("OW_TARGET_POSITIONING_FORBIDDEN", "pos.float"),
    ]
    assert found[2].msg == "<p>: no geometry"
    assert found[2].fix == "ow out constructs owtest --construct pos.float"
    assert {f.severity for f in found} == {Severity.ERROR}
    assert found[0].at == "il/u01.html:1:38"


def test_a_forbidden_when_row_fires_only_in_a_unit_holding_its_condition() -> None:
    plain = '<section><p id="a">x</p></section>'
    assert _run(_rule("forbidden-when"), plain) == []
    cascaded = '<section><style>p{}</style><p id="a">x</p></section>'
    [found] = _run(_rule("forbidden-when"), cascaded)
    assert (found.code, found.construct, found.msg) == (
        "OW_TARGET_TEXT_INVALID",
        "attr.id",
        "<p>: an id beside a cascade",
    )


# ---------------------------------------------------------------------------------------------
# order 22, rulings 2 and 3: the closed set
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("<section><blink>x</blink></section>", "<blink>"),
        ("<section><div>x</div></section>", "<div>"),
        ("<section><a>x</a></section>", "<a>"),
        ('<section><p title="t">x</p></section>', "attribute 'title'"),
        ('<section><p href="#x">x</p></section>', "attribute 'href'"),
        ('<section><p style="color: red">x</p></section>', "style property 'color'"),
    ],
)
def test_what_no_row_declares_is_refused(text: str, what: str) -> None:
    [found] = _run(_rule("closed"), text)
    assert found.code == NOT_IN_TABLE
    assert found.msg.startswith(what)
    assert 'unknown_construct = "forbidden"' in found.msg
    assert found.fix.startswith("ow out constructs owtest")
    assert found.construct is None


def test_an_undeclared_element_is_one_finding_and_its_children_are_still_read() -> None:
    found = list(
        undeclared(
            TABLE,
            html_carrier(
                "il/u01.html",
                '<section><blink title="t" x="y"><p title="u">x</p></blink></section>',
                strict=True,
            ).root(),
        )
    )
    assert [(n.tag, what) for n, what in found] == [
        ("html|blink", "<blink>"),
        ("html|p", "attribute 'title'"),
    ]


def test_an_element_qualifier_declares_its_attribute_on_that_element_only() -> None:
    assert _run(_rule("closed"), '<section><a href="#u01/e1">x</a></section>') == []
    assert _run(_rule("closed"), '<section><div data-ow-manual="x">x</div></section>') == []


def test_ignore_removes_an_element_with_its_subtree_and_an_attribute_or_property() -> None:
    text = (
        '<section data-scratch="1"><template><blink>x</blink></template>'
        '<p style="caret-color: red; text-align: start">y</p></section>'
    )
    assert _run(_rule("closed"), text) == []


def test_a_table_with_no_style_row_declares_style_only_through_an_attribute_row() -> None:
    raw = _raw(ignore=[])
    raw["construct"] = [
        r for r in raw["construct"] if not str(r.get("selector", "")).startswith("@style|")
    ]
    table = ConstructTable.parse(raw, NORMALIZERS, source="t.toml")
    doc = html_carrier("il/u01.html", '<section style="">x</section>', strict=True)
    assert [what for _, what in undeclared(table, doc.root())] == ["attribute 'style'"]
    raw["construct"].append(_native("attr.style", "@style"))
    table = ConstructTable.parse(raw, NORMALIZERS, source="t.toml")
    doc = html_carrier("il/u01.html", '<section style="color: red">x</section>', strict=True)
    assert list(undeclared(table, doc.root())) == []


# ---------------------------------------------------------------------------------------------
# order 23, ruling 5: normalize warnings
# ---------------------------------------------------------------------------------------------


def test_a_normalize_row_is_one_folded_warning_a_unit_with_its_canonical() -> None:
    text = (
        '<section><p lang="en">a</p><p lang="EN">b</p><p lang="fr">c</p><p lang="de">d</p>'
        '<p lang="it">e</p></section>'
    )
    [found] = _run(_rule("normalize"), text)
    assert (found.code, found.severity, found.count, found.canonical) == (
        "OW_TARGET_LANG_CASE",
        Severity.WARNING,
        4,
        "upper case",
    )
    assert found.examples == ("en", "fr", "de")
    assert found.construct == "attr.lang.case"
    assert found.fix == "ow out normalize --unit u01 --construct attr.lang.case"
    assert found.at == "il/u01.html:1:10"


def test_a_normalize_row_over_an_element_or_a_property_is_refused_at_build() -> None:
    raw = _raw()
    [row] = [r for r in raw["construct"] if r["id"] == "attr.lang.case"]
    row["normalizes_to"] = "block.p"
    table = ConstructTable.parse(raw, NORMALIZERS, source="t.toml")
    with pytest.raises(TargetError, match="names no attribute value") as caught:
        table_pack(table, "owtest", NORMALIZERS)
    assert caught.value.code() == "OW_TARGET_CONSTRUCTS_INVALID"


# ---------------------------------------------------------------------------------------------
# ruling 6: a bake row is order 24, and its severity is the card's (D789)
# ---------------------------------------------------------------------------------------------

BAKE_ROW: dict[str, Any] = {
    "id": "style.shadow",
    "selector": "@style|text-shadow",
    "disposition": "bake",
    "round_trip": "lossy",
    "code": "OW_TARGET_SHADOW_REQUIRES_BAKE",
    "bake": {"renderer": "raster", "dpi": 192, "role": "bake"},
    "since": "0.1.0",
}
SHADOWED = '<section><p style="text-shadow: 1px 1px red">x</p><p>y</p></section>'


def _baked(bake: str) -> RuleSpec:
    raw = _raw()
    raw["construct"].append(BAKE_ROW)
    table = ConstructTable.parse(raw, NORMALIZERS, source="baked.toml")
    [spec] = [s for s in table_pack(table, "owtest", NORMALIZERS, bake=bake) if s.order == 24]
    return spec


def test_a_bake_row_is_an_error_while_the_cards_bake_is_unavailable() -> None:
    spec = _baked("unavailable")
    assert (spec.id, spec.codes) == ("ow.owtest.bake@1", {"OW_TARGET_SHADOW_REQUIRES_BAKE"})
    [found] = _run(spec, SHADOWED)
    assert (found.severity, found.construct, found.fix) == (
        Severity.ERROR,
        "style.shadow",
        "ow out constructs owtest --construct style.shadow",
    )
    assert found.msg == (
        "<p>: @style|text-shadow needs the bake tier (raster at 192 dpi), and this target's bake "
        "is unavailable"
    )


def test_a_bake_row_is_a_warning_once_the_cards_bake_is_available() -> None:
    [found] = _run(_baked("available"), SHADOWED)
    assert (found.severity, found.msg) == (
        Severity.WARNING,
        "<p>: @style|text-shadow is baked (raster at 192 dpi), a lossy raster degradation",
    )
    assert _run(_baked("available"), "<section><p>y</p></section>") == []


# ---------------------------------------------------------------------------------------------
# ruling 7: the cite rules, every target's, built from the table (D791)
# ---------------------------------------------------------------------------------------------


class _Cites:
    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def by_cite(self, cite: str) -> CitedBlock | None:
        return self.by_cites((cite,))[cite]

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]:
        self.batches.append(cites)
        known = CitedBlock("d7#1", 101, 7, 1, "Revenue rose.", Quote.VERBATIM, 0)
        return {c: known if c == "d7#1" else None for c in cites}


@dataclass
class _CiteCtx:
    doc: CarrierDoc | None
    cites: _Cites
    unit: OutUnit | None = UNIT


def _with_facts() -> ConstructTable:
    raw = _raw()
    raw["construct"] += [
        _native("cite.kind", "@data-ow-cite-kind"),
        _native("cite.span", "@data-ow-cite-span"),
    ]
    return ConstructTable.parse(raw, NORMALIZERS, source="facts.toml")


def _cited(spec: RuleSpec, text: str, cites: _Cites | None = None) -> list[Finding]:
    doc = html_carrier("il/u01.html", text, strict=True)
    return list(spec.fn(_CiteCtx(doc, cites or _Cites())))  # type: ignore[arg-type]


def test_the_cite_pack_is_named_for_its_target_and_has_facts_only_where_rows_do() -> None:
    assert [(s.id, s.order, s.needs) for s in cite_pack(_with_facts(), "pptx")] == [
        ("pptx.cite.facts@1", 58, frozenset()),
        ("pptx.cite.resolves@1", 80, frozenset({"cites"})),
    ]
    assert [s.id for s in cite_pack(TABLE, "owtest")] == ["owtest.cite.resolves@1"]
    [facts, resolves] = cite_pack(_with_facts(), "pptx")
    assert (facts.codes, resolves.codes) == ({CITE_FACTS}, {CITE_UNRESOLVED})


def test_every_cite_on_a_unit_resolves_in_one_batch() -> None:
    cites = _Cites()
    [resolves] = cite_pack(TABLE, "owtest")
    found = _cited(
        resolves,
        '<section><p data-ow-cite="d7#1 d7#9">a</p><p data-ow-cite="d7#9 d7#1">b</p></section>',
        cites,
    )
    assert cites.batches == [("d7#1", "d7#9")]
    assert [(f.construct, f.msg, f.fix) for f in found] == [
        ("ow.cite", "cite 'd7#9' resolves to no live block in this corpus", "ow open d7#9")
    ] * 2
    assert _cited(resolves, "<section><p>x</p></section>", cites) == []
    assert cites.batches == [("d7#1", "d7#9")], "a unit with no cite asks nothing"


@pytest.mark.parametrize(
    ("attrs", "construct", "said"),
    [
        ('data-ow-cite-kind="hearsay"', "cite.kind", "data-ow-cite-kind='hearsay' is not one of"),
        ('data-ow-cite-span="4:4"', "cite.span", "data-ow-cite-span='4:4' is not a:b with a < b"),
        ('data-ow-cite-span="a:9"', "cite.span", "data-ow-cite-span='a:9'"),
        ('data-ow-cite-span="9"', "cite.span", "data-ow-cite-span='9'"),
    ],
)
def test_a_cites_facts_are_its_rows(attrs: str, construct: str, said: str) -> None:
    [facts, _] = cite_pack(_with_facts(), "pptx")
    [found] = _cited(facts, f'<section><p data-ow-cite="d7#1" {attrs}>x</p></section>')
    assert (found.code, found.construct) == (CITE_FACTS, construct)
    assert said in found.msg
    assert found.fix == f"ow out constructs pptx --construct {construct}"


def test_stated_facts_pass() -> None:
    [facts, _] = cite_pack(_with_facts(), "pptx")
    good = '<section><p data-ow-cite-kind="quote" data-ow-cite-span="0:12">x</p></section>'
    assert _cited(facts, good) == []
