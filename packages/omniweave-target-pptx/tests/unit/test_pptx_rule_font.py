"""`pptx.font@1`: a size, weight, spacing and family DrawingML can hold. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.font import (
    HUNDREDTHS_PER_UNIT,
    SIZE_MAX,
    SIZE_MIN,
    SPEC,
    WEIGHTS,
)


def test_the_spec_and_drawingmls_ranges() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == ("pptx.font@1", 48, {"OW_TARGET_FONT_INVALID"})
    assert (HUNDREDTHS_PER_UNIT, SIZE_MIN, SIZE_MAX) == (75, 100, 400_000), "1 to 4000 pt"
    assert len(WEIGHTS) == 11


@pytest.mark.parametrize(
    "body",
    [
        '<text font-size="44" font-weight="bold" letter-spacing="-0.5"'
        " font-family=\"Arial, 'Helvetica Neue', sans-serif\">a</text>",
        '<text font-size="1.34" font-weight="100">a</text>',
        '<text font-size="5333" font-weight="900" letter-spacing="5333">a</text>',
        '<text style="font-size: 20px; font-weight: normal; letter-spacing: 1px">a</text>',
        '<text font-size="20px">a</text>',
    ],
)
def test_values_drawingml_holds_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<text font-size="0">a</text>', "<text> font-size='0': write a number above 0"),
        ('<text font-size="12pt">a</text>', "<text> font-size='12pt': write a number above 0"),
        ('<text font-size="1.3">a</text>', "<text> font-size='1.3': DrawingML holds 1 to 4000 pt"),
        ('<text font-size="5334">a</text>', "DrawingML holds 1 to 4000 pt"),
        ('<text font-weight="semibold">a</text>', "write normal, bold, or 100 to 900 by 100"),
        ('<text font-weight="450">a</text>', "<text> font-weight='450'"),
        ('<text letter-spacing="0.1em">a</text>', "write a decimal number, user units"),
        ('<text letter-spacing="-5334">a</text>', "DrawingML holds +/-4000 pt of spacing"),
        ('<text font-family="Arial, ,serif">a</text>', "name one family or more, none empty"),
        ('<text font-family="  ">a</text>', "name one family or more, none empty"),
        ('<text style="font-family: \'\'">a</text>', "name one family or more, none empty"),
    ],
)  # fmt: skip
def test_other_values_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
