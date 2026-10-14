"""`omniweave.run.bench`'s section 5: the Pacer, and the ratio every time budget is. D822."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest
from omniweave.run import bench
from omniweave_core.store.oweval import Perf

REPO = Path(__file__).resolve().parents[4]
SMALL = {"hash_bytes": 3 * 1024 * 1024 + 17, "loop": 1000, "rows": 50}


class Ticks:
    """A clock that answers from a script, one reading per call."""

    def __init__(self, *readings: int) -> None:
        self._readings = list(readings)
        self.calls = 0

    def monotonic_ns(self) -> int:
        self.calls += 1
        return self._readings.pop(0)

    def wall_ns(self) -> int:  # pragma: no cover -- the Pacer reads no wall clock
        raise AssertionError("the Pacer reads no wall clock")


def _lcg(n: int) -> int:
    value = 0
    for _ in range(n):
        value = (value * 6_364_136_223_846_793_005 + 1_442_695_040_888_963_407) % (1 << 64)
    return value


def test_the_workload_is_the_plans() -> None:
    """12:73-74, and `eval/perf.toml`'s `[pacer] work` saying the same."""
    assert bench.PACER_HASH_BYTES == 64 * 1024 * 1024
    assert bench.PACER_LOOP == 2_000_000
    assert bench.PACER_ROWS == 200_000
    pacer = tomllib.loads((REPO / "eval" / "perf.toml").read_text(encoding="utf-8"))["pacer"]
    assert pacer["work"] == "blake2b(64MiB) + a 2M int loop + 200k sqlite insert+select"
    assert pacer["instability_pct"] == bench.INSTABILITY_PCT == 15


def test_a_run_times_each_third_and_proves_it_did_the_work(tmp_path: Path) -> None:
    clock = Ticks(1_000, 1_400, 2_100, 3_000)
    got = bench.pacer(
        tmp_path,
        clock=clock,
        hash_bytes=SMALL["hash_bytes"],
        loop=SMALL["loop"],
        rows=SMALL["rows"],
    )
    assert (got.hash_ns, got.loop_ns, got.sqlite_ns, got.total_ns) == (400, 700, 900, 2_000)
    assert clock.calls == 4
    assert got.digest == hashlib.blake2b(bytes(SMALL["hash_bytes"])).hexdigest()
    assert got.loop_value == _lcg(SMALL["loop"])
    assert got.key_sum == 50 * 49 // 2
    assert list(tmp_path.iterdir()) == []


def test_two_runs_do_the_same_work(tmp_path: Path) -> None:
    one = bench.pacer(
        tmp_path, hash_bytes=SMALL["hash_bytes"], loop=SMALL["loop"], rows=SMALL["rows"]
    )
    two = bench.pacer(
        tmp_path, hash_bytes=SMALL["hash_bytes"], loop=SMALL["loop"], rows=SMALL["rows"]
    )
    assert (one.digest, one.loop_value, one.key_sum) == (two.digest, two.loop_value, two.key_sum)
    assert one.total_ns > 0


def test_the_ratio_and_the_disagreement_are_the_plans() -> None:
    """12:75: `work_ns / mean(before, after)`, and `abs(before - after) / mean`."""
    assert bench.time_ratio(300, 100, 200) == 2.0
    assert bench.disagreement(100, 200) == pytest.approx(100 / 150)
    assert bench.disagreement(150, 150) == 0.0
    for bad in ((0, 0), (-1, 1)):
        with pytest.raises(ValueError, match="positive"):
            bench.time_ratio(1, *bad)
        with pytest.raises(ValueError, match="positive"):
            bench.disagreement(*bad)


def _paced(tmp_path: Path, before: int, work: int, after: int) -> tuple[Perf, list[int]]:
    """Ten readings: four for the Pacer before, two around the work, four for the Pacer after."""
    calls: list[int] = []
    clock = Ticks(0, 0, 0, before, 10, 10 + work, 20, 20, 20, 20 + after)
    row = bench.paced(
        lambda: calls.append(1),
        run_id="run-1",
        budget_id="parse.p50_ms",
        workspace=tmp_path,
        clock=clock,
        sizes=SMALL,
    )
    return row, calls


def test_a_paced_measurement_is_one_eval_perf_row(tmp_path: Path) -> None:
    row, calls = _paced(tmp_path, before=1_000, work=500, after=1_100)
    assert calls == [1]
    assert (row.pacer_before_ns, row.work_ns, row.pacer_after_ns) == (1_000, 500, 1_100)
    assert row.time_ratio == pytest.approx(500 / 1_050)
    assert (row.peak_rss_bytes, row.peak_wal_bytes) == (None, None)
    assert row.status == "unknown"


def test_a_pacer_that_moved_more_than_fifteen_percent_is_unstable(tmp_path: Path) -> None:
    """12:75-77: neither a pass nor a fail. 1,000 and 1,170 disagree by 15.7%."""
    row, _ = _paced(tmp_path, before=1_000, work=500, after=1_170)
    assert row.status == "unstable"
    edge, _ = _paced(tmp_path, before=1_000, work=500, after=1_162)
    assert bench.disagreement(1_000, 1_162) * 100 < 15
    assert edge.status == "unknown"


def test_the_pacer_subject_runs() -> None:
    assert bench.SUBJECTS["pacer"].runnable
    assert "pacer" in bench.runnable()
