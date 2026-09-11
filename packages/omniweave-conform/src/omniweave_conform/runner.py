"""Run the twelve, in order, and render what they said.

04-driver-system.md:2313-2332 prints exactly what a finished run looks like, down to the
parenthetical after each suite name and the final line's arithmetic. This module produces that.

## Three rules the loop follows, and each one is a failure mode it refuses

1. **A suite that raises is the KIT's bug, and is attributed as one.** `_guarded()` catches
   everything and turns it into a `fail` whose detail names the exception and the suite. It does
   not let the exception out, because one broken suite must not cost the other eleven their run --
   and it does not report `unknown`, because "the kit crashed" is not "we could not look".
2. **The order is `SUITES`' and the loop does not reorder it.** `card` and `purity` must run before
   anything imports the driver; `contract` must run before anything constructs it. See
   `suites/__init__.py` for why each of those is load-bearing.
3. **The five-minute assertion is made, not assumed.** 04:2085: the mandatory tier "runs in under
   five minutes on a laptop, enforced as a CI timing assertion, because a skipped gate is not a
   gate." `ConformReport.elapsed_ms` carries the measurement and `mandatory_budget_exceeded()` is
   the predicate; the CI job asserts on it, and `tools/ow_conform.py` prints it.

## The verdict line's arithmetic

`12 suites, 11 pass, 1 unknown, 0 fail, 4m12s  -> PASS (mandatory tier)` is :2332. Note what
"PASS" is computed from: the eleven MANDATORY suites, all at `pass`. The `1 unknown` in that line
is `quality`, and it does not participate. `ConformReport.passed` is that predicate and
`mandatory_total` is `len(MANDATORY)` rather than "the number that reported", so a run that lost a
suite cannot print 10/10 and read as a pass.

Specified in 04-driver-system.md section 8 and section 9 step 4.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import card_sha256

from omniweave_conform.badge import kit_version
from omniweave_conform.result import (
    MANDATORY,
    SUITES,
    Assertion,
    ConformReport,
    SuiteResult,
    Verdict,
)
from omniweave_conform.suites import run_suite

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_conform.subject import Subject

__all__ = ["MANDATORY_BUDGET_S", "report_lines", "run", "verdict_line"]

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

MANDATORY_BUDGET_S: Final = 300.0
"""Five minutes, on a laptop, for the eleven mandatory suites (04-driver-system.md:2085).

A budget rather than a timeout: nothing here stops a run that exceeds it. Stopping a suite
mid-flight would produce a report whose verdicts describe a partial run, and a partial run that
says `pass` is worse than a slow one that says `pass` late. The CI timing assertion the plan asks
for reads `mandatory_budget_exceeded()`."""


def run(subject: Subject, *, only: Sequence[str] = ()) -> ConformReport:
    """Run the twelve (or the named subset) and return the report.

    Args:
        subject: the card, the fixtures and the workdir. Built once and shared, because the twelve
            are meant to see the same subject -- a suite that rebuilt it could be looking at a
            card another suite's `--bench` write had already changed.
        only: suite names to run, in `SUITES` order regardless of the order given. Empty means all
            twelve. A name outside the twelve raises `KeyError` rather than being ignored.

    The report's `attestation` is the card's *declared* one, carried through unchanged. Writing a
    new one is `publish.write_results()`, and it happens after a run rather than during it: a run
    that attested itself while its own suites were still failing would be attesting a card it had
    not finished checking.
    """
    wanted = _selection(only)
    started = time.monotonic_ns()
    results = [_guarded(name, subject) for name in wanted]
    elapsed_ms = (time.monotonic_ns() - started) / _NS_PER_MS
    return ConformReport(
        results=tuple(results),
        card_sha256=card_sha256(subject.raw),
        kit_version=kit_version(),
        driver_id=subject.driver_id,
        attestation=subject.card.attestation,
        elapsed_ms=elapsed_ms,
        fixtures=len(subject.fixtures),
    )


def _selection(only: Sequence[str]) -> tuple[str, ...]:
    if not only:
        return SUITES
    unknown = sorted(set(only) - set(SUITES))
    if unknown:
        msg = f"{unknown} are not among the twelve: {', '.join(SUITES)}"
        raise KeyError(msg)
    return tuple(name for name in SUITES if name in set(only))


def _guarded(name: str, subject: Subject) -> SuiteResult:
    """Run one suite. An escaping exception becomes a `fail` naming the kit, not the driver."""
    started = time.monotonic_ns()
    try:
        return run_suite(name, subject)
    except Exception as exc:  # a suite that raises is OUR bug, and it is attributed as one.
        return SuiteResult(
            suite=name,
            verdict=Verdict.FAIL,
            assertions=(
                Assertion(
                    f"the {name} suite ran to completion",
                    ok=False,
                    detail=(
                        f"the suite itself raised {type(exc).__name__}: {exc}. This is a defect "
                        f"in omniweave-conform, not a finding about the driver"
                    ),
                    locus="kit",
                ),
            ),
            summary=f"the suite raised {type(exc).__name__}",
            elapsed_ms=(time.monotonic_ns() - started) / _NS_PER_MS,
        )


def mandatory_budget_exceeded(report: ConformReport) -> bool:
    """Did the mandatory tier take longer than five minutes? The CI timing assertion's predicate."""
    mandatory_ms = sum(r.elapsed_ms for r in report.results if r.suite in MANDATORY)
    return mandatory_ms > MANDATORY_BUDGET_S * 1000


def verdict_line(report: ConformReport) -> str:
    """04-driver-system.md:2332's last line, rebuilt from the report.

    `12 suites, 11 pass, 1 unknown, 0 fail, 4m12s  -> PASS (mandatory tier)`
    """
    counts = report.counts()
    outcome = "PASS" if report.passed else "FAIL"
    tally = (
        f"{counts[Verdict.PASS]} pass, {counts[Verdict.UNKNOWN]} unknown, "
        f"{counts[Verdict.FAIL]} fail"
    )
    return (
        f"{len(report.results)} suites, {tally}, {_duration(report.elapsed_ms)}"
        f"  -> {outcome} (mandatory tier)"
    )


def _duration(ms: float) -> str:
    seconds = ms / 1000
    minutes = int(seconds // 60)
    return f"{minutes}m{seconds - minutes * 60:04.1f}s" if minutes else f"{seconds:.2f}s"


def report_lines(report: ConformReport, *, failures: bool = True) -> Iterator[str]:
    """The console form of 04-driver-system.md:2313-2332, one line per suite then the verdict.

    `failures=True` adds one line per failing assertion under its suite, which is what makes a
    failing run actionable: :2334 wants the fixture, the block and the two strings, and
    `Assertion.line()` is where those are formatted.
    """
    width = max((len(r.suite) for r in report.results), default=8)
    for result in report.results:
        yield f"{result.suite:<{width}}  {result.verdict.value:<8}({result.summary})"
        if failures:
            for assertion in result.failures():
                yield f"{'':<{width}}    {assertion.line()}"
    if report.attestation:
        yield f"{'attestation':<{width}}  {report.attestation}"
    yield verdict_line(report)
    if mandatory_budget_exceeded(report):
        mandatory_ms = sum(r.elapsed_ms for r in report.results if r.suite in MANDATORY)
        yield (
            f"the mandatory tier took {_duration(mandatory_ms)}, over the "
            f"{MANDATORY_BUDGET_S:.0f}s laptop budget of 04-driver-system.md:2085"
        )
