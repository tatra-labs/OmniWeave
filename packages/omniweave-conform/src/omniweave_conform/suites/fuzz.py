"""Suite 11 of 12 -- `fuzz`: a crash is allowed, a hang is not.

04-driver-system.md:2082: "a corpus of malformed inputs: **a crash is allowed, a hang is not**;
ships a deliberate segfault fixture and asserts the run completes". The defect: **in-process death
taking the run with it**.

## The asymmetry is the whole argument for `subproc` being affordable

04-driver-system.md:2089-2091 states it: the asymmetry "is deliberate and is the whole reason
`subproc` is affordable: the host already handles a crash as one row and it cannot handle a hang
without a deadline." A crash costs one unit and a retry at `batch = 1`; a hang costs the run's
wall clock and every unit behind it. So this suite is permissive about the first and absolute about
the second, and a driver that turns a malformed input into a clean typed refusal is better than
either but is not *required* to be.

03-document-model.md's P28 gives the same rule at the row grain: "a corrupt fixture yields
`status='partial'` with `Diag` rows, or a typed `DriverError` from the closed `FailureClass`; a
crash is allowed (one unit), a hang is not."

## The corpus: generated from the fixtures, not shipped as a second corpus

Every mutation is derived from the author's own fixtures -- truncated, bit-flipped, header-swapped,
run-length-exploded, nul-injected, deeply nested. That is deliberate and it is not laziness: a
shipped corpus of malformed PDFs says nothing to a driver that parses notebooks, and a kit that
shipped one corpus per format would be shipping the format knowledge the drivers exist to hold.
A mutation of the author's own fixture is malformed in the author's own format by construction.

`fuzz/seeds/` is read when it exists. 04-driver-system.md:2092-2094 mirrors anydoc's twelve
cargo-fuzz targets' seeds into it, and a driver whose format overlaps those seeds gets them for
free.

## What "a hang is not allowed" means in a library that cannot spawn

A real hang detector needs a deadline enforced from outside the hung thing, which needs a process,
which this file may not create. What IS enforceable here is a wall-clock budget per input measured
around the call: a driver that exceeds it has not been *stopped*, but it has been *caught*, and the
assertion says which. The stopping half is `tools/ow_conform.py`'s, where a child process and
`host/subproc.py`'s deadline ladder are both available. The deliberate segfault fixture is the
same: a segfault must be survived by a host, and a host is a process.

Specified in 04-driver-system.md section 8.2 row 11; 03-document-model.md P28.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import DriverHostError, OwError
from omniweave_ports.types import DriverError, Port

from omniweave_conform.harness import Fixture, MemoryBlobStore, run_parse
from omniweave_conform.mutate import count, mutations
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "fuzz"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

HANG_BUDGET_S: Final = 5.0
"""Per-input wall clock beyond which an input is reported as a hang, in seconds.

Five seconds against a mandatory tier that must finish in five minutes across twelve suites
(04:2085). A driver taking five seconds on a mutation of a fixture it parses in milliseconds is
not slow; it is stuck, and the usual cause is a length field read from the input and trusted."""

SEGFAULT_KEY = "segfault_survived"
"""The key `tools/ow_conform.py` puts its segfault-containment result under in
`Subject.measurements`. `True` means a child was made to dereference address 1 and this process was
still here afterwards to say so."""

HANG_BUDGET_NS: Final = int(HANG_BUDGET_S * 1_000_000_000)
"""The same budget in the unit the clock reports. Derived, so the two cannot disagree."""


def _mutations(fixture: Fixture) -> Iterator[tuple[str, bytes]]:
    """The mutation set, from the one module that defines it.

    It moved to `omniweave_conform.mutate` when `fuzz/targets/` needed the same set: this suite
    runs it over an author's fixtures on the author's machine, and the atheris targets run it
    over `fuzz/seeds/` in the nightly job 14-security.md:477 specifies. Two mechanisms, one
    definition of "malformed", because a driver green under one and red under the other has been
    told two different things by one framework (INV-21).

    The extraction found a defect and it is worth naming. This docstring used to accuse seven
    things -- including `empty`, "the degenerate case every parser forgets" -- over a generator
    that yielded six, and `empty` was the one it never produced. The generator was the half that
    was wrong, and the whole argument for naming a mutation after the bug it hunts is that the
    gap between the two is readable.
    """
    return mutations(fixture.data)


def run(subject: Subject) -> SuiteResult:
    """The `fuzz` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731

    if subject.card.identity.port is not Port.PARSE:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=f"no {subject.card.identity.port.value}/1 harness in this kit yet",
            elapsed_ms=elapsed(),
        )
    if not subject.fixtures:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=(
                "--fixtures named no readable file; the corpus is generated FROM the author's "
                "fixtures, so there is nothing to malform"
            ),
            elapsed_ms=elapsed(),
        )
    try:
        driver = subject.instantiate()
    except (DriverHostError, DriverError, TypeError, ValueError) as exc:
        return SuiteResult.of(
            SUITE,
            [Assertion("the driver constructs", ok=False, detail=str(exc), locus="construct")],
            elapsed_ms=elapsed(),
        )

    checks, tally = _assertions(subject, driver)
    survived = subject.measurements.get(SEGFAULT_KEY)
    checks.append(
        Assertion(
            "the deliberate segfault was contained and the run completed",
            ok=survived is True,
            detail=(
                "a child dereferenced address 1 and the run continued around it"
                if survived is True
                else "a segfault must be survived by something OUTSIDE the segfaulting "
                "process, and this library may not create one. Run "
                "`python tools/ow_conform.py --card <card> --fixtures <dir>`, which spawns "
                "the crash and reports whether the parent was still there afterwards"
            ),
            locus="segfault",
            expected="a contained crash",
            actual="contained" if survived is True else "not measured from in-process",
        )
    )
    summary = (
        f"{tally['execs']} execs, {tally['refused']} typed refusals, {tally['crashes']} crashes "
        f"contained, {tally['hangs']} hangs"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _assertions(subject: Subject, driver: object) -> tuple[list[Assertion], dict[str, int]]:
    scratch = subject.scratch(SUITE)
    tally = {"execs": 0, "refused": 0, "crashes": 0, "hangs": 0, "ok": 0}
    checks: list[Assertion] = []
    hangs: list[str] = []
    untyped: list[str] = []

    for index, fixture in enumerate(subject.fixtures):
        for number, (label, body) in enumerate(_mutations(fixture)):
            mutant = Fixture(
                path=fixture.path,
                data=body,
                digest=MemoryBlobStore.digest_of(body),
            )
            where = f"{fixture.name}:{label}"
            at = time.monotonic_ns()
            try:
                run_parse(driver, mutant, scratch / f"m{index}-{number}")
                tally["ok"] += 1
            except DriverError:
                tally["refused"] += 1
            except (RecursionError, MemoryError):
                # A crash in the sense the row means: the process would have died under a real
                # host, the host would have logged one row, and the run would have continued.
                tally["crashes"] += 1
            except OwError as exc:
                untyped.append(f"{where}: {type(exc).__name__}")
            except Exception as exc:
                untyped.append(f"{where}: {type(exc).__name__}: {exc}"[:100])
            finally:
                tally["execs"] += 1
            if time.monotonic_ns() - at > HANG_BUDGET_NS:
                hangs.append(where)

    checks.append(
        Assertion(
            "no input took longer than the hang budget",
            ok=not hangs,
            detail=(
                f"over {HANG_BUDGET_S}s: {', '.join(hangs[:4])}"
                if hangs
                else f"{tally['execs']} execs, none over {HANG_BUDGET_S}s"
            ),
            locus="hang",
        )
    )
    checks.append(
        Assertion(
            "every failure is a typed DriverError from the closed FailureClass",
            ok=not untyped,
            detail=(
                f"untyped: {'; '.join(untyped[:4])}"
                if untyped
                else f"{tally['refused']} typed refusals, {tally['crashes']} contained crashes"
            ),
            locus="typed",
            expected="DriverError, RecursionError or MemoryError",
            actual="; ".join(untyped[:3]) or "none",
        )
    )
    # The floor is what the mutator ACTUALLY yields, counted, rather than a constant times the
    # fixture count: `bitflip` is skipped for an empty fixture, so a hand-written multiplier is
    # off by one for every zero-byte input and the assertion then fails for a reason that is
    # about arithmetic rather than about the driver. It did; `mutate.count` is the fix, and it
    # generates for exactly that reason.
    expected = sum(count(f.data) for f in subject.fixtures)
    checks.append(
        Assertion(
            "every generated mutation was actually run",
            ok=tally["execs"] >= expected,
            detail=f"{tally['execs']} execs of {expected} mutations",
            locus="corpus",
            expected=str(expected),
            actual=str(tally["execs"]),
        )
    )
    return checks, tally
