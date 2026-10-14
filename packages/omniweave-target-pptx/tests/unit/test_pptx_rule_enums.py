"""`pptx.enum@1`: a keyword is one of its words, and stands where it means something. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.enums import KEYWORDS, SPEC


def test_the_spec_and_its_keyword_properties() -> None:
    assert (SPEC.id, SPEC.order) == ("pptx.enum@1", 46)
    assert len(KEYWORDS) == 13
    assert {code for _, code in KEYWORDS.values()} | {"OW_TARGET_GEOMETRY_INVALID"} == SPEC.codes


@pytest.mark.parametrize(
    "body",
    [
        '<line stroke-linecap="round" stroke-linejoin="bevel" vector-effect="none"/>',
        '<text font-style="italic" text-anchor="middle" text-decoration="underline line-through"'
        ' xml:space="preserve">a<tspan baseline-shift="super">2</tspan></text>',
        '<linearGradient gradientUnits="objectBoundingBox"/>',
        '<marker orient="auto-start-reverse" markerUnits="strokeWidth"/>',
        '<clipPath clipPathUnits="objectBoundingBox"/><filter primitiveUnits="userSpaceOnUse"/>',
        '<image preserveAspectRatio="xMidYMid slice"/><image preserveAspectRatio="none"/>',
        '<image preserveAspectRatio="xMaxYMin"/>',
        '<line style="stroke-linecap: square; vector-effect: non-scaling-stroke"/>',
    ],
)
def test_words_in_their_sets_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said", "code"),
    [
        ('<line stroke-linecap="flat"/>', "<line> stroke-linecap='flat': write one of butt | round"
         " | square", "OW_TARGET_STROKE_INVALID"),
        ('<text font-style="oblique">a</text>', "write one of italic | normal",
         "OW_TARGET_FONT_INVALID"),
        ('<text text-decoration="line-through underline">a</text>',
         "write one of line-through | none", "OW_TARGET_FONT_INVALID"),
        ('<text xml:space="keep">a</text>', "write one of default | preserve",
         "OW_TARGET_TEXT_INVALID"),
        ('<radialGradient gradientUnits="userSpaceOnUse"/>', "write one of objectBoundingBox",
         "OW_TARGET_GRADIENT_INVALID"),
        ('<marker orient="45"/>', "write one of auto | auto-start-reverse",
         "OW_TARGET_EFFECT_INVALID"),
        ('<image preserveAspectRatio="xMidYMid crop"/>', "write none, or xMinYMin to xMaxYMax",
         "OW_TARGET_GEOMETRY_INVALID"),
        ('<line style="stroke-linejoin: arcs"/>', "<line> style stroke-linejoin: 'arcs'",
         "OW_TARGET_STROKE_INVALID"),
    ],
)  # fmt: skip
def test_other_words_are_refused_under_their_familys_code(
    slide: Any, body: str, said: str, code: str
) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert found.code == code


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (
            '<text x="1" y="1">a<tspan text-anchor="end">b</tspan></text>',
            "<tspan> text-anchor='end': text-anchor is the text box's: set it on <text>",
        ),
        (
            '<text baseline-shift="sub">a</text>',
            "<text> baseline-shift='sub': baseline-shift is a run's: set it on <tspan>",
        ),
        ('<rect xml:space="preserve"/>', "xml:space belongs to <text> or <tspan>"),
    ],
)
def test_a_keyword_where_it_means_nothing_is_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
