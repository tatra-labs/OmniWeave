"""`omniweave_serve.dispatch`: the first `Dispatcher` in the repository, and what it may not do.

**No loop is started in this file.** Every coroutine here completes without suspending -- the
dispatcher awaits nothing but its `Caller`, and the doubles await nothing at all -- so `_drive()`
steps each one with `send(None)` and reads the `StopIteration`. That keeps `asyncio` out of a test
of a module that does not name it, which is the property `test_serve_stdio.py`'s exemption test
counts, and it makes a coroutine that DID suspend a loud failure here rather than a hang.

The sharpest test is the whole-session one: the real `stdio.serve()` loop, driving this dispatcher,
with a `Caller` whose commit is recorded against the sink's writes. It is the first test in which
10:979-981's ordering runs through a dispatcher that is not a test double.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import omniweave_serve.catalog as catalog_module
import omniweave_serve.dispatch as dispatch_module
import pytest
from omniweave_core.contract import RELEASE
from omniweave_core.errors import ConfigError
from omniweave_serve import listing
from omniweave_serve.dispatch import (
    INITIALIZE,
    PING,
    TOOLS_CALL,
    TOOLS_LIST,
    McpDispatcher,
    Surface,
    uncallable,
)
from omniweave_serve.stdio import (
    INVALID_PARAMS,
    JSONRPC,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SUPPORTED_VERSIONS,
    Dispatcher,
    Line,
    Notification,
    Reply,
    Request,
    Served,
    encode,
    result,
    serve,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

PROFILES = ("default", "full")
T = TypeVar("T")

SWITCHES = [(small, resolves) for small in (True, False) for resolves in (True, False)]


def _drive(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine that never suspends. One that does is a failure, not a hang."""
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    coroutine.close()
    pytest.fail("the coroutine suspended; nothing on this path may wait")


def _dispatcher(
    profile: str = "default", *, small: bool = True, resolves: bool = True, **kwargs: Any
) -> McpDispatcher:
    return McpDispatcher.create(
        Surface(profile=profile, compact=small, corpus_resolves=resolves), **kwargs
    )


def _ask(
    dispatcher: McpDispatcher, method: str, params: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    reply = _drive(dispatcher.dispatch(Request(ident=7, method=method, params=params or {})))
    assert reply is not None
    return dict(reply.body)


# ---------------------------------------------------------------------------------------------
# initialize and ping
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("resolves", [True, False])
def test_initialize_sends_the_listings_variant_for_the_profile(
    profile: str, *, resolves: bool
) -> None:
    body = _ask(_dispatcher(profile, resolves=resolves), INITIALIZE)
    assert body["id"] == 7
    assert body["result"]["instructions"] == listing.instructions(profile, corpus_resolves=resolves)


def test_initialize_puts_the_version_first_and_declares_tools_only() -> None:
    answer = _ask(_dispatcher(), INITIALIZE, {"protocolVersion": "2024-11-05"})["result"]
    assert list(answer) == ["protocolVersion", "capabilities", "serverInfo", "instructions"]
    assert answer["protocolVersion"] == "2024-11-05"
    assert answer["capabilities"] == {"tools": {"listChanged": False}}
    assert answer["serverInfo"] == {"name": SERVER_NAME, "version": RELEASE}


@pytest.mark.parametrize("requested", [None, "2025-11-25", "1999-01-01", 20250326])
def test_a_version_this_build_does_not_carry_negotiates_down_rather_than_failing(
    requested: object,
) -> None:
    params = {} if requested is None else {"protocolVersion": requested}
    answer = _ask(_dispatcher(), INITIALIZE, params)
    assert "error" not in answer
    assert answer["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert SUPPORTED_VERSIONS[0] == PROTOCOL_VERSION


def test_ping_is_answered_with_an_empty_result() -> None:
    assert _ask(_dispatcher(), PING) == {"jsonrpc": JSONRPC, "id": 7, "result": {}}


# ---------------------------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(("small", "resolves"), SWITCHES)
def test_tools_list_is_the_listings_selection_for_every_switch(
    profile: str, *, small: bool, resolves: bool
) -> None:
    answer = _ask(_dispatcher(profile, small=small, resolves=resolves), TOOLS_LIST)["result"]
    assert list(answer) == ["tools"], "no nextCursor: the whole list is one page"
    assert answer["tools"] == list(
        listing.tools_list(profile, compact=small, corpus_resolves=resolves)
    )


def test_the_default_front_door_is_the_four_tools_in_the_catalogues_order() -> None:
    tools = _ask(_dispatcher(), TOOLS_LIST)["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["ow_add", "ow_corpora", "ow_open", "ow_query"]


def test_a_cursor_is_refused_because_none_is_ever_issued() -> None:
    answer = _ask(_dispatcher(), TOOLS_LIST, {"cursor": "anything"})
    assert answer["error"]["code"] == INVALID_PARAMS
    assert "nextCursor" in answer["error"]["message"]


def test_a_caller_that_mutates_a_reply_cannot_reach_the_next_one() -> None:
    dispatcher = _dispatcher()
    first = _ask(dispatcher, TOOLS_LIST)["result"]["tools"]
    first[0]["name"] = "ow_mutated"
    first.clear()
    second = _ask(dispatcher, TOOLS_LIST)["result"]["tools"]
    assert [tool["name"] for tool in second] == ["ow_add", "ow_corpora", "ow_open", "ow_query"]


def test_the_selection_is_taken_once_at_create_and_never_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`listChanged: false` is a promise. Kept by construction: after `create()` the listing is
    never consulted, so a listing that became unreadable mid-process changes nothing sent."""
    dispatcher = _dispatcher()
    before = _ask(dispatcher, TOOLS_LIST)

    def gone(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the listing was read after create()")

    monkeypatch.setattr(listing, "tools_list", gone)
    monkeypatch.setattr(listing, "instructions", gone)
    assert _ask(dispatcher, TOOLS_LIST) == before
    assert "instructions" in _ask(dispatcher, INITIALIZE)["result"]


# ---------------------------------------------------------------------------------------------
# refusals, and the startup side of the line
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method", ["resources/list", "prompts/list", "logging/setLevel", "completion/complete", "x"]
)
def test_a_method_for_a_capability_not_declared_is_not_found(method: str) -> None:
    answer = _ask(_dispatcher(), method)
    assert answer["id"] == 7
    assert answer["error"]["code"] == METHOD_NOT_FOUND
    assert method in answer["error"]["message"]


@pytest.mark.parametrize(
    "method",
    ["notifications/initialized", "notifications/cancelled", "notifications/unheard_of", "ping"],
)
def test_no_notification_is_answered_whatever_its_method(method: str) -> None:
    dispatcher = _dispatcher()
    assert _drive(dispatcher.dispatch(Notification(method=method, params={}))) is None


def test_an_unknown_profile_fails_at_create_before_any_transport() -> None:
    with pytest.raises(ConfigError, match="is not a profile"):
        _dispatcher("everything")


def test_the_shipped_default_needs_no_catalogue_and_only_the_raw_form_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D509. A `pip install` has the listing and not `schema/` (D341, D508), and
    `compact_schemas = true` is the shipped default, so three of the four forms must start with no
    catalogue. The fourth is the catalogue's own object and must still say so, by name."""

    def absent() -> Path:
        raise ConfigError("schema/mcp-tools-v1.json is not readable", fix="reinstall")

    monkeypatch.setattr(catalog_module, "catalogue_path", absent)
    for small, resolves in SWITCHES:
        if (small, resolves) == (False, True):
            with pytest.raises(ConfigError, match="not readable"):
                _dispatcher(small=small, resolves=resolves)
        else:
            assert _ask(_dispatcher(small=small, resolves=resolves), TOOLS_LIST)["result"]["tools"]


# ---------------------------------------------------------------------------------------------
# tools/call: the seam, and what is sent while nothing is plugged into it
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("params", [{}, {"name": ""}, {"name": 3}, {"arguments": {}}])
def test_a_call_without_a_name_is_invalid_params(params: dict[str, Any]) -> None:
    assert _ask(_dispatcher(), TOOLS_CALL, params)["error"]["code"] == INVALID_PARAMS


def test_with_no_caller_a_call_is_refused_naming_what_is_owed() -> None:
    answer = _ask(_dispatcher(), TOOLS_CALL, {"name": "ow_query", "arguments": {"query": "x"}})
    error = answer["error"]
    assert error["code"] == METHOD_NOT_FOUND
    assert "ow_query" in error["message"]
    assert error["data"] == {"owed": uncallable()[0]}


@dataclass
class Committing:
    """A `Caller` that answers and commits through `after_send`, logging both into one list."""

    log: list[str]
    seen: list[tuple[str, Surface]] = field(default_factory=list)

    async def call(self, request: Request, surface: Surface) -> Reply:
        self.seen.append((str(request.params["name"]), surface))
        self.log.append("rendered")
        return Reply(
            body=result(request.ident, {"content": [], "isError": False}),
            after_send=lambda: self.log.append("committed"),
        )


def test_a_caller_receives_the_request_and_the_surface_and_its_reply_is_returned_whole() -> None:
    caller = Committing(log=[])
    dispatcher = _dispatcher(resolves=False, caller=caller)
    reply = _drive(
        dispatcher.dispatch(Request(ident=1, method=TOOLS_CALL, params={"name": "ow_x"}))
    )
    assert reply is not None
    assert reply.after_send is not None
    assert caller.seen == [("ow_x", dispatcher.surface)]
    assert caller.log == ["rendered"], "the dispatcher must not run the commit itself"


def test_this_module_never_calls_after_send() -> None:
    """The commit's one caller is `stdio.serve()` (and `http.Listener._post`). A dispatcher that
    ran one would commit before the flush, which is 10:987's three failures by a fourth route."""
    tree = ast.parse(Path(dispatch_module.__file__).read_text(encoding="utf-8"))
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "after_send" not in names


# ---------------------------------------------------------------------------------------------
# a whole session, through the real loop
# ---------------------------------------------------------------------------------------------


@dataclass
class Scripted:
    lines: list[Line]

    async def readline(self) -> Line:
        return self.lines.pop(0) if self.lines else Line(b"")


@dataclass
class Recorder:
    log: list[str]
    frames: list[dict[str, Any]] = field(default_factory=list)

    async def send(self, frame: bytes) -> None:
        self.frames.append(json.loads(frame))
        self.log.append("sent")


def _frame(ident: int | None, method: str, params: Mapping[str, Any] | None = None) -> Line:
    message: dict[str, Any] = {"jsonrpc": JSONRPC, "method": method}
    if ident is not None:
        message["id"] = ident
    if params is not None:
        message["params"] = dict(params)
    return Line(encode(message))


def test_a_whole_session_through_serve_commits_after_the_send() -> None:
    log: list[str] = []
    caller = Committing(log=log)
    dispatcher: Dispatcher = _dispatcher(caller=caller)
    sink = Recorder(log=log)
    lines = Scripted(
        [
            _frame(1, INITIALIZE, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}}),
            _frame(None, "notifications/initialized"),
            _frame(2, TOOLS_LIST),
            _frame(3, PING),
            _frame(4, TOOLS_CALL, {"name": "ow_query", "arguments": {"query": "q"}}),
            _frame(5, "resources/list"),
        ]
    )
    served = _drive(serve(lines, sink, dispatcher))
    assert served == Served(requests=5, notifications=1, refused=0, sent=5, committed=1)
    assert [frame["id"] for frame in sink.frames] == [1, 2, 3, 4, 5]
    assert log == ["sent", "sent", "sent", "rendered", "sent", "committed", "sent"]
    assert sink.frames[1]["result"]["tools"] == list(
        listing.tools_list("default", compact=True, corpus_resolves=True)
    )
    assert sink.frames[4]["error"]["code"] == METHOD_NOT_FOUND
