"""Suite 5 of 12 -- `idempotence`: the same bytes in, the same bytes out, twice and then again.

04-driver-system.md:2077: "the same input twice through one process yields byte-identical output,
and again through two processes". The defect: **hidden per-instance state**.

## The two halves are two different accusations

* **The same instance, twice.** Catches state a driver accumulated on its first call -- a cache
  keyed on nothing, a counter in a block id, a list appended to rather than rebuilt. This is the
  half that catches `self.` where a local was meant.
* **A fresh instance, once each.** Catches state at *class* scope -- a mutable default, a module
  global, a lazily built table that the first construction populated differently. A driver can
  pass the first half and fail this one, which is why both run.

Both are in-process and both run here. **The third -- two processes -- is `tools/ow_conform.py`'s**,
under ledger D25's standing pattern: `subprocess` has exactly two permitted homes in library code
(`omniweave_core/toolchain.py` and `omniweave_core/host/subproc.py`) and
`tools/semgrep/omniweave.yaml` scopes that ban to `packages/*/src/**`, which is this file. When the
tool has not supplied a cross-process digest, this suite says so in an assertion rather than
reporting eleven-twelfths of a claim as a pass.

## Why the comparison is over the fragment bytes and not over the records

Byte-identical is the claim. Comparing decoded records would pass for a driver that emitted its
keys in a different order on the second run -- which is a real difference, is visible in any
downstream digest, and is exactly what `replay_class = byte_exact` promises will not happen.

Specified in 04-driver-system.md section 8.2 row 5; 03-document-model.md section 15's P21.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import DriverHostError
from omniweave_ports.types import DriverError, Port

from omniweave_conform.harness import run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from omniweave_conform.harness import Fixture
    from omniweave_conform.subject import Subject

SUITE = "idempotence"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

CROSS_PROCESS_KEY = "cross_process_digests"
"""The key `tools/ow_conform.py` puts a second process's per-fixture digests under in
`Subject.measurements`, so this suite can compare without spawning anything itself."""


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def run(subject: Subject) -> SuiteResult:
    """The `idempotence` suite."""
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
            unknown="--fixtures named no readable file; there is nothing to run twice",
            elapsed_ms=elapsed(),
        )
    try:
        first = subject.instantiate()
        second = subject.instantiate()
    except (DriverHostError, DriverError, TypeError, ValueError) as exc:
        return SuiteResult.of(
            SUITE,
            [Assertion("two instances construct", ok=False, detail=str(exc), locus="construct")],
            elapsed_ms=elapsed(),
        )

    checks = list(_assertions(subject, first, second))
    compared = sum(1 for a in checks if a.locus.startswith("same:"))
    summary = (
        f"{compared} fixtures x 2 calls on one instance and 1 on a second, byte-identical; "
        f"{_cross_process_state(subject)}"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _cross_process_state(subject: Subject) -> str:
    supplied = subject.measurements.get(CROSS_PROCESS_KEY)
    return "cross-process compared" if supplied else "cross-process NOT observed in this process"


def _assertions(subject: Subject, first: object, second: object) -> Iterator[Assertion]:
    scratch = subject.scratch(SUITE)
    digests: dict[str, str] = {}
    for index, fixture in enumerate(subject.fixtures):
        name = fixture.name
        try:
            run_a = run_parse(first, fixture, scratch / f"a{index}")
            run_b = run_parse(first, fixture, scratch / f"b{index}")
            run_c = run_parse(second, fixture, scratch / f"c{index}")
        except DriverError:
            # A refused fixture is `contract`'s finding, not this suite's. It is still evidence:
            # a driver that refuses deterministically is idempotent about its refusals, which is
            # asserted below over the exception class rather than skipped.
            yield from _refusal_assertions(first, second, fixture, scratch=scratch, index=index)
            continue
        except Exception as exc:  # attributed by `contract`.
            yield Assertion(
                "the fixture parses, so two runs can be compared",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}"[:160],
                fixture=name,
                locus="run",
            )
            continue
        digest_a, digest_b, digest_c = (_digest(r.body) for r in (run_a, run_b, run_c))
        digests[name] = digest_a
        yield Assertion(
            "the same instance called twice produces byte-identical output",
            ok=digest_a == digest_b,
            detail="catches per-instance state: a cache, a counter, a list appended to",
            fixture=name,
            locus=f"same:{name}",
            expected=digest_a,
            actual=digest_b,
        )
        yield Assertion(
            "a second instance produces byte-identical output",
            ok=digest_a == digest_c,
            detail="catches class-scope state: a mutable default, a module global, a lazy table",
            fixture=name,
            locus=f"fresh:{name}",
            expected=digest_a,
            actual=digest_c,
        )
    yield from _cross_process_assertions(subject, digests)


def _refusal_assertions(
    first: object,
    second: object,
    fixture: Fixture,
    *,
    scratch: Path,
    index: int,
) -> Iterator[Assertion]:
    """A fixture the driver refuses must be refused the same way every time.

    A driver that raises `CORRUPT_INPUT` once and `DRIVER_BUG` the next time is exactly as
    non-idempotent as one whose output bytes differ, and it is the harder failure to notice
    because both runs "failed".
    """
    classes: list[str] = []
    for instance, tag in ((first, "d"), (first, "e"), (second, "f")):
        try:
            run_parse(instance, fixture, scratch / f"{tag}{index}")
            classes.append("ok")
        except DriverError as exc:
            classes.append(exc.cls.value)
        except Exception as exc:
            classes.append(type(exc).__name__)
    yield Assertion(
        "a refused fixture is refused identically on every run",
        ok=len(set(classes)) == 1,
        detail=f"outcomes: {', '.join(classes)}",
        fixture=fixture.name,
        locus=f"same:{fixture.name}",
        expected=classes[0],
        actual=", ".join(classes[1:]),
    )


def _cross_process_assertions(subject: Subject, digests: dict[str, str]) -> Iterator[Assertion]:
    """Compare against a second process's digests, when the tool supplied them.

    `Subject.measurements[CROSS_PROCESS_KEY]` is `{fixture name: sha256 of the fragment
    body}`, written by `tools/ow_conform.py` from a child interpreter. When it is absent the
    assertion is `ok=False` with the reason, which makes the suite `fail` rather than `pass`:
    04:2085's "a skipped gate is not a gate" applies to a *half* of a gate too, and this half is
    a third of the row.
    """
    supplied = subject.measurements.get(CROSS_PROCESS_KEY)
    if not isinstance(supplied, dict):
        yield Assertion(
            "a second process produced byte-identical output",
            ok=False,
            detail=(
                "no cross-process digests were supplied. This library may not spawn -- subprocess "
                "has two homes and neither is here -- so run `python tools/ow_conform.py --card "
                "<card> --fixtures <dir>`, which drives the second process and passes the digests "
                "back through Subject.measurements"
            ),
            locus="cross_process",
        )
        return
    for name, digest in sorted(digests.items()):
        other = supplied.get(name)
        yield Assertion(
            "a second process produced byte-identical output",
            ok=other == digest,
            detail="a difference here is state that outlived a process, or ambient input",
            fixture=name,
            locus=f"cross:{name}",
            expected=digest,
            actual=str(other) if other is not None else "<the second process produced nothing>",
        )
