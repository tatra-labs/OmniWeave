"""`SessionEnd`: the last of the six, whose whole job in the plan is four words in a table cell.

10:1856 is the row:

> | `SessionEnd` | -- | -- | **flush; prune > 24 h** | -- |

and 10:1917 is the only prose about it:

> **Pruning does not depend on `SessionEnd` firing.** `SessionEnd` prunes on the way out, and both
> `ow serve` at start-up and `SessionStart` sweep `<sessions>/` for files older than 24 h, plus an
> oldest-first eviction above `SESSIONS_MAX_FILES = 2_000`. **A host that crashes never fires
> `SessionEnd`**, and a directory that only grows is a slow leak in the one place a user never
> looks.

That is the entire specification. Every other event in section 8 has a subsection of its own --
8.3 through 8.6 -- and this one has a row and a caveat, where the caveat is about *not relying on
it*. D426.

## "FLUSH" IS A WORD THAT APPEARS ONCE AND NAMES NOTHING

The word occurs exactly once in 10 section 8, in that cell. And 10:1891 has already ruled out the
thing it usually means:

> A hook never opens a write transaction and never runs the Supervisor. **Its only write is an
> append to its own journal, its lease file or its marker file**, all under `<sessions>/`.

All three are single `write()` calls on handles that are closed before the handler returns, in a
process that exits immediately after. **There is no buffer in a hook to flush.** The only thing
under `<sessions>/` that can be outstanding when a session ends is the `.pending` queue -- edits
appended by `PostToolUse` that no drain has taken -- so that is what is flushed here, and the
reading is recorded rather than assumed.

## THE CRASH 10:1919 NAMES FOR PRUNING IS WORSE FOR THE QUEUE

The plan noticed that a host which crashes never fires this event, and drew the conclusion for the
*directory*: pruning must not depend on it. The same crash does something worse to the *queue*, and
the plan does not draw that one.

10:2063 makes the lease **per deployment** and 10:2054 makes the queue **per session**. A drain is
spawned by whichever hook won the lease, and nothing says whose queue it reads. If it reads only
the spawning session's, then a session whose host died with edits queued and no lease taken is
never drained by anything: its own hooks will not fire again, another session's hooks drain their
own queue, and 10:1918's sweep deletes the file at 24 hours. **The edits are lost, silently, by a
rule written for conversation history.** D427.

A drain that enumerates `*.pending.jsonl` closes it, which is why the queue is its own file and
why `posttool.queue_key()` carries that argument. This handler cannot fix it -- what `ow ingest`
reads is `ow ingest`'s -- but it is the one event that can make the crash case rarer, by draining
whatever is outstanding at the one moment a session is known to be over.

## "PRUNES ON THE WAY OUT" HAS A READING THAT SILENTLY DISABLES `resume`

*"Prunes on the way out"* reads naturally as *cleans up after itself*: the session is over, its
journal is spent, delete it. **Taking that reading would break two of `SessionStart`'s three
sources.** 10:1849's matcher is `compact|resume|fork`, and a host fires `SessionEnd` at exit and
then `SessionStart` with `source=resume` when the user comes back -- to a journal this handler had
deleted. The briefing would be empty, always, and empty is the normal state of a new session, so
nothing would look wrong.

So the prune here is 10:1856's literal *"prune > 24 h"*: the same sweep `ow serve` and
`SessionStart` run, with this session's own files in `keep`. Which means `SessionEnd`'s prune adds
no behaviour at all beyond being a third trigger for it. D429.

## IT SAYS NOTHING

`EVENTS["SessionEnd"].cap` is 0 and `emission()` refuses the event whatever it is handed, so every
return here is a counter and an exit 0. The session is over; there is no model left to tell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave.hooks.envelope import Advice
from omniweave.hooks.posttool import (
    EDITED,
    KIND,
    break_lease,
    command,
    queue_key,
    release_lease,
    take_lease,
)
from omniweave.hooks.session import SWEEP_AGE_S, append, journal_paths, read, sweep

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "ENDED",
    "QUEUE_AGE_MIN",
    "REASON",
    "UNKNOWN_REASON",
    "end_reason",
    "flush",
    "handler",
    "own_files",
    "queued",
    "run_sessionend",
    "unflushed",
]

REASON: Final[str] = "reason"
UNKNOWN_REASON: Final[str] = "unknown"
"""The payload field that says *why* the session ended, and the value when it does not say.

The plan names `trigger` for `PreCompact` (10:1942), `source` for `SessionStart` (10:1954) and
`session_id` and `transcript_path` for the key (10:1899), and names nothing for this event. The
default follows `precompact`'s exactly -- `payload.get("trigger", "unknown")` -- because an
unnamed field is D423's problem again and the same answer is the only consistent one.
"""

ENDED: Final[str] = "ended"
"""The journal record this handler writes, and the only durable trace that the event fired.

Nothing in the plan asks for it. It is here because 10:1919 makes *"did `SessionEnd` fire?"* an
operational question -- a host that crashed never fired it -- and the answer is otherwise
unobtainable: this event has no channel, the counters file does not exist yet (D397), and a prune
that removes nothing leaves no mark. `render_briefing()` groups by 10:1958's four kinds and ignores
this one, so a restored session is not told how the last one ended.
"""

QUEUE_AGE_MIN: Final[int] = SWEEP_AGE_S // 60
"""24 hours, and deliberately not 10:1884's 240 minutes. D428.

*"Every hook read is age-bounded at 240 minutes"* is stated universally and argued narrowly: *"a
stale journal from a dead session must not present days-old work as this task's focus."* That is a
rule about a briefing telling the truth. **A queued edit is not a focus, it is outstanding work**,
and a queue read at 240 minutes reports nothing to drain while the file still holds edits the
24-hour sweep is keeping -- the drain would then never run and the sweep would delete them. The
bound that belongs on a queue is the lifetime of the file it lives in.
"""

_TIER_FLUSHED: Final[str] = "flushed"
_TIER_QUIET: Final[str] = "quiet"
_TIER_HELD: Final[str] = "noop-lease-held"
_TIER_SPAWN_FAILED: Final[str] = "noop-spawn-failed"
_TIER_NO_KEY: Final[str] = "noop-no-key"


def end_reason(payload: Mapping[str, Any]) -> str:
    """`reason` if the host sent a non-empty string, else `"unknown"`."""
    value = payload.get(REASON)
    return value.strip() if isinstance(value, str) and value.strip() else UNKNOWN_REASON


def queued(root: Path, key: str, *, now_ns: int, max_age_min: int = QUEUE_AGE_MIN) -> int:
    """How many edits are sitting in this session's queue. Never raises.

    Counted rather than tested for emptiness because the number is the only thing anyone will ever
    know about a drain that did not happen: a file that exists and holds nothing readable is
    indistinguishable from one that was never written, and both are a legitimate quiet exit.

    **This counts what is in the file and not what is undrained**, because nothing records how far
    a drain got. A high-water mark would need the record schema that does not exist (D405) and the
    counters file that does not exist (D397), so the conservative reading is taken: a queue with
    records in it is a queue worth draining. The cost of being wrong is one redundant `ow ingest`
    per session end, bounded by the same lease that bounds every other drain.
    """
    journal = read(root, queue_key(key), now_ns=now_ns, max_age_min=max_age_min)
    return sum(1 for record in journal.records if record.get(KIND) == EDITED)


def own_files(root: Path, key: str) -> frozenset[str]:
    """The four file names this session owns: both generations of its journal and of its queue.

    Handed to `sweep(keep=...)` so the prune cannot take them, which matters for two different
    reasons at once -- the journal is what `SessionStart(source=resume)` will read when the user
    comes back, and the queue is what the drain this handler just spawned is still reading.
    """
    return frozenset(
        path.name for path in (*journal_paths(root, key), *journal_paths(root, queue_key(key)))
    )


def flush(
    root: Path,
    key: str,
    *,
    now_ns: int,
    pid: int,
    spawn: Callable[[Sequence[str]], bool] | None,
    argv0: str = "",
) -> str:
    """Spawn one drain if this session has queued edits and nobody else is draining. 10:1856.

    The same three steps `PostToolUse` takes, in the same order and through the same functions:
    break an expired lease once, claim, spawn, and release the claim if the spawn failed. One lease
    implementation, one set of edge cases -- including D422's non-atomic break, which is not made
    better or worse by having a second caller.

    Losing the claim here is a **quiet, correct** outcome and not a failure: somebody is already
    draining, and 10:2060's whole point is that one drain per burst is the right number. The
    counter distinguishes it anyway, because *"a session ended with work queued and the lease
    held"* is the state that precedes the loss D427 describes.
    """
    if not queued(root, key, now_ns=now_ns):
        return _TIER_QUIET
    break_lease(root, now_ns=now_ns)
    if not take_lease(root, pid=pid, at_ns=now_ns):
        return _TIER_HELD
    if spawn is None or not spawn(command(argv0)):
        release_lease(root)
        return _TIER_SPAWN_FAILED
    return _TIER_FLUSHED


def run_sessionend(
    payload: Mapping[str, Any],
    *,
    root: Path | None,
    key: str,
    now_ns: int,
    pid: int,
    spawn: Callable[[Sequence[str]], bool] | None = None,
    argv0: str = "",
    swept: bool = True,
) -> Advice:
    """Journal the end, flush the queue, then prune -- and the order is the whole of the care.

    **The prune is last**, for the reason D412 already cost this package once: a sweep that ran
    first would hand this session's own files to the 24-hour rule and then read the queue it had
    just removed, and it would do it silently, because an empty queue is the normal state.

    **The prune runs even when there is no session identity.** 10:1917 is emphatic that pruning is
    not conditional on this event firing; making it conditional on a `session_id` the host may not
    have sent would reintroduce the same leak through a smaller hole.
    """
    if root is None:
        return Advice(counter=_TIER_NO_KEY)
    if not key:
        _prune(root, now_ns=now_ns, keep=frozenset(), swept=swept)
        return Advice(counter=_TIER_NO_KEY)

    append(root, key, {KIND: ENDED, REASON: end_reason(payload)}, at_ns=now_ns, pid=pid)
    tier = flush(root, key, now_ns=now_ns, pid=pid, spawn=spawn, argv0=argv0)
    _prune(root, now_ns=now_ns, keep=own_files(root, key), swept=swept)
    return Advice(counter=tier)


def _prune(root: Path, *, now_ns: int, keep: frozenset[str], swept: bool) -> None:
    """10:1856's *"prune > 24 h"*, which is 10:1918's sweep and nothing more than it."""
    if swept:
        sweep(root, now_ns=now_ns, max_age_s=SWEEP_AGE_S, keep=keep)


def handler(
    root: Path | None,
    *,
    key_of: Callable[[Mapping[str, Any]], str],
    now_ns: Callable[[], int],
    pid: int,
    spawn: Callable[[Sequence[str]], bool] | None = None,
    argv0: str = "",
) -> Callable[[Mapping[str, Any]], Advice]:
    """`run_sessionend` bound to its seams, in the shape `envelope.run()` takes."""

    def bound(payload: Mapping[str, Any]) -> Advice:
        return run_sessionend(
            payload,
            root=root,
            key=key_of(payload),
            now_ns=now_ns(),
            pid=pid,
            spawn=spawn,
            argv0=argv0,
        )

    return bound


def unflushed() -> tuple[str, ...]:
    """What the last of the six does against a reading rather than against a statement."""
    return (
        "what `flush` means. It is one word in one table cell (10:1856), it is the only "
        "description this event has, and 10:1891 has already said a hook's only writes are single "
        "appends to files it closes -- so there is no buffer. The `.pending` queue is the only "
        "outstanding thing under `<sessions>/` and is what is flushed here (D426)",
        "whose queue a drain drains. The lease is per deployment (10:2063) and the queue is per "
        "session (10:2054), and a session whose host crashed with edits queued is drained by "
        "nothing and swept at 24 h -- the crash 10:1919 names for pruning, costing work rather "
        "than disk (D427)",
        "how far back a queue read reaches. 10:1884 bounds every hook read at 240 minutes and "
        "argues it from a briefing's honesty; applied to a queue it hides outstanding edits the "
        "24-hour sweep is still keeping, so this reads at 24 h and says so (D428)",
        "what `prunes on the way out` prunes. Read as cleaning up after itself it deletes the "
        "journal `SessionStart(source=resume)` exists to read, which is a feature lost with no "
        "symptom; read as 10:1856's `prune > 24 h` it adds nothing but a third trigger (D429)",
        "which payload field carries the end reason, and whether the reasons are a closed set. "
        "`precompact` has `trigger`, `sessionstart` has `source`, and this event has neither -- "
        "so `reason` is a guess with the same default the plan gives the one it did name (D423)",
    )
