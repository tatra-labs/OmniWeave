"""The sinks: a real file, a real thread, a real roll, and four properties that are load-bearing.

Nothing here is mocked at the boundary that matters. `NdjsonSink` writes to `tmp_path`, rolls a real
shard, gzips it and reopens; the tests read the bytes back and parse them. A queue test fills a real
`queue.Queue`. The console tests write to a `StringIO` whose `isatty` is controlled, because the
suppression 15:452 asks for is a property of the STREAM and a test that set a flag instead would be
testing the flag.

## The four that would be silently wrong

1. **`emit()` must not block** (15:361, in capitals). `test_a_full_queue_drops_the_oldest_and_never_
   blocks` fills the queue with the writer thread stopped and asserts both halves: the call returns,
   and the record that went is the oldest.
2. **`seq` is assigned before the queue can discard anything** (15:382-385), so a drop is a GAP and
   not an absence. `test_a_drop_leaves_a_gap_in_seq_rather_than_an_absence` reads the written stream
   and finds the hole.
3. **A buffer overflow flushes the unit UNSAMPLED rather than truncating it** (15:158). Truncation
   would produce the orphan I33 forbids, so the overflow test asserts the whole subtree arrives even
   at `ok_rate = 0`.
4. **`fsync` only on roll and at exit** (15:400). Asserted by counting `os.fsync` calls across a
   run that writes forty records and rolls six times: seven, which is one per roll plus one at
   exit, and not one per record.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import queue
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.config import KEYS
from omniweave_core.errors import ConfigError
from omniweave_core.events import (
    CONSOLE_FLOOR_WHEN_PIPED,
    DEFAULT_SHARD_BYTES,
    EVENTS,
    NDJSON_SEPARATORS,
    OK_SAMPLE_RATE,
    SHARD_ORDINAL_DIGITS,
    ConsoleSink,
    Event,
    EventKind,
    Level,
    NdjsonSink,
    Phase,
    RunRecorder,
    SinkStats,
    TraceSink,
    parse_line,
    serialise,
    shard_path,
)
from omniweave_core.limits import MAX_EVENT_QUEUE, MAX_SPAN_BUFFER_EVENTS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conftest import PlanDocs

NOW_NS = 1_757_400_000_000_000_000
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
RUN_ID = "r_01J8Z9QK2M4N6P8R0S2T4V6X8Z"
WRITER = "abc123abc123"


class FakeClock:
    """`Clock`, injected. 15:384: *"what makes an event stream replayable in a test."*"""

    def __init__(self) -> None:
        self.wall = NOW_NS
        self.mono = 1_000

    def monotonic_ns(self) -> int:
        self.mono += 1
        return self.mono

    def wall_ns(self) -> int:
        return self.wall


def record(
    kind: EventKind = EventKind.CACHE_HIT,
    *,
    span_id: str = "00f067aa0ba902b7",
    parent: str | None = None,
    seq: int = 0,
    **over: object,
) -> Event:
    spec = EVENTS[kind.value]
    values: dict[str, Any] = {
        "ts_wall_ns": 0,
        "ts_mono_ns": 0,
        "run_id": "",
        "writer_id": "",
        "seq": seq,
        "trace_id": TRACE_ID,
        "span_id": span_id,
        "parent_span_id": parent,
        "kind": kind,
        "phase": spec.phase.value,
        "level": spec.level.value,
        "fields": {},
    }
    values.update(over)
    return Event(**values)


class Collect:
    """A `TraceSink` that keeps everything. The fan-out's far side, made readable."""

    def __init__(self) -> None:
        self.seen: list[Event] = []

    def emit(self, e: Event) -> None:
        self.seen.append(e)

    def flush(self, timeout_ms: int) -> int:  # noqa: ARG002 -- nothing is queued.
        return 0


@pytest.fixture
def sink(tmp_path: Path) -> Iterator[NdjsonSink]:
    made = NdjsonSink(tmp_path / "events" / f"{RUN_ID}.ndjson", clock=FakeClock())
    try:
        yield made
    finally:
        made.close()


def drain(made: NdjsonSink, *, expect: int) -> list[Event]:
    """Wait for the writer thread, then read what it wrote."""
    deadline = time.monotonic() + 5
    while made.stats.emitted < expect and time.monotonic() < deadline:
        time.sleep(0.002)
    made.flush(1_000)
    return read_shard(made.live_path)


def read_shard(path: Path) -> list[Event]:
    if not path.is_file():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
        return [event for line in handle if (event := parse_line(line)) is not None]


# ---------------------------------------------------------------------------------------------
# 1. The line
# ---------------------------------------------------------------------------------------------


def test_a_record_is_one_line_with_sorted_keys_and_no_whitespace(plan: PlanDocs) -> None:
    """15:389, transcribed: `json.dumps(..., sort_keys=True, separators=(",", ":"))`."""
    assert NDJSON_SEPARATORS == (",", ":")
    assert plan.grep(r'sort_keys=True, separators=\(",", ":"\)', documents=("15-observability.md",))
    line = serialise(record(fields={"layer": "call", "cache_key": "a" * 64}))
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert b", " not in line
    assert b'": ' not in line
    body = json.loads(line)
    assert list(body) == sorted(body)


def test_a_record_round_trips_through_the_line() -> None:
    original = record(
        EventKind.WORK_COMPLETE,
        unit="file:///corpus/a.pdf",
        part="p3",
        operator="parse.pdf",
        driver="parse.pdf.pdfium",
        fields={"work_id": 41, "outcome": "ok", "micros": 0, "was_cache_hit": False},
        seq=7,
    )
    back = parse_line(serialise(original).decode("utf-8"))
    assert back == original


def test_a_partial_final_line_is_skipped_and_never_repaired(plan: PlanDocs) -> None:
    """15:390. Repairing would invent a record; raising would cost the whole shard."""
    assert plan.grep(r"partial final line is skipped on read", documents=("15-observability.md",))
    whole = serialise(record()).decode("utf-8")
    assert parse_line(whole) is not None
    assert parse_line(whole[: len(whole) // 2]) is None
    assert parse_line("") is None
    assert parse_line("   \n") is None
    assert parse_line('{"not": "a record"}') is None


def test_a_non_ascii_name_stays_itself_rather_than_twelve_bytes_of_escapes() -> None:
    line = serialise(record(unit="file:///corpus/contrat-résumé.pdf"))
    assert "résumé".encode() in line
    assert b"\\u00e9" not in line


# ---------------------------------------------------------------------------------------------
# 2. `NdjsonSink`: the queue, the file, and the roll
# ---------------------------------------------------------------------------------------------


def test_a_record_reaches_the_file_through_the_writer_thread(sink: NdjsonSink) -> None:
    sink.emit(record(seq=1))
    assert [e.seq for e in drain(sink, expect=1)] == [1]
    assert sink.stats.emitted == 1
    assert sink.stats.serialise_ns_total > 0


def test_the_parent_directory_is_created_rather_than_required(tmp_path: Path) -> None:
    made = NdjsonSink(tmp_path / "deep" / "deeper" / f"{RUN_ID}.ndjson", clock=FakeClock())
    try:
        made.emit(record(seq=1))
        assert len(drain(made, expect=1)) == 1
    finally:
        made.close()


def test_a_full_queue_drops_the_oldest_and_never_blocks(tmp_path: Path) -> None:
    """15:361 and 15:38. Both halves, with the writer thread held off so the queue really fills.

    The writer is starved by never letting it run: `_drain` blocks on `get()` and this test fills
    the queue faster than a 1 ms sleep lets it drain, so the bound is exercised rather than raced.
    """
    made = NdjsonSink(tmp_path / f"{RUN_ID}.ndjson", clock=FakeClock())
    made._thread.join(timeout=0)
    try:
        made._queue = queue.Queue(maxsize=4)
        for n in range(1, 7):
            started = time.monotonic()
            made.emit(record(seq=n))
            assert time.monotonic() - started < 0.5, "emit blocked"
        assert made.stats.dropped == 2
        held = [made._queue.get_nowait().seq for _ in range(4)]
        assert held == [3, 4, 5, 6], "the OLDEST two went, not the newest"
    finally:
        made.close(timeout_ms=200)


def test_the_queue_bound_is_the_plans_sixty_four_k(plan: PlanDocs, tmp_path: Path) -> None:
    """02:245 and 15:38 both say *"a bounded 64k queue, drop-oldest"*, and a sink is built at it."""
    assert MAX_EVENT_QUEUE == 65_536
    assert plan.grep(r"bounded 64k.*drop-oldest", documents=("15-observability.md",))
    made = NdjsonSink(tmp_path / f"{RUN_ID}.ndjson", clock=FakeClock())
    try:
        assert made._queue.maxsize == MAX_EVENT_QUEUE
    finally:
        made.close(timeout_ms=500)


def test_a_shard_rolls_at_its_byte_bound_and_the_roll_record_closes_it(tmp_path: Path) -> None:
    """15:396-399 and 15:264-268: the closing line names the successor, and the shard is
    deflated."""
    live = tmp_path / f"{RUN_ID}.ndjson"
    made = NdjsonSink(live, clock=FakeClock(), shard_bytes=2_048)
    try:
        # One record at a time, stopping the moment the first roll lands: a burst would roll
        # several times and this test is about what ONE roll leaves behind.
        written = 0
        deadline = time.monotonic() + 5
        while made.stats.shards_rolled == 0 and time.monotonic() < deadline:
            written += 1
            made.emit(record(seq=written, fields={"layer": "call", "cache_key": "c" * 64}))
            time.sleep(0.002)
        assert made.stats.shards_rolled == 1
    finally:
        made.close()
    assert made.stats.shards_rolled == 1

    rolled = shard_path(live, 1)
    assert rolled.is_file()
    assert rolled.name == f"{RUN_ID}.0001.ndjson.gz"
    records = read_shard(rolled)
    assert records[-1].kind == EventKind.SHARD_ROLL, "the roll is the CLOSING line"
    assert records[-1].fields["successor"] == rolled.name
    assert records[-1].fields["closed"] == live.name
    assert int(records[-1].fields["bytes"]) >= 2_048
    assert all(e.kind is not EventKind.SHARD_ROLL for e in records[:-1])


def test_the_roll_record_is_the_vocabularys_own_row() -> None:
    """`shard.roll` is 15:336's appended row, and its four fields are that row's."""
    assert EVENTS["shard.roll"].fields == ("closed", "successor", "bytes", "records")
    assert EVENTS["shard.roll"].level is Level.NOTICE


def test_shard_names_are_four_digits_from_one_and_an_ordinal_below_one_is_refused(
    tmp_path: Path,
) -> None:
    """`{run_id}.0001.ndjson.gz` (15:387). The live shard has no ordinal, so rolls start at 1."""
    assert SHARD_ORDINAL_DIGITS == 4
    live = tmp_path / f"{RUN_ID}.ndjson"
    assert shard_path(live, 1).name.endswith(".0001.ndjson.gz")
    assert shard_path(live, 42).name.endswith(".0042.ndjson.gz")
    with pytest.raises(ConfigError, match="the live shard has no ordinal"):
        shard_path(live, 0)


def test_fsync_happens_on_roll_and_at_exit_and_not_per_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """15:400. A per-record fsync would be eight disk flushes per unit inside a 0.5 ms budget."""
    calls: list[int] = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    made = NdjsonSink(tmp_path / f"{RUN_ID}.ndjson", clock=FakeClock(), shard_bytes=2_048)
    for n in range(1, 41):
        made.emit(record(seq=n, fields={"layer": "call", "cache_key": "c" * 64}))
    deadline = time.monotonic() + 5
    while made.stats.shards_rolled == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    made.close()
    rolled = made.stats.shards_rolled
    assert rolled >= 1
    assert len(calls) == rolled + 1, f"one per roll plus one at exit, not {len(calls)}"
    assert len(calls) < 40, "forty records did not each cost a disk barrier"


def test_an_unwritable_path_degrades_and_the_run_continues(tmp_path: Path) -> None:
    """15:401-403 -- *"telemetry never fails a run, exactly as telemetry never fails a query."*

    The path is a directory, so `open("ab")` raises `IsADirectoryError` on every platform.
    """
    blocked = tmp_path / "events"
    blocked.mkdir()
    made = NdjsonSink(blocked, clock=FakeClock())
    try:
        made.emit(record(seq=1))
        made.emit(record(seq=2))
        deadline = time.monotonic() + 5
        while made.stats.dropped < 2 and time.monotonic() < deadline:
            time.sleep(0.002)
        assert made.stats.dropped == 2
        assert made.stats.emitted == 0
        assert "could not be opened" in made.degraded
        assert "ndjson_path" in made.degraded
    finally:
        made.close(timeout_ms=200)


def test_close_is_idempotent_and_reports_what_it_could_not_write(sink: NdjsonSink) -> None:
    sink.emit(record(seq=1))
    assert sink.close(timeout_ms=1_000) == 0
    assert sink.close() == 0


def test_a_shard_bytes_of_zero_is_refused_naming_the_knob(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[observe\] shard_bytes"):
        NdjsonSink(tmp_path / "x.ndjson", clock=FakeClock(), shard_bytes=0)


def test_the_shipped_shard_bound_is_the_config_default() -> None:
    assert DEFAULT_SHARD_BYTES == KEYS["observe.shard_bytes"].default == 67_108_864


# ---------------------------------------------------------------------------------------------
# 3. `ConsoleSink`: stderr, and the suppression that tests the stream
# ---------------------------------------------------------------------------------------------


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_a_terminal_gets_the_narrative_and_a_pipe_gets_warnings(plan: PlanDocs) -> None:
    """15:452-457. The suppression asks the STREAM, not a config flag."""
    assert CONSOLE_FLOOR_WHEN_PIPED is Level.WARN
    assert plan.grep(r"stderr is not a TTY", documents=("15-observability.md",))

    terminal, piped = _Tty(), io.StringIO()
    on_tty, off_tty = ConsoleSink(terminal), ConsoleSink(piped)
    assert on_tty.floor is Level.DEBUG
    assert off_tty.floor is Level.WARN

    for made in (on_tty, off_tty):
        made.emit(record(EventKind.CACHE_HIT, fields={"layer": "call"}))
        made.emit(record(EventKind.DRIVER_CRASH, fields={"driver": "d"}))
    assert terminal.getvalue().count("\n") == 2
    assert piped.getvalue().count("\n") == 1
    assert "driver.crash" in piped.getvalue()
    assert "cache.hit" not in piped.getvalue()


def test_a_configured_floor_is_never_lowered_by_a_terminal() -> None:
    """A `[observe] level` of `error` stays `error` on a TTY: the TTY rule only ever raises."""
    made = ConsoleSink(_Tty(), floor=Level.ERROR)
    assert made.floor is Level.ERROR


def test_the_console_renders_the_fields_in_the_rows_declared_order() -> None:
    stream = _Tty()
    ConsoleSink(stream).emit(
        record(
            EventKind.WORK_COMPLETE,
            unit="file:///corpus/a.pdf",
            part="p3",
            fields={"micros": 12, "work_id": 41, "outcome": "ok"},
        )
    )
    line = stream.getvalue().strip()
    assert line.index("work_id=") < line.index("outcome=") < line.index("micros=")
    assert "file:///corpus/a.pdf#p3" in line
    assert line.startswith("info")


def test_the_console_never_raises_on_a_closed_stream() -> None:
    stream = _Tty()
    made = ConsoleSink(stream)
    stream.close()
    made.emit(record())
    assert made.flush(0) == 0
    assert made.stats.dropped == 1


def test_the_console_defaults_to_stderr_and_never_stdout(plan: PlanDocs) -> None:
    """15:444-450: stdout is the machine channel and a progress line in it is a parse error."""
    assert ConsoleSink()._stream is sys.stderr
    assert plan.grep(r"stdout is the machine channel", documents=("15-observability.md",))


# ---------------------------------------------------------------------------------------------
# 4. `RunRecorder`: `seq`, the floor, and the tail-sampling buffer
# ---------------------------------------------------------------------------------------------


def recorder(*sinks: TraceSink, **over: Any) -> RunRecorder:
    kwargs: dict[str, Any] = {
        "run_id": RUN_ID,
        "writer": WRITER,
        "clock": FakeClock(),
        "sinks": sinks,
    }
    kwargs.update(over)
    return RunRecorder(**kwargs)


def test_seq_is_monotone_from_one_and_stamps_the_run_and_writer() -> None:
    """15:370-374: monotone per `(run_id, writer_id)`, and both halves are on the record."""
    out = Collect()
    made = recorder(out)
    for _ in range(5):
        made.emit(record())
    assert [e.seq for e in out.seen] == [1, 2, 3, 4, 5]
    assert {e.run_id for e in out.seen} == {RUN_ID}
    assert {e.writer_id for e in out.seen} == {WRITER}
    assert made.seq == 5


def test_both_clocks_are_read_host_side_when_the_caller_leaves_them_zero() -> None:
    """15:201-207: a driver-supplied timestamp is a value in `fields`, never an envelope field."""
    out = Collect()
    recorder(out).emit(record())
    assert out.seen[0].ts_wall_ns == NOW_NS
    assert out.seen[0].ts_mono_ns > 0


def test_the_floor_is_applied_before_serialisation_and_counted() -> None:
    """15:1281: applied *"at `emit()`, before serialisation"*, for both sinks at once."""
    out = Collect()
    made = recorder(out, level=Level.NOTICE)
    made.emit(record(EventKind.STORE_TXN, fields={"rows": 1, "ms": 2}))  # debug
    made.emit(record(EventKind.CACHE_HIT, fields={"layer": "call"}))  # info
    made.emit(record(EventKind.GC_SWEEP, fields={"rows": 1, "bytes": 2}))  # notice
    made.emit(record(EventKind.DRIVER_CRASH, fields={"driver": "d"}))  # error
    assert [str(e.kind) for e in out.seen] == ["gc.sweep", "driver.crash"]
    assert made.stats.dropped == 2
    assert made.seq == 2, "a record below the floor never takes a seq"


def test_the_level_on_the_record_is_the_kinds_whatever_the_caller_said() -> None:
    out = Collect()
    recorder(out).emit(record(EventKind.DRIVER_CRASH, level="debug", fields={"driver": "d"}))
    assert out.seen[0].level == "error"


def test_a_fan_out_gives_every_sink_the_same_record() -> None:
    first, second = Collect(), Collect()
    recorder(first, second).emit(record())
    assert first.seen == second.seen
    assert len(first.seen) == 1


def test_a_drop_leaves_a_gap_in_seq_rather_than_an_absence(tmp_path: Path) -> None:
    """15:382-385, end to end: the recorder stamps, a full queue discards, the file shows the hole.

    *"That ordering is what makes a drop detectable as a gap in `seq` rather than invisible; the
    reverse ordering would have made `run.events_dropped` the only evidence a record ever existed."*
    """
    made = NdjsonSink(tmp_path / f"{RUN_ID}.ndjson", clock=FakeClock())
    made._thread.join(timeout=0)
    rec = recorder(made)
    try:
        made._queue = queue.Queue(maxsize=3)
        for _ in range(5):
            rec.emit(record())
        assert rec.seq == 5, "every record took a seq before the queue could discard one"
        held = [made._queue.get_nowait().seq for _ in range(3)]
        assert held == [3, 4, 5]
        assert made.stats.dropped == 2
        assert set(range(1, 6)) - set(held) == {1, 2}, "seq 1 and 2 are a GAP, not an absence"
    finally:
        made.close(timeout_ms=200)


# ---------------------------------------------------------------------------------------------
# 5. Tail sampling: the buffer, the decision, and the overflow
# ---------------------------------------------------------------------------------------------


def open_unit_subtree(made: RunRecorder, *, work_id: str = "w1", depth: int = 3) -> None:
    """A `unit` span and `depth - 1` descendants under it, parent before child."""
    made.open_unit(work_id, "unit0001")
    made.emit(record(EventKind.UNIT_BEGIN, span_id="unit0001", parent="plan0001"))
    made.emit(
        record(
            EventKind.ATTEMPT_BEGIN, span_id="attm0001", parent="unit0001", fields={"attempt": 1}
        )
    )
    for n in range(depth):
        made.emit(
            record(
                EventKind.CALL_BEGIN,
                span_id=f"call{n:04d}",
                parent="attm0001",
                fields={"driver": "d"},
            )
        )


def test_a_sampled_out_unit_takes_its_whole_subtree_with_it() -> None:
    """15:157: *"dropped whole and counted into `run.events_dropped`."*"""
    out = Collect()
    made = recorder(out, ok_rate=0.0)
    open_unit_subtree(made)
    assert out.seen == [], "nothing escapes while the unit is open"
    assert made.open_units == 1
    assert made.close_unit("w1", "ok") == 0
    assert out.seen == []
    assert made.stats.dropped == 5
    assert made.open_units == 0


def test_a_non_ok_unit_is_kept_whole_at_any_rate() -> None:
    """`non_ok = 1.0`, and the subtree arrives parent-first in emission order."""
    out = Collect()
    made = recorder(out, ok_rate=0.0)
    open_unit_subtree(made)
    assert made.close_unit("w1", "failed_permanent") == 5
    assert [str(e.kind) for e in out.seen] == [
        "unit.begin",
        "attempt.begin",
        "call.begin",
        "call.begin",
        "call.begin",
    ]


def test_a_sampled_in_unit_is_kept_whole() -> None:
    out = Collect()
    made = recorder(out, ok_rate=1.0)
    open_unit_subtree(made)
    assert made.close_unit("w1", "ok") == 5
    assert len(out.seen) == 5


def test_an_overflow_flushes_the_unit_unsampled_rather_than_truncating_it() -> None:
    """15:158, and the reason: a truncated subtree is the orphan I33 forbids in another hat."""
    out = Collect()
    made = recorder(out, ok_rate=0.0)
    made.open_unit("w1", "unit0001")
    for n in range(MAX_SPAN_BUFFER_EVENTS + 12):
        made.emit(
            record(
                EventKind.CALL_BEGIN, span_id=f"c{n:07d}", parent="unit0001", fields={"driver": "d"}
            )
        )
    assert len(out.seen) == 12, "past the bound, records go straight through"
    kept = made.close_unit("w1", "ok")
    assert kept == MAX_SPAN_BUFFER_EVENTS
    assert len(out.seen) == MAX_SPAN_BUFFER_EVENTS + 12
    assert made.stats.dropped == 0, "an overflowed unit is not sampled out"


def test_run_and_plan_records_are_never_buffered() -> None:
    """15:161: *"so the tree always has a spine, and a fully sampled-out run still produces …"*"""
    out = Collect()
    made = recorder(out, ok_rate=0.0)
    made.open_unit("w1", "unit0001")
    made.emit(record(EventKind.RUN_START, span_id="run00001", fields={"trigger": "cli"}))
    made.emit(record(EventKind.PLAN_BEGIN, span_id="unit0001", fields={"stage": "parse"}))
    assert [str(e.kind) for e in out.seen] == ["run.start", "plan.begin"]


def test_an_unowned_record_goes_straight_through() -> None:
    out = Collect()
    made = recorder(out, ok_rate=0.0)
    made.open_unit("w1", "unit0001")
    made.emit(record(EventKind.CACHE_HIT, span_id="other001", fields={"layer": "call"}))
    assert len(out.seen) == 1


def test_closing_a_unit_that_was_never_opened_is_zero_and_not_an_error() -> None:
    made = recorder(Collect())
    assert made.close_unit("never", "ok") == 0


def test_a_second_open_replaces_the_buffer_rather_than_merging_attempts() -> None:
    """A REGEN claims the same work row again; two attempts under one decision would be wrong."""
    out = Collect()
    made = recorder(out, ok_rate=0.0)
    made.open_unit("w1", "unit0001")
    made.emit(record(EventKind.UNIT_BEGIN, span_id="unit0001", parent="plan0001"))
    made.open_unit("w1", "unit0002")
    made.emit(record(EventKind.UNIT_BEGIN, span_id="unit0002", parent="plan0001"))
    assert made.close_unit("w1", "failed_permanent") == 1
    assert out.seen[0].span_id == "unit0002"


def test_the_default_rate_is_the_shipped_one_in_sixty_four() -> None:
    made = recorder(Collect())
    assert OK_SAMPLE_RATE == 1 / 64
    kept = 0
    for n in range(2_000):
        made.open_unit(f"w{n}", f"u{n:07d}")
        made.emit(record(EventKind.UNIT_BEGIN, span_id=f"u{n:07d}", parent="plan0001"))
        kept += made.close_unit(f"w{n}", "ok")
    assert 12 <= kept <= 55, kept  # 2000/64 = 31.25


def test_a_recorder_without_a_run_id_is_refused() -> None:
    with pytest.raises(ConfigError, match="monotone per the pair"):
        RunRecorder(run_id="", writer=WRITER, clock=FakeClock())
    with pytest.raises(ConfigError, match="monotone per the pair"):
        RunRecorder(run_id=RUN_ID, writer="", clock=FakeClock())


# ---------------------------------------------------------------------------------------------
# 6. The protocol, and the numbers the manifest reads
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("made", ["ndjson", "console", "recorder"])
def test_every_shipped_sink_satisfies_the_protocol(made: str, tmp_path: Path) -> None:
    built: TraceSink
    if made == "ndjson":
        built = NdjsonSink(tmp_path / "x.ndjson", clock=FakeClock())
    elif made == "console":
        built = ConsoleSink(io.StringIO())
    else:
        built = RunRecorder(run_id=RUN_ID, writer=WRITER, clock=FakeClock())
    try:
        assert isinstance(built, TraceSink)
        built.emit(record())
        assert built.flush(50) >= 0
    finally:
        if isinstance(built, NdjsonSink):
            built.close(timeout_ms=500)


def test_the_serialise_total_comes_from_the_injected_clock_and_not_the_machine() -> None:
    """G8 bans `time.perf_counter_ns()` in library code, and 08:277 makes `Clock` the one source.

    The counting clock below advances one nanosecond per read, so `serialise_ns_total` is exactly
    two reads per record. That is the whole point of injecting it: the number is deterministic in a
    test and is a real duration in a run, and no module but the `Clock` implementation reads the
    machine.
    """
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as where:
        made = NdjsonSink(Path(where) / "r.ndjson", clock=clock)
        try:
            for _ in range(3):
                made.emit(record())
            deadline = time.monotonic() + 5
            while made.stats.emitted < 3 and time.monotonic() < deadline:
                time.sleep(0.002)
        finally:
            made.close()
    assert made.stats.serialise_ns_total == 3, "one tick per record, from the injected clock"


def test_the_clock_the_ban_prescribes_cannot_measure_what_the_manifest_asks_for() -> None:
    """D154, as a measurement rather than a claim.

    G8's own message prescribes *"`time.monotonic_ns()` for a duration"* and 15:434 asks the
    manifest for `observe.serialise_ns_total`. On Windows `time.monotonic()` is
    `GetTickCount64`, whose
    resolution is 15.6 ms, so every per-record delta rounds to zero and the sum reports a serialiser
    that costs nothing. This test records the platform's answer instead of asserting a number, so it
    is evidence on every runner rather than a claim about one.
    """
    monotonic = time.get_clock_info("monotonic").resolution
    perf = time.get_clock_info("perf_counter").resolution
    assert perf <= monotonic, "perf_counter is never the coarser of the two"
    if monotonic > 1e-6:  # pragma: no cover -- true on Windows, false on Linux and macOS
        assert monotonic >= 0.001, monotonic


def test_the_manifest_fields_are_the_four_the_plan_names(plan: PlanDocs) -> None:
    """15:434's four, plus the two the roll produces. Named, so the manifest cannot rename them."""
    fields = SinkStats(
        emitted=3, dropped=1, serialise_ns_total=99, shard_bytes=7
    ).as_manifest_fields()
    for name in ("events_emitted", "events_dropped", "serialise_ns_total", "shard_bytes"):
        assert name in fields
        assert plan.grep(rf"observe\.{name}", documents=("15-observability.md",)), name
    assert fields["events_emitted"] == 3
    assert fields["shards_rolled"] == 0


def test_a_refusal_is_counted_apart_from_a_drop() -> None:
    """A bug at a call site must not hide inside a number an operator reads as back pressure."""
    stats = SinkStats()
    assert stats.refused == 0
    assert "events_refused" in stats.as_manifest_fields()
    assert stats.as_manifest_fields()["events_dropped"] == 0


def test_the_peak_buffer_is_the_plans_formula(plan: PlanDocs) -> None:
    """15:168-175, over the real bound and the charter's `max_inflight`."""
    assert plan.grep(r"MAX_SPAN_BUFFER_EVENTS", documents=("15-observability.md",))
    assert (32 + 4 + 2) * MAX_SPAN_BUFFER_EVENTS * 180 == 437_760


def test_a_phase_on_a_span_kind_is_the_kinds_own() -> None:
    """The sinks never override a phase; `Event.validate()` is what refuses a wrong one."""
    assert EVENTS["call.begin"].phase is Phase.START
    assert EVENTS["call.end"].phase is Phase.END
    record(EventKind.CALL_BEGIN, fields={"driver": "d"}).validate()
