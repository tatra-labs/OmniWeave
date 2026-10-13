"""`pptx.path@1`: path data complete under SVG's command grammar, on a `<path>`. D790."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.path_data import ARGUMENTS, SPEC, problem


def test_the_spec_and_the_command_set() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == ("pptx.path@1", 44, {"OW_TARGET_PATH_INVALID"})
    assert "".join(sorted(ARGUMENTS)) == "achlmqstvz"


@pytest.mark.parametrize(
    "d",
    [
        "M0 0L10 10Z",
        "m 0,0 l 10,10 h 5 v -5 z",
        "M0 0 10 10 20 0",
        "M0 0C1 1 2 2 3 3S4 4 5 5Q6 6 7 7T8 8",
        "M10 10 A5 5 0 0 1 20 20",
        "M10 10a5 5 30 1020 20",
        "M1e2 .5L-3.25e-1+4",
        "M0 0 Z M5 5 L6 6",
    ],
)
def test_grammatical_data_has_no_problem(d: str) -> None:
    assert problem(d) is None


@pytest.mark.parametrize(
    ("d", "said"),
    [
        ("", "the path data is empty"),
        ("   ", "the path data is empty"),
        ("L0 0", "path data starts with M or m"),
        ("M0", "M takes 2 numbers a segment; offset 2 has none"),
        ("M0 0 L", "L at offset 6 has no numbers"),
        ("M0 0 C1 1 2 2", "C takes 6 numbers a segment"),
        ("M0 0 X1 1", "'X1 1' at offset 5 is no path command"),
        ("M0 0 Z 5", "'5' at offset 7 is no path command"),
        ("M0 0 A5 5 0 2 1 1 1", "an arc flag is 0 or 1, at offset 12"),
        ("M0 0 A-5 5 0 0 1 1 1", "an arc radius is never negative, -5 at offset 6"),
    ],
)
def test_each_problem_is_named(d: str, said: str) -> None:
    assert problem(d) == said or (problem(d) or "").startswith(said)


def test_the_rule_reports_a_problem_where_it_is_written(slide: Any) -> None:
    [found] = slide(SPEC, '<path d="M0 0 L"/>')
    assert found.msg == "<path> d='M0 0 L': L at offset 6 has no numbers"
    assert found.construct == "geom.d"


def test_d_belongs_to_a_path(slide: Any) -> None:
    [found] = slide(SPEC, '<rect d="M0 0 L1 1"/>')
    assert found.msg == "<rect> d='M0 0 L1 1': d belongs to <path>"
    assert slide(SPEC, '<path d="M0 0 L1 1"/>') == []
