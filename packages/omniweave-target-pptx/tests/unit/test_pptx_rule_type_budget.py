"""`pptx.type.budget@1`: an undeclared type size may stay a one-off, never a pattern. D794."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from omniweave_core.out.brief import BRIEF_SCHEMA, Brief, parse_brief
from omniweave_core.out.finding import Severity
from omniweave_target_pptx.rules.type_budget import (
    LIMIT,
    LIMIT_DEFAULT,
    SPEC,
    TOLERANCE,
    type_budget,
)


def _brief(typography: str) -> Brief:
    return parse_brief(
        f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
        "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
        f"- level: static\n## typography\n{typography}## rhythm\n## forbidden\n",
        baseline=(),
    )


ANCHORED = _brief("- title_family: Probe Sans\n- body: 20\n- title: 44\n")


@dataclass
class _Document:
    """A document-scope context: no doc, no unit, the completed index and the Brief."""

    sizes: dict[str, int]
    brief: Any = ANCHORED
    limits: dict[str, int] = field(default_factory=dict)
    doc: None = None
    unit: None = None

    @property
    def index(self) -> Any:
        return SimpleNamespace(value_occurrences={"type_size": Counter(self.sizes)})


def _said(sizes: dict[str, int], **over: Any) -> list[tuple[Severity, str]]:
    found = list(type_budget(_Document(sizes, **over)))  # type: ignore[arg-type]
    return [(f.severity, f.msg) for f in found]


def test_the_spec_is_a_final_stage_document_rule() -> None:
    assert (SPEC.id, SPEC.order, SPEC.scope, SPEC.final_only, SPEC.codes) == (
        "pptx.type.budget@1",
        90,
        "document",
        True,
        {"OW_TARGET_TYPE_SIZE_UNDECLARED"},
    )
    assert (LIMIT, LIMIT_DEFAULT, TOLERANCE) == ("undeclared_size_max", 2, 2)


def test_anchors_and_their_two_units_either_side_are_declared() -> None:
    assert _said({"20": 9, "18": 4, "22": 4, "44": 7, "42": 3, "46": 3}) == []


def test_a_one_off_is_silent_the_second_a_warning_and_the_third_an_error() -> None:
    found = _said({"13": 1, "17.5": 2, "30": 3})
    assert [s for s, _ in found] == [Severity.WARNING, Severity.ERROR]
    assert found[0][1] == (
        "font-size 17.5 appears 2 times across the deck and is within 2 of no typography anchor "
        "in the Brief (20, 44); past 2 it needs a named role"
    )
    assert "font-size 30 appears 3 times" in found[1][1]


def test_the_limit_is_the_checks() -> None:
    assert [s for s, _ in _said({"30": 3}, limits={"undeclared_size_max": 4})] == [Severity.WARNING]
    assert [s for s, _ in _said({"30": 2}, limits={"undeclared_size_max": 1})] == [Severity.ERROR]


@pytest.mark.parametrize(
    "brief", [None, _brief(""), _brief("- title_family: Probe Sans\n- body: large\n")]
)
def test_without_a_numeric_anchor_there_is_no_budget(brief: Any) -> None:
    assert _said({"30": 9}, brief=brief) == []
