"""`omniweave_core.out.lowering`: preflight check 1, every target's (09 section 5.1). D795.

`resolve()` is read against family modules built here, and `refuse_unmapped()` against stand-in
constructs, since it reads only `id` and `maps_to`. `unmapped()`, `walk()` and
`refuse_normalizable()` run over real tables in the docx and pptx lowering tests.
"""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.out.lowering import refuse_unmapped, resolve


def _family(**names: Any) -> ModuleType:
    module = ModuleType("lower.shapes")
    for name, value in names.items():
        setattr(module, name, value)
    module.__all__ = [n for n in names if n != "hidden"]  # type: ignore[attr-defined]
    return module


def rect() -> None:
    """A lowering function."""


def _private() -> None:
    """A private name, exported by mistake."""


FAMILIES = {
    "lower.shapes": _family(rect=rect, _private=_private, hidden=rect, LIMIT=3),
}


def test_a_maps_to_resolves_to_the_function_its_family_exports() -> None:
    assert resolve("lower.shapes:rect", FAMILIES) is rect


@pytest.mark.parametrize(
    "maps_to",
    [
        "lower.text:run",  # no such family
        "lower.shapes:_private",  # private, even when exported
        "lower.shapes:hidden",  # defined, not exported
        "lower.shapes:LIMIT",  # exported, not callable
        "lower.shapes:ellipse",  # not defined
        "lower.shapes",  # no symbol
        "",
    ],
)
def test_anything_else_resolves_to_nothing(maps_to: str) -> None:
    assert resolve(maps_to, FAMILIES) is None


def test_no_missing_construct_is_no_refusal() -> None:
    refuse_unmapped([], "pptx")


def test_the_refusal_names_every_missing_construct_and_the_targets_fix() -> None:
    missing = [
        SimpleNamespace(id="text.text", maps_to="lower.text:text_box"),
        SimpleNamespace(id="shape.path", maps_to="lower.paths:freeform"),
    ]
    with pytest.raises(TargetError) as caught:
        refuse_unmapped(missing, "pptx")  # type: ignore[arg-type]
    assert str(caught.value) == (
        "the units use constructs this compiler cannot lower: "
        "text.text (lower.text:text_box), shape.path (lower.paths:freeform)"
    )
    assert caught.value.code() == "OW_TARGET_CONSTRUCT_UNMAPPED"
    assert caught.value.fix == "ow out constructs pptx --construct text.text"
