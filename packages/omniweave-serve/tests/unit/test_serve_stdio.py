"""The transport: the framing, the loop, and the instant a response counts as sent.

**The assertion this file exists for is an ordering, not a value.** 10:979 makes `ledger.commit()`
happen after `await transport.send(answer)` and 10:981 calls the three failures that ordering
prevents *"structurally impossible rather than tested for"* -- so the tests below check the
structure that makes it so (a dispatcher is handed no writer, and `after_send` has exactly one
caller) as well as the order itself.

The rest is framing, and framing is tested the way a wire format has to be: against the bytes.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import sys
import tomllib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import mcp.server.stdio
import omniweave_serve.stdio as stdio_module
import pytest
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import LATEST_PROTOCOL_VERSION
from omniweave.gen.budget import RECIPE, serialised
from omniweave_core.contract import RELEASE
from omniweave_serve.guard import MAX_REQUEST_BYTES
from omniweave_serve.stdio import (
    EOF,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC,
    MAX_FRAME_BYTES,
    PARSE_ERROR,
    PEER_GONE,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SUPPORTED_VERSIONS,
    BinaryLines,
    BinarySink,
    Dispatcher,
    Line,
    Malformed,
    Notification,
    Reply,
    Request,
    decode,
    encode,
    failure,
    initialize_result,
    negotiate,
    pipes,
    result,
    serve,
    uninstructable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------------------------
# Doubles. None of them holds a loop of its own; every async test drives one with `asyncio.run`.
# ---------------------------------------------------------------------------------------------


@dataclass
class Scripted:
    """A `Lines` that answers from a list and then reports end of input."""

    lines: list[Line] = field(default_factory=list)
    reads: int = 0

    async def readline(self) -> Line:
        self.reads += 1
        return self.lines.pop(0) if self.lines else Line(b"")


@dataclass
class Recorder:
    """A `Sink` that records the frames it was given, and the order it was given them in."""

    frames: list[bytes] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    async def send(self, frame: bytes) -> None:
        self.frames.append(frame)
        self.log.append("sent")

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(frame) for frame in self.frames]


@dataclass
class Echo:
    """A `Dispatcher` that answers every request and commits through `after_send` when told to."""

    log: list[str] = field(default_factory=list)
    commit: bool = True
    seen: list[Request | Notification] = field(default_factory=list)

    async def dispatch(self, message: Request | Notification) -> Reply | None:
        self.seen.append(message)
        if isinstance(message, Notification):
            return None
        hook = (lambda: self.log.append("committed")) if self.commit else None
        return Reply(body=result(message.ident, {"echo": message.method}), after_send=hook)


def _line(payload: Mapping[str, Any]) -> Line:
    return Line(encode(payload))


def _run(lines: Sequence[Line], dispatcher: Echo, sink: Recorder) -> stdio_module.Served:
    return asyncio.run(serve(Scripted(list(lines)), sink, dispatcher))


# ---------------------------------------------------------------------------------------------
# The ordering 10:979 fixes, and the structure that makes it the only possible one
# ---------------------------------------------------------------------------------------------


def test_the_commit_runs_after_the_frame_is_sent_and_never_before() -> None:
    """10:981's window, closed. The sink and the commit hook share one log, so the assertion is
    on the sequence rather than on two counters that could both be right separately."""
    log: list[str] = []
    sink = Recorder(log=log)
    dispatcher = Echo(log=log)
    served = _run([_line({"jsonrpc": JSONRPC, "id": 1, "method": "ping"})], dispatcher, sink)
    assert log == ["sent", "committed"]
    assert served.sent == 1
    assert served.committed == 1


def test_a_dispatcher_is_handed_no_writer_and_so_cannot_send_at_all() -> None:
    """The structural half. `Dispatcher.dispatch` takes one argument and it is the message: there
    is no sink, no stream and no callback on it, so committing early is not a discipline a
    dispatcher keeps -- it is a thing a dispatcher has no way to do."""
    parameters = list(inspect.signature(Dispatcher.dispatch).parameters)
    assert parameters == ["self", "message"]
    assert set(inspect.signature(Reply).parameters) == {"body", "after_send"}


def test_after_send_has_exactly_one_call_site_and_it_is_in_the_loop() -> None:
    """The other structural half, read from the module rather than asserted about it."""
    tree = ast.parse(Path(stdio_module.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "after_send"
    ]
    assert len(calls) == 1
    inside = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and any(c in ast.walk(node) for c in calls)
    ]
    assert inside == ["serve"]


def test_a_reply_with_no_commit_hook_is_sent_and_counted_once() -> None:
    sink = Recorder()
    served = _run(
        [_line({"jsonrpc": JSONRPC, "id": 1, "method": "ping"})], Echo(commit=False), sink
    )
    assert served.sent == 1
    assert served.committed == 0


def test_a_notification_is_never_answered_even_if_the_dispatcher_offers_one() -> None:
    """The rule is JSON-RPC's and the transport keeps it rather than trusting a handler to. A
    dispatcher that replied to `notifications/initialized` would put an unsolicited response on the
    wire and a commit behind it; here it reaches the dispatcher and produces no frame."""

    @dataclass
    class Overeager:
        seen: list[Request | Notification] = field(default_factory=list)
        committed: int = 0

        async def dispatch(self, message: Request | Notification) -> Reply | None:
            self.seen.append(message)
            return Reply(body={"jsonrpc": JSONRPC, "id": 0, "result": {}}, after_send=self.bump)

        def bump(self) -> None:
            self.committed += 1

    sink = Recorder()
    dispatcher = Overeager()
    served = asyncio.run(
        serve(
            Scripted([_line({"jsonrpc": JSONRPC, "method": "notifications/cancelled"})]),
            sink,
            dispatcher,
        )
    )
    assert [m.method for m in dispatcher.seen] == ["notifications/cancelled"]
    assert sink.frames == []
    assert dispatcher.committed == 0
    assert served.notifications == 1
    assert served.sent == 0


def test_a_write_that_fails_stops_the_loop_before_the_commit() -> None:
    """10:981's transport-error row, which is the one that ordering exists for: the frame did not
    arrive, so the emission it carried was never received, so nothing about it may be recorded."""

    @dataclass
    class Broken:
        log: list[str] = field(default_factory=list)

        async def send(self, frame: bytes) -> None:
            self.log.append(f"attempted {len(frame)}")
            raise BrokenPipeError(32, "the host went away")

    log: list[str] = []
    sink = Broken(log=log)
    served = asyncio.run(
        serve(
            Scripted(
                [
                    _line({"jsonrpc": JSONRPC, "id": 1, "method": "ping"}),
                    _line({"jsonrpc": JSONRPC, "id": 2, "method": "ping"}),
                ]
            ),
            sink,
            Echo(log=log),
        )
    )
    assert [entry.split()[0] for entry in log] == ["attempted"]
    assert "committed" not in log
    assert served.stopped_by == PEER_GONE
    assert served.sent == 0
    assert served.committed == 0
    assert served.requests == 1, "the second frame was never read"


def test_the_sdk_write_stream_returns_before_the_frame_is_flushed() -> None:
    """D384, measured. `mcp.server.stdio.stdio_server()` hands a caller a zero-capacity anyio
    memory object stream, and `await write_stream.send(...)` returns before the writer task has
    written or flushed anything -- so a ledger commit ordered after that `send` is committed on a
    message still in a queue. Both halves are checked: the SDK's capacity, read from its source,
    and the ordering, measured."""
    source = Path(inspect.getfile(mcp.server.stdio)).read_text(encoding="utf-8")
    assert "create_memory_object_stream(0)" in source
    assert "await stdout.flush()" in source

    order: list[str] = []

    async def main() -> None:
        send, recv = anyio.create_memory_object_stream(0)

        async def writer() -> None:
            async with recv:
                async for item in recv:
                    order.append(f"received {item}")
                    await anyio.sleep(0)
                    order.append(f"wrote {item}")
                    order.append(f"flushed {item}")

        async with anyio.create_task_group() as group, send:
            group.start_soon(writer)
            await anyio.sleep(0.01)
            await send.send("A")
            order.append("send() returned")

    anyio.run(main, backend="asyncio")
    assert order.index("send() returned") < order.index("flushed A")


# ---------------------------------------------------------------------------------------------
# Framing: the bytes
# ---------------------------------------------------------------------------------------------


def test_a_frame_is_one_line_and_the_newline_is_the_last_byte() -> None:
    frame = encode({"jsonrpc": JSONRPC, "id": 1, "result": {}})
    assert frame.endswith(b"\n")
    assert frame.count(b"\n") == 1


@pytest.mark.parametrize(
    "hostile",
    [
        "a" + chr(10) + "b",
        "a" + chr(13) + "b",
        "a" + chr(0x2028) + "b",
        chr(0),
        chr(0x85),
    ],
)
def test_no_payload_can_put_a_second_newline_in_a_frame(hostile: str) -> None:
    """The framing is newline-delimited, so a character some reader treats as a line break is the
    one way a payload could split its own frame. `json.dumps` escapes every code point below 0x20,
    and U+2028 and U+0085 survive as themselves -- which is safe because the frame is split on one
    byte and neither encodes to it. Asserted rather than assumed: both are line breaks to
    `str.splitlines()`, and a framing that had reached for it would be splittable from inside."""
    frame = encode({"jsonrpc": JSONRPC, "id": 1, "result": {"text": hostile}})
    assert frame.count(b"\n") == 1
    assert json.loads(frame)["result"]["text"] == hostile


def test_the_wire_carries_real_utf8_and_not_escapes() -> None:
    """10:331: *"`ensure_ascii=False` is load-bearing ... The `tools/list` payload is real
    UTF-8."* The em dash and the middle dot are the two the payload actually carries."""
    frame = encode({"jsonrpc": JSONRPC, "id": 1, "result": {"text": "a — b · c"}})
    assert "—".encode() in frame
    assert b"\\u2014" not in frame


def test_the_frame_is_the_string_the_frozen_baseline_counted() -> None:
    """The recipe is `gen.budget.RECIPE`, executed. A test may import across the layers row that
    `unservable()` names, because G4 scans `packages/*/src/**/*.py` and a test tree is not
    source."""
    tool = {"name": "ow_query", "description": "a — b", "annotations": {"readOnlyHint": True}}
    assert encode(tool)[:-1].decode("utf-8") == serialised(tool)
    assert RECIPE == "json.dumps(tool,separators=(',',':'),ensure_ascii=False)"


def test_a_frame_that_cannot_be_encoded_raises_rather_than_arriving_wrong() -> None:
    """D386. 10:1553's process-wide `errors="replace"` would have substituted the character and
    sent a frame the peer parses and misreads; `errors="strict"` refuses to send it at all."""
    with pytest.raises(UnicodeEncodeError):
        encode({"jsonrpc": JSONRPC, "id": 1, "result": {"text": "\ud800"}})


def test_nan_and_infinity_are_refused_because_they_are_not_json() -> None:
    with pytest.raises(ValueError, match="Out of range"):
        encode({"jsonrpc": JSONRPC, "id": 1, "result": {"n": float("nan")}})


# ---------------------------------------------------------------------------------------------
# Framing: the messages
# ---------------------------------------------------------------------------------------------


def test_a_request_carries_its_id_method_and_params() -> None:
    message = decode(
        encode({"jsonrpc": JSONRPC, "id": 7, "method": "tools/call", "params": {"a": 1}})
    )
    assert message == Request(ident=7, method="tools/call", params={"a": 1})


def test_a_notification_has_no_id_and_is_owed_no_answer() -> None:
    message = decode(encode({"jsonrpc": JSONRPC, "method": "notifications/initialized"}))
    assert message == Notification(method="notifications/initialized", params={})


def test_a_blank_line_is_ignored_rather_than_answered() -> None:
    for blank in (b"\n", b"  \n", b"\r\n"):
        message = decode(blank)
        assert isinstance(message, Malformed)
        assert not message.answerable


def test_a_batch_is_refused_and_the_refusal_says_which_thing_it_refused() -> None:
    message = decode(b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]\n')
    assert isinstance(message, Malformed)
    assert message.code == INVALID_REQUEST
    assert "batch" in message.reason
    assert message.ident is None


@pytest.mark.parametrize(
    "line", [b"not json\n", b"{\n", b'{"jsonrpc":"2.0",}\n', b"\xff\xfe not utf8\n"]
)
def test_a_line_that_does_not_parse_is_a_parse_error_with_no_id(line: bytes) -> None:
    message = decode(line)
    assert isinstance(message, Malformed)
    assert message.code == PARSE_ERROR
    assert message.ident is None
    assert message.answerable


def test_a_frame_declaring_another_protocol_is_not_addressed_to_us() -> None:
    message = decode(b'{"jsonrpc":"1.0","id":1,"method":"ping"}\n')
    assert isinstance(message, Malformed)
    assert message.code == INVALID_REQUEST
    assert message.ident == 1


@pytest.mark.parametrize("ident", [None, True, 1.5, {"a": 1}])
def test_an_id_no_response_could_address_is_refused(ident: object) -> None:
    """`true` is the sharp one: JSON `true` is a Python `bool` and a `bool` is an `int`, so an
    identity check that forgot it would have accepted `id: true` and answered `id: 1`."""
    message = decode(encode({"jsonrpc": JSONRPC, "id": ident, "method": "ping"}))
    assert isinstance(message, Malformed)
    assert message.code == INVALID_REQUEST


def test_params_must_be_an_object_because_mcp_carries_named_arguments_only() -> None:
    message = decode(b'{"jsonrpc":"2.0","id":1,"method":"ping","params":[1,2]}\n')
    assert isinstance(message, Malformed)
    assert message.code == INVALID_PARAMS
    assert message.ident == 1


def test_a_broken_notification_is_not_answered_and_a_broken_request_is() -> None:
    """Answering a notification is a protocol violation *including on failure*, and the id is the
    only thing that tells the two apart once `method` is unusable."""
    quiet = decode(b'{"jsonrpc":"2.0","method":123}\n')
    loud = decode(b'{"jsonrpc":"2.0","id":"x","method":123}\n')
    assert isinstance(quiet, Malformed)
    assert isinstance(loud, Malformed)
    assert not quiet.answerable
    assert loud.answerable
    assert loud.ident == "x"


# ---------------------------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------------------------


def test_the_loop_stops_at_end_of_input_and_says_so() -> None:
    served = _run([], Echo(), Recorder())
    assert served.stopped_by == EOF
    assert served == stdio_module.Served(stopped_by=EOF)


def test_a_request_is_answered_and_a_notification_is_not() -> None:
    sink = Recorder()
    served = _run(
        [
            _line({"jsonrpc": JSONRPC, "id": 1, "method": "ping"}),
            _line({"jsonrpc": JSONRPC, "method": "notifications/initialized"}),
        ],
        Echo(),
        sink,
    )
    assert served.requests == 1
    assert served.notifications == 1
    assert [body["id"] for body in sink.bodies()] == [1]


def test_a_malformed_frame_is_answered_and_does_not_stop_the_loop() -> None:
    sink = Recorder()
    served = _run(
        [Line(b"not json\n"), _line({"jsonrpc": JSONRPC, "id": 2, "method": "ping"})], Echo(), sink
    )
    assert served.refused == 1
    assert served.requests == 1
    bodies = sink.bodies()
    assert bodies[0]["id"] is None
    assert bodies[0]["error"]["code"] == PARSE_ERROR
    assert bodies[1]["id"] == 2


def test_a_frame_that_is_owed_no_answer_produces_no_frame() -> None:
    sink = Recorder()
    served = _run([Line(b"\n"), Line(b'{"jsonrpc":"2.0","method":9}\n')], Echo(), sink)
    assert served.refused == 2
    assert sink.frames == []


def test_an_over_long_frame_is_refused_without_being_parsed() -> None:
    sink = Recorder()
    served = _run([Line(b"", truncated=True)], Echo(), sink)
    assert served.refused == 1
    body = sink.bodies()[0]
    assert body["id"] is None
    assert body["error"]["code"] == INVALID_REQUEST
    assert str(MAX_FRAME_BYTES) in body["error"]["message"]


# ---------------------------------------------------------------------------------------------
# The binding to real pipes
# ---------------------------------------------------------------------------------------------


def test_the_reader_returns_one_line_at_a_time_and_then_end_of_input() -> None:
    reader = BinaryLines(BytesIO(b'{"a":1}\n{"b":2}\n'))
    assert reader.read_now() == Line(b'{"a":1}\n')
    assert reader.read_now() == Line(b'{"b":2}\n')
    assert reader.read_now().eof()


def test_the_reader_returns_a_final_line_that_was_never_terminated() -> None:
    reader = BinaryLines(BytesIO(b'{"a":1}'))
    assert reader.read_now() == Line(b'{"a":1}')
    assert reader.read_now().eof()


def test_the_cap_is_applied_by_the_reader_and_the_tail_is_not_read_as_the_next_frame() -> None:
    """The reason the cap lives in the reader: a limit checked after the line is in memory is not
    a limit, and a limit that stops mid-line leaves the remainder to be parsed as a frame the
    peer never sent."""
    stream = BytesIO(b"x" * 40 + b"\n" + b'{"after":1}\n')
    reader = BinaryLines(stream, limit=16)
    refused = reader.read_now()
    assert refused.truncated
    assert refused.data == b""
    assert reader.read_now() == Line(b'{"after":1}\n')
    assert reader.read_now().eof()


def test_a_frame_exactly_at_the_cap_is_not_refused() -> None:
    reader = BinaryLines(BytesIO(b"x" * 8 + b"\n"), limit=8)
    assert reader.read_now() == Line(b"x" * 8 + b"\n")


def test_the_sink_flushes_before_send_returns() -> None:
    """`Sink.send`'s whole contract. 10:979: *"stdio: written AND flushed."*"""

    class Watched(BytesIO):
        def __init__(self) -> None:
            super().__init__()
            self.log: list[str] = []

        def write(self, data: Any) -> int:
            self.log.append("write")
            return super().write(data)

        def flush(self) -> None:
            self.log.append("flush")
            super().flush()

    stream = Watched()
    asyncio.run(BinarySink(stream).send(b'{"a":1}\n'))
    assert stream.log == ["write", "flush"]
    assert stream.getvalue() == b'{"a":1}\n'


def test_pipes_binds_the_binary_buffers_and_never_the_text_layer() -> None:
    """The text layer is flushed first so nothing it holds can land inside a frame, and the
    streams taken are the binary ones, where 10:1553's process-wide `errors="replace"` does not
    apply."""
    lines, sink = pipes()
    assert lines.stream is sys.stdin.buffer
    assert sink.stream is sys.stdout.buffer
    assert lines.limit == MAX_FRAME_BYTES


# ---------------------------------------------------------------------------------------------
# The handshake
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("asked", list(SUPPORTED_VERSIONS))
def test_a_supported_revision_is_echoed_back(asked: str) -> None:
    assert negotiate(asked) == asked


@pytest.mark.parametrize("asked", ["2099-01-01", "", None, 3, "2025-06-18"])
def test_anything_else_negotiates_down_rather_than_failing(asked: object) -> None:
    """A client asking for a revision this build does not carry is not an error: answering with
    one is how a host that would have worked at an older revision fails to connect at all."""
    assert negotiate(asked) == PROTOCOL_VERSION


def test_initialize_names_this_build_and_omits_instructions_when_there_are_none() -> None:
    body = initialize_result()
    assert body["serverInfo"] == {"name": SERVER_NAME, "version": RELEASE}
    assert body["capabilities"]["tools"] == {"listChanged": False}
    assert "instructions" not in body
    assert initialize_result(instructions="hello")["instructions"] == "hello"


def test_the_one_string_initialize_owes_is_in_the_distribution_this_one_may_not_import() -> None:
    """D340, a fourth crossing, and the sharpest for `initialize`: 10:861 makes the instructions
    *"the only prose that survives deferral"*."""
    owed = uninstructable()
    assert any("omniweave.gen.instructions" in line for line in owed)
    assert any("omniweave.surface.startup" in line for line in owed)
    rows = tomllib.loads((REPO / "tools" / "layers.toml").read_text(encoding="utf-8"))
    assert "omniweave" not in rows["omniweave_serve"]


# ---------------------------------------------------------------------------------------------
# The shape, the exemption, and the two numbers nothing else binds
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(stdio_module.__file__).read_text(encoding="utf-8"))


def test_this_module_imports_nothing_from_the_forbidden_distribution() -> None:
    roots: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "omniweave" not in roots
    assert {"asyncio", "json", "sys"} <= roots


def test_the_only_thing_this_module_takes_from_asyncio_is_a_thread() -> None:
    """`tools/egress.toml`'s `[[client]]` row for this path is a declaration (14:779 clause 1),
    and this is the assertion behind it: the module holds a dialer and dials nothing.
    `connect_read_pipe` is named because it is the one an `asyncio`-native reader would have
    reached for, and the reason it is absent is D385 rather than taste."""
    used = {
        node.attr
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    }
    assert used == {"to_thread"}
    named = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Attribute | ast.Name)
    }
    assert named.isdisjoint(
        {
            "open_connection",
            "create_server",
            "sock_connect",
            "create_subprocess_exec",
            "connect_read_pipe",
        }
    )


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(stdio_module.__all__)


def test_the_asyncio_exemption_is_scoped_to_the_one_file_that_binds_a_pipe() -> None:
    """D344, taken. The ban's message reads INV-3 as a rule about where a loop may live; INV-3 is
    about what `import omniweave_core` pulls in, and 02:264 row 40 gives this distribution the
    transports by name. The exemption is per-file, so the framing, the loop and the ordering
    above it stay loop-free and the one file that touches `asyncio` is the one that binds pipes."""
    ignores = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"][
        "lint"
    ]["per-file-ignores"]
    exempt = {
        path
        for path, codes in ignores.items()
        if "TID251" in codes and path.startswith("packages/omniweave-serve/src/")
    }
    assert exempt == {
        "packages/omniweave-serve/src/omniweave_serve/otlp.py",
        "packages/omniweave-serve/src/omniweave_serve/stdio.py",
    }
    awaiting = {
        node.name for node in ast.walk(_module_tree()) if isinstance(node, ast.AsyncFunctionDef)
    }
    assert awaiting == {"readline", "send", "serve", "dispatch", "_refuse"}


def test_the_two_transports_cap_the_same_object_with_two_names() -> None:
    """D348's lesson the other way round. 10:2367's arithmetic bounds the CALL, so both
    transports carry the same number, and neither imports the other's constant -- a shared name
    would make the HTTP body cap and the stdio frame cap one knob by accident."""
    assert MAX_FRAME_BYTES == MAX_REQUEST_BYTES


def test_the_revision_llms_txt_publishes_is_the_one_this_transport_negotiates() -> None:
    """D388. `llms.txt` is generated and byte-diff gated (G25), so a revision printed there and
    nowhere else is a claim nothing checks. This is the check; the second assertion records the
    distance from the SDK that actually parses the frames, so the day it closes is a failure."""
    published = (REPO / "llms.txt").read_text(encoding="utf-8")
    unwrapped = " ".join(published.split())
    assert f"(MCP Streamable HTTP, spec {PROTOCOL_VERSION})" in unwrapped
    assert PROTOCOL_VERSION in SUPPORTED_PROTOCOL_VERSIONS
    assert LATEST_PROTOCOL_VERSION != PROTOCOL_VERSION


def test_the_five_jsonrpc_numbers_are_not_in_the_code_register() -> None:
    """They are protocol facts about a frame that never reached an Action, and `codes.toml` is
    append-only (G13): coining `OW-A-*` rows for them would put five codes with no `fix` command
    in a register whose whole shape is a condition plus the command that clears it."""
    register = tomllib.loads((REPO / "codes.toml").read_text(encoding="utf-8"))
    meanings = " ".join(row.get("meaning", "") for row in register["code"])
    assert "-32700" not in meanings
    assert "jsonrpc" not in meanings.lower()


def test_failure_carries_a_null_id_when_there_was_nothing_to_answer_to() -> None:
    assert failure(None, PARSE_ERROR, "no") == {
        "jsonrpc": JSONRPC,
        "id": None,
        "error": {"code": PARSE_ERROR, "message": "no"},
    }
    assert failure(4, INVALID_REQUEST, "no", data={"k": 1})["error"]["data"] == {"k": 1}
