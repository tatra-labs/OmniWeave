"""`pptx.length@1`: a geometry length is a canonical number; a size is never negative. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.length import LENGTHS, SIZES, SPEC


def test_the_spec_and_its_lengths() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.length@1",
        42,
        {"OW_TARGET_GEOMETRY_INVALID"},
    )
    assert len(LENGTHS) == 15
    assert frozenset({"width", "height", "rx", "ry", "r"}) == SIZES


@pytest.mark.parametrize(
    "body",
    [
        '<rect x="-10" y="0.5" width="100" height=".5" rx="4" ry="0"/>',
        '<circle cx="1" cy="2" r="3"/><line x1="0" y1="0" x2="10" y2="10"/>',
        '<text x="1" y="2"><tspan dx="-1" dy="20">a</tspan></text>',
        '<rect style="x: 10px; width: 20"/>',
        '<rect x="4px"/>',
        '<linearGradient x1="50%" x2="100%"/>',
    ],
)
def test_canonical_lengths_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<rect x="1e3"/>', "<rect> x='1e3': write a decimal number in user units"),
        ('<rect y="+5"/>', "<rect> y='+5'"),
        ('<rect width="10pt"/>', "<rect> width='10pt'"),
        ('<rect height="5."/>', "<rect> height='5.'"),
        ('<rect width="-1"/>', "<rect> width='-1': a width is never negative"),
        ('<circle r="-0.5"/>', "<circle> r='-0.5': a r is never negative"),
        ('<rect style="width: 10em"/>', "<rect> style width: '10em'"),
        ('<rect style="height: -2px"/>', "<rect> style height: '-2px': a height is never negative"),
        ('<text x="1 2 3" y="1">a</text>', "<text> x='1 2 3'"),
    ],
)
def test_other_lengths_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert found.msg.startswith(said)
