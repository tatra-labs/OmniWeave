"""Suite 2 of 12 -- `purity`: building the catalog imported none of the driver's modules.

04-driver-system.md:2074: "discovery under an **import tracer**: fails if any module of the
driver's distribution was imported while building the catalog". The defect it catches is named:
**docling's load-then-gate order**.

That order is worth restating because it is the whole argument for the suite.
`docling/docling/models/factories/base_factory.py:96` calls
`plugin_manager.load_setuptools_entrypoints(plugin_name)`, and the `allow_external_plugins` test
sits in the NEXT loop at `:98-105`. The gate suppresses *registration* by code that has already
*executed*. Four consequences omniweave cannot accept: no licence gate before execution, no cost
evidence without paying the import, no catalog without importing everything, and order-dependent
registration.

## The instrument, and the thing it is honest about

`sys.modules` before, `catalog()`, `sys.modules` after. A watched name that appears in the
difference is a failure.

The honesty is in the other direction. **A watched name that was ALREADY imported cannot be
observed at all** -- once a process has the module for its own reasons, `sys.modules` can no longer
tell you whether discovery put it there. `test_discovery_never_imports.py:23-25` says exactly this
about its own instrument: "The fresh interpreter is the only place either is observable". So each
watched name is classified before the run, unobservable names are reported as unobservable, and if
*every* watched name is unobservable the suite is `unknown` with that reason rather than `pass`.
A pass earned by not being able to look is the failure this suite exists to catch, turned inward.

## Why it does not spawn a fresh interpreter

Because it may not. `subprocess` has exactly two permitted homes in library code --
`omniweave_core/toolchain.py` and `omniweave_core/host/subproc.py` -- and
`tools/semgrep/omniweave.yaml`'s `omniweave-no-subprocess-outside-toolchain-and-host-subproc`
scopes the ban to `packages/*/src/**`, which includes this file. The process control is
`tools/ow_conform.py`'s, under ledger D25's standing pattern: the mechanism lives in the package
and the spawn lives in `tools/`. Run from there, every watched name is observable, which is why
the tool runs `purity` in a child of its own and this function reports what it can see from where
it is.

Specified in 04-driver-system.md sections 4.6 and 8.2 row 2; INV-4, DR1, DR2.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Final

from omniweave_core.discovery import catalog

from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from omniweave_conform.subject import Subject

SUITE = "purity"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

CLEAN_PROCESS_KEY = "purity_clean_process"
"""`{"verdict": ..., "summary": ...}` from a fresh interpreter, supplied by
`tools/ow_conform.py`.

CORROBORATION, never a replacement. This suite reports what IT observed, because a suite that
reported someone else measurement would be a suite with no instrument -- and the value arrives
through `Subject.config`, which is caller-supplied and therefore exactly as trustworthy as the
caller. So the child verdict is added as one more assertion beside this process own, and a
disagreement between them is itself visible rather than resolved in favour of either."""


def watched_names(subject: Subject) -> tuple[str, ...]:
    """The module names whose appearance in `sys.modules` would be a failure.

    Three, narrowest last, because the narrowest is the one that stays observable when the driver
    ships inside a package the kit itself is running from:

    * the distribution's top-level import root (`omniweave_driver_plaintext`);
    * the package containing the entrypoint module (`omniweave_driver_plaintext.driver`'s parent);
    * the entrypoint module itself.

    For a driver installed as its own distribution all three are unimported before a run and all
    three are watched. For the conformance-template driver -- which ships inside `omniweave_conform`
    so that `ow drivers scaffold` has something to copy -- the first two are the kit's own package
    and are necessarily already imported, and the third is not. The suite watches what it can and
    says which.
    """
    entrypoint = subject.card.identity.entrypoint
    if entrypoint is None:
        return ()
    module = entrypoint.partition(":")[0]
    names = {module, subject.import_root}
    parent = module.rpartition(".")[0]
    if parent:
        names.add(parent)
    return tuple(sorted(names, key=len))


def _imported_under(names: Iterable[str]) -> set[str]:
    """Every `sys.modules` key that is one of `names` or a submodule of one."""
    watched = tuple(names)
    return {
        key
        for key in tuple(sys.modules)
        if any(key == name or key.startswith(f"{name}.") for name in watched)
    }


def run(subject: Subject) -> SuiteResult:
    """The `purity` suite. **Does not call `Subject.activate()`**, and must not."""
    started = time.monotonic_ns()
    names = watched_names(subject)
    if not names:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=(
                "this card declares [driver] exec and names no module; activate() imports "
                "nothing for an exec driver, so there is nothing for discovery to import"
            ),
            elapsed_ms=(time.monotonic_ns() - started) / _NS_PER_MS,
        )

    supplied = subject.measurements.get(CLEAN_PROCESS_KEY)
    before = _imported_under(names)
    preloaded = sorted(
        name for name in names if any(key == name or key.startswith(f"{name}.") for key in before)
    )
    observable = [name for name in names if name not in preloaded]

    built = catalog()
    after = _imported_under(names)
    appeared = sorted(after - before)

    checks = [
        Assertion(
            "building the catalog imported no module of the driver's distribution",
            ok=not appeared,
            detail=(
                f"appeared during catalog(): {', '.join(appeared)}"
                if appeared
                else f"watched {', '.join(observable) or 'nothing observable'}"
            ),
            locus="sys.modules",
            expected="no new module under " + ", ".join(names),
            actual=", ".join(appeared) if appeared else "none",
        ),
        Assertion(
            "the catalog was actually built, so the instrument had something to watch",
            ok=built is not None,
            detail=f"{len(built.cards)} cards discovered",
            locus="catalog",
        ),
    ]
    if isinstance(supplied, dict):
        checks.append(
            Assertion(
                "a fresh interpreter, in which every watched name is observable, agrees",
                ok=supplied.get("verdict") == "pass",
                detail=str(supplied.get("summary", ""))[:200],
                locus="clean_process",
                expected="pass",
                actual=str(supplied.get("verdict", "not measured")),
            )
        )
    for name in preloaded:
        checks.append(
            Assertion(
                f"{name} was already imported and is therefore unobservable here",
                ok=True,
                detail=(
                    "sys.modules cannot say who imported it; run `tools/ow_conform.py --suite "
                    "purity` for a fresh interpreter in which it is observable"
                ),
                locus="sys.modules",
            )
        )
    if not observable and not isinstance(supplied, dict):
        return SuiteResult.of(
            SUITE,
            checks,
            unknown=(
                f"every watched name ({', '.join(names)}) was already imported in this "
                f"process, and no clean-interpreter measurement was supplied, so nothing "
                f"about discovery is observable from anywhere this suite can see"
            ),
            elapsed_ms=(time.monotonic_ns() - started) / _NS_PER_MS,
        )
    summary = (
        f"{len(appeared)} driver modules imported during discovery; watched "
        f"{', '.join(observable)}" + (f"; {len(preloaded)} unobservable" if preloaded else "")
    )
    return SuiteResult.of(
        SUITE,
        checks,
        summary=summary,
        elapsed_ms=(time.monotonic_ns() - started) / _NS_PER_MS,
    )
