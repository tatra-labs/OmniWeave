"""`ow hook <event>`: stdin JSON in, a bounded injection out, every failure path a silent exit 0.

02-architecture.md row 34 gives this package the six handlers and forbids it two things by name:
*"being importable by the Supervisor, or importing it -- a hook must not pay a loop import (G26,
INV-3)"*. 10-interfaces.md section 8.1 adds the distribution boundary: the handlers live here,
*"core plus ports plus office -- **never** `omniweave_serve`, never `mcp`"*.

That second clause is why this package could be written now. D340 separates the MCP server from
three transforms and D389 from the `initialize` string, and none of it reaches here: a hook is on
the other side of the line D340 is about.

`session.py` is `<sessions>/` -- where it is, the journal, the markers and the sweep -- and
`envelope.py` is what all six handlers share -- the channel, the caps, the session key, the kill
switches, the deadline and the `Outcome` that makes a silent failure visible from inside.
`precompact.py` and `sessionstart.py` are the two halves of the compaction play: 10:1927 gives
`PreCompact` no model-facing channel, so it writes two files and says nothing, and `SessionStart`
is the one hook that speaks. `prompt.py` is the front-load `UserPromptSubmit` runs and the one G26
measures, `pretool.py` is the five-gate scope check -- the only handler here that can stop
something -- and `posttool.py` is the coalescing enqueue that keeps `Edit|Write` from spawning one
child per edit, and `sessionend.py` is the last of the six: the one event with no subsection
of its own, whose job is one undefined word and a sweep two other triggers already run.
`main.py` is `ow hook <event>` itself -- the process around all six, reading and writing bytes
because a piped child on Windows gets cp1252 (D431). It is deliberately not re-exported here: an
entry point is not API. The counters file (D397) and `ow hooks check` (section 8.7) come next.
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
from omniweave.hooks.posttool import (
    LEASE_NAME,
    LEASE_TTL_MS,
    Lease,
    break_lease,
    command,
    queue_key,
    read_lease,
    release_lease,
    run_posttool,
    take_lease,
)
from omniweave.hooks.precompact import (
    BRIEFING,
    BRIEFING_MAX_CHARS,
    COMPACTED,
    KINDS,
    SOURCE_LABELS,
    briefing,
    render_briefing,
    run_precompact,
    strip_cites,
)
from omniweave.hooks.pretool import (
    ENFORCE_ADVISORY,
    ENFORCE_OFF,
    ENFORCE_STEER,
    MIN_SIZE_BYTES,
    OPAQUE_DOC_EXTS,
    Indexed,
    Lookup,
    Target,
    enforce_mode,
    run_pretool,
    ttl_seconds,
)
from omniweave.hooks.prompt import (
    CITE_RE,
    MEDIUM_MAX_CHARS,
    Probes,
    Shapes,
    run_prompt,
    shapes_of,
)
from omniweave.hooks.session import (
    JOURNAL_MAX_BYTES,
    READ_AGE_MIN,
    RECORD_MAX_BYTES,
    SESSIONS_MAX_FILES,
    SWEEP_AGE_S,
    Journal,
    Swept,
    Written,
    anchor,
    append,
    journal_paths,
    read,
    rotate,
    sessions_dir,
    sweep,
    write_marker,
)
from omniweave.hooks.sessionend import (
    ENDED,
    QUEUE_AGE_MIN,
    end_reason,
    flush,
    queued,
    run_sessionend,
)
from omniweave.hooks.sessionstart import (
    SILENT_SOURCES,
    run_sessionstart,
    verified,
)

__all__ = [
    "BRIEFING",
    "BRIEFING_MAX_CHARS",
    "CITE_RE",
    "COMPACTED",
    "ENDED",
    "ENFORCE_ADVISORY",
    "ENFORCE_OFF",
    "ENFORCE_STEER",
    "EVENTS",
    "EXIT_OK",
    "JOURNAL_MAX_BYTES",
    "KINDS",
    "LEASE_NAME",
    "LEASE_TTL_MS",
    "MEDIUM_MAX_CHARS",
    "MIN_SIZE_BYTES",
    "OPAQUE_DOC_EXTS",
    "QUEUE_AGE_MIN",
    "READ_AGE_MIN",
    "RECORD_MAX_BYTES",
    "SELF_DEADLINE_MS",
    "SESSIONS_MAX_FILES",
    "SILENT_SOURCES",
    "SOURCE_LABELS",
    "SWEEP_AGE_S",
    "Advice",
    "EventSpec",
    "Indexed",
    "Journal",
    "Lease",
    "Lookup",
    "Outcome",
    "Probes",
    "Shapes",
    "Swept",
    "Target",
    "Written",
    "anchor",
    "append",
    "break_lease",
    "briefing",
    "command",
    "counter",
    "emission",
    "end_reason",
    "enforce_mode",
    "flush",
    "journal_paths",
    "queue_key",
    "queued",
    "read",
    "read_lease",
    "release_lease",
    "render_briefing",
    "rotate",
    "run",
    "run_posttool",
    "run_precompact",
    "run_pretool",
    "run_prompt",
    "run_sessionend",
    "run_sessionstart",
    "session_key",
    "sessions_dir",
    "shapes_of",
    "silent_because",
    "strip_cites",
    "sweep",
    "take_lease",
    "ttl_seconds",
    "verified",
    "write_marker",
]
