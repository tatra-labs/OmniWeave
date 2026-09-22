"""The stdio transport: the framing, the loop, and the instant a response counts as sent.

This distribution has had every part of a server for eleven cells and no part that moves a byte.
`admission.py` decides who may hold a snapshot, `guard.py` refuses before the work, `catalog.py`
loads the payload, `authority.py` resolves the roster and `surface/startup.py` decides what is
servable -- every one of them pure, every one of them tested by passing values in. What was left is
the part 02:264 row 40 names first, *"the `stdio` and `http` transports"*, and the reason it could
not be written before now is one `await`.

## THE SEND IS THE LOAD-BEARING FUNCTION. THE FRAMING IS NOT.

10:975 prints the sequence and puts a comment on the middle line:

    answer, emission = render(response, ledger=ledger.view(), budget=budget)
    await transport.send(answer)          # stdio: written AND flushed.
    ledger.commit(emission)

10:981 says what that ordering buys: three failures -- a cancelled call, a transport error and a
truncated response -- which all reach a user as *"omniweave appearing to have lost a document"*,
made *"structurally impossible rather than tested for"*.

**Structural is a claim about who is able to call what**, so this module is built so that nothing
else can. A `Dispatcher` does not receive the sink and cannot write a frame; it returns a `Reply`,
whose `after_send` is the only place a commit may live, and `serve()` is the only caller of it --
after `Sink.send()` has returned, which the protocol defines as *written and flushed*. A dispatcher
that wanted to commit early would have to be handed a writer it is never given.

**This is not what the obvious seam provides.** `mcp.server.stdio.stdio_server()` yields a pair of
`anyio` memory object streams, and `await write_stream.send(msg)` on a zero-capacity stream returns
at the rendezvous -- measured here as returning *before* the writer task even receives the item, and
long before `stdout.write` and `stdout.flush` run inside it. A ledger committed after that `send` is
committed on a message still in a queue. D384.

## WHY THE READER RUNS IN A THREAD, WHICH IS NOT A PORTABILITY DETAIL

An `asyncio`-native reader over `sys.stdin.buffer` does not work on Windows and does not say so.
`loop.connect_read_pipe()` accepts the pipe, `_ProactorReadPipeTransport` then fails its first read
with `OSError: [WinError 6] The handle is invalid`, the error is swallowed inside a callback, and
`StreamReader.readline()` never returns. The failure mode is a server that starts, answers nothing
and reports nothing. Measured, not inferred. D385.

So `BinaryLines` and `BinarySink` hand a blocking `readline`/`write`+`flush` to `asyncio.to_thread`,
which is what the MCP SDK does through `anyio.wrap_file`, in a comment giving the same reason:
*"Encoding of stdin/stdout as text streams on python is platform-dependent (Windows is particularly
problematic)"*.

## THE FRAME IS BYTES, AND NEVER PASSES THROUGH `sys.stdout`

10:1553 forces `sys.stdout`/`sys.stderr` to `encoding="utf-8", errors="replace"` at the top of
`main()`, and gives the reason: *"a mojibake character in an answer is recoverable and a
`UnicodeEncodeError` mid-render is not"*. On every channel `ow` had, that is right. On this one the
trade inverts: a replaced character inside a JSON string is a frame the client parses successfully
and reads as text the server did not send -- and for `tools/list` it is precisely the string 10:331
measured, because that paragraph commits the wire to real UTF-8 rather than to escapes
(*"`ensure_ascii=False` is load-bearing ... The `tools/list` payload is real UTF-8"*) and that
payload carries an em dash and a middle dot.

So `encode()` serialises with `ensure_ascii=False` to match `gen.budget.RECIPE`, encodes with
`errors="strict"`, and writes bytes to the binary buffer, where a process-wide `errors="replace"`
cannot reach it. A frame that cannot be encoded raises here instead of arriving wrong. D386.

## WHAT THIS MODULE REFUSES

A **batch**. JSON-RPC 2.0 permits an array of calls, the revision 10:2458 names permits it, and the
revision after it removes it. Supporting one would also put N answers behind one frame, which is
exactly the boundary `after_send` is defined at: there would be no instant at which *the* response
was accepted, only one at which all of them were. `INVALID_REQUEST`, and the reason is written here
rather than in a comment on the branch.

An **over-long frame**, at `MAX_FRAME_BYTES`. 10:2367 caps the HTTP body *"before parsing"* so that
*"a hostile client cannot spend a snapshot"*, and says nothing about stdio, where the peer is the
host that launched the process. The cap is here anyway, and it lives in the reader rather than in
the loop, because a cap applied after the line is in memory is not a cap. The rest of a refused
frame is drained to its newline, so its tail is never read as the next one. D387.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Any, Final, Protocol

from omniweave_core.contract import RELEASE

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "EOF",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC",
    "MAX_FRAME_BYTES",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PEER_GONE",
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SUPPORTED_VERSIONS",
    "BinaryLines",
    "BinarySink",
    "Dispatcher",
    "Line",
    "Lines",
    "Malformed",
    "Notification",
    "Reply",
    "Request",
    "Served",
    "Sink",
    "decode",
    "encode",
    "failure",
    "initialize_result",
    "negotiate",
    "pipes",
    "result",
    "serve",
    "uninstructable",
]


JSONRPC: Final[str] = "2.0"
"""The only `jsonrpc` value MCP carries. A frame declaring anything else is not addressed to us."""

MAX_FRAME_BYTES: Final[int] = 1_048_576
"""The cap on one line of input, enforced by the reader.

The same number as `guard.MAX_REQUEST_BYTES`, deliberately and not by inheritance: 10:2367's
arithmetic -- *"a JSON-RPC call whose arguments are capped at 4,096-character queries and 256
sources cannot legally approach it"* -- is about the call and not about the transport carrying it,
so the two transports bound the same object and a test binds the two constants. The separate
spelling is D348's lesson taken the other way round: two names for one thing is wrong, and one name
for two things is worse.
"""

PARSE_ERROR: Final[int] = -32700
INVALID_REQUEST: Final[int] = -32600
METHOD_NOT_FOUND: Final[int] = -32601
INVALID_PARAMS: Final[int] = -32602
INTERNAL_ERROR: Final[int] = -32603
"""The five JSON-RPC 2.0 error numbers this transport can produce on its own.

They are not `OW-A-*` codes and must not be given one. `codes.toml` registers conditions a user can
act on, each with a `fix` command; these are protocol facts about a frame that never reached an
Action. 10 section 3.10's table starts one layer above this module, at `isError` on a tool result,
and every row of it is reachable only after a frame has parsed.
"""

PROTOCOL_VERSION: Final[str] = "2025-03-26"
"""The revision `llms.txt` publishes: *"MCP Streamable HTTP, spec 2025-03-26"* (10:2458).

Named here as a constant so that the two ends are comparable at all. The installed SDK's
`LATEST_PROTOCOL_VERSION` is two revisions past it and its `SUPPORTED_PROTOCOL_VERSIONS` lists four,
and nothing in this repository binds the string a generated artefact publishes to the string a
transport negotiates. `llms.txt` is byte-diff gated by G25, so it is not hand-correctable either.
D388.
"""

SUPPORTED_VERSIONS: Final[tuple[str, ...]] = ("2025-03-26", "2024-11-05")
"""What `initialize` will echo back, newest first. Anything else negotiates down to the first.

Two rather than the SDK's four, because a revision this transport has not been written against is
one it would be claiming rather than supporting: 2025-06-18 removes batching (which this module
refuses anyway) and moves the protocol version onto an HTTP header, which is the other transport's
concern and does not exist yet.
"""

SERVER_NAME: Final[str] = "omniweave"
"""`serverInfo.name`. The product name, which is also the console script's first name (02:255)."""

EOF: Final[str] = "eof"
PEER_GONE: Final[str] = "peer_gone"
"""The two ways this loop stops, and they are not the same event.

`EOF` is the peer closing its end, which is how an MCP host shuts a server down and is an ordinary
exit. `PEER_GONE` is a write that failed -- the host died mid-answer -- and it is 10:981's
**transport error** row, which is why it breaks the loop *before* the commit rather than after it:
the frame did not arrive, so the emission it carried was never received, so nothing about it may be
recorded. 10:1549 handles the same exception one layer up for a different reason (`ow ingest |
head`), and the two must not be confused: there a broken pipe is success.
"""


@dataclass(frozen=True, slots=True)
class Line:
    """One line off the input, or the two things that are not one.

    `data` empty with `truncated` false is end of input; `truncated` is a frame that exceeded
    `MAX_FRAME_BYTES` and was discarded to its newline. Two flags rather than an exception because
    neither is an error in this process -- one ends the loop and the other answers a frame -- and a
    reader that raised would collapse both into the same thing at the call site.
    """

    data: bytes
    truncated: bool = False

    def eof(self) -> bool:
        """Whether the peer closed the input."""
        return not self.data and not self.truncated


@dataclass(frozen=True, slots=True)
class Request:
    """A call: it has an `id` and therefore it is owed exactly one response."""

    ident: str | int
    method: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Notification:
    """A message with no `id`. Answering one is a protocol violation, including on failure."""

    method: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Malformed:
    """A line that is not an addressable message, and whether it may be answered.

    `ident` is carried when it could be recovered -- a frame with a usable `id` and a bad `method`
    is answerable *to that id* -- and is `None` when the line did not parse at all, which JSON-RPC
    answers with a null id. `answerable` is false for a blank line and for anything recognisably a
    notification, because silence is the only correct response to both.
    """

    reason: str
    code: int = PARSE_ERROR
    ident: str | int | None = None
    answerable: bool = True


@dataclass(frozen=True, slots=True)
class Reply:
    """What a dispatcher returns: the body, and the one thing allowed to happen after it is sent.

    `after_send` is 10:983's `ledger.commit(emission)` and `serve_emission.insert(...)`, and it is a
    field rather than a call the dispatcher makes because the dispatcher has no way to know when the
    frame was flushed and no handle it could use to find out. Returning it hands the ordering to the
    one function that does.
    """

    body: Mapping[str, Any]
    after_send: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class Served:
    """What one run of the loop did. Counts rather than a log, for the reason `Step` carries them.

    `committed` is separate from `sent` on purpose: they are equal exactly when every reply that
    carried an `after_send` had it run, and the distance between them is the window 10:981 exists to
    close.
    """

    requests: int = 0
    notifications: int = 0
    refused: int = 0
    sent: int = 0
    committed: int = 0
    stopped_by: str = EOF
    """`EOF` or `PEER_GONE`. A caller turns the second into a non-zero exit and the first into 0."""


class Lines(Protocol):
    """The input seam: one frame at a time, with the cap already applied."""

    async def readline(self) -> Line:
        """The next line, or a `Line` whose `eof()` is true."""
        ...


class Sink(Protocol):
    """The output seam, and the whole contract is in when `send` returns."""

    async def send(self, frame: bytes) -> None:
        """Write one frame and do not return until it has been written AND flushed (10:979)."""
        ...


class Dispatcher(Protocol):
    """What turns a message into a reply. Holds no sink, so it cannot send and cannot commit."""

    async def dispatch(self, message: Request | Notification) -> Reply | None:
        """The reply, or `None` for a message that is owed no response."""
        ...


def encode(message: Mapping[str, Any]) -> bytes:
    """One frame: compact UTF-8 JSON, newline-terminated, strict.

    `ensure_ascii=False` is `gen.budget.RECIPE`'s and 10:331's -- the payload measured against the
    frozen baseline is the real UTF-8 one, and escaping it here would put a different string on the
    wire from the one that was counted. `errors="strict"` is this module's: a frame that cannot be
    encoded is one that must not be sent, and the process-wide `errors="replace"` of 10:1553 would
    have sent it with the difference silently substituted.

    `separators` are the recipe's, and `allow_nan=False` because `NaN` and `Infinity` are Python's
    JSON extension rather than JSON -- a peer is entitled to reject them and some do.
    """
    text = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return text.encode("utf-8", errors="strict") + b"\n"


def decode(line: bytes) -> Request | Notification | Malformed:
    """One line to a message. Never raises; every failure is a `Malformed` carrying a reason.

    The clauses are in the order a reader can act on them, which is also the order that decides
    whether an answer is owed: a line that is not JSON has no id to answer to, a batch has many, and
    a frame missing `method` may still have an id worth answering to.
    """
    stripped = line.strip()
    if not stripped:
        return Malformed("blank line", answerable=False)
    try:
        text = stripped.decode("utf-8")
    except UnicodeDecodeError as exc:
        return Malformed(f"not UTF-8: {exc}")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return Malformed(f"not JSON: {exc}")
    if isinstance(parsed, list):
        return Malformed("a batch: this transport carries one message per frame", INVALID_REQUEST)
    if not isinstance(parsed, dict):
        return Malformed("not a JSON-RPC object", INVALID_REQUEST)
    return _message(parsed)


def _message(parsed: Mapping[str, Any]) -> Request | Notification | Malformed:
    """A parsed object to a message. Addressing is settled first, because it decides the rest.

    Whether an answer is owed is a property of the frame and not of what is wrong with it, so it
    is computed once here and handed to every clause below -- which is what keeps a broken
    notification silent and a broken request answered.
    """
    ident = parsed.get("id")
    has_id = "id" in parsed and isinstance(ident, str | int) and not isinstance(ident, bool)
    answerable = has_id or "method" not in parsed
    recovered: str | int | None = ident if has_id else None

    bad = _unaddressable(parsed, recovered, answerable=answerable)
    if bad is not None:
        return bad
    method = str(parsed["method"])
    params = dict(parsed.get("params", {}))
    if "id" not in parsed:
        return Notification(method=method, params=params)
    if not isinstance(ident, str | int) or isinstance(ident, bool):
        return Malformed(f"id is {ident!r}, which no response can address", INVALID_REQUEST)
    return Request(ident=ident, method=method, params=params)


def _unaddressable(
    parsed: Mapping[str, Any], recovered: str | int | None, *, answerable: bool
) -> Malformed | None:
    """The three clauses that make a well-formed JSON object not a message. `None` is a message."""
    if parsed.get("jsonrpc") != JSONRPC:
        return Malformed(
            f"jsonrpc is {parsed.get('jsonrpc')!r}, not {JSONRPC!r}",
            INVALID_REQUEST,
            recovered,
            answerable,
        )
    method = parsed.get("method")
    if not isinstance(method, str) or not method:
        return Malformed("no method", INVALID_REQUEST, recovered, answerable)
    if not isinstance(parsed.get("params", {}), dict):
        return Malformed(
            "params is not an object: MCP carries named arguments only",
            INVALID_PARAMS,
            recovered,
            answerable,
        )
    return None


def result(ident: str | int, payload: Mapping[str, Any]) -> dict[str, Any]:
    """A success response, in the key order the spec prints."""
    return {"jsonrpc": JSONRPC, "id": ident, "result": dict(payload)}


def failure(
    ident: str | int | None, code: int, message: str, *, data: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """An error response. A null `id` is legal and is what an unparseable frame is answered with."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = dict(data)
    return {"jsonrpc": JSONRPC, "id": ident, "error": error}


def negotiate(requested: object) -> str:
    """The version to echo on `initialize`: the peer's if we support it, ours otherwise.

    The spec's rule, and the reason it is a function rather than an equality: a client asking for a
    revision this build does not carry is not an error, and answering with an error rather than with
    a version is how a host that would have worked at 2024-11-05 fails to connect at all.
    """
    if isinstance(requested, str) and requested in SUPPORTED_VERSIONS:
        return requested
    return PROTOCOL_VERSION


def initialize_result(*, instructions: str | None = None) -> dict[str, Any]:
    """The `initialize` result body, minus the negotiated version the caller supplies.

    `instructions` is an argument and not something this module builds. 10:864 makes it *"generated,
    capped at 1,000 characters (SV2), and bound to the live catalog"*, and the generator is
    `omniweave.gen.instructions`, in the distribution 02:361 forbids this one from importing. It is
    optional in the protocol, so a server can start without it and lose only the prose -- see
    `uninstructable()`, which says so out loud rather than letting an absent field look intended.
    """
    body: dict[str, Any] = {
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": RELEASE},
    }
    if instructions is not None:
        body["instructions"] = instructions
    return body


def uninstructable() -> tuple[str, ...]:
    """What `initialize` owes and this distribution cannot build. D340 a fourth time; D389.

    `catalog.unservable()` names the three transforms `tools/list` needs; this names the one string
    `initialize` needs, and it is the sharper instance for a reason 10:861 states: the instructions
    arrive *"on a separate track from `tools/list`"*, so they arrive whole *"even in a host that
    defers tool schemas and sends names only"* -- *"the only prose that survives deferral, at
    exactly the moment steering matters most."* A server that cannot build it loses the one channel
    that is guaranteed to be read.
    """
    return (
        "initialize.instructions: omniweave.gen.instructions.instructions(profile=, "
        "default_corpus=) builds both variants and omniweave_serve may not import it",
        "the variant is chosen by omniweave.surface.startup.servable().resolves, which is in the "
        "same distribution",
    )


async def serve(lines: Lines, sink: Sink, dispatcher: Dispatcher) -> Served:
    """Read frames until the input closes. The only function in this package that sends a byte.

    One message at a time and no task group: a second in-flight call would need the admission ladder
    `admission.py` already owns, and starting one here would be a second answer to a question 10:951
    settles with a queue. What this loop guarantees instead is the ordering -- `send` then
    `after_send`, never the other way and never concurrently -- which is the property 10:981 asks
    for.

    **Two protocol rules are enforced here rather than trusted to a dispatcher.** A `Notification`
    is dispatched and whatever it returns is discarded, because JSON-RPC forbids answering one and a
    transport that relied on a handler to remember that would be one bug away from breaking a
    session; `notifications/cancelled` still reaches the dispatcher, which is what 10:965 needs. And
    a write that fails stops the loop **before** the commit, which is 10:981's transport-error row:
    the frame did not arrive, so its emission was never received, so nothing about it is recorded.
    """
    requests = notifications = refused = sent = committed = 0
    stopped_by = EOF
    while True:
        line = await lines.readline()
        if line.eof():
            break
        try:
            if line.truncated:
                refused += 1
                sent += await _refuse(
                    sink, None, INVALID_REQUEST, f"frame above {MAX_FRAME_BYTES} bytes; not parsed"
                )
                continue

            message = decode(line.data)
            if isinstance(message, Malformed):
                refused += 1
                if message.answerable:
                    sent += await _refuse(sink, message.ident, message.code, message.reason)
                continue

            if isinstance(message, Notification):
                notifications += 1
                await dispatcher.dispatch(message)
                continue

            requests += 1
            reply = await dispatcher.dispatch(message)
            if reply is None:
                continue
            await sink.send(encode(reply.body))
            sent += 1
        except (BrokenPipeError, ConnectionResetError):
            stopped_by = PEER_GONE
            break
        if reply.after_send is not None:
            reply.after_send()
            committed += 1
    return Served(
        requests=requests,
        notifications=notifications,
        refused=refused,
        sent=sent,
        committed=committed,
        stopped_by=stopped_by,
    )


async def _refuse(sink: Sink, ident: str | int | None, code: int, reason: str) -> int:
    """Send one error frame and report that a frame was sent. Separated to keep `serve()` flat."""
    await sink.send(encode(failure(ident, code, reason)))
    return 1


@dataclass(slots=True)
class BinaryLines:
    """A `Lines` over a blocking binary stream, read on a worker thread.

    The cap is applied by `readline(limit + 1)` rather than after the fact, and an over-long frame
    is drained to its newline before the next read, so the tail of a refused frame is never parsed
    as the frame after it.
    """

    stream: IO[bytes]
    limit: int = MAX_FRAME_BYTES

    async def readline(self) -> Line:
        """The next line. Blocking work is handed to a thread; see the module docstring for why."""
        return await asyncio.to_thread(self.read_now)

    def read_now(self) -> Line:
        """The blocking half, callable from a test without a loop."""
        data = self.stream.readline(self.limit + 1)
        if not data:
            return Line(b"")
        if data.endswith(b"\n") or len(data) <= self.limit:
            return Line(data)
        while True:
            more = self.stream.readline(self.limit + 1)
            if not more or more.endswith(b"\n"):
                break
        return Line(b"", truncated=True)


@dataclass(slots=True)
class BinarySink:
    """A `Sink` over a blocking binary stream. `send` returns only after the flush."""

    stream: IO[bytes]

    async def send(self, frame: bytes) -> None:
        """Write and flush, on a worker thread, and return when both have happened."""
        await asyncio.to_thread(self.send_now, frame)

    def send_now(self, frame: bytes) -> None:
        """The blocking half. Flushed here and nowhere else, because this is what `send` means."""
        self.stream.write(frame)
        self.stream.flush()


def pipes(*, limit: int = MAX_FRAME_BYTES) -> tuple[BinaryLines, BinarySink]:
    """Bind the transport to this process's stdin and stdout.

    `sys.stdout` is flushed once before the binary buffer underneath it is taken, so anything the
    text layer is holding cannot land in the middle of a frame. After this call nothing may write to
    stdout but the sink: the MCP stdio transport reserves the stream for protocol messages, and
    15:446 already sends this framework's own console records to stderr for the same reason --
    *"stdout is the machine channel"*.
    """
    sys.stdout.flush()
    return BinaryLines(sys.stdin.buffer, limit=limit), BinarySink(sys.stdout.buffer)
