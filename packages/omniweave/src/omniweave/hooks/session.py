"""`<sessions>/`: where it is, the append-only journal, the markers, and the sweep that bounds it.

10:1882 makes this directory the whole interface between a server and a hook -- *"the server
appends `<sessions>/<key>.jsonl` on every call. Hooks read that file; they never expect in-process
state."* A hook is a separate process, so there is no other channel; 10:1891 closes the loop from
the other side by forbidding a hook every write except *"an append to its own journal, its lease
file or its marker file, all under `<sessions>/`"*.

## THE APPEND DISCIPLINE IS NOT TRUE ON WINDOWS, AND THE LOSS IS SILENT

10:1913 states the guarantee in one clause:

> each record capped at 4,096 bytes and written with **a single `write()` on a handle opened
> `"a"`** so an interleaved append from a second server process **cannot split a record**.

That is a POSIX sentence. `open(2)` makes the offset-update-plus-write of `O_APPEND` atomic for a
regular file, so on POSIX the clause holds as written. Windows' CRT emulates `_O_APPEND` as a seek
to end followed by a write, and the two are not one operation. Measured on this machine, eight
processes appending 512-byte records to one file under a synchronised start:

| writers | records offered | records intact | lost | malformed lines |
|---:|---:|---:|---:|---:|
| 2 | 600 | 462 | **138 (23%)** | 0 |
| 4 | 1,200 | 644 | **556 (46%)** | 5 |
| 8 | 4,000 | 1,219 | **2,781 (70%)** | 5 |

`os.write` on a raw `O_APPEND` descriptor measures the same, so this is the platform and not
Python's buffering. **The failure is worse than the one the plan defends against.** A split record
is a malformed line, and 10:1912 already has an answer for those -- the reader *"skips and counts"*
them. A lost record leaves nothing to count: at two writers the reader sees **zero** malformed
lines and 138 records that never existed. The plan's only instrument reports 0 where the truth is
138, so the defence is not merely absent, it reads as healthy. D400.

**So every record carries `pid` and `seq`, and the reader returns a gap count.** That does not fix
the loss -- a fix is a decision this module may not take, and `locks.py` already holds the house
answer it would be taken with. What it does is make the loss a number. This is the treatment 16:718
asks for on the deadline (*"half of this item is the instrumentation that makes the breach
visible"*) applied to the other silent failure in this layer.

## WHAT IT IMPORTS: NOTHING FIRST-PARTY, AND THAT IS MEASURED TOO

`<sessions>` is `.omniweave/sessions/` beside the **resolved `omniweave.toml`** (10:1893), and the
`.omniweave` spelling has a home in `omniweave_core.config.CONTROL_DIR`. Importing it costs a hook
**42 ms** -- `omniweave_core.config` drags `tomllib`, `difflib`, `inspect` and
`importlib.resources` in at module scope, and it is not one of G17's nine lazy subpackages, so no
gate bounds it. Against a 400 ms self-deadline that is a tenth of the budget spent learning a
twelve-character string. So the constant is spelled here and a **test** asserts it equals the one
in `config`; a test tree may import across a boundary a hook cannot afford to. D401.

## THE SWEEP IS SPECIFIED OVER A DIRECTORY THAT HOLDS FIVE KINDS OF FILE

10:1918 sweeps *"`<sessions>/` for files older than 24 h, plus an oldest-first eviction above
`SESSIONS_MAX_FILES = 2_000`"*, and the directory holds journals, `.compacted` and `.briefing`
markers, `.pending` queues, `ingest.lease` and `counters.json`. Three of those have lifetimes the
24 h rule contradicts, and eviction by *file* tears a session's group in half. `sweep()` ships the
literal rule with `keep` as an argument and **reports** the orphans it makes. D402.

## WHAT IS NOT HERE

The counters. 10:1992 makes them *"a single `counters.json` read-modify-written under the journal's
own append discipline"*, which D397 records as a sentence whose two halves cannot both hold -- and
D400 now says the discipline it invokes does not hold on Windows either. A writer built against
that sentence would be built twice. The markers are here because they are `os.replace` and carry no
such claim.
"""

from __future__ import annotations

import itertools
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "AT_NS",
    "CONTROL_DIR",
    "JOURNAL_MAX_BYTES",
    "LIVE_SUFFIX",
    "PID",
    "PROJECT_FILE",
    "READ_AGE_MIN",
    "RECORD_MAX_BYTES",
    "ROTATED_SUFFIX",
    "SEQ",
    "SESSIONS_DIR",
    "SESSIONS_MAX_FILES",
    "SWEEP_AGE_S",
    "Journal",
    "Swept",
    "Written",
    "anchor",
    "append",
    "claim",
    "claimed",
    "encode_record",
    "journal_paths",
    "read",
    "rotate",
    "sessions_dir",
    "sweep",
    "unmeasured",
    "write_marker",
]

# ---------------------------------------------------------------------------------------------
# Where. 10:1893, and the one string this module is not allowed to get wrong.
# ---------------------------------------------------------------------------------------------

CONTROL_DIR: Final[str] = ".omniweave"
"""`omniweave_core.config.CONTROL_DIR`, respelled because importing it costs a hook 42 ms.

A test asserts the two are equal. That is the same trade `http.py`'s `_declared()` refuses and for
the opposite reason: a listener has already paid for `config` by the time it binds a socket, and a
hook has a 400 ms budget of which this import is a tenth. D401 records that the gate which makes
`import omniweave_core` cheap (G17) does not reach `omniweave_core.config`.
"""

SESSIONS_DIR: Final[str] = "sessions"
PROJECT_FILE: Final[str] = "omniweave.toml"
GIT_DIR: Final[str] = ".git"

LIVE_SUFFIX: Final[str] = ".jsonl"
ROTATED_SUFFIX: Final[str] = ".1.jsonl"

JOURNAL_MAX_BYTES: Final[int] = 4 * 1024 * 1024
"""10:1914. One generation, then discard: *"a journal is a recent-activity window, not an
archive"*."""

RECORD_MAX_BYTES: Final[int] = 4_096
"""10:1911. Enforced by REFUSING an oversize record, never by cutting one.

A truncated JSON object is an unparseable line, so a writer that trimmed to the cap would be
manufacturing exactly the malformed line 10:1912 tells the reader to skip -- and it would be doing
it deterministically, on the largest records, which are the interesting ones.
"""

SESSIONS_MAX_FILES: Final[int] = 2_000
SWEEP_AGE_S: Final[int] = 24 * 60 * 60
READ_AGE_MIN: Final[int] = 240
"""10:1884: *"every hook read is age-bounded at 240 minutes"* -- not a default a caller picks.

The clause continues *"and never renders a zero-state snapshot as data"*, which is why `read()`
reports `stale` separately from `skipped`: a journal that is entirely older than the window is a
dead session, and a briefing built from it would present days-old work as this task's focus.
"""

AT_NS: Final[str] = "at_ns"
PID: Final[str] = "pid"
SEQ: Final[str] = "seq"
_RESERVED: Final[frozenset[str]] = frozenset({AT_NS, PID, SEQ})

_NS_PER_MIN: Final[int] = 60 * 1_000_000_000
_SEQUENCE = itertools.count()
"""This process's record counter. Per-process by construction, which is the point.

`seq` is only useful next to `pid`: it says how many records *this* writer offered, so a reader can
tell how many of them the platform kept. A shared counter would be one more thing to lose.
"""


# ---------------------------------------------------------------------------------------------
# Results. Every one of them is a value a caller reads instead of an exception it catches.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Written:
    """What one append did. `ok=False` is normal and never an error.

    10:1993's rule for the counters -- *"a failed counter write never blocks the hook"* -- is the
    rule for every write under `<sessions>/`, because the alternative is 10:1842's silent exit 0
    arriving by a different road.
    """

    ok: bool = False
    reason: str = ""
    size: int = 0
    rotated: bool = False


@dataclass(frozen=True, slots=True)
class Journal:
    """A bounded read of one session's journal. Never raises, and says what it could not use.

    Four numbers, because the three ways a record can fail to arrive are different questions:
    `skipped` is a line that parsed badly (10:1912's case, *"a truncated last line after a
    `SIGKILL` is normal, not corruption"*), `stale` is a record outside the 240-minute window, and
    `gaps` is a record that was written and is not here -- D400's loss, counted.
    """

    records: tuple[Mapping[str, Any], ...] = ()
    skipped: int = 0
    stale: int = 0
    gaps: int = 0
    sources: tuple[str, ...] = ()

    def empty(self) -> bool:
        """Whether this is the zero-state 10:1884 forbids rendering as data."""
        return not self.records


@dataclass(frozen=True, slots=True)
class Swept:
    """What one sweep removed, and what it broke doing so.

    `orphaned` is the finding rather than the action: eviction is specified per *file* and a
    session is a *group* of files (`<key>.jsonl`, `<key>.1.jsonl`, `<key>.compacted`,
    `<key>.briefing`, `<key>.pending`), so an oldest-first pass can delete a journal and leave the
    briefing built from it. D402.
    """

    aged: tuple[str, ...] = ()
    evicted: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    kept: int = 0
    failed: int = 0


# ---------------------------------------------------------------------------------------------
# Locating `<sessions>`.
# ---------------------------------------------------------------------------------------------


def anchor(cwd: Path) -> Path | None:
    """The resolved `omniweave.toml`, or `None`. Walks up, stopping at a `.git` directory.

    The stop rule is `omniweave_core.config._walk_up`'s and a test asserts the two agree on the
    same tree. They have to: 10:1893 says `<sessions>` is beside *the resolved* project file, so a
    hook that resolved a different file from the server would be reading a different directory --
    which is 10:1875's out-of-process failure with the two halves one level further apart.
    """
    try:
        here = cwd.resolve()
    except OSError:  # pragma: no cover -- a cwd that vanished mid-call
        return None
    for directory in (here, *here.parents):
        candidate = directory / PROJECT_FILE
        try:
            if candidate.is_file():
                return candidate
            if (directory / GIT_DIR).exists():
                return None
        except OSError:  # pragma: no cover -- an unreadable directory on the way up
            return None
    return None


def sessions_dir(cwd: Path) -> Path | None:
    """`<anchor>/.omniweave/sessions/`, or `None` when no `omniweave.toml` was found.

    **`None` is a real deployment and not an edge case.** `config.load()` resolves from four file
    layers, and a user whose settings live in `$OMNIWEAVE_HOME/config.toml` or in a
    `[tool.omniweave]` table has a working install and no project file at all -- for whom 10:1893's
    *"beside the resolved `omniweave.toml`"* names nothing. Every hook is then silent for the life
    of that install, which is D403 and is exactly the failure 10:1842 makes unreportable.

    The caller treats `None` the way `envelope.session_key` treats `""`: no identity, no state, no
    output, exit 0.
    """
    found = anchor(cwd)
    return None if found is None else found.parent / CONTROL_DIR / SESSIONS_DIR


def journal_paths(root: Path, key: str) -> tuple[Path, Path]:
    """`(live, rotated)` for one session key: `<key>.jsonl` and `<key>.1.jsonl` (10:1914)."""
    return (root / f"{key}{LIVE_SUFFIX}", root / f"{key}{ROTATED_SUFFIX}")


# ---------------------------------------------------------------------------------------------
# Writing.
# ---------------------------------------------------------------------------------------------


def encode_record(record: Mapping[str, Any], *, at_ns: int, pid: int, seq: int) -> bytes:
    """One line, or `b""` when it will not fit. The stamps are applied here and cannot be forged.

    `at_ns`, `pid` and `seq` are written *after* the caller's mapping, so a payload carrying those
    keys loses them rather than overwriting the three fields the reader bounds and counts by. A
    journal whose timestamps came from the record being journalled would let one bad writer hold a
    dead session inside the 240-minute window forever.
    """
    body = {key: value for key, value in record.items() if key not in _RESERVED}
    body[AT_NS] = at_ns
    body[PID] = pid
    body[SEQ] = seq
    try:
        text = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return b""
    line = text.encode("utf-8", errors="surrogatepass") + b"\n"
    return b"" if len(line) > RECORD_MAX_BYTES else line


def append(
    root: Path,
    key: str,
    record: Mapping[str, Any],
    *,
    at_ns: int,
    pid: int | None = None,
    seq: int | None = None,
    max_bytes: int = JOURNAL_MAX_BYTES,
) -> Written:
    """10:1911's append: rotate if full, then **one** `write()` on a handle opened `"a"`.

    The single write is asserted over the AST by a test, because it is the whole of the plan's
    stated defence and a second write would silently halve it -- on POSIX, where the defence works
    at all. On Windows it does not: D400 measures 23% of records lost at two concurrent writers,
    and this function ships the plan's instruction because the alternative is a locking decision
    `locks.py` already holds the shape of and this module may not take.

    `"ab"` and not 10:1911's `"a"`, which is the same mode in binary and is not a deviation: the
    line is already UTF-8 and text mode on Windows would translate its `\\n` to `\\r\\n`, making
    the bytes on disk one longer than the bytes `RECORD_MAX_BYTES` was checked against. A cap
    enforced on a different string from the one written is not a cap.
    """
    if not key:
        return Written(reason="no_key")
    line = encode_record(
        record,
        at_ns=at_ns,
        pid=os.getpid() if pid is None else pid,
        seq=next(_SEQUENCE) if seq is None else seq,
    )
    if not line:
        return Written(reason="oversize")
    rotated = rotate(root, key, max_bytes=max_bytes)
    live = journal_paths(root, key)[0]
    try:
        root.mkdir(parents=True, exist_ok=True)
        with live.open("ab") as handle:
            handle.write(line)
    except OSError:
        return Written(reason="io", rotated=rotated)
    return Written(ok=True, size=len(line), rotated=rotated)


def rotate(root: Path, key: str, *, max_bytes: int = JOURNAL_MAX_BYTES) -> bool:
    """Move `<key>.jsonl` to `<key>.1.jsonl` when it is full. One generation, then discard.

    Two processes can both decide to rotate; `Path.replace` is atomic, so the loser overwrites the
    winner's generation with a file that is also full and also correct. What is lost is a
    generation, not a record, and a rotation racing an append loses the appends that landed between
    the size check and the rename -- which is D400's loss under a different name and is counted the
    same way.
    """
    live, rotated = journal_paths(root, key)
    try:
        if live.stat().st_size < max_bytes:
            return False
        live.replace(rotated)
    except OSError:
        return False
    return True


def claim(root: Path, name: str, payload: Mapping[str, Any]) -> bool:
    """Create `<name>` with `O_CREAT|O_EXCL|O_WRONLY`. `True` means **this process created it**.

    10:2059 calls the creation itself the atomic act -- *"`O_EXCL` is the atomic claim: exactly one
    of N simultaneous hook processes creates it"* -- and 10:2020 needs the same primitive for the
    strict deny's *"once per session, claimed with `O_EXCL`"*. One function, two callers, because
    they are the same guarantee and a second spelling would be a second set of edge cases.

    **This is the one write under `<sessions>/` that D400 does not reach.** An `O_EXCL` create is
    not an append: the filesystem either created the file or it did not, and Windows honours that
    where it does not honour `O_APPEND`'s atomicity. A loser gets `FileExistsError` and `False`,
    which is an answer and not a failure.

    Every other error is also `False`. A hook that cannot claim must behave exactly like a hook that
    lost the claim -- 10:1842 leaves no way to report the difference, and the conservative reading
    of "I could not take the once-per-session lock" is "somebody else has it".
    """
    if not name:
        return False
    try:
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return False
    try:
        root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(root / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError:
        return True  # the claim is the create; a failed body leaves a claimed, empty file
    return True


def claimed(root: Path, name: str) -> bool:
    """Whether `<name>` exists at all -- the question a caller asks when it did not try to claim."""
    try:
        return (root / name).is_file()
    except OSError:  # pragma: no cover -- an unreadable directory
        return False


def write_marker(root: Path, key: str, name: str, payload: Mapping[str, Any]) -> bool:
    """`<key>.<name>` written atomically: a sibling temp file, then `os.replace`. 10:1938.

    A sibling and not the system temp directory, because `os.replace` is atomic only within one
    filesystem. `export.py`'s `_replace` is these lines in a distribution this one may not import
    and D363 records that; this is the third copy and the reason is still the layers row.

    A marker is a *replace* and not an append, so D400 does not reach it -- the last writer wins
    and every writer is writing the same fact. That is why `.compacted` and `.briefing` are here
    and `counters.json` is not.
    """
    if not key or not name:
        return False
    target = root / f"{key}.{name}"
    try:
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return False
    try:
        root.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=str(root), prefix=target.name, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
                out.write(text)
            Path(temporary).replace(target)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
            return False
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------------------------
# Reading. 10:1912 -- "skips and counts malformed lines and never raises".
# ---------------------------------------------------------------------------------------------


def read(
    root: Path,
    key: str,
    *,
    now_ns: int,
    max_age_min: int = READ_AGE_MIN,
) -> Journal:
    """Both generations, oldest first, age-bounded, forgiving. Never raises.

    **The rotated generation is read too, and the plan does not say to.** 10:1914 discards at one
    generation and 10:1884 bounds every read at 240 minutes, and the two boundaries are
    independent: a rotation at minute 239 leaves a live file holding seconds of history, so a
    reader that took only the live file would go quiet exactly after the busiest session in the
    window. Reading both and letting the age bound do the discarding makes the 240 minutes mean
    what it says. D404.
    """
    if not key:
        return Journal()
    live, rotated = journal_paths(root, key)
    kept: list[Mapping[str, Any]] = []
    sources: list[str] = []
    skipped = stale = 0
    horizon = now_ns - max_age_min * _NS_PER_MIN
    for path in (rotated, live):
        lines = _lines(path)
        if lines is None:
            continue
        sources.append(path.name)
        for raw in lines:
            record = _parse(raw)
            if record is None:
                skipped += 1
            elif int(record[AT_NS]) < horizon:
                stale += 1
            else:
                kept.append(record)
    return Journal(
        records=tuple(kept),
        skipped=skipped,
        stale=stale,
        gaps=_gaps(kept),
        sources=tuple(sources),
    )


def _lines(path: Path) -> list[bytes] | None:
    """Every line of a journal file, or `None` when there is no file to read.

    Read whole rather than streamed: a journal is bounded at 4 MiB by `JOURNAL_MAX_BYTES`, and a
    single `read_bytes` cannot observe the file half-rotated the way an open handle can.

    **Blank segments are dropped here and not counted as malformed.** Every well-formed journal
    ends in a newline, so the split always yields a trailing empty element; counting it would put a
    floor of one under `Journal.skipped` and turn the plan's only instrument for a torn record into
    a number that is never zero.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return [line for line in raw.split(b"\n") if line.strip()]


def _parse(raw: bytes) -> Mapping[str, Any] | None:
    """One line to a record, or `None` for anything a reader must skip and count.

    A record with no usable `at_ns` is skipped rather than kept, because 10:1884 bounds every hook
    read by age and a record that cannot be aged cannot be bounded. Keeping it would be the
    zero-state the same clause forbids rendering, arriving one field at a time.
    """
    if not raw.strip():
        return None
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    stamp = record.get(AT_NS)
    if not isinstance(stamp, int) or isinstance(stamp, bool):
        return None
    return record


def _gaps(records: Iterable[Mapping[str, Any]]) -> int:
    """How many records a writer offered and this file does not hold. A LOWER BOUND, deliberately.

    Per `pid`, the span `max(seq) - min(seq) + 1` is what that process wrote between its first and
    last surviving record; the difference from the count is what the platform dropped in between.
    Records lost at either *end* of a process's run are invisible to this, so the number is never
    an overstatement -- which is the right direction for a figure whose job is to stop D400's loss
    from reading as zero.
    """
    spans: dict[int, list[int]] = {}
    for record in records:
        owner, position = record.get(PID), record.get(SEQ)
        if isinstance(owner, int) and isinstance(position, int) and not isinstance(owner, bool):
            spans.setdefault(owner, []).append(position)
    return sum(max(seen) - min(seen) + 1 - len(set(seen)) for seen in spans.values() if seen)


# ---------------------------------------------------------------------------------------------
# The sweep. 10:1918 -- and it does not depend on `SessionEnd` firing.
# ---------------------------------------------------------------------------------------------


def sweep(
    root: Path,
    *,
    now_ns: int,
    max_age_s: int = SWEEP_AGE_S,
    max_files: int = SESSIONS_MAX_FILES,
    keep: frozenset[str] = frozenset(),
) -> Swept:
    """Files older than 24 h, then oldest-first eviction above 2,000. 10:1918.

    `keep` defaults to **empty**, which is the plan read literally, and the literal reading deletes
    `counters.json` after a quiet day -- the file 10:1991 says exists to turn *"is the gate any
    good"* from vibes into a measured recall rate. The argument is here so a decision has somewhere
    to land; the default is here because taking it is not this module's to do. D402.

    *"A host that crashes never fires `SessionEnd`, and a directory that only grows is a slow leak
    in the one place a user never looks."* -- which is why this runs from `ow serve` start-up and
    `SessionStart` as well, and why a failed unlink is counted rather than raised.
    """
    entries = _entries(root)
    if entries is None:
        return Swept()
    cutoff = now_ns - max_age_s * 1_000_000_000
    doomed: list[tuple[int, str]] = []
    survivors: list[tuple[int, str]] = []
    for mtime_ns, name in entries:
        (doomed if mtime_ns < cutoff else survivors).append((mtime_ns, name))
    aged = tuple(name for _, name in sorted(doomed))
    survivors.sort()
    overflow = max(len(survivors) - max_files, 0)
    evicted = tuple(name for _, name in survivors[:overflow])
    removed = tuple(name for name in (*aged, *evicted) if name not in keep)
    failed = sum(1 for name in removed if not _unlink(root / name))
    return Swept(
        aged=aged,
        evicted=evicted,
        orphaned=_orphans(tuple(name for _, name in entries), removed),
        kept=len(entries) - len(removed) + failed,
        failed=failed,
    )


def _entries(root: Path) -> tuple[tuple[int, str], ...] | None:
    """`(mtime_ns, name)` for every file directly under `<sessions>/`, or `None` if it is not there.

    Directories are ignored rather than swept: nothing in 10:1891's list of what a hook may write is
    a directory, so one appearing here belongs to something else and removing it would be this
    function deciding on that thing's behalf.
    """
    try:
        found = [
            (entry.stat().st_mtime_ns, entry.name) for entry in root.iterdir() if entry.is_file()
        ]
    except OSError:
        return None
    return tuple(sorted(found))


def _unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _orphans(present: tuple[str, ...], removed: tuple[str, ...]) -> tuple[str, ...]:
    """Session keys left holding some of their files and not others. The finding, not the action.

    A key is everything before the first `.`, which is how `journal_paths` and `write_marker` both
    spell it. `counters.json` and `ingest.lease` group under their own names and are never partial,
    so they cannot produce a false positive here.
    """
    gone = set(removed)
    groups: dict[str, list[str]] = {}
    for name in present:
        groups.setdefault(name.split(".", 1)[0], []).append(name)
    torn = [key for key, names in groups.items() if 0 < len(gone.intersection(names)) < len(names)]
    return tuple(sorted(torn))


def unmeasured() -> tuple[str, ...]:
    """What this module's tests cannot reach, stated rather than left to a coverage report."""
    return (
        "POSIX `O_APPEND` atomicity: D400's table is measured on Windows only. The claim that "
        "10:1913 holds on POSIX is read off `open(2)` and is not measured here, because this "
        "checkout has one platform and a test that skipped everywhere would assert nothing.",
        "A rotation racing an append. `rotate()` checks a size and renames, and the window "
        "between them is real; provoking it needs two processes and a scheduler this suite does "
        "not control. The loss it causes is D400's and is counted by the same `gaps`.",
        "`counters.json` and `ingest.lease` under the sweep. Neither file exists yet -- the "
        "counters are D397's and the lease is W7.4f's -- so `keep` is tested with names this "
        "module invents and not with the two it was added for.",
        "A `<sessions>/` on a filesystem where `Path.replace` is not atomic. `write_marker` and "
        "`rotate` both assume one filesystem, which a sibling temp file buys and a network mount "
        "can still take away.",
    )
