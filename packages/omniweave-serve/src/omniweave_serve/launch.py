"""The entry point `ow serve` loads: three decided values in, a stdio server, an exit code out.

`omniweave` may not import this distribution and this one may not import `omniweave` (02:350,
02:361). So `ow serve --mcp` runs startup step 5 where it lives, then reaches this function
through the `omniweave.serve` entry-point group that `pyproject.toml` declares, the way the
framework reaches every driver it does not import. Only data crosses the boundary: five
keyword arguments of builtin types, because a type defined on either side is one the other side
cannot name. `corpus` and `corpora` are what `query.QueryCaller` searches.

## WHY `asyncio` IS NAMED HERE, ONCE

`stdio.serve()` is a coroutine and something has to run it. `asyncio.run` is that call, and the
standard library's only one. D344's reasoning covers it, and the exemption is this file's alone:
the dispatcher, the framing and the loop still take their streams as arguments and hold no loop.

## THE EXIT, FROM HOW THE LOOP STOPPED

`stdio.Served.stopped_by` is `EOF` or `PEER_GONE`, and its docstring leaves the mapping to the
caller: *"A caller turns the second into a non-zero exit and the first into 0."* 10:1426 gives
`ow serve` exits 0/1/9, and none of them is a write that failed mid-answer. `PEER_GONE` is 70:
10:1494's *"internal error"*, 10:2185's *"anything else"*. A host that closes its end has shut
the server down, which is 0.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.errors import InternalError

from omniweave_serve import listing
from omniweave_serve.dispatch import McpDispatcher, Surface
from omniweave_serve.query import QueryCaller
from omniweave_serve.stdio import EOF, pipes, serve

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_serve.stdio import Dispatcher, Lines, Sink

__all__ = ["OK", "report", "run", "run_on"]

OK: Final[int] = 0


def report(surface: Surface) -> tuple[str, ...]:
    """The startup lines, for stderr. Only what the listing cannot send: D507's unpublished tools.

    `full` lists nine tools and five have no published schema, so `tools/list` sends four. That is
    said once here, where an operator reading the host's server log will see it, rather than left
    for them to find by counting.
    """
    missing = listing.unpublished(surface.profile)
    if not missing:
        return ()
    return (
        f"omniweave: profile {surface.profile} lists {len(missing)} tool(s) with no published "
        f"schema, not sent by tools/list: {', '.join(missing)}",
    )


async def run_on(lines: Lines, sink: Sink, dispatcher: Dispatcher) -> int:
    """`serve()` to an exit code. The seam a test drives, with doubles and no process."""
    served = await serve(lines, sink, dispatcher)
    return OK if served.stopped_by == EOF else InternalError.EXIT


def run(
    *,
    profile: str,
    compact: bool,
    corpus_resolves: bool,
    corpus: str | None,
    corpora: Mapping[str, str],
    stderr: TextIO | None = None,
) -> int:
    """The `omniweave.serve` entry point: select, report, bind this process's stdio, serve.

    `McpDispatcher.create()` runs before `pipes()` takes the streams, so a `ConfigError` from a
    bad profile is raised before anything could have been written to stdout (02:723's *"before
    the transport opens"*), and `ow`'s own error path reports it.
    """
    surface = Surface(profile=profile, compact=compact, corpus_resolves=corpus_resolves)
    caller = QueryCaller(
        corpora={name: Path(path) for name, path in corpora.items()}, default=corpus
    )
    dispatcher = McpDispatcher.create(surface, caller=caller)
    err = stderr or sys.stderr
    for line in report(surface):
        err.write(line + "\n")
    err.flush()
    lines, sink = pipes()
    return asyncio.run(run_on(lines, sink, dispatcher))
