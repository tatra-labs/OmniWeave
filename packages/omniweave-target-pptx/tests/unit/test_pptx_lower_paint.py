"""`compile.pptx.native`'s paint servers: a `url(#id)` fill or line as a gradient or a pattern.
D798.

Each paint is lowered through `lowered()` (tests/lowerkit.py) and read back from the package. A
linear gradient's stops move to where they fall on DrawingML's run across the whole box, and a
radial's by its radius, so the expected positions are worked by hand in each case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lowerkit import (  # type: ignore[import-not-found]  # tests/lowerkit.py
    A,
    P,
    line_of,
    lowered,
    outline,
    slide,
    u,
)
from omniweave_target_pptx.driver import PptxCompiler
from omniweave_target_pptx.lower.gradients import units

STOPS = '<stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#1F4E79"/>'


def painted(tmp_path: Path, definition: str, shape: str = "") -> Any:
    """The first shape of a slide whose `<defs>` holds `definition`, filled with `url(#p)`."""
    drawn = shape or '<rect width="10" height="10" fill="url(#p)"/>'
    return lowered(tmp_path, slide(f"<defs>{definition}</defs>{drawn}")).first()


def fill_of(shape: Any) -> list[str]:
    """The shape's fill, its third `p:spPr` child, as an outline."""
    return outline(shape.find(f"{P}spPr")[2])


def positions(shape: Any) -> list[str]:
    return [gs.get("pos") for gs in shape.iter(f"{A}gs")]


# ---------------------------------------------------------------------------------------------
# linear gradients
# ---------------------------------------------------------------------------------------------


def test_a_linear_gradient_is_a_grad_fill_in_drawingmls_order(tmp_path: Path) -> None:
    shape = painted(tmp_path, f'<linearGradient id="p">{STOPS}</linearGradient>')
    assert fill_of(shape) == [
        "gradFill rotWithShape=1",
        "gsLst",
        "gs pos=0",
        "srgbClr val=FFFFFF",
        "gs pos=100000",
        "srgbClr val=1F4E79",
        "lin ang=0 scaled=1",
    ]


@pytest.mark.parametrize(
    ("ends", "angle", "where"),
    [
        ("", "0", ["0", "100000"]),
        ('x2="0" y2="1"', "5400000", ["0", "100000"]),
        ('x2="1" y2="1"', "2700000", ["0", "100000"]),
        ('x1="1" x2="0"', "10800000", ["0", "100000"]),
        ('x1="0.25" x2="0.75"', "0", ["25000", "75000"]),
        ('x1="25%" x2="75%"', "0", ["25000", "75000"]),
        ('x1="0.5" y1="0.5" x2="1" y2="0.5"', "0", ["50000", "100000"]),
        ('y1="0.5" x2="0.5" y2="0.5"', "0", ["0", "50000"]),
    ],
)
def test_a_linear_run_is_moved_onto_drawingmls_run_across_the_box(
    tmp_path: Path, ends: str, angle: str, where: list[str]
) -> None:
    shape = painted(tmp_path, f'<linearGradient id="p" {ends}>{STOPS}</linearGradient>')
    assert shape.find(f".//{A}lin").get("ang") == angle
    assert positions(shape) == where


def test_a_stops_offset_may_be_a_percentage_and_its_colour_a_style(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        '<linearGradient id="p"><stop/>'
        '<stop offset="40%" style="stop-color: #00ff00; stop-opacity: 50%"/>'
        '<stop offset="1" stop-color="#0000FF" stop-opacity="0.25"/></linearGradient>',
    )
    # a stop with no offset or colour is SVG's: at 0, black (the gate asks for both)
    assert fill_of(shape)[2:-1] == [
        "gs pos=0",
        "srgbClr val=000000",
        "gs pos=40000",
        "srgbClr val=00FF00",
        "alpha val=50000",
        "gs pos=100000",
        "srgbClr val=0000FF",
        "alpha val=25000",
    ]


def test_a_stops_opacity_is_clamped_to_none(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        '<linearGradient id="p"><stop offset="0" stop-color="#FFFFFF" stop-opacity="-1"/>'
        '<stop offset="1" stop-color="#000000" stop-opacity="2"/></linearGradient>',
    )
    assert [a.get("val") for a in shape.iter(f"{A}alpha")] == ["0"]


def test_a_gradients_units_are_its_box() -> None:
    """`lower.gradients:units`: the only units `pptx.enum@1` admits, stated or not."""
    root = (
        PptxCompiler()
        .carrier(
            "il/u01.svg",
            slide(
                '<defs><linearGradient id="a"/>'
                '<linearGradient id="b" gradientUnits="objectBoundingBox"/></defs>'
            ),
        )
        .root()
    )
    [defs] = root.children()
    assert [units(g) for g in defs.children()] == ["objectBoundingBox", "objectBoundingBox"]


def test_a_stops_alpha_is_its_opacity_times_the_shapes(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        '<linearGradient id="p"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.5"/>'
        '<stop offset="1" stop-color="#000000"/></linearGradient>',
        '<g opacity="0.5"><rect width="10" height="10" fill="url(#p)" fill-opacity="0.5"/></g>',
    )
    assert [a.get("val") for a in shape.iter(f"{A}alpha")] == ["12500", "25000"]


# ---------------------------------------------------------------------------------------------
# radial gradients
# ---------------------------------------------------------------------------------------------


def test_a_radial_gradient_is_a_circle_path_from_its_focus(tmp_path: Path) -> None:
    shape = painted(tmp_path, f'<radialGradient id="p">{STOPS}</radialGradient>')
    assert fill_of(shape) == [
        "gradFill rotWithShape=1",
        "gsLst",
        "gs pos=0",
        "srgbClr val=FFFFFF",
        "gs pos=100000",
        "srgbClr val=1F4E79",
        "path path=circle",
        "fillToRect b=50000 l=50000 r=50000 t=50000",
    ]


@pytest.mark.parametrize(
    ("attrs", "where", "focus"),
    [
        ('r="0.25"', ["0", "50000"], "b=50000 l=50000 r=50000 t=50000"),
        ('r="1"', ["0", "100000"], "b=50000 l=50000 r=50000 t=50000"),
        ('cx="0.3" cy="0.7"', ["0", "100000"], "b=30000 l=30000 r=70000 t=70000"),
        ('fx="0.4" fy="0.6"', ["0", "100000"], "b=40000 l=40000 r=60000 t=60000"),
    ],
)
def test_a_radials_radius_scales_its_stops_and_its_focus_is_the_fill_rect(
    tmp_path: Path, attrs: str, where: list[str], focus: str
) -> None:
    shape = painted(
        tmp_path,
        f'<radialGradient id="p" {attrs}><stop offset="0" stop-color="#FFFFFF"/>'
        '<stop offset="1" stop-color="#000000"/></radialGradient>',
    )
    assert positions(shape) == where
    assert fill_of(shape)[-1] == f"fillToRect {focus}"


THREE = (
    '<stop offset="0" stop-color="#FFFFFF"/><stop offset="0.5" stop-color="#808080"/>'
    '<stop offset="1" stop-color="#000000"/>'
)


@pytest.mark.parametrize(
    ("definition", "where"),
    [
        # the diagonal's run is the box's whole diagonal: a middle stop is at its middle
        (f'<linearGradient id="p" x2="1" y2="1">{THREE}</linearGradient>',
         ["0", "50000", "100000"]),
        # half the diagonal is half the box's run
        (f'<linearGradient id="p" x2="0.5" y2="0.5">{THREE}</linearGradient>',
         ["0", "25000", "50000"]),
        # r = 0.5 is DrawingML's own reach
        (f'<radialGradient id="p">{THREE}</radialGradient>', ["0", "50000", "100000"]),
    ],
)  # fmt: skip
def test_a_middle_stop_lands_at_its_share_of_the_run(
    tmp_path: Path, definition: str, where: list[str]
) -> None:
    assert positions(painted(tmp_path, definition)) == where


def test_a_radial_stop_past_the_edge_is_clamped_to_it(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        '<radialGradient id="p" r="1"><stop offset="0.25" stop-color="#FFFFFF"/>'
        '<stop offset="0.75" stop-color="#000000"/></radialGradient>',
    )
    assert positions(shape) == ["50000", "100000"]


# ---------------------------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        (
            'data-ow-preset="ltUpDiag" data-ow-fg="#FF0000" data-ow-bg="#00FF00"',
            [
                "pattFill prst=ltUpDiag",
                "fgClr",
                "srgbClr val=FF0000",
                "bgClr",
                "srgbClr val=00FF00",
            ],
        ),
        (
            'data-ow-preset="smGrid"',
            ["pattFill prst=smGrid", "fgClr", "srgbClr val=000000", "bgClr", "srgbClr val=FFFFFF"],
        ),
    ],
)
def test_a_pattern_is_its_preset_and_its_two_colours(
    tmp_path: Path, attrs: str, expected: list[str]
) -> None:
    shape = painted(tmp_path, f'<pattern id="p" {attrs}/>')
    assert fill_of(shape) == expected


def test_a_patterns_colours_take_the_shapes_alpha(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        '<pattern id="p" data-ow-preset="cross"/>',
        '<rect width="10" height="10" fill="url(#p)" fill-opacity="0.5"/>',
    )
    assert [a.get("val") for a in shape.iter(f"{A}alpha")] == ["50000", "50000"]


# ---------------------------------------------------------------------------------------------
# where a paint server goes
# ---------------------------------------------------------------------------------------------


def test_a_line_takes_a_paint_server_too(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        f'<linearGradient id="p">{STOPS}</linearGradient>',
        '<rect width="10" height="10" fill="none" stroke="url(#p)" stroke-width="2"/>',
    )
    line = line_of(shape)
    assert outline(line)[:2] == [f"ln cap=flat w={u(2)}", "gradFill rotWithShape=1"]


def test_a_runs_fill_takes_a_paint_server_too(tmp_path: Path) -> None:
    shape = painted(
        tmp_path,
        f'<linearGradient id="p">{STOPS}</linearGradient>',
        '<text y="40" fill="url(#p)">a</text>',
    )
    properties = shape.find(f".//{A}rPr")
    assert outline(properties)[1:3] == ["gradFill rotWithShape=1", "gsLst"]


@pytest.mark.parametrize(
    ("drawn", "rot", "angle"),
    [
        ('<rect width="10" height="10" fill="url(#p)" transform="rotate(90)"/>', "5400000", "0"),
        (
            '<polygon points="0,0 10,0 10,10" fill="url(#p)" transform="rotate(90)"/>',
            None,
            "5400000",
        ),
        (
            '<path d="M 0 0 L 10 0 L 10 10 Z" fill="url(#p)" transform="rotate(30)"/>',
            None,
            "1800000",
        ),
    ],
)
def test_a_presets_gradient_turns_with_it_and_a_freeforms_by_its_matrix(
    tmp_path: Path, drawn: str, rot: str | None, angle: str
) -> None:
    shape = painted(tmp_path, f'<linearGradient id="p">{STOPS}</linearGradient>', drawn)
    assert shape.find(f"{P}spPr/{A}xfrm").get("rot") == rot
    assert shape.find(f".//{A}lin").get("ang") == angle
