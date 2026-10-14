"""`pptx.opacity@1`: an opacity is a number from 0 to 1. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.opacity import OPACITIES, SPEC


def test_the_spec_covers_the_five_opacities() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.opacity@1",
        41,
        {"OW_TARGET_OPACITY_INVALID"},
    )
    assert OPACITIES == (
        "opacity",
        "fill-opacity",
        "stroke-opacity",
        "stop-opacity",
        "flood-opacity",
    )


@pytest.mark.parametrize(
    "body",
    [
        '<rect opacity="0" fill-opacity="1" stroke-opacity="0.5"/>',
        '<rect style="opacity: .25"/>',
        '<rect opacity="50%"/>',
    ],
)
def test_fractions_from_0_to_1_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<rect opacity="1.5"/>', "<rect> opacity='1.5': write a number from 0 to 1"),
        ('<rect opacity="150%"/>', "<rect> opacity='150%'"),
        ('<rect fill-opacity="-0.1"/>', "<rect> fill-opacity='-0.1'"),
        ('<rect stroke-opacity="half"/>', "<rect> stroke-opacity='half'"),
        ('<rect style="opacity: 50%"/>', "<rect> style opacity: '50%'"),
        ('<stop stop-opacity="1e0"/>', "<stop> stop-opacity='1e0'"),
    ],
)
def test_other_opacities_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert found.msg.startswith(said)
