"""`route_spend`'s contribution to a completion's transaction. **D733.**"""

from __future__ import annotations

from omniweave.route.spend import PriceBook, Spend
from omniweave.run.spend_rows import SPEND_SQL, priced, spend_row
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
        "would_have_been_micros": 0, "outcome": "ok",
    }  # fmt: skip


def test_nothing_measured_is_no_row_and_a_hit_says_so() -> None:
    """Ruling 1 (D139: `None` is not a zero bill) and ruling 4."""
    assert spend_row(4, _result()) == ()
    [hit] = spend_row(4, _result(spend=Spend(tokens_in=5), was_cache_hit=True))
    assert hit.params["was_cache_hit"] == 1


BOOK = PriceBook.loads(
    'version = 1\ncurrency = "USD"\n[local]\ntokens_in_micros = 0.5\ntokens_out_micros = 2.0\n'
)


def test_the_runner_prices_a_paid_attempt_and_a_hit_records_its_saving() -> None:
    """Ruling 6 (D734): 120 in at 0.5 and 30 out at 2.0 is 120 micros; a hit bills 0 and would
    have cost the same."""
    spend = Spend(tokens_in=120, tokens_out=30, calls=1)
    [paid] = priced(BOOK)(4, _result(spend=spend))
    assert (paid.params["micros"], paid.params["would_have_been_micros"]) == (120, 0)
    [hit] = priced(BOOK)(4, _result(spend=spend, was_cache_hit=True))
    assert (hit.params["micros"], hit.params["would_have_been_micros"]) == (0, 120)
    [unpriced] = priced(None)(4, _result(spend=spend, micros=7))
    assert (unpriced.params["micros"], unpriced.params["would_have_been_micros"]) == (7, 0)
    assert priced(BOOK)(4, _result()) == ()


def test_the_books_digest_is_its_rates_as_written() -> None:
    """D734: stable for one book, moved by a rate, and in `route_decision`'s identity."""
    again = PriceBook.loads(
        'currency = "USD"\nversion = 1\n[local]\ntokens_out_micros = 2.0\ntokens_in_micros = 0.5\n'
    )
    assert BOOK.digest == again.digest
    moved = PriceBook.loads(
        'version = 1\ncurrency = "USD"\n[local]\ntokens_in_micros = 0.6\ntokens_out_micros = 2.0\n'
    )
    assert moved.digest != BOOK.digest
    assert len(BOOK.digest) == 64
