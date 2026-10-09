"""What every package's tests share: latency budgets that cannot fail a content assertion.

**D689.** The query path's deadlines are real: a Channel that misses its `channel_ms` is reported
`UNAVAILABLE(timeout)` and the answer is degraded, and a snapshot that outlives `snapshot_ms` is
refused `OW-S-010` (07:1791, 07:2784). The shipped numbers are 15 to 80 ms per Channel and 2,000
ms per snapshot. A test that asserts WHAT a query finds and runs under them fails whenever its
worker stalls past one, and D688 measured exactly that: one full tier 1/2 run in about twelve,
each time a different test, none of them a product defect.

So by default every test runs with each budget key's declared default replaced:

* `[retrieval.budget]` `query_ms`, `hydration_reserve_ms` and every `channel_ms` entry are
  multiplied by `BUDGET_SCALE`, which keeps the shipped arithmetic (`sum(channel_ms) +
  hydration_reserve_ms == query_ms`) exactly as it is;
* `[retrieval] snapshot_ms` is the ceiling `MAX_SNAPSHOT_MS`, the most a deadline may be.

The declared defaults are the one seam: `config.load()` instantiates them, `QueryBudget()` reads
them and `sqlite.snapshot()` falls back to `snapshot_ms`'s. `config` holds each declaration three
ways (the `_DECLARATIONS` roster, the `_LITERAL_KEYS` subset `load()` walks, and `KEYS`), and all
three are replaced together, so `resolve_key()` and `KEYS` still name one object.
`test_the_budget_a_query_spends_is_the_projects` (`QueryBudget()` equals an empty project's
budget) is what fails if they ever disagree. A budget a test passes explicitly is untouched.

A test that is ABOUT the shipped numbers, or about a deadline that fires at them, carries
`@pytest.mark.shipped_budgets` and runs with the real defaults.

Not reached:

* a subprocess. A test that runs `ow` in a child process gets the shipped budgets;
* a fixture wider than a function. One built before this fixture runs (a module-scoped
  `RetrievalPolicy(budget=QueryBudget())`, say) holds the shipped numbers.

**Why `packages/` and not the repository root.** 58 test modules import names from their
package's `conftest` for the type checker, and pyright resolves a bare `conftest` against the
root first, so a root `conftest.py` turns those into unknown-symbol errors. Every
test pytest collects (`testpaths = ["packages"]`) is under this directory.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest
from omniweave_core import config as ow_config
from omniweave_core.config import KEYS
from omniweave_core.limits import MAX_SNAPSHOT_MS

BUDGET_SCALE = 20
SCALED_KEYS = (
    "retrieval.budget.query_ms",
    "retrieval.budget.hydration_reserve_ms",
)
CHANNEL_KEY = "retrieval.budget.channel_ms"
SNAPSHOT_KEY = "retrieval.snapshot_ms"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "shipped_budgets: runs with the shipped latency budgets, not packages/conftest.py's "
        "(D689).",
    )


def _generous() -> dict[str, object]:
    """Each replaced key's test-time default, computed from its shipped one."""
    out: dict[str, object] = {}
    for key in SCALED_KEYS:
        shipped = KEYS[key].default
        if not isinstance(shipped, int):
            raise TypeError(f"{key} declares {shipped!r}, not a number of milliseconds")
        out[key] = shipped * BUDGET_SCALE
    channels = KEYS[CHANNEL_KEY].default
    if not isinstance(channels, Mapping):
        raise TypeError(f"{CHANNEL_KEY} declares {channels!r}, not a table")
    out[CHANNEL_KEY] = {name: int(ms) * BUDGET_SCALE for name, ms in channels.items()}  # type: ignore[call-overload]
    out[SNAPSHOT_KEY] = MAX_SNAPSHOT_MS
    return out


@pytest.fixture(autouse=True)
def generous_budgets(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every budget key's default made generous, unless the test is marked `shipped_budgets`."""
    if request.node.get_closest_marker("shipped_budgets") is not None:
        return
    generous = {key: replace(KEYS[key], default=default) for key, default in _generous().items()}
    for name in ("_DECLARATIONS", "_LITERAL_KEYS"):
        roster = getattr(ow_config, name)
        monkeypatch.setattr(ow_config, name, tuple(generous.get(k.name, k) for k in roster))
    for key, spec in generous.items():
        monkeypatch.setitem(KEYS, key, spec)  # type: ignore[arg-type]
