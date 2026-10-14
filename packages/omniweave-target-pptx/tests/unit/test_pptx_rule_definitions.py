"""`pptx.defs@1`: a definition in `<defs>` with an id; a pattern a DrawingML preset. D791."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.definitions import DEFINITIONS, PRESETS, SPEC


def test_the_spec_the_definitions_and_the_54_presets() -> None:
    assert (SPEC.id, SPEC.order) == ("pptx.defs@1", 52)
    assert set(DEFINITIONS) == {
        "svg|filter",
        "svg|marker",
        "svg|clipPath",
        "svg|pattern",
        "svg|symbol",
    }
    assert len(PRESETS) == 54
    assert {"pct5", "ltUpDiag", "zigZag", "diagCross"} <= PRESETS


def test_definitions_in_defs_with_ids_say_nothing(slide: Any) -> None:
    body = (
        '<defs><filter id="f"/><marker id="m"/><clipPath id="c"/>'
        '<pattern id="p" data-ow-preset="pct50"/><symbol id="s"/></defs>'
    )
    assert slide(SPEC, body) == []


@pytest.mark.parametrize(
    ("body", "said", "construct", "code"),
    [
        ('<filter id="f"/>', "a <filter> is a definition: put it in <defs>", "effect.filter-def",
         "OW_TARGET_EFFECT_INVALID"),
        ('<defs><g><marker id="m"/></g></defs>', "a <marker> is a definition",
         "effect.marker-def", "OW_TARGET_EFFECT_INVALID"),
        ("<defs><clipPath/></defs>", "a <clipPath> has an id for its users to name",
         "effect.clip-def", "OW_TARGET_EFFECT_INVALID"),
        ('<defs><symbol id=" "/></defs>', "a <symbol> has an id", "def.symbol",
         "OW_TARGET_REFERENCE_UNRESOLVED"),
        ('<defs><pattern id="p"/></defs>', "data-ow-preset=None is no DrawingML preset pattern",
         "def.preset", "OW_TARGET_FILL_INVALID"),
        ('<defs><pattern id="p" data-ow-preset="stripes"/></defs>',
         "data-ow-preset='stripes' is no DrawingML preset pattern", "def.preset",
         "OW_TARGET_FILL_INVALID"),
    ],
)  # fmt: skip
def test_each_misplaced_or_unnamed_definition_carries_its_rows_code(
    slide: Any, body: str, said: str, construct: str, code: str
) -> None:
    [found] = slide(SPEC, body)
    assert said in found.msg
    assert (found.construct, found.code) == (construct, code)
    assert code in SPEC.codes
