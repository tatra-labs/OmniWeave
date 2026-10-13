"""`pptx.text.canvas@1`: a text's measured lines stay on the slide. D793.

The faces are `font_dir`'s: `Probe Sans` regular draws `A` 600 units wide and every other glyph
500, at 1000 units to the em, ascender 800 and descender -200. At `font-size="100"` a glyph of
500 units is 50 user units wide, the ascent is 80 and the descent 20. The slide is 1280x720.
"""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.text_canvas import MODEL, SPEC

FACE = 'font-family="Probe Sans" font-size="100"'


def test_the_spec_needs_measure_and_states_its_model() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes, SPEC.needs) == (
        "pptx.text.canvas@1",
        60,
        {"OW_TARGET_TEXT_OFF_CANVAS"},
        {"measure"},
    )
    assert MODEL == "single-line width per positioned line; vertical wrapping is not modeled"


@pytest.mark.parametrize(
    "body",
    [
        f'<text x="0" y="80" {FACE}>bbbb</text>',
        f'<text x="1080" y="700" {FACE}>bbbb</text>',
        f'<text x="1280" y="700" text-anchor="end" {FACE}>bbbb</text>',
        f'<text x="640" y="100" text-anchor="middle" {FACE}>bbbbbbbbbbbbbbbbbbbbbbbbb</text>',
        f'<g text-anchor="end"><text x="1280" y="100" {FACE}>bbbb</text></g>',
        f'<g transform="translate(100, 100)"><text x="0" y="0" {FACE}>bbbb</text></g>',
        f'<text x="0" y="80" {FACE}>b<tspan x="0" dy="100">bbbb</tspan>'
        '<tspan x="0" y="600">b</tspan></text>',
    ],
)
def test_text_on_the_slide_says_nothing(measured: Any, body: str) -> None:
    assert measured(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (f'<text x="1081" y="700" {FACE}>bbbb</text>',
         "measures 1081..1281 by 620..720 on a 1280x720 slide, past its right edge"),
        (f'<text x="-1" y="700" {FACE}>bbbb</text>', "-1..199 by 620..720"),
        (f'<text x="0" y="79" {FACE}>bbbb</text>',
         "0..200 by -1..99 on a 1280x720 slide, past its top"),
        (f'<text x="0" y="701" {FACE}>bbbb</text>', "past its bottom edge"),
        (f'<text x="100" y="700" text-anchor="end" {FACE}>bbbb</text>', "-100..100"),
        (f'<text x="1200" y="700" text-anchor="middle" {FACE}>bbbb</text>', "1100..1300"),
        (f'<text x="0" y="80" {FACE}>b<tspan x="0" dy="700">b</tspan></text>', "0..50 by 0..800"),
        (f'<text x="0" y="80" {FACE}>b<tspan x="0" y="900">b</tspan></text>', "0..50 by 0..920"),
        (f'<g transform="translate(1100)"><text x="0" y="100" {FACE}>bbbb</text></g>',
         "1100..1300"),
        (f'<text x="1280" y="0" {FACE}>bbbb</text>',
         "past its right and top edge (single-line width per positioned line; vertical wrapping "
         "is not modeled)"),
    ],
)  # fmt: skip
def test_text_past_an_edge_is_named(measured: Any, body: str, said: str) -> None:
    [found] = measured(SPEC, body)
    assert said in found.msg
    assert (found.code, found.construct) == ("OW_TARGET_TEXT_OFF_CANVAS", "text.text")
    assert found.msg.endswith(f"({MODEL})")


@pytest.mark.parametrize(
    "body",
    [
        f'<g transform="rotate(90)"><text x="5000" y="0" {FACE}>bbbb</text></g>',
        f'<text x="5000" y="0" transform="scale(2)" {FACE}>bbbb</text>',
        '<text x="5000" y="0" font-family="Nowhere">bbbb</text>',
        f'<text x="far" y="0" {FACE}>bbbb</text>',
    ],
)
def test_text_outside_the_model_is_not_measured_here(measured: Any, body: str) -> None:
    assert measured(SPEC, body) == []


def test_without_a_canvas_the_slide_rule_speaks_and_this_one_does_not(document: Any) -> None:
    bare = '<svg xmlns="http://www.w3.org/2000/svg"><text x="5000">a</text></svg>'
    assert document(SPEC, bare) == []


def test_the_slide_roots_transform_moves_no_text_here(measured: Any) -> None:
    """A root `transform` is `pptx.canvas@1`'s refusal; it is not a text's translation."""
    root = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"'
        f' transform="translate(5000)"><text x="0" y="80" {FACE}>b</text></svg>'
    )
    assert measured(SPEC, root) == []
