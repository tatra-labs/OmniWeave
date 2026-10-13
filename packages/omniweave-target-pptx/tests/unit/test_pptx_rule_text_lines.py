"""`pptx.text.lines@1`: a positioned line is a paragraph of its own text box. D793."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.text_lines import SPEC


def test_the_spec() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.text.lines@1",
        53,
        {"OW_TARGET_TEXT_INVALID"},
    )


@pytest.mark.parametrize(
    "body",
    [
        '<text x="10" y="20">a<tspan x="10" dy="24">b</tspan><tspan dy="24">c</tspan></text>',
        '<text x="10.0" y="20">a<tspan x="10" dy="24">b</tspan></text>',
        '<text y="20">a<tspan x="0" dy="24">b</tspan></text>',
        '<text x="10" y="20">a<tspan font-weight="bold">b<tspan>c</tspan></tspan></text>',
        '<text x="10" y="20">a<tspan x="10" y="60">b</tspan><tspan dy="1">c</tspan></text>',
        '<text y="20" dy="-5">a<tspan x="0" y="16">b</tspan></text>',
        '<text x="10" y="20" dx="0">a<tspan dx="0.0">b</tspan></text>',
    ],
)
def test_lines_at_the_texts_x_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<text x="10" y="20">a<tspan x="10" dy="0">b</tspan></text>',
         "its baseline, 20, is not below the line before's, 20"),
        ('<text x="10" y="20">a<tspan x="10" dy="-4">b</tspan></text>',
         "its baseline, 16, is not below the line before's, 20"),
        ('<text x="10" y="20">a<tspan x="10" y="60">b</tspan><tspan x="10" y="40">c</tspan></text>',
         "its baseline, 40, is not below the line before's, 60"),
        ('<text x="10" y="20" dy="10">a<tspan x="10" y="25">b</tspan></text>',
         "its baseline, 25, is not below the line before's, 30"),
    ],
)  # fmt: skip
def test_a_line_above_the_one_before_is_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert (found.code, found.construct) == ("OW_TARGET_TEXT_INVALID", "text.tspan")


@pytest.mark.parametrize(
    ("body", "said", "construct"),
    [
        ('<text x="10" y="20" dx="4">a</text>', "dx='4': a DrawingML run has no offset", "geom.dx"),
        ('<text x="10" y="20">a<tspan dx="-2">b</tspan></text>', "dx='-2'", "geom.dx"),
        ('<text x="10" y="20">a<tspan y="60">b</tspan></text>',
         "a y on a run that starts no line moves it off its line", "geom.y"),
    ],
)  # fmt: skip
def test_a_run_moved_off_its_place_is_refused(
    slide: Any, body: str, said: str, construct: str
) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert (found.code, found.construct) == ("OW_TARGET_TEXT_INVALID", construct)


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<text x="10" y="20">a<tspan x="40" dy="24">b</tspan></text>',
         "x='40': a line of a text box starts at the text's x, 10"),
        ('<text y="20">a<tspan x="5" dy="24">b</tspan></text>',
         "x='5': a line of a text box starts at the text's x, 0"),
        ('<text x="10" y="20">a<tspan>b<tspan x="10" dy="24">c</tspan></tspan></text>',
         "a line starts in its <text>, never inside a run"),
        ('<text x="10" y="20"><tspan>b<tspan dy="24">c</tspan></tspan></text>',
         "a line starts in its <text>, never inside a run"),
    ],
)  # fmt: skip
def test_a_line_elsewhere_is_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert (found.code, found.construct) == ("OW_TARGET_TEXT_INVALID", "text.tspan")
