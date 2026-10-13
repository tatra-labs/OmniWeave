"""`pptx.paint@1`: `#RRGGBB`, and a shape's paint may be `none` or `url(#id)`. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.paint import SPEC


def test_the_spec() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == ("pptx.paint@1", 40, {"OW_TARGET_FILL_INVALID"})


@pytest.mark.parametrize(
    "body",
    [
        '<rect width="1" height="1" fill="#1F4E79" stroke="none"/>',
        '<rect width="1" height="1" fill="url(#sky)"/>',
        '<rect width="1" height="1" style="fill: #FFFFFF; stroke: url(#a)"/>',
        '<defs><linearGradient id="g"><stop offset="0" stop-color="#000000"/></linearGradient>'
        "</defs>",
        '<pattern id="p" data-ow-preset="pct50" data-ow-fg="#000000" data-ow-bg="#FFFFFF"/>',
    ],
)
def test_canonical_paints_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


def test_a_value_the_normalize_row_settles_is_its_warning_and_not_this_error(slide: Any) -> None:
    assert slide(SPEC, '<rect width="1" height="1" fill="#abc" stroke="#1f4e79"/>') == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<rect fill="red"/>', "<rect> fill='red': write #RRGGBB in upper case, none or url(#id)"),
        ('<rect fill="#abcd"/>', "<rect> fill='#abcd'"),
        ('<rect stroke="currentColor"/>', "<rect> stroke='currentColor'"),
        ('<rect fill="rgb(1,2,3)"/>', "<rect> fill='rgb(1,2,3)'"),
        ('<rect fill="url(sky)"/>', "<rect> fill='url(sky)'"),
        ('<rect style="fill: #abc"/>', "<rect> style fill: '#abc'"),
        ('<stop stop-color="none"/>', "<stop> stop-color='none': write #RRGGBB in upper case"),
        ('<filter flood-color="url(#x)"/>', "<filter> flood-color='url(#x)'"),
        ('<pattern data-ow-fg="black"/>', "<pattern> data-ow-fg='black'"),
    ],
)
def test_other_paints_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert found.msg.startswith(said)
    assert found.code == "OW_TARGET_FILL_INVALID"


def test_the_construct_is_the_row_written(slide: Any) -> None:
    found = slide(SPEC, '<rect fill="red" style="stroke: blue"/>')
    assert [(f.construct, f.fix) for f in found] == [
        ("paint.fill", "ow out constructs pptx --construct paint.fill"),
        ("style.stroke", "ow out constructs pptx --construct style.stroke"),
    ]
