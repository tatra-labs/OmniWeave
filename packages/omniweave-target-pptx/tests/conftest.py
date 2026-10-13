"""What the owsvg/1 rule tests share: one slide, one rule, called directly. D790.

A rule is called with a context holding only what owsvg/1's rules read, rather than through
`check()`, because a report folds a rule's findings in a unit into one finding with a count
(OUT7) and keeps the first message, and these tests read every message.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
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
