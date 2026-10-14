"""`pptx.canvas@1`: the root's `viewBox` is the slide, in PowerPoint's bounds and the Brief's
format. D789 ruling 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from omniweave_core.out.brief import BRIEF_SCHEMA, Brief, parse_brief
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.finding import Finding
from omniweave_core.out.plan import OutUnit
from omniweave_target_pptx.driver import PptxCompiler
from omniweave_target_pptx.rules.canvas import EMU_PER_UNIT, SPEC, UNITS_MAX, UNITS_MIN

NS = 'xmlns="http://www.w3.org/2000/svg"'


def _brief(fmt: str) -> Brief:
    return parse_brief(
        f"{BRIEF_SCHEMA}\n## canvas\n- format: {fmt}\n- unit: slide\n## communication\n"
        "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
        "- level: static\n## typography\n## rhythm\n## forbidden\n",
        baseline=(),
    )


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None = field(
        default_factory=lambda: OutUnit(id="u01", ord=1, il_path="il/u01.svg")
    )
    brief: Any = None


def _run(attrs: str, brief: Brief | None = None) -> list[str]:
    doc = PptxCompiler().carrier("il/u01.svg", f"<svg {NS} {attrs}/>")
    found: list[Finding] = list(SPEC.fn(_Ctx(doc, brief=brief)))  # type: ignore[arg-type]
    assert {(f.code, f.construct) for f in found} <= {
        ("OW_TARGET_CANVAS_MISMATCH", "canvas.viewbox")
    }
    return [f.msg for f in found]


def test_the_spec_and_powerpoints_slide_bounds() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.canvas@1",
        11,
        {"OW_TARGET_CANVAS_MISMATCH"},
    )
    assert (UNITS_MIN * EMU_PER_UNIT, UNITS_MAX * EMU_PER_UNIT) == (914_400, 51_206_400)


@pytest.mark.parametrize(
    "attrs",
    [
        'viewBox="0 0 1280 720"',
        'viewBox="0 0 96 5376"',
        'viewBox="0 0 1280 720" width="1280" height="720"',
        'viewBox="0 0 1280 720" width="1280px"',
    ],
)
def test_a_canvas_inside_the_bounds_says_nothing(attrs: str) -> None:
    assert _run(attrs) == []


@pytest.mark.parametrize(
    ("attrs", "said"),
    [
        ("", "viewBox=None is not '0 0 W H' in positive integers"),
        ('viewBox="0 0 1280.5 720"', "viewBox='0 0 1280.5 720' is not '0 0 W H'"),
        ('viewBox="10 0 1280 720"', "viewBox='10 0 1280 720' is not '0 0 W H'"),
        ('viewBox="0,0,1280,720"', "viewBox='0,0,1280,720' is not '0 0 W H'"),
        ('viewBox="0 0 0 720"', "viewBox='0 0 0 720' is not '0 0 W H'"),
        ('viewBox="0 0 95 720"', "the viewBox width 95 is outside a slide's 96-5376"),
        ('viewBox="0 0 1280 5377"', "the viewBox height 5377 is outside a slide's 96-5376"),
        ('viewBox="0 0 1280 720" width="640"', "width='640' scales the slide"),
        ('viewBox="0 0 1280 720" height="50%"', "height='50%' scales the slide"),
        ('viewBox="0 0 1280 720" transform="scale(2)"', "a transform on the root moves"),
    ],
)
def test_a_canvas_that_is_not_the_slide_is_refused(attrs: str, said: str) -> None:
    [msg] = _run(attrs)
    assert said in msg


def test_without_a_brief_the_ratio_is_not_read() -> None:
    assert _run('viewBox="0 0 1024 768"') == []


@pytest.mark.parametrize(
    ("fmt", "attrs"),
    [
        ("16:9", 'viewBox="0 0 1280 720"'),
        ("16:9", 'viewBox="0 0 1920 1080"'),
        ("4:3", 'viewBox="0 0 1024 768"'),
        (" 16:9 ", 'viewBox="0 0 1280 720"'),
    ],
)
def test_the_viewbox_holds_the_briefs_format(fmt: str, attrs: str) -> None:
    assert _run(attrs, _brief(fmt)) == []


def test_another_ratio_is_named_with_both_sides() -> None:
    assert _run('viewBox="0 0 1024 768"', _brief("16:9")) == [
        "the viewBox is 1024x768, and the Brief's canvas format is 16:9"
    ]


@pytest.mark.parametrize("fmt", ["A4", "16x9", "0:9", "16:9:1"])
def test_a_format_that_is_not_a_ratio_cannot_be_held(fmt: str) -> None:
    assert _run('viewBox="0 0 1280 720"', _brief(fmt)) == [
        f"the Brief's canvas format {fmt!r} is not a W:H ratio"
    ]


def test_a_bad_viewbox_stops_before_the_brief() -> None:
    assert len(_run('viewBox="0 0 1 1 1"', _brief("16:9"))) == 1


def test_a_document_scope_context_reads_nothing() -> None:
    assert list(SPEC.fn(_Ctx(None, None))) == []  # type: ignore[arg-type]
