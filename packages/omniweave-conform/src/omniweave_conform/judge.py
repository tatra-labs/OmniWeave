"""Judging a run: assertions over a candidate's pages, to `eval_verdict` rows. **D827.**

13-quality.md section 8.1: an assertion is a claim about **one page of one document**, run against
a tool's output for that page, returning pass or fail and why. D825 and D826 judge one assertion
over one text; D815 stages verdicts and D816 rolls them up. This module is the step between: it
takes a run's assertions and the candidate's text per `(doc, page)`, and returns the verdicts the
staging writes and the rollup reads, with what it did not judge named.

Section 8.5 item 8's first planted defect is the case this exists to get right: *"the 12-page
`sec-exhibit-scan` fixture, page 7 removed from the candidate output: exactly the 6 assertions
anchored on page 7 fail; `34/40 = 0.850`; the six ids are named in the report"*.

## Rulings

1. **A page the candidate does not have fails every assertion anchored on it**, with the
   explanation *"page N of doc D is missing from the candidate"*. A dropped page is a loss the
   tool made, not a gap in the run: the assertion ran, against nothing.
2. **An assertion with no page runs against the document's pages joined in page order**, a blank
   line between, which is how a whole-document tool's output reads.
3. **A `rejected` assertion does not run**, and a `NULL`-checked one does (13:1022): its verdict is
   written and the rollup leaves it unscored (D816).
4. **An assertion the text evaluator cannot judge is not run and is named** in `Judged.not_run`
   with the reason the evaluator gave. It is neither a pass nor a fail, and no verdict row claims
   otherwise.
5. **A verdict's `slice_key` is the assertion's first slice, or `*`**, the unsliced key D815 and
   D816 use. `explanation` is the evaluator's: empty on a pass.
6. **Verdicts come back in assertion-id order**, so a run's verdict list is the same whatever order
   its assertions arrived in.

Specified in 13-quality.md sections 8.1, 8.5 and 2.10.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Verdict

from omniweave_conform.assertions import evaluate_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_core.store.oweval import Assertion

__all__ = ["EVALUATOR", "UNSLICED", "Judged", "judge"]

EVALUATOR: Final = "text"
UNSLICED: Final = "*"
REJECTED: Final = "rejected"
PAGE_JOIN: Final = "\n\n"


@dataclass(frozen=True, slots=True)
class Judged:
    """A run's verdicts, the ids that failed, and what was not run and why."""

    verdicts: tuple[Verdict, ...]
    failed: tuple[str, ...]
    not_run: tuple[tuple[str, str], ...]

    @property
    def passed(self) -> int:
        return sum(1 for v in self.verdicts if v.passed)


def judge(
    assertions: Iterable[Assertion],
    pages: Mapping[tuple[str, int], str],
    *,
    run_id: str,
) -> Judged:
    """Every assertion over its page of the candidate (rulings 1-6)."""
    verdicts, failed, not_run = [], [], []
    for assertion in sorted(assertions, key=lambda a: a.assertion_id):
        if assertion.checked == REJECTED:
            continue
        text = _text(assertion, pages)
        if text is None:
            verdict = _verdict(
                assertion,
                run_id,
                passed=False,
                why=f"page {assertion.page} of doc {assertion.doc} is missing from the candidate",
            )
        else:
            try:
                got = evaluate_text(assertion, text)
            except QualityError as refused:
                not_run.append((assertion.assertion_id, str(refused)))
                continue
            verdict = _verdict(assertion, run_id, passed=got.passed, why=got.explanation)
        verdicts.append(verdict)
        if not verdict.passed:
            failed.append(assertion.assertion_id)
    return Judged(verdicts=tuple(verdicts), failed=tuple(failed), not_run=tuple(not_run))


def _text(assertion: Assertion, pages: Mapping[tuple[str, int], str]) -> str | None:
    """Rulings 1 and 2: the page's text, the document's pages joined, or `None` for a lost page."""
    if assertion.page is not None:
        return pages.get((assertion.doc, assertion.page))
    ours = sorted((page, text) for (doc, page), text in pages.items() if doc == assertion.doc)
    return PAGE_JOIN.join(text for _, text in ours)


def _verdict(assertion: Assertion, run_id: str, *, passed: bool, why: str) -> Verdict:
    """Ruling 5."""
    return Verdict(
        run_id=run_id,
        assertion_id=assertion.assertion_id,
        evaluator=EVALUATOR,
        passed=passed,
        score=None,
        slice_key=assertion.slices[0] if assertion.slices else UNSLICED,
        explanation=why,
    )
