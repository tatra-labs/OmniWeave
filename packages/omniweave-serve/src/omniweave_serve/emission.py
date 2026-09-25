"""The emission ledger of one stdio session, and the one `stat` a compaction marker is read by.

10:2376: *"the **emission ledger is keyed on a session identity**"*. Over HTTP the identity is the
`Mcp-Session-Id` `sessions.SessionRegistry` mints. Over stdio there is no header and no second
client: MCP's stdio transport is one host talking to one server process for the life of that
process, so **the process is the session**. `StdioSession` is that session's ledger, its call
count, and the time it was last cleared.

## THE KEY

18:474 gives the SDK's default: *"a stable digest of (pid, corpus, process start time)"*. This is
that recipe without the corpus, because an MCP session spans every corpus the agent queries and
`SessionLedger` already keys each emission by `corpus_id`. The key names the ledger and nothing
reads it back; `serve_emission`'s `session_key` column (10:2615) is the consumer it is shaped for,
and nothing writes that table yet (D533).

## WHY ANY MARKER CLEARS THE LEDGER

10:1948: *"The server clears the ledger when `<key>.compacted` is newer than `ledger.cleared_at`"*,
and the marker is read *"on every call -- one `stat`, not a watcher"*. `<key>` is
`hooks.session.session_key()` over the HOST's `session_id`, and a stdio server is never told that
id: `initialize` does not carry it, and D355 is the same gap for HTTP. So this server cannot find
ITS marker, and it clears on **any** `.compacted` in `<sessions>` newer than its last clear (D534).

That is safe by the ledger's own asymmetry. A marker from another agent's session in the same
deployment clears a ledger that did not need clearing, and the next Answer re-sends a few hundred
characters it could have withheld. A missed marker leaves a pointer to content the agent's
compaction removed, which 10:1937 calls *"strictly worse than re-sending it: the agent Reads the
file"*. The first failure is the only one this rule can make.

A `<sessions>` that cannot be listed is read the same way: the server cannot tell whether a
compaction happened, so it clears. A directory that does not exist has no markers, which is every
deployment whose host never installed the hooks. For those, 10:994's retention window,
`MAX_CALLS_RETAINED = 8`, is the only backstop, as the plan says it is.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.answer.dedup import SessionLedger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from omniweave_core.answer.dedup import Emission

__all__ = ["MARKER_SUFFIX", "StdioSession", "stdio_key"]

MARKER_SUFFIX: Final[str] = ".compacted"
"""`omniweave.hooks.precompact.COMPACTED` as a file suffix, respelled across the layers row.

`omniweave` writes the marker and this distribution reads it, and neither may import the other
(02:350). A test in `omniweave`'s suite asserts the two spellings agree."""

_KEY_CHARS: Final[int] = 16
"""`hooks.session.session_key()`'s width: sixteen hex characters of a SHA-256."""


def stdio_key(*, pid: int, started_ns: int) -> str:
    """18:474's default key without the corpus: a digest of the process and when it started."""
    return hashlib.sha256(f"{pid}:{started_ns}".encode()).hexdigest()[:_KEY_CHARS]


@dataclass(slots=True)
class StdioSession:
    """One stdio session: its ledger, how many `ow_query` calls it has answered, and its last clear.

    `sessions` is `<sessions>`, 10:1893's `.omniweave/sessions/` beside the resolved
    `omniweave.toml`, or `None` when there is none (D403's deployment). `cleared_at_ns` starts at
    the process's start time, so a marker a previous session left behind does not reset a ledger
    that has recorded nothing.
    """

    ledger: SessionLedger
    sessions: Path | None
    cleared_at_ns: int
    calls: int = 0

    @classmethod
    def open(cls, *, sessions: Path | None, pid: int, started_ns: int) -> StdioSession:
        """A fresh session for this process."""
        return cls(
            ledger=SessionLedger(stdio_key(pid=pid, started_ns=started_ns)),
            sessions=sessions,
            cleared_at_ns=started_ns,
        )

    def compacted(self) -> bool:
        """Clear the ledger if a compaction happened since the last clear. `True` if it did.

        Run before every `ow_query` retrieval, which is 10:1950's *"on every call"*. The caller
        records `ledger_reset_by_compaction` when this is `True`.
        """
        if self.sessions is None:
            return False
        try:
            stamps = [
                marker.stat().st_mtime_ns for marker in self.sessions.glob(f"*{MARKER_SUFFIX}")
            ]
        except OSError:
            self.ledger.clear()
            return True
        newest = max(stamps, default=None)
        if newest is None or newest <= self.cleared_at_ns:
            return False
        self.ledger.clear()
        self.cleared_at_ns = newest
        return True

    def commit(self, emissions: Sequence[Emission]) -> None:
        """10:981's `ledger.commit(emission)`. Only ever called from `Reply.after_send`."""
        self.ledger.record(emissions)
