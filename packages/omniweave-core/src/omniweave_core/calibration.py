"""`Calibrated` and `CalStatus` -- the wrapper a confidence crosses the serve boundary inside.

03:1720 states the whole cell in four clauses: *"`score` is never rendered as a number to a user. It
crosses the serve boundary inside `Calibrated`, which carries the raw value, a `CalStatus`, the
bucket's empirical accuracy and Wilson interval, `n`, `eval_set_id` and `slice_key`; the renderer
consumes the **status**, never the float."* 13:1427 says why that is a type and not a convention:
*"There is no code path from an uncalibrated number to a bar."* A code path is a thing a module
either has or does not, so the ban belongs where the path would be.

## What this module is for, in one sentence

`render_confidence()` is the only function in the framework that turns a confidence into characters,
so INV-19's ban is one `if` in one place rather than a rule every surface remembers.

01:520 is the invariant: *"A confidence whose `Calibrated.status != "calibrated"` may print an
ordinal name plus `(uncalibrated)` and may never print a numeral, percentage, bar, colour or
grade -- while remaining usable as an internal filter and sort key."* 13:1998 registers the enforcer
as a test rather than a lint -- *"a renderer test over all four `CalStatus` values, asserting output
**shape**"* -- and 13:1522 says why shape and not text: *"so a copy change cannot break the gate and
a bar cannot sneak in behind one."*

## The home, which the tree does not name

11:186-207 prints core's file tree and this module is not in it, exactly as `quality.py` is not.
Both are the same derivation. `Calibrated` has three consumers in three distributions -- the
calibrator and the scoreboard generator in `omniweave_conform` (11:123), the provenance table and
the block header in `omniweave_core.answer`, and `ow eval calibrate`'s writer in `omniweave` --
and `tools/layers.toml` gives `omniweave_conform` and `omniweave` no edge to each other. Their only
common ancestor is this distribution. `quality.py`'s docstring argues the same derivation for
`TruthKind` at length and this module does not repeat it; D231 records that a derived answer is
still a gap.

Not folded INTO `quality.py`, because that module's subject is what a metric's reference IS and this
one's is what a reading may PRINT. They share a charter fence (charter.md:7273-7366) and nothing
else: `TruthKind` is read by the harness that refuses an inadmissible column, and `Calibrated` is
read by a renderer. Stdlib only, eager, exporting nothing into `omniweave_core/__init__.py`'s nine
lazy names.

## Two spellings of one suffix, and they are a ruling rather than a slip

10:739 renders the provenance cell as *"`<kind>: <ordinal>` plus `(uncal.)` while
`Calibrated.status != "calibrated"`, and `-` where the pair is NULL"*, and 10:635's evidence header
prints the same block's same signal as `layout: high (uncalibrated)`. One document, one worked
Answer, two spellings of one suffix, eighteen lines apart.

[ADR-11](../../../../../_plan/adr/0011-eval-register-reconciliation.md):94 rules both deliberate:
the two cells become `layout: high (uncal.)` in the table and `layout: high (uncalibrated)` in the
header. The difference is column width -- `ow:provenance` is eleven columns inside a 549-character
section (10:698) -- and both forms satisfy Q-G14, whose test asserts shape. So `UNCALIBRATED_MARK`
and `UNCALIBRATED_MARK_SHORT` are two constants, one switch chooses between them, and both arrive
through the same status branch. The alternative -- one spelling everywhere -- would have been a
quieter implementation that contradicts a decision record.

## The two numbers `Calibrated` cannot turn into an ordinal, and D283

13:1438's table registers four signals and three of them are probabilities: `garble.score`,
`page.ocr_score` and `retrieval.confidence`. Only `block.trust` is an ordinal. But the surfacing
rule at 13:1521 permits exactly one thing, *"the ordinal member name followed by
`(uncalibrated)`"*, so for three of the four registered signals it permits nothing at all.

ADR-11 nevertheless rules a rendered output for a fourth, unregistered one: `layout`, whose store
value is `score REAL` (03:2343) and whose charter cell is `0.71`, becomes `high`. Something bins a
float into a name and no document says what. Any binning this module chose would be a claim that
0.71 is high on the `layout` scale -- which is the claim `status != "calibrated"` exists to say we
cannot make.

**Shipped:** a float under a non-calibrated status renders `NO_SCORE`. The cell goes empty rather
than carrying a rank nobody fitted. D283 is the entry, and the fix is one column in
`tools/scorekinds.toml`: 13:1417 already requires the register to carry each scale's *"domain,
semantics, declared consumers, eval set and calibration numbers"*, and ordinal band names are
semantics.

## A numeral needs a clock, which Q-G13 requires and no signature carries

13:1544 makes a curve past `max_age_days = 30` carry `status = 'stale'` plus
`Degradation(kind="calibration_stale")`. But `status` is a stored field written by `ow eval
calibrate` (15:1097), and `measured_at_ns` is stored beside it, so a reading fitted forty days ago
and never re-run still says `calibrated`. The two fields can disagree, and the only case where the
disagreement is visible is the one that matters: a `calibrated` reading past the age prints a
numeral that Q-G13 says is stale.

`effective_status()` recomputes from the clock and `render_confidence()` calls it, so staleness is
derived at the point of printing rather than trusted from a field. The cost is that printing a
numeral now requires a `now_ns`; `render_confidence()` refuses a calibrated reading without one
rather than defaulting to fresh, which is the fail-closed direction. At release 1 nothing is
calibrated (13:1531), so nothing pays it.

## The internal-filter clause lives in the store, not here

13:1527: *"An uncalibrated signal remains usable as an internal filter and sort key."* The example
the plan gives is `block_review`'s partial index, `WHERE trust < 2` -- SQL over the `block.trust`
INTEGER column, which this wrapper never stands between. So the clause is satisfied by this module
doing nothing: `Calibrated.value` is a public field, code may read and sort it, and only
`render_confidence()` is forbidden to print it. A wrapper that hid the number from code as well as
from the page would have broken the review surface on day one, which is 13:1528's point.

Specified in 03-document-model.md section 8.4, 13-quality.md section 9.4 and 01-principles.md
INV-19; ruled by ADR-11 decision 4; scheduled by 16-roadmap.md:663.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

from omniweave_core.errors import QualityError

__all__ = [
    "BOOTSTRAP",
    "CALIBRATED",
    "CALIBRATION_STALE",
    "CAL_STATUSES",
    "CAL_STATUS_BY_EVAL",
    "EVAL_STATUSES",
    "MAX_AGE_DAYS",
    "MAX_AGE_NS",
    "NO_SCORE",
    "STALE",
    "UNCALIBRATED",
    "UNCALIBRATED_MARK",
    "UNCALIBRATED_MARK_SHORT",
    "CalStatus",
    "Calibrated",
    "cal_status_of_eval",
    "effective_status",
    "is_publishable",
    "render_confidence",
]


# =============================================================================================
# 1. The two vocabularies, and the join the plan does not state
# =============================================================================================

CalStatus = Literal["calibrated", "bootstrap", "uncalibrated", "stale"]
"""charter.md:7328's literal, in its order.

A `Literal` and not a `StrEnum` because that is what the charter prints and because 13:2045 records
the terminology-lock gap in those words -- `CalStatus` *"appears in the charter as a `Literal` alias
and in the lock"* -- discharged by ADR-1, which put it in the lock as a type and not as a class."""

CAL_STATUSES: Final[tuple[str, ...]] = get_args(CalStatus)
"""The same four as a tuple, for iteration and validation.

`get_args` rather than a second list: INV-21 allows a fact one home, and 13:1523's renderer test
feeds *"each of the four `CalStatus` values"*, so the test's parametrisation and the type's
membership must be the same object or the gate can pass over three."""

CALIBRATED: Final[str] = CAL_STATUSES[0]
"""The one status that licenses a digit. Every rule in this module is keyed on `!= CALIBRATED`."""

BOOTSTRAP: Final[str] = CAL_STATUSES[1]
"""Shipped with no eval set registered. 17:500 is the only site that says what it means in use --
`garble.score` *"ships reporting `calibration: bootstrap`"* -- and no document defines it."""

UNCALIBRATED: Final[str] = CAL_STATUSES[2]
"""Measured and not separated, or measured below `n`. Renders identically to `BOOTSTRAP`."""

STALE: Final[str] = CAL_STATUSES[3]
"""A curve past `MAX_AGE_DAYS`. 13:1544. Renders identically to the other two non-calibrated rungs;
the difference is carried in the envelope by `CALIBRATION_STALE`, never in the cell."""

EVAL_STATUSES: Final[tuple[str, ...]] = ("pass", "fail", "unstable", "stale", "unknown")
"""charter.md:7293's `EvalStatus`, transcribed here only to make the join below expressible.

Its home is the eval harness, which does not exist yet. Five members against `CalStatus`'s four,
sharing one spelling (`stale`) that means two things: here a curve's age, there a gate's verdict."""

CAL_STATUS_BY_EVAL: Final[dict[str, str]] = {"pass": CALIBRATED}
"""The one pair the plan states. D284.

00:750 makes `status == "calibrated"` follow from a gate verdict -- *"ordinal separation under
`Q-G11` ... or probability sharpness under `Q-G12`"* -- so `pass -> calibrated` is stated. The other
four are not, and the readings that suggest themselves disagree with each other: `unknown` is
13:1545's *"a slice below `n = 150` per bucket"*, which is a measurement that did not reach the bar,
while `BOOTSTRAP` is a scale with no eval set at all, and nothing says which of the two an
under-powered slice becomes. One stated pair, and `None` for the rest -- 05:2122's discipline,
*"Uncomputable is None; NEVER a default value"*, applied to a question the plan does not answer."""

CALIBRATION_STALE: Final[str] = "calibration_stale"
"""The degradation a `STALE` reading carries. 13:1544; 15:1097 names `ow eval calibrate` as the fix.

A member of `omniweave_core.observe.degradation.DEGRADATION_KINDS`, asserted by test rather than
imported: this module has no reason to pull the twenty-seven-member literal in to name one of
them, and an assertion catches the drift an import would only have hidden behind a NameError."""

MAX_AGE_DAYS: Final[int] = 30
"""13:1544's `max_age_days`. 13:1997 notes the weekly fit gives 4x headroom."""

MAX_AGE_NS: Final[int] = MAX_AGE_DAYS * 24 * 60 * 60 * 1_000_000_000
"""The same bound against `measured_at_ns`, whose unit charter.md:7342 fixes as nanoseconds."""


# =============================================================================================
# 2. What a non-calibrated reading is allowed to print
# =============================================================================================

UNCALIBRATED_MARK: Final[str] = "(uncalibrated)"
"""01:521 and 13:1522's spelling, printed in the evidence header at 10:635."""

UNCALIBRATED_MARK_SHORT: Final[str] = "(uncal.)"
"""10:739's spelling, printed in the provenance cell at 10:657. ADR-11:94 rules both deliberate."""

NO_SCORE: Final[str] = chr(0x2013)
"""U+2013 EN DASH -- 10:739's *"`-` where the pair is NULL"*, and this module's fail-closed output.

Named by codepoint because `ruff`'s RUF001 reads the glyph in a string literal as an ambiguous
hyphen and because the character is the whole value; a reader who cannot see which dash it is
cannot check the cell against the plan's own table."""

_SEPARATOR: Final[str] = ": "
"""10:739's `<kind>: <ordinal>`, and 10:635's `layout: high (uncalibrated)`. One space after."""

_CLOCKLESS_NUMERAL: Final[str] = "OW_CAL_CLOCKLESS_NUMERAL"
"""Rendering a `CALIBRATED` reading with no clock to check `MAX_AGE_DAYS` against.

No definition site spells a symbol for this condition -- Q-G13 names the rule and not a raise -- so
the spelling is this module's and a `codes.toml` row for it is a required edit, the same shape
`omniweave_core.store.doc`'s `OW_SCORE_KIND_UNREGISTERED` already carries."""

_BAD_READING: Final[str] = "OW_CAL_READING_INVALID"
"""A `Calibrated` whose fields contradict its status. See `__post_init__`."""


# =============================================================================================
# 3. The wrapper
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Calibrated:
    """charter.md:7331's nine fields, in its order.

    Frozen because a reading is a measurement: 01:531 makes `MeasuredOn` *"frozen with **no
    defaults** and ten fields, so a card supplying seven of them raises `TypeError` at construction
    rather than writing a blank cell"*, and the same argument reaches one field further -- a
    mutable reading lets a caller set `status = "calibrated"` after the numbers were fitted.

    No defaults, for that reason. Nine arguments is the price of INV-19, 01:517 -- *"every number
    carries its evidence"* -- and a default would have been the blank cell that invariant forbids.
    """

    signal: str
    """`'block.trust' | 'garble.score' | 'page.ocr_score'` -- charter.md:7334's comment, which is
    three of 13:1438's four; `retrieval.confidence` is the fourth. Not validated against a closed
    set here: the register is `tools/scorekinds.toml`, which is append-only and does not exist
    yet, and `DocSink.add_block` already refuses an unregistered kind at the write (03:295)."""

    value: float | str
    """The raw score, or the ordinal member name. charter.md:7335.

    The union is keyed on the SIGNAL's shape and not on the status: `block.trust` is an ordinal so
    its value is a member name, and the other three of 13:1438's four are probabilities so theirs
    is a float. `Calibrated` carries no field saying which, so `isinstance` is the discriminator --
    which is exactly why a float under a non-calibrated status has nothing to print. D283."""

    status: CalStatus
    """The field every render decision is keyed on, and the only one `render_confidence()` may
    branch on before it has decided whether a digit is allowed at all."""

    p_correct: float | None
    """charter.md:7337 -- *"the empirical accuracy of THIS bucket in THIS slice"*. Never printed
    while `status != CALIBRATED`: it is a numeral adjacent to the signal, which 13:1521 bans."""

    ci95: tuple[float, float] | None
    """The bucket's Wilson 95% interval. 13:401 makes Wilson the only interval -- *"never the normal
    approximation, which is wrong at the p->1 end where our gates live"*."""

    n: int
    """The bucket's sample size. 13:1545 puts the ordinal floor at 150 per bucket per slice and
    13:1494's `sharpness` floor at 1000; neither is checked here, because both are gate thresholds
    and a reading below them is a real reading with a `status` that says so."""

    eval_set_id: str
    """`parse-cal@<corpus version>` and its three siblings, 13:1442-1445."""

    slice_key: str
    """The slice the bucket was measured in -- `office/docx`, `pdf/scan-degraded` (13:1508-1511).
    13:1545 requires an under-powered slice to be NAMED rather than pooled, which is what this
    field makes possible."""

    measured_at_ns: int
    """When the curve was fitted. The input to `effective_status()`, and the field that makes
    Q-G13 checkable at the point of printing rather than only at the point of fitting."""

    def __post_init__(self) -> None:
        """Four refusals, and each one is a state the render rule could not describe.

        None of them is a threshold: a reading below `n = 150` is a real reading and its `status`
        is where that fact belongs. What is refused is a reading that contradicts itself.
        """
        if self.status not in CAL_STATUSES:
            raise QualityError(
                f"{self.status!r} is not a CalStatus",
                symbol=_BAD_READING,
                fix=f"use one of {', '.join(CAL_STATUSES)}",
            )
        if not self.signal:
            raise QualityError(
                "a reading with no signal names no scale",
                symbol=_BAD_READING,
                fix="pass the registered score_kind, e.g. signal='block.trust'",
            )
        if self.n < 0:
            raise QualityError(
                f"n = {self.n} is not a sample size",
                symbol=_BAD_READING,
                fix="pass n = 0 for a reading fitted on no rows",
            )
        _check_interval(self.p_correct, self.ci95)
        if self.status == CALIBRATED:
            _check_calibrated(self)


def _check_interval(p_correct: float | None, ci95: tuple[float, float] | None) -> None:
    """A rate and its interval, both in `[0, 1]` and the interval ordered.

    13:401 makes every rate a Wilson 95% interval, and 13:1508's worked row prints `0.349` beside
    `0.288-0.416`. A `hi < lo` is not a narrower interval, it is a transposition -- and an interval
    that does not contain its own point estimate is a different fault that this does not check,
    because Wilson's centre is shrunk toward 0.5 and need not equal `p_hat` at small `n`.
    """
    if p_correct is not None and not (0.0 <= p_correct <= 1.0):
        raise QualityError(
            f"p_correct = {p_correct} is not a rate",
            symbol=_BAD_READING,
            fix="p_correct is the bucket's empirical accuracy, in [0, 1]",
        )
    if ci95 is None:
        return
    lo, hi = ci95
    if not (0.0 <= lo <= hi <= 1.0):
        raise QualityError(
            f"ci95 = ({lo}, {hi}) is not an ordered interval in [0, 1]",
            symbol=_BAD_READING,
            fix="pass (lo, hi) with lo <= hi, both in [0, 1]; a Wilson 95% interval",
        )


def _check_calibrated(cal: Calibrated) -> None:
    """INV-19's first half, at construction: a calibrated reading carries its evidence.

    01:519 requires *"`(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)`"* of a
    published metric, and a `CALIBRATED` reading is the only kind that publishes. Three of those
    seven are fields here; `method`, `corpus_digest`, `MeasuredOn` and `witness` are the
    `eval_metric` row's and are reached through `eval_set_id`. So the check is over what this
    shape can see, and it is the difference between a status that licenses a digit and a status
    that asserts one was earned.
    """
    missing = [
        name
        for name, present in (
            ("p_correct", cal.p_correct is not None),
            ("ci95", cal.ci95 is not None),
            ("eval_set_id", bool(cal.eval_set_id)),
            ("n", cal.n > 0),
        )
        if not present
    ]
    if missing:
        raise QualityError(
            f"a calibrated reading of {cal.signal!r} is missing {', '.join(missing)}",
            symbol=_BAD_READING,
            fix=(
                "a calibrated status licenses a digit, so it must carry the bucket it was fitted "
                f"on; use status={UNCALIBRATED!r} while the curve does not exist"
            ),
        )


# =============================================================================================
# 4. Freshness, and the one function that prints
# =============================================================================================


def effective_status(cal: Calibrated, now_ns: int | None) -> str:
    """The stored status, demoted to `STALE` when the curve is past `MAX_AGE_DAYS`. Q-G13.

    Only a `CALIBRATED` reading can be demoted, because the other three rungs already print the
    same thing and a demotion between them would be a difference nothing can observe.

    `now_ns is None` means the caller supplied no clock. A non-calibrated reading is returned
    unchanged -- its answer does not depend on the time -- and a calibrated one is the caller's
    error, raised by `render_confidence()` rather than silently treated as fresh.
    """
    if cal.status != CALIBRATED or now_ns is None:
        return cal.status
    if now_ns - cal.measured_at_ns > MAX_AGE_NS:
        return STALE
    return cal.status


def is_publishable(cal: Calibrated, now_ns: int | None) -> bool:
    """Whether this reading licenses a digit. The predicate `render_confidence()` branches on.

    Separate from the renderer because a caller that is deciding whether to ASK for a numeral --
    `ow eval`'s scoreboard, a card's benchmark row -- needs the answer without the characters, and
    two spellings of `status == CALIBRATED` is the second home INV-21 forbids.
    """
    return effective_status(cal, now_ns) == CALIBRATED


def render_confidence(
    cal: Calibrated | None,
    *,
    now_ns: int | None = None,
    abbreviated: bool = False,
) -> str:
    """The only function that turns a confidence into characters. 13:1427's single code path.

    Four outcomes, and three of them print no digit:

    * `cal is None` -- the `(score, score_kind)` pair is NULL, so there is nothing to render.
      10:739's *"`-` where the pair is NULL"*, which 10:657's first and third rows print.
    * publishable -- `<signal>: <value>`, the numeral included. 10:741: *"a calibrated one renders
      its numeral."* Nothing in the framework reaches this branch at release 1 (13:1531).
    * not publishable, `value` a string -- `<signal>: <name> (uncalibrated)`, which is the one form
      13:1521 permits. ADR-11:94's two cells are this branch, once each way.
    * not publishable, `value` a float -- `NO_SCORE`. No ordinal name exists and the numeral is
      banned, so the cell goes empty. D283.

    `abbreviated` selects 10:739's `(uncal.)` over 01:521's `(uncalibrated)`. It is a column width
    and not a mode: both arrive through this one branch, so there is no second path to audit.
    """
    if cal is None:
        return NO_SCORE
    status = effective_status(cal, now_ns)
    if cal.status == CALIBRATED and now_ns is None:
        raise QualityError(
            f"cannot render a calibrated reading of {cal.signal!r} without a clock",
            symbol=_CLOCKLESS_NUMERAL,
            fix=(
                "pass now_ns: Q-G13 demotes a curve past "
                f"max_age_days = {MAX_AGE_DAYS} to {STALE!r}, and the numeral is the one output "
                "that depends on the answer"
            ),
        )
    if status == CALIBRATED:
        return f"{cal.signal}{_SEPARATOR}{cal.value}"
    if not isinstance(cal.value, str):
        return NO_SCORE
    mark = UNCALIBRATED_MARK_SHORT if abbreviated else UNCALIBRATED_MARK
    return f"{cal.signal}{_SEPARATOR}{cal.value} {mark}"


def cal_status_of_eval(eval_status: str) -> str | None:
    """The gate verdict a curve was given, as the status a reading carries. `None` where unstated.

    One pair, and D284 is the entry. A `None` here is not a failure -- it is the answer that the
    plan states no rule -- and a caller that needs a status for a non-`pass` verdict must decide
    between `BOOTSTRAP` and `UNCALIBRATED` on grounds this module does not have.
    """
    if eval_status not in EVAL_STATUSES:
        raise QualityError(
            f"{eval_status!r} is not an EvalStatus",
            symbol=_BAD_READING,
            fix=f"use one of {', '.join(EVAL_STATUSES)}",
        )
    return CAL_STATUS_BY_EVAL.get(eval_status)
