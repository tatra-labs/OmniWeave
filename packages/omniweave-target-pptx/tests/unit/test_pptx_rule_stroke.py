"""`pptx.stroke@1`: a stroke width is a size, a dash array dashes and gaps. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.stroke import DASHES_MIN, SPEC


def test_the_spec() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == ("pptx.stroke@1", 47, {"OW_TARGET_STROKE_INVALID"})
    assert DASHES_MIN == 2


@pytest.mark.parametrize(
    "body",
    [
        '<line stroke-width="0" stroke-dasharray="none"/>',
        '<line stroke-width="2.5" stroke-dasharray="4 4"/>',
        '<line stroke-width="2px" stroke-dasharray="8,4,2,4"/>',
        '<line style="stroke-width: 3px; stroke-dasharray: 6 3"/>',
    ],
)
def test_widths_and_arrays_drawingml_holds_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<line stroke-width="-1"/>', "stroke-width='-1': write a decimal number, 0 or more"),
        ('<line stroke-width="thin"/>', "<line> stroke-width='thin'"),
        ('<line style="stroke-width: 2em"/>', "<line> style stroke-width: '2em'"),
        ('<line stroke-dasharray="4"/>', "write none, or two or more numbers above 0"),
        ('<line stroke-dasharray="4 0"/>', "<line> stroke-dasharray='4 0'"),
        ('<line stroke-dasharray="4 -2"/>', "<line> stroke-dasharray='4 -2'"),
        ('<line stroke-dasharray="dashed"/>', "<line> stroke-dasharray='dashed'"),
        ('<line stroke-dasharray=""/>', "<line> stroke-dasharray=''"),
    ],
)  # fmt: skip
def test_other_strokes_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
