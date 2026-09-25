"""The dispatcher: what `initialize`, `ping` and `tools/list` answer, and what `tools/call` owes.

10:977 names this file -- *"`omniweave_serve/dispatch.py` — the ONE place a ledger write
happens."* -- and both transports have taken a `Dispatcher` since W7.3l and W7.3m with nothing in
the repository implementing one. D340's route 2 (W7.3n) put every byte `tools/list` and
`initialize` send into `mcp-listing-v1.json`, so this is the first cell in which a dispatcher can
be written without re-deriving anything `omniweave` owns.

## IT IS HANDED WHAT IT SERVES, AND DECIDES NOTHING ABOUT IT

`Surface` is three values, and none of them is computed here:

| field | decided by | why not here |
|---|---|---|
| `profile` | `[serve] profile`, through `authority.resolve()` | step 5 is `omniweave`'s (D382) |
| `compact` | `[serve] compact_schemas` (`Servable.compact`) | the same step, the same reason |
| `corpus_resolves` | `Servable.resolves` (10:871's selector) | a copy would re-answer D381 |

So the dispatcher's whole configuration is what 02:723 step 5 decided, handed in. A server that
re-read `omniweave.toml` to find its own profile would be a second startup sequence, which is the
defect 02:712's first sentence exists to rule out.

## THE SELECTION HAPPENS ONCE, BEFORE THE TRANSPORT OPENS

`McpDispatcher.create()` selects the `tools` array and the `instructions` string at construction
and keeps them as JSON text. Two reasons, and the second is the one that matters:

1. **Nothing it sends can change during a process.** `capabilities.tools.listChanged` is `false`
   (`stdio.initialize_result`), which is a promise that `tools/list` answers the same way for the
   life of the server; a list selected once is that promise kept by construction.
2. **A bad profile is a startup failure, not a first-call failure.** 02:723 puts step 5's refusals
   *"before the transport opens"*. `listing.tools_list()` raises `ConfigError` for a profile the
   listing does not carry, and raising it from `create()` is what puts it on that side of the line
   -- rather than as the first answer a host receives, after it has already shown the server as
   connected.

Each answer parses the text back, so a caller that mutates a reply cannot reach the next one.

## WHAT IS NOT GATED ON THE LIFECYCLE, AND WHY

MCP's lifecycle has the client send `initialize`, then `notifications/initialized`, then anything
else. This dispatcher answers `tools/list` whether or not `initialize` came first, and that is a
decision rather than an omission: `http.Listener` holds **one** dispatcher for every session and
for `--stateless`, where 10:2374 has no session at all and every POST arrives without one. Lifecycle
state is per-session, `sessions.py` owns sessions, and a dispatcher that tracked it would refuse
every stateless call. So the dispatcher is stateless and the rule it would have enforced is the
client's (*"SHOULD NOT"* in the spec), which is the side the spec puts it on.

## WHAT `tools/call` IS, TODAY

Not built, and said. `tools/call` runs an Action: the `ow_query` retrieval, the `ow_open` resolve,
the `ow_corpora` enumeration and the `ow_add` roster write. `omniweave_core.retrieve` holds the
planner, the channels, fusion and the verdict, and holds no `retrieve()` that composes them;
10:977's `render`/`send`/`commit` needs that first. So `create()` takes a `Caller`, the seam the
owed half plugs into, and without one a call is answered with `METHOD_NOT_FOUND` -- JSON-RPC's
code for a method that *"does not exist / is not available"*, the second half of which is this
build's state -- carrying `uncallable()`'s row as `data`, in `catalog.unservable()`'s idiom. D511.

A `Caller` receives the `Request` and returns a `Reply`, so the one ordering 10:979-981 prints is
unchanged by this file: the caller puts its commit in `Reply.after_send`, and `serve()` runs it
after the flush. This module never runs one itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave_serve import listing as listing_module
from omniweave_serve.stdio import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    Notification,
    Reply,
    Request,
    failure,
    initialize_result,
    negotiate,
    result,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_serve.catalog import Catalogue
    from omniweave_serve.listing import Listing

__all__ = [
    "INITIALIZE",
    "PING",
    "TOOLS_CALL",
    "TOOLS_LIST",
    "Caller",
    "McpDispatcher",
    "Surface",
    "uncallable",
]

INITIALIZE: Final[str] = "initialize"
PING: Final[str] = "ping"
TOOLS_LIST: Final[str] = "tools/list"
TOOLS_CALL: Final[str] = "tools/call"
"""The four request methods answered. Every other request is `METHOD_NOT_FOUND`.

Four because `capabilities` declares `tools` and nothing else (`stdio.initialize_result`): no
`resources`, no `prompts`, no `logging`, no `completions`. A server that answered `resources/list`
with an empty list would be advertising, by answering, a capability it declined to declare.
"""


@dataclass(frozen=True, slots=True)
class Surface:
    """What step 5 decided, as the three values this module reads. See the module docstring."""

    profile: str
    compact: bool
    corpus_resolves: bool


class Caller(Protocol):
    """The `tools/call` seam. Returns the `Reply`; its commit goes in `after_send`, never inline."""

    async def call(self, request: Request, surface: Surface) -> Reply:
        """Answer one `tools/call`. `request.params` is `{"name": ..., "arguments": ...}`."""
        ...


def uncallable() -> tuple[str, ...]:
    """What `tools/call` still needs that this distribution does not hold. D511."""
    return (
        "tools/call runs an Action, and omniweave_core.retrieve holds the planner, channels, "
        "fusion and verdict with no retrieve() composing them; no Caller is wired",
    )


@dataclass(frozen=True, slots=True)
class McpDispatcher:
    """A `stdio.Dispatcher`. Build it with `create()`, which is where the selection happens."""

    surface: Surface
    tools_text: str
    """The `tools` array as JSON text, selected once. Parsed per answer, so no reply aliases it."""
    instructions: str
    caller: Caller | None = None

    @classmethod
    def create(
        cls,
        surface: Surface,
        *,
        caller: Caller | None = None,
        listing: Listing | None = None,
        catalogue: Catalogue | None = None,
    ) -> McpDispatcher:
        """Select what this process serves. Raises `ConfigError` here, before any transport."""
        tools = listing_module.tools_list(
            surface.profile,
            compact=surface.compact,
            corpus_resolves=surface.corpus_resolves,
            listing=listing,
            catalogue=catalogue,
        )
        prose = listing_module.instructions(
            surface.profile, corpus_resolves=surface.corpus_resolves, listing=listing
        )
        return cls(
            surface=surface,
            tools_text=json.dumps(list(tools), ensure_ascii=False),
            instructions=prose,
            caller=caller,
        )

    async def dispatch(self, message: Request | Notification) -> Reply | None:
        """One message to its reply. A notification is owed nothing and gets `None`.

        `notifications/initialized` and `notifications/cancelled` are both accepted and neither
        changes anything: the first because this dispatcher holds no lifecycle state (see the
        module docstring), the second because nothing here is ever in flight -- `serve()` awaits
        one dispatch at a time and none of the four methods answered here does work to cancel.
        """
        if isinstance(message, Notification):
            return None
        if message.method == TOOLS_CALL:
            return await self._call(message)
        body = self._answer(message)
        return Reply(body=body)

    def _answer(self, request: Request) -> dict[str, Any]:
        """The three methods whose answers are fixed at `create()`, and the refusal for the rest."""
        if request.method == INITIALIZE:
            return result(request.ident, self._initialize(request.params))
        if request.method == PING:
            return result(request.ident, {})
        if request.method == TOOLS_LIST:
            if "cursor" in request.params:
                return failure(
                    request.ident,
                    INVALID_PARAMS,
                    "tools/list: this server never issues a nextCursor, so no cursor is valid",
                )
            return result(request.ident, {"tools": json.loads(self.tools_text)})
        return failure(
            request.ident,
            METHOD_NOT_FOUND,
            f"{request.method!r} is not a method this server answers; capabilities declare "
            f"tools only",
        )

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """`protocolVersion` first, as the spec prints the result, then the fixed body."""
        return {
            "protocolVersion": negotiate(params.get("protocolVersion")),
            **initialize_result(instructions=self.instructions),
        }

    async def _call(self, request: Request) -> Reply:
        """Validate the one field every `tools/call` must carry, then hand it to the `Caller`."""
        name = request.params.get("name")
        if not isinstance(name, str) or not name:
            return Reply(
                body=failure(request.ident, INVALID_PARAMS, "tools/call: params.name is required")
            )
        if self.caller is None:
            (owed,) = uncallable()
            return Reply(
                body=failure(
                    request.ident,
                    METHOD_NOT_FOUND,
                    f"tools/call is not available in this build: {name} cannot be run",
                    data={"owed": owed},
                )
            )
        return await self.caller.call(request, self.surface)
