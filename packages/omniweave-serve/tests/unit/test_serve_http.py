"""The listener: five routes, the four refusals that finally have a caller, and SSE.

**Every test here drives ASGI directly.** No port is bound, no server is started and no framework
is imported, which is the same property 10:2333 asks the production code for -- *"raw ASGI
middleware, not a framework `BaseHTTPMiddleware`"* -- seen from the test side: a route table that
needs a socket to exercise is a route table nobody exercises.

The refusals themselves are `test_serve_guard.py`'s and the session transitions are
`test_serve_sessions.py`'s. What only exists once they are joined is the order they run in, the two
response shapes, and the fact that `after_send` means something weaker here than it does over a
pipe.
"""

from __future__ import annotations

import ast
import asyncio
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave_serve.http as http_module
import pytest
from omniweave_core.config import KEYS
from omniweave_core.contract import RELEASE
from omniweave_serve.guard import MAX_REQUEST_BYTES, OPEN_ROUTES, Rejection
from omniweave_serve.http import (
    DEFAULT_PATH,
    HEADER_SESSION,
    HEALTHZ,
    READ_TIMEOUT_STATUS,
    READYZ,
    SSE_MEDIA_TYPE,
    Listener,
    read_body,
    sse_event,
    unroutable,
)
from omniweave_serve.sessions import SessionRegistry
from omniweave_serve.stdio import JSONRPC, Notification, Reply, Request, encode, result

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO = Path(__file__).resolve().parents[4]
KEY = "s3cret"


# ---------------------------------------------------------------------------------------------
# An ASGI driver, and the doubles the routes are exercised against
# ---------------------------------------------------------------------------------------------


@dataclass
class Exchange:
    """Everything one ASGI call produced, in the order the application produced it."""

    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def started(self) -> dict[str, Any]:
        return next(m for m in self.messages if m["type"] == "http.response.start")

    @property
    def status(self) -> int:
        return int(self.started["status"])

    def header(self, name: str) -> str:
        wanted = name.lower().encode("ascii")
        for key, value in self.started["headers"]:
            if key.lower() == wanted:
                return value.decode("latin-1")
        return ""

    @property
    def body(self) -> bytes:
        return b"".join(
            m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"
        )

    def json(self) -> dict[str, Any]:
        return json.loads(self.body)

    def answered(self) -> bool:
        return any(m["type"] == "http.response.start" for m in self.messages)


@dataclass
class Echo:
    """A `Dispatcher` that answers every request and commits through `after_send`."""

    log: list[str] = field(default_factory=list)
    seen: list[Request | Notification] = field(default_factory=list)
    reply: bool = True

    async def dispatch(self, message: Request | Notification) -> Reply | None:
        self.seen.append(message)
        if isinstance(message, Notification) or not self.reply:
            return None
        return Reply(
            body=result(message.ident, {"echo": message.method}),
            after_send=lambda: self.log.append("committed"),
        )


def _listener(**overrides: Any) -> Listener:
    fields: dict[str, Any] = {"dispatcher": Echo(), "api_key": KEY}
    fields.update(overrides)
    return Listener(**fields)


def _scope(
    method: str = "POST",
    path: str = DEFAULT_PATH,
    *,
    headers: Sequence[tuple[bytes, bytes]] | None = None,
    key: str | None = KEY,
) -> dict[str, Any]:
    rows: list[tuple[bytes, bytes]] = [(b"host", b"127.0.0.1:8000")]
    if key is not None:
        rows.append((b"x-api-key", key.encode()))
    if method == "POST":
        rows.append((b"content-type", b"application/json"))
    rows.extend(headers or ())
    return {"type": "http", "method": method, "path": path, "headers": rows}


def _drive(
    app: Listener, scope: Mapping[str, Any], chunks: Sequence[bytes] = (b"",), *, hang: bool = False
) -> Exchange:
    """One ASGI call, driven to completion. `hang` never finishes the body."""
    exchange = Exchange()
    pending = list(chunks)

    async def receive() -> dict[str, Any]:
        if hang:
            await asyncio.sleep(3600)
        if not pending:
            return {"type": "http.disconnect"}
        chunk = pending.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message: Mapping[str, Any]) -> None:
        exchange.messages.append(dict(message))

    asyncio.run(app(scope, receive, send))
    return exchange


def _post(app: Listener, payload: Mapping[str, Any], **kwargs: Any) -> Exchange:
    return _drive(app, _scope(**kwargs), [encode(payload).rstrip(b"\n")])


# ---------------------------------------------------------------------------------------------
# The ordering, and the second meaning of the instant it follows
# ---------------------------------------------------------------------------------------------


def test_the_commit_runs_after_the_last_body_message_and_never_before() -> None:
    """W7.3l's rule, carried to the transport whose response is a stream. The log records the ASGI
    messages and the commit together, so the assertion is on one sequence."""
    log: list[str] = []
    dispatcher = Echo(log=log)
    app = _listener(dispatcher=dispatcher, json_response=True)
    exchange = Exchange()
    pending = [encode({"jsonrpc": JSONRPC, "id": 1, "method": "ping"}).rstrip(b"\n")]

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": pending.pop(0), "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        exchange.messages.append(dict(message))
        log.append(message["type"])

    asyncio.run(app(_scope(), receive, send))
    assert log == ["http.response.start", "http.response.body", "committed"]


def test_the_commit_runs_after_the_terminating_sse_event() -> None:
    """10:979 splits the instant per transport: *"HTTP: body fully written; for SSE, after the
    terminating event."* The terminating event is the `more_body: False` message, so the commit is
    last here for the same structural reason and at a different point."""
    log: list[str] = []
    app = _listener(dispatcher=Echo(log=log))
    pending = [encode({"jsonrpc": JSONRPC, "id": 1, "method": "ping"}).rstrip(b"\n")]
    seen: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": pending.pop(0), "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        seen.append(dict(message))
        log.append(f"{message['type']}:{message.get('more_body', '')}")

    asyncio.run(app(_scope(), receive, send))
    assert log == [
        "http.response.start:",
        "http.response.body:True",
        "http.response.body:False",
        "committed",
    ]
    assert seen[1]["body"].startswith(b"data: ")
    assert seen[2]["body"] == b""


def test_a_dispatcher_is_handed_no_send_over_this_transport_either() -> None:
    """The structural guarantee is the seam's, not the carrier's: `Dispatcher.dispatch` takes one
    argument on both transports, so neither can be given a writer by one of them."""
    app = _listener()
    dispatcher = app.dispatcher
    assert not hasattr(dispatcher, "send")
    tree = _module_tree()
    inner = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dispatch"
    ]
    assert inner, "the listener dispatches"
    assert all(len(call.args) == 1 and not call.keywords for call in inner)


def test_after_send_has_one_call_site_in_this_module_too() -> None:
    calls = [
        node
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "after_send"
    ]
    assert len(calls) == 1


def test_asgi_offers_no_signal_that_the_client_received_anything() -> None:
    """D390, asserted the only way a negative can be. ASGI's `send` returns `None` and carries no
    acknowledgement, so this module never reads its result -- every `await send(...)` is a bare
    statement. A version of this file that believed otherwise would have to bind one."""
    tree = _module_tree()
    bound = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "send"
    ]
    assert bound, "the module does send"
    statements = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)
    }
    for await_node in bound:
        assert id(await_node) in statements, "a send result was bound; ASGI provides none"


# ---------------------------------------------------------------------------------------------
# The route table
# ---------------------------------------------------------------------------------------------


def test_healthz_is_a_boolean_and_not_an_inventory() -> None:
    """10:2325: *"no release string, no corpus list, no document counts."*"""
    exchange = _drive(_listener(), _scope("GET", HEALTHZ, key=None))
    assert exchange.status == 200
    assert exchange.body == b"ok"
    assert RELEASE.encode() not in exchange.body


def test_readyz_is_503_when_the_listener_was_given_no_way_to_check() -> None:
    """A readiness endpoint that answers 200 without checking is worse than one that admits it
    cannot, so the absence of a probe is `not ready` and never `ready`."""
    exchange = _drive(_listener(), _scope("GET", READYZ, key=None))
    assert exchange.status == 503
    assert exchange.body == b"not ready"


def test_readyz_is_200_only_when_the_probe_says_so() -> None:
    assert _drive(_listener(readiness=lambda: True), _scope("GET", READYZ, key=None)).status == 200
    assert _drive(_listener(readiness=lambda: False), _scope("GET", READYZ, key=None)).status == 503


def test_the_health_routes_need_no_api_key_and_the_mcp_route_does() -> None:
    for path in OPEN_ROUTES:
        assert _drive(_listener(), _scope("GET", path, key=None)).status in {200, 503}
    assert _drive(_listener(), _scope("POST", DEFAULT_PATH, key=None)).status == 401


def test_the_health_routes_are_still_behind_the_rebinding_guard() -> None:
    """D349's conservative reading, asserted where it takes effect: 10:2317 gives both routes
    `auth: none` and says nothing about `Origin`, and `gate()` exempts them from the key alone."""
    exchange = _drive(
        _listener(), _scope("GET", HEALTHZ, key=None, headers=[(b"origin", b"https://evil.test")])
    )
    assert exchange.status == 403
    assert exchange.body == b'{"error":"forbidden"}'
    assert b"evil.test" not in exchange.body


def test_an_unknown_path_is_404_and_llms_txt_is_one_of_them() -> None:
    """10:2327: *"`llms.txt` is not served over HTTP"* -- and the way it is not served is that
    there is no route, rather than a branch that refuses one."""
    for path in ("/llms.txt", "/", "/mcp/extra"):
        assert _drive(_listener(), _scope("GET", path)).status == 404
    tree = _module_tree()
    prose = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    routes = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("/")
        and id(node) not in prose
    }
    assert routes == {DEFAULT_PATH}, "the health routes come from guard.OPEN_ROUTES, not a literal"


def test_get_on_the_mcp_path_is_405_because_there_is_no_stream_to_open() -> None:
    assert _drive(_listener(), _scope("GET", DEFAULT_PATH)).status == 405


def test_an_unsupported_method_is_405() -> None:
    assert _drive(_listener(), _scope("PUT", DEFAULT_PATH)).status == 405


def test_delete_answers_204_whether_or_not_the_session_was_live() -> None:
    """Not 404 for an unknown id: a caller who can tell a live session from a dead one by status
    code can enumerate them, which is the rule every other refusal in front of this keeps."""
    registry = SessionRegistry(max_sessions=4)
    registry.open("sess_live", at_ns=0)
    app = _listener(sessions=registry)
    live = _drive(app, _scope("DELETE", headers=[(HEADER_SESSION.encode(), b"sess_live")]))
    dead = _drive(app, _scope("DELETE", headers=[(HEADER_SESSION.encode(), b"sess_never")]))
    assert live.status == dead.status == 204
    assert registry.live == 0


def test_the_path_is_configurable_and_the_health_routes_are_not() -> None:
    app = _listener(path="/rpc")
    assert _drive(app, _scope("GET", DEFAULT_PATH)).status == 404
    assert _drive(app, _scope("GET", "/rpc")).status == 405
    assert _drive(app, _scope("GET", HEALTHZ, key=None)).status == 200


# ---------------------------------------------------------------------------------------------
# The refusals, which finally have a caller
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ([(b"origin", b"https://evil.test")], 403),
        ([(b"host", b"attacker.test")], 403),
        ([(b"content-type", b"text/plain")], 415),
        ([(b"content-length", str(MAX_REQUEST_BYTES + 1).encode())], 413),
    ],
)
def test_each_of_the_four_refusals_reaches_the_wire(
    headers: list[tuple[bytes, bytes]], status: int
) -> None:
    scope = _scope("POST", DEFAULT_PATH)
    if headers[0][0] in {b"host", b"content-type"}:
        scope["headers"] = [row for row in scope["headers"] if row[0] != headers[0][0]]
    scope["headers"] = [*scope["headers"], *headers]
    exchange = _drive(_listener(), scope)
    assert exchange.status == status
    assert exchange.body == Rejection(status).body()


def test_a_missing_key_says_one_word_and_names_no_check() -> None:
    exchange = _drive(_listener(), _scope(key=None))
    assert exchange.status == 401
    assert exchange.body == b'{"error":"unauthorized"}'


def test_a_body_larger_than_it_declared_is_still_capped() -> None:
    """The cap lives in the reader because `content-length` is the sender's claim: a chunked
    body declares none and a lying one declares the wrong thing, so the running total is what
    bounds it."""
    app = _listener(max_request_bytes=16)
    exchange = _drive(app, _scope(), [b"x" * 10, b"y" * 10])
    assert exchange.status == 413


def test_a_body_that_stops_arriving_is_answered_rather_than_held() -> None:
    """D392. 10:2371 requires the deadline and names no status; `408` is HTTP's own answer and the
    word comes from `guard`'s vocabulary rather than from a second one here."""
    app = _listener(read_timeout_ms=10)
    exchange = _drive(app, _scope(), hang=True)
    assert exchange.status == READ_TIMEOUT_STATUS
    assert exchange.body == b'{"error":"request_timeout"}'


def test_a_client_that_disconnects_is_answered_with_nothing() -> None:
    exchange = _drive(_listener(), _scope(), [])
    assert not exchange.answered()


# ---------------------------------------------------------------------------------------------
# JSON-RPC over POST, and the two response shapes
# ---------------------------------------------------------------------------------------------


def test_a_request_is_answered_as_a_stream_by_default() -> None:
    exchange = _post(_listener(), {"jsonrpc": JSONRPC, "id": 1, "method": "ping"})
    assert exchange.status == 200
    assert exchange.header("content-type") == SSE_MEDIA_TYPE
    assert exchange.header("cache-control") == "no-cache"
    assert exchange.body.startswith(b"data: ")
    assert exchange.body.endswith(b"\n\n")
    assert json.loads(exchange.body[len(b"data: ") :])["id"] == 1


def test_json_response_selects_the_other_shape() -> None:
    exchange = _post(_listener(json_response=True), {"jsonrpc": JSONRPC, "id": 1, "method": "ping"})
    assert exchange.header("content-type") == "application/json"
    assert exchange.json()["result"] == {"echo": "ping"}


def test_the_sse_payload_is_the_same_bytes_a_stdio_frame_would_be() -> None:
    """One framing, two carriers. `sse_event()` reuses `encode()` rather than calling `json.dumps`
    again, so `ensure_ascii=False` -- which 10:331 makes load-bearing for the one payload whose
    size is frozen -- cannot differ between the two transports."""
    payload = {"jsonrpc": JSONRPC, "id": 1, "result": {"text": "a — b · c"}}
    assert sse_event(payload) == b"data: " + encode(payload).rstrip(b"\n") + b"\n\n"
    assert "—".encode() in sse_event(payload)


def test_a_notification_is_accepted_with_202_and_no_body() -> None:
    dispatcher = Echo()
    exchange = _post(
        _listener(dispatcher=dispatcher),
        {"jsonrpc": JSONRPC, "method": "notifications/initialized"},
    )
    assert exchange.status == 202
    assert exchange.body == b""
    assert [m.method for m in dispatcher.seen] == ["notifications/initialized"]


def test_a_malformed_frame_is_answered_with_a_jsonrpc_error_and_not_an_http_one() -> None:
    """10:2317's POST route carries JSON-RPC, so a frame that parsed as HTTP and failed as JSON-RPC
    is a `200` with an `error` member. Only the four guard refusals change the status."""
    exchange = _drive(_listener(), _scope(), [b"not json"])
    assert exchange.status == 200
    assert exchange.json()["error"]["code"] == -32700


def test_a_frame_that_is_owed_no_answer_is_202() -> None:
    exchange = _drive(_listener(), _scope(), [b'{"jsonrpc":"2.0","method":9}'])
    assert exchange.status == 202
    assert exchange.body == b""


def test_a_dispatcher_that_returns_nothing_is_202() -> None:
    app = _listener(dispatcher=Echo(reply=False))
    assert _post(app, {"jsonrpc": JSONRPC, "id": 1, "method": "ping"}).status == 202


# ---------------------------------------------------------------------------------------------
# Sessions, and the header the plan does not name
# ---------------------------------------------------------------------------------------------


def test_initialize_mints_a_session_and_names_it_in_the_header() -> None:
    registry = SessionRegistry(max_sessions=4)
    app = _listener(sessions=registry, mint=lambda: "sess_minted", json_response=True)
    exchange = _post(app, {"jsonrpc": JSONRPC, "id": 1, "method": "initialize"})
    assert exchange.header(HEADER_SESSION) == "sess_minted"
    assert registry.live == 1


def test_a_known_session_is_touched_rather_than_opened_a_second_time() -> None:
    registry = SessionRegistry(max_sessions=1)
    registry.open("sess_a", at_ns=0)
    app = _listener(sessions=registry, json_response=True, now_ns=lambda: 5)
    exchange = _post(
        app,
        {"jsonrpc": JSONRPC, "id": 1, "method": "ping"},
        headers=[(HEADER_SESSION.encode(), b"sess_a")],
    )
    assert exchange.header(HEADER_SESSION) == "sess_a"
    assert registry.live == 1


def test_a_stateless_listener_carries_no_session_header_at_all() -> None:
    """10:2374: `--stateless` *"serves each request with no session manager"*, and the field IS the
    flag -- there is no second boolean that could disagree with it."""
    app = _listener(sessions=None, mint=lambda: "sess_never", json_response=True)
    exchange = _post(app, {"jsonrpc": JSONRPC, "id": 1, "method": "initialize"})
    assert exchange.header(HEADER_SESSION) == ""


def test_a_duplicated_session_header_names_nothing() -> None:
    registry = SessionRegistry(max_sessions=4)
    registry.open("sess_a", at_ns=0)
    app = _listener(sessions=registry, json_response=True)
    exchange = _post(
        app,
        {"jsonrpc": JSONRPC, "id": 1, "method": "ping"},
        headers=[(HEADER_SESSION.encode(), b"sess_a"), (HEADER_SESSION.encode(), b"sess_b")],
    )
    assert exchange.header(HEADER_SESSION) == ""
    assert registry.live == 1


def test_a_session_refused_at_the_ceiling_yields_no_header() -> None:
    registry = SessionRegistry(max_sessions=1)
    registry.open("sess_taken", at_ns=0)
    app = _listener(sessions=registry, mint=lambda: "sess_new", json_response=True)
    exchange = _post(app, {"jsonrpc": JSONRPC, "id": 1, "method": "initialize"})
    assert exchange.header(HEADER_SESSION) == ""
    assert registry.live == 1


# ---------------------------------------------------------------------------------------------
# Lifespan, the body reader, and the shape
# ---------------------------------------------------------------------------------------------


def test_the_lifespan_protocol_is_answered_rather_than_ignored() -> None:
    """A server whose startup message goes unanswered logs that the protocol is unsupported and
    carries on -- a warning on a line nobody reads, which 10:2340 refuses one paragraph over."""
    app = _listener()
    incoming = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    out: list[str] = []

    async def receive() -> dict[str, Any]:
        return incoming.pop(0)

    async def send(message: Mapping[str, Any]) -> None:
        out.append(str(message["type"]))

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert out == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


def test_a_websocket_scope_is_declined_without_answering() -> None:
    out: list[Any] = []

    async def receive() -> dict[str, Any]:  # pragma: no cover - never called
        return {"type": "websocket.connect"}

    async def send(message: Mapping[str, Any]) -> None:  # pragma: no cover - never called
        out.append(message)

    asyncio.run(_listener()({"type": "websocket"}, receive, send))
    assert out == []


def test_the_reader_joins_chunks_and_reports_a_disconnect() -> None:
    async def whole() -> Any:
        pending = [
            {"type": "http.request", "body": b"ab", "more_body": True},
            {"type": "http.request", "body": b"cd", "more_body": False},
        ]
        return await read_body(lambda: _answer(pending))

    body = asyncio.run(whole())
    assert body.usable()
    assert body.data == b"abcd"

    async def cut() -> Any:
        pending = [{"type": "http.disconnect"}]
        return await read_body(lambda: _answer(pending))

    gone = asyncio.run(cut())
    assert gone.disconnected
    assert not gone.usable()


async def _answer(pending: list[dict[str, Any]]) -> dict[str, Any]:
    return pending.pop(0)


def _module_tree() -> ast.Module:
    return ast.parse(Path(http_module.__file__).read_text(encoding="utf-8"))


def test_this_module_imports_nothing_from_the_forbidden_distribution() -> None:
    roots: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "omniweave" not in roots


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(http_module.__all__)


def test_the_only_thing_this_module_takes_from_asyncio_is_a_deadline() -> None:
    """The `[[client]]` row in `tools/egress.toml` claims this, and it is the assertion behind it:
    a listener that is CALLED rather than one that listens, holding a dialer it never dials."""
    used = {
        node.attr
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    }
    assert used == {"timeout"}
    named = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Attribute | ast.Name)
    }
    assert named.isdisjoint(
        {"create_server", "open_connection", "sock_connect", "bind", "listen", "socket"}
    )


def test_the_exemptions_and_the_egress_rows_name_the_same_three_files() -> None:
    """The two registers that have to agree about which files may hold a loop, held equal.

    Three since W7.3p: the two transports, and `launch.py`, which runs the loop they are driven by.
    `otlp.py`'s exemption is for `opentelemetry` and not `asyncio`, so it has no row here."""
    root = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    exempt = {
        path
        for path, codes in root["tool"]["ruff"]["lint"]["per-file-ignores"].items()
        if "TID251" in codes and path.startswith("packages/omniweave-serve/src/")
    }
    egress = tomllib.loads((REPO / "tools" / "egress.toml").read_text(encoding="utf-8"))
    declared = {
        row["path"]
        for row in egress["client"]
        if row["module"] == "asyncio" and row["path"].startswith("packages/omniweave-serve/")
    }
    assert declared == {
        "packages/omniweave-serve/src/omniweave_serve/stdio.py",
        "packages/omniweave-serve/src/omniweave_serve/http.py",
        "packages/omniweave-serve/src/omniweave_serve/launch.py",
    }
    assert declared <= exempt


def test_the_open_routes_are_the_guards_own_tuple_and_not_a_second_spelling() -> None:
    assert (HEALTHZ, READYZ) == OPEN_ROUTES


def test_the_read_timeout_status_has_a_word_in_the_guards_vocabulary() -> None:
    """D392's landing place. A refusal with no reason string would raise inside `Rejection.body()`,
    so the vocabulary and the status cannot drift apart silently."""
    assert Rejection(READ_TIMEOUT_STATUS).reason() == "request_timeout"


def test_the_listener_needs_six_operator_decisions_and_no_channel_carries_them() -> None:
    """D393. Four of the six have no `[serve]` key at all, and `ow serve` has no Action, so today
    neither of the framework's two configuration channels reaches this transport."""
    owed = unroutable()
    assert len(owed) == 6
    for absent in ("serve.path", "serve.api_key", "serve.stateless", "serve.json_response"):
        assert absent not in KEYS
    for present in ("serve.allowed_origins", "serve.allowed_hosts", "serve.read_timeout_ms"):
        assert present in KEYS


def test_the_flag_that_selects_the_response_shape_is_in_one_flag_table_and_not_the_other() -> None:
    """D393's sharpest row, read from the two documents. 10:2317 branches the whole POST response
    on `--json-response`; 18:916's flag list has it and 10:1426's does not."""
    interfaces = (REPO / "_plan" / "10-interfaces.md").read_text(encoding="utf-8").split("\n")
    sketch = (REPO / "_plan" / "18-api-sketch.md").read_text(encoding="utf-8").split("\n")
    rows = [line for line in interfaces if line.startswith("| `ow serve`")]
    other = [line for line in sketch if line.startswith("| `ow serve`")]
    assert len(rows) == 1
    assert len(other) == 1
    assert "--json-response" not in rows[0]
    assert "--json-response" in other[0]
    assert "--json-response" in " ".join(line for line in interfaces if line.startswith("| `POST`"))
