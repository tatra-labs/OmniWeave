"""Q-G14: the renderer test, fed each `CalStatus`, asserting output shape.

13:1998 registers the enforcer in those words and 13:1522 says why shape and not text -- *"so a copy
change cannot break the gate and a bar cannot sneak in behind one"*. Section 3 is that test, and it
asserts the ban as an ABSENCE over a generated space rather than as an equality against four
strings: a hypothesis property drives every non-calibrated reading through `render_confidence()` and
requires the output to carry no digit at all.

The other three families:

* **The vocabularies are the plan's, parsed out of it.** Section 1 reads `CalStatus` and
  `EvalStatus` out of `_notes/charter.md`'s own fence, so a member added to one and not the
  other fails here rather than in a review.
* **Two spellings of one suffix, and ADR-11 rules both.** Section 4 reproduces
  `adr/0011-eval-register-reconciliation.md`'s two ruled cells byte for byte, and reproduces
  10:657's provenance row and 10:635's header tail from a `RenderedBlock`.
* **A numeral needs a clock.** Section 5 drives Q-G13's `max_age_days = 30` from both sides of the
  boundary and asserts that the clockless case REFUSES rather than assuming freshness.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.answer.render import RenderedBlock
from omniweave_core.calibration import (
    BOOTSTRAP,
    CAL_STATUS_BY_EVAL,
    CAL_STATUSES,
    CALIBRATED,
    CALIBRATION_STALE,
    EVAL_STATUSES,
    MAX_AGE_DAYS,
    MAX_AGE_NS,
    NO_SCORE,
    STALE,
    UNCALIBRATED,
    UNCALIBRATED_MARK,
    UNCALIBRATED_MARK_SHORT,
    Calibrated,
    cal_status_of_eval,
    effective_status,
    is_publishable,
    render_confidence,
)
from omniweave_core.errors import QualityError
from omniweave_core.model.enums import Quote
from omniweave_core.observe.degradation import DEGRADATION_KINDS

if TYPE_CHECKING:
    from conftest import PlanDocs

CHARTER = "_notes/charter.md"
QUALITY = "13-quality.md"
INTERFACES = "10-interfaces.md"
ADR11 = "adr/0011-eval-register-reconciliation.md"

DAY_NS = 24 * 60 * 60 * 1_000_000_000

CLOSE = chr(0x00BB) + chr(42) * 2
"""10:629's block-header terminator: U+00BB, then two asterisks. Built from codepoints for the
reason `GRADE` gives below."""

# A fitted reading, and the only shape in this file that may print a digit.
FITTED = Calibrated(
    signal="block.trust",
    value="extracted",
    status=CALIBRATED,
    p_correct=0.977,
    ci95=(0.972, 0.982),
    n=4102,
    eval_set_id="parse-cal@2026.09",
    slice_key="office/docx",
    measured_at_ns=0,
)

# The same curve over a PROBABILITY signal, which is the only kind a numeral can come from.
FITTED_PROB = Calibrated(
    **{
        **{n: getattr(FITTED, n) for n in Calibrated.__slots__},
        "signal": "garble.score",
        "value": 0.0331,
    }
)

# 10:657's `handbook:d7#418` cell, as the wrapper that produces it.
LAYOUT = Calibrated(
    signal="layout",
    value="high",
    status=UNCALIBRATED,
    p_correct=None,
    ci95=None,
    n=0,
    eval_set_id="",
    slice_key="",
    measured_at_ns=0,
)


def _literal(text: str, name: str) -> tuple[str, ...]:
    """The members of a one-line `X = Literal[...]` of strings, in the source's order."""
    line = next(ln for ln in text.splitlines() if ln.startswith(f"{name} = Literal["))
    return tuple(re.findall(r'"([a-z_]+)"', line))


# =============================================================================================
# 1. The two vocabularies, read out of the charter's own fence
# =============================================================================================


def test_cal_statuses_are_the_charters_four_in_its_order(plan: PlanDocs) -> None:
    """charter.md:7328. Four members and the order is the document's, not alphabetical."""
    plan.require()
    assert _literal(plan.text(CHARTER), "CalStatus") == CAL_STATUSES
    assert len(CAL_STATUSES) == 4


def test_eval_statuses_are_the_charters_five(plan: PlanDocs) -> None:
    """charter.md:7293, transcribed only so the join in section 2 is expressible."""
    plan.require()
    assert _literal(plan.text(CHARTER), "EvalStatus") == EVAL_STATUSES


def test_the_two_vocabularies_share_exactly_one_spelling() -> None:
    """`stale` is a curve's age here and a gate's verdict there, and nothing says they are one."""
    assert set(CAL_STATUSES) & set(EVAL_STATUSES) == {STALE}


def test_the_named_rungs_are_the_tuples_members() -> None:
    """Four constants and one tuple, never two lists. INV-21 allows a fact one home."""
    assert (CALIBRATED, BOOTSTRAP, UNCALIBRATED, STALE) == CAL_STATUSES


def test_calibration_stale_is_a_degradation_kind() -> None:
    """13:1544 pairs `status = 'stale'` with `Degradation(kind="calibration_stale")`.

    Asserted rather than imported: this module names one member of a twenty-seven-member closed
    literal and has no reason to pull the literal in, but a spelling that drifted would otherwise
    be caught by nothing.
    """
    assert CALIBRATION_STALE in DEGRADATION_KINDS


def test_max_age_days_is_the_plans_thirty(plan: PlanDocs) -> None:
    """13:1544's `max_age_days = 30`, and the nanosecond form derived from it rather than typed."""
    plan.require()
    assert f"max_age_days = {MAX_AGE_DAYS}" in plan.text(QUALITY)
    assert MAX_AGE_NS == MAX_AGE_DAYS * DAY_NS


# =============================================================================================
# 2. The join the plan states once, and the four it does not
# =============================================================================================


def test_pass_is_the_one_stated_join() -> None:
    """00:750 makes `calibrated` follow from a Q-G11 or Q-G12 pass, and states no other pair."""
    assert cal_status_of_eval("pass") == CALIBRATED
    assert CAL_STATUS_BY_EVAL == {"pass": CALIBRATED}


@pytest.mark.parametrize("verdict", [v for v in EVAL_STATUSES if v != "pass"])
def test_every_other_verdict_is_none_rather_than_a_guess(verdict: str) -> None:
    """05:2122 -- uncomputable is `None`, never a default value. D284 is the entry."""
    assert cal_status_of_eval(verdict) is None


def test_an_unknown_verdict_raises_rather_than_returning_none() -> None:
    """`None` means "the plan states no rule", so a typo must not be able to mean it too."""
    with pytest.raises(QualityError) as caught:
        cal_status_of_eval("passed")
    assert caught.value.fix


# =============================================================================================
# 3. Q-G14 -- the shape, over all four statuses and over a generated space
# =============================================================================================

DIGIT = re.compile(r"[0-9]")

GRADE = chr(42)
"""U+002A ASTERISK, named by its codepoint rather than written.

A bare star inside a string literal pairs with the next quote character and makes this file's own
prose look like a citation to the scratchpad's quote checker -- the same repair the `ow:status`
marker needed in `answer/render.py`."""

ESCAPE = chr(27)
"""U+001B, the first byte of every ANSI colour sequence. A colour ramp, as a byte."""

FORBIDDEN = ("%", "|", "#", chr(0x2588), chr(0x2591), ESCAPE, "[]", GRADE)
"""A percentage, a bar in three spellings a terminal renderer reaches for, a colour escape and a
grade: 13:1521's banned list as characters rather than as a sentence."""


@pytest.mark.parametrize("status", CAL_STATUSES)
@pytest.mark.parametrize("abbreviated", [False, True])
def test_the_four_statuses_and_the_shape_each_one_prints(status: str, *, abbreviated: bool) -> None:
    """Q-G14's registered test: each `CalStatus`, and the output's SHAPE rather than its text."""
    now = MAX_AGE_NS  # inside the window for a reading measured at 0, so `FITTED` stays fitted
    reading = (
        FITTED if status == CALIBRATED else Calibrated(**{**vars_of(LAYOUT), "status": status})
    )
    out = render_confidence(reading, now_ns=now, abbreviated=abbreviated)
    assert not any(bad in out for bad in FORBIDDEN)
    if status == CALIBRATED:
        # The member name and NO mark. 13:1442 makes `block.trust` the one ordinal of the four, so
        # this rung's calibrated output differs from its uncalibrated one only by the missing
        # suffix -- which is the whole visible content of Q-G14 for an ordinal signal.
        assert out == "block.trust: extracted"
        assert UNCALIBRATED_MARK not in out
        assert UNCALIBRATED_MARK_SHORT not in out
        return
    assert DIGIT.search(out) is None
    mark = UNCALIBRATED_MARK_SHORT if abbreviated else UNCALIBRATED_MARK
    assert out.endswith(f" {mark}")
    assert out.startswith(f"{reading.signal}: ")


def vars_of(cal: Calibrated) -> dict[str, object]:
    """`dataclasses.asdict` would recurse into `ci95`; this is the flat field map."""
    return {name: getattr(cal, name) for name in Calibrated.__slots__}


@given(
    signal=st.sampled_from(["block.trust", "garble.score", "page.ocr_score", "layout"]),
    name=st.sampled_from(["high", "medium", "low", "extracted", "inferred", "ambiguous"]),
    status=st.sampled_from([s for s in CAL_STATUSES if s != CALIBRATED]),
)
def test_no_uncalibrated_rendering_ever_carries_a_digit(
    signal: str, name: str, status: str
) -> None:
    """The ban as an absence over a generated space, which is what makes it a gate.

    An equality against four strings passes when a fifth branch is added; this fails.
    """
    reading = Calibrated(
        signal=signal,
        value=name,
        status=status,
        p_correct=0.5,
        ci95=(0.4, 0.6),
        n=1234,
        eval_set_id="e",
        slice_key="s",
        measured_at_ns=0,
    )
    for abbreviated in (False, True):
        out = render_confidence(reading, now_ns=DAY_NS, abbreviated=abbreviated)
        assert DIGIT.search(out) is None
        assert "0.5" not in out
        assert "1234" not in out


def test_the_three_non_calibrated_rungs_render_identically() -> None:
    """`bootstrap`, `uncalibrated` and `stale` are one output. 13:1544 carries the difference in
    the envelope, as `CALIBRATION_STALE`, and never in the cell."""
    rendered = {
        status: render_confidence(
            Calibrated(**{**vars_of(LAYOUT), "status": status}), now_ns=DAY_NS
        )
        for status in (BOOTSTRAP, UNCALIBRATED, STALE)
    }
    assert len(set(rendered.values())) == 1


def test_a_null_pair_renders_the_dash() -> None:
    """10:739 -- *"`-` where the pair is NULL"*; 03:295 makes `score`/`score_kind` nullable
    together, so `None` is the pair's other state and not a missing argument."""
    assert render_confidence(None) == NO_SCORE
    assert render_confidence(None, abbreviated=True) == NO_SCORE


def test_a_float_under_an_uncalibrated_status_renders_the_dash() -> None:
    """D283. The rule permits an ordinal NAME and nothing bins a float into one, so the cell goes
    empty rather than carrying a rank nobody fitted."""
    probability = Calibrated(**{**vars_of(LAYOUT), "value": 0.71})
    assert render_confidence(probability, now_ns=DAY_NS) == NO_SCORE
    assert render_confidence(probability, now_ns=DAY_NS, abbreviated=True) == NO_SCORE


def test_three_of_the_four_registered_signals_are_probabilities(plan: PlanDocs) -> None:
    """13:1438's table is D283's size: only `block.trust` is an ordinal, so the one form the
    surfacing rule permits fits one of the four signals the chain is mandatory for."""
    plan.require()
    table = plan.text(QUALITY).splitlines()[1437:1446]
    rows = [ln for ln in table if ln.startswith("| `")]
    ordinals = [ln for ln in rows if "ordinal" in ln]
    assert len(rows) == 4
    assert len(ordinals) == 1
    assert "block.trust" in ordinals[0]


# =============================================================================================
# 4. The two spellings, and the cells ADR-11 rules
# =============================================================================================


def test_the_two_marks_are_the_two_spellings_the_corpus_prints(plan: PlanDocs) -> None:
    """01:521 and 13:1522 spell it out; 10:739 abbreviates it. Both are in the plan verbatim."""
    plan.require()
    assert UNCALIBRATED_MARK in plan.text(QUALITY)
    assert UNCALIBRATED_MARK_SHORT in plan.text(INTERFACES)


def test_adr11_rules_both_cells_and_the_renderer_reproduces_them(plan: PlanDocs) -> None:
    """The ADR's own ruling row, parsed and reproduced -- long in the header, short in the table."""
    plan.require()
    row = next(ln for ln in plan.text(ADR11).splitlines() if "in the header" in ln)
    assert f"`layout: high {UNCALIBRATED_MARK_SHORT}`" in row
    assert f"`layout: high {UNCALIBRATED_MARK}`" in row
    assert render_confidence(LAYOUT, abbreviated=True) == f"layout: high {UNCALIBRATED_MARK_SHORT}"
    assert render_confidence(LAYOUT) == f"layout: high {UNCALIBRATED_MARK}"


def _block(score: Calibrated | None) -> RenderedBlock:
    """10:635 and 10:657's `handbook:d7#418`, as the renderer's input."""
    return RenderedBlock(
        cite="handbook:d7#418",
        addr="p14/9",
        doc_uri="policy.pdf",
        page=14,
        kind="paragraph",
        text="...",
        quote=Quote.REFLOWED,
        trust="inferred",
        method="text_layer",
        origin_driver="parse.pdf.pdfium@2",
        byte_exact=False,
        score=score,
    )


def test_the_block_header_ends_in_the_plans_own_sixth_field(plan: PlanDocs) -> None:
    """10:635's header, whose last field before the closing guillemet is the long spelling."""
    plan.require()
    printed = next(ln for ln in plan.text(INTERFACES).splitlines() if "handbook:d7#418 " in ln)
    tail = f"layout: high {UNCALIBRATED_MARK} {CLOSE}"
    assert printed.endswith(tail)
    assert _block(LAYOUT).header.endswith(tail)


def test_a_block_with_no_confidence_grows_no_sixth_field() -> None:
    """10:622's header has five fields, so the confidence is present only when there is one."""
    assert NO_SCORE not in _block(None).header
    assert _block(None).header.endswith(f"parse.pdf.pdfium@2 {CLOSE}")


def test_the_provenance_cell_is_10_657s(plan: PlanDocs) -> None:
    """The score column of the plan's own middle row, and of a row rendered from the wrapper."""
    plan.require()
    printed = next(ln for ln in plan.text(INTERFACES).splitlines() if "| p14/9 |" in ln)
    cells = [cell.strip() for cell in printed.strip().strip("|").split("|")]
    assert cells[9] == f"layout: high {UNCALIBRATED_MARK_SHORT}"
    assert cells[10] == NO_SCORE
    assert render_confidence(_block(LAYOUT).score, abbreviated=True) == cells[9]


def test_the_generated_schema_carries_the_four_member_enum() -> None:
    """`schema/answer-v1.json` is T-GENERATED and G6-gated, so the vocabulary is now gate-visible:
    a fifth `CalStatus` cannot land without a byte diff a human approves."""
    root = Path(__file__).resolve().parents[4]
    schema = json.loads((root / "schema" / "answer-v1.json").read_text(encoding="utf-8"))
    assert tuple(schema["$defs"]["Calibrated"]["properties"]["status"]["enum"]) == CAL_STATUSES


# =============================================================================================
# 5. Q-G13 -- a numeral needs a clock
# =============================================================================================


def test_a_fitted_curve_inside_the_window_publishes() -> None:
    """Strictly inside, and AT the boundary: 13:1544 says *"past `max_age_days = 30`"*, so thirty
    days exactly is not past it."""
    assert is_publishable(FITTED, MAX_AGE_NS)
    assert effective_status(FITTED, MAX_AGE_NS) == CALIBRATED
    assert DIGIT.search(render_confidence(FITTED_PROB, now_ns=MAX_AGE_NS)) is not None
    assert render_confidence(FITTED_PROB, now_ns=MAX_AGE_NS) == "garble.score: 0.0331"


def test_a_fitted_curve_past_the_window_prints_no_digit() -> None:
    """The case the stored field gets wrong: `status` still says `calibrated` and the clock does
    not. Q-G13 is checked where the characters are produced."""
    stale_now = MAX_AGE_NS + 1
    assert FITTED_PROB.status == CALIBRATED
    assert effective_status(FITTED_PROB, stale_now) == STALE
    assert not is_publishable(FITTED_PROB, stale_now)
    # A float under a non-calibrated status has no ordinal name, so the cell empties. D283, and it
    # is the right failure: the digit Q-G13 withdrew is not replaced by a rank nobody fitted.
    assert render_confidence(FITTED_PROB, now_ns=stale_now) == NO_SCORE


def test_a_clockless_numeral_refuses() -> None:
    """Fail-closed: no clock is not the same fact as a fresh curve."""
    with pytest.raises(QualityError) as caught:
        render_confidence(FITTED)
    assert caught.value.fix
    assert str(MAX_AGE_DAYS) in caught.value.fix


@pytest.mark.parametrize("status", [s for s in CAL_STATUSES if s != CALIBRATED])
def test_a_clockless_non_numeral_does_not_refuse(status: str) -> None:
    """Only the numeral depends on the answer, so only the numeral pays for the clock."""
    reading = Calibrated(**{**vars_of(LAYOUT), "status": status})
    assert render_confidence(reading) == f"layout: high {UNCALIBRATED_MARK}"
    assert effective_status(reading, None) == status


# =============================================================================================
# 6. A reading that contradicts itself
# =============================================================================================


def test_a_calibrated_reading_must_carry_the_bucket_it_was_fitted_on() -> None:
    """INV-19's first half at construction. 01:517 -- *"Every number carries its evidence"*."""
    for missing in ("p_correct", "ci95", "eval_set_id", "n"):
        blank: object = None if missing != "eval_set_id" else ""
        if missing == "n":
            blank = 0
        with pytest.raises(QualityError) as caught:
            Calibrated(**{**vars_of(FITTED), missing: blank})
        assert missing in str(caught.value)


def test_an_uncalibrated_reading_needs_none_of_it() -> None:
    """The check is asymmetric on purpose: a reading with no curve is the normal case at release 1
    and must be constructible without inventing a bucket for it."""
    assert LAYOUT.p_correct is None
    assert LAYOUT.n == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "calibrating"),
        ("signal", ""),
        ("n", -1),
        ("p_correct", 1.5),
        ("ci95", (0.9, 0.2)),
        ("ci95", (-0.1, 0.2)),
    ],
)
def test_the_refusals_each_name_a_fix(field: str, value: object) -> None:
    """Every `OwError` in this codebase carries a `fix=`, and a refusal with none is a dead end."""
    with pytest.raises(QualityError) as caught:
        Calibrated(**{**vars_of(LAYOUT), field: value})
    assert caught.value.fix


def test_a_reading_is_frozen() -> None:
    """01:531's argument one field further: a mutable reading lets a caller promote the status
    after the numbers were fitted."""
    with pytest.raises((AttributeError, TypeError)):
        LAYOUT.status = CALIBRATED  # type: ignore[misc]


# =============================================================================================
# 7. The internal-filter clause, which this module satisfies by doing nothing
# =============================================================================================


def test_an_uncalibrated_reading_is_still_a_sort_key() -> None:
    """13:1527 -- *"An uncalibrated signal remains usable as an internal filter and sort key."*

    The wrapper hides the number from the PAGE and not from code. A version that hid it from both
    would have broken the `block_review` partial index on day one, which is 13:1528's point.
    """
    readings = [
        Calibrated(**{**vars_of(LAYOUT), "signal": "garble.score", "value": v})
        for v in (0.9, 0.1, 0.5)
    ]
    assert [r.value for r in sorted(readings, key=lambda r: float(r.value))] == [0.1, 0.5, 0.9]
    assert [r for r in readings if float(r.value) < 0.5] == [readings[1]]
    assert {render_confidence(r, now_ns=DAY_NS) for r in readings} == {NO_SCORE}
