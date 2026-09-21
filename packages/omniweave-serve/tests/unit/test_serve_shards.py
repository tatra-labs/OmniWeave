"""The reader, over shards written by the sink that actually writes them.

**The fixtures come from `NdjsonSink`, not from hand-written JSON.** A reader tested against lines
a test composed is a reader tested against the test's idea of the format; these tests roll a real
sink at a small `shard_bytes`, so the `.gz` archives, the `shard.roll` closing line and the live
file are the ones a run produces. That is what turned D362 from a reading of two documents into a
property a test can hold.

**Nothing here sleeps.** `Tail.drain()` reads what is there now, so a follower crossing a roll is a
sequence of appends and two calls rather than a race and a timeout.
"""

from __future__ import annotations

import ast
import gzip
import json
import sys
from pathlib import Path
from typing import Any

import omniweave_serve.shards as shards_module
import pytest
from omniweave_core.clock import Clock
from omniweave_core.errors import ConfigError
from omniweave_core.events import (
    SHARD_ORDINAL_DIGITS,
    Event,
    EventKind,
    NdjsonSink,
    serialise,
    shard_path,
)
from omniweave_serve.shards import (
    GZ_SUFFIX,
    LIVE_ORDINAL,
    LIVE_SUFFIX,
    Position,
    Tail,
    continues_at,
    read_shard,
    shard_of,
    shards_for,
    walk,
)

RUN = "r_01J0000000000000000000000"
TRACE = "0af7651916cd43dd8448eb211c80319c"


class Ticking:
    """A `Clock` that advances one millisecond per reading. Two lines, which is the point of it."""

    def __init__(self) -> None:
        self._ns = 1_700_000_000_000_000_000

    def wall_ns(self) -> int:
        self._ns += 1_000_000
        return self._ns

    def monotonic_ns(self) -> int:
        return self._ns


def _event(index: int, kind: str = EventKind.CACHE_HIT) -> Event:
    values: dict[str, Any] = {
        "ts_wall_ns": 1_700_000_000_000_000_000 + index,
        "ts_mono_ns": 5_000_000_000 + index,
        "run_id": RUN,
        "writer_id": "abc123abc123",
        "seq": index,
        "trace_id": TRACE,
        "span_id": f"{index:016x}",
        "parent_span_id": None,
        "kind": kind,
        "phase": "point",
        "level": "info",
        "fields": {"layer": "call"},
    }
    return Event(**values)


def _write(path: Path, events: list[Event]) -> None:
    """One shard, written the way the sink writes: one serialised record per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for event in events:
            handle.write(serialise(event))


def _gzip(path: Path, events: list[Event]) -> None:
    with gzip.open(path, "wb") as handle:
        for event in events:
            handle.write(serialise(event))


def _live(tmp_path: Path) -> Path:
    return tmp_path / f"{RUN}{LIVE_SUFFIX}"


def _rolled_run(tmp_path: Path, *, records: int, shard_bytes: int) -> Path:
    """A real `NdjsonSink` rolled by volume, so the fixtures are what a run leaves behind."""
    live = _live(tmp_path)
    sink = NdjsonSink(live, clock=Ticking(), shard_bytes=shard_bytes)
    try:
        for index in range(records):
            sink.emit(_event(index))
    finally:
        sink.close()
    return live


# ---------------------------------------------------------------------------------------------
# Classifying a file
# ---------------------------------------------------------------------------------------------


def test_a_live_shard_has_no_ordinal() -> None:
    shard = shard_of(Path(f"/x/{RUN}{LIVE_SUFFIX}"))
    assert shard.ordinal == LIVE_ORDINAL
    assert shard.compressed is False
    assert shard.name == f"{RUN}{LIVE_SUFFIX}"


def test_a_rolled_shard_carries_the_ordinal_the_writer_gave_it() -> None:
    rolled = shard_path(Path(f"/x/{RUN}{LIVE_SUFFIX}"), 7)
    shard = shard_of(rolled)
    assert shard.ordinal == 7
    assert shard.compressed is True
    assert shard.name.endswith(GZ_SUFFIX)


def test_the_ordinal_width_is_the_writers() -> None:
    """Read off `SHARD_ORDINAL_DIGITS` rather than transcribed, so a widening moves both sides."""
    rolled = shard_path(Path(f"/x/{RUN}{LIVE_SUFFIX}"), 3)
    digits = rolled.name.removesuffix(GZ_SUFFIX).rsplit(".", 1)[1]
    assert len(digits) == SHARD_ORDINAL_DIGITS
    assert shard_of(rolled).ordinal == 3


@pytest.mark.parametrize("name", ["notes.txt", f"{RUN}.ndjson.gz", f"{RUN}.12.ndjson.gz"])
def test_a_name_of_neither_shape_is_treated_as_live(name: str) -> None:
    """`[observe] ndjson_path` is a template an operator may set to anything, so an unrecognised
    name is far likelier to be a legal configuration than a corruption."""
    assert shard_of(Path("/x") / name).ordinal == LIVE_ORDINAL


def test_rolled_shards_sort_by_ordinal() -> None:
    live = Path(f"/x/{RUN}{LIVE_SUFFIX}")
    shards = [shard_of(shard_path(live, n)) for n in (3, 1, 2)]
    assert [shard.ordinal for shard in sorted(shards)] == [1, 2, 3]


# ---------------------------------------------------------------------------------------------
# Finding a run's shards
# ---------------------------------------------------------------------------------------------


def test_the_live_shard_comes_last_because_it_is_newest(tmp_path: Path) -> None:
    live = _live(tmp_path)
    _write(live, [_event(9)])
    for ordinal in (2, 1):
        _gzip(shard_path(live, ordinal), [_event(ordinal)])
    found = shards_for(tmp_path, live)
    assert [shard.ordinal for shard in found] == [1, 2, LIVE_ORDINAL]
    assert found[-1].name == live.name


def test_another_runs_shards_are_not_this_runs(tmp_path: Path) -> None:
    live = _live(tmp_path)
    _write(live, [_event(1)])
    _gzip(shard_path(live, 1), [_event(2)])
    other = tmp_path / f"r_other{LIVE_SUFFIX}"
    _write(other, [_event(3)])
    _gzip(shard_path(other, 1), [_event(4)])
    assert {shard.name for shard in shards_for(tmp_path, live)} == {
        live.name,
        shard_path(live, 1).name,
    }


def test_a_run_with_no_live_shard_is_its_archives(tmp_path: Path) -> None:
    """`ow trace prune` can remove the live shard of a finished run and leave the archives."""
    live = _live(tmp_path)
    _gzip(shard_path(live, 1), [_event(1)])
    assert [shard.ordinal for shard in shards_for(tmp_path, live)] == [1]


def test_a_missing_directory_is_no_shards_and_not_an_error(tmp_path: Path) -> None:
    """A run that emitted nothing is a run with no shards, which an export reports as zero spans."""
    assert shards_for(tmp_path / "absent", tmp_path / "absent" / f"{RUN}{LIVE_SUFFIX}") == ()


# ---------------------------------------------------------------------------------------------
# Reading one shard
# ---------------------------------------------------------------------------------------------


def test_every_record_comes_back_with_the_offset_after_it(tmp_path: Path) -> None:
    """The offset AFTER, because a cursor holding the position of a record already sent would
    re-send it on every resume, and re-sending forever is not a harmless duplicate."""
    live = _live(tmp_path)
    events = [_event(index) for index in range(3)]
    _write(live, events)
    read = list(read_shard(shard_of(live)))
    assert [event.seq for _, event in read] == [0, 1, 2]
    running = 0
    for (position, _), event in zip(read, events, strict=True):
        running += len(serialise(event))
        assert position == Position(shard=live.name, offset=running)
    assert running == live.stat().st_size


def test_a_read_resumes_at_an_offset_and_re_reads_nothing(tmp_path: Path) -> None:
    live = _live(tmp_path)
    events = [_event(index) for index in range(4)]
    _write(live, events)
    first = len(serialise(events[0])) + len(serialise(events[1]))
    assert [event.seq for _, event in read_shard(shard_of(live), start=first)] == [2, 3]


def test_a_gz_archive_reads_the_same_way_as_a_live_shard(tmp_path: Path) -> None:
    """The offset counts UNCOMPRESSED bytes, which is what `shard.roll`'s `bytes` field counts,
    so a roll record and a reader's offset are in the same units."""
    live = _live(tmp_path)
    events = [_event(index) for index in range(3)]
    archive = shard_path(live, 1)
    _gzip(archive, events)
    read = list(read_shard(shard_of(archive)))
    assert [event.seq for _, event in read] == [0, 1, 2]
    assert read[-1][0].offset == sum(len(serialise(event)) for event in events)


def test_a_line_that_is_not_a_record_advances_the_offset_and_yields_nothing(
    tmp_path: Path,
) -> None:
    """The bytes were consumed either way, and 15:390 says a read never repairs."""
    live = _live(tmp_path)
    good = serialise(_event(1))
    with live.open("wb") as handle:
        handle.write(b'{"not": "a record"}\n')
        handle.write(b"\n")
        handle.write(good)
    read = list(read_shard(shard_of(live)))
    assert len(read) == 1
    assert read[0][0].offset == live.stat().st_size


def test_a_trailing_fragment_is_left_where_it_is(tmp_path: Path) -> None:
    """15:390's *"a partial final line is skipped on read, never repaired"*, plus the half this
    module owns: the offset stops IN FRONT of it, so the record arrives once the writer finishes
    the line rather than being skipped forever."""
    live = _live(tmp_path)
    complete = serialise(_event(1))
    with live.open("wb") as handle:
        handle.write(complete)
        handle.write(serialise(_event(2))[:20])
    read = list(read_shard(shard_of(live)))
    assert [event.seq for _, event in read] == [1]
    assert read[0][0].offset == len(complete), "in front of the fragment, not past it"


def test_finishing_the_fragment_makes_the_record_readable(tmp_path: Path) -> None:
    """The property the offset rule exists for, driven end to end."""
    live = _live(tmp_path)
    first, second = serialise(_event(1)), serialise(_event(2))
    with live.open("wb") as handle:
        handle.write(first)
        handle.write(second[:20])
    stopped = list(read_shard(shard_of(live)))[-1][0]
    with live.open("r+b") as handle:
        handle.seek(len(first))
        handle.write(second)
    assert [event.seq for _, event in read_shard(shard_of(live), start=stopped.offset)] == [2]


def test_an_empty_shard_reads_nothing(tmp_path: Path) -> None:
    live = _live(tmp_path)
    _write(live, [])
    assert list(read_shard(shard_of(live))) == []


# ---------------------------------------------------------------------------------------------
# Walking a run
# ---------------------------------------------------------------------------------------------


def _walked(tmp_path: Path, resume: Position | None = None) -> list[int]:
    live = _live(tmp_path)
    return [event.seq for _, event in walk(shards_for(tmp_path, live), resume=resume)]


def test_a_walk_crosses_every_shard_in_order(tmp_path: Path) -> None:
    live = _live(tmp_path)
    _gzip(shard_path(live, 1), [_event(1), _event(2)])
    _gzip(shard_path(live, 2), [_event(3)])
    _write(live, [_event(4)])
    assert _walked(tmp_path) == [1, 2, 3, 4]


def test_a_walk_resumes_inside_an_archive_and_continues_past_it(tmp_path: Path) -> None:
    live = _live(tmp_path)
    first, second = _event(1), _event(2)
    archive = shard_path(live, 1)
    _gzip(archive, [first, second])
    _write(live, [_event(3)])
    resume = Position(shard=archive.name, offset=len(serialise(first)))
    assert _walked(tmp_path, resume) == [2, 3]


def test_a_walk_resuming_at_the_end_of_an_archive_yields_only_what_follows(
    tmp_path: Path,
) -> None:
    live = _live(tmp_path)
    archive = shard_path(live, 1)
    _gzip(archive, [_event(1), _event(2)])
    _write(live, [_event(3)])
    end = sum(len(serialise(_event(index))) for index in (1, 2))
    assert _walked(tmp_path, Position(shard=archive.name, offset=end)) == [3]


def test_a_resume_naming_a_pruned_shard_re_reads_everything(tmp_path: Path) -> None:
    """`ow trace prune` unlinks on a fourteen-day cycle. Re-sending is what 15:255 makes safe;
    skipping is what nothing makes safe."""
    live = _live(tmp_path)
    _gzip(shard_path(live, 2), [_event(5)])
    _write(live, [_event(6)])
    gone = Position(shard=shard_path(live, 1).name, offset=99)
    assert _walked(tmp_path, gone) == [5, 6]


def test_walking_no_shards_yields_nothing(tmp_path: Path) -> None:
    assert _walked(tmp_path) == []


# ---------------------------------------------------------------------------------------------
# The roll, and the field the plan gets backwards
# ---------------------------------------------------------------------------------------------


def test_a_real_sink_roll_names_the_archive_in_successor_and_the_live_path_in_closed(
    tmp_path: Path,
) -> None:
    """D362, asserted against the writer rather than against a reading of the prose.

    15:273 says the roll record carries *"the new shard's name"* and that a follower *"opens the
    named successor"*; 15:274 says it *"never re-reads a `.gz`"*. Both cannot hold, and this is
    which way round the shipped writer has it.
    """
    live = _rolled_run(tmp_path, records=40, shard_bytes=600)
    archive = shard_path(live, 1)
    assert archive.is_file(), "the sink rolled at all"
    rolls = [
        event
        for _, event in read_shard(shard_of(archive))
        if event.kind == EventKind.SHARD_ROLL.value
    ]
    assert len(rolls) == 1
    roll = rolls[0]
    assert roll.fields["successor"] == archive.name, "the ARCHIVE of what closed"
    assert str(roll.fields["successor"]).endswith(GZ_SUFFIX)
    assert roll.fields["closed"] == live.name, "the path the stream CONTINUES at"


def test_continues_at_reads_closed_and_never_successor(tmp_path: Path) -> None:
    """A follower that opened `successor` would open a gzip file as text."""
    live = _rolled_run(tmp_path, records=40, shard_bytes=600)
    archive = shard_path(live, 1)
    roll = next(
        event
        for _, event in read_shard(shard_of(archive))
        if event.kind == EventKind.SHARD_ROLL.value
    )
    assert continues_at(roll) == live.name
    assert continues_at(roll) != roll.fields["successor"]
    assert not str(continues_at(roll)).endswith(GZ_SUFFIX)


def test_continues_at_is_none_for_every_other_record() -> None:
    assert continues_at(_event(1)) is None


def test_a_roll_record_with_no_closed_field_names_nothing() -> None:
    """A record from a future writer that dropped the field is `None`, not a crash: a follower
    that stopped is recoverable and one that opened `Path(None)` is not."""
    roll = Event(
        ts_wall_ns=1,
        ts_mono_ns=1,
        run_id=RUN,
        writer_id="abc123abc123",
        seq=1,
        trace_id=TRACE,
        span_id="0" * 16,
        parent_span_id=None,
        kind=EventKind.SHARD_ROLL,
        phase="point",
        level="notice",
        fields={"successor": "x.gz"},
    )
    assert continues_at(roll) is None


# ---------------------------------------------------------------------------------------------
# Following
# ---------------------------------------------------------------------------------------------


def _append(path: Path, events: list[Event]) -> None:
    with path.open("ab") as handle:
        for event in events:
            handle.write(serialise(event))


def test_a_follower_drains_what_is_there_and_returns(tmp_path: Path) -> None:
    live = _live(tmp_path)
    _write(live, [_event(1)])
    with Tail(shard_of(live)) as tail:
        assert [event.seq for _, event in tail.drain()] == [1]
        assert [event.seq for _, event in tail.drain()] == [], "nothing new yet"
        _append(live, [_event(2), _event(3)])
        assert [event.seq for _, event in tail.drain()] == [2, 3]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows refuses to rename a file another handle holds open, which is the very "
    "situation this asserts a follower survives on POSIX",
)
def test_a_follower_holds_the_handle_and_not_the_path(tmp_path: Path) -> None:
    """15:272. The writer unlinks the live file at every roll, so a follower that reopened by
    path between two reads would race the unlink and read a new file as though it continued the
    old one."""
    live = _live(tmp_path)
    _write(live, [_event(1)])
    with Tail(shard_of(live)) as tail:
        list(tail.drain())
        _append(live, [_event(2)])
        live.replace(tmp_path / "moved.ndjson")
        assert [event.seq for _, event in tail.drain()] == [2], "read through the rename"


def test_a_follower_stops_in_front_of_a_fragment_and_picks_it_up_later(tmp_path: Path) -> None:
    live = _live(tmp_path)
    _write(live, [_event(1)])
    second = serialise(_event(2))
    with Tail(shard_of(live)) as tail:
        list(tail.drain())
        with live.open("ab") as handle:
            handle.write(second[:15])
        assert list(tail.drain()) == []
        with live.open("ab") as handle:
            handle.write(second[15:])
        assert [event.seq for _, event in tail.drain()] == [2]


def _roll_record(tmp_path: Path) -> tuple[Path, Event]:
    """A real `shard.roll`, taken out of a real sink's archive.

    The RECORD is authentic and the file it is replayed into is not: a follower reads the live
    shard, and the live shard's closing roll line only exists for the instant before the sink
    gzips it. So the record is lifted and written into a plain file, which is what the follower
    would have been reading at that instant.
    """
    live = _rolled_run(tmp_path, records=40, shard_bytes=600)
    archive = shard_path(live, 1)
    roll = next(
        event
        for _, event in read_shard(shard_of(archive))
        if event.kind == EventKind.SHARD_ROLL.value
    )
    return live, roll


def test_a_follower_stops_at_a_roll_and_names_where_to_continue(tmp_path: Path) -> None:
    """The whole `--follow` mechanism: read to the roll, stop, and be told what to open."""
    live, roll = _roll_record(tmp_path)
    following = tmp_path / "following.ndjson"
    _write(following, [_event(1), _event(2), roll])
    with Tail(shard_of(following)) as tail:
        drained = [event.kind for _, event in tail.drain()]
        assert drained == [EventKind.CACHE_HIT.value] * 2, "the roll is consumed, not yielded"
        assert tail.rolled == live.name, "the live path, never the .gz"
        assert list(tail.drain()) == [], "a closed follower yields nothing rather than spinning"


def test_a_follower_consumes_the_roll_record_before_it_stops(tmp_path: Path) -> None:
    """The position includes the roll line, so a cursor committed here does not re-read it."""
    _, roll = _roll_record(tmp_path)
    following = tmp_path / "following.ndjson"
    _write(following, [_event(1), roll])
    with Tail(shard_of(following)) as tail:
        list(tail.drain())
        assert tail.position.offset == following.stat().st_size


def test_records_after_a_roll_in_one_file_are_not_read(tmp_path: Path) -> None:
    """A roll ends a shard. Anything the test writes after it is not part of that shard, and a
    follower that kept reading would be reading the next shard through the wrong handle."""
    _, roll = _roll_record(tmp_path)
    following = tmp_path / "following.ndjson"
    _write(following, [_event(1), roll, _event(9)])
    with Tail(shard_of(following)) as tail:
        assert [event.seq for _, event in tail.drain()] == [1]


def test_a_follower_refuses_a_rolled_shard(tmp_path: Path) -> None:
    """15:274: it *"never re-reads a `.gz`"*, and a follower pointed at one is a caller error."""
    live = _live(tmp_path)
    archive = shard_path(live, 1)
    _gzip(archive, [_event(1)])
    with pytest.raises(ConfigError, match=r"never re-reads a \.gz"):
        Tail(shard_of(archive))


def test_a_follower_reports_its_position(tmp_path: Path) -> None:
    live = _live(tmp_path)
    events = [_event(1), _event(2)]
    _write(live, events)
    with Tail(shard_of(live)) as tail:
        list(tail.drain())
        assert tail.position == Position(
            shard=live.name, offset=sum(len(serialise(event)) for event in events)
        )


def test_a_follower_starts_at_an_offset(tmp_path: Path) -> None:
    live = _live(tmp_path)
    first = _event(1)
    _write(live, [first, _event(2)])
    with Tail(shard_of(live), start=len(serialise(first))) as tail:
        assert [event.seq for _, event in tail.drain()] == [2]


def test_closing_twice_is_fine(tmp_path: Path) -> None:
    """A roll closes the handle and so does the caller."""
    live = _live(tmp_path)
    _write(live, [_event(1)])
    tail = Tail(shard_of(live))
    tail.close()
    tail.close()
    assert list(tail.drain()) == []


# ---------------------------------------------------------------------------------------------
# End to end against a rolled run
# ---------------------------------------------------------------------------------------------


def test_a_rolled_run_walks_every_record_it_wrote(tmp_path: Path) -> None:
    """The integration the rest of this file is made of: a real sink, a real roll, and a walk
    that reads both sides of it."""
    live = _rolled_run(tmp_path, records=60, shard_bytes=600)
    found = shards_for(tmp_path, live)
    assert len(found) > 1, "the sink rolled"
    records = [event for _, event in walk(found)]
    cache_hits = [event for event in records if event.kind == EventKind.CACHE_HIT.value]
    assert len(cache_hits) == 60
    assert [event.seq for event in cache_hits] == list(range(60))


def test_a_resume_across_a_roll_loses_nothing_and_repeats_nothing(tmp_path: Path) -> None:
    """Split a rolled run at its midpoint, walk each half, and demand the two halves are the
    whole: exactly the arithmetic a stopped export and its re-run perform."""
    live = _rolled_run(tmp_path, records=60, shard_bytes=600)
    found = shards_for(tmp_path, live)
    everything = list(walk(found))
    assert len(found) > 1, "the sink rolled, so the split really does cross a shard boundary"

    halfway = everything[len(everything) // 2][0]
    before: list[int] = []
    for position, event in everything:
        before.append(event.seq)
        if position == halfway:
            break
    after = [event.seq for _, event in walk(found, resume=halfway)]

    assert before + after == [event.seq for _, event in everything]
    assert len(set(before) & set(after)) == 0, "nothing is sent twice"


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def test_the_reader_holds_no_clock_and_no_loop() -> None:
    tree = ast.parse(Path(shards_module.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"asyncio", "time", "threading", "urllib", "socket"})
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith)
    ]


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    tree = ast.parse(Path(shards_module.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(shards_module.__all__)


def test_the_clock_protocol_is_satisfied_by_the_fixture() -> None:
    """The fixture above is a `Clock` because the sink demands one; asserted so a Protocol change
    fails here rather than in a confusing sink error."""
    assert isinstance(Ticking(), Clock)


def test_the_fixtures_are_the_writers_own_bytes() -> None:
    """A guard against this file drifting into hand-composed fixtures: every shard above is
    written with `serialise`, which is the function the sink writes with, so a change to the
    record encoding moves both sides at once."""
    assert json.loads(serialise(_event(1)).decode("utf-8"))["seq"] == 1
