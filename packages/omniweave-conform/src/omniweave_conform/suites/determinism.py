"""Suite 6 of 12 -- `determinism`: `replay_class` is honoured, and it is honoured per class.

04-driver-system.md:2077: "`replay_class` is honoured: `byte_exact` across processes with differing
`PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd; `seeded` across seeds; `unpinnable` merely
declared". The defect: **a determinism boolean that cannot express continuous batching**.

That defect is the whole reason `replay_class` is a three-member enum rather than a flag. A
hosted model behind continuous batching is not reproducible and cannot be made so by any amount
of seeding; a boolean forces its author to write `True` and lie, or `False` and be
indistinguishable from a parser with a dict-ordering bug. So each class is checked against *its
own* promise:

| `replay_class` | what this suite requires |
|---|---|
| `byte_exact` | identical bytes across five varied ambient inputs |
| `seeded` | identical bytes for one seed, and the seed is a declared `[config]` key |
| `unpinnable` | nothing beyond the declaration -- and the suite says so, not silently |

## The five ambient inputs, and which three this process can actually vary

`PYTHONHASHSEED` is read by the interpreter at startup and cannot be changed afterwards; cwd is
an ambient input that `tools/semgrep/omniweave.yaml`'s `omniweave-no-getcwd-in-library-code`
forbids library code from touching at all. So **two of the five are the tool's**
(`tools/ow_conform.py` varies them across the child it spawns) and three are varied here:

* `TMPDIR` -- varied directly, because `DriverIO.tmpdir` is an argument rather than an environment
  read. A driver that embeds its scratch path in its output fails this and only this.
* `TZ` and `LC_ALL` -- set in `os.environ` around the second call and restored after. A driver that
  formats a date or case-folds under the ambient locale sees the difference.

`os.environ` is mutated and restored rather than patched, because the point is to change what the
driver's own `os.environ` reads say -- a patched module object would not reach a driver that did
`import os` before the suite ran.

Specified in 04-driver-system.md section 8.2 row 6; 03-document-model.md section 15's P19 and P20.
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import DriverHostError
from omniweave_ports.types import DriverError, Port, ReplayClass

from omniweave_conform.harness import run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "determinism"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

CROSS_PROCESS_KEY = "determinism_cross_process"
"""`{fixture name: digest}` from a child interpreter run under a different `PYTHONHASHSEED` and
cwd, supplied by `tools/ow_conform.py`."""

_VARIED = {"TZ": "Pacific/Kiritimati", "LC_ALL": "tr_TR.UTF-8"}
"""Two values chosen to be maximally hostile rather than merely different.

`Pacific/Kiritimati` is UTC+14, the largest offset in the database, so a driver that stamps a local
date crosses a day boundary relative to almost any other zone. `tr_TR` is the Turkish locale, whose
dotless-i case mapping is the classic case-folding trap: `"I".lower()` differs from the invariant
answer, so a driver that case-folds under the ambient locale changes its output here and nowhere
else.
"""


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@contextmanager
def _ambient(values: dict[str, str]) -> Iterator[None]:
    """Set environment variables and restore exactly what was there, including absence."""
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, was in previous.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


def run(subject: Subject) -> SuiteResult:
    """The `determinism` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731
    replay = subject.card.identity.replay_class

    if replay is ReplayClass.UNPINNABLE:
        return SuiteResult.of(
            SUITE,
            [
                Assertion(
                    "replay_class = unpinnable is merely declared",
                    ok=True,
                    detail=(
                        "04:2077 requires nothing further. The declaration is the honest answer "
                        "for a hosted model behind continuous batching, and a boolean could not "
                        "have expressed it -- which is the defect this row exists to name"
                    ),
                    locus="replay_class",
                )
            ],
            summary="replay_class=unpinnable, declared and not measured",
            elapsed_ms=elapsed(),
        )
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
            unknown="--fixtures named no readable file; ambient variation needs a subject",
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

    checks = list(_assertions(subject, driver, replay))
    varied = ", ".join(["TMPDIR", *sorted(_VARIED)])
    summary = f"replay_class={replay.value} across {varied}; PYTHONHASHSEED and cwd are the tool's"
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _assertions(subject: Subject, driver: object, replay: ReplayClass) -> Iterator[Assertion]:
    scratch = subject.scratch(SUITE)
    digests: dict[str, str] = {}
    for index, fixture in enumerate(subject.fixtures):
        name = fixture.name
        try:
            base = run_parse(driver, fixture, scratch / f"base{index}")
        except DriverError:
            continue
        except Exception as exc:  # attributed by `contract`.
            yield Assertion(
                "the fixture parses, so ambient variation can be compared",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}"[:160],
                fixture=name,
                locus="run",
            )
            continue
        want = _digest(base.body)
        digests[name] = want

        # TMPDIR: a different scratch directory, handed through DriverIO rather than the
        # environment, because `DriverIO.tmpdir` is the argument a driver is obliged to use.
        try:
            with _ambient(_VARIED):
                varied = run_parse(driver, fixture, scratch / f"varied-{index}-deeper-path")
        except DriverError as exc:
            yield Assertion(
                "varying TMPDIR, TZ and LC_ALL does not change the outcome",
                ok=False,
                detail=f"refused under varied ambient input: {exc.cls.value}",
                fixture=name,
                locus=f"ambient:{name}",
            )
            continue
        except Exception as exc:
            yield Assertion(
                "varying TMPDIR, TZ and LC_ALL does not change the outcome",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}"[:160],
                fixture=name,
                locus=f"ambient:{name}",
            )
            continue
        yield Assertion(
            "varying TMPDIR, TZ and LC_ALL produces byte-identical output",
            ok=_digest(varied.body) == want,
            detail=(
                "a difference is an ambient read: a scratch path in the output, a locale-folded "
                "string, or a local date"
            ),
            fixture=name,
            locus=f"ambient:{name}",
            expected=want,
            actual=_digest(varied.body),
        )
    yield from _seeded_assertion(subject, replay)
    yield from _cross_process_assertions(subject, digests, replay)


def _seeded_assertion(subject: Subject, replay: ReplayClass) -> Iterator[Assertion]:
    """`seeded` means there IS a seed, and it is a declared `[config]` key.

    A driver claiming `seeded` with no way for a caller to set the seed has claimed reproducibility
    it offers no handle for, which is `unpinnable` with a better-sounding name.
    """
    if replay is not ReplayClass.SEEDED:
        return
    keys = [name for name in subject.card.config.properties if "seed" in name.lower()]
    yield Assertion(
        "replay_class = seeded, and the card declares a seed in [config]",
        ok=bool(keys),
        detail=(
            f"[config] properties naming a seed: {', '.join(keys)}"
            if keys
            else "reproducibility with no handle to set is unpinnable with a better name"
        ),
        locus="replay_class:seed",
    )


def _cross_process_assertions(
    subject: Subject, digests: dict[str, str], replay: ReplayClass
) -> Iterator[Assertion]:
    """`PYTHONHASHSEED` and cwd, which only a second process can vary."""
    if replay is not ReplayClass.BYTE_EXACT:
        return
    supplied = subject.measurements.get(CROSS_PROCESS_KEY)
    if not isinstance(supplied, dict):
        yield Assertion(
            "a process with a different PYTHONHASHSEED and cwd produced identical output",
            ok=False,
            detail=(
                "PYTHONHASHSEED is fixed at interpreter startup and cwd is an ambient input "
                "library code may not touch, so both axes belong to `tools/ow_conform.py`. Run it "
                "and this assertion is made rather than reported as unmade"
            ),
            locus="cross_process",
        )
        return
    for name, digest in sorted(digests.items()):
        other = supplied.get(name)
        yield Assertion(
            "a process with a different PYTHONHASHSEED and cwd produced identical output",
            ok=other == digest,
            detail="byte_exact is a promise about set and dict iteration order too",
            fixture=name,
            locus=f"cross:{name}",
            expected=digest,
            actual=str(other) if other is not None else "<the second process produced nothing>",
        )
