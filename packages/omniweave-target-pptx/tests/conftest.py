"""What the owsvg/1 rule tests share: one slide, one rule, called directly. D790.

A rule is called with a context holding only what owsvg/1's rules read, rather than through
`check()`, because a report folds a rule's findings in a unit into one finding with a count
(OUT7) and keeps the first message, and these tests read every message.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fontkit import tiny_font, write_font  # type: ignore[import-not-found]  # tests/fontkit.py
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.finding import Finding
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.rules import RuleSpec
from omniweave_target_pptx.driver import PptxCompiler, table

SLIDE_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'


@dataclass
class RuleContext:
    """`RuleCtx` as owsvg/1's rules read it."""

    doc: CarrierDoc | None
    unit: OutUnit | None = field(
        default_factory=lambda: OutUnit(id="u01", ord=1, il_path="il/u01.svg")
    )
    limits: dict[str, int] = field(default_factory=dict)
    brief: Any = None
    constructs: Any = field(default_factory=table)
    estimator: Any = None

    def measure(self, n: Any) -> Any:
        """`RuleCtx.measure(n)`, as `check()` builds it: the estimator's box, or `None`."""
        return None if self.estimator is None else self.estimator.box(n)


Run = Callable[[RuleSpec, str], list[Finding]]


@pytest.fixture
def slide() -> Run:
    """`slide(SPEC, body)`: the rule's findings over a 1280x720 slide holding `body`."""

    def run(spec: RuleSpec, body: str) -> list[Finding]:
        doc = PptxCompiler().carrier("il/u01.svg", f"{SLIDE_OPEN}{body}</svg>")
        return list(spec.fn(RuleContext(doc)))  # type: ignore[arg-type]

    return run


@pytest.fixture
def document() -> Run:
    """`document(SPEC, text)`: the rule's findings over a whole IL file, its root included."""

    def run(spec: RuleSpec, text: str) -> list[Finding]:
        doc = PptxCompiler().carrier("il/u01.svg", text)
        return list(spec.fn(RuleContext(doc)))  # type: ignore[arg-type]

    return run


@pytest.fixture
def font_dir(tmp_path: Path) -> Path:
    """D792: four faces in one directory, as `font_dirs` would name it.

    `Probe Sans` regular (`A` 600 units, `B` 400, the rest 500), bold (550 a glyph) and italic
    (450 a glyph), and `Other Serif` (400 a glyph), each 1000 units to the em, ascender 800 and
    descender -200, so a size of 10 makes each unit a hundredth of a user unit.
    """
    root = tmp_path / "fonts"
    write_font(root, "probe.ttf", tiny_font("Probe Sans", widths={"A": 600, "B": 400}))
    write_font(root, "probe-bold.ttf", tiny_font("Probe Sans", advance=550, weight=700))
    write_font(root, "probe-italic.TTF", tiny_font("Probe Sans", advance=450, italic=True))
    write_font(root, "nested/other.otf", tiny_font("Other Serif", advance=400, line_gap=100))
    (root / "readme.txt").write_text("not a font", encoding="utf-8")
    return root


@pytest.fixture
def measured(font_dir: Path) -> Run:
    """`measured(SPEC, body)`: as `slide`, with `measure.py`'s estimator over `font_dir`. A
    `body` that is a whole `<svg>` is read as the document."""
    from omniweave_target_pptx.measure import FontBook, HarfBuzzMeasure  # noqa: PLC0415

    estimator = HarfBuzzMeasure(FontBook((font_dir,)))

    def run(spec: RuleSpec, body: str) -> list[Finding]:
        text = body if body.startswith("<svg") else f"{SLIDE_OPEN}{body}</svg>"
        doc = PptxCompiler().carrier("il/u01.svg", text)
        return list(spec.fn(RuleContext(doc, estimator=estimator)))  # type: ignore[arg-type]

    return run
