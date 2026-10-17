"""`Session`: the emission ledger across one caller's calls, opened by `Corpus.session()`. D867.

18:470-490 prints `Corpus.session(key=None) -> ContextManager[Session]` and 18:783 the `Session`:
`query` and `open` with `Corpus`'s signatures, `stats()` and `clear()`. Inside a session, a block
already sent comes back as an `ow:sent-earlier` pointer instead of its content. Outside one,
*"DEDUP IS OFF, deliberately"* (18:474). The ledger is `answer.dedup.SessionLedger`, the one the
MCP server keeps per stdio session (`omniweave_serve.emission`), and `pack()` reads it.

## Rulings

1. **A session's calls are its `Corpus`'s calls, with the ledger passed in.** `query` and `open`
   run `Corpus._query()` and `Corpus._open()`, the bodies `Corpus.query()` and `Corpus.open()`
   run, so a session cannot answer differently except by withholding. The signatures are
   `Corpus`'s, parameter for parameter.
2. **What a call returns is what it records.** The SDK has no renderer between `pack()` and the
   caller, so nothing is truncated after packing, and every block in `Packed.emissions` reached
   the caller. That is the whole of 10:981's rule, *"anything the truncator dropped [is] NOT
   recorded"*, with no truncator. `open` withholds nothing (D542) and still records what it sent,
   so a block opened is withheld from a later query.
3. **The ledger dies with the `with` block** (18:476). On exit it is cleared, and nothing is
   written to disk: a library that wrote files into a user's project as a side effect of a read
   would be *"a surprise nobody asked for"*.
4. **The default key is a digest of the process id, the corpus and the session's opening time.**
   18:474 prints *"(pid, corpus, process start time)"*. A process's start time is not readable
   without a dependency, and the key names the ledger and nothing reads it back (as
   `omniweave_serve.emission` notes of its own), so the session's opening time stands in.
5. **A compaction marker clears the ledger** (18:487-489). Before each call, a `.compacted` marker
   in the project's `.omniweave/sessions/` that is newer than the last clear clears the ledger,
   and that call's Answer carries the `ledger_reset_by_compaction` degradation. Any marker counts,
   for the reason `omniweave_serve.emission` gives: the SDK is never told the host's session id,
   and clearing a ledger that did not need it costs a re-send, while missing one leaves a pointer to
   content the agent no longer has. A directory that cannot be listed clears too. No
   `omniweave.toml`, so no sessions directory, means no markers. The rule is restated here, not
   imported, because `omniweave` may not import `omniweave_serve` (02:350).
6. **`stats()` is 18:788's five counts**: `calls` this session answered, then `docs`, `blocks`
   and `chars_sent` from the ledger, which `SESSION_LIMITS` bounds, and `saved`, the characters
   withheld over the session's life, the sum of each Answer's `budget.chars_deduped`.
"""

from __future__ import annotations

import hashlib
import os
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.answer.dedup import LEDGER_RESET_KIND, SessionLedger

from omniweave.sdk.api import MAX_BLOCKS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from omniweave_core.answer.pack import Packed
    from omniweave_core.answer.render import Answer
    from omniweave_core.model.enums import Layer
    from omniweave_core.store.types import Expand, Filters

    from omniweave.sdk.api import Corpus

__all__ = ["MARKER_SUFFIX", "Session", "default_key"]

MARKER_SUFFIX: Final[str] = ".compacted"
"""`hooks.precompact.COMPACTED` as a file suffix, the marker `omniweave_serve.emission` reads."""

_KEY_CHARS: Final = 16
"""`hooks.session.session_key()`'s width: sixteen hex characters of a SHA-256."""


def default_key(*, pid: int, corpus: str, opened_ns: int) -> str:
    """18:474's default key, with the session's opening time for the process's (ruling 4)."""
    return hashlib.sha256(f"{pid}:{corpus}:{opened_ns}".encode()).hexdigest()[:_KEY_CHARS]


class Session:
    """18:783's emission ledger for one caller. Not a dataclass: it mutates."""

    __slots__ = ("_calls", "_cleared_at_ns", "_corpus", "_ledger", "_saved", "_sessions", "key")

    def __init__(
        self, corpus: Corpus, key: str | None, *, sessions: Path | None, opened_ns: int
    ) -> None:
        self.key = key or default_key(pid=os.getpid(), corpus=corpus.name, opened_ns=opened_ns)
        self._corpus = corpus
        self._ledger = SessionLedger(self.key)
        self._sessions = sessions
        self._cleared_at_ns = opened_ns
        self._calls = 0
        self._saved = 0

    def query(
        self,
        text: str = "",
        *,
        refs: Sequence[str] = (),
        scope: str | None = None,
        want: str = "passages",
        filters: Filters | None = None,
        mode: str = "find",
        k: int = 20,
        max_blocks: int = MAX_BLOCKS,
        max_chars: int = 24_000,
        expand: Expand | None = None,
        route_hints: object | None = None,
    ) -> Answer:
        """`Corpus.query()`, withholding what this session already sent (rulings 1-2)."""
        reset = self._compacted()
        packed = self._corpus._query(  # the handle's own body (ruling 1)
            text,
            refs=refs,
            scope=scope,
            want=want,
            filters=filters,
            mode=mode,
            k=k,
            max_blocks=max_blocks,
            max_chars=max_chars,
            expand=expand,
            route_hints=route_hints,
            ledger=self._ledger,
            call_ord=self._calls + 1,
            degradations=(LEDGER_RESET_KIND,) if reset else (),
        )
        return self._sent(packed)

    def open(
        self,
        ref: str | Sequence[str],
        *,
        context: int = 1,
        layers: Iterable[Layer] | None = None,
        raw: bool = False,
        want_impact: bool = False,
        max_chars: int = 24_000,
    ) -> Answer:
        """`Corpus.open()`, recording what it sent; `open` withholds nothing (ruling 2)."""
        reset = self._compacted()
        packed = self._corpus._open(  # the handle's own body (ruling 1)
            ref,
            context=context,
            layers=layers,
            raw=raw,
            want_impact=want_impact,
            max_chars=max_chars,
            call_ord=self._calls + 1,
            degradations=(LEDGER_RESET_KIND,) if reset else (),
        )
        return self._sent(packed)

    def stats(self) -> Mapping[str, int]:
        """18:788: calls, docs, blocks, chars_sent, saved (ruling 6)."""
        ledger = self._ledger.stats()
        return MappingProxyType(
            {
                "calls": self._calls,
                "docs": ledger["docs"],
                "blocks": ledger["blocks"],
                "chars_sent": ledger["chars_sent"],
                "saved": self._saved,
            }
        )

    def clear(self) -> None:
        """Forget every emission, so the next call sends everything again."""
        self._ledger.clear()

    def _sent(self, packed: Packed) -> Answer:
        """Record what the call returned (ruling 2), and what it saved."""
        self._calls += 1
        self._ledger.record(packed.emissions.values())
        budget = packed.answer.budget
        self._saved += budget.chars_deduped if budget is not None else 0
        return packed.answer

    def _compacted(self) -> bool:
        """Clear the ledger if a compaction marker is newer than the last clear (ruling 5)."""
        if self._sessions is None:
            return False
        try:
            stamps = [
                marker.stat().st_mtime_ns for marker in self._sessions.glob(f"*{MARKER_SUFFIX}")
            ]
        except OSError:
            self._ledger.clear()
            return True
        newest = max(stamps, default=None)
        if newest is None or newest <= self._cleared_at_ns:
            return False
        self._ledger.clear()
        self._cleared_at_ns = newest
        return True
