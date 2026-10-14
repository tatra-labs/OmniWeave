"""`compile.docx.native`: owflow/1's card, table, carrier and rules (09 section 12.3). D781.

The card loads through `load_card()` and `CompileCard.of()`, the table through
`ConstructTable.load()` with the target's own normalizers, and every rule runs through
`omniweave_core.out.compile.check()`, the framework's half, over a JobDir in `tmp_path`. The
compile is refused by name until lowering lands, so the gate is all there is to test.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import TargetError, explain
from omniweave_core.host.activate import normalizers as host_normalizers
from omniweave_core.model.enums import Kind, Quote
from omniweave_core.out.card import CompileCard
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.cites import CitedBlock
from omniweave_core.out.compile import CheckResult, CompileV1, check
from omniweave_core.out.constructs import Disposition
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.roundtrip import applicable
from omniweave_ports import ProbeStatus
from omniweave_target_docx.driver import (
    CARD,
    HERE,
    NORMALIZERS,
    DocxCompiler,
    table,
)
from omniweave_target_docx.normalizers import bcp47_case, collapse_space, int_text
from omniweave_target_docx.rules import LIST_DEPTH_MAX

TABLE = table()


def _driver() -> DriverCard:
    loaded = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(loaded, DriverCard)
    return loaded


DRIVER = _driver()
COMPILED = CompileCard.of(DRIVER)
SLOT = "asset-slot:" + "ab" * 32
UNIT = OutUnit(id="u01", ord=1, il_path="il/u01.html")
IL_TOML = (
    'schema = "omniweave.out-il/1"\nil = "owflow/1"\nconstructs_digest = "'
    + TABLE.digest()
    + '"\n\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n\n'
    '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n'
)
CLEAN = {
    "u01.html": (
        '<section data-ow-el="u01/e1">\n'
        '  <h1 data-ow-el="u01/e2">Results</h1>\n'
        '  <p data-ow-el="u01/e3" data-ow-cite="d7#1" lang="en-GB">Revenue <strong>rose</strong>'
        ' 12%.<a data-ow-note="n1"></a></p>\n'
        "  <h2>Margins</h2>\n"
        "  <ul><li>held<ul><li>in <em>Q3</em></li></ul></li></ul>\n"
        '  <table><caption>Q3</caption><thead><tr><th colspan="2">Region</th></tr></thead>'
        '<tbody><tr><td rowspan="2">EU</td><td>1</td></tr><tr><td>2</td></tr></tbody></table>\n'
        f'  <figure><img src="{SLOT}" alt="a chart"><figcaption>Chart</figcaption></figure>\n'
        '  <p style="text-align: center" dir="ltr">See <a href="#u01/e3">above</a>.</p>\n'
        '  <aside data-ow-footnote="n1"><p>Audited.</p></aside>\n'
        "</section>"
    ),
    "u02.html": (
        "<section><h1>Outlook</h1><dl><dt>Risk</dt><dd>low</dd></dl><pre><code>x = 1</code></pre>"
        '<blockquote><p>Quoted.</p></blockquote><hr><div data-ow-manual="unverifiable_data">'
        "a figure nobody can verify</div></section>"
    ),
}


class _Cites:
    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def by_cite(self, cite: str) -> CitedBlock | None:
        return self.by_cites((cite,))[cite]

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]:
        self.batches.append(cites)
        known = CitedBlock("d7#1", 101, 7, 1, "Revenue rose 12%.", Quote.VERBATIM, 0)
        return {c: known if c == "d7#1" else None for c in cites}


def _job(tmp_path: Path, **files: str) -> Path:
    il = tmp_path / "il"
    il.mkdir(parents=True, exist_ok=True)
    for name, text in {"il.toml": IL_TOML, **CLEAN, **files}.items():
        (il / name).write_text(text, encoding="utf-8", newline="")
    return tmp_path


def _check(
    tmp_path: Path,
    u01: str | None = None,
    *,
    cites: _Cites | None = None,
    limits: Mapping[str, int] | None = None,
) -> CheckResult:
    files = {} if u01 is None else {"u01.html": u01}
    return check(
        _job(tmp_path, **files),
        DocxCompiler(),
        target="docx",
        constructs=TABLE,
        stage="final",
        cites=cites if cites is not None else _Cites(),
        limits=limits,
    )


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None = UNIT
    limits: Mapping[str, int] = field(default_factory=dict)
    cites: _Cites = field(default_factory=_Cites)


def _codes(body: str, limits: Mapping[str, int] | None = None) -> list[tuple[str, str]]:
    """Every finding the pack emits over a u01 whose `<section>` holds `body`, as (code, msg).

    The rules are called directly, because a report folds a rule's findings in a unit into one
    with a count (OUT7) and keeps the first message, and these tests read every message.
    """
    compiler = DocxCompiler()
    ctx = _Ctx(compiler.carrier("il/u01.html", f"<section>{body}</section>"), limits=limits or {})
    return [
        (f.code, f.msg)
        for group in compiler.rules().values()
        for spec in group
        for f in spec.fn(ctx)  # type: ignore[arg-type]
    ]


# ---------------------------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------------------------


def test_the_card_is_the_flow_target_section_12_3_prints() -> None:
    c = COMPILED
    assert (c.driver, c.target, c.unit, c.carrier, c.il) == (
        "compile.docx.native",
        "docx",
        "section",
        "html",
        "owflow/1",
    )
    assert (c.citations, c.bake, c.measure, c.runtime_rules, c.toolchain) == (
        "embedded",
        "unavailable",
        "none",
        False,
        "",
    )
    assert c.determinism == ("part", "byte")
    assert (c.read_back, c.fidelity, c.kind_map) == (
        "parse.docx.native",
        "patched",
        "kind_map.toml",
    )
    assert applicable(c.laws, c.fidelity).applies == ("r1", "r2", "r3", "r5", "r6", "r7")
    assert c.suffix == ".docx"
    assert c.media_type.endswith("wordprocessingml.document")
    assert dict(DRIVER.compile_sibling)["provenance_part"] == (
        "customXml/omniweave-provenance.json"
    )


def test_the_card_is_implemented_and_names_its_table() -> None:
    """D783: notes and embedded citations were the last constructs without a lowering."""
    assert (COMPILED.implemented, COMPILED.reason) == (True, "")
    assert COMPILED.constructs_digest == TABLE.digest()
    assert COMPILED.agent_doc_tokens_max > 0


def test_the_package_declares_the_driver_and_the_target() -> None:
    drivers = {e.name: e.value for e in entry_points(group="omniweave.drivers")}
    targets = {e.name: e.value for e in entry_points(group="omniweave.targets")}
    assert drivers["compile.docx.native"] == "omniweave_target_docx"
    assert targets["docx"] == "omniweave_target_docx"


# ---------------------------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------------------------


def test_the_table_is_owflow_1_with_the_mandatory_constructs() -> None:
    assert (TABLE.carrier, TABLE.il, len(TABLE.rows)) == ("html", "owflow/1", 85)
    ids = {row.id for row in TABLE.rows}
    assert {"ow.cite", "ow.el", "ow.manual", "ow.unit"} <= ids
    assert TABLE.row("ow.unit").selector == "html|section"


def test_every_code_the_table_names_is_registered() -> None:
    for row in TABLE.rows:
        assert explain(row.code).symbol == row.code


GEOMETRY = (
    "position", "float", "top", "left", "right", "bottom", "transform", "z-index", "width",
    "height", "margin", "break-before", "page-break-before", "align", "x", "y",
)  # fmt: skip


def test_no_row_but_a_forbidden_one_names_geometry() -> None:
    """Section 12.3: *"the ConstructTable has **no** `selector` matching a geometry attribute"*."""
    for row in TABLE.rows:
        named = row.selector.rpartition("|")[2].removeprefix("@")
        if named in GEOMETRY:
            assert row.disposition is Disposition.FORBIDDEN, row.id
            assert row.code == "OW_TARGET_POSITIONING_FORBIDDEN", row.id
    positioning = [row for row in TABLE.rows if row.id.startswith("pos.")]
    assert len(positioning) == 13
    assert {r.disposition for r in positioning} == {Disposition.FORBIDDEN}


def test_there_is_no_bake_row_and_every_native_row_maps_into_lower() -> None:
    assert not [r for r in TABLE.rows if r.disposition is Disposition.BAKE]
    for row in TABLE.rows:
        if row.disposition is Disposition.NATIVE:
            assert (row.maps_to or "").startswith("lower."), row.id
        assert row.since == "0.1.0"


def test_the_kind_map_names_real_kinds_over_real_rows() -> None:
    kinds = tomllib.loads((HERE / "kind_map.toml").read_text(encoding="utf-8"))["kind"]
    assert set(kinds) <= {row.id for row in TABLE.rows}
    assert Kind(kinds["block.h3"]) is Kind.HEADING
    assert Kind(kinds["note.footnote"]) is Kind.FOOTNOTE
    assert {Kind(v) for v in kinds.values()} >= {Kind.SECTION, Kind.TABLE_CELL, Kind.PICTURE}


# ---------------------------------------------------------------------------------------------
# the normalizers
# ---------------------------------------------------------------------------------------------


def test_the_normalizers_are_the_ones_the_host_would_load() -> None:
    assert dict(host_normalizers(DRIVER)) == dict(NORMALIZERS)


@pytest.mark.parametrize(
    ("fn", "value", "want"),
    [
        (collapse_space, " d7#1   d7#2 ", "d7#1 d7#2"),
        (collapse_space, "d7#1\td7#2", "d7#1 d7#2"),
        (int_text, " 02", "2"),
        (int_text, "+3", "3"),
        (int_text, "two", "two"),
        (int_text, "0", "0"),
        (bcp47_case, "EN-latn-us", "en-Latn-US"),
        (bcp47_case, "es-419", "es-419"),
        (bcp47_case, "en-GB-x-ACME", "en-GB-x-acme"),
        (bcp47_case, "en_US", "en_US"),
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


def test_the_compiler_is_a_compile_v1_whose_probe_is_ok() -> None:
    compiler: CompileV1 = DocxCompiler()
    assert compiler.PORT == "compile/1"
    assert compiler.measure() is None
    verdict = DocxCompiler.probe(None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.OK


def test_project_is_refused_by_name() -> None:
    """No Doc-to-owflow/1 projection is built, and the card says `project = false`."""
    with pytest.raises(TargetError, match="project = false") as caught:
        DocxCompiler().project(None, None)  # type: ignore[arg-type]
    assert caught.value.code() == "OW_TARGET_PROJECT_UNAVAILABLE"


def test_a_note_body_is_no_part_of_its_units_visible_text() -> None:
    doc = DocxCompiler().carrier(
        "il/u01.html",
        '<section><p>Rose.<a data-ow-note="n1"></a></p>'
        '<aside data-ow-footnote="n1"><p>Audited.</p></aside><p>Held.</p></section>',
    )
    assert doc.visible_text(doc.root()) == "Rose.\nHeld."


# ---------------------------------------------------------------------------------------------
# the rules, through the framework
# ---------------------------------------------------------------------------------------------


def test_a_clean_bundle_is_a_manual_required_gate_with_one_cite_batch(tmp_path: Path) -> None:
    cites = _Cites()
    result = _check(tmp_path, cites=cites)
    assert [(f.code, f.msg) for f in result.report.findings] == []
    assert result.status is GateStatus.MANUAL_REQUIRED
    assert cites.batches == [("d7#1",)]


def test_without_a_resolver_the_cite_rule_is_a_recorded_skip(tmp_path: Path) -> None:
    result = check(_job(tmp_path), DocxCompiler(), target="docx", constructs=TABLE, stage="final")
    assert result.status is GateStatus.UNVERIFIED
    assert [(s.rule, s.needs) for s in result.report.skipped_checks] == [
        ("docx.cite.resolves@1", "cites")
    ]


@pytest.mark.parametrize(
    ("u01", "code"),
    [
        ("<div><p>x</p></div>", "OW_TARGET_UNIT_MALFORMED"),
        ("<section><section><p>x</p></section></section>", "OW_TARGET_UNIT_MALFORMED"),
        (
            '<section><p data-ow-el="u01/e2">a</p><p data-ow-el="u01/e2">b</p></section>',
            "OW_TARGET_EL_DUPLICATE",
        ),
        ('<section><p data-ow-cite="d7#9">x</p></section>', "OW_TARGET_CITE_UNRESOLVED"),
    ],
)
def test_the_structural_rules_and_the_cite_rule_fail_the_gate(
    tmp_path: Path, u01: str, code: str
) -> None:
    result = _check(tmp_path, u01)
    assert result.status is GateStatus.FAILED
    assert code in {f.code for f in result.report.findings}


def test_positioning_is_forbidden_by_its_own_rows() -> None:
    found = _codes(
        '<p style="position: absolute; top: 4px">x</p><p style="page-break-before: always">y</p>'
        '<img src="' + SLOT + '" width="40" alt="a">',
    )
    assert {code for code, _ in found} == {"OW_TARGET_POSITIONING_FORBIDDEN"}
    assert len(found) == 4
    assert any("page breaks are the renderer's" in msg for _, msg in found)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("<script>1</script>", "OW_TARGET_SCRIPT_FORBIDDEN"),
        ("<p><b>x</b></p>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ('<p class="lead">x</p>', "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<p><ins>x</ins></p>", "OW_TARGET_CONSTRUCT_FORBIDDEN"),
        ("<p><blink>x</blink></p>", "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
        ('<p title="t">x</p>', "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
        ('<p style="color: red">x</p>', "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
        ("<div>x</div>", "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
        ("<p><span>x</span></p>", "OW_TARGET_CONSTRUCT_NOT_IN_TABLE"),
    ],
)
def test_the_table_closes_the_il(body: str, code: str) -> None:
    found = _codes(body)
    assert [c for c, _ in found] == [code]


def test_the_normalize_rows_warn_and_the_gate_still_passes(tmp_path: Path) -> None:
    result = _check(
        tmp_path,
        '<section><p data-ow-cite=" d7#1 " lang="EN-gb">x</p><table><tr><td colspan="01">a</td>'
        "</tr></table></section>",
    )
    assert result.status is GateStatus.MANUAL_REQUIRED, "u02's manual region, not a warning"
    assert sorted((f.code, f.canonical is not None) for f in result.report.findings) == [
        ("OW_TARGET_CITE_SPACING", True),
        ("OW_TARGET_LANG_CASE", True),
        ("OW_TARGET_SPAN_NOT_CANONICAL", True),
    ]
    assert result.introduced_warning_count == 3


@pytest.mark.parametrize(
    ("body", "count"),
    [
        ("<h1>a</h1><h3>b</h3>", 1),
        ("<h2>a</h2><h4>b</h4><h6>c</h6>", 2),
        ("<h3>a</h3><h1>b</h1><h2>c</h2><h3>d</h3>", 0),
    ],
)
def test_a_heading_goes_at_most_one_level_deeper(body: str, count: int) -> None:
    found = _codes(body)
    assert [c for c, _ in found] == ["OW_TARGET_HEADING_SKIP"] * count


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>", "covers 1 columns"),
        ('<table><tr><td rowspan="3">a</td></tr><tr><td>b</td></tr></table>', "runs past"),
        (
            '<table><tr><td rowspan="2">a</td><td>b</td></tr>'
            '<tr><td colspan="2">c</td></tr></table>',
            "covers 3 columns",
        ),
        (
            '<table><tr><td>a</td><td rowspan="2">b</td></tr>'
            '<tr><td colspan="2">c</td></tr></table>',
            "overlaps a cell spanning into its row",
        ),
        ('<table><tr><td colspan="two">a</td></tr></table>', "decimal integers from 1"),
        ("<table><tr><td>a</td></tr><caption>late</caption></table>", "first child"),
        ("<p>x</p><tr><td>a</td></tr>", "not a table or row group"),
        ("<table><tbody><td>a</td></tbody></table>", "not a <tr>"),
    ],
)
def test_a_table_is_a_grid_its_cells_cover_exactly(body: str, said: str) -> None:
    found = [(c, m) for c, m in _codes(body) if c == "OW_TARGET_TABLE_TOPOLOGY"]
    assert found, body
    assert any(said in m for _, m in found), found


def test_a_rowspan_is_counted_into_the_rows_it_spans() -> None:
    body = (
        '<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td rowspan="2">c</td>'
        '<td>d</td></tr><tr><td>e</td></tr></tbody><tr><td colspan="2">f</td></tr></table>'
    )
    assert _codes(body) == []


def _nested(depth: int, tag: str = "ul") -> str:
    return f"<{tag}><li>x" * depth + f"</li></{tag}>" * depth


def test_lists_nest_nine_deep_and_no_deeper() -> None:
    assert LIST_DEPTH_MAX == 9
    assert _codes(_nested(9)) == []
    [(code, msg)] = _codes(_nested(10, "ol"))
    assert code == "OW_TARGET_LIST_MALFORMED"
    assert "nested 10 deep" in msg


def test_a_limit_lowers_the_depth_and_never_raises_it() -> None:
    lowered = _codes(_nested(3), limits={"list_depth_max": 2})
    assert [c for c, _ in lowered] == ["OW_TARGET_LIST_MALFORMED"]
    raised = _codes(_nested(10), limits={"list_depth_max": 20})
    assert [c for c, _ in raised] == ["OW_TARGET_LIST_MALFORMED"]


@pytest.mark.parametrize(
    "body",
    [
        "<li>x</li>",
        "<ul><p>x</p></ul>",
        "<dt>x</dt>",
        "<dl><li>x</li></dl>",
        '<ul start="2"><li>x</li></ul>',
        '<ol start="two"><li>x</li></ol>',
    ],
)
def test_a_list_part_outside_its_container_is_malformed(body: str) -> None:
    assert "OW_TARGET_LIST_MALFORMED" in {c for c, _ in _codes(body)}


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<p>x<a data-ow-note="n9"></a></p>', "has no body"),
        ('<aside data-ow-footnote="n1"><p>y</p></aside>', "referenced 0 times"),
        (
            '<p><a data-ow-note="n1"></a><a data-ow-note="n1"></a></p>'
            '<aside data-ow-endnote="n1"><p>y</p></aside>',
            "referenced 2 times",
        ),
        (
            '<p><a data-ow-note="n1"></a></p><aside data-ow-footnote="n1"><p>y</p></aside>'
            '<aside data-ow-endnote="n1"><p>z</p></aside>',
            "names two bodies",
        ),
        ('<p><a data-ow-note="n1">1</a></p><aside data-ow-footnote="n1">y</aside>', "is empty"),
        (
            '<blockquote><p><a data-ow-note="n1"></a></p>'
            '<aside data-ow-footnote="n1">y</aside></blockquote>',
            "child of the unit's <section>",
        ),
    ],
)
def test_notes_pair_one_to_one_within_the_unit(body: str, said: str) -> None:
    found = [m for c, m in _codes(body) if c == "OW_TARGET_NOTE_UNRESOLVED"]
    assert any(said in m for m in found), found


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ("<p>a<ul><li>b</li></ul></p>", "holds inline content only"),
        ("<h1><p>a</p></h1>", "holds inline content only"),
        ("<p><strong><p>a</p></strong></p>", "holds inline content only"),
        ("<figcaption>a</figcaption>", "inside <figure> only"),
        ('<p style="text-align: middle">a</p>', "not start, center, end or justify"),
        ('<p dir="up">a</p>', "ltr or rtl"),
        ('<p><a href="javascript:alert(1)">a</a></p>', "mailto: URI"),
    ],
)
def test_the_content_model_and_three_values(body: str, said: str) -> None:
    found = [m for c, m in _codes(body) if c == "OW_TARGET_TEXT_INVALID"]
    assert any(said in m for m in found), found


@pytest.mark.parametrize("src", ["https://cdn/x.png", "x.png", "data:image/png;base64,AA", ""])
def test_a_picture_is_a_frozen_slot_and_nothing_else(src: str) -> None:
    found = _codes(f'<img src="{src}" alt="a">')
    assert [c for c, _ in found] == ["OW_TARGET_IL_ASSET_URI"]


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<p data-ow-cite="d7#1" data-ow-cite-kind="hearsay">x</p>', "is not one of"),
        ('<p data-ow-cite="d7#1" data-ow-cite-span="7:3">x</p>', "is not a:b with a < b"),
        ('<p data-ow-cite="d7#1" data-ow-cite-span="x">x</p>', "is not a:b with a < b"),
    ],
)
def test_a_cites_kind_and_span_hold_their_grammar(body: str, said: str) -> None:
    """D783: the rows that declare them, and the rule that says what the compile would refuse."""
    found = [(c, m) for c, m in _codes(body) if c == "OW_TARGET_IL_MALFORMED"]
    assert [said in m for _, m in found] == [True]


def test_a_stated_kind_and_span_pass() -> None:
    body = '<p data-ow-cite="d7#1" data-ow-cite-kind="quote" data-ow-cite-span="0:7">x</p>'
    assert _codes(body) == []
