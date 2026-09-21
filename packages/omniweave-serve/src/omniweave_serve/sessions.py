"""Stateful sessions: how many, how long, and what a reap takes with it. 10:2392-2407.

> *"**Sessions are capped, because each one holds a reader.** `[serve] max_sessions` (default
> **64**) bounds concurrent stateful sessions; beyond it a new `initialize` is refused with
> `OW-A-022 / OW_SERVE_OVERLOADED` and a `retry_after_ms`."*

> *"`--session-timeout` (default 3,600 s, `0` disables) reaps idle stateful sessions, and reaping
> clears that session's ledger and journal."*

## WHY A SESSION IS EXPENSIVE, WHICH IS THE ONLY REASON IT IS CAPPED

Not memory in the abstract -- file descriptors, counted. 10:2401: *"each session holds one `Corpus`
handle per corpus it touches, `SESSION_LIMITS` caps that at 4, and 64 x 4 x 3 descriptors per store
(main, `-wal`, `-shm`) is 768 against a default soft limit of 1,024 on macOS."* The cap is
therefore a measurement and not a policy, and `ow doctor --runtime` prints the observed count
against the platform limit so it can be raised on evidence.

The plan states one consequence of that cap as unpriced and this module does not price it either:
64 sessions x 4 corpora is up to 256 held readers at 68 MB each against `12 §4.1`'s budgeted 16.
`12 §4.1` owns that row and R-Q6 is the measurement.

## THE SECOND `OW-A-022`, AND THE `retry_after_ms` THAT CANNOT ALWAYS BE COMPUTED

`admission.py` raises `OW_SERVE_OVERLOADED` when the query queue is full and computes its
`retry_after_ms` from the observed p95 of a snapshot hold. This module raises the same code for a
different ceiling, and the wait is a different quantity: not how long a query runs, but how long
until a session frees. That is exactly computable when reaping is on -- the least-recently-seen
session becomes reapable at `timeout - idle` -- and **not computable at all when it is off**.

`--session-timeout 0` disables reaping, four lines above the sentence requiring the refusal to
carry a `retry_after_ms`. Under that configuration a session ends only by an explicit `DELETE`, so
no number the server could print would be a prediction. `Refused.retry_after_ms` is therefore
`int | None`, and `None` means *"the server cannot say"* -- which HTTP already has a spelling for,
namely omitting `Retry-After`. Inventing 3,600,000 there would advertise a wait that nothing in the
process is going to honour. D354.

## THE ID, AND WHERE ITS ENTROPY COMES FROM

`sess_` plus `omniweave_core.operator.ulid()`, which is `new_run_id()`'s construction one prefix
over. Both inputs are arguments: the clock is injected because `clock.py` says so, and the entropy
because `new_run_id`'s docstring says why -- *"a function that reached for its own randomness would
be one more ambient source to stub"*, and `random` is banned outright.

**Eighty bits, and the length is checked rather than assumed.** A session id is a bearer credential
for the duration of a session: anyone who can guess one can resume another client's conversation,
including on a shared machine where the loopback bind is reachable by every local uid. `ulid()`
raises on an entropy argument of the wrong length, so a caller that passed four bytes gets an error
rather than a short id, and a test here asserts that rather than trusting it.

## WHAT A REAP TAKES, AND WHAT THIS MODULE CANNOT REACH

`SessionLedger.clear()`, which is the ledger half and is in `omniweave_core.answer.dedup` -- on the
near side of the layers row, so it is an ordinary import. The journal half is not: 10 section 8's
journal is written by `ow hook` into `.omniweave/sessions/<key>.journal`, keyed by the AGENT HOST's
session key, and nothing maps that key to an id this server minted. D355.

**`reap()` is a call and never a timer.** The caller decides when it runs, because the one ordering
question the plan leaves open -- may a session with an in-flight call be reaped, when 10 section
3.11(c) commits that call's ledger *after* the transport accepts the response? -- is answerable
only where both facts are held. D356.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.answer.dedup import DEDUP_OFF_MESSAGE, LEDGER_RESET_KIND, SessionLedger
from omniweave_core.config import KEYS
from omniweave_core.errors import ConfigError, InternalError, ResourceLimit
from omniweave_core.operator import ulid

from omniweave_serve.admission import OVERLOADED, elapsed_ms

if TYPE_CHECKING:
    from omniweave_core.config import Config

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "KEY_MAX_SESSIONS",
    "SESSION_ID_PREFIX",
    "TIMEOUT_DISABLED",
    "Opened",
    "Reaped",
    "Refused",
    "SessionRegistry",
    "new_session_id",
    "overloaded",
    "stateless_degradation",
]

KEY_MAX_SESSIONS: Final = "serve.max_sessions"
"""10:2399's cap. A file-descriptor argument, and the only reason a session is scarce."""

DEFAULT_TIMEOUT_S: Final = 3600
"""`--session-timeout`'s default, in seconds.

**A flag with no configuration row**, which is the mirror image of `max_sessions`: a key with no
flag. Two knobs on one object, each reachable through only one of the two channels the framework
offers, and an operator who configures a server in `omniweave.toml` cannot set this one at all.
D353 records it; until it is decided, this is a constructor argument with the flag's default and
nothing reads a `[serve]` key for it, because inventing one would put a value in `KEYS` that
`omniweave.toml.example` would then have to print as though the plan had asked for it.
"""

TIMEOUT_DISABLED: Final = 0
"""10:2394's `0`. Sessions then end only by an explicit `DELETE`, and see D354."""

SESSION_ID_PREFIX: Final = "sess_"
"""`r_` for a run, `res_` for a reservation, `coh_` for a cohort, `sess_` for a session."""


@dataclass(frozen=True, slots=True)
class Opened:
    """A session that exists. `live` is the count including this one."""

    session_id: str
    live: int


@dataclass(frozen=True, slots=True)
class Refused:
    """`OW-A-022` at the session ceiling.

    `retry_after_ms` is `None` when the server cannot predict a free slot, which is every
    configuration with reaping disabled. See this module's docstring; D354 is the entry.
    """

    live: int
    retry_after_ms: int | None


@dataclass(frozen=True, slots=True)
class Reaped:
    """One session that a reap took, and how long it had been idle when it went."""

    session_id: str
    idle_ms: int


def new_session_id(*, wall_ns: int, entropy: bytes) -> str:
    """`sess_` plus a ULID. Both inputs are arguments, for `new_run_id`'s reason.

    `ulid()` refuses an entropy argument that is not exactly `ULID_ENTROPY_BYTES`, so a caller
    that passed too few bytes gets an error instead of a guessable bearer credential.
    """
    return SESSION_ID_PREFIX + ulid(wall_ns, entropy)


def stateless_degradation() -> tuple[str, str]:
    """The `(kind, message)` pair a `--stateless` transport reports, both from core.

    10:2386 states the compromise in the pair itself: *"That `kind` is the nearest legal member,
    not the right one."* `DegradationKind` is closed at twenty-seven members, none of which names a
    ledger that was never opened, so the kind records the consequence and the message carries the
    real cause. Returned as a pair rather than spelled here, because both literals have one home
    and it is `omniweave_core.answer.dedup`.
    """
    return LEDGER_RESET_KIND, DEDUP_OFF_MESSAGE


def overloaded(refused: Refused) -> ResourceLimit:
    """`OW-A-022 / OW_SERVE_OVERLOADED` for a refused `initialize`, naming the knob.

    The same code and the same class as `admission.overloaded()`, and a different knob: that one
    names `max_queued_queries` because a query was turned away, this one names `max_sessions`
    because a session was. `ResourceLimit` is *"the ONE error required to name a knob"* and the
    whole point of `.limit` is that the two refusals send an operator to two different numbers.
    """
    wait = (
        "the server cannot say when one will free: session reaping is disabled"
        if refused.retry_after_ms is None
        else f"retry after {refused.retry_after_ms} ms"
    )
    return ResourceLimit(
        f"the server is holding {refused.live} stateful session(s), which is its ceiling; {wait}",
        limit=KEY_MAX_SESSIONS,
        symbol=OVERLOADED,
        fix=f"ow config set {KEY_MAX_SESSIONS} <n>   # or close a session with DELETE <--path>",
    )


class SessionRegistry:
    """Which sessions are live, when each was last seen, and what each one's ledger holds.

    Four transitions, three of which take the caller's monotonic reading:

    * `open(session_id, at_ns)` -- `Opened` or `Refused`;
    * `touch(session_id, at_ns)` -- a request arrived on an existing session;
    * `close(session_id)` -- the explicit `DELETE` of 10:2317's fourth route;
    * `reap(at_ns)` -- every session idle at or past the timeout, ledgers cleared.

    **The registry mints nothing.** `open()` takes an id, because minting needs entropy and this
    object holds no ambient sources; `new_session_id()` is the constructor and the caller supplies
    both of its arguments. That also lets a transport that inherits a session id from a header --
    which is how MCP Streamable HTTP resumes one -- hand it straight in.

    **An id already live is not a refusal.** `open()` on a known session is a resume: it touches it
    and returns `Opened`, because a client replaying `initialize` on its own session has not asked
    for a second reader and refusing it would consume the ceiling twice for one caller.
    """

    __slots__ = ("_last_seen", "_ledgers", "_max_sessions", "_timeout_s")

    def __init__(self, *, max_sessions: int, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        if max_sessions < 1:
            raise ConfigError(
                f"{KEY_MAX_SESSIONS} is {max_sessions}; a server that admits no session cannot "
                f"serve a stateful transport at all",
                symbol="OW_CONFIG_VALUE",
                fix=f"set {KEY_MAX_SESSIONS} to 1 or more in omniweave.toml, or serve --stateless",
            )
        if timeout_s < 0:
            raise ConfigError(
                f"--session-timeout is {timeout_s}; {TIMEOUT_DISABLED} disables reaping and "
                f"negative means nothing",
                symbol="OW_CONFIG_VALUE",
                fix=f"ow serve --session-timeout {DEFAULT_TIMEOUT_S}   # or 0 to disable reaping",
            )
        self._max_sessions = max_sessions
        self._timeout_s = timeout_s
        self._last_seen: dict[str, int] = {}
        self._ledgers: dict[str, SessionLedger] = {}

    @classmethod
    def shipped(cls, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> SessionRegistry:
        """The registry an unconfigured server runs, with the cap read from `KEYS`."""
        return cls(max_sessions=_shipped_int(KEY_MAX_SESSIONS), timeout_s=timeout_s)

    @classmethod
    def from_config(cls, config: Config, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> SessionRegistry:
        """One key through the layers, and one argument the layers cannot carry (D353)."""
        value = config.get(KEY_MAX_SESSIONS)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(
                f"{KEY_MAX_SESSIONS} resolved to {value!r}, which is not an integer",
                symbol="OW_CONFIG_VALUE",
                fix=f"set {KEY_MAX_SESSIONS} to an integer in omniweave.toml",
            )
        return cls(max_sessions=value, timeout_s=timeout_s)

    @property
    def live(self) -> int:
        """Sessions held right now, each of which is up to four readers."""
        return len(self._last_seen)

    @property
    def reaping(self) -> bool:
        """Whether an idle session ever ends by itself."""
        return self._timeout_s != TIMEOUT_DISABLED

    def open(self, session_id: str, *, at_ns: int) -> Opened | Refused:
        """Admit or refuse one `initialize`. A known id is a resume and never a second session."""
        if not session_id:
            raise InternalError(
                "a session with no id is a --stateless transport, which holds no registry",
                fix="ow doctor --deep --render json   # attach the report: this is an "
                "omniweave bug",
            )
        if session_id in self._last_seen:
            self._last_seen[session_id] = at_ns
            return Opened(session_id=session_id, live=len(self._last_seen))
        if len(self._last_seen) >= self._max_sessions:
            return Refused(
                live=len(self._last_seen), retry_after_ms=self.retry_after_ms(at_ns=at_ns)
            )
        self._last_seen[session_id] = at_ns
        self._ledgers[session_id] = SessionLedger(session_id)
        return Opened(session_id=session_id, live=len(self._last_seen))

    def touch(self, session_id: str, *, at_ns: int) -> bool:
        """Record that a request arrived. `False` if the session is not live."""
        if session_id not in self._last_seen:
            return False
        self._last_seen[session_id] = at_ns
        return True

    def ledger(self, session_id: str) -> SessionLedger | None:
        """This session's emission ledger, or `None` when there is no such session."""
        return self._ledgers.get(session_id)

    def close(self, session_id: str) -> bool:
        """10:2317's `DELETE`. Clears the ledger before dropping it, as a reap does."""
        if session_id not in self._last_seen:
            return False
        self._ledgers.pop(session_id).clear()
        del self._last_seen[session_id]
        return True

    def reap(self, *, at_ns: int) -> tuple[Reaped, ...]:
        """Take every session idle at or past the timeout, least recently seen first.

        Returns what it took, because the caller is the one that records a `Degradation` and the
        one that knows whether a reaped session had work in flight. Reaping disabled takes nothing
        and is not an error: `0` is a configuration, not an omission.
        """
        if not self.reaping:
            return ()
        timeout_ns = self._timeout_s * 1_000_000_000
        due = sorted(
            (seen, key) for key, seen in self._last_seen.items() if at_ns - seen >= timeout_ns
        )
        taken: list[Reaped] = []
        for seen, key in due:
            self._ledgers.pop(key).clear()
            del self._last_seen[key]
            taken.append(Reaped(session_id=key, idle_ms=elapsed_ms(seen, at_ns)))
        return tuple(taken)

    def retry_after_ms(self, *, at_ns: int) -> int | None:
        """Milliseconds until the next session becomes reapable, or `None` if none ever will.

        `None` is the honest answer under `--session-timeout 0` and on an empty registry, and it is
        a value rather than a number because HTTP's own spelling for "we cannot say" is to omit
        `Retry-After` rather than to guess one. D354.
        """
        if not self.reaping or not self._last_seen:
            return None
        oldest = min(self._last_seen.values())
        timeout_ms = self._timeout_s * 1000
        return max(1, timeout_ms - elapsed_ms(oldest, at_ns))


def _shipped_int(key: str) -> int:
    """The declared default for `key`, read from the registry rather than transcribed."""
    default = KEYS[key].default
    if not isinstance(default, int) or isinstance(default, bool):
        raise InternalError(  # pragma: no cover - a registry edit would have to break the kind
            f"{key} is declared {default!r}, which is not an int",
            fix="ow doctor --deep --render json   # attach the report: this is an omniweave bug",
        )
    return default
