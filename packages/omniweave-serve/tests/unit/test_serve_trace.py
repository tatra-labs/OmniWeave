"""The join: read, pair, batch, send, and commit only what is safe to commit.

**The assertions here are about the seam and not about the parts.** Pairing is `test_serve_otlp`'s,
the ladder is `test_serve_export`'s, offsets are `test_serve_shards`'. What only exists once the
four are joined is the rule that a cursor cannot advance past an open span, and its consequence:
a live run pins the cursor at the `run` span, forever, by construction.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave_serve.export as export_module
import omniweave_serve.trace as trace_module
import pytest
from omniweave_core.events import Event, EventKind, serialise
from omniweave_serve.export import Delivered, Exporter, Halted, Response, cursor_path, read_cursor
from omniweave_serve.otlp import Resource
from omniweave_serve.shards import Position, Tail, shard_of, shards_for
from omniweave_serve.trace import (
    Carried,
    Selection,
    Step,
    export_once,
    follow,
    safe_position,
    send,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

RUN = "r_01J0000000000000000000000"
TRACE = "0af7651916cd43dd8448eb211c80319c"
ENDPOINT = "https://collector.internal:4318"
URL = f"{ENDPOINT}/v1/traces"
LIVE = f"{RUN}.ndjson"
ARCHIVE = f"{RUN}.0001.ndjson.gz"


@dataclass
class Recorder:
    """A `Transport` that answers from a script and keeps every call."""

    answers: list[Response] = field(default_factory=list)
    calls: list[tuple[str, bytes, dict[str, str]]] = field(default_factory=list)
    default: Response = field(default_factory=lambda: Response(200, "OK"))

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> Response:
        self.calls.append((url, body, dict(headers)))
        return self.answers.pop(0) if self.answers else self.default


def _exporter(recorder: Recorder | None = None) -> Exporter:
    return Exporter(transport=recorder or Recorder(), sleep=lambda _seconds: None)


def _resource() -> Resource:
    return Resource(config_digest="3b8a1f4c" * 8)


def _event(index: int, kind: str = EventKind.CACHE_HIT, *, span: str | None = None) -> Event:
    """One record of `kind`, with the phase and level its row declares."""
    values: dict[str, Any] = {
        "ts_wall_ns": 1_700_000_000_000_000_000 + index * 1_000_000,
        "ts_mono_ns": 5_000_000_000 + index * 1_000_000,
        "run_id": RUN,
        "writer_id": "abc123abc123",
        "seq": index,
        "trace_id": TRACE,
        "span_id": span or f"{index:016x}",
        "parent_span_id": None,
        "kind": kind,
        "phase": "point",
        "level": "info",
        "fields": {"layer": "call"} if kind == EventKind.CACHE_HIT else {},
    }
    probe = Event(**values).spec()
    if probe.span is not None:
        values["phase"] = probe.phase.value
    values["level"] = probe.level.value
    if kind == EventKind.RUN_START:
        values["fields"] = {"trigger": "cli"}
    elif kind == EventKind.RUN_END:
        values["fields"] = {"status": "ok"}
    elif kind == EventKind.UNIT_BEGIN:
        values["fields"] = {}
    elif kind == EventKind.UNIT_COMPLETE:
        values["fields"] = {"outcome": "ok"}
    return Event(**values)


def _at(offset: int, shard: str = LIVE) -> Position:
    return Position(shard=shard, offset=offset)


def _records(events: list[Event], shard: str = LIVE) -> list[tuple[Position, Event]]:
    """`(position, event)` pairs with the offsets the reader would have produced."""
    out: list[tuple[Position, Event]] = []
    running = 0
    for event in events:
        running += len(serialise(event))
        out.append((Position(shard=shard, offset=running), event))
    return out


def _write(path: Path, events: list[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for event in events:
            handle.write(serialise(event))


def _span_pair(span_id: str, *, begin: int, end: int) -> list[Event]:
    return [
        _event(begin, EventKind.UNIT_BEGIN, span=span_id),
        _event(end, EventKind.UNIT_COMPLETE, span=span_id),
    ]


# ---------------------------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------------------------


def test_no_since_keeps_everything() -> None:
    selection = Selection(live=Path(LIVE))
    assert all(selection.keeps(_event(index)) for index in range(5))


def test_since_is_compared_on_the_wall_clock() -> None:
    """A window is a human's question, and `ts_mono_ns` is not comparable across processes."""
    early, late = _event(1), _event(9)
    selection = Selection(live=Path(LIVE), since_wall_ns=late.ts_wall_ns)
    assert selection.keeps(early) is False
    assert selection.keeps(late) is True


def test_since_is_inclusive_at_its_own_instant() -> None:
    event = _event(4)
    assert Selection(live=Path(LIVE), since_wall_ns=event.ts_wall_ns).keeps(event) is True


# ---------------------------------------------------------------------------------------------
# The rule this module exists for
# ---------------------------------------------------------------------------------------------


def test_with_nothing_open_the_cursor_reaches_what_was_read() -> None:
    assert safe_position(_at(4096), (), order=[LIVE]) == _at(4096)


def test_an_open_span_holds_the_cursor_at_its_start() -> None:
    """A resume from past it would read the `end` alone, and an end with no start is no span."""
    held = Carried(position=_at(100), event=_event(1, EventKind.UNIT_BEGIN))
    assert safe_position(_at(9000), [held], order=[LIVE]) == _at(100)


def test_the_earliest_open_span_wins() -> None:
    first = Carried(position=_at(100), event=_event(1, EventKind.UNIT_BEGIN))
    second = Carried(position=_at(500), event=_event(2, EventKind.UNIT_BEGIN))
    assert safe_position(_at(9000), [second, first], order=[LIVE]) == _at(100)


def test_positions_in_two_shards_are_ranked_by_the_shard_order() -> None:
    """`{run}.0001.ndjson.gz` byte 900 is before `{run}.ndjson` byte 20, and no property of
    either position says so."""
    held = Carried(position=_at(900, ARCHIVE), event=_event(1, EventKind.UNIT_BEGIN))
    assert safe_position(_at(20), [held], order=[ARCHIVE, LIVE]) == _at(900, ARCHIVE)


def test_a_shard_missing_from_the_order_sorts_first() -> None:
    """The conservative way to be wrong: it can only hold the cursor back."""
    held = Carried(position=_at(900, "pruned.ndjson"), event=_event(1, EventKind.UNIT_BEGIN))
    assert safe_position(_at(20), [held], order=[LIVE]) == _at(900, "pruned.ndjson")


def test_nothing_read_and_nothing_open_is_no_position() -> None:
    assert safe_position(None, (), order=[LIVE]) is None


def test_nothing_read_but_something_open_is_that_something() -> None:
    held = Carried(position=_at(7), event=_event(1, EventKind.UNIT_BEGIN))
    assert safe_position(None, [held], order=[LIVE]) == _at(7)


# ---------------------------------------------------------------------------------------------
# Sending one window
# ---------------------------------------------------------------------------------------------


def _send(records: list[tuple[Position, Event]], **over: object) -> Step:
    settings: dict[str, Any] = {"url": URL, "order": [LIVE]}
    settings.update(over)
    return send(_exporter(), _resource(), records, **settings)


def test_a_closed_span_is_sent_and_the_cursor_reaches_the_end() -> None:
    records = _records(_span_pair("a" * 16, begin=1, end=2))
    step = _send(records)
    assert step.spans == 1
    assert step.safe == records[-1][0]
    assert step.carried == ()
    assert step.pinned_by == ""
    assert not step.halted()


def test_an_open_span_is_carried_and_names_what_pinned_the_cursor() -> None:
    begin = _event(1, EventKind.UNIT_BEGIN, span="a" * 16)
    records = _records([begin, _event(2)])
    step = _send(records)
    assert step.spans == 0, "a span with no end is not a span"
    assert [held.event.kind for held in step.carried] == [EventKind.UNIT_BEGIN.value]
    assert step.safe == records[0][0], "pinned at the start, not at what was read"
    assert step.pinned_by == EventKind.UNIT_BEGIN.value


def test_a_carried_start_pairs_with_an_end_in_the_next_window() -> None:
    """The whole reason a start is carried: `pair()` is order-sensitive and the start still
    precedes its end once it is put back at the front."""
    begin = _event(1, EventKind.UNIT_BEGIN, span="a" * 16)
    first = _send(_records([begin]))
    assert first.spans == 0

    end = _event(2, EventKind.UNIT_COMPLETE, span="a" * 16)
    second = _send(_records([end]), carried=first.carried)
    assert second.spans == 1
    assert second.carried == ()
    assert second.pinned_by == ""


def test_an_end_with_no_start_is_counted_and_never_becomes_a_span() -> None:
    step = _send(_records([_event(2, EventKind.UNIT_COMPLETE, span="a" * 16)]))
    assert step.spans == 0
    assert step.orphaned == 1


def test_records_outside_the_window_never_reach_the_sender() -> None:
    recorder = Recorder()
    step = send(_exporter(recorder), _resource(), [], url=URL, order=[LIVE])
    assert recorder.calls == []
    assert step.safe is None
    assert isinstance(step.result, Delivered)
    assert step.result.requests == 0


def test_a_halted_send_reports_it_and_keeps_the_previous_position() -> None:
    recorder = Recorder(default=Response(503, "Unavailable"))
    records = _records(_span_pair("a" * 16, begin=1, end=2))
    step = send(
        _exporter(recorder),
        _resource(),
        records,
        url=URL,
        order=[LIVE],
        committed=_at(11),
    )
    assert step.halted()
    assert isinstance(step.result, Halted)
    assert step.result.position == _at(11)


# ---------------------------------------------------------------------------------------------
# The consequence on a live run
# ---------------------------------------------------------------------------------------------


def test_a_live_run_pins_the_cursor_at_the_run_span() -> None:
    """D370, which is the finding this cell exists to have made.

    A `run` span opens with the first record and closes with the last, so while a run is in
    flight the earliest open span is at the top of the shard and the cursor cannot advance at all.
    """
    events = [
        _event(1, EventKind.RUN_START, span="f" * 16),
        *_span_pair("a" * 16, begin=2, end=3),
        *_span_pair("b" * 16, begin=4, end=5),
    ]
    records = _records(events)
    step = _send(records)
    assert step.spans == 2, "the two unit spans are sent"
    assert step.pinned_by == EventKind.RUN_START.value
    assert step.safe == records[0][0], "the cursor is at the run span's start record"


def test_the_run_span_releases_the_cursor_when_the_run_ends() -> None:
    """And the other half: once `run.end` arrives the cursor jumps to the end of what was read."""
    events = [
        _event(1, EventKind.RUN_START, span="f" * 16),
        *_span_pair("a" * 16, begin=2, end=3),
        _event(9, EventKind.RUN_END, span="f" * 16),
    ]
    records = _records(events)
    step = _send(records)
    assert step.spans == 2
    assert step.carried == ()
    assert step.safe == records[-1][0]


# ---------------------------------------------------------------------------------------------
# One pass over a run
# ---------------------------------------------------------------------------------------------


def test_a_one_shot_export_reads_every_shard_and_sends_the_spans(tmp_path: Path) -> None:
    live = tmp_path / LIVE
    _write(
        live, [_event(1, EventKind.RUN_START, span="f" * 16), *_span_pair("a" * 16, begin=2, end=3)]
    )
    recorder = Recorder()
    step = export_once(
        _exporter(recorder),
        _resource(),
        Selection(live=live),
        events_dir=tmp_path,
        url=URL,
    )
    assert step.spans == 1
    assert len(recorder.calls) == 1


def test_a_one_shot_export_honours_the_window(tmp_path: Path) -> None:
    live = tmp_path / LIVE
    early = _span_pair("a" * 16, begin=1, end=2)
    late = _span_pair("b" * 16, begin=8, end=9)
    _write(live, [*early, *late])
    step = export_once(
        _exporter(),
        _resource(),
        Selection(live=live, since_wall_ns=late[0].ts_wall_ns),
        events_dir=tmp_path,
        url=URL,
    )
    assert step.spans == 1, "only the span whose records are both inside the window"


def test_a_one_shot_export_commits_the_cursor(tmp_path: Path) -> None:
    live = tmp_path / LIVE
    _write(live, _span_pair("a" * 16, begin=1, end=2))
    cursor = cursor_path(tmp_path)
    step = export_once(
        _exporter(),
        _resource(),
        Selection(live=live),
        events_dir=tmp_path,
        url=URL,
        cursor=cursor,
        endpoint=ENDPOINT,
        run_id=RUN,
    )
    assert read_cursor(cursor, endpoint=ENDPOINT, run_id=RUN) == step.safe


def test_a_one_shot_export_of_an_empty_directory_sends_nothing(tmp_path: Path) -> None:
    recorder = Recorder()
    step = export_once(
        _exporter(recorder),
        _resource(),
        Selection(live=tmp_path / LIVE),
        events_dir=tmp_path,
        url=URL,
    )
    assert recorder.calls == []
    assert step.spans == 0
    assert step.safe is None


def test_the_shard_order_comes_from_the_directory_and_not_from_a_guess(tmp_path: Path) -> None:
    """`export_once` hands `safe_position` the same order `walk` read in, which is what makes a
    carried start in an archive rank before anything in the live shard."""
    live = tmp_path / LIVE
    _write(live, [_event(3)])
    assert [shard.name for shard in shards_for(tmp_path, live)] == [LIVE]


# ---------------------------------------------------------------------------------------------
# Following
# ---------------------------------------------------------------------------------------------


def test_a_follow_turn_drains_pairs_and_sends(tmp_path: Path) -> None:
    live = tmp_path / LIVE
    _write(live, _span_pair("a" * 16, begin=1, end=2))
    recorder = Recorder()
    with Tail(shard_of(live)) as tail:
        step = follow(_exporter(recorder), _resource(), tail, Selection(live=live), url=URL)
    assert step.spans == 1
    assert len(recorder.calls) == 1
    assert step.continues_at is None, "the shard is still live"


def test_a_follow_turn_carries_an_open_span_to_the_next(tmp_path: Path) -> None:
    """Two turns and one span, which is the shape every `--follow` actually has."""
    live = tmp_path / LIVE
    _write(live, [_event(1, EventKind.UNIT_BEGIN, span="a" * 16)])
    selection = Selection(live=live)
    with Tail(shard_of(live)) as tail:
        first = follow(_exporter(), _resource(), tail, selection, url=URL)
        assert first.spans == 0
        assert len(first.carried) == 1

        with live.open("ab") as handle:
            handle.write(serialise(_event(2, EventKind.UNIT_COMPLETE, span="a" * 16)))
        second = follow(_exporter(), _resource(), tail, selection, url=URL, carried=first.carried)
    assert second.spans == 1
    assert second.carried == ()


def test_a_follow_turn_that_reads_nothing_sends_nothing(tmp_path: Path) -> None:
    live = tmp_path / LIVE
    _write(live, [])
    recorder = Recorder()
    with Tail(shard_of(live)) as tail:
        step = follow(_exporter(recorder), _resource(), tail, Selection(live=live), url=URL)
    assert recorder.calls == []
    assert step.safe is None


def test_a_follow_turn_reports_where_to_continue_after_a_roll(tmp_path: Path) -> None:
    """The caller loops: `continues_at` set means open that name at offset 0, and only the caller
    knows whether to wait — which is why this module holds no sleep."""
    live = tmp_path / LIVE
    roll = Event(
        ts_wall_ns=1_700_000_000_000_000_000,
        ts_mono_ns=5_000_000_000,
        run_id=RUN,
        writer_id="abc123abc123",
        seq=99,
        trace_id=TRACE,
        span_id="0" * 16,
        parent_span_id=None,
        kind=EventKind.SHARD_ROLL,
        phase="point",
        level="notice",
        fields={"closed": LIVE, "successor": ARCHIVE, "bytes": 10, "records": 2},
    )
    _write(live, [_event(1), roll])
    with Tail(shard_of(live)) as tail:
        step = follow(_exporter(), _resource(), tail, Selection(live=live), url=URL)
    assert step.continues_at == LIVE, "the live path, never the .gz"


# ---------------------------------------------------------------------------------------------
# The cursor is written once per distinct position
# ---------------------------------------------------------------------------------------------


def test_many_batches_at_one_position_write_the_cursor_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every caller whose window holds an open span cannot advance the position between batches,
    and would otherwise pay an atomic rewrite per request for a value that did not change.

    Six spans at `--max-batch 1` is six requests, one position, and one write.
    """
    cursor = cursor_path(tmp_path)
    written: list[Position] = []
    real = export_module.write_cursor

    def counting(path: Path, **named: object) -> None:
        written.append(named["position"])  # type: ignore[arg-type]
        real(path, **named)  # type: ignore[arg-type]

    monkeypatch.setattr(export_module, "write_cursor", counting)

    events = [_event(1, EventKind.RUN_START, span="f" * 16)]
    for index in range(6):
        events.extend(_span_pair(f"{index:016x}", begin=2 + index * 2, end=3 + index * 2))
    step = _send(
        _records(events),
        cursor=cursor,
        endpoint=ENDPOINT,
        run_id=RUN,
        max_spans=1,
    )
    assert step.spans == 6, "six spans, and at one span a batch that is six requests"
    assert len(written) == 1, "one distinct position, one write"
    assert read_cursor(cursor, endpoint=ENDPOINT, run_id=RUN) == step.safe


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(trace_module.__file__).read_text(encoding="utf-8"))


def test_the_orchestration_holds_no_clock_no_loop_and_no_sleep() -> None:
    tree = _module_tree()
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
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(trace_module.__all__)


def test_the_cli_distribution_may_not_import_this_one() -> None:
    """D369, read from the file G4 reads it from: `ow trace export` and `ow serve` are CLI verbs
    whose implementation is in a distribution the CLI's layers row does not carry, and which is
    an optional extra besides."""
    repo = Path(__file__).resolve().parents[4]
    rows = tomllib.loads((repo / "tools" / "layers.toml").read_text(encoding="utf-8"))
    assert "omniweave_serve" not in rows["omniweave"]
    assert rows["omniweave_serve"] == ["omniweave_core", "omniweave_ports"]
    extras = tomllib.loads(
        (repo / "packages" / "omniweave" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["optional-dependencies"]
    assert any(name.startswith("omniweave-serve") for name in extras["serve"])


@pytest.mark.parametrize("symbol", ["OW_EVAL_NOT_INSTALLED"])
def test_the_optional_extra_refusal_has_a_code_for_eval_and_none_for_serve(symbol: str) -> None:
    """D369's other half. `eval` reaching an absent `omniweave_conform` is `OW-A-027`; `serve`
    and `trace` reaching an absent `omniweave_serve` is an `ImportError`, which DR21 forbids:
    *"a missing capability is a pruned plan with a report, never an `ImportError`"*."""
    repo = Path(__file__).resolve().parents[4]
    register = tomllib.loads((repo / "codes.toml").read_text(encoding="utf-8"))
    symbols = {row["symbol"] for row in register["code"]}
    assert symbol in symbols
    assert not [name for name in symbols if "SERVE_NOT_INSTALLED" in name]
