"""`compile.pptx.native`'s effects: a filter's shadow or glow, and a marker as a line's end. D799.

Each effect is lowered through `lowered()` (tests/lowerkit.py) and read back from the package. A
shadow's distance is `hypot(dx, dy)` and its direction `atan2(dy, dx)`, a blur radius is two
deviations, and a marker's size is bucketed in stroke widths, so each expected value is worked by
hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lowerkit import (  # type: ignore[import-not-found]  # tests/lowerkit.py
    INK,
    A,
    P,
    line_of,
    lowered,
    outline,
    slide,
    u,
)
from omniweave_core.errors import TargetError
from omniweave_target_pptx.driver import PptxCompiler
from omniweave_target_pptx.lower.effects import end_anchor, end_units, orient, units

SHADOW = (
    '<filter id="f"><feDropShadow dx="3" dy="4" stdDeviation="2" flood-color="#333333" '
    'flood-opacity="0.5"/></filter>'
)


def drawn(tmp_path: Path, definitions: str, body: str) -> Any:
    return lowered(tmp_path, slide(f"<defs>{definitions}</defs>{body}"))


def effects_of(element: Any) -> list[str]:
    """The `a:effectLst` under `element`, as an outline, or `[]`."""
    found = element.find(f"{A}effectLst")
    return [] if found is None else outline(found)


# ---------------------------------------------------------------------------------------------
# shadows
# ---------------------------------------------------------------------------------------------


def test_a_drop_shadow_is_an_outer_shadow_after_the_line(tmp_path: Path) -> None:
    shape = drawn(tmp_path, SHADOW, '<rect width="10" height="10" filter="url(#f)"/>').first()
    body = shape.find(f"{P}spPr")
    assert [c.tag.rpartition("}")[2] for c in body] == [
        "xfrm",
        "prstGeom",
        "solidFill",
        "ln",
        "effectLst",
    ]
    assert effects_of(body) == [
        "effectLst",
        f"outerShdw blurRad={u(4)} dir=3187806 dist={u(5)} rotWithShape=1",
        "srgbClr val=333333",
        "alpha val=50000",
    ]


def test_a_shadows_offset_and_deviation_default_to_two(tmp_path: Path) -> None:
    shape = drawn(
        tmp_path,
        '<filter id="f"><feDropShadow/></filter>',
        '<rect width="10" height="10" filter="url(#f)"/>',
    ).first()
    assert effects_of(shape.find(f"{P}spPr")) == [
        "effectLst",
        f"outerShdw blurRad={u(4)} dir=2700000 dist={u(2 * 2**0.5)} rotWithShape=1",
        "srgbClr val=000000",
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            '<rect width="10" height="10" filter="url(#f)" transform="scale(2)"/>',
            f"outerShdw blurRad={u(8)} dir=0 dist={u(6)} rotWithShape=1",
        ),
        (
            '<rect width="10" height="10" filter="url(#f)" transform="rotate(90)"/>',
            f"outerShdw blurRad={u(4)} dir=0 dist={u(3)} rotWithShape=1",
        ),
        (
            '<polygon points="0,0 10,0 10,10" filter="url(#f)" transform="rotate(90)"/>',
            f"outerShdw blurRad={u(4)} dir=5400000 dist={u(3)} rotWithShape=1",
        ),
    ],
)
def test_a_shadow_grows_with_its_shape_and_turns_with_it(
    tmp_path: Path, body: str, expected: str
) -> None:
    shape = drawn(
        tmp_path, '<filter id="f"><feDropShadow dx="3" dy="0" stdDeviation="2"/></filter>', body
    ).first()
    assert effects_of(shape.find(f"{P}spPr"))[1] == expected


# ---------------------------------------------------------------------------------------------
# glows
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("primitive", "fill", "expected"),
    [
        ('stdDeviation="3"', 'fill="#FF0000"', ["srgbClr val=FF0000"]),
        ('stdDeviation="3" flood-color="#00FF00"', 'fill="#FF0000"', ["srgbClr val=00FF00"]),
        ('stdDeviation="3" flood-opacity="0.4"', 'fill="#FF0000"',
         ["srgbClr val=FF0000", "alpha val=40000"]),
        ('stdDeviation="3"', 'fill="none"', ["srgbClr val=000000"]),
        ('stdDeviation="3" flood-opacity="-1"', 'fill="#FF0000"',
         ["srgbClr val=FF0000", "alpha val=0"]),
        ('stdDeviation="3"', "", ["srgbClr val=000000"]),
        # a `style` fill no normalize row settles is settled as the fill itself is
        ('stdDeviation="3"', 'style="fill: #f00"', ["srgbClr val=FF0000"]),
    ],
)  # fmt: skip
def test_a_blur_is_a_glow_of_its_flood_or_the_shapes_own_colour(
    tmp_path: Path, primitive: str, fill: str, expected: list[str]
) -> None:
    shape = drawn(
        tmp_path,
        f'<filter id="f"><feGaussianBlur {primitive}/></filter>',
        f'<rect width="10" height="10" {fill} filter="url(#f)"/>',
    ).first()
    assert effects_of(shape.find(f"{P}spPr")) == ["effectLst", f"glow rad={u(6)}", *expected]


# ---------------------------------------------------------------------------------------------
# where a filter goes
# ---------------------------------------------------------------------------------------------


def test_a_glow_grows_with_its_shape(tmp_path: Path) -> None:
    shape = drawn(
        tmp_path,
        '<filter id="f"><feGaussianBlur stdDeviation="3"/></filter>',
        '<rect width="10" height="10" fill="#FF0000" filter="url(#f)" transform="scale(2)"/>',
    ).first()
    assert effects_of(shape.find(f"{P}spPr"))[1] == f"glow rad={u(12)}"


def test_a_groups_filter_is_its_group_frames_and_turns_by_its_matrix(tmp_path: Path) -> None:
    out = drawn(
        tmp_path,
        '<filter id="f"><feDropShadow dx="3" dy="0" stdDeviation="2"/></filter>',
        '<g filter="url(#f)" transform="rotate(90)"><rect width="10" height="10"/></g>',
    )
    [made] = out.shapes()
    frame = made.find(f"{P}grpSpPr")
    assert [c.tag.rpartition("}")[2] for c in frame] == ["xfrm", "effectLst"]
    assert (
        effects_of(frame)[1] == f"outerShdw blurRad={u(4)} dir=5400000 dist={u(3)} rotWithShape=1"
    )
    assert effects_of(made.find(f"{P}sp/{P}spPr")) == []


def test_a_texts_filter_is_each_runs(tmp_path: Path) -> None:
    shape = drawn(
        tmp_path,
        '<filter id="f"><feGaussianBlur stdDeviation="1"/></filter>',
        '<text y="40" fill="#0000FF" filter="url(#f)" font-family="Probe Sans">a<tspan>b</tspan>'
        "</text>",
    ).first()
    for properties in shape.iter(f"{A}rPr"):
        assert outline(properties)[1:] == [
            "solidFill",
            "srgbClr val=0000FF",
            "effectLst",
            f"glow rad={u(2)}",
            "srgbClr val=0000FF",
            "latin typeface=Probe Sans",
            "ea typeface=Probe Sans",
            "cs typeface=Probe Sans",
        ]


def test_no_filter_is_no_effect_list(tmp_path: Path) -> None:
    out = drawn(tmp_path, SHADOW, '<rect width="10" height="10" filter="none"/>')
    assert effects_of(out.first().find(f"{P}spPr")) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<rect width="1" height="1" filter="url(#nowhere)"/>', "names no id in this slide"),
        ('<rect id="r" width="1" height="1" filter="url(#r)"/>',
         "names a <rect>; it must name a <filter>"),
        (f'<line x2="9" {INK} marker-end="url(#f)"/>', "names a <filter>; it must name a <marker>"),
    ],
)  # fmt: skip
def test_an_effect_naming_the_wrong_definition_is_refused(
    tmp_path: Path, body: str, said: str
) -> None:
    with pytest.raises(TargetError, match=said) as caught:
        drawn(tmp_path, SHADOW, body)
    assert caught.value.code() == "OW_TARGET_REFERENCE_UNRESOLVED"


# ---------------------------------------------------------------------------------------------
# markers
# ---------------------------------------------------------------------------------------------


def _ends(tmp_path: Path, marker: str, line: str = "") -> list[str]:
    out = drawn(
        tmp_path,
        f'<marker id="m" {marker}',
        line or f'<line x2="100" {INK} stroke-width="2" marker-end="url(#m)"/>',
    )
    return [e for e in outline(line_of(out.first())) if e.startswith(("headEnd", "tailEnd"))]


@pytest.mark.parametrize(
    ("shape", "kind"),
    [
        ('<circle r="5"/>', "oval"),
        ('<ellipse rx="5" ry="3"/>', "oval"),
        ('<polygon points="0,0 10,5 0,10"/>', "triangle"),
        ('<polygon points="0,5 5,0 10,5 5,10"/>', "diamond"),
        ('<path d="M 0 0 L 10 5 L 0 10 Z"/>', "triangle"),
        ('<path d="M 0 0 L 10 5 L 0 10" fill="none"/>', "arrow"),
        ("", "triangle"),
    ],
)
def test_a_markers_type_is_the_shape_it_holds(tmp_path: Path, shape: str, kind: str) -> None:
    assert _ends(tmp_path, f">{shape}</marker>") == [f"tailEnd len=med type={kind} w=med"]


@pytest.mark.parametrize(
    ("attrs", "length", "width"),
    [
        ('markerWidth="2" markerHeight="5"', "sm", "lg"),
        ('markerWidth="2.5" markerHeight="4"', "sm", "med"),
        ('markerWidth="4.1" markerHeight="2.6"', "lg", "med"),
        ('markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="4"', "lg", "sm"),
        ('markerUnits="strokeWidth" markerWidth="10" markerHeight="4"', "lg", "med"),
    ],
)
def test_a_markers_size_is_bucketed_in_stroke_widths(
    tmp_path: Path, attrs: str, length: str, width: str
) -> None:
    assert _ends(tmp_path, f'{attrs}><circle r="1"/></marker>') == [
        f"tailEnd len={length} type=oval w={width}"
    ]


def test_a_user_space_marker_on_a_line_with_no_width_is_its_own_size(tmp_path: Path) -> None:
    ends = _ends(
        tmp_path,
        'markerUnits="userSpaceOnUse" markerWidth="5"><circle r="1"/></marker>',
        f'<line x2="100" {INK} stroke-width="0" marker-end="url(#m)"/>',
    )
    assert ends == ["tailEnd len=lg type=oval w=med"]


def test_a_start_is_the_head_and_an_end_the_tail_after_the_join(tmp_path: Path) -> None:
    out = drawn(
        tmp_path,
        '<marker id="m"><circle r="1"/></marker>',
        f'<path d="M 0 0 L 10 0" {INK} marker-start="url(#m)" marker-end="url(#m)"/>',
    )
    assert outline(line_of(out.first()))[-3:] == [
        "miter lim=800000",
        "headEnd len=med type=oval w=med",
        "tailEnd len=med type=oval w=med",
    ]


def test_no_marker_is_no_end(tmp_path: Path) -> None:
    assert (
        _ends(
            tmp_path,
            '><circle r="1"/></marker>',
            f'<line x2="100" {INK} marker-start="none" marker-end="none"/>',
        )
        == []
    )


# ---------------------------------------------------------------------------------------------
# what the table names and DrawingML cannot hold
# ---------------------------------------------------------------------------------------------


def test_the_rest_of_a_definitions_words_are_read_as_svg_reads_them() -> None:
    root = (
        PptxCompiler()
        .carrier(
            "il/u01.svg",
            slide(
                '<defs><marker id="a"/><marker id="b" orient="auto-start-reverse" refX="2" '
                'refY="3" markerUnits="userSpaceOnUse"/><filter id="c"/>'
                '<filter id="d" primitiveUnits="userSpaceOnUse"/></defs>'
            ),
        )
        .root()
    )
    [defs] = root.children()
    a, b, c, d = defs.children()
    assert (orient(a), orient(b)) == ("auto", "auto-start-reverse")
    assert (end_anchor(a), end_anchor(b)) == ((0.0, 0.0), (2.0, 3.0))
    assert (end_units(a), end_units(b)) == ("strokeWidth", "userSpaceOnUse")
    assert (units(c), units(d)) == ("userSpaceOnUse", "userSpaceOnUse")
