"""`pptx.points@1`: pairs, enough of them, on a polygon or polyline. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.points import PAIRS_MIN, SPEC


def test_the_spec_and_its_minimums() -> None:
    assert (SPEC.id, SPEC.order) == ("pptx.points@1", 43)
    assert PAIRS_MIN == {"svg|polygon": 3, "svg|polyline": 2}


@pytest.mark.parametrize(
    "body",
    [
        '<polygon points="0,0 10,0 10,10"/>',
        '<polygon points="0 0 10 0 10 10 0 10"/>',
        '<polyline points="0,0, 5,5"/>',
        '<polyline points=" 0 , 0   -5.5 .5 "/>',
    ],
)
def test_enough_pairs_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<polygon points="0,0 10,0"/>', "<polygon> points='0,0 10,0': a polygon needs 3 points"),
        ('<polyline points="0,0"/>', "<polyline> points='0,0': a polyline needs 2 points"),
        ('<polygon points="0,0 10,0 10"/>', "write x,y pairs of decimal numbers"),
        ('<polygon points="0,0 a,b 1,1"/>', "write x,y pairs of decimal numbers"),
        ('<polyline points=""/>', "a polyline needs 2 points"),
        ('<rect points="0,0 1,1"/>', "<rect> points='0,0 1,1': points belong to <polygon>"),
    ],
)
def test_other_point_lists_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert (found.code, found.construct) == ("OW_TARGET_GEOMETRY_INVALID", "geom.points")
