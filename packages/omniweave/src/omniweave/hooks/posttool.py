"""`PostToolUse`: append the edited path, and spawn one drain per burst rather than one per edit.

10:2053 states the problem and the shape of the answer in two sentences:

> `Edit|Write` fires often, and **one process per edit is how a hook becomes a performance bug.**
> The handler appends the edited path to `<sessions>/<key>.pending` and spawns the detached
> `ow ingest` child **only if no unexpired lease exists** -- one drain per burst.

So there are two writes with two different disciplines: an **append** that every hook makes, and a
**claim** that exactly one hook wins. They fail in opposite ways, and only one of them is safe.

## THE CLAIM IS ATOMIC AND THE BREAK IS NOT

10:2059 is exact about the claim:

> `<sessions>/ingest.lease` is created with `O_CREAT|O_EXCL|O_WRONLY` … **`O_EXCL` is the atomic
> claim: exactly one of N simultaneous hook processes creates it and spawns the child; the rest
> append to `.pending` and exit.**

and then, in the same paragraph, adds an operation with no such guarantee:

> a lease older than its `ttl_ms` **is broken by the next hook** and the break is journalled, so a
> killed child cannot wedge ingestion.

**Breaking is read, decide, unlink, create -- four steps and no atom.** Two hooks that both find the
same expired lease both unlink it, and the second unlink removes the *first one's fresh claim*: two
children, which is the one outcome the whole mechanism exists to prevent. The window is small and it
is exactly the window a wedged child creates, which is when a burst of hooks is most likely. D422.

## THE QUEUE IS THE THING D400 MEASURED

`<key>.pending` is appended to by *N simultaneous hook processes* -- 10:2060 guarantees they exist,
because that is the sentence that justifies the lease. D400 measured what concurrent appends do on
this platform: 23% of records lost at two writers, silently, with zero malformed lines to show for
it. **The coalescing mechanism's input queue is its lossiest part**, and a lost `.pending` line is
an edit that is never re-indexed -- which looks exactly like an edit the user made before the index
was current. D421.

So the queue is written through `session.append()` rather than as bare lines: JSON per line, capped,
stamped with `pid` and `seq`, and countable by `Journal.gaps`. The plan says *"appends the edited
path"* and does not say in what form; every other file under `<sessions>/` is JSON lines, and this
is the one that can report its own losses.

It is also its **own** file rather than a kind of record in the session journal, which is where
W7.4g first put it and which was wrong: a shared file makes edit records and briefing records evict
each other through one 4 MiB rotation, and 10:1884's 240-minute read bound -- written for a briefing
-- would drop queued work the 24-hour sweep is still keeping. `queue_key()` carries that argument.

## THE SELF-INVOCATION RULE IS A SECURITY RULE WEARING A PORTABILITY HAT

10:2066:

> the hook process inherits the host's minimal PATH, so a bare-name spawn dies silently on exactly
> the installs (pipx, `pip --user`, framework Python) that needed the absolute path. **Prefer the
> absolute path this process was launched with; fall back to `python -m omniweave`** …
> `os.path.isabs` on `argv[0]` is load-bearing: a relative `argv[0]` is re-resolved against the
> hook's cwd -- **the checked-out, untrusted repository** -- where a file named `ow` must never
> become the thing we execute.

`command()` is that rule as a pure function of `(argv0, executable)`, so the decision is testable
without spawning anything: absolute wins, everything else falls back to `-m omniweave` on this
interpreter, and a relative `argv[0]` is never resolved.

## WHAT IT DOES NOT IMPORT

`subprocess`, which `TID251` bans outside `omniweave_core.toolchain` and
`omniweave_core.host.subproc`. The spawn arrives as a callable and `spawn_kwargs()` returns the
flags 10:2072 requires as plain integers, so the knowledge lives here and the import does not. A
test with the ban lifted asserts the integers are `subprocess`'s own.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave.hooks.envelope import Advice
from omniweave.hooks.session import append, claim

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "CREATE_NO_WINDOW",
    "DETACHED_PROCESS",
    "EDITED",
    "KIND",
    "LEASE_NAME",
    "LEASE_TTL_MS",
    "PENDING_SUFFIX",
    "Lease",
    "break_lease",
    "command",
    "edited_path",
    "handler",
    "queue_key",
    "read_lease",
    "release_lease",
    "run_posttool",
    "spawn_kwargs",
    "take_lease",
    "uncoalesced",
]

LEASE_NAME: Final[str] = "ingest.lease"
"""10:2058. **Per deployment and not per corpus**, because *"the drain is `ow ingest --scope`, which
is already scope-bounded."*"""

LEASE_TTL_MS: Final[int] = 30_000
"""10:2059's `ttl_ms`, inside the lease body rather than assumed by the reader.

A lease carries its own expiry so a hook from a *newer* build cannot decide an older build's lease
expired early. The constant is the value written; the value honoured is whatever the file says.
"""

PENDING_SUFFIX: Final[str] = ".pending"

KIND: Final[str] = "kind"
EDITED: Final[str] = "edited"
"""The queue record's one discriminator, spelled here because there is nowhere else to spell it.

`precompact.KIND` is the same four letters for the same purpose in another module, and the
duplication is D405 arriving as code: 10 section 8 has no record schema at all, so every writer
names its own fields and every reader guesses them. Two modules agreeing by coincidence is what a
missing table looks like from the inside.
"""

DETACHED_PROCESS: Final[int] = 0x00000008
CREATE_NO_WINDOW: Final[int] = 0x08000000
"""10:2072's Windows flags, as integers, because `subprocess` is `TID251`-banned in this package.

A test with the ban lifted asserts these equal `subprocess.DETACHED_PROCESS` and
`subprocess.CREATE_NO_WINDOW`, so the two spellings cannot drift.
"""

_MODULE_FALLBACK: Final[tuple[str, ...]] = ("-m", "omniweave")
_INGEST: Final[tuple[str, ...]] = ("ingest",)
_SOURCE_SUFFIX: Final[str] = ".py"

_PID: Final[str] = "pid"
_AT_NS: Final[str] = "at_ns"
_TTL_MS: Final[str] = "ttl_ms"

_TIER_DRAINED: Final[str] = "drained"
_TIER_ENQUEUED: Final[str] = "enqueued"
_TIER_BROKE: Final[str] = "drained-after-break"
_TIER_NO_KEY: Final[str] = "noop-no-key"
_TIER_NO_PATH: Final[str] = "noop-no-path"
_TIER_NO_WRITE: Final[str] = "noop-no-write"
_TIER_SPAWN_FAILED: Final[str] = "noop-spawn-failed"

_PATH_FIELDS: Final[tuple[str, ...]] = ("file_path", "path", "filePath", "notebook_path")
"""Where the edited path might be. D423: the plan never names the field.

Four spellings tried in order, because `PostToolUse` fires on `Edit|Write` and the payload shape is
the host's rather than the plan's. A handler that guessed one spelling and was wrong would enqueue
nothing and report success, which is 10:1842's silent exit 0 arriving as a feature.
"""


# ---------------------------------------------------------------------------------------------
# The lease. 10:2058.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Lease:
    """`{"pid": …, "at_ns": …, "ttl_ms": 30000}`, verbatim. 10:2059."""

    pid: int = 0
    at_ns: int = 0
    ttl_ms: int = LEASE_TTL_MS

    def expired(self, now_ns: int) -> bool:
        """Whether the next hook may break this lease. A non-positive `ttl_ms` never expires.

        Never-expires rather than always-expires, because a zero `ttl_ms` is a malformed lease and
        the safe reading of a malformed lease is *"somebody may be draining"*. Spawning a second
        drain is a real cost; waiting for a sweep is not.
        """
        if self.ttl_ms <= 0:
            return False
        return now_ns - self.at_ns > self.ttl_ms * 1_000_000

    def body(self) -> Mapping[str, int]:
        return {_PID: self.pid, _AT_NS: self.at_ns, _TTL_MS: self.ttl_ms}


def read_lease(root: Path) -> Lease | None:
    """The live lease, or `None` when there is none and when there is one that will not parse.

    An unreadable lease is treated as absent, which is the one choice here that can only cost a
    duplicate drain. Treating it as present would let a single corrupt byte stop ingestion for the
    life of the deployment, with nothing to see -- there is no channel on this event (`cap = 0`).
    """
    try:
        raw = (root / LEASE_NAME).read_bytes()
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return Lease(
        pid=_as_int(parsed.get(_PID)),
        at_ns=_as_int(parsed.get(_AT_NS)),
        ttl_ms=_as_int(parsed.get(_TTL_MS)) or LEASE_TTL_MS,
    )


def take_lease(root: Path, *, pid: int, at_ns: int, ttl_ms: int = LEASE_TTL_MS) -> bool:
    """`O_CREAT|O_EXCL|O_WRONLY`. `True` means **this process** is the one that drains. 10:2060."""
    return claim(root, LEASE_NAME, Lease(pid=pid, at_ns=at_ns, ttl_ms=ttl_ms).body())


def break_lease(root: Path, *, now_ns: int) -> bool:
    """Unlink an expired lease so the next claim can succeed. `True` when one was removed.

    **This is the operation 10:2059 asks for and does not make atomic, and D422 is the entry.**
    Read, decide, unlink: two hooks that see one expired lease both unlink, and the second unlink
    can remove the *first one's fresh claim*, so both spawn. `locks.py` already holds the house
    answer -- `O_CREAT|O_EXCL` plus an advisory lock (`fcntl.flock`, `msvcrt.locking`) whose
    *absence* is the staleness test rather than a timestamp -- and taking it here is a decision
    this module may not make.

    What is done instead is to narrow the window: the break is attempted **once**, and a caller that
    loses the claim afterwards stands down rather than retrying. A retry loop would turn a rare race
    into a reliable one.
    """
    lease = read_lease(root)
    if lease is None or not lease.expired(now_ns):
        return False
    try:
        (root / LEASE_NAME).unlink(missing_ok=True)
    except OSError:
        return False
    return True


def release_lease(root: Path) -> bool:
    """The child's unlink when the drain finishes. 10:2062, and not this hook's to call."""
    try:
        (root / LEASE_NAME).unlink(missing_ok=True)
    except OSError:
        return False
    return True


def queue_key(key: str) -> str:
    """The journal key of one session's queue, so the queue is `<key>.pending.jsonl` on disk.

    **10:2054 names a file -- `<sessions>/<key>.pending` -- and the queue belongs in it rather than
    in the session journal**, which is where W7.4g first put it. The two files are described
    separately and they are different kinds of thing, in three ways that matter:

    1. **They share a budget if they share a file.** 10:1914 rotates the journal at 4 MiB and keeps
       *"one generation, then discard"*, so a session busy enough to rotate twice discards the
       oldest generation -- and a mixed file makes edit records and briefing records evict each
       other, which is one instrument destroying another.
    2. **They want different read bounds.** 10:1884 age-bounds every hook read at 240 minutes
       because *"a stale journal from a dead session must not present days-old work as this task's
       focus"* -- a rule about a briefing's honesty. A queued edit is not a focus, it is an
       outstanding piece of work, and dropping it at 240 minutes deletes it from a file the 24-hour
       sweep is still keeping. D428.
    3. **A drain has to be able to find the queues.** The lease is per deployment (10:2063) and the
       queue is per session, so whatever drains must enumerate them; `*.pending.jsonl` is that
       enumeration and a journal holding some records of one kind is not. D427.

    `.pending.jsonl` and not the plan's bare `.pending`, because the file *is* JSON lines -- capped,
    stamped and countable, which is what D421 buys -- and every other JSON-lines file under
    `<sessions>/` says so in its name. A queue named `.pending` alone would be the one file a reader
    must parse whose name does not admit it.
    """
    return f"{key}{PENDING_SUFFIX}"


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# ---------------------------------------------------------------------------------------------
# The self-invocation rule. 10:2066.
# ---------------------------------------------------------------------------------------------


def command(argv0: str, executable: str = "") -> tuple[str, ...]:
    """`ow ingest`'s argv. Absolute `argv[0]` wins; anything else is `python -m omniweave`.

    **A relative `argv[0]` is never resolved and that is the security half of the rule.** 10:2069:
    *"a relative `argv[0]` is re-resolved against the hook's cwd -- the checked-out, untrusted
    repository -- where a file named `ow` must never become the thing we execute."* So the test is
    a shape test and not `shutil.which`: a bare name falls through to the interpreter form rather
    than being looked up.

    **`Path.is_absolute()` and not 10:2069's `os.path.isabs`, because on Windows they disagree on
    exactly the paths this rule exists to reject.** Measured on this machine:

    | `argv[0]` | `os.path.isabs` | `Path.is_absolute` | resolves against |
    |---|---|---|---|
    | `C:\tools\\ow.exe` | True | True | nothing |
    | `\\server\\share\\ow.exe` | True | True | nothing |
    | `\\ow.exe` | **True** | **False** | the **current drive** |
    | `/usr/bin/ow` | **True** | **False** | the **current drive** |

    The last two are drive-relative: Windows resolves them against the drive of the process's cwd,
    which is the untrusted repository 10:2069 names. `os.path.isabs` calls them absolute and would
    execute them; `Path.is_absolute` does not. The stricter answer is also the safe one to be wrong
    about, because the fallback needs nothing from the cwd. D425. (This said *"always works"* when
    W7.4g wrote it, and it did not: there was no `omniweave/__main__.py` until W7.4i. D433.)

    The fallback *"needs no PATH lookup at all"* because `sys.executable` is an absolute path the
    running process already proved works.

    **An absolute `argv[0]` that is a `.py` file is not a launcher, and `python -m` produces one.**
    Measured: under `python -m omniweave`, `sys.argv[0]` is the absolute path of `__main__.py`, so
    10:2068's *"the absolute path this process was launched with"* is a source file -- not an
    executable on Windows, and neither executable nor shebanged in site-packages on POSIX. Without
    this test a hook launched the way this function's own fallback launches it would spawn a drain
    that cannot start. D434.
    """
    if argv0 and Path(argv0).is_absolute() and Path(argv0).suffix.lower() != _SOURCE_SUFFIX:
        return (argv0, *_INGEST)
    return (executable or sys.executable, *_MODULE_FALLBACK, *_INGEST)


def spawn_kwargs() -> Mapping[str, Any]:
    """10:2072's detach flags for this platform, as a mapping a caller hands to `subprocess`.

    Returned rather than applied, because `subprocess` is `TID251`-banned in this package and the
    ban is right: a hook that spawned directly would be the second site in the framework allowed to,
    for a call that `omniweave_core.host.subproc` already knows how to make.
    """
    if sys.platform == "win32":
        return {"creationflags": DETACHED_PROCESS | CREATE_NO_WINDOW}
    return {"start_new_session": True}


# ---------------------------------------------------------------------------------------------
# The handler.
# ---------------------------------------------------------------------------------------------


def edited_path(payload: Mapping[str, Any]) -> str:
    """The path `Edit|Write` touched, or `""`. D423: the plan never names the field.

    `tool_input` first because that is where every documented host puts it, then the top level, then
    four spellings in each. A path is only accepted if it is a non-empty string: a host that sends a
    list of paths sends something this handler does not understand, and enqueuing `str(list)` would
    put an un-ingestable line in the queue.
    """
    holder = payload.get("tool_input")
    sources: tuple[Mapping[str, Any], ...] = (
        (holder, payload) if isinstance(holder, dict) else (payload,)
    )
    for source in sources:
        for field in _PATH_FIELDS:
            value = source.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def run_posttool(
    payload: Mapping[str, Any],
    *,
    root: Path | None,
    key: str,
    now_ns: int,
    pid: int,
    spawn: Callable[[Sequence[str]], bool] | None = None,
    argv0: str = "",
) -> Advice:
    """Append, then claim, then spawn -- and never the other way round. 10:2053.

    **The append comes first and is unconditional.** A hook that claimed before enqueuing would, on
    losing the claim, exit having recorded nothing: the winner's child drains a queue that does not
    yet contain this edit, and the edit is lost until something else touches the file. Enqueue then
    coalesce is the only order in which losing the race is free.

    This event has no channel -- `EVENTS["PostToolUse"].cap` is 0 -- so every return is a counter
    and an exit 0. That is 10:1842, and it is why the `Advice` carries no text.
    """
    path = edited_path(payload)
    if not path:
        return Advice(counter=_TIER_NO_PATH)
    if root is None or not key:
        return Advice(counter=_TIER_NO_KEY)
    queue = queue_key(key)
    if not append(root, queue, {KIND: EDITED, "path": path}, at_ns=now_ns, pid=pid).ok:
        return Advice(counter=_TIER_NO_WRITE)

    broke = break_lease(root, now_ns=now_ns)
    if not take_lease(root, pid=pid, at_ns=now_ns):
        return Advice(counter=_TIER_ENQUEUED)
    if spawn is None or not spawn(command(argv0)):
        release_lease(root)
        return Advice(counter=_TIER_SPAWN_FAILED)
    return Advice(counter=_TIER_BROKE if broke else _TIER_DRAINED)


def handler(
    root: Path | None,
    *,
    key_of: Callable[[Mapping[str, Any]], str],
    now_ns: Callable[[], int],
    pid: int,
    spawn: Callable[[Sequence[str]], bool] | None = None,
    argv0: str = "",
) -> Callable[[Mapping[str, Any]], Advice]:
    """`run_posttool` bound to its seams, in the shape `envelope.run()` takes."""

    def bound(payload: Mapping[str, Any]) -> Advice:
        return run_posttool(
            payload,
            root=root,
            key=key_of(payload),
            now_ns=now_ns(),
            pid=pid,
            spawn=spawn,
            argv0=argv0,
        )

    return bound


def uncoalesced() -> tuple[str, ...]:
    """What this enqueue does against a reading rather than against a statement."""
    return (
        "the `.pending` queue's concurrency. 10:2060 guarantees N simultaneous hook processes and "
        "D400 measured 23% of appends lost at two writers on this platform, so the coalescing "
        "mechanism's input is its lossiest part. Written through `session.append()` so the loss is "
        "countable, which is not the same as prevented (D421)",
        "breaking an expired lease. `O_EXCL` makes the claim atomic and nothing makes the break "
        "atomic: two hooks that see one expired lease both unlink, and the second can remove the "
        "first one's fresh claim. `locks.py` holds the house answer and taking it is a decision "
        "(D422)",
        "which payload field carries the edited path. The plan names `trigger`, `session_id` and "
        "`transcript_path` where it needs them and never names this one, though two handlers "
        "depend on it. Four spellings are tried (D423)",
        "where a broken lease is journalled. 10:2062 says the break is journalled; the lease is "
        "per deployment and the journal is per session, so a deployment-wide event lands in one "
        "session's file and the 24 h sweep takes the only record of a wedged child with it (D424)",
        "what unlinks a lease whose child died. 10:2062 has the child unlink it and 10:2062 has "
        "the next hook break it after `ttl_ms`; a deployment that stops editing between those two "
        "keeps the lease until the sweep, which is 24 h for a 30 s lock",
        r"10:2069's `os.path.isabs`. On Windows it calls `\ow.exe` and `/usr/bin/ow` absolute, and "
        "both resolve against the current drive -- which is the cwd the rule exists to distrust. "
        "`Path.is_absolute()` is used instead and rejects them (D425)",
        "the absolute path this process was launched with. Under `python -m omniweave` it is "
        "`__main__.py`, which is absolute and not executable, so a `.py` argv[0] falls back to "
        "the interpreter form rather than becoming a drain that cannot start (D434)",
    )
