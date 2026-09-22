"""`ow hook <event>`: stdin JSON in, a bounded injection out, every failure path a silent exit 0.

02-architecture.md row 34 gives this package the six handlers and forbids it two things by name:
*"being importable by the Supervisor, or importing it -- a hook must not pay a loop import (G26,
INV-3)"*. 10-interfaces.md section 8.1 adds the distribution boundary: the handlers live here,
*"core plus ports plus office -- **never** `omniweave_serve`, never `mcp`"*.

That second clause is why this package could be written now. D340 separates the MCP server from
three transforms and D389 from the `initialize` string, and none of it reaches here: a hook is on
the other side of the line D340 is about.

`envelope.py` is what all six handlers share -- the channel, the caps, the session key, the kill
switches, the deadline and the `Outcome` that makes a silent failure visible from inside. The
handlers themselves, the journal, the counters file, the markers and the lease are the cells after
this one.
"""

from __future__ import annotations

from omniweave.hooks.envelope import (
    EVENTS,
    EXIT_OK,
    SELF_DEADLINE_MS,
    Advice,
    EventSpec,
    Outcome,
    counter,
    emission,
    run,
    session_key,
    silent_because,
)

__all__ = [
    "EVENTS",
    "EXIT_OK",
    "SELF_DEADLINE_MS",
    "Advice",
    "EventSpec",
    "Outcome",
    "counter",
    "emission",
    "run",
    "session_key",
    "silent_because",
]
