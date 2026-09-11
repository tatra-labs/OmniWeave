"""Suite 12 of 12 -- `quality`: the one that is not mandatory, and the shape of the number if it is.

13-quality.md:1740-1760 owns this suite. 04-driver-system.md:2083 gives it the only `mandatory = no`
cell in the table, and the reason is at 13:1747: "an accuracy number is expensive to produce, needs
a licensed corpus, and a driver that declines to produce one is honest rather than deficient."

**What is not optional is the shape of the number if it exists.** That sentence is 13:1749's and it
is the whole of this module. A card with no `[quality]` block is `unknown` and that is a complete,
correct answer; a card WITH one has made claims, and every one of them is checked here.

## The four keys an author may not write

13:1755-1760, and each row carries its own reason:

| key | why the author may not write it |
|---|---|
| `n` | 12 documents and 1,200 would be indistinguishable, and no Guard could fire |
| `ci95` | a point estimate with no interval cannot be compared to anything |
| `witness` | the author would write `ci` |
| `measured_on` | all ten fields, `corpus` / `corpus_digest` / `harness_version` included |

Enforcing "the author may not write it" is the publish gate's job and lives in
`omniweave_conform.publish` (04-driver-system.md:2682 names that file for DR13). This suite checks
the complementary thing: given that the block exists, is it *shaped* like a measurement.

## DR24, and the hole it closes

13:1770-1774: "A benchmark row whose `measured_on.corpus_digest` does not match a digest in the
omniweave release manifest is treated as `witness = "self"` **regardless of what it declares**".
That is the answer to "run the kit against a locally modified copy of `omniweave-golden 2026.09`
and get a perfectly valid attestation". This suite asserts the rule's *precondition*: a row
declaring `ci` or `third_party` must carry a corpus digest at all, because a row with an empty one
is a row DR24 downgrades and an author who does not know that is an author who believes they have a
ranked number.

There is **no row-level `corpus_digest`** (13:1762): the corpus identity lives inside `measured_on`,
exactly once, so DR24 has one field to read and cannot be pointed at two candidates. The assertion
reads that field and no other.

## `--bench` is not implemented here, and this says so rather than implying it

`ow conform --bench --corpus <name>` produces the block. It needs a registered corpus fetched by
`ow eval fetch`, which is 13 section 13.3's `ow eval` group and P10's. When the block is absent this
suite reports `unknown` with the command that would produce it -- which is what 04:2330's own
console line does: "quality       unknown (run `ow conform --bench` with a registered corpus)".

Specified in 13-quality.md section 12; 04-driver-system.md section 8.2 row 12.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import MEASURED_ON_FIELDS, MIN_SLICE_N, WITNESSES

from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "quality"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

KIT_WRITTEN_KEYS = ("n", "ci95", "witness", "measured_on")
"""13-quality.md:1755-1760's four. Read by `omniweave_conform.publish`, which is where the
"author values are rejected" half lives; named here because this is the suite the table is in."""

_RANKED_WITNESSES = ("ci", "third_party")


def run(subject: Subject) -> SuiteResult:
    """The `quality` suite. **Never mandatory** -- `MANDATORY` derives that by subtraction."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731
    quality = subject.card.quality

    if not quality.benchmarks:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=(
                "no [[quality.benchmark]] row. Run `ow conform --bench --corpus <name>` with a "
                "registered corpus; a driver that declines to produce a number is honest rather "
                "than deficient (13:1747)"
            ),
            elapsed_ms=elapsed(),
        )

    checks = list(_assertions(subject))
    rows = len(quality.benchmarks)
    witnesses = sorted({row.witness for row in quality.benchmarks})
    summary = f"{rows} benchmark rows, witness={'/'.join(witnesses)}, kit={quality.kit_version}"
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _assertions(subject: Subject) -> Iterator[Assertion]:
    quality = subject.card.quality
    yield Assertion(
        "[quality] names the kit version that wrote it",
        ok=bool(quality.kit_version.strip()),
        detail=(
            "the badge encodes kit_version (04:2115); a block with no kit version is a block "
            "no reader can date"
        ),
        locus="kit_version",
    )
    for index, row in enumerate(quality.benchmarks):
        where = f"benchmark[{index}] {row.metric}"
        yield Assertion(
            "n is at least the minimum slice",
            ok=row.n >= MIN_SLICE_N,
            detail="12 documents and 1,200 would otherwise be indistinguishable (13:1755)",
            locus=where,
            expected=f">= {MIN_SLICE_N}",
            actual=str(row.n),
        )
        low, high = row.ci95
        yield Assertion(
            "ci95 is an interval, and it is not a point",
            ok=low < high,
            detail="a point estimate with no interval cannot be compared to anything (13:1756)",
            locus=f"{where} ci95",
            expected="low < high",
            actual=f"[{low}, {high}]",
        )
        yield Assertion(
            "ci95 contains the value",
            ok=low <= row.value <= high,
            detail=f"{row.value} in [{low}, {high}]",
            locus=f"{where} ci95",
        )
        yield Assertion(
            "witness is one of the three",
            ok=row.witness in WITNESSES,
            detail="an unrecognised witness claim is exactly a self-report (04:2130)",
            locus=f"{where} witness",
            expected="/".join(WITNESSES),
            actual=row.witness,
        )
        yield from _measured_on_assertions(where, row)
        yield from _dr24_assertions(where, row)
        yield Assertion(
            "the row declares its method",
            ok=bool(row.method.strip()),
            detail="a number with no method is a number nobody can reproduce",
            locus=f"{where} method",
        )


def _measured_on_assertions(where: str, row: object) -> Iterator[Assertion]:
    """All ten fields populated. `MeasuredOn` is frozen with no defaults, so a card supplying
    seven raises `TypeError` at construction rather than writing a blank cell (13:1759) -- which
    means this assertion catches the case that construction cannot: a field present and EMPTY.
    """
    measured_on = row.measured_on  # type: ignore[attr-defined]
    blank = [name for name in MEASURED_ON_FIELDS if not str(getattr(measured_on, name, "")).strip()]
    yield Assertion(
        "every one of the ten measured_on fields carries a value",
        ok=not blank,
        detail=(
            f"blank: {', '.join(blank)} -- the defect 04:2070 names is 'a card with seven "
            f"MeasuredOn fields and a blank cell', and a blank cell is what this catches"
            if blank
            else f"all {len(MEASURED_ON_FIELDS)} populated"
        ),
        locus=f"{where} measured_on",
        expected=f"{len(MEASURED_ON_FIELDS)} populated",
        actual=f"{len(MEASURED_ON_FIELDS) - len(blank)} populated",
    )


def _dr24_assertions(where: str, row: object) -> Iterator[Assertion]:
    """A row claiming a ranked witness must at least carry the digest DR24 reads."""
    witness = row.witness  # type: ignore[attr-defined]
    digest = str(getattr(row.measured_on, "corpus_digest", "")).strip()  # type: ignore[attr-defined]
    if witness not in _RANKED_WITNESSES:
        yield Assertion(
            "witness = self is displayed and never ranked, which is the honest default",
            ok=True,
            detail="13:1768 -- there is no flag that sets ci; only omniweave's own workflow does",
            locus=f"{where} DR24",
        )
        return
    yield Assertion(
        f"a witness = {witness} row carries the corpus digest DR24 reads",
        ok=bool(digest),
        detail=(
            "DR24 rewrites the witness at card load for a digest outside the release manifest, "
            "and an EMPTY digest is outside it. A row that believes it is ranked and is not is "
            "worse than a row that says self"
        ),
        locus=f"{where} DR24",
        expected="measured_on.corpus_digest is set",
        actual=digest or "<empty>",
    )
