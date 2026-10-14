"""`pptx.gradient@1`: a gradient DrawingML's `a:gradFill` can hold. D790."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from omniweave_target_pptx.rules.gradient import SPEC, STOPS_MIN, fraction

STOPS = '<stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#000000"/>'


def _defs(gradient: str) -> str:
    return f"<defs>{gradient}</defs>"


def test_the_spec() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.gradient@1",
        49,
        {"OW_TARGET_GRADIENT_INVALID"},
    )
    assert STOPS_MIN == 2


@pytest.mark.parametrize(
    ("text", "want"),
    [("0.25", Decimal("0.25")), ("25%", Decimal("0.25")), (" 100% ", Decimal(1)), ("x", None)],
)
def test_a_fraction_is_a_number_or_a_percentage(text: str, want: Decimal | None) -> None:
    assert fraction(text) == want


@pytest.mark.parametrize(
    "gradient",
    [
        f'<linearGradient id="g">{STOPS}</linearGradient>',
        f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="100%">{STOPS}</linearGradient>',
        f'<radialGradient id="r">{STOPS}</radialGradient>',
        f'<radialGradient id="r" cx="0.4" cy="0.4" r="0.6" fx="0.2" fy="0.2">{STOPS}'
        "</radialGradient>",
        '<linearGradient id="g"><stop offset="0%" style="stop-color: #FFFFFF"/>'
        '<stop offset="40%" stop-color="#000000"/><stop offset="40%" stop-color="#FF0000"/>'
        "</linearGradient>",
    ],
)
def test_gradients_drawingml_holds_say_nothing(slide: Any, gradient: str) -> None:
    assert slide(SPEC, _defs(gradient)) == []


@pytest.mark.parametrize(
    ("body", "said", "construct"),
    [
        (f'<linearGradient id="g">{STOPS}</linearGradient>',
         "a gradient is a direct child of <defs>", "def.linear"),
        (_defs(f'<g><radialGradient id="r">{STOPS}</radialGradient></g>'),
         "a gradient is a direct child of <defs>", "def.radial"),
        (_defs(f"<linearGradient>{STOPS}</linearGradient>"),
         "a gradient has an id for url(#id) to name", "def.linear"),
        (_defs('<linearGradient id="g"><stop offset="0" stop-color="#FFFFFF"/></linearGradient>'),
         "a gradient holds two <stop>s or more and nothing else", "def.linear"),
        (_defs(f'<linearGradient id="g">{STOPS}<rect/></linearGradient>'),
         "a gradient holds two <stop>s or more and nothing else", "def.linear"),
        (_defs('<linearGradient id="g"><stop stop-color="#FFFFFF"/>'
               '<stop offset="1" stop-color="#000000"/></linearGradient>'),
         "offset=None: write a fraction from 0 to 1", "def.offset"),
        (_defs('<linearGradient id="g"><stop offset="120%" stop-color="#FFFFFF"/>'
               '<stop offset="1" stop-color="#000000"/></linearGradient>'),
         "offset='120%': write a fraction from 0 to 1", "def.offset"),
        (_defs('<linearGradient id="g"><stop offset="0.6" stop-color="#FFFFFF"/>'
               '<stop offset="0.5" stop-color="#000000"/></linearGradient>'),
         "offset='0.5' comes before the stop above it", "def.offset"),
        (_defs('<linearGradient id="g"><stop offset="0"/>'
               '<stop offset="1" stop-color="#000000"/></linearGradient>'),
         "a stop states its stop-color", "def.stop"),
        ('<stop offset="0" stop-color="#FFFFFF"/>', "a <stop> belongs to a gradient", "def.stop"),
        (_defs(f'<linearGradient id="g" x2="1.5">{STOPS}</linearGradient>'),
         "x2='1.5': write a fraction from 0 to 1", "def.linear"),
        (_defs(f'<linearGradient id="g" x1="1" x2="1">{STOPS}</linearGradient>'),
         "the gradient's two ends are one point", "def.linear"),
        (_defs(f'<radialGradient id="r" r="0">{STOPS}</radialGradient>'),
         "a radial gradient's r is above 0", "def.radial"),
        (_defs(f'<radialGradient id="r" r="0.2" fx="0.9">{STOPS}</radialGradient>'),
         "the focus lies outside the gradient's circle", "def.radial"),
        (_defs(f'<radialGradient id="r" cx="-0.1">{STOPS}</radialGradient>'),
         "cx='-0.1': write a fraction from 0 to 1", "def.radial"),
    ],
)  # fmt: skip
def test_each_structure_drawingml_cannot_hold_is_named(
    slide: Any, body: str, said: str, construct: str
) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert found.construct == construct
