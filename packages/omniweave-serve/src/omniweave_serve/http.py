"""The HTTP transport: five routes, four refusals in front of them, and a second meaning for `sent`.

`guard.py` has been complete since W7.3c and `sessions.py` since W7.3d, and **neither has ever had a
caller.** Between them they hold every refusal that happens before a request reaches a dispatcher
and every transition a stateful session has; what was missing is the thing that receives a request.
This is that thing, and writing it is what turns two pure modules into a listener.

## RAW ASGI, BECAUSE THE PLAN SAYS SO AND THE REASON IS NOT STYLE

10:2333:

> The gate is written as **raw ASGI middleware, not a framework `BaseHTTPMiddleware`**, and the
> reason is precise: a buffering middleware breaks the Streamable HTTP SSE stream.

So `Listener.__call__` is the ASGI signature and there is no framework under it. That costs nothing
-- an ASGI application is three arguments and a protocol of five message types -- and it buys two
things beyond the SSE stream: this distribution's declared dependencies stay `core, ports, mcp`
under 11 section 2.3's ceiling, and every test below drives `scope`/`receive`/`send` directly, so
the whole route table, both response shapes and all four refusals are exercised without binding a
port.

## THE SAME `after_send`, AND A SECOND DEFINITION OF THE INSTANT IT FOLLOWS

10:979 annotates one line with both transports:

    await transport.send(answer)          # stdio: written AND flushed. HTTP: body fully written;
                                          # for SSE, after the terminating event.

W7.3l made the stdio half structural: a `Dispatcher` is handed no writer, `Reply.after_send` is the
only place a commit may live, and the loop is its only caller. **That shape carries over unchanged
and the instant underneath it does not.** Here `after_send()` runs after the final
`http.response.body` with `more_body: False` -- which for a JSON response is the body and for an SSE
response is the terminating event, exactly as the comment splits them.

**And over ASGI that instant is weaker than it is over a pipe, which is D390.** `BinarySink.send()`
returns after a real `flush()` syscall; `await send(...)` returns when the *server* accepted the
bytes, and ASGI has no message, no return value and no callback that means the client received
them. 10:979's "body fully written" is the strongest thing this transport can offer and it is not
the same guarantee as the line beside it.

## WHAT THE FOUR REFUSALS COST, AND WHY NONE OF THEM IS HERE

`guard.gate()` is four checks in one order that is a security property (10:2355: *"`Origin` and
`Host` are validated **before auth**"*), and this module calls it and decides nothing. The one thing
it adds is the fifth: a body that never finishes arriving. 10:2371 requires
`[serve] read_timeout_ms` and names no status for it; `guard._REASONS` is a closed vocabulary of
four; `408` is this module asking for a fifth, and D392 is why.

## THE SESSION HAS NO NAME IN THE PLAN

`sessions.py` implements `open`, `touch`, `close` and `reap`, `[serve] max_sessions` caps them, the
emission ledger is keyed on one, and 10:2317's `DELETE` route *"terminate a session explicitly"*
requires a client to say **which** -- and no document in the plan names the header that carries it.
`Mcp-Session-Id` is the MCP Streamable HTTP spelling and it appears nowhere in `_plan/`. D391.

## WHAT IT WILL NOT SERVE

`llms.txt`, by 10:2325: it *"enumerates the whole Action surface including unlisted names, and an
unauthenticated inventory is exactly what the two health endpoints are shaped to avoid."* There is
no route for it and no branch that could grow one. `/healthz` answers three bytes and `/readyz`
answers a boolean, and a `Listener` built with no readiness probe answers `503` rather than claiming
a readiness nothing checked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave_core.config import KEYS

from omniweave_serve.guard import (
    MAX_REQUEST_BYTES,
    MEDIA_TYPE,
    OPEN_ROUTES,
    Rejection,
    gate,
    headers_of,
)
from omniweave_serve.sessions import Opened
from omniweave_serve.stdio import (
    Malformed,
    Notification,
    Request,
    decode,
    encode,
    failure,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from omniweave_serve.sessions import SessionRegistry
    from omniweave_serve.stdio import Dispatcher

__all__ = [
    "DEFAULT_PATH",
    "HEADER_SESSION",
    "HEALTHZ",
    "READYZ",
    "READ_TIMEOUT_STATUS",
    "SSE_MEDIA_TYPE",
    "Body",
    "Listener",
    "Readiness",
    "Response",
    "json_reply",
    "read_body",
    "sse_event",
    "unroutable",
]


DEFAULT_PATH: Final[str] = "/mcp"
"""10:2317's `<--path>` default. The three MCP routes hang off it and the two health ones do not."""

HEALTHZ: Final[str] = OPEN_ROUTES[0]
READYZ: Final[str] = OPEN_ROUTES[1]
"""The two unauthenticated routes, taken from `guard.OPEN_ROUTES` rather than respelled.

`gate()` exempts exactly that tuple from the API key, so a literal here that drifted from it would
be a route this module serves and the guard still demands a key for -- or worse, the reverse.
"""

HEADER_SESSION: Final[str] = "mcp-session-id"
"""The header a stateful session is named by. **Not in the plan** -- D391.

MCP Streamable HTTP's spelling, lowercased because `headers_of()` lowercases and ASGI promises it.
Spelled as a constant rather than inline so that the day `10 §10` names one, there is a single place
that disagrees with it.
"""

SSE_MEDIA_TYPE: Final[str] = "text/event-stream"
"""10:2317's POST default and the GET route's only shape."""

READ_TIMEOUT_STATUS: Final[int] = 408
"""The status a body that stopped arriving is answered with. D392.

`guard._REASONS` is *"the whole vocabulary a refusal may use"* and holds four; 10:2371 requires
`[serve] read_timeout_ms` and gives its breach no status at all. `408` is HTTP's own answer and
`guard` is where the fifth row now lives, because two modules building refusal bodies would be two
homes for the one thing 10:2325 constrains most tightly.
"""

_HEALTHZ_BODY: Final[bytes] = b"ok"
_READYZ_BODY: Final[bytes] = b"ready"
_NOT_READY_BODY: Final[bytes] = b"not ready"
"""10:2321's bodies. *"A load balancer needs a boolean, not an inventory"* -- so no release string,
no corpus names and no counts, which is the same rule `Rejection.body()` keeps one module over."""

_TEXT_MEDIA_TYPE: Final[str] = "text/plain; charset=utf-8"


class Readiness(Protocol):
    """Whether every `[corpora]` store opens read-only. 10:2321's `/readyz`."""

    def __call__(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class Response:
    """One non-streaming answer: a status, a media type and a body, and nothing negotiable.

    Frozen and tiny on purpose. Every route below returns one of these or streams, so the tests can
    assert a route's answer without an ASGI round trip, and the one place that turns a `Response`
    into ASGI messages is `_send_response()`.
    """

    status: int
    body: bytes = b""
    media_type: str = MEDIA_TYPE
    extra: tuple[tuple[str, str], ...] = ()

    def headers(self) -> list[tuple[bytes, bytes]]:
        """The wire headers, `content-length` included because a peer is entitled to it."""
        rows = [
            (b"content-type", self.media_type.encode("latin-1")),
            (b"content-length", str(len(self.body)).encode("ascii")),
        ]
        rows.extend((name.encode("latin-1"), value.encode("latin-1")) for name, value in self.extra)
        return rows


@dataclass(frozen=True, slots=True)
class Body:
    """What came up the wire, or the reason nothing did.

    Three outcomes and not an exception each: a body that arrived, a refusal the caller sends back,
    and a client that went away, which is answered with nothing at all because there is no longer
    anyone to answer.
    """

    data: bytes = b""
    rejection: Rejection | None = None
    disconnected: bool = False

    def usable(self) -> bool:
        """Whether there is a body to parse."""
        return self.rejection is None and not self.disconnected


def json_reply(payload: Mapping[str, Any], *, session_id: str = "") -> Response:
    """One JSON-RPC message as a complete HTTP response.

    Named for what it builds rather than for the flag that selects it: `Listener.json_response` is
    `--json-response`, and one name for the knob and the constructor would make the two impossible
    to grep apart.
    """
    extra = ((HEADER_SESSION, session_id),) if session_id else ()
    return Response(status=200, body=encode(payload).rstrip(b"\n"), extra=extra)


def sse_event(payload: Mapping[str, Any]) -> bytes:
    """One JSON-RPC message as a `text/event-stream` event.

    `encode()` is reused rather than `json.dumps` called again, so an SSE frame and a stdio frame
    are the same bytes by construction -- including `ensure_ascii=False`, which 10:331 makes
    load-bearing for the one payload whose size is frozen. The trailing newline `encode()` adds is
    stripped because SSE supplies its own framing, and it is safe to strip exactly one because
    `json.dumps` escapes every code point below 0x20: a frame carries no interior newline, which
    `test_serve_stdio.py` asserts over four hostile characters.
    """
    return b"data: " + encode(payload).rstrip(b"\n") + b"\n\n"


async def read_body(
    receive: Callable[[], Awaitable[Mapping[str, Any]]],
    *,
    limit: int = MAX_REQUEST_BYTES,
    timeout_ms: int = 0,
) -> Body:
    """Read one request body, bounded and deadlined. 10:2367 and 10:2371.

    **The cap is enforced as the chunks arrive**, not from `content-length`:
    `guard.payload_rejection()` already refuses an over-large declared length and a chunked body
    declares none, so a body that lies or omits is bounded here or nowhere. The running total
    is compared before the chunk is
    kept, so a hostile sender cannot buy one chunk's worth of memory past the limit.

    A timeout of `0` is no deadline, which is what `[serve] read_timeout_ms = 0` should mean by the
    same reading `sessions.TIMEOUT_DISABLED` already has for `--session-timeout`.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        async with asyncio.timeout(timeout_ms / 1000 if timeout_ms > 0 else None):
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    return Body(disconnected=True)
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > limit:
                    return Body(rejection=Rejection(413))
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
    except TimeoutError:
        return Body(rejection=Rejection(READ_TIMEOUT_STATUS))
    return Body(data=b"".join(chunks))


@dataclass(slots=True)
class Listener:
    """The ASGI application. Holds the configuration a listener was opened with and no state.

    `sessions` is `None` under `--stateless`, which 10:2374 defines as *"each request with no
    session
    manager"* -- so the field is the flag, and there is no second boolean that could disagree with
    it. `readiness` is `None` when nothing was supplied, and `/readyz` then answers `503`: a
    readiness endpoint that returns `200` without checking is worse than one that admits it cannot.
    """

    dispatcher: Dispatcher
    path: str = DEFAULT_PATH
    api_key: str = ""
    allowed_origins: Sequence[str] = field(
        default_factory=lambda: _declared("serve.allowed_origins")
    )
    allowed_hosts: Sequence[str] = field(default_factory=lambda: _declared("serve.allowed_hosts"))
    sessions: SessionRegistry | None = None
    json_response: bool = False
    read_timeout_ms: int = 0
    max_request_bytes: int = MAX_REQUEST_BYTES
    readiness: Readiness | None = None
    now_ns: Callable[[], int] = field(default=lambda: 0)
    mint: Callable[[], str] = field(default=lambda: "")

    async def __call__(
        self,
        scope: Mapping[str, Any],
        receive: Callable[[], Awaitable[Mapping[str, Any]]],
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        """ASGI. `http` is served, `lifespan` is answered, anything else is declined.

        `lifespan` is handled rather than ignored because a server whose startup message goes
        unanswered logs that the protocol is unsupported and carries on -- a warning on a line
        nobody reads, which is the failure mode 10:2340 refuses one paragraph over.
        """
        kind = scope.get("type")
        if kind == "lifespan":
            await _lifespan(receive, send)
            return
        if kind != "http":
            return
        await self._http(scope, receive, send)

    async def _http(
        self,
        scope: Mapping[str, Any],
        receive: Callable[[], Awaitable[Mapping[str, Any]]],
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "")).upper()
        headers = headers_of(scope.get("headers", ()))

        rejection = gate(
            headers,
            path=path,
            api_key=self.api_key,
            allowed_origins=self.allowed_origins,
            allowed_hosts=self.allowed_hosts,
        )
        if rejection is not None:
            await _send_response(send, _refusal(rejection))
            return

        if path in OPEN_ROUTES:
            await _send_response(send, self._health(path, method))
            return
        if path != self.path:
            await _send_response(send, Response(status=404, body=b'{"error":"not_found"}'))
            return
        if method == "DELETE":
            await _send_response(send, self._delete(headers))
            return
        if method == "GET":
            await _send_response(send, self._get())
            return
        if method != "POST":
            await _send_response(send, Response(status=405, body=b'{"error":"method_not_allowed"}'))
            return
        await self._post(headers, receive, send)

    def _health(self, path: str, method: str) -> Response:
        """`/healthz` and `/readyz`. Neither reveals anything an unauthenticated caller
        could use."""
        if method not in {"GET", "HEAD"}:
            return Response(status=405, body=b'{"error":"method_not_allowed"}')
        if path == HEALTHZ:
            return Response(status=200, body=_HEALTHZ_BODY, media_type=_TEXT_MEDIA_TYPE)
        ready = self.readiness is not None and self.readiness()
        return Response(
            status=200 if ready else 503,
            body=_READYZ_BODY if ready else _NOT_READY_BODY,
            media_type=_TEXT_MEDIA_TYPE,
        )

    def _delete(self, headers: Mapping[str, tuple[str, ...]]) -> Response:
        """10:2317's fourth route. `204` whether or not the session was live.

        Not `404` for an unknown id, and the reason is the same one every other refusal here keeps:
        a caller who can tell a live session id from a dead one by status code can enumerate them.
        """
        session_id = _session_of(headers)
        if self.sessions is not None and session_id:
            self.sessions.close(session_id)
        return Response(status=204)

    def _get(self) -> Response:
        """10:2318's server-to-client stream, which this build has nothing to put on.

        `405` rather than an empty `200` stream, and the choice is not a stub. A client told the
        stream opened waits on it, and a server with no server-initiated message to send would be
        holding one of 10:2397's capped readers open for a channel that never carries anything --
        the cap exists *because* each session holds a reader. The MCP spec provides for exactly this
        answer, so `405` is the supported way to say there is no such stream rather than a gap.
        """
        return Response(status=405, body=b'{"error":"method_not_allowed"}')

    async def _post(
        self,
        headers: Mapping[str, tuple[str, ...]],
        receive: Callable[[], Awaitable[Mapping[str, Any]]],
        send: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        """One JSON-RPC message in, one response out, and the commit after the last byte.

        The ordering is W7.3l's and the shape is unchanged: the dispatcher is handed no `send`, and
        `after_send` runs here and nowhere else, after the final body message. What differs is what
        that instant means, which is D390 and is stated in the module docstring rather than
        absorbed.
        """
        body = await read_body(
            receive, limit=self.max_request_bytes, timeout_ms=self.read_timeout_ms
        )
        if body.disconnected:
            return
        if body.rejection is not None:
            await _send_response(send, _refusal(body.rejection))
            return

        message = decode(body.data)
        session_id = self._session_for(message, headers)
        if isinstance(message, Malformed):
            if not message.answerable:
                await _send_response(send, Response(status=202))
                return
            answer = failure(message.ident, message.code, message.reason)
            await _send_response(send, json_reply(answer, session_id=session_id))
            return
        if isinstance(message, Notification):
            await self.dispatcher.dispatch(message)
            await _send_response(send, Response(status=202))
            return

        reply = await self.dispatcher.dispatch(message)
        if reply is None:
            await _send_response(send, Response(status=202))
            return
        if self.json_response:
            await _send_response(send, json_reply(reply.body, session_id=session_id))
        else:
            await _send_stream(send, reply.body, session_id=session_id)
        if reply.after_send is not None:
            reply.after_send()

    def _session_for(
        self, message: Request | Notification | Malformed, headers: Mapping[str, tuple[str, ...]]
    ) -> str:
        """The session this request belongs to, minting one on `initialize` and touching otherwise.

        Returns `""` under `--stateless`, which is the whole of 10:2374's compromise: no id means no
        ledger key, which means dedup is off, which `sessions.stateless_degradation()` is the pair
        that reports. A refused `initialize` also returns `""` -- `OW-A-022` belongs to the
        dispatcher's answer and this method does not invent a refusal the caller cannot see.
        """
        if self.sessions is None:
            return ""
        presented = _session_of(headers)
        if presented and self.sessions.touch(presented, at_ns=self.now_ns()):
            return presented
        if not isinstance(message, Request) or message.method != "initialize":
            return ""
        opened = self.sessions.open(presented or self.mint(), at_ns=self.now_ns())
        return opened.session_id if isinstance(opened, Opened) else ""


async def _lifespan(
    receive: Callable[[], Awaitable[Mapping[str, Any]]],
    send: Callable[[Mapping[str, Any]], Awaitable[None]],
) -> None:
    """Answer `lifespan.startup` and `lifespan.shutdown` and hold nothing open between them."""
    while True:
        message = await receive()
        kind = message.get("type")
        if kind == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif kind == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return
        else:  # pragma: no cover - an ASGI server sends only the two
            return


def _declared(key: str) -> tuple[str, ...]:
    """A `[serve]` list key's declared default, read from `KEYS` and never respelled here.

    `serve.allowed_hosts` ships `("localhost", "127.0.0.1", "[::1]")` and `serve.allowed_origins`
    ships empty. Transcribing either would put a loopback literal in a second file -- which is what
    `tools/egress.toml`'s `[[literal]]` clause exists to catch, and it caught it: the rows in that
    register name `config.py` as the one home for these three strings, and a listener that carried
    its own copy would be a second answer to "which Host does this build trust".
    """
    default = KEYS[key].default
    return tuple(str(item) for item in default) if isinstance(default, tuple | list) else ()


def _refusal(rejection: Rejection) -> Response:
    """A `guard.Rejection` as a response. The body is the guard's and never this module's."""
    return Response(status=rejection.status, body=rejection.body())


def _session_of(headers: Mapping[str, tuple[str, ...]]) -> str:
    """The `Mcp-Session-Id` a request names, or `""`. A duplicated header names nothing.

    Duplicates are dropped rather than resolved, for `guard.rebinding_rejection`'s reason one module
    over: two values mean the request one component reads is not the request another one reads, and
    there is no legitimate second session id.
    """
    values = headers.get(HEADER_SESSION, ())
    return values[0] if len(values) == 1 else ""


async def _send_response(
    send: Callable[[Mapping[str, Any]], Awaitable[None]], response: Response
) -> None:
    """Two ASGI messages, and the second one ends the response."""
    await send(
        {"type": "http.response.start", "status": response.status, "headers": response.headers()}
    )
    await send({"type": "http.response.body", "body": response.body, "more_body": False})


async def _send_stream(
    send: Callable[[Mapping[str, Any]], Awaitable[None]],
    payload: Mapping[str, Any],
    *,
    session_id: str = "",
) -> None:
    """One SSE event and its terminating body. 10:979's *"for SSE, after the terminating event"*.

    `content-length` is deliberately absent -- a stream has none -- and `cache-control: no-cache`
    is present because an intermediary that cached an MCP response would serve one session's answer
    to another.
    """
    rows: list[tuple[bytes, bytes]] = [
        (b"content-type", SSE_MEDIA_TYPE.encode("ascii")),
        (b"cache-control", b"no-cache"),
    ]
    if session_id:
        rows.append((HEADER_SESSION.encode("ascii"), session_id.encode("latin-1")))
    await send({"type": "http.response.start", "status": 200, "headers": rows})
    await send({"type": "http.response.body", "body": sse_event(payload), "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})


def unroutable() -> tuple[str, ...]:
    """What `ow serve --http` needs from an operator and no channel can carry. D393.

    `catalog.unservable()` names what the payload needs and `stdio.uninstructable()` what
    `initialize` needs; this names what the *listener* needs. Each row is a decision 10 section 10
    requires, paired with the channel that would have to carry it and does not.
    """
    return (
        "--host/--port: no [serve] key declares a bind address, so listener_refusal() can only be "
        "given one by a flag on a command the CLI has no Action for (D334, D369)",
        "--path: 10:2317 defaults it to /mcp and no [serve] key declares it",
        "--api-key: 10:2333 gives it a flag and OMNIWEAVE_API_KEY, and no [serve] key",
        "--stateless: decides whether a SessionRegistry exists at all, and has no [serve] key",
        "--json-response: decides the POST response shape, is in 18:916's flag list and is absent "
        "from 10:1426's",
        "--session-timeout: sessions.DEFAULT_TIMEOUT_S, a flag with no key (D353)",
    )
