"""`measure.py`: owsvg/1's one `TextMeasure`, over the faces `font_dirs` names. D792.

Every face is `tests/fontkit.py`'s, built from its tables, so each width below is arithmetic:
at a size of 10 and 1000 units to the em, a glyph of 600 units is 6 user units wide.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from omniweave_core.errors import ConfigError
from omniweave_core.out import Box
from omniweave_target_pptx.driver import PptxCompiler
from omniweave_target_pptx.measure import DEFAULT_SIZE, FontBook, HarfBuzzMeasure

NS = 'xmlns="http://www.w3.org/2000/svg"'


def _node(body: str, *, path: str = "0") -> object:
    """The node at `path` (child indices, `.`-separated) under a slide holding `body`."""
    doc = PptxCompiler().carrier("il/u01.svg", f'<svg {NS} viewBox="0 0 1280 720">{body}</svg>')
    node = doc.root()
    for index in path.split("."):
        node = list(node.children())[int(index)]
    return node


def _box(font_dir: Path, body: str, *, path: str = "0") -> Box | None:
    return HarfBuzzMeasure(FontBook((font_dir,))).box(_node(body, path=path))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# Rulings 1 and 2: the configured faces, and finding one
# ---------------------------------------------------------------------------------------------


def test_the_book_reads_every_font_under_its_roots_in_path_order(font_dir: Path) -> None:
    faces = FontBook((font_dir, font_dir / "missing")).faces()
    assert [(f.path.name, f.families, f.weight, f.italic) for f in faces] == [
        ("other.otf", ("Other Serif",), 400, False),
        ("probe-bold.ttf", ("Probe Sans",), 700, False),
        ("probe-italic.TTF", ("Probe Sans",), 400, True),
        ("probe.ttf", ("Probe Sans",), 400, False),
    ]
    assert (faces[0].upem, faces[0].ascender, faces[0].descender, faces[0].line_gap) == (
        1000,
        800,
        -200,
        100,
    )
    assert FontBook(()).faces() == ()


def test_a_family_is_found_by_name_then_style(font_dir: Path) -> None:
    book = FontBook((font_dir,))

    def found(families: tuple[str, ...], weight: int, *, italic: bool) -> str | None:
        face = book.find(families, weight, italic=italic)
        return None if face is None else face.path.name

    assert found(("Probe Sans",), 400, italic=False) == "probe.ttf"
    assert found(("  probe   sans ",), 400, italic=False) == "probe.ttf"
    assert found(("'Probe Sans'",), 700, italic=False) == "probe-bold.ttf"
    assert found(("Probe Sans",), 600, italic=False) == "probe-bold.ttf", "600 is nearer 700"
    assert found(("Probe Sans",), 500, italic=False) == "probe.ttf", "500 is nearer 400"
    assert found(("Probe Sans",), 550, italic=False) == "probe-bold.ttf", "a tie: path order"
    assert found(("Probe Sans",), 700, italic=True) == "probe-italic.TTF", "italic first"
    assert found(("Missing", "Other Serif"), 400, italic=False) == "other.otf"
    assert found(("sans-serif",), 400, italic=False) is None, "a generic names no face"
    assert found((), 400, italic=False) is None


# ---------------------------------------------------------------------------------------------
# Rulings 3-6: a text's box
# ---------------------------------------------------------------------------------------------


def test_one_line_is_its_shaped_width_at_its_size(font_dir: Path) -> None:
    box = _box(font_dir, '<text x="0" y="10" font-family="Probe Sans" font-size="10">AB</text>')
    assert box == Box(advance=10.0, height=10.0, ascent=8.0, descent=2.0, lines=1, overflow=False)


def test_spacing_is_added_after_each_character(font_dir: Path) -> None:
    box = _box(
        font_dir,
        '<text font-family="Probe Sans" font-size="10" letter-spacing="1.5px">AB</text>',
    )
    assert box is not None and box.advance == 13.0


def test_properties_inherit_from_groups_and_style(font_dir: Path) -> None:
    body = (
        '<g font-family="Probe Sans" style="font-size: 20px"><g><text>A</text></g></g>'
        '<g font-family="Probe Sans" font-size="20"><text style="font-size: 10">A</text></g>'
    )
    assert (_box(font_dir, body, path="0.0.0") or Box(0, 0, 0, 0, 0, False)).advance == 12.0
    assert (_box(font_dir, body, path="1.0") or Box(0, 0, 0, 0, 0, False)).advance == 6.0


def test_the_default_size_is_16(font_dir: Path) -> None:
    box = _box(font_dir, '<text font-family="Probe Sans">A</text>')
    assert box is not None and box.advance == 600 * DEFAULT_SIZE / 1000


def test_weight_and_style_choose_the_face(font_dir: Path) -> None:
    def advance(attrs: str) -> float:
        box = _box(font_dir, f'<text font-family="Probe Sans" font-size="10" {attrs}>A</text>')
        assert box is not None
        return box.advance

    assert advance("") == 6.0
    assert advance('font-weight="bold"') == 5.5
    assert advance('font-weight="900"') == 5.5
    assert advance('font-style="italic"') == 4.5


def test_whitespace_collapses_unless_preserved(font_dir: Path) -> None:
    text = '<text font-family="Probe Sans" font-size="10"{}>\n  A \t  B  \n</text>'
    collapsed = _box(font_dir, text.format(""))
    kept = _box(font_dir, text.format(' xml:space="preserve"'))
    assert collapsed is not None and collapsed.advance == 6.0 + 5.0 + 4.0, "A, one space, B"
    assert kept is not None and kept.advance == 6.0 + 4.0 + 5.0 * 10, "ten whitespace kept"


def test_positioned_tspans_are_lines_and_the_widest_is_the_advance(font_dir: Path) -> None:
    body = (
        '<text x="0" y="10" font-family="Probe Sans" font-size="10">AB'
        '<tspan x="0" dy="12">AAA</tspan><tspan dy="12">B</tspan></text>'
    )
    box = _box(font_dir, body)
    assert box == Box(
        advance=18.0, height=8.0 + 2.0 + 2 * 10.0, ascent=8.0, descent=2.0, lines=3,
        overflow=False,
    )  # fmt: skip


def test_runs_take_their_own_face_and_size(font_dir: Path) -> None:
    body = (
        '<text font-family="Probe Sans" font-size="10">A<tspan font-size="20">A</tspan>'
        '<tspan font-family="Other Serif">A</tspan></text>'
    )
    box = _box(font_dir, body)
    assert box is not None
    assert (box.advance, box.lines, box.ascent, box.descent) == (6.0 + 12.0 + 4.0, 1, 16.0, 4.0)


def test_a_tspan_is_measured_as_its_own_content(font_dir: Path) -> None:
    body = '<text font-family="Probe Sans" font-size="10">AB<tspan x="0" dy="12">A</tspan></text>'
    box = _box(font_dir, body, path="0.0")
    assert box is not None and (box.advance, box.lines) == (6.0, 1)


def test_the_leading_is_the_nodes_own_face(font_dir: Path) -> None:
    body = '<text font-family="Other Serif" font-size="10">A<tspan dy="12">A</tspan></text>'
    box = _box(font_dir, body)
    assert box is not None and box.height == 8.0 + 2.0 + (800 + 200 + 100) / 100


@pytest.mark.parametrize(
    "body",
    [
        '<rect width="1" height="1"/>',
        '<text font-family="Nowhere" font-size="10">A</text>',
        '<text font-family="sans-serif" font-size="10">A</text>',
        "<text>A</text>",
        '<text font-family="Probe Sans">A<tspan font-family="Nowhere">B</tspan></text>',
    ],
)
def test_a_node_with_no_face_or_no_text_is_unmeasurable(font_dir: Path, body: str) -> None:
    assert _box(font_dir, body) is None


# ---------------------------------------------------------------------------------------------
# The driver's measure()
# ---------------------------------------------------------------------------------------------


def test_without_font_dirs_there_is_no_estimator() -> None:
    assert PptxCompiler().measure() is None
    assert PptxCompiler(font_dirs=[]).measure() is None


def test_one_compiler_has_one_estimator(font_dir: Path) -> None:
    compiler = PptxCompiler(font_dirs=[str(font_dir)])
    first = compiler.measure()
    assert isinstance(first, HarfBuzzMeasure)
    assert compiler.measure() is first, "09 section 4.4: the kit asserts the identical object"


def test_a_relative_font_dir_is_refused_when_the_compiler_is_built() -> None:
    with pytest.raises(ConfigError, match=r"font_dirs \['fonts'\] are not absolute") as caught:
        PptxCompiler(font_dirs=["fonts"])
    assert "font_dirs" in caught.value.fix


def test_without_uharfbuzz_there_is_no_estimator(
    font_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "uharfbuzz", None)
    monkeypatch.delitem(sys.modules, "omniweave_target_pptx.measure")
    assert PptxCompiler(font_dirs=[str(font_dir)]).measure() is None


def test_a_style_declaration_outranks_the_attribute_beside_it(font_dir: Path) -> None:
    box = _box(
        font_dir, '<text font-family="Probe Sans" font-size="20" style="font-size: 10">A</text>'
    )
    assert box is not None and box.advance == 6.0
