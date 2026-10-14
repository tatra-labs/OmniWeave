"""`pptx.effect@1`: one shadow or glow, a marker of one shape, a clip of one shape. D791."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.effect import CLIP_SHAPES, MARKER_SHAPES, PRIMITIVES, SPEC

SLOT = "asset-slot:" + "ab" * 32


def test_the_spec_and_the_shapes_each_effect_holds() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == ("pptx.effect@1", 51, {"OW_TARGET_EFFECT_INVALID"})
    assert {"svg|feDropShadow", "svg|feGaussianBlur"} == PRIMITIVES
    assert {"svg|rect"} == CLIP_SHAPES - MARKER_SHAPES


@pytest.mark.parametrize(
    "body",
    [
        '<defs><filter id="f"><feDropShadow dx="2" dy="-2" stdDeviation="3"/></filter>'
        '<filter id="g"><feGaussianBlur stdDeviation="0"/></filter></defs>',
        '<defs><marker id="m" markerWidth="4" markerHeight="4" refX="-1" refY="0">'
        '<path d="M0 0 L4 2 L0 4 Z"/></marker></defs>',
        '<defs><clipPath id="c"><circle cx="1" cy="1" r="1"/></clipPath></defs>',
        '<path d="M0 0 L1 1" marker-start="url(#m)"/><line marker-end="url(#m)"/>',
        f'<image href="{SLOT}" clip-path="url(#c)"/><image href="{SLOT}" filter="url(#f)"/>',
    ],
)
def test_effects_drawingml_holds_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said", "construct"),
    [
        ('<filter id="f"/>', "a <filter> holds one of <feDropShadow>, <feGaussianBlur>",
         "effect.filter-def"),
        ('<filter id="f"><feGaussianBlur stdDeviation="1"/><feDropShadow stdDeviation="1"/>'
         "</filter>", "and nothing else", "effect.filter-def"),
        ('<filter id="f"><feOffset/></filter>', "a <filter> holds one of", "effect.filter-def"),
        ('<filter id="f"><feGaussianBlur/></filter>',
         "stdDeviation=None: write a number, 0 or more", "effect.blur"),
        ('<filter id="f"><feGaussianBlur stdDeviation="-1"/></filter>',
         "stdDeviation='-1'", "effect.blur"),
        ('<filter id="f"><feDropShadow stdDeviation="1" dx="2px"/></filter>',
         "dx='2px': write a decimal number", "effect.shadow"),
        ('<g><feGaussianBlur stdDeviation="1"/></g>', "a <feGaussianBlur> belongs to a <filter>",
         "effect.blur"),
        ('<marker id="m"><rect/></marker>', "a <marker> holds one of", "effect.marker-def"),
        ('<marker id="m"><circle/><circle/></marker>', "and nothing else", "effect.marker-def"),
        ('<marker id="m" markerWidth="0"><circle/></marker>',
         "markerWidth='0': a marker's size is above 0", "effect.marker-def"),
        ('<marker id="m" refY="top"><circle/></marker>', "refY='top': write a decimal number",
         "effect.marker-def"),
        ('<clipPath id="c"><text>a</text></clipPath>', "a <clipPath> holds one of",
         "effect.clip-def"),
        ('<rect marker-end="url(#m)"/>',
         "marker-end on a <rect>: a line end belongs to a <line> or <path>", "effect.marker-end"),
        ('<rect clip-path="url(#c)"/>', "clip-path on a <rect>: a clip crops an <image>",
         "effect.clip"),
        (f'<image href="{SLOT}" clip-path="url(#c)" filter="url(#f)"/>',
         "an <image> takes a filter or a clip, not both", "effect.clip"),
    ],
)  # fmt: skip
def test_effects_drawingml_cannot_hold_are_named(
    slide: Any, body: str, said: str, construct: str
) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert found.construct == construct
