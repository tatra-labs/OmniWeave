"""`TruthKind` -- what a metric's reference IS, and the two values that may never be accuracy.

13:1451 prints the six values and *"the exact admissibility rule for each"*; 13:1228
makes the rule a gate rather than a caveat -- *"`TruthKind` forbids self-anchoring at the column
level"* -- and 16-roadmap.md:609 schedules the plumbing of one of them with W5.7.

## Why this type is in core, when the document that defines it asks core for one thing

13:1973 is explicit about its own ask: `normalize_eval()` *"is a new function in
`omniweave_conform.normalize` and a new obligation on `omniweave_core.ident`: the shared fold table
becomes a named `fold_common` so the evaluator can compose it rather than copy it. That is the only
change this document asks of core."* So the plan does not put `TruthKind` here, and it does not put
it anywhere else either -- the enum is printed in a quality code block and given no module.

The home falls out of `tools/layers.toml`, which is derived and not chosen. `TruthKind` has exactly
two consumers and they are in two distributions: the `agree` writer is `omniweave.route.agree`, and
the harness that refuses an inadmissible column is `omniweave_conform`'s (13:1993 puts `Q-G9` at
class `G`). `omniweave_conform = ["omniweave_core", "omniweave_ports"]` and
`omniweave = ["omniweave_core", "omniweave_ports", "omniweave_office"]`, so **neither can import the
other** and their only common ancestor is this distribution. The alternative is the vocabulary
written twice, which is the failure 13:1072 already names for the fold table: *"A dash added to one
is added to both -- which is the failure the collection actually exhibits, where two normalisers
drift and a comparison starts depending on which one ran."* One list, one home; 02:229 states that
reason for `fold_common` in the same words, and this module is `fold_common`'s shape rather than a
new idea. D231 records that the plan names no home, because a derived answer is still a gap.

## Two vocabularies, and the plan joins exactly two of their members

`route_quality.source` has four members (05:2860) and `TruthKind` has six, and the only pairs the
plan states are `agree -> agreement` (05:2251, 12:1101, 03:1771, 13:1459 and 02:569, five sites) and
`self -> self` (13:1459's last row, *"a driver's self-report"*). `TRUTH_KIND_BY_SOURCE` holds those
two and `truth_kind_of()` returns `None` for the others -- 05:2122's discipline, *"Uncomputable is
None; NEVER a default value"*, applied to a question the plan does not answer rather than to a
signal a provider could not compute.

The gap is not cosmetic and D232 is the entry. 05:2852 makes an `audit` verdict a comparison
against *"a second, more expensive reading of a sampled part"* -- another driver, on the same
bytes -- which is the argument 05:2251 gives for why `agreement` may never be accuracy: *"two
readings agreeing is not evidence that either is right"*. Yet `audit` is the source whose divergence
drives `route_scoreboard.state`, and 12:1103 says *"until F23 reports, **only `audit` verdicts may
trigger a demotion**"*. Both may be right -- a reference driver chosen for capability is better
evidence than a free cross-rung diff -- but the difference is a judgement the six values do not
carry, so this module records the two pairs the plan states and refuses to invent the others.

## The rule is a predicate here and a gate elsewhere

Nothing in this file can stop a column being populated; `eval_metric` is the `.oweval` store's and
`Q-G9` is the harness's (13:1993). What lives here is the question in one form, so that when the
harness arrives it asks rather than restates. `why_not_accuracy()` returns the reason and not a
bool, because the caller prints it: 13:37 names the failure mode this prevents in the voice of the
thing that went wrong -- *"`native_run` or `agreement` populates an accuracy column and the number
measures self-consistency"* -- and a `False` does not say that.

Stdlib only, eager, exporting nothing into `omniweave_core/__init__.py`'s nine lazy names: a tuple
of six strings and four predicates cost nothing to import and belong to no subpackage.

Specified in 13-quality.md sections 8.3 and 13.6; scheduled by 16-roadmap.md:609.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_core.errors import QualityError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AGREEMENT",
    "FIDELITY_ONLY",
    "NEVER_ACCURACY",
    "NEVER_SCORED",
    "QUALITY_SOURCES",
    "SELF",
    "TRUTH_KINDS",
    "TRUTH_KIND_BY_SOURCE",
    "check_accuracy_column",
    "may_demote",
    "truth_kind_of",
    "why_not_accuracy",
]

TRUTH_KINDS: Final[tuple[str, ...]] = (
    "human",
    "rendered",
    "native_run",
    "synth_ocr",
    "agreement",
    "self",
)
"""The six, in the order 13:1453's table lists them -- which is also weakest-claim-last.

`human` is *"**The anchor.**"* and is admissible for anything; `rendered` for structure, order and
coverage; `native_run` for fidelity only; `synth_ocr` for anything *"reported per degradation level
L0-L4 and never pooled"*; `agreement` for its own column; `self` for nothing. The glossary states
the same list as a single sentence (glossary.md:1094)."""

AGREEMENT: Final[str] = TRUTH_KINDS[4]
"""`agree.decode_vs_page`'s, and the reason this module exists in W5.7 rather than in P6."""

SELF: Final[str] = TRUTH_KINDS[5]
"""A driver's self-report. *"Stored, never scored, never ranked"* (13:1459)."""

NEVER_ACCURACY: Final[frozenset[str]] = frozenset({AGREEMENT, SELF})
"""The two 13:1230 names together: *"`agreement` and `self` may **never** populate an accuracy
column"*. A frozenset and not a tuple because membership is the only question asked of it."""

FIDELITY_ONLY: Final[frozenset[str]] = frozenset({"native_run"})
"""13:1230's other half, and 13:1232 argues it is *"derived, not conservative"*.

The source XML run text answers *"do the extracted characters equal the source run's characters"*
and nothing else, because *"any independent `w:t` walk either re-implements or contradicts the same
branch selection the subject driver makes"* -- `mc:AlternateContent`, `w:sdt`, `w:instrText`,
`w:txbxContent` and the footnote parts. A recall number against a naive walk *"measures which
branches you both chose"*."""

NEVER_SCORED: Final[frozenset[str]] = frozenset({SELF})
"""Narrower than `NEVER_ACCURACY` and separately stated, because the store already implements it:
05:2870 says `source = 'self'` rows are *"written and never scored"* and the `route_scoreboard`
view's own `WHERE source IN ('agree','audit','feedback')` is where that happens (RT12). The rows are
written anyway: 05:2843 keeps them because *"the gap between `self` and `audit` is itself
a diagnostic"*."""

QUALITY_SOURCES: Final[tuple[str, ...]] = ("self", "agree", "audit", "feedback")
"""`route_quality.source`'s CHECK, in the DDL's own order (05:2860).

A second vocabulary, not a spelling of the first: a source says who produced a verdict and a
`TruthKind` says what its reference was, and 05:2837-2840's table gives the four sources three
different answers about the scoreboard (`self` never, `agree` as `escalation_divergence`, `audit` as
`divergence`, `feedback` as `complaints`)."""

TRUTH_KIND_BY_SOURCE: Final[Mapping[str, str]] = {"agree": AGREEMENT, "self": SELF}
"""The two pairs the plan states. `audit` and `feedback` are absent and D232 is why."""

_ACCURACY_FIX = "uv run ow eval run --suite parse"


def truth_kind_of(source: str) -> str | None:
    """The `TruthKind` of a `route_quality.source`, or `None` where the plan states none.

    `None` is the honest answer for `audit` and `feedback` and is not a placeholder for one: an
    audit's reference is another driver and a feedback's is a human who did not label anything,
    and guessing either would put a value in the column whose whole job is to say where a number
    came from. An unknown source is a `KeyError`-shaped question rather than a `None`, so it
    raises -- `QUALITY_SOURCES` is a closed CHECK and a value outside it never reached the store.
    """
    if source not in QUALITY_SOURCES:
        raise QualityError(
            f"{source!r} is not a route_quality.source; the CHECK admits {QUALITY_SOURCES}",
            fix="uv run ow store verify",
        )
    return TRUTH_KIND_BY_SOURCE.get(source)


def why_not_accuracy(truth_kind: str) -> str:
    """Empty when this `TruthKind` may anchor an accuracy metric; the reason when it may not.

    A string and not a bool for the reason 13:37 gives: the failure mode is *"`native_run` or
    `agreement` populates an accuracy column and the number measures self-consistency"*, and what
    a reader needs at that moment is which of the three ways it went wrong.
    """
    if truth_kind not in TRUTH_KINDS:
        return f"{truth_kind!r} is not a TruthKind; the six are {', '.join(TRUTH_KINDS)}"
    if truth_kind == AGREEMENT:
        return (
            "agreement may never populate an accuracy column: two readings agreeing is not "
            "evidence that either is right, and 12:1102 gives it its own column headed "
            '"Agreement (not accuracy)"'
        )
    if truth_kind == SELF:
        return "self is stored, never scored and never ranked -- a driver grading its own work"
    if truth_kind in FIDELITY_ONLY:
        return (
            "native_run anchors a FIDELITY metric only: an independent run walk re-implements or "
            "contradicts the same branch selection the subject driver makes, so a recall number "
            "against it measures which branches you both chose"
        )
    return ""


def check_accuracy_column(metric: str, truth_kind: str) -> None:
    """Raise when `metric` is an accuracy column and `truth_kind` may not anchor one.

    The raising half of `why_not_accuracy()`, for the writer that has already decided the column
    is an accuracy column. It does not decide that itself: which of 13:1090's eleven metrics are
    accuracy is the harness's table, and a second copy of it here would be a second answer.
    """
    why = why_not_accuracy(truth_kind)
    if why:
        raise QualityError(
            f"{metric} may not be anchored by {truth_kind}: {why}", fix=_ACCURACY_FIX
        )


def may_demote(source: str) -> bool:
    """Only an `audit` verdict may move a slice to a more expensive driver. F23, and it is open.

    12:1103: *"Two drivers sharing a base model family can be wrong identically, which is F23 --
    and until F23 reports, **only `audit` verdicts may trigger a demotion**."* 17:518 carries the
    open question with its own pre-committed fallback, so this predicate is the fallback in force
    and not a permanent rule -- the day `ow eval correlate` reports, the set widens by one.

    Stated over a source rather than over a `TruthKind` on purpose: the demotion writer holds a
    `route_quality` row, and `truth_kind_of('audit')` is `None` (D232) -- so a rule phrased over
    the reference vocabulary would be unanswerable for exactly the one source it must admit.
    """
    return source == "audit"
