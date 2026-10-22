"""The absence harness asks under a scaled budget, so latency is not read as degradation. D942."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from omniweave_conform import absence
from omniweave_core.limits import MAX_SNAPSHOT_MS
from omniweave_core.retrieve.types import QueryBudget
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite


@pytest.mark.shipped_budgets
def test_the_harness_budget_is_the_shipped_one_scaled_and_still_lints() -> None:
    """Ruling 5: every figure times the scale; channels plus the reserve equal `query_ms`, which
    is `ow route lint` check 3's arithmetic; the snapshot at its cap."""
    shipped, budget = QueryBudget(), absence.harness_budget()
    scale = absence.HARNESS_BUDGET_SCALE
    assert budget.query_ms == shipped.query_ms * scale
    assert dict(budget.channel_ms) == {k: v * scale for k, v in shipped.channel_ms.items()}
    assert budget.hydration_reserve_ms + sum(budget.channel_ms.values()) == budget.query_ms
    assert budget.snapshot_ms == MAX_SNAPSHOT_MS
    #  The point of the scale: no channel's budget is one a slow runner's cold query overruns.
    assert min(budget.channel_ms.values()) >= 250


def test_ask_queries_under_the_harness_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 5's wiring: the `Query` `ask()` hands to `execute()` carries the scaled budget."""
    store = tmp_path / "project" / ".omniweave" / "docs.owstore"
    store.parent.mkdir(parents=True)
    connection = store_sqlite.connect(store)
    try:
        migrate.apply_pending(connection, now_ns=0)
    finally:
        connection.close()
    seen: dict[str, Any] = {}

    class StopError(Exception):
        pass

    def execute(_reader: object, query: Any, _policy: object) -> Any:
        seen["budget"] = query.budget
        raise StopError

    monkeypatch.setattr("omniweave_core.retrieve.execute.execute", execute)
    with pytest.raises(StopError):
        absence.ask(tmp_path, "anything", now_ns=lambda: 0)
    assert seen["budget"] == absence.harness_budget()
