"""The twelve suites, in the order `SUITES` gives them, and the one function that dispatches.

04-driver-system.md:2068-2083 is the table. This package is one module per row, each exposing a
single `run(subject) -> SuiteResult`, and `SUITE_RUNNERS` is the mapping from the card's own suite
name to that function.

## The order is not alphabetical and not arbitrary

`SUITES` is `omniweave_core.drivers.card.QUALITY_SUITES`, and its order is load-bearing twice over:

1. **`card` and `purity` run before anything imports the driver.** `purity`'s whole claim is that
   discovery imported no driver module; a suite that ran first and activated the driver would make
   that claim unobservable in-process, which is docling's defect one level up. Nothing in `card` or
   `purity` calls `Subject.activate()`.
2. **`contract` runs before every suite that invokes the driver.** `contract` is the suite that
   asserts `__init__` opens no file and loads no model; running it after a suite that already
   constructed the driver would be asserting a property of a constructor that already ran.

`run_suite()` is therefore a dispatch and not a scheduler: the runner walks `SUITES` in order and
this module refuses to reorder it.

Specified in 04-driver-system.md section 8.2.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from omniweave_conform.result import SUITES, SuiteResult
from omniweave_conform.suites import (
    capability,
    card,
    contract,
    cost,
    determinism,
    fuzz,
    idempotence,
    licence,
    limits,
    purity,
    quality,
    sandbox,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_conform.subject import Subject

__all__ = ["SUITE_RUNNERS", "SuiteRunner", "run_suite"]


class SuiteRunner(Protocol):
    """One suite: a `Subject` in, one `SuiteResult` out, and nothing raised.

    A suite that raises is a bug in the kit rather than a finding about the driver, which is why
    `runner.run()` converts an escape into a `fail` naming the kit -- see its `_guarded()`. The
    Protocol is here so that mapping is typed rather than `dict[str, Any]`.
    """

    def __call__(self, subject: Subject) -> SuiteResult: ...


SUITE_RUNNERS: Final[Mapping[str, SuiteRunner]] = MappingProxyType(
    {
        "card": card.run,
        "purity": purity.run,
        "contract": contract.run,
        "capability": capability.run,
        "idempotence": idempotence.run,
        "determinism": determinism.run,
        "limits": limits.run,
        "sandbox": sandbox.run,
        "cost": cost.run,
        "licence": licence.run,
        "fuzz": fuzz.run,
        "quality": quality.run,
    }
)
"""Name to implementation. **Keyed by the card's own suite names**, and `test_conform_suites.py`
asserts the key set is exactly `SUITES` -- so a thirteenth suite added to the card grammar without
an implementation here is a red test rather than a silently missing row in a report."""


def run_suite(name: str, subject: Subject) -> SuiteResult:
    """Dispatch by name. Raises `KeyError` for a name outside the twelve.

    A `KeyError` rather than an `unknown` verdict: a caller asking for a suite that does not exist
    has made a usage error, and answering it with a verdict would put a row in a report for
    something the kit never ran.
    """
    if name not in SUITES:
        msg = f"{name!r} is not one of the twelve: {', '.join(SUITES)}"
        raise KeyError(msg)
    return SUITE_RUNNERS[name](subject)
