"""Suite 7 of 12 -- `limits`: the ceilings refuse, on the right side of the boundary.

04-driver-system.md:2078: "every driver-enforced `[limits]` value refuses at the read boundary with
`take(N+1)`-then-check, and every host-enforced one refuses **before** `INVOKE`; a breach is
`RESOURCE_LIMIT{limit}` naming the knob". The defect: **a max-file-size set to `sys.maxsize`, with
the page check *after* the parse**.

## Two halves, and the second one is an assertion about ABSENCE

The row names two enforcers, and the interesting one is the boundary between them:

* **Host-enforced.** `max_input_bytes` is refused before `INVOKE` -- the unit never reaches the
  driver. So the driver-side assertion is an *inverted* one: hand the driver a unit larger than its
  own `max_input_bytes` and require that it does **not** raise `RESOURCE_LIMIT{max_input_bytes}`.
  Both the template driver and 04:2243's worked driver carry the comment in as many words: "NO
  max_input_bytes CHECK. The host refused the unit before INVOKE (DR20); a driver that re-checks a
  host-enforced ceiling is a second implementation of a safety limit." A second implementation is
  how two limits drift apart, and the drift is invisible until one of them is wrong.
* **Driver-enforced, through `ArtifactRef.of`.** `max_output_bytes` arrives per-invocation on
  `DriverIO` and is metered at one site. Lower it below what the driver will emit and
  `DriverError(TOO_LARGE, limit="max_output_bytes")` must come back -- *naming the knob*, which is
  the clause a suite can check and a reviewer cannot.

## P29, and the fixture 03-document-model.md promises this suite ships

03-document-model.md:2277-2278: "`page` is **never a batch index**. A driver that processed pages
40-59 as batch 2 writes 40-59, and the conformance kit's `limits` suite ships a fixture that would
pass under batch indexing and fails." The check here is the general form of that fixture: the set of
`page` indices a fragment emits must be the distinct values `0..page_count-1`. Under batch indexing
with batch size 4 a 12-page document emits `0,1,2,3` three times -- distinct count 4, page_count 12,
and duplicates where there should be none. Three separate symptoms, all from one comparison.

`page_kind = "stream"` is the degenerate case and is checked as itself: 03:2275 says a stream
document is "Always `page = 0`", so exactly one page row at index 0.

Specified in 04-driver-system.md section 8.2 row 7 and section 2.5; 03-document-model.md P25, P29.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import DriverHostError
from omniweave_core.limits import MAX_ENTRY_BYTES, MAX_ENTRY_COUNT
from omniweave_ports.types import DriverError, FailureClass, Port

from omniweave_conform.harness import run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.harness import ParseRun
    from omniweave_conform.subject import Subject

SUITE = "limits"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

_SHOWN = 6
"""How many page indices a failure message prints before eliding."""

_TINY_OUTPUT_BYTES = 8
"""A `max_output_bytes` no `owdoc-fragment/1` body can fit under: the `doc` record alone is longer.
Eight rather than zero, because zero is a value a driver might special-case as 'unset' and the
assertion must be about crossing a real ceiling."""


def run(subject: Subject) -> SuiteResult:
    """The `limits` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731

    checks = list(_declaration_assertions(subject))
    if subject.card.identity.port is not Port.PARSE:
        return SuiteResult.of(
            SUITE,
            checks,
            summary="declarations checked; no parse/1 harness for this Port yet",
            elapsed_ms=elapsed(),
        )
    if not subject.fixtures:
        checks.append(
            Assertion(
                "there is a fixture to push against the ceilings",
                ok=False,
                detail="--fixtures named no readable file; only the declarations were checked",
                locus="corpus",
            )
        )
        return SuiteResult.of(SUITE, checks, elapsed_ms=elapsed())
    try:
        driver = subject.instantiate()
    except (DriverHostError, DriverError, TypeError, ValueError) as exc:
        checks.append(
            Assertion("the driver constructs", ok=False, detail=str(exc), locus="construct")
        )
        return SuiteResult.of(SUITE, checks, elapsed_ms=elapsed())

    checks.extend(_output_ceiling_assertions(subject, driver))
    checks.extend(_input_ceiling_assertions(subject, driver))
    checks.extend(_page_index_assertions(subject, driver))
    limits = subject.card.limits
    summary = (
        f"max_input_bytes={limits.max_input_bytes} refused host-side before INVOKE; "
        f"max_parts={limits.max_parts} honoured; RESOURCE_LIMIT names the knob"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _declaration_assertions(subject: Subject) -> Iterator[Assertion]:
    """The declared ceilings are real numbers under the host's, not `sys.maxsize`.

    `load_card()` refuses a value ABOVE `HOST_MAX`, so the failure this catches is the other one in
    the row: a ceiling set so high it is not a ceiling. Reported as a ratio, because "8 MiB of a
    128 MiB host ceiling" and "128 MiB of 128 MiB" are both legal and only one of them is a limit.
    """
    limits = subject.card.limits
    for name, value, ceiling in (
        ("max_input_bytes", limits.max_input_bytes, MAX_ENTRY_BYTES),
        ("max_parts", limits.max_parts, MAX_ENTRY_COUNT),
    ):
        yield Assertion(
            f"[limits] {name} is at or under the host ceiling",
            ok=value <= ceiling,
            detail=f"{value} of the host's {ceiling}",
            locus=f"declared:{name}",
            expected=f"<= {ceiling}",
            actual=str(value),
        )
        yield Assertion(
            f"[limits] {name} is a limit rather than a formality",
            ok=value < ceiling,
            detail=(
                "a driver declaring exactly the host ceiling has declared no limit of its own; "
                "the host's is the one that will fire, and DR20 wanted the driver's judgement"
            ),
            locus=f"declared:{name}:meaning",
            expected=f"< {ceiling}",
            actual=str(value),
        )


def _output_ceiling_assertions(subject: Subject, driver: object) -> Iterator[Assertion]:
    """`max_output_bytes` crossed must raise `TOO_LARGE` naming the knob.

    Fixtures are tried **largest first, and a refusal is not an answer**. The largest fixture in a
    serious corpus is often an abuse case -- a zip bomb, a 400-deep XML document -- which the
    driver refuses before it produces a byte, and that refusal says nothing at all about whether
    the driver meters its output. An earlier draft took the largest fixture and reported the
    refusal as a failure, which failed `parse.office.anydoc` for having a `max_xml_depth` fixture
    in its corpus: a finding about this suite's fixture choice wearing a driver's name.

    So a `DriverError` that is not `TOO_LARGE` moves to the next fixture; only a fixture that got
    far enough to produce output can answer the question, and the suite says so when none did.
    """
    scratch = subject.scratch(SUITE)
    refused: list[str] = []
    for fixture in sorted(subject.fixtures, key=lambda f: f.byte_len, reverse=True):
        try:
            run_parse(driver, fixture, scratch / "ceiling", max_output_bytes=_TINY_OUTPUT_BYTES)
        except DriverError as exc:
            if exc.cls is not FailureClass.TOO_LARGE:
                refused.append(f"{fixture.name}:{exc.cls.value}")
                continue
            yield Assertion(
                "crossing max_output_bytes raises TOO_LARGE",
                ok=True,
                detail=f"raised {exc.cls.value}",
                fixture=fixture.name,
                locus="max_output_bytes",
                expected=FailureClass.TOO_LARGE.value,
                actual=exc.cls.value,
            )
            yield Assertion(
                "the breach names the knob",
                ok=exc.limit == "max_output_bytes",
                detail=(
                    "a RESOURCE_LIMIT that does not say which limit sends its reader to read the "
                    "code; naming the knob is what makes the refusal actionable"
                ),
                fixture=fixture.name,
                locus="max_output_bytes:limit",
                expected="max_output_bytes",
                actual=str(exc.limit),
            )
            return
        except Exception as exc:
            yield Assertion(
                "crossing max_output_bytes raises TOO_LARGE",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}"[:160],
                fixture=fixture.name,
                locus="max_output_bytes",
                expected="DriverError(too_large)",
                actual=type(exc).__name__,
            )
            return
        yield Assertion(
            "crossing max_output_bytes raises TOO_LARGE",
            ok=False,
            detail=(
                f"the driver produced a fragment under a {_TINY_OUTPUT_BYTES}-byte ceiling, so it "
                f"is not routing its output through ArtifactRef.of, the single metered site"
            ),
            fixture=fixture.name,
            locus="max_output_bytes",
            expected="DriverError(too_large)",
            actual="returned ok",
        )
        return
    yield Assertion(
        "a fixture exists that produces output, so the ceiling can be crossed",
        ok=False,
        detail=(
            "every fixture refused before producing a byte, so nothing exercised "
            f"ArtifactRef.of's meter: {', '.join(refused[:6])}"
        ),
        locus="max_output_bytes",
    )


def _input_ceiling_assertions(subject: Subject, driver: object) -> Iterator[Assertion]:
    """The INVERTED assertion: the driver must NOT re-check a host-enforced ceiling.

    Built by handing the driver a `UnitRef` whose `byte_len` is one byte over the card's
    `max_input_bytes` while the content is a real fixture. A driver that reads `unit.byte_len` and
    refuses has implemented the host's limit a second time; a driver that parses is doing what
    DR20 asks.
    """
    fixture = max(subject.fixtures, key=lambda f: f.byte_len)
    scratch = subject.scratch(SUITE)
    over = subject.card.limits.max_input_bytes + 1
    try:
        run_parse(driver, fixture, scratch / "oversized", declared_byte_len=over)
    except DriverError as exc:
        yield Assertion(
            "the driver does not re-check the host-enforced max_input_bytes",
            ok=exc.limit != "max_input_bytes",
            detail=(
                f"raised {exc.cls.value} limit={exc.limit!r}. A driver that re-checks a "
                f"host-enforced ceiling is a second implementation of a safety limit (DR20)"
            ),
            fixture=fixture.name,
            locus="max_input_bytes",
            expected="no max_input_bytes refusal from the driver",
            actual=f"{exc.cls.value}{{{exc.limit}}}",
        )
        return
    except Exception as exc:
        # NOT swallowed. An earlier draft caught this, discarded it and fell through to the
        # `ok=True` below -- so a driver that blew up on an oversized `byte_len` read as one that
        # does not check it, which is the opposite of the truth. A refusal is a refusal whatever
        # type it wears; what distinguishes a re-check from an unrelated failure is whether the
        # knob is named, and that is what is tested.
        named = "max_input_bytes" in f"{exc}" or "max_input_bytes" in repr(exc)
        yield Assertion(
            "the driver does not re-check the host-enforced max_input_bytes",
            ok=not named,
            detail=(
                f"raised {type(exc).__name__}: {exc}"[:160]
                + (
                    ". A driver that re-checks a host-enforced ceiling is a second "
                    "implementation of a safety limit (DR20)"
                    if named
                    else ". The knob is not named, so this is some other failure and "
                    "`contract` owns it"
                )
            ),
            fixture=fixture.name,
            locus="max_input_bytes",
            expected="no max_input_bytes refusal from the driver",
            actual=f"{type(exc).__name__} naming max_input_bytes" if named else "unrelated",
        )
        return
    yield Assertion(
        "the driver does not re-check the host-enforced max_input_bytes",
        ok=True,
        detail=(
            "DR20: the host refused the unit before INVOKE, so a conforming driver never "
            "sees an oversized one and has no reason to check"
        ),
        fixture=fixture.name,
        locus="max_input_bytes",
    )


def _page_index_assertions(subject: Subject, driver: object) -> Iterator[Assertion]:
    """P29: the page indices are the ORIGINAL ones, dense from 0, never a batch index."""
    scratch = subject.scratch(SUITE)
    for index, fixture in enumerate(subject.fixtures):
        try:
            result = run_parse(driver, fixture, scratch / f"pages{index}")
        except Exception as exc:
            # A refusal is `contract`'s finding; P29 is a claim about documents that DID parse.
            del exc
            continue
        yield from _page_assertions_for(result)


def _page_assertions_for(result: ParseRun) -> Iterator[Assertion]:
    pages = result.fragment.pages
    if not pages:
        return
    indices = [int(p.get("page", -1)) for p in pages]
    name = result.fixture.name
    duplicates = sorted({i for i in indices if indices.count(i) > 1})
    yield Assertion(
        "no page index is emitted twice",
        ok=not duplicates,
        detail=(
            f"repeated: {duplicates[:6]} -- under batch indexing a 12-page document emits "
            f"0,1,2,3 three times (03:2277)"
            if duplicates
            else f"{len(indices)} distinct page rows"
        ),
        fixture=name,
        locus="P29:distinct",
    )
    declared = int((result.fragment.doc or {}).get("page_count", len(indices)))
    yield Assertion(
        "the page indices are dense from 0 up to page_count",
        ok=sorted(indices) == list(range(declared)),
        detail="a batch index is dense from 0 too -- but only within its batch",
        fixture=name,
        locus="P29:dense",
        expected=f"0..{declared - 1}",
        actual=f"{sorted(indices)[:_SHOWN]}{'...' if len(indices) > _SHOWN else ''}",
    )
    streams = [p for p in pages if p.get("page_kind") == "stream"]
    if streams:
        yield Assertion(
            "a stream document has exactly one page row, at index 0",
            ok=len(pages) == 1 and indices == [0],
            detail="03:2275: 'there are no pages: HTML, markdown, code, plain text, email. "
            "Always page = 0'",
            fixture=name,
            locus="P29:stream",
            expected="[0]",
            actual=str(indices[:6]),
        )
