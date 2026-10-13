"""`compile.pptx.native`: owsvg/1's card, table, carrier and gate (09 section 12.1). D789.

The card loads through `load_card()` and `CompileCard.of()`, the table through
`ConstructTable.load()` with the target's own normalizers, and the gate runs through
`omniweave_core.out.compile.check()`, the framework's half, over a JobDir in `tmp_path`. Each
structural rule has its own test file, `test_pptx_rule_<rule>.py`. The compile is refused by
name until lowering lands.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import TargetError, explain
from omniweave_core.host.activate import normalizers as host_normalizers
from omniweave_core.model.enums import Kind
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.card import CompileCard
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.compile import CheckResult, CompileV1, check
from omniweave_core.out.constructs import Disposition
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.roundtrip import applicable
from omniweave_ports import ProbeStatus
from omniweave_target_pptx.driver import CARD, HERE, NORMALIZERS, REASON, PptxCompiler, table
from omniweave_target_pptx.normalizers import (
    collapse_space,
    opacity_fraction,
    px_length,
    upper_hex,
)

TABLE = table()


def _driver() -> DriverCard:
    loaded = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(loaded, DriverCard)
    return loaded


DRIVER = _driver()
COMPILED = CompileCard.of(DRIVER)
SLOT = "asset-slot:" + "ab" * 32
UNIT = OutUnit(id="u01", ord=1, il_path="il/u01.svg")
BRIEF = parse_brief(
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n## forbidden\n",
    baseline=(),
)
IL_TOML = (
    'schema = "omniweave.out-il/1"\nil = "owsvg/1"\nconstructs_digest = "'
    + TABLE.digest()
    + '"\n\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.svg"\n\n'
    '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.svg"\n'
)
SVG = '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" viewBox="0 0 1280 720"'
CLEAN = {
    "u01.svg": (
        f'{SVG} data-ow-el="u01/e1">\n'
        '  <defs><linearGradient id="sky" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#1F4E79"/>'
        "</linearGradient></defs>\n"
        '  <rect x="0" y="0" width="1280" height="720" fill="url(#sky)"/>\n'
        '  <text data-ow-el="u01/e2" x="64" y="120" font-family="Arial" font-size="44" '
        'fill="#1A1A1A">Revenue <tspan font-weight="bold">rose</tspan></text>\n'
        f'  <image href="{SLOT}" x="900" y="400" width="300" height="200"/>\n'
        '  <path d="M 0 700 L 1280 700" stroke="#C00000" stroke-width="2"/>\n'
        "</svg>"
    ),
    "u02.svg": (
        f"{SVG}>"
        '<g data-ow-manual="unverifiable_data"><text x="64" y="120">a figure nobody can verify'
        "</text></g></svg>"
    ),
}


def _job(tmp_path: Path, **files: str) -> Path:
    il = tmp_path / "il"
    il.mkdir(parents=True, exist_ok=True)
    for name, text in {"il.toml": IL_TOML, **CLEAN, **files}.items():
        (il / name).write_text(text, encoding="utf-8", newline="")
    return tmp_path


def _check(tmp_path: Path, u01: str | None = None) -> CheckResult:
    files = {} if u01 is None else {"u01.svg": u01}
    return check(
        _job(tmp_path, **files),
        PptxCompiler(),
        target="pptx",
        constructs=TABLE,
        stage="final",
        brief=BRIEF,
    )


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None = UNIT
    limits: dict[str, int] = field(default_factory=dict)
    brief: Any = None


def _codes(body: str) -> list[str]:
    """Every code the pack emits over a u01 whose root `<svg>` holds `body`."""
    compiler = PptxCompiler()
    ctx = _Ctx(compiler.carrier("il/u01.svg", f"{SVG}>{body}</svg>"))
    return [
        f.code
        for group in compiler.rules().values()
        for spec in group
        for f in spec.fn(ctx)  # type: ignore[arg-type]
    ]


# ---------------------------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------------------------


def test_the_card_is_the_slide_target_section_12_1_prints() -> None:
    c = COMPILED
    assert (c.driver, c.target, c.unit, c.carrier, c.il) == (
        "compile.pptx.native",
        "pptx",
        "slide",
        "svg",
        "owsvg/1",
    )
    assert (c.citations, c.bake, c.runtime_rules, c.toolchain) == (
        "embedded",
        "unavailable",
        False,
        "",
    )
    assert c.determinism == ("part", "byte")
    assert (c.read_back, c.fidelity, c.project) == ("parse.pptx.native", "passthrough", False)
    assert applicable(c.laws, c.fidelity).applies == ("r1", "r2", "r3", "r4", "r5", "r6", "r7")
    assert c.max_units == 2000, "09 section 14.2's roster"
    assert (c.suffix, c.media_type.endswith("presentationml.presentation")) == (".pptx", True)
    assert dict(DRIVER.compile_sibling)["provenance_part"] == (
        "customXml/omniweave-provenance.json"
    )


def test_the_card_says_not_implemented_and_why_and_names_its_table() -> None:
    assert not COMPILED.implemented
    assert COMPILED.reason == REASON
    assert "lowering to DrawingML" in REASON
    assert COMPILED.constructs_digest == TABLE.digest()
    assert COMPILED.agent_doc_tokens_max == 6000, "09 section 3.3"


def test_the_package_declares_the_driver_and_the_target() -> None:
    drivers = {e.name: e.value for e in entry_points(group="omniweave.drivers")}
    targets = {e.name: e.value for e in entry_points(group="omniweave.targets")}
    assert drivers["compile.pptx.native"] == "omniweave_target_pptx"
    assert targets["pptx"] == "omniweave_target_pptx"


# ---------------------------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------------------------


def test_the_table_is_owsvg_1_with_the_mandatory_constructs() -> None:
    assert (TABLE.carrier, TABLE.il, len(TABLE.rows)) == ("svg", "owsvg/1", 190)
    ids = {row.id for row in TABLE.rows}
    assert {"ow.cite", "ow.el", "ow.manual", "ow.unit"} <= ids
    assert TABLE.row("ow.unit").selector == "svg|svg"
    assert TABLE.ignore == ("svg|desc", "svg|title", "svg|metadata", "@version")


def test_every_code_the_table_names_is_registered() -> None:
    for row in TABLE.rows:
        assert explain(row.code).symbol == row.code


def test_the_three_rows_a_real_table_must_express_are_here() -> None:
    """09 section 3.3: a bake tier, a conditional prohibition, and the closed inline style set."""
    blend = TABLE.row("bake.blend-style")
    assert (blend.disposition, blend.code) == (Disposition.BAKE, "OW_TARGET_BLEND_REQUIRES_BAKE")
    assert blend.bake is not None and (blend.bake.renderer, blend.bake.dpi) == ("raster", 192)
    ident = TABLE.row("geom.id")
    assert (ident.forbidden_when, ident.code) == ("svg|style", "OW_TARGET_ID_WITH_STYLE")
    styled = {r.selector.removeprefix("@style|") for r in TABLE.rows if r.id.startswith("style.")}
    assert len(styled) == 30, "ppt-master's 32, less filter and shape-rendering"
    assert {"fill", "stroke", "font-size", "opacity", "stroke-dasharray", "x"} <= styled
    assert {r.disposition for r in TABLE.rows if r.id.startswith("style.")} == {Disposition.NATIVE}


def test_every_style_row_lowers_as_its_attribute_does() -> None:
    by_selector = {r.selector: r for r in TABLE.rows if r.disposition is Disposition.NATIVE}
    for row in TABLE.rows:
        if row.id.startswith("style."):
            twin = by_selector[row.selector.replace("@style|", "@")]
            assert (row.maps_to, row.code) == (twin.maps_to, twin.code), row.id


def test_every_native_row_maps_into_lower_and_every_row_is_new() -> None:
    for row in TABLE.rows:
        if row.disposition is Disposition.NATIVE:
            assert (row.maps_to or "").startswith("lower."), row.id
        assert row.since == "0.1.0"


def test_the_kind_map_names_real_kinds_over_real_rows() -> None:
    kinds = tomllib.loads((HERE / "kind_map.toml").read_text(encoding="utf-8"))["kind"]
    assert set(kinds) <= {row.id for row in TABLE.rows}
    assert Kind(kinds["ow.unit"]) is Kind.SECTION
    assert Kind(kinds["text.text"]) is Kind.PARAGRAPH
    assert Kind(kinds["shape.image"]) is Kind.PICTURE
    assert {Kind(v) for v in kinds.values()} == {
        Kind.SECTION,
        Kind.PARAGRAPH,
        Kind.CONTAINER,
        Kind.PICTURE,
        Kind.DIAGRAM,
    }


# ---------------------------------------------------------------------------------------------
# the normalizers
# ---------------------------------------------------------------------------------------------


def test_the_normalizers_are_the_ones_the_host_would_load() -> None:
    assert dict(host_normalizers(DRIVER)) == dict(NORMALIZERS)


@pytest.mark.parametrize(
    ("fn", "value", "want"),
    [
        (collapse_space, " d7#1   d7#2 ", "d7#1 d7#2"),
        (upper_hex, "#abc", "#AABBCC"),
        (upper_hex, "#1f4e79", "#1F4E79"),
        (upper_hex, " #1F4E79 ", "#1F4E79"),
        (upper_hex, "#1F4E79", "#1F4E79"),
        (upper_hex, "red", "red"),
        (upper_hex, "url(#sky)", "url(#sky)"),
        (upper_hex, "#abcd", "#abcd"),
        (px_length, "12px", "12"),
        (px_length, "-0.5px", "-0.5"),
        (px_length, ".5px", ".5"),
        (px_length, "12", "12"),
        (px_length, "12pt", "12pt"),
        (px_length, "1e3px", "1e3px"),
        (opacity_fraction, "50%", "0.5"),
        (opacity_fraction, "100%", "1"),
        (opacity_fraction, "12.50%", "0.125"),
        (opacity_fraction, "1000%", "10"),
        (opacity_fraction, "0%", "0"),
        (opacity_fraction, "0.5", "0.5"),
        (opacity_fraction, "-5%", "-5%"),
    ],
)
def test_each_normalizer_settles_in_one_step(
    fn: Callable[[str], str], value: str, want: str
) -> None:
    assert fn(value) == want
    assert fn(fn(value)) == fn(value)


# ---------------------------------------------------------------------------------------------
# the compiler
# ---------------------------------------------------------------------------------------------


def test_the_compiler_is_a_compile_v1_whose_probe_names_the_reason() -> None:
    compiler: CompileV1 = PptxCompiler()
    assert compiler.PORT == "compile/1"
    assert compiler.measure() is None
    verdict = PptxCompiler.probe(None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.UNAVAILABLE
    assert REASON in verdict.detail


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.lower(None, None, None, None),
        lambda c: c.postflight("x.pptx", None),
        lambda c: c.project(None, None),
    ],
)
def test_the_compile_is_refused_with_the_cards_reason(call: Callable[[Any], object]) -> None:
    with pytest.raises(TargetError, match="implemented = false") as caught:
        call(PptxCompiler())
    assert caught.value.code() == "OW_TARGET_NOT_IMPLEMENTED"


def test_a_slides_visible_text_is_a_line_a_text_box() -> None:
    doc = PptxCompiler().carrier("il/u01.svg", CLEAN["u01.svg"])
    assert doc.visible_text(doc.root()) == "Revenue rose"


# ---------------------------------------------------------------------------------------------
# the gate, through the framework
# ---------------------------------------------------------------------------------------------


def test_a_clean_deck_is_a_manual_required_gate(tmp_path: Path) -> None:
    result = _check(tmp_path)
    assert [(f.code, f.msg) for f in result.report.findings] == []
    assert result.status is GateStatus.MANUAL_REQUIRED, "u02's manual region"


@pytest.mark.parametrize(
    ("u01", "code"),
    [
        (f'{SVG}><svg viewBox="0 0 10 10"/></svg>', "OW_TARGET_UNIT_MALFORMED"),
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 768"/>',
         "OW_TARGET_CANVAS_MISMATCH"),
        (
            f'{SVG}><text data-ow-el="u01/e2" x="1" y="2">a</text>'
            '<text data-ow-el="u01/e2" x="1" y="9">b</text></svg>',
            "OW_TARGET_EL_DUPLICATE",
        ),
        (f'{SVG}><circle cx="1" cy="1" r="1" style="mix-blend-mode: multiply"/></svg>',
         "OW_TARGET_BLEND_REQUIRES_BAKE"),
    ],
)  # fmt: skip
def test_the_structural_rules_and_a_bake_row_fail_the_gate(
    tmp_path: Path, u01: str, code: str
) -> None:
    result = _check(tmp_path, u01)
    assert result.status is GateStatus.FAILED
    assert code in {f.code for f in result.report.findings}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("<script>1</script>", "OW_TARGET_SCRIPT_FORBIDDEN"),
        ('<rect width="1" height="1" onclick="x()"/>', "OW_TARGET_SCRIPT_FORBIDDEN"),
        ("<style>rect{}</style>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ('<rect class="a" width="1" height="1"/>', "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<foreignObject/>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ('<text x="1" y="1"><textPath>a</textPath></text>', "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<mask/>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<animate/>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ('<use xlink:href="#a" xmlns:xlink="http://www.w3.org/1999/xlink"/>',
         "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ('<path d="M0 0" fill-rule="evenodd"/>', "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ('<rect width="1" height="1" style="filter: url(#f)"/>', "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<switch/>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<feTurbulence/>", "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
        ('<rect width="1" height="1" title="t"/>', "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
        ('<rect width="1" height="1" style="cursor: pointer"/>',
         "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
    ],
)  # fmt: skip
def test_the_table_closes_the_il(body: str, code: str) -> None:
    assert _codes(body) == [code]


def test_ignored_constructs_say_nothing() -> None:
    assert _codes("<title>Q3</title><desc>a slide</desc><metadata><x/></metadata>") == []


def test_id_is_native_until_a_cascade_is_present() -> None:
    assert _codes('<rect id="a" width="1" height="1"/>') == []
    found = _codes('<style>rect{}</style><rect id="a" width="1" height="1"/>')
    assert sorted(found) == ["OW_TARGET_CONSTRUCT_FORBIDDEN", "OW_TARGET_ID_WITH_STYLE"]


def test_the_normalize_rows_warn_and_the_gate_still_passes(tmp_path: Path) -> None:
    result = _check(
        tmp_path,
        f'{SVG}><rect data-ow-cite=" d7#1 " x="4px" y="4" width="10" height="10" fill="#abc" '
        'opacity="50%"/></svg>',
    )
    assert result.status is GateStatus.MANUAL_REQUIRED, "u02's manual region, not a warning"
    assert sorted(f.code for f in result.report.findings) == [
        "OW_TARGET_CITE_SPACING",
        "OW_TARGET_FILL_NOT_UPPER_HEX",
        "OW_TARGET_LENGTH_UNIT",
        "OW_TARGET_OPACITY_PERCENT",
    ]
    assert result.introduced_warning_count == 4
