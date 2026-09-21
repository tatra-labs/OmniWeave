"""The export mechanics, with a recording transport and a sleep that counts instead of waiting.

**Nothing here opens a socket and nothing here waits.** `Transport` is a Protocol with one method,
so a fake is four lines; `sleep` is a constructor argument, so asserting the 1/2/4 ladder costs no
seconds. A test suite that exercised the real ladder would take seven seconds per failure case and
would be the first thing someone deleted.

**The ordering test is the one that matters.** The cursor is written AFTER the transport accepted
a request, which is the whole reason this module has a cursor at all: written first, a crash in the
gap loses spans, and 15:255 makes a duplicate arrival harmless while nothing makes a gap
recoverable. A watching transport reads the cursor on its way past and the test asserts what it
saw.
"""

from __future__ import annotations

import ast
import json
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import omniweave_serve.export as export_module
import pytest
from omniweave_core.errors import ConfigError
from omniweave_serve.export import (
    BACKOFF_S,
    CONTENT_TYPE,
    CURSOR_NAME,
    DELIVERED,
    TRACES_PATH,
    Delivered,
    Exporter,
    Halted,
    Response,
    Transport,
    UrllibTransport,
    cursor_key,
    cursor_path,
    endpoint_digest,
    payload,
    read_cursor,
    traces_url,
    write_cursor,
)
from omniweave_serve.otlp import (
    SPAN_KIND_INTERNAL,
    STATUS_CODE_UNSET,
    Resource,
    Span,
    traces_request,
)
from omniweave_serve.shards import Position

if TYPE_CHECKING:
    from collections.abc import Mapping

ENDPOINT = "https://collector.internal:4318"
RUN = "r_01J0000000000000000000000"


@dataclass
class Recorder:
    """A `Transport` that answers from a script and keeps every call. Four lines of behaviour."""

    answers: list[Response] = field(default_factory=list)
    calls: list[tuple[str, bytes, dict[str, str]]] = field(default_factory=list)
    default: Response = field(default_factory=lambda: Response(200, "OK"))

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> Response:
        self.calls.append((url, body, dict(headers)))
        return self.answers.pop(0) if self.answers else self.default


@dataclass
class Waits:
    """A `sleep` that records instead of sleeping."""

    seen: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        self.seen.append(seconds)


def _span(index: int = 0) -> Span:
    return Span(
        trace_id="0af7651916cd43dd8448eb211c80319c",
        span_id=f"{index:016x}",
        parent_span_id=None,
        name="run",
        kind=SPAN_KIND_INTERNAL,
        start_wall_ns=1_700_000_000_000_000_000,
        end_wall_ns=1_700_000_000_250_000_000,
        clock_stepped=False,
        status_code=STATUS_CODE_UNSET,
        status_message="",
    )


def _resource() -> Resource:
    return Resource(config_digest="3b8a1f4c" * 8)


def _exporter(recorder: Recorder, waits: Waits | None = None) -> Exporter:
    return Exporter(transport=recorder, sleep=waits or Waits())


SHARD = "r_01J0000000000000000000000.ndjson"


def _at(offset: int) -> Position:
    return Position(shard=SHARD, offset=offset)


def _batches(count: int) -> list[tuple[Position, list[Span]]]:
    """`(position, spans)` pairs, with an offset that grows the way a shard's does."""
    return [(_at((index + 1) * 4096), [_span(index)]) for index in range(count)]


# ---------------------------------------------------------------------------------------------
# The URL and the body
# ---------------------------------------------------------------------------------------------


def test_the_url_is_the_endpoint_plus_the_traces_path() -> None:
    assert traces_url(ENDPOINT) == f"{ENDPOINT}{TRACES_PATH}"
    assert TRACES_PATH == "/v1/traces"


def test_a_trailing_slash_is_tolerated_and_never_doubled() -> None:
    """An operator pastes an endpoint with a slash on it roughly half the time."""
    assert traces_url(ENDPOINT + "/") == traces_url(ENDPOINT)
    assert traces_url(ENDPOINT + "///") == traces_url(ENDPOINT)


def test_the_body_is_the_traces_request_compactly_encoded() -> None:
    body = payload(_resource(), [_span()])
    assert json.loads(body) == traces_request(_resource(), [_span()])
    assert b", " not in body, "a wire format, not a file a human diffs"


def test_the_content_type_is_the_one_the_plan_names() -> None:
    recorder = Recorder()
    _exporter(recorder).export(_resource(), _batches(1), url=traces_url(ENDPOINT))
    assert recorder.calls[0][2] == {"Content-Type": CONTENT_TYPE}
    assert CONTENT_TYPE == "application/json"


# ---------------------------------------------------------------------------------------------
# The retry ladder
# ---------------------------------------------------------------------------------------------


def test_a_delivered_request_is_not_retried() -> None:
    recorder = Recorder()
    waits = Waits()
    answer, attempts = _exporter(recorder, waits).deliver("u", b"{}")
    assert answer.ok()
    assert attempts == 1
    assert len(recorder.calls) == 1
    assert waits.seen == []


def test_the_ladder_is_one_two_four_and_stops_there() -> None:
    """15:254: *"retried three times with 1 s / 2 s / 4 s backoff"*. Four attempts, three waits."""
    recorder = Recorder(default=Response(503, "Service Unavailable"))
    waits = Waits()
    answer, attempts = _exporter(recorder, waits).deliver("u", b"{}")
    assert attempts == 4
    assert len(recorder.calls) == 4
    assert waits.seen == [1.0, 2.0, 4.0]
    assert answer.status == 503


def test_no_wait_follows_the_final_failure() -> None:
    """A ladder that slept after its last attempt would add four seconds to every failed export
    and change nothing about its outcome."""
    waits = Waits()
    _exporter(Recorder(default=Response(500)), waits).deliver("u", b"{}")
    assert len(waits.seen) == len(BACKOFF_S)


def test_a_retry_that_succeeds_stops_the_ladder_where_it_succeeded() -> None:
    recorder = Recorder(answers=[Response(503), Response(0, "connection reset"), Response(200)])
    waits = Waits()
    answer, attempts = _exporter(recorder, waits).deliver("u", b"{}")
    assert answer.ok()
    assert attempts == 3
    assert waits.seen == [1.0, 2.0], "the third rung is never climbed"


def test_a_socket_error_and_a_non_2xx_are_one_condition() -> None:
    """15:254 treats them identically, so they are one type with one predicate."""
    assert Response(0, "connection refused").ok() is False
    assert Response(503).ok() is False
    assert Response(200).ok() is True


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_every_2xx_is_a_delivery(status: int) -> None:
    assert Response(status).ok() is True
    assert status in DELIVERED


@pytest.mark.parametrize("status", [0, 100, 199, 300, 301, 400, 401, 429, 500, 503])
def test_nothing_else_is(status: int) -> None:
    assert Response(status).ok() is False


def test_a_negative_backoff_is_refused_at_construction() -> None:
    with pytest.raises(ConfigError, match="never negative"):
        Exporter(transport=Recorder(), sleep=Waits(), backoff=(1.0, -2.0))


def test_the_attempt_count_is_the_ladder_plus_one() -> None:
    assert _exporter(Recorder()).attempts == 1 + len(BACKOFF_S) == 4
    assert Exporter(transport=Recorder(), sleep=Waits(), backoff=()).attempts == 1


def test_an_empty_ladder_tries_once_and_gives_up() -> None:
    recorder = Recorder(default=Response(500))
    exporter = Exporter(transport=recorder, sleep=Waits(), backoff=())
    answer, attempts = exporter.deliver("u", b"{}")
    assert (answer.ok(), attempts, len(recorder.calls)) == (False, 1, 1)


# ---------------------------------------------------------------------------------------------
# The cursor
# ---------------------------------------------------------------------------------------------


def test_the_cursor_lives_beside_the_shards() -> None:
    assert cursor_path(Path(".omniweave/events")).name == CURSOR_NAME
    assert CURSOR_NAME == ".export_cursor.json"


def test_the_key_is_the_endpoint_digest_and_the_run() -> None:
    """15:256's `(endpoint_digest, run_id)`."""
    key = cursor_key(ENDPOINT, RUN)
    assert key == f"{endpoint_digest(ENDPOINT)}:{RUN}"
    assert RUN in key


def test_the_endpoint_itself_never_reaches_the_file() -> None:
    """A collector URL can carry a token in its query string, and `.omniweave/` is a directory
    people tar up and attach to issues."""
    carrying = "https://collector.internal:4318/?token=s3cret"
    assert "s3cret" not in endpoint_digest(carrying)
    assert "collector" not in endpoint_digest(carrying)


def test_two_endpoints_key_two_rows(tmp_path: Path) -> None:
    path = cursor_path(tmp_path)
    write_cursor(path, endpoint=ENDPOINT, run_id=RUN, position=_at(10))
    write_cursor(path, endpoint="http://other:4318", run_id=RUN, position=_at(20))
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) == _at(10)
    assert read_cursor(path, endpoint="http://other:4318", run_id=RUN) == _at(20)


def test_two_runs_key_two_rows(tmp_path: Path) -> None:
    path = cursor_path(tmp_path)
    write_cursor(path, endpoint=ENDPOINT, run_id=RUN, position=_at(10))
    write_cursor(path, endpoint=ENDPOINT, run_id="r_other", position=_at(20))
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) == _at(10)


def test_a_second_write_preserves_every_other_row(tmp_path: Path) -> None:
    """The cursor is one file for every run this `.omniweave/` has exported."""
    path = cursor_path(tmp_path)
    for index in range(5):
        write_cursor(path, endpoint=ENDPOINT, run_id=f"r_{index}", position=_at(index))
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 5


def test_an_absent_cursor_reads_as_absent(tmp_path: Path) -> None:
    assert read_cursor(cursor_path(tmp_path), endpoint=ENDPOINT, run_id=RUN) is None


@pytest.mark.parametrize("content", ["", "not json", "[]", '"a string"', "null", "123"])
def test_a_malformed_cursor_is_absent_rather_than_a_failure(tmp_path: Path, content: str) -> None:
    """A cursor is an optimisation over re-sending, and 15:255 already licenses a duplicate
    arrival as harmless. Refusing to export because a JSON file was truncated by a full disk
    turns a recoverable duplicate into an unrecoverable gap."""
    path = cursor_path(tmp_path)
    path.write_text(content, encoding="utf-8")
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) is None


@pytest.mark.parametrize(
    "value",
    [
        4096,
        "r_01.ndjson:4096",
        {"shard": SHARD},
        {"offset": 10},
        {"shard": "", "offset": 10},
        {"shard": SHARD, "offset": -1},
        {"shard": SHARD, "offset": "10"},
        {"shard": SHARD, "offset": True},
        {"shard": 7, "offset": 10},
    ],
)
def test_a_row_that_is_not_a_position_reads_as_absent(tmp_path: Path, value: object) -> None:
    """D367's compatibility rule, and the first case is the point of it: a bare integer is
    what 15:256's single "shard offset" would be, and what a cursor written before D367
    holds. It reads as absent, because a duplicate arrival is free and a resume into the
    wrong shard is not."""
    path = cursor_path(tmp_path)
    path.write_text(json.dumps({cursor_key(ENDPOINT, RUN): value}), encoding="utf-8")
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) is None


def test_a_negative_offset_is_refused_when_a_position_is_built() -> None:
    """Reading tolerates it and constructing does not: one is somebody else's corruption
    and the other is ours."""
    with pytest.raises(ConfigError, match="byte count"):
        Position(shard=SHARD, offset=-1)


def test_the_cursor_is_written_atomically_and_leaves_no_temp_file(tmp_path: Path) -> None:
    """`ow trace export` and `ow trace export --follow` can run against one `.omniweave/` at
    once, and a torn cursor read as 0 re-sends a whole run."""
    path = cursor_path(tmp_path)
    write_cursor(path, endpoint=ENDPOINT, run_id=RUN, position=_at(7))
    assert [entry.name for entry in tmp_path.iterdir()] == [CURSOR_NAME]


def test_the_cursor_directory_is_created_if_it_is_missing(tmp_path: Path) -> None:
    path = cursor_path(tmp_path / "events")
    write_cursor(path, endpoint=ENDPOINT, run_id=RUN, position=_at(1))
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) == _at(1)


# ---------------------------------------------------------------------------------------------
# The export, and the ordering the whole design rests on
# ---------------------------------------------------------------------------------------------


def test_every_batch_is_sent_in_order() -> None:
    recorder = Recorder()
    result = _exporter(recorder).export(_resource(), _batches(3), url=traces_url(ENDPOINT))
    assert isinstance(result, Delivered)
    assert (result.requests, result.spans, result.position) == (3, 3, _at(3 * 4096))
    assert [call[0] for call in recorder.calls] == [traces_url(ENDPOINT)] * 3


def test_the_cursor_is_written_after_the_send_and_never_before(tmp_path: Path) -> None:
    """The ordering 10 section 3.11(c) fixes for the emission ledger, one system over: a cursor
    written first loses spans on a crash in the gap, and nothing makes a gap recoverable."""
    path = cursor_path(tmp_path)
    seen: list[Position | None] = []

    class Watching(Recorder):
        def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> Response:
            seen.append(read_cursor(path, endpoint=ENDPOINT, run_id=RUN))
            return super().post(url, body, headers)

    _exporter(Watching()).export(
        _resource(),
        _batches(3),
        url=traces_url(ENDPOINT),
        cursor=path,
        endpoint=ENDPOINT,
        run_id=RUN,
    )
    assert seen == [None, _at(4096), _at(2 * 4096)], "each send saw only the PREVIOUS"
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) == _at(3 * 4096)


def test_a_failure_stops_the_export_and_sends_nothing_after_it() -> None:
    recorder = Recorder(answers=[Response(200), *[Response(500)] * 4])
    result = _exporter(recorder).export(_resource(), _batches(5), url=traces_url(ENDPOINT))
    assert isinstance(result, Halted)
    assert result.requests == 1
    assert len(recorder.calls) == 1 + 4, "one delivery, then one batch up the whole ladder"


def test_a_failure_names_the_offset_a_re_run_resumes_from() -> None:
    """15:255: *"exits non-zero naming the last shard offset it **committed**"* -- the committed
    one, not the one being attempted, because starting there re-sends at most the failed batch."""
    recorder = Recorder(answers=[Response(200), Response(200), *[Response(0, "reset")] * 4])
    result = _exporter(recorder).export(_resource(), _batches(4), url=traces_url(ENDPOINT))
    assert isinstance(result, Halted)
    assert result.position == _at(2 * 4096)
    assert result.attempts == 4
    assert result.status == 0
    assert result.reason == "reset"


def test_a_failure_on_the_very_first_batch_still_names_where_this_run_began() -> None:
    """`committed` carries the cursor a run resumed from, so a `Halted` never reports 0 for a
    resumed export that failed immediately."""
    recorder = Recorder(default=Response(500))
    result = _exporter(recorder).export(
        _resource(), _batches(2), url=traces_url(ENDPOINT), committed=_at(8192)
    )
    assert isinstance(result, Halted)
    assert result.position == _at(8192)


def test_the_cursor_holds_the_last_success_after_a_failure(tmp_path: Path) -> None:
    path = cursor_path(tmp_path)
    recorder = Recorder(answers=[Response(200), *[Response(500)] * 4])
    _exporter(recorder).export(
        _resource(),
        _batches(3),
        url=traces_url(ENDPOINT),
        cursor=path,
        endpoint=ENDPOINT,
        run_id=RUN,
    )
    assert read_cursor(path, endpoint=ENDPOINT, run_id=RUN) == _at(4096)


def test_the_halted_message_names_the_cause_the_counts_and_the_offset() -> None:
    message = Halted(
        requests=2,
        spans=7,
        position=_at(8192),
        attempts=4,
        status=503,
        reason="Unavailable",
    ).message()
    assert "HTTP 503" in message
    assert "Unavailable" in message
    assert "8192" in message
    assert "2 request(s)" in message
    assert "7 span(s)" in message


def test_a_socket_failure_says_so_rather_than_printing_http_0() -> None:
    message = Halted(requests=0, spans=0, position=None, attempts=4, status=0, reason="").message()
    assert "socket error" in message
    assert "HTTP 0" not in message


def test_exporting_nothing_sends_nothing() -> None:
    recorder = Recorder()
    result = _exporter(recorder).export(_resource(), [], url=traces_url(ENDPOINT))
    assert result == Delivered(requests=0, spans=0, position=None)
    assert recorder.calls == []


def test_no_cursor_is_written_when_none_is_given() -> None:
    """`--file` and `--dry-run` have no endpoint to key a cursor on."""
    recorder = Recorder()
    result = _exporter(recorder).export(_resource(), _batches(2), url=traces_url(ENDPOINT))
    assert isinstance(result, Delivered)
    assert result.position == _at(2 * 4096)


# ---------------------------------------------------------------------------------------------
# `--dry-run --print-payload`
# ---------------------------------------------------------------------------------------------


def test_a_rehearsal_dials_nothing_and_commits_nothing(tmp_path: Path) -> None:
    recorder = Recorder()
    bodies = _exporter(recorder).rehearse(_resource(), _batches(3))
    assert len(bodies) == 3
    assert recorder.calls == []
    assert not list(tmp_path.iterdir())


def test_what_would_be_sent_is_byte_identical_to_what_is_sent() -> None:
    """15:2024 asks for *"the exact OTLP JSON that would be sent"*, and a rehearsal that rebuilt
    the payload by a second path would be a reassuring fiction the first time the two drifted."""
    batches = _batches(4)
    rehearsed = _exporter(Recorder()).rehearse(_resource(), batches)
    recorder = Recorder()
    _exporter(recorder).export(_resource(), batches, url=traces_url(ENDPOINT))
    assert rehearsed == tuple(body for _, body, _ in recorder.calls)


def test_a_rehearsed_body_parses_as_the_document_a_collector_expects() -> None:
    body = _exporter(Recorder()).rehearse(_resource(), _batches(1))[0]
    parsed = json.loads(body)
    assert list(parsed) == ["resourceSpans"]
    assert len(parsed["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 1


# ---------------------------------------------------------------------------------------------
# The shipped transport
# ---------------------------------------------------------------------------------------------


def test_the_shipped_transport_satisfies_the_protocol() -> None:
    assert isinstance(UrllibTransport(), Transport)


def test_a_recording_fake_satisfies_it_too() -> None:
    """The point of narrowing the Protocol to one method: a test double is four lines and needs
    no base class and no mocking library."""
    assert isinstance(Recorder(), Transport)


def test_the_transport_turns_every_failure_into_a_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """15:254 treats a non-2xx and a socket error alike, so a caller that also had to catch
    `URLError` would be implementing that rule twice."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(export_module.urllib.request, "urlopen", refuse)
    answer = UrllibTransport().post("http://127.0.0.1:1/v1/traces", b"{}", {})
    assert answer.status == 0
    assert "refused" in answer.reason


def test_an_http_error_keeps_its_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(export_module.urllib.request, "urlopen", refuse)
    answer = UrllibTransport().post("http://x", b"{}", {})
    assert answer.status == 429
    assert answer.ok() is False


def test_a_timeout_is_a_socket_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(export_module.urllib.request, "urlopen", refuse)
    assert UrllibTransport().post("http://x", b"{}", {}).status == 0


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(export_module.__file__).read_text(encoding="utf-8"))


def test_the_only_module_that_dials_holds_no_clock_and_no_loop() -> None:
    """`sleep` is injected for `clock.py`'s reason, and there is no loop here at all: an export
    is a synchronous walk over batches, which is what makes every case above a unit test."""
    tree = _module_tree()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"asyncio", "selectors", "time", "threading", "opentelemetry"})
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith)
    ]


def test_the_socket_is_behind_one_class() -> None:
    """Everything else in this module is pure, which is why the `[[client]]` row in
    `tools/egress.toml` names one path and one reason."""
    dialers = [
        node
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Attribute) and node.attr == "urlopen"
    ]
    assert len(dialers) == 1


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(export_module.__all__)
