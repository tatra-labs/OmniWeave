"""The parse attempt's bill: a `DriverResult`'s metrics as the `Spend` route_spend records. D854.

`test_spend_reconciles_process.py`, in the conform tier, holds a real ingest to I30 under
`ow cost --verify`. This holds the conversion: the seven dimensions copied, a negative report
clamped, and a unit with no result in its report billed as a measured zero.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from omniweave.route.spend import Spend
from omniweave.run.operators import parse
from omniweave_ports.types import DriverMetrics


def _reply(*metrics: DriverMetrics | None) -> Any:
    results = [None if one is None else SimpleNamespace(metrics=one) for one in metrics]
    return SimpleNamespace(report=SimpleNamespace(results=results))


def test_the_seven_dimensions_are_the_drivers() -> None:
    reported = DriverMetrics(
        wall_ms=12,
        cpu_ms=9,
        gpu_ms=3,
        tokens_in=40,
        tokens_out=7,
        calls=2,
        bytes_egress=512,
        bytes_read=4096,
        peak_rss_bytes=1 << 20,
    )
    assert parse._spend_of(_reply(DriverMetrics(), reported), 1) == Spend(
        wall_ms=12, cpu_ms=9, gpu_ms=3, tokens_in=40, tokens_out=7, calls=2, bytes_egress=512
    )


def test_a_negative_report_is_clamped_to_zero() -> None:
    assert parse._spend_of(_reply(DriverMetrics(wall_ms=-5, calls=1)), 0) == Spend(calls=1)


def test_a_unit_with_no_result_is_a_measured_zero() -> None:
    """The attempt ran, so it has a bill; nothing was reported, so the bill is zero."""
    assert parse._spend_of(_reply(DriverMetrics(calls=3)), 1) == Spend()
    assert parse._spend_of(_reply(None), 0) == Spend()
    nothing: Any = SimpleNamespace(report=None)
    assert parse._spend_of(nothing, 0) == Spend()
