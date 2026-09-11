"""What a suite returns, what a run returns, and the two strings a finished run may emit.

04-driver-system.md:2068 gives twelve suites and one verdict column; :2332 prints what a finished
run says on stdout; :2395 prints the badge. This module is those shapes and nothing else. It runs
no suite, loads no card and touches no disk, so every suite module can import it without importing
the runner, and the runner can format a report it did not produce.

## The verdict vocabulary is the card's, not ours

`Verdict`'s three members are `omniweave_core.drivers.card.QUALITY_VERDICTS` -- the closed domain
of `[quality.suites]`, which is the table `ow conform` writes its own results into
(04-driver-system.md:2095-2097). A kit that invented a fourth state would be inventing a value it
could not then write onto the card it exists to fill in.

**There is no `skip`.** card.py:323-325 records the terminology lock striking the skip vocabulary
outright: "`unknown` is a VALUE, not a skipped state". A suite that cannot run on this machine is
therefore `unknown`, and because a passing run needs every mandatory suite at `pass`, a machine
that cannot run one does not get a pass out of the deal. That is the intended asymmetry --
04:2085's "a skipped gate is not a gate" -- and it is why `ConformReport.passed` tests for `PASS`
rather than for "not FAIL".

The enum is declared here and `test_conform_result.py` pins it against `QUALITY_VERDICTS`. Both
sides are transcriptions of the same plan sentence, so that test catches drift between two
transcriptions and proves nothing about the plan; it is worth having for the first reason and is
not evidence for the second.

## An assertion names its locus, because the suite's job is to be actionable

04-driver-system.md:2334: if `capability` fails on `origin_span`, "the message names the fixture,
the block and the two strings that differed -- because the point of a capability suite is to be
*actionable*, not to be a verdict." `Assertion` carries `fixture`, `locus`, `expected` and
`actual` for exactly that sentence, and `Assertion.line()` is the one formatter that uses them.

Specified in 04-driver-system.md section 8 and 13-quality.md section 12.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import QUALITY_SUITES

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

__all__ = [
    "MANDATORY",
    "SUITES",
    "Assertion",
    "ConformReport",
    "SuiteResult",
    "Verdict",
]


SUITES: Final[tuple[str, ...]] = QUALITY_SUITES
"""The twelve, in the order a run reports them.

**Imported, never re-listed** (INV-21). `omniweave_core.drivers.card` already owns this tuple
because `[quality.suites]` is a closed table and the card loader refuses an unknown key in it; a
second list here would be a second grammar, and the failure mode is a kit that runs a suite the
card cannot record. The order is 04-driver-system.md:2070-2083's table order, which is also the
order :2313-2331's console output prints."""

MANDATORY: Final[frozenset[str]] = frozenset(SUITES) - {"quality"}
"""The eleven. **Derived by subtraction, so a thirteenth suite is mandatory by default.**

04-driver-system.md:2083 is the only `mandatory = no` row in the table, and 13-quality.md:1747
gives the reason: "an accuracy number is expensive to produce, needs a licensed corpus, and a
driver that declines to produce one is honest rather than deficient". Writing the eleven out would
make the next suite's mandatoriness an editorial act performed in two files; subtracting makes the
default the safe direction, which is the direction a conformance kit should fail in."""


class Verdict(StrEnum):
    """A suite's three states, and `QUALITY_VERDICTS`' three members."""

    PASS = "pass"  # noqa: S105 -- a verdict, and the card grammar fixes the spelling.
    FAIL = "fail"
    UNKNOWN = "unknown"

    @staticmethod
    def worst(verdicts: Iterable[Verdict]) -> Verdict:
        """`FAIL` if any failed, else `UNKNOWN` if any is unknown, else `PASS`.

        An empty iterable is `UNKNOWN` rather than `PASS`: nothing was checked, and a kit that
        reports a pass for a run that asserted nothing is the same shape of defect as docling's
        load-then-gate order, one level up.
        """
        seen = frozenset(verdicts)
        if Verdict.FAIL in seen:
            return Verdict.FAIL
        if Verdict.UNKNOWN in seen or not seen:
            return Verdict.UNKNOWN
        return Verdict.PASS


@dataclass(frozen=True, slots=True)
class Assertion:
    """One checked claim, and everything a reader needs to act on it without re-running.

    `name` is the claim in the imperative present ("origin_span=exact re-reads the retained
    part"), never a restatement of the verdict. `detail` is what was observed; `expected` and
    `actual` are populated only when the two are comparable strings, because a diff of two things
    that are not both strings is a worse message than a sentence.
    """

    name: str
    ok: bool
    detail: str = ""
    fixture: str = ""
    locus: str = ""
    expected: str = ""
    actual: str = ""

    def line(self) -> str:
        """The one-line form, with the fixture and the locus in front of the difference.

        04-driver-system.md:2334's sentence, mechanised: fixture, block, and the two strings.
        """
        head = "ok  " if self.ok else "FAIL"
        where = " ".join(part for part in (self.fixture, self.locus) if part)
        parts = [f"{head} {self.name}"]
        if where:
            parts.append(f"at {where}")
        if self.expected or self.actual:
            parts.append(f"expected {self.expected!r}, got {self.actual!r}")
        elif self.detail:
            parts.append(self.detail)
        return "  ".join(parts)


@dataclass(frozen=True, slots=True)
class SuiteResult:
    """One suite's verdict, its assertions and the parenthetical the console prints after it.

    `summary` is the text inside the brackets of 04-driver-system.md:2313-2331 -- "15 declared, 15
    asserted present-or-absent; origin_span=exact re-verified on 214 blocks" -- and it is written
    by the suite rather than derived here, because only the suite knows which of its counts a
    reader cares about.

    `elapsed_ms` exists for one assertion and not for a report column: 04:2085 makes the mandatory
    tier's five minutes "a CI timing assertion", and an assertion needs a number.
    """

    suite: str
    verdict: Verdict
    assertions: tuple[Assertion, ...] = ()
    summary: str = ""
    elapsed_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.suite not in SUITES:
            msg = f"{self.suite!r} is not one of the twelve: {', '.join(SUITES)}"
            raise ValueError(msg)

    @property
    def mandatory(self) -> bool:
        return self.suite in MANDATORY

    def failures(self) -> tuple[Assertion, ...]:
        return tuple(a for a in self.assertions if not a.ok)

    @classmethod
    def of(
        cls,
        suite: str,
        assertions: Sequence[Assertion],
        *,
        summary: str = "",
        elapsed_ms: float = 0.0,
        unknown: str = "",
    ) -> SuiteResult:
        """Build a result whose verdict is *derived from the assertions*, never passed in.

        `unknown` is the one override and it is a REASON rather than a flag: a suite that could
        not run says why in the same breath, and an empty reason cannot produce an `unknown`. That
        keeps 04:2085's "a skipped gate is not a gate" mechanical -- there is no argument a caller
        can pass that turns an unchecked suite into a quiet pass.
        """
        if unknown:
            return cls(suite, Verdict.UNKNOWN, tuple(assertions), unknown, elapsed_ms)
        failed = any(not a.ok for a in assertions)
        verdict = Verdict.FAIL if failed else Verdict.PASS if assertions else Verdict.UNKNOWN
        text = summary or (f"{len(assertions)} assertions" if assertions else "nothing asserted")
        return cls(suite, verdict, tuple(assertions), text, elapsed_ms)


@dataclass(frozen=True, slots=True)
class ConformReport:
    """One `ow conform` run: twelve results, the card they ran against, and the two digests.

    `card_sha256` is `card_sha256()`'s -- over the RAW BYTES, so a comment-only edit moves it
    (card.py:1282-1290). The badge carries it, which is what makes a badge specific to the file an
    author published rather than to its meaning; `attestation` is the other digest and moves only
    on a change of meaning. Both are on the report because 04:2115 puts one on the badge and :2331
    prints the other.
    """

    results: tuple[SuiteResult, ...]
    card_sha256: str
    kit_version: str
    driver_id: str = ""
    attestation: str | None = None
    elapsed_ms: float = 0.0
    fixtures: int = 0

    def __post_init__(self) -> None:
        seen = [r.suite for r in self.results]
        if len(set(seen)) != len(seen):
            msg = f"a suite reported twice: {seen}"
            raise ValueError(msg)

    def __iter__(self) -> Iterator[SuiteResult]:
        return iter(self.results)

    def by_suite(self) -> Mapping[str, SuiteResult]:
        return {r.suite: r for r in self.results}

    def verdict_of(self, suite: str) -> Verdict:
        """`UNKNOWN` for a suite that did not report, which is what a missing suite means."""
        found = self.by_suite().get(suite)
        return found.verdict if found else Verdict.UNKNOWN

    @property
    def mandatory_results(self) -> tuple[SuiteResult, ...]:
        return tuple(r for r in self.results if r.mandatory)

    @property
    def mandatory_passed(self) -> int:
        return sum(1 for r in self.mandatory_results if r.verdict is Verdict.PASS)

    @property
    def mandatory_total(self) -> int:
        """`len(MANDATORY)`, NOT the number that reported.

        11/11 has to mean eleven of the eleven that exist. A run that lost a suite to an exception
        and printed 10/10 would read as a pass, which is the one arithmetic a badge may not be
        capable of.
        """
        return len(MANDATORY)

    @property
    def passed(self) -> bool:
        """The mandatory tier, and only it: `quality` never gates a run (13-quality.md:1740)."""
        return self.mandatory_passed == self.mandatory_total

    def counts(self) -> Mapping[Verdict, int]:
        tally = dict.fromkeys(Verdict, 0)
        for result in self.results:
            tally[result.verdict] += 1
        return tally

    def failures(self) -> tuple[tuple[str, Assertion], ...]:
        rows: list[tuple[str, Assertion]] = []
        for result in self.results:
            rows.extend((result.suite, a) for a in result.failures())
        return tuple(rows)
