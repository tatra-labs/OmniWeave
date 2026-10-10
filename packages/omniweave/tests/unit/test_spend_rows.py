"""`route_spend`'s contribution to a completion's transaction. **D733.**"""

from __future__ import annotations

from omniweave.route.spend import Spend
from omniweave.run.spend_rows import SPEND_SQL, spend_row
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, StepMetrics, StepResult
from omniweave_core.store.queue import COMPLETE_PARTICIPANTS
from omniweave_ports.types import UnitRef

UNIT = UnitRef(uri="file:///d/a.md", part="seg:0123456789abcdef", content_sha256="", byte_len=0)


PRODUCER = Producer(operator="derive.entity", op_version=1, code_fingerprint="",
                    options_digest=bytes(32))  # fmt: skip


def _result(**metrics: object) -> StepResult:
    return StepResult(
        outcome=Outcome.OK,
        unit=UNIT,
        identity=PRODUCER,
        cache_key="0" * 64,
        metrics=StepMetrics(**metrics),  # type: ignore[arg-type]
    )


def test_a_measured_attempt_is_one_statement_in_the_spend_rows_place() -> None:
    """Rulings 1, 3 and 5: the seven dimensions, the runner's micros, and the outcome."""
    spend = Spend(wall_ms=9, tokens_in=120, tokens_out=30, calls=1, bytes_egress=640)
    [statement] = spend_row(4, _result(spend=spend, micros=7))
    assert (statement.participant, statement.name, statement.sql) == (
        "spend_row", "route_spend", SPEND_SQL,
    )  # fmt: skip
    assert "spend_row" in COMPLETE_PARTICIPANTS
    assert dict(statement.params) == {
        "id": 4, "provider": "", "wall_ms": 9, "cpu_ms": 0, "gpu_ms": 0, "tokens_in": 120,
        "tokens_out": 30, "calls": 1, "bytes_egress": 640, "micros": 7, "was_cache_hit": 0,
        "outcome": "ok",
    }  # fmt: skip


def test_nothing_measured_is_no_row_and_a_hit_says_so() -> None:
    """Ruling 1 (D139: `None` is not a zero bill) and ruling 4."""
    assert spend_row(4, _result()) == ()
    [hit] = spend_row(4, _result(spend=Spend(tokens_in=5), was_cache_hit=True))
    assert hit.params["was_cache_hit"] == 1
