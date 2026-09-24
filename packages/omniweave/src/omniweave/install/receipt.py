"""`$OMNIWEAVE_HOME/install-receipt.json`: what makes uninstall exact rather than re-derived.

10:1700-1747 is the specification. One row per artefact, each written immediately after its write
and carrying its own `written_at`; `scope_root` on every row, `null` for global and the resolved
project root for local, so an uninstall in project B never looks at project A's rows; and the whole
file written under `$OMNIWEAVE_HOME/.install.lock`. 10:1729 names the mechanism: *"The
**post-write `sha256`** is the whole mechanism. It answers the only question uninstall needs: has
the user touched this since we wrote it?"*

## A WHOLE-FILE HASH CANNOT ANSWER THAT QUESTION, AND THE PLAN'S OWN EXAMPLE SHOWS WHY

10:1709-1722 writes two rows to `~/.claude/settings.json` -- `permissions` at 10:12:03 with
`sha256_after` `3b8a...`, then `hooks` at 10:12:04 with `77a2...`. The second write changed the
file, so from 10:12:04 on the file hashes to `77a2...` and **the first row can never match again**:
uninstall would report the permissions it wrote itself as *"kept -- modified since install"*. The
two hashes chain only if uninstall walks the rows newest first and every removal restores the
exact bytes before it, which D441 showed holds only for a file whose style fits.

And the host rewrites its own file. `~/.claude.json` is where `mcpServers.omniweave` goes
(10:1667), and its 72 top-level keys are Claude Code's own state. Measured on this machine: it was
rewritten at 2026-09-23T20:39:50Z, more than a day into the session this module was written in,
with no install run. A whole-file hash of it goes stale on the host's
schedule, not the user's, and an uninstall that trusted it would keep every MCP entry. D448.

**So each row carries two digests.** `sha256_after` is the plan's, the whole file just after the
write: when it still matches, nothing at all has changed and byte-identity can be promised.
`owned_sha256` is new, the digest of **only what omniweave owns** -- the value at the key, the
array values, the section: when it matches, the user and the host may have changed everything else
and the owned part is still exactly what was written. `verdict()` returns which of the two held.
What uninstall does with each is its cell's; the receipt format freezes at the end of P7 (16:728),
so a field it needs has to exist before then.

## TWO MORE THINGS A ROW MUST RECORD THAT THE PLAN'S ROWS DO NOT

**What the write created.** A `json-array-add` of `mcp__omniweave__*` into a `settings.json` with no
`permissions` creates `{"permissions": {"allow": [...]}}`. Removing the one value leaves
`{"permissions": {"allow": []}}` -- not the pre-install bytes, so G-install's first case fails --
and nothing on 10:1712's row says the two containers were ours. The same holds for a file the
install created, which uninstall should delete rather than leave as `{}`, and for the directories
`atomic_write` made on the way to it. Rows carry `created_file`, `created_parents` and
`created_dirs`. D449, D452.

**Which row a re-install replaces.** 10:1739 says rows are *appended*. A second `ow install` that
rewrites the same key appends a second row for the same artefact, and the older one's digests are
stale by construction. A row's identity is `(target, location, scope_root, kind, path)`; recording
a row replaces the one with its identity and moves it last, so the newest-first order the whole-file
chain needs is the order of the file. D449.

## THE LOCK: THE HOUSE MECHANISM, AND THE 120 SECONDS AS A REPORT

10:1744-1747: `O_CREAT|O_EXCL`, *"a lock older than 120 s is broken and the break is reported as
`OW-A-033`"*. `omniweave_core.locks.FileScopedLock` already is `O_CREAT|O_EXCL`, and it answers
staleness better than an age: an advisory lock on the file, which the kernel drops when the holder
dies, so a dead holder's file is broken **at any age** and a live one is broken **at none**. An age
cannot tell the two apart, and this lock has live holders that are legitimately old: `ow uninstall`
asks the user their location first (10:1754) and prints the whole plan before touching anything
(10:1760), and `ow install` has a `--yes` (10:1427) and so a confirmation without it. Either, two
minutes into waiting at its own prompt, is alive -- and under the age rule a second shell would
break its lock and both would write. The shipped rule: a dead holder's lock is broken and the break
reported as `OW-A-033`; a live holder is refused, named, and -- when it is older than 120 s -- said
to be, but not broken. INV-21's one home for a lock is kept, and the plan's code keeps its job.
D450.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import OwError
from omniweave_core.locks import INTERACTIVE_WAIT_MS, FileScopedLock, LockHolder, inspect

from omniweave.install.primitives import (
    DEFAULT_STYLE,
    atomic_write,
    read_json,
    render_json,
    section_span,
)
from omniweave.install.types import KINDS, LOCATIONS, MODES, TARGET_IDS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_core.clock import Clock

    from omniweave.install.types import Kind, Location, Mode, TargetId

__all__ = [
    "LOCK_NAME",
    "LOCK_REPORT_AGE_S",
    "RECEIPT_LOCKED",
    "RECEIPT_NAME",
    "SCHEMA",
    "Entry",
    "InstallLock",
    "Loaded",
    "Receipt",
    "Recorded",
    "Taken",
    "Verdict",
    "dotted",
    "expand",
    "file_sha256",
    "forget",
    "identity_of",
    "load",
    "lock_path",
    "owned_array",
    "owned_key",
    "owned_section",
    "receipt_path",
    "record",
    "same_scope",
    "take_lock",
    "tildify",
    "unbuilt",
    "verdict",
    "written_at",
]

# 10:1703.
RECEIPT_NAME: Final = "install-receipt.json"
# 10:1744.
LOCK_NAME: Final = ".install.lock"
# 10:1704's `"schema":1`.
SCHEMA: Final = 1
# 10:1745. Reported, not enforced (D450).
LOCK_REPORT_AGE_S: Final = 120
# codes.toml: OW-A-033 OW_INSTALL_RECEIPT_LOCKED.
RECEIPT_LOCKED: Final = "OW-A-033"

_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_STAMP: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_TILDE: Final = "~"

# 10:1702-1726's keys, in the order the plan prints them, then the four this package adds.
_ORDER: Final = (
    "target",
    "location",
    "scope_root",
    "written_at",
    "kind",
    "path",
    "mode",
    "key",
    "values",
    "marker",
    "events",
    "sha256_after",
    "bundle_sha256",
    "owned_sha256",
    "created_file",
    "created_parents",
    "created_dirs",
)

# The field each mode needs, from the row that mode appears on at 10:1705-1726.
_MODE_FIELD: Final[Mapping[str, str]] = {
    "json-key": "key",
    "json-array-add": "values",
    "marker-section": "marker",
    "json-hook-rules": "events",
    "dir": "bundle_sha256",
}


# ---------------------------------------------------------------------------------------------
# Where things are, and how a path is spelled in a row.
# ---------------------------------------------------------------------------------------------


def receipt_path(home: Path) -> Path:
    """`$OMNIWEAVE_HOME/install-receipt.json`. 10:1703."""
    return home / RECEIPT_NAME


def lock_path(home: Path) -> Path:
    """`$OMNIWEAVE_HOME/.install.lock`. 10:1744."""
    return home / LOCK_NAME


def tildify(path: Path, user_home: Path) -> str:
    """`~/...` when `path` is under `user_home`, else the absolute path; `/`-separated either way.

    10:1707 spells a global row's path `~/.claude.json` and 10:1725 a local row's absolutely, and
    18:2973 prints paths tildified. Forward slashes on Windows too, so one receipt reads the same
    from Git Bash and PowerShell.
    """
    try:
        relative = path.relative_to(user_home)
    except ValueError:
        return path.as_posix()
    return _TILDE if not relative.parts else f"{_TILDE}/{relative.as_posix()}"


def expand(stored: str, user_home: Path) -> Path:
    """The inverse of `tildify`, against the home the caller resolved -- never an ambient one."""
    if stored == _TILDE:
        return user_home
    if stored.startswith(_TILDE + "/"):
        return user_home / stored[2:]
    return Path(stored)


def same_scope(left: str | None, right: str | None) -> bool:
    """Whether two `scope_root`s name one project.

    `Path.resolve()` already canonicalises an existing path's case on Windows -- measured,
    `e:/ai/_project` resolves to `E:\\AI\\_Project` -- so resolved roots compare equal as strings.
    `normcase` is for the root that no longer exists when uninstall runs, which `resolve()` cannot
    canonicalise.
    """
    if left is None or right is None:
        return left is right
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def written_at(wall_ns: int) -> str:
    """10:1706's `"2026-09-01T10:12:03Z"`: UTC, whole seconds, from the caller's wall clock."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(wall_ns // 1_000_000_000))


def dotted(*segments: str) -> str:
    """10:1708's `"key":"mcpServers.omniweave"`. A segment containing `.` is refused.

    The plan spells a key path as one dotted string, which cannot address a key that contains a
    dot -- and VS Code's `settings.json` is keyed that way (`"editor.fontSize"`). Refusing at
    construction keeps the ambiguity out of the receipt rather than inside it.
    """
    if not segments or any(not part or "." in part for part in segments):
        raise ValueError(f"not a dotted key path: {segments!r}")
    return ".".join(segments)


# ---------------------------------------------------------------------------------------------
# Rows.
# ---------------------------------------------------------------------------------------------


def identity_of(
    target: str, location: str, scope_root: str | None, kind: str, path: str
) -> tuple[str, str, str, str, str]:
    """A row's identity from its parts, so a caller can look one up before there is a row."""
    scope = "" if scope_root is None else os.path.normcase(scope_root)
    return (target, location, scope, kind, path)


@dataclass(frozen=True, slots=True)
class Entry:
    """One receipt row. 10:1705-1726, plus `owned_sha256` (D448) and `created_*` (D449).

    `extra` holds keys this version does not know, so a receipt a newer release wrote is
    rewritten with them intact rather than silently narrowed.
    """

    target: TargetId
    location: Location
    scope_root: str | None
    written_at: str
    kind: Kind
    path: str
    mode: Mode
    key: str = ""
    values: tuple[str, ...] = ()
    marker: str = ""
    events: tuple[str, ...] = ()
    sha256_after: str = ""
    bundle_sha256: str = ""
    owned_sha256: str = ""
    created_file: bool = False
    created_parents: tuple[str, ...] = ()
    created_dirs: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def identity(self) -> tuple[str, str, str, str, str]:
        """What a re-install replaces. D449."""
        return identity_of(self.target, self.location, self.scope_root, self.kind, self.path)

    def owned(self) -> str:
        """The digest of what omniweave owns: `owned_sha256`, or a `dir` row's bundle digest."""
        return self.owned_sha256 or self.bundle_sha256

    def to_json(self) -> dict[str, Any]:
        """The row as the receipt stores it: the plan's key order, only the fields its mode uses."""
        row: dict[str, Any] = {
            "target": self.target,
            "location": self.location,
            "scope_root": self.scope_root,
            "written_at": self.written_at,
            "kind": self.kind,
            "path": self.path,
            "mode": self.mode,
        }
        needed = _MODE_FIELD[self.mode]
        if needed == "key":
            row["key"] = self.key
        elif needed == "values":
            #  The array the values went into, which 10:1712's row leaves out. D462.
            if self.key:
                row["key"] = self.key
            row["values"] = list(self.values)
        elif needed == "marker":
            row["marker"] = self.marker
        elif needed == "events":
            row["events"] = list(self.events)
        if self.mode == "dir":
            row["bundle_sha256"] = self.bundle_sha256
        else:
            row["sha256_after"] = self.sha256_after
            row["owned_sha256"] = self.owned_sha256
            row["created_parents"] = list(self.created_parents)
        row["created_file"] = self.created_file
        row["created_dirs"] = list(self.created_dirs)
        ordered = {name: row[name] for name in _ORDER if name in row}
        ordered.update((name, value) for name, value in self.extra.items() if name not in ordered)
        return ordered

    @classmethod
    def from_json(cls, row: object) -> Entry | str:
        """A row, or why it is not one. Never raises."""
        if not isinstance(row, dict):
            return "a row is not an object"
        problem = _problem(row)
        if problem:
            return problem
        known = set(_ORDER)
        return cls(
            target=row["target"],
            location=row["location"],
            scope_root=row["scope_root"],
            written_at=row["written_at"],
            kind=row["kind"],
            path=row["path"],
            mode=row["mode"],
            key=row.get("key", ""),
            values=tuple(row.get("values", ())),
            marker=row.get("marker", ""),
            events=tuple(row.get("events", ())),
            sha256_after=row.get("sha256_after", ""),
            bundle_sha256=row.get("bundle_sha256", ""),
            owned_sha256=row.get("owned_sha256", ""),
            created_file=row.get("created_file", False) is True,
            created_parents=tuple(row.get("created_parents", ())),
            created_dirs=tuple(row.get("created_dirs", ())),
            extra={name: value for name, value in row.items() if name not in known},
        )


def _problem(row: dict[str, Any]) -> str:
    """The first reason `row` is not a valid entry, or `""`."""
    checks: tuple[tuple[bool, str], ...] = (
        (row.get("target") in TARGET_IDS, "target"),
        (row.get("location") in LOCATIONS, "location"),
        (row.get("kind") in KINDS, "kind"),
        (row.get("mode") in MODES, "mode"),
        (isinstance(row.get("path"), str) and bool(row.get("path")), "path"),
        (
            isinstance(row.get("written_at"), str) and bool(_STAMP.fullmatch(row["written_at"])),
            "written_at",
        ),
        (_scope_ok(row.get("location"), row.get("scope_root", ...)), "scope_root"),
    )
    for ok, name in checks:
        if not ok:
            return f"{name} is missing or not valid"
    return _mode_problem(row)


def _scope_ok(location: object, scope: object) -> bool:
    # 10:1737: "`null` for global and the absolute, resolved project root for local".
    if location == "global":
        return scope is None
    return isinstance(scope, str) and Path(scope).is_absolute()


def _strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


def _mode_problem(row: dict[str, Any]) -> str:
    needed = _MODE_FIELD[row["mode"]]
    value = row.get(needed)
    if needed == "values":
        # Empty is a row that says "this install added nothing": the value was the user's already,
        # and without the row a re-derived uninstall would revoke it (D454).
        ok = isinstance(value, list) and all(isinstance(v, str) and v for v in value)
    elif needed == "events":
        ok = _strings(value)
    elif needed == "bundle_sha256":
        ok = isinstance(value, str) and bool(_HEX64.fullmatch(value))
    else:
        ok = isinstance(value, str) and bool(value)
    if not ok:
        return f"a {row['mode']} row needs {needed}"
    if row["mode"] != "dir" and not (
        isinstance(row.get("sha256_after"), str) and _HEX64.fullmatch(row["sha256_after"])
    ):
        return "sha256_after is not a full sha256"
    for name in ("created_parents", "created_dirs"):
        listed = row.get(name, [])
        if not isinstance(listed, list) or not all(isinstance(v, str) and v for v in listed):
            return f"{name} is not a list of strings"
    return ""


@dataclass(frozen=True, slots=True)
class Receipt:
    """The whole file: `release`, `schema`, rows, and rows this version could not read.

    `foreign` rows are kept verbatim and written back, for the reason `Entry.extra` exists: a
    receipt is the one record of what was written, and dropping a row because this release cannot
    parse it would strand exactly the artefact that row describes.
    """

    release: str
    schema: int = SCHEMA
    entries: tuple[Entry, ...] = ()
    foreign: tuple[Any, ...] = ()

    def for_scope(self, location: Location, scope_root: str | None) -> tuple[Entry, ...]:
        """10:1738: *"uninstall filters on it first"*. Global has `scope_root` `None`."""
        return tuple(
            entry
            for entry in self.entries
            if entry.location == location and same_scope(entry.scope_root, scope_root)
        )

    def find(self, identity: tuple[str, str, str, str, str]) -> Entry | None:
        return next((entry for entry in self.entries if entry.identity() == identity), None)

    def with_entry(self, entry: Entry, *, release: str) -> Receipt:
        """`entry` recorded: the row with its identity replaced, and moved last. D449."""
        kept = tuple(one for one in self.entries if one.identity() != entry.identity())
        return replace(self, release=release, entries=(*kept, entry))

    def without(self, identities: Iterable[tuple[str, str, str, str, str]]) -> Receipt:
        gone = set(identities)
        return replace(self, entries=tuple(e for e in self.entries if e.identity() not in gone))

    def to_json(self) -> dict[str, Any]:
        rows = [entry.to_json() for entry in self.entries]
        return {"release": self.release, "schema": self.schema, "entries": [*rows, *self.foreign]}


# ---------------------------------------------------------------------------------------------
# The lock. D450.
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class InstallLock:
    """A held `.install.lock`. `record` and `forget` take one: the receipt is written under it."""

    home: Path
    _lock: FileScopedLock

    @property
    def held(self) -> bool:
        return self._lock._fd is not None

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> InstallLock:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class Taken:
    """The result of `take_lock`: the lock, or why not, and a dead holder's lock that was broken."""

    lock: InstallLock | None
    broke: LockHolder | None = None
    reason: str = ""
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.lock is not None


def take_lock(home: Path, *, clock: Clock, wait_ms: int = INTERACTIVE_WAIT_MS) -> Taken:
    """Take `$OMNIWEAVE_HOME/.install.lock`. Never raises; `OW-A-033` on a break or a refusal."""
    path = lock_path(home)
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return Taken(None, reason=f"cannot create {home}: {type(error).__name__}")
    before = inspect(path)
    lock = FileScopedLock(path=path, now_ns=clock.wall_ns, name="install")
    try:
        lock.acquire(wait_ms=wait_ms)
    except OwError:
        return Taken(None, reason=_refusal(path, clock.wall_ns()), code=RECEIPT_LOCKED)
    held = InstallLock(home, lock)
    if not before.stale:
        return Taken(held)
    gone = before.holder
    who = f"{gone.host} pid {gone.pid}" if gone else "an unreadable holder"
    age = f", {gone.age_s(clock.wall_ns()):.0f} s old" if gone else ""
    reason = f"broke a stale {path.name} left by {who}{age}; its writer is gone"
    return Taken(held, broke=gone, reason=reason, code=RECEIPT_LOCKED)


def _refusal(path: Path, now_ns: int) -> str:
    state = inspect(path)
    holder = state.holder
    if holder is None:
        return f"{path} is held and its holder cannot be read"
    age = holder.age_s(now_ns)
    message = (
        f"another ow install or uninstall holds {path}: {holder.host} pid {holder.pid}, {age:.0f} s"
    )
    if age > LOCK_REPORT_AGE_S:
        message += (
            f"; older than 10:1745's {LOCK_REPORT_AGE_S} s but its writer is alive, so it is not "
            "broken -- it may be waiting at its own prompt"
        )
    return message


# ---------------------------------------------------------------------------------------------
# Reading and writing the receipt.
# ---------------------------------------------------------------------------------------------

LoadState = Literal["missing", "read", "unparseable", "unreadable", "newer"]


@dataclass(frozen=True, slots=True)
class Loaded:
    """The receipt as read. `writable` is false when rewriting it would lose something."""

    receipt: Receipt
    state: LoadState
    skipped: tuple[str, ...] = ()
    reason: str = ""
    code: str = ""

    @property
    def writable(self) -> bool:
        return self.state in {"missing", "read", "unparseable"}


def load(home: Path, *, pid: int, release: str = "", back_up: bool = True) -> Loaded:
    """Read the receipt. Never raises; an unparseable one is backed up first (OW-A-032).

    `back_up=False` is a dry run's read, which writes nothing, backups included (D453); a receipt
    it cannot parse is then `unreadable`, since nothing was saved that a rewrite could stand on.

    A receipt whose `schema` is newer than this release's is read but not writable: its rows may
    mean something this version cannot know, and rewriting it would narrow them.
    """
    read = read_json(receipt_path(home), pid=pid, back_up=back_up)
    empty = Receipt(release=release)
    if read.state == "missing":
        return Loaded(empty, "missing")
    if read.state == "unreadable":
        return Loaded(empty, "unreadable", reason=read.reason)
    if read.state == "empty":
        return Loaded(empty, "read")
    if read.state == "unparseable":
        writable = read.backup is not None
        state: LoadState = "unparseable" if writable else "unreadable"
        return Loaded(empty, state, reason=read.reason, code=read.code)
    value = read.value
    schema = value.get("schema", SCHEMA)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema > SCHEMA:
        return Loaded(empty, "newer", reason=f"schema {schema!r} is newer than {SCHEMA}")
    rows = value.get("entries", [])
    if not isinstance(rows, list):
        rows = []
    entries: list[Entry] = []
    foreign: list[Any] = []
    skipped: list[str] = []
    for index, row in enumerate(rows):
        parsed = Entry.from_json(row)
        if isinstance(parsed, str):
            foreign.append(row)
            skipped.append(f"entry {index}: {parsed}")
        else:
            entries.append(parsed)
    stored = value.get("release")
    receipt = Receipt(
        release=stored if isinstance(stored, str) else release,
        schema=SCHEMA,
        entries=tuple(entries),
        foreign=tuple(foreign),
    )
    return Loaded(receipt, "read", tuple(skipped))


@dataclass(frozen=True, slots=True)
class Recorded:
    """What `record` or `forget` did to the receipt file."""

    ok: bool
    receipt: Receipt | None = None
    reason: str = ""
    code: str = ""


def record(
    lock: InstallLock,
    entry: Entry,
    *,
    release: str,
    pid: int,
    sleep: Callable[[float], None] = time.sleep,
) -> Recorded:
    """Append `entry`, replacing the row with its identity. 10:1739: right after its write."""
    return _rewrite(lock, lambda r: r.with_entry(entry, release=release), release, pid, sleep)


def forget(
    lock: InstallLock,
    identities: Sequence[tuple[str, str, str, str, str]],
    *,
    release: str,
    pid: int,
    sleep: Callable[[float], None] = time.sleep,
) -> Recorded:
    """Drop the rows with these identities -- uninstall's half, once an artefact is gone."""
    return _rewrite(lock, lambda r: r.without(identities), release, pid, sleep)


def _rewrite(
    lock: InstallLock,
    change: Callable[[Receipt], Receipt],
    release: str,
    pid: int,
    sleep: Callable[[float], None],
) -> Recorded:
    if not lock.held:
        return Recorded(
            ok=False, reason=f"{LOCK_NAME} is not held; the receipt is written under it"
        )
    loaded = load(lock.home, pid=pid, release=release)
    if not loaded.writable:
        return Recorded(ok=False, reason=loaded.reason, code=loaded.code)
    updated = change(loaded.receipt)
    wrote = atomic_write(
        receipt_path(lock.home), render_json(updated.to_json(), DEFAULT_STYLE), pid=pid, sleep=sleep
    )
    if not wrote.ok:
        return Recorded(ok=False, reason=wrote.reason)
    return Recorded(ok=True, receipt=updated, reason=loaded.reason, code=loaded.code)


# ---------------------------------------------------------------------------------------------
# The two digests, and what they say. D448.
# ---------------------------------------------------------------------------------------------

Verdict = Literal["untouched", "owned-untouched", "modified", "missing"]


def file_sha256(path: Path) -> str | None:
    """The digest `sha256_after` is compared with, or `None` when there is no file to read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


_ABSENT: Final = object()


def _at(document: Mapping[str, Any], key: str) -> object:
    node: object = document
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return _ABSENT
        node = node[part]
    return node


def owned_key(document: Mapping[str, Any], key: str) -> str | None:
    """A `json-key` row's owned digest: the canonical value at `key`, or `None` when absent."""
    value = _at(document, key)
    return None if value is _ABSENT else sha256_canonical(value)  # type: ignore[arg-type]


def owned_array(document: Mapping[str, Any], key: str, values: Sequence[str]) -> str | None:
    """A `json-array-add` row's owned digest: those of `values` still present, in their order.

    Equal to the row's own digest exactly when every value omniweave added is still there.
    """
    array = _at(document, key)
    if not isinstance(array, list):
        return None
    return sha256_canonical([value for value in values if value in array])


def owned_section(text: str) -> str | None:
    """A `marker-section` row's owned digest: the section's lines, newline-normalised."""
    span = section_span(text)
    if not isinstance(span, tuple):
        return None
    start, stop = span
    return hashlib.sha256(text[start:stop].replace("\r\n", "\n").encode("utf-8")).hexdigest()


def verdict(
    entry: Entry, *, exists: bool, current_sha256: str | None, owned_now: str | None
) -> Verdict:
    """Which of the row's two digests still holds. D448.

    `untouched`: the whole file is byte-for-byte what was written, so reversing is byte-exact.
    `owned-untouched`: something else in the file changed -- the user, the host -- and omniweave's
    part is exactly as written. `modified`: omniweave's part itself changed.
    """
    if not exists:
        return "missing"
    if entry.sha256_after and current_sha256 == entry.sha256_after:
        return "untouched"
    if entry.owned() and owned_now == entry.owned():
        return "owned-untouched"
    return "modified"


def unbuilt() -> tuple[str, ...]:
    """What 10 section 7.3 names that is not here, and why."""
    return (
        "what uninstall does with each verdict (10:1756). `untouched` and `owned-untouched` both "
        "say omniweave's part is as written; which of them may remove it is the uninstall cell's",
        "the owned digest of a json-hook-rules row. It is per command inside hook rules and needs "
        "10:1690's ownership parse, which ships with that mode",
        "where a local scope_root comes from. 10:1737 says 'the absolute, resolved project root' "
        "and 10:1665's local paths are './'-relative; whether the root is the cwd, the git root or "
        "omniweave.toml's directory is unstated. The receipt takes it from its caller (D451)",
        "which release writes the file. Nothing reads packages/omniweave/pyproject.toml's version "
        "at runtime yet; `release` is the caller's",
    )
