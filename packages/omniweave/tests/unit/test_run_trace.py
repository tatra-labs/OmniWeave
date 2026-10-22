"""A run's event spine: where its shard is, and the three kinds it writes. D941."""

from __future__ import annotations

from pathlib import Path

from omniweave.run.trace import RunTrace, shard_of
from omniweave_core.clock import SystemClock
from omniweave_core.config import load
from omniweave_core.events import parse_line


def _config(tmp_path: Path, observe: str = "") -> object:
    (tmp_path / "omniweave.toml").write_text(observe or "[ingest]\nmax_parts = 50\n", "utf-8")
    return load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "h")})


def test_a_run_with_no_project_writes_no_shard(tmp_path: Path) -> None:
    """Ruling 1: `[observe] ndjson_path` is relative to the project, and there is none."""
    assert shard_of(load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "h")}), "r1") is None


def test_the_shard_is_the_configured_path_under_the_project(tmp_path: Path) -> None:
    assert shard_of(_config(tmp_path), "r_01") == tmp_path / ".omniweave/events/r_01.ndjson"  # type: ignore[arg-type]


def test_a_project_that_leaves_ndjson_out_of_its_sinks_writes_none(tmp_path: Path) -> None:
    config = _config(tmp_path, '[observe]\nsinks = ["console"]\n')
    assert shard_of(config, "r_01") is None  # type: ignore[arg-type]


def test_a_shard_under_omniweave_home_is_expanded_from_the_declared_environment(
    tmp_path: Path,
) -> None:
    """15:1729's shared-service form. The variable comes from `env`; absent, there is no shard
    rather than a directory called `$OMNIWEAVE_HOME`."""
    config = _config(
        tmp_path, '[observe]\nndjson_path = "$OMNIWEAVE_HOME/events/{run_id}.ndjson"\n'
    )
    home = tmp_path / "owhome"
    assert shard_of(config, "r_01", env={"OMNIWEAVE_HOME": str(home)}) == (  # type: ignore[arg-type]
        home / "events" / "r_01.ndjson"
    )
    assert shard_of(config, "r_01", env={}) is None  # type: ignore[arg-type]


def test_the_spine_is_start_failures_end_and_every_record_is_valid(tmp_path: Path) -> None:
    """Ruling 2: one run span, `run.start` and `run.end` on it with no parent, each `unit.failed`
    a point record under it; ruling 3: the stored message travels as it is."""
    config = _config(tmp_path)
    trace = RunTrace.open(config, run_id="r_01", worker="host:42:12.5", clock=SystemClock())  # type: ignore[arg-type]
    assert trace is not None
    trace.start(
        trigger="cli",
        argv_digest="a" * 64,
        config_digest="b" * 64,
        semantic_digest="c" * 64,
        generation=3,
    )
    assert (
        trace.failed([("u/a.txt", "parse.text.x", "driver_bug", "ValueError at d.py:3 in p")]) == 1
    )
    trace.end(status="partial", units=2, failures=1, micros=0)
    assert trace.close() == 0
    lines = trace.path.read_text(encoding="utf-8").splitlines()
    records = [parse_line(line) for line in lines]
    assert all(record is not None for record in records)
    kinds = [str(record.kind) for record in records if record is not None]
    assert kinds == ["run.start", "unit.failed", "run.end"]
    start, failed, end = (record for record in records if record is not None)
    for record in (start, failed, end):
        record.validate()
        assert record.trace_id == start.trace_id
        assert record.run_id == "r_01"
    assert (start.parent_span_id, end.parent_span_id) == (None, None)
    assert start.span_id == end.span_id == failed.parent_span_id
    assert (failed.unit, failed.driver) == ("u/a.txt", "parse.text.x")
    assert dict(failed.fields) == {
        "failure_class": "driver_bug",
        "message": "ValueError at d.py:3 in p",
    }
    assert dict(end.fields)["events_dropped"] == 0
    assert [record.seq for record in records if record is not None] == [1, 2, 3]
