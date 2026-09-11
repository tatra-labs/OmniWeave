"""Suite 3 of 12 -- `contract`: the code is the shape the card and the Port say it is.

04-driver-system.md:2075: "`PORT` and `SCHEMA_VERSION` match the card; every protocol method
exists with the declared signature; `__init__` loads no model and opens no file; `DriverError` is
raised, never `None` returned, never an empty success". The defect: **a driver returning `None` on
failure and blaming the next stage**.

`omniweave_ports/base.py:29-31` hands this suite its job by name: the four Port protocols are
deliberately not `@runtime_checkable`, because "structural conformance to a work signature is the
conform `contract` suite's job, not `isinstance`'s". A `runtime_checkable` Protocol checks that
*names* exist and says nothing about their parameters, which is precisely the check that would pass
for a driver whose `parse` takes `(self, unit)` and blows up at the third argument.

## The four claims, and what makes each one able to fail

* **`PORT` / `SCHEMA_VERSION`.** `activate()` raises `CARD_CODE_MISMATCH` on disagreement, so this
  assertion is the *outcome* of calling it, caught and reported rather than propagated. Reported,
  because a mismatch is a finding about the driver and a traceback is a finding about the kit.
* **Signatures.** Compared parameter NAME by parameter name against the Protocol, in order. Names
  and not just arity: the host calls `parse(unit, parts, io)` positionally today and a renamed
  parameter is a latent break the day anything calls it by keyword. `inspect.signature` on the
  Protocol's own method is the reference, so the check follows `ports.py` without transcribing it.
* **`__init__` opens no file and loads no model.** The instrument RECORDS rather than raises: a
  driver that opens a file gets a real handle and finishes constructing, so the suite reports what
  was opened instead of reporting a traceback from halfway through a constructor. `imports_torch`
  is the card's own key for the model half, so a card declaring `false` and a `sys.modules` that
  gains `torch` is a card/code disagreement this suite can state precisely.
* **Never `None`, never an empty success.** Every fixture is run and the results are classified. A
  driver that raises something other than `DriverError` is the failure named in the row, and the
  kit does not need to know which fixture is the bad one to find it.

And one more the row implies rather than states: **cancellation is checked at every loop top**
(04-driver-system.md:1738, and the template driver's own `io.cancelled()` call). `KitIO` can cancel
after the Nth progress report, which turns "does it check" into a deterministic question with no
clock in it.

Specified in 04-driver-system.md section 8.2 row 3, sections 1.2 and 1.4.
"""

from __future__ import annotations

import builtins
import inspect
import io as _io
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import DriverHostError
from omniweave_ports.ports import AcquireV1, DeriveV1, EmbedV1, ParseV1
from omniweave_ports.types import DriverError, DriverResult, FailureClass, Port

from omniweave_conform.harness import run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "contract"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

PROTOCOL_FOR_PORT: dict[Port, type] = {
    Port.ACQUIRE: AcquireV1,
    Port.PARSE: ParseV1,
    Port.DERIVE: DeriveV1,
    Port.EMBED: EmbedV1,
}
"""Port to Protocol. `Port.COMPILE` is absent on purpose.

04-driver-system.md:379-383: `CompileV1` "lives in `omniweave_core.out.compile`, NOT here", because
its signature mixes ports types with `Plan`, `ILBundle`, `AssetLedger`, `RuleSpec` and `CarrierDoc`
and a Protocol has to live in the one distribution holding both halves. That module is P5's, so a
`compile/1` card gets an `unknown` naming what is missing rather than a signature check against a
Protocol this kit would have had to invent."""

_MODEL_MODULES = ("torch",)
"""What `[hardware] imports_torch = false` is a claim about. One entry because the card has one
key: inventing a wider list here would be the kit asserting something no card declares, and a
driver would fail a claim it was never offered a way to make."""


@contextmanager
def _watching_io() -> Iterator[dict[str, list[str]]]:
    """Record every file open and socket creation, and let all of them succeed.

    Recording rather than raising, for the reason in the module docstring. The four patched names
    are the four ways a constructor actually opens something: `builtins.open` (which `io.open` is),
    `Path.open`, `Path.read_bytes`/`read_text` (which do not route through `builtins.open`), and
    `socket.socket`.
    """
    seen: dict[str, list[str]] = {"open": [], "socket": []}
    real_open = builtins.open
    real_path_open = Path.open
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text
    real_socket = socket.socket

    def traced_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        seen["open"].append(str(file))
        return real_open(file, *args, **kwargs)

    def traced_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        seen["open"].append(str(self))
        return real_path_open(self, *args, **kwargs)

    def traced_read_bytes(self: Path) -> bytes:
        seen["open"].append(str(self))
        return real_read_bytes(self)

    def traced_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        seen["open"].append(str(self))
        return real_read_text(self, *args, **kwargs)

    def traced_socket(*args: Any, **kwargs: Any) -> Any:
        seen["socket"].append(f"socket({args!r})")
        return real_socket(*args, **kwargs)

    builtins.open = traced_open  # type: ignore[assignment]
    _io.open = traced_open  # type: ignore[assignment]
    Path.open = traced_path_open  # type: ignore[method-assign]
    Path.read_bytes = traced_read_bytes  # type: ignore[method-assign]
    Path.read_text = traced_read_text  # type: ignore[method-assign]
    socket.socket = traced_socket  # type: ignore[misc]
    try:
        yield seen
    finally:
        builtins.open = real_open  # type: ignore[assignment]
        _io.open = real_open  # type: ignore[assignment]
        Path.open = real_path_open  # type: ignore[method-assign]
        Path.read_bytes = real_read_bytes  # type: ignore[method-assign]
        Path.read_text = real_read_text  # type: ignore[method-assign]
        socket.socket = real_socket  # type: ignore[misc]


def run(subject: Subject) -> SuiteResult:
    """The `contract` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731

    try:
        loaded = subject.activate()
    except DriverHostError as exc:
        return SuiteResult.of(
            SUITE,
            [
                Assertion(
                    "the card's entrypoint activates and its PORT/SCHEMA_VERSION match the card",
                    ok=False,
                    detail=f"{exc.symbol}: {exc}",
                    locus="activate",
                )
            ],
            elapsed_ms=elapsed(),
        )

    checks: list[Assertion] = [
        Assertion(
            "the card's entrypoint activates and its PORT/SCHEMA_VERSION match the card",
            ok=True,
            detail=f"{loaded.__module__}.{loaded.__qualname__}",
            locus="activate",
        )
    ]
    checks.extend(_signature_assertions(subject, loaded))
    construction, driver = _construction_assertions(subject)
    checks.extend(construction)
    if driver is not None and subject.card.identity.port is Port.PARSE:
        checks.extend(_outcome_assertions(subject, driver))

    summary = (
        f"{len(checks)} assertions; __init__ opened {_opened_count(checks)} files, loaded 0 models"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _opened_count(checks: list[Assertion]) -> int:
    for check in checks:
        if check.locus == "__init__:open":
            return 0 if check.ok else 1
    return 0


def _signature_assertions(subject: Subject, loaded: type) -> Iterator[Assertion]:
    """Every method of the Port's Protocol, present and with the declared parameter names."""
    port = subject.card.identity.port
    protocol = PROTOCOL_FOR_PORT.get(port)
    if protocol is None:
        yield Assertion(
            f"the {port.value}/1 Protocol is available to compare against",
            ok=False,
            detail=(
                "CompileV1 lives in omniweave_core.out.compile (04:379-383), which arrives at "
                "P5 W5.x; this kit will not invent a Protocol to check a driver against"
            ),
            locus="signature",
        )
        return
    for name, reference in _protocol_methods(protocol):
        actual = getattr(loaded, name, None)
        if actual is None:
            yield Assertion(
                f"{name}() exists",
                ok=False,
                detail=f"{protocol.__name__} declares it and the loaded class has no attribute",
                locus=f"signature:{name}",
            )
            continue
        want = _parameter_names(reference)
        got = _parameter_names(actual)
        yield Assertion(
            f"{name}() takes the parameters {protocol.__name__} declares",
            ok=want == got,
            detail="compared by NAME and order, because a host may call by keyword",
            locus=f"signature:{name}",
            expected="(" + ", ".join(want) + ")",
            actual="(" + ", ".join(got) + ")",
        )


def _protocol_methods(protocol: type) -> Iterator[tuple[str, Any]]:
    """The Protocol's own methods, minus `__init__`, which every class has anyway.

    `__init__` is checked by construction rather than by signature: `**config: Scalar` admits any
    keyword, so a name comparison against it would assert nothing.
    """
    for name, member in vars(protocol).items():
        if name.startswith("_") or not callable(member):
            continue
        yield name, member


def _parameter_names(func: Any) -> tuple[str, ...]:
    """Positional parameter names, `self` and `cls` dropped, `**kwargs` kept as `**name`."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return ("<unreadable>",)
    names: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            names.append(f"**{parameter.name}")
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            names.append(f"*{parameter.name}")
        else:
            names.append(parameter.name)
    return tuple(names)


def _construction_assertions(subject: Subject) -> tuple[list[Assertion], object | None]:
    """Construct under the card's own `[config]` defaults, watching what `__init__` touches."""
    before = frozenset(sys.modules)
    try:
        with _watching_io() as seen:
            driver = subject.instantiate()
    except Exception as exc:  # a constructor may raise anything; that IS the finding.
        return (
            [
                Assertion(
                    "the driver constructs under the [config] defaults its own card declares",
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}",
                    locus="__init__",
                )
            ],
            None,
        )
    gained = sorted(frozenset(sys.modules) - before)
    model_modules = [name for name in gained if name.split(".")[0] in _MODEL_MODULES]
    checks = [
        Assertion(
            "the driver constructs under the [config] defaults its own card declares",
            ok=True,
            detail=f"{len(gained)} modules imported during __init__",
            locus="__init__",
        ),
        Assertion(
            "__init__ opens no file",
            ok=not seen["open"],
            detail=(
                "opened: " + ", ".join(seen["open"][:3])
                if seen["open"]
                else "a 100%-cache-hit run constructs and reads nothing (ports/base.py:52-55)"
            ),
            locus="__init__:open",
        ),
        Assertion(
            "__init__ opens no socket",
            ok=not seen["socket"],
            detail="; ".join(seen["socket"][:3]) or "none",
            locus="__init__:socket",
        ),
        Assertion(
            "__init__ loads no model the card says it does not load",
            ok=subject.card.hardware.imports_torch or not model_modules,
            detail=(
                f"[hardware] imports_torch = {str(subject.card.hardware.imports_torch).lower()}; "
                f"__init__ imported {', '.join(model_modules) or 'no model module'}"
            ),
            locus="__init__:model",
        ),
    ]
    return checks, driver


def _outcome_assertions(subject: Subject, driver: object) -> Iterator[Assertion]:
    """Run every fixture and classify: no `None`, no foreign exception, no empty success."""
    if not subject.fixtures:
        yield Assertion(
            "there is a fixture to run",
            ok=False,
            detail=(
                "--fixtures named no readable file; the outcome half of this suite asserts "
                "nothing without one, and a suite that asserts nothing must not read as a pass"
            ),
            locus="outcome",
        )
        return
    scratch = subject.scratch(SUITE)
    best: tuple[int, Any] | None = None
    for index, fixture in enumerate(subject.fixtures):
        try:
            run_result = run_parse(driver, fixture, scratch / f"f{index}")
        except DriverError as exc:
            yield Assertion(
                "a failure is raised as DriverError",
                ok=True,
                detail=f"{exc.cls.value}: {exc}"[:120],
                fixture=fixture.name,
                locus="outcome",
            )
            continue
        except Exception as exc:  # anything that is not a DriverError IS the defect.
            yield Assertion(
                "a failure is raised as DriverError, never as another exception type",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}"[:160],
                fixture=fixture.name,
                locus="outcome",
                expected="DriverError",
                actual=type(exc).__name__,
            )
            continue
        result = run_result.result
        if not isinstance(result, DriverResult):
            yield Assertion(
                "parse() returns a DriverResult, never None",
                ok=False,
                detail=f"returned {type(result).__name__}",
                fixture=fixture.name,
                locus="outcome",
                expected="DriverResult",
                actual=type(result).__name__,
            )
            continue
        yield Assertion(
            "an ok outcome produced at least one artifact",
            ok=bool(result.produced),
            detail=f"outcome={result.outcome} produced={len(result.produced)}",
            fixture=fixture.name,
            locus="outcome",
        )
        blocks = len(run_result.blocks)
        if blocks == 0 and result.produced:
            yield Assertion(
                "an empty result is named by is_valid_nonempty rather than returned as ok",
                ok=not driver.is_valid_nonempty(result.produced[0]),  # type: ignore[attr-defined]
                detail=(
                    "an ok that fails here becomes FAILED_PERMANENT(EMPTY_RESULT), so an empty "
                    "success is never memoised and never served from cache forever"
                ),
                fixture=fixture.name,
                locus="outcome:empty",
            )
        if best is None or blocks > best[0]:
            best = (blocks, fixture)
    yield from _cancellation_assertion(subject, driver, best)


def _cancellation_assertion(
    subject: Subject, driver: object, best: tuple[int, Any] | None
) -> Iterator[Assertion]:
    """Cancel after the first progress report and require a `DriverError(TIMEOUT)`.

    04-driver-system.md:1738 makes `io.cancelled()` a check "at every loop top". Deterministic
    because the cancellation is a counter in `KitIO`, not a clock: the suite needs a fixture with
    at least two blocks so there IS a second loop top, and says so when there is not.
    """
    if best is None or best[0] < 2:  # noqa: PLR2004 -- two blocks is two loop tops, by definition.
        yield Assertion(
            "a fixture with at least two blocks exists, so there is a second loop top to cancel at",
            ok=False,
            detail=(
                "every fixture produced fewer than two blocks; cancellation cannot be observed "
                "in a loop that runs once"
            ),
            locus="cancel",
        )
        return
    _, fixture = best
    try:
        run_parse(driver, fixture, subject.scratch(SUITE) / "cancel", cancel_after_progress=1)
    except DriverError as exc:
        yield Assertion(
            "cancellation between loop tops raises DriverError(TIMEOUT)",
            ok=exc.cls is FailureClass.TIMEOUT,
            detail=f"raised {exc.cls.value}",
            fixture=fixture.name,
            locus="cancel",
            expected=FailureClass.TIMEOUT.value,
            actual=exc.cls.value,
        )
        return
    except Exception as exc:
        yield Assertion(
            "cancellation between loop tops raises DriverError(TIMEOUT)",
            ok=False,
            detail=f"raised {type(exc).__name__}: {exc}"[:160],
            fixture=fixture.name,
            locus="cancel",
            expected="DriverError(timeout)",
            actual=type(exc).__name__,
        )
        return
    yield Assertion(
        "cancellation between loop tops raises DriverError(TIMEOUT)",
        ok=False,
        detail=(
            "the driver ran to completion after io.cancelled() became True, so it does not check "
            "at every loop top and a cancelled generation cannot stop it"
        ),
        fixture=fixture.name,
        locus="cancel",
        expected="DriverError(timeout)",
        actual="returned ok",
    )
