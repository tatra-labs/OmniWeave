"""`pptx.transform@1`: a transform DrawingML can hold, where it can hold it. D790."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from omniweave_target_pptx.rules.transform import ARITY, SPEC, operations


def test_the_spec_and_the_four_operations() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.transform@1",
        45,
        {"OW_TARGET_TRANSFORM_INVALID"},
    )
    assert set(ARITY) == {"matrix", "translate", "scale", "rotate"}


def test_a_list_is_read_in_order() -> None:
    assert operations("translate(10 20) rotate(45, 5, 5),scale(2)") == [
        ("translate", [Decimal(10), Decimal(20)]),
        ("rotate", [Decimal(45), Decimal(5), Decimal(5)]),
        ("scale", [Decimal(2)]),
    ]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("", "the transform is empty"),
        ("skewX(10)", "skewX: DrawingML has no skew"),
        ("perspective(3)", "'perspective' is not matrix, translate, scale or rotate"),
        ("rotate(1, 2)", "rotate takes 1 or 3 numbers"),
        ("matrix(1 0 0 1 0)", "matrix takes 6 numbers"),
        ("translate(a)", "translate takes 1 or 2 numbers"),
        ("translate 10", "'translate 10' is not name(numbers)"),
    ],
)
def test_a_list_drawingml_cannot_hold_says_why(text: str, said: str) -> None:
    assert operations(text) == said


@pytest.mark.parametrize(
    "body",
    [
        '<rect width="1" height="1" transform="translate(10,20) scale(2 3) rotate(30)"/>',
        '<path d="M0 0 L1 1" transform="matrix(0 1 -1 0 5 5)"/>',
        '<text x="1" y="1" transform="rotate(-90 640 360)">a</text>',
        '<text x="1" y="1" transform="translate(1) translate(2,3)">a</text>',
        '<g transform="translate(5)"><text x="1" y="1">a</text></g>',
        '<g transform="scale(2)"><rect width="1" height="1"/></g>',
    ],
)
def test_transforms_drawingml_holds_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<rect transform="skewY(3)"/>', "transform='skewY(3)': skewY: DrawingML has no skew"),
        ('<rect transform="scale(0 1)"/>', "a scale of zero collapses the shape"),
        ('<rect transform="matrix(1 2 2 4 0 0)"/>', "a matrix of determinant zero collapses"),
        ('<rect transform="matrix(1 0 1 1 0 0)"/>', "a matrix whose axes are not perpendicular"),
        (
            '<text x="1" y="1" transform="scale(2)">a</text>',
            "<text> transform='scale(2)': text takes a translate or one rotate, and nothing else",
        ),
        (
            '<text x="1" y="1" transform="rotate(5) rotate(5)">a</text>',
            "text takes a translate or one rotate",
        ),
        (
            '<g transform="matrix(0 1 -1 0 0 0)"><g><text x="1" y="1">a</text></g></g>',
            "<g> transform='matrix(0 1 -1 0 0 0)': text takes a translate or one rotate",
        ),
        (
            '<clipPath id="c"><rect width="1" height="1" transform="translate(1)"/></clipPath>',
            "nothing inside <clipPath> is transformed",
        ),
        (
            '<marker id="m"><g><path d="M0 0" transform="rotate(1)"/></g></marker>',
            "nothing inside <marker> is transformed",
        ),
    ],
)  # fmt: skip
def test_other_transforms_are_refused(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert found.construct == "geom.transform"


def test_the_slide_roots_transform_is_the_canvas_rules(document: Any) -> None:
    root = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" transform="skewX(1)"/>'
    assert document(SPEC, root) == []
