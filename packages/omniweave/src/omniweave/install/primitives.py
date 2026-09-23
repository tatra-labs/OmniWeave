"""The shared write primitives, each of which 10:1645 calls *"a recorded bug fix"*.

10:1648-1654 names five: `atomic_write`, `json_deep_equal` before writing, a `read_json` that backs
up what it cannot parse, the marked-section pair, and self-healing pruning. The first four are here.
Pruning is not: it is *"at the individual-command level"* over hook rules, and whether a command is
ours is decided by 10:1690's four-spelling parse of the `ow` subcommand inside it -- one algorithm
with 10:1695's matcher convergence, so it ships with the `json-hook-rules` mode that needs both.

## THE REVERSAL GATE IS A CLAIM ABOUT A SERIALISER THE PLAN NEVER SPECIFIES

G-install (10:1775) installs, uninstalls, and asserts **byte identity** with the pre-install state
-- including for *"a `settings.json` that already had unrelated MCP servers and permissions"*. For
a JSON file, install and uninstall are each a parse, an edit and a re-serialise, so the gate holds
only if serialising the parsed file reproduces its bytes. Nothing in 10 section 7 says how the file
is re-serialised. Measured on this machine against the five host configs present, all written by
the hosts themselves:

| file | written by | indent | newline | trailing | Python `json.dumps(indent=2)` |
|---|---|---|---|---|---|
| `~/.claude.json` | Claude Code | 2 | LF | none | **68,758 positions differ** |
| `~/.claude/settings.json` | Claude Code | 2 | LF | `\\n` | 1 differs |
| `~/.cursor/mcp.json` | Cursor | 2 | LF | none | identical |
| `Code/User/settings.json` | VS Code | 4 | **CRLF** | none | 296 differ |
| `Cursor/User/settings.json` | Cursor | 4 | LF | none | 1,085 differ |

`~/.claude.json` is the worst because it holds 31 non-ASCII characters and Python's default
`ensure_ascii=True` turns each into a six-character escape, moving every byte after the first.
Three hosts, four styles, and the obvious serialiser round-trips one file in five. **So the style
is read from the file and written back in it**: indent unit, separators, ASCII escaping, newline,
what follows the closing brace, and the BOM. With that, all five round-trip byte-exactly. And as a
style is only *fitted* when re-rendering the parsed value reproduces the file exactly, `ReadJson`
knows before anything is written whether this file *can* be reversed byte-for-byte -- a duplicate
key, a `1e5`, or mixed newlines make it `round_trips=False`, and the gate's claim for that file is
then known false in advance rather than discovered by a diff. D441.

## FIVE MEASURED WAYS THE OTHER PRIMITIVES WOULD HAVE LIED

- **`json_deep_equal` is not `==`.** In Python `True == 1 == 1.0`, so the obvious comparison reports
  `unchanged` for a config holding `1` where `true` was asked for, and never writes it. Equality
  here is by JSON type first. D442.
- **`json.loads` rejects a UTF-8 BOM** (*"Unexpected UTF-8 BOM"*, measured), and PowerShell's
  `Out-File` and older Notepad write one. A BOM'd, perfectly valid config would read as unparseable,
  be backed up, and be replaced by `{}` plus our keys. It is decoded `utf-8-sig` and the BOM is
  written back. D443.
- **One `.backup` path destroys the first backup on the second failure.** A config that fails to
  parse twice -- the user breaks it, we back it up and rewrite it, they break it again -- overwrites
  the only copy of their original. Backups do not clobber: an identical one is reused, a different
  one gets `.backup.1`, `.backup.2`. D443.
- **`os.replace` over a symlink replaces the link.** Measured: the link becomes a regular file and
  its target is untouched, so a dotfile manager's repository never sees the edit -- and the reversal
  gate, which compares bytes at the path, passes while the link is gone. Writes go *through* a
  link. A read-only target is refused (Windows refuses the replace anyway, measured; POSIX's
  rename would silently overwrite it), and an existing file's mode bits are kept, because a
  default create is `0o666 & ~umask` and `~/.claude.json` holds account state. D444.
- **On Windows, a replace fails while any other handle has the target open.** Measured:
  `PermissionError` (winerror 5) with a reader holding the file. A host reading its config, or a
  scanner, at the wrong moment makes `ow install` fail. The replace is retried, bounded, on
  `PermissionError` alone -- npm's `graceful-fs` carries the same retry for the same reason. D445.

## THE MARKED SECTION: THE PLAN NAMES ONE MARKER, AND THE OBVIOUS SEPARATOR IS NOT INVERTIBLE

10:1716 names `<!-- omniweave:begin -->` and no end marker; `END` below is ours. And the natural
insert -- a blank line, then the block -- maps two different files to one: `"X\\n"` and `"X"` (no
final newline) both become `"X\\n\\n<block>"`, so the remove cannot know which to restore and the
byte-identity gate fails on one of them. The insert here is always exactly **one** newline before
the block, which is injective: `"X\\n"` gives a blank line and `"X"` gives none, and the remove
takes back exactly that newline. A marker counts only on a line of its own and outside a fenced
code block -- a CLAUDE.md that *documents* omniweave quotes the marker -- and two begins, a begin
without an end, or an end before its begin is refused rather than guessed at: deleting from a lone
begin to the end of a user's file is the one outcome worse than doing nothing. D446.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from omniweave.install.types import Action

__all__ = [
    "BACKUP_LIMIT",
    "BEGIN",
    "BOM",
    "DEFAULT_STYLE",
    "END",
    "REPLACE_ATTEMPTS",
    "REPLACE_BACKOFF_S",
    "UNPARSEABLE",
    "JsonStyle",
    "ReadJson",
    "Section",
    "Wrote",
    "atomic_write",
    "backup",
    "decode_text",
    "encode_text",
    "fit_style",
    "json_deep_equal",
    "read_json",
    "remove_marked_section",
    "render_json",
    "section_span",
    "temp_name",
    "unbuilt",
    "upsert_marked_section",
    "write_json",
]

BOM: Final = b"\xef\xbb\xbf"

# The one code a primitive reports. codes.toml: "backed up to <path>.backup".
UNPARSEABLE: Final = "OW-A-032"

# D445. Six attempts, doubling from 20 ms: at most 620 ms of waiting before giving up.
REPLACE_ATTEMPTS: Final = 6
REPLACE_BACKOFF_S: Final = 0.02

# D443. `.backup`, then `.backup.1` .. `.backup.99`; past that the write is refused, not clobbered.
BACKUP_LIMIT: Final = 100

# 10:1716, verbatim.
BEGIN: Final = "<!-- omniweave:begin -->"
# Not in the plan. D446.
END: Final = "<!-- omniweave:end -->"


# ---------------------------------------------------------------------------------------------
# atomic_write. 10:1650: "`tmp.<pid>` then rename, unlink on failure".
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Wrote:
    """What `atomic_write` did. `path` is where the bytes went, which is a link's target (D444).

    `sha256` is the digest of what was written, which is what is on disk after a successful replace
    -- the receipt's `sha256_after` (10:1729) without a second read.
    """

    ok: bool
    path: Path
    sha256: str = ""
    reason: str = ""
    attempts: int = 0


def temp_name(target: Path, pid: int) -> Path:
    """`<name>.tmp.<pid>`, a sibling, because `os.replace` is atomic only within one filesystem."""
    return target.with_name(f"{target.name}.tmp.{pid}")


def _through(path: Path) -> Path | str:
    """The path to write: `path` itself, or what a symlink at `path` points to. D444."""
    try:
        if not path.is_symlink():
            return path
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:  # a loop is RuntimeError on 3.12
        return f"cannot follow the link at {path}: {type(error).__name__}"


def atomic_write(
    path: Path,
    data: bytes,
    *,
    pid: int,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = REPLACE_ATTEMPTS,
) -> Wrote:
    """Write `data` to `path` so a crash leaves the old file or the new one, never half of either.

    Never raises. The temp file is unlinked on every failure after it exists (10:1650), and the
    reason is returned rather than logged, because the caller reports it per path (10:1763).
    """
    prepared = _prepare(path)
    if isinstance(prepared, Wrote):
        return prepared
    target, mode = prepared
    temporary = temp_name(target, pid)
    try:
        _stage(temporary, data, mode)
    except OSError as error:
        _discard(temporary)
        return Wrote(ok=False, path=target, reason=f"{temporary}: {type(error).__name__}")
    wrote = _replace(temporary, target, data, sleep=sleep, attempts=max(attempts, 1))
    if not wrote.ok:
        _discard(temporary)
    return wrote


def _prepare(path: Path) -> tuple[Path, int | None] | Wrote:
    """The real target and its mode bits, or the refusal. D444."""
    target = _through(path)
    if isinstance(target, str):
        return Wrote(ok=False, path=path, reason=target)
    mode: int | None = None
    try:
        if target.exists():
            if target.is_dir():
                return Wrote(ok=False, path=target, reason=f"{target} is a directory")
            if not os.access(target, os.W_OK):
                return Wrote(ok=False, path=target, reason=f"{target} is read-only")
            mode = stat.S_IMODE(target.stat().st_mode)
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return Wrote(ok=False, path=target, reason=f"{target}: {type(error).__name__}")
    return target, mode


def _replace(
    temporary: Path,
    target: Path,
    data: bytes,
    *,
    sleep: Callable[[float], None],
    attempts: int,
) -> Wrote:
    """`os.replace`, retried with a doubling wait on `PermissionError` alone. D445."""
    delay = REPLACE_BACKOFF_S
    reason = ""
    for attempt in range(1, attempts + 1):
        try:
            temporary.replace(target)
        except PermissionError as error:
            reason = _locked(target, error)
            if attempt < attempts:
                sleep(delay)
                delay *= 2
        except OSError as error:
            failed = f"{target}: {type(error).__name__}"
            return Wrote(ok=False, path=target, reason=failed, attempts=attempt)
        else:
            digest = hashlib.sha256(data).hexdigest()
            return Wrote(ok=True, path=target, sha256=digest, attempts=attempt)
    return Wrote(ok=False, path=target, reason=reason, attempts=attempts)


def _stage(temporary: Path, data: bytes, mode: int | None) -> None:
    """Create the temp file exclusively, write every byte, fsync, and copy the target's mode."""
    temporary.unlink(missing_ok=True)  # a stale one from a crashed run with a reused pid
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    handle = os.open(temporary, flags, 0o666)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(handle, view) :]
        os.fsync(handle)
    finally:
        os.close(handle)
    if mode is not None:
        temporary.chmod(mode)


def _discard(temporary: Path) -> None:
    # Nothing further to do if even this fails; the caller reports the write.
    with contextlib.suppress(OSError):
        temporary.unlink(missing_ok=True)


def _locked(target: Path, error: PermissionError) -> str:
    code = getattr(error, "winerror", None)
    held = " (another process has it open)" if code in {5, 32} else ""
    return f"{target}: PermissionError{held}"


# ---------------------------------------------------------------------------------------------
# JSON: read, compare, write -- in the file's own style. D441.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JsonStyle:
    """Everything `json.dumps` cannot infer and a host's file has anyway.

    `trailing` is what follows the closing brace, spelled with `\\n`; `newline` replaces each
    `\\n` on the way out, which is safe because `json.dumps` escapes every newline inside a string.
    """

    indent: str | None = "  "
    item_separator: str = ","
    key_separator: str = ": "
    ascii: bool = False
    newline: str = "\n"
    trailing: str = "\n"
    bom: bool = False


# What a file we create gets: `~/.claude/settings.json`'s style as Claude Code writes it, measured.
DEFAULT_STYLE: Final = JsonStyle()

State = Literal["missing", "empty", "parsed", "unparseable", "unreadable"]


@dataclass(frozen=True, slots=True)
class ReadJson:
    """A config as read: its value, its style, and whether writing it back reproduces its bytes.

    `state` is one of five, and only two of them are the plan's `{}` (10:1652): `missing` and
    `unparseable`. `empty` is a zero-byte or whitespace file, which is not worth a backup and cannot
    be reproduced by any serialiser. `unreadable` -- a directory, no permission -- is not
    unparseable: nothing was read, so nothing can be backed up, and a write over it is refused.
    """

    value: dict[str, Any]
    state: State
    style: JsonStyle
    round_trips: bool
    raw: bytes | None = None
    backup: Path | None = None
    reason: str = ""
    code: str = ""


# `bool` before `int`: `isinstance(True, int)` is True, which is the whole of D442.
_CATEGORIES: Final[tuple[tuple[type | tuple[type, ...], str], ...]] = (
    (type(None), "null"),
    (bool, "bool"),
    (int, "int"),
    (float, "float"),
    (str, "str"),
    (dict, "object"),
    ((list, tuple), "array"),
)


def _category(value: object) -> str:
    for kind, name in _CATEGORIES:
        if isinstance(value, kind):
            return name
    return type(value).__name__


def json_deep_equal(left: object, right: object) -> bool:
    """Equal as JSON: same type at every node, objects unordered, arrays ordered. D442.

    A list and a tuple are both a JSON array, because `json.dumps` writes them identically and a
    target builds its desired value in whichever it likes. Object key order is ignored, because a
    host re-orders nothing and a difference in order alone is not worth a write.
    """
    if _category(left) != _category(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_deep_equal(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(map(json_deep_equal, left, right))
    return left == right


def render_json(value: object, style: JsonStyle = DEFAULT_STYLE) -> bytes:
    """`value` as `style` writes it. Raises `ValueError`/`TypeError` for what JSON cannot hold."""
    text = json.dumps(
        value,
        indent=style.indent,
        separators=(style.item_separator, style.key_separator),
        ensure_ascii=style.ascii,
        allow_nan=False,
    )
    text = (text + style.trailing).replace("\n", style.newline)
    return (BOM if style.bom else b"") + text.encode("utf-8")


_INDENT = re.compile(r"\n([ \t]+)[^ \t\n]")


def _candidates(body: str, newline: str, trailing: str, bom: bool) -> Iterator[JsonStyle]:
    found = _INDENT.search(body)
    if found:
        indents: tuple[str | None, ...] = (found.group(1),)
    elif "\n" in body:
        indents = (None,)
    else:
        # One line: any indent renders empty containers alike, so prefer the default's -- a key
        # added later is then written the way a created file would be, not on one long line.
        indents = (DEFAULT_STYLE.indent, None)
    for indent in indents:
        separators = ((",", ": "), (",", ":")) if indent is not None else ((",", ":"), (", ", ": "))
        for item, key in separators:
            for ascii_only in (False, True):
                yield JsonStyle(indent, item, key, ascii_only, newline, trailing, bom)


def fit_style(text: str, value: object, *, bom: bool = False) -> JsonStyle | None:
    """The style that re-renders `value` as exactly `text`, or `None` when none does. D441."""
    newline = "\r\n" if "\r\n" in text else "\n"
    flat = text.replace("\r\n", "\n")
    body = flat.rstrip(" \t\n")
    trailing = flat[len(body) :]
    target = (BOM if bom else b"") + text.encode("utf-8")
    for style in _candidates(body, newline, trailing, bom):
        try:
            if render_json(value, style) == target:
                return style
        except (TypeError, ValueError):  # pragma: no cover -- a parsed value always renders
            return None
    return None


def _reject_constant(name: str) -> object:
    # `json.loads` accepts NaN and Infinity by default; no host writes them and none reads them.
    raise ValueError(f"{name} is not JSON")


def decode_text(raw: bytes) -> tuple[str, bool]:
    """UTF-8, BOM stripped and reported. Raises `UnicodeDecodeError`. D443."""
    return raw.decode("utf-8-sig"), raw.startswith(BOM)


def encode_text(text: str, *, bom: bool) -> bytes:
    """The inverse of `decode_text`."""
    return (BOM if bom else b"") + text.encode("utf-8")


def read_json(path: Path, *, pid: int) -> ReadJson:
    """10:1652: a config that will not parse is **backed up** before `{}` is returned. Never raises.

    The backup is written before this returns, so a caller that goes on to write `{}` plus its own
    keys over the file has already kept the user's version. `backup` is `None` only when that
    copy could not be made, and `write_json` then refuses the write.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return ReadJson(value={}, state="missing", style=DEFAULT_STYLE, round_trips=True)
    except OSError as error:
        reason = f"{path}: {type(error).__name__}"
        return ReadJson({}, "unreadable", DEFAULT_STYLE, round_trips=False, reason=reason)
    return _parse(path, raw, pid)


def _parse(path: Path, raw: bytes, pid: int) -> ReadJson:
    try:
        text, bom = decode_text(raw)
    except UnicodeDecodeError:
        return _unparseable(path, raw, pid, "not UTF-8")
    if not text.strip():
        style = JsonStyle(bom=bom)
        return ReadJson({}, "empty", style, round_trips=False, raw=raw)
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        return _unparseable(path, raw, pid, f"{type(error).__name__}: {error}")
    if not isinstance(value, dict):
        return _unparseable(path, raw, pid, f"the top level is {_category(value)}, not an object")
    fitted = fit_style(text, value, bom=bom)
    style = fitted or JsonStyle(newline="\r\n" if "\r\n" in text else "\n", bom=bom)
    return ReadJson(value, "parsed", style, round_trips=fitted is not None, raw=raw)


def _unparseable(path: Path, raw: bytes, pid: int, why: str) -> ReadJson:
    saved = backup(path, raw, pid=pid)
    if isinstance(saved, str):
        reason = f"{path} would not parse ({why}) and could not be backed up: {saved}"
        return ReadJson({}, "unparseable", DEFAULT_STYLE, False, raw, None, reason, UNPARSEABLE)
    reason = f"{path} would not parse ({why}); backed up to {saved}"
    return ReadJson({}, "unparseable", DEFAULT_STYLE, False, raw, saved, reason, UNPARSEABLE)


def backup(path: Path, raw: bytes, *, pid: int) -> Path | str:
    """`<path>.backup`, or the first free `.backup.<n>`; an identical one is reused. D443."""
    for index in range(BACKUP_LIMIT):
        suffix = ".backup" if index == 0 else f".backup.{index}"
        candidate = path.with_name(path.name + suffix)
        try:
            if candidate.exists():
                if candidate.is_file() and candidate.read_bytes() == raw:
                    return candidate
                continue
        except OSError:
            continue
        wrote = atomic_write(candidate, raw, pid=pid)
        return candidate if wrote.ok else wrote.reason
    return f"{BACKUP_LIMIT} backups of {path.name} already exist"


def write_json(
    path: Path,
    value: dict[str, Any],
    before: ReadJson,
    *,
    pid: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Action, Wrote | None, str]:
    """Write `value` over what `before` read, in its style -- or not at all when nothing changed.

    Returns the action, the write (or `None` when nothing was written), and a note. 10:1651:
    `json_deep_equal` first, so `unchanged` is a fact about the file and not a guess.
    """
    unsafe = before.state == "unparseable" and before.backup is None
    if before.state == "unreadable" or unsafe:
        return "kept", None, before.reason
    if before.state == "parsed" and json_deep_equal(before.value, value):
        return "unchanged", None, ""
    try:
        data = render_json(value, before.style)
    except (TypeError, ValueError) as error:
        return "kept", None, f"not JSON: {error}"
    if before.raw is not None and data == before.raw:
        return "unchanged", None, ""
    wrote = atomic_write(path, data, pid=pid, sleep=sleep)
    if not wrote.ok:
        return "kept", wrote, wrote.reason
    action: Action = "created" if before.state == "missing" else "updated"
    return action, wrote, before.reason


# ---------------------------------------------------------------------------------------------
# The marked section. 10:1653: "clobbering an unrelated section of CLAUDE.md". D446.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Section:
    """The text after an upsert or remove, or `None` with a reason when the edit was refused."""

    text: str | None
    action: Action
    reason: str = ""


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _lines(text: str) -> Iterator[tuple[int, str]]:
    """Each line's start offset and its content without the line ending."""
    offset = 0
    for line in text.split("\n"):
        yield offset, line.removesuffix("\r")
        offset += len(line) + 1


def section_span(text: str) -> tuple[int, int] | str | None:
    """The block's `[start, stop)` offsets, `None` when absent, or why it is refused."""
    begins: list[int] = []
    ends: list[tuple[int, int]] = []
    fence: str | None = None
    for offset, line in _lines(text):
        opened = _FENCE.match(line)
        if fence is not None:
            if opened and _closes(opened, line, fence):
                fence = None
            continue
        if opened:
            fence = opened.group(1)
            continue
        marker = line.rstrip(" \t")
        if marker == BEGIN:
            begins.append(offset)
        elif marker == END:
            stop = text.find("\n", offset)
            ends.append((offset, len(text) if stop < 0 else stop + 1))
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or ends[0][0] < begins[0]:
        found = f"{len(begins)} begin and {len(ends)} end markers"
        return f"{found}; not editing a section it cannot find"
    return begins[0], ends[0][1]


def _closes(opened: re.Match[str], line: str, fence: str) -> bool:
    """CommonMark: the same character, at least as many, and nothing after it on the line."""
    run = opened.group(1)
    return run[0] == fence[0] and len(run) >= len(fence) and not line[opened.end() :].strip()


def _newline(text: str) -> str:
    first = text.find("\n")
    return "\r\n" if first > 0 and text[first - 1] == "\r" else "\n"


def _block(body: str, newline: str) -> str:
    inner = body.replace("\r\n", "\n").strip("\n").replace("\n", newline)
    return f"{BEGIN}{newline}{inner}{newline}{END}{newline}"


def upsert_marked_section(text: str, body: str) -> Section:
    """Insert or replace the block. Absent: exactly one newline, then the block, at the end."""
    span = section_span(text)
    if isinstance(span, str):
        return Section(None, "kept", span)
    newline = _newline(text)
    block = _block(body, newline)
    if span is None:
        return Section(text + newline + block if text else block, "created")
    start, stop = span
    updated = text[:start] + block + text[stop:]
    return Section(updated, "unchanged" if updated == text else "updated")


def remove_marked_section(text: str) -> Section:
    """The inverse of an insert: the block, and the newline before it when it ends the file."""
    span = section_span(text)
    if isinstance(span, str):
        return Section(None, "kept", span)
    if span is None:
        return Section(text, "not-found")
    start, stop = span
    prefix, suffix = text[:start], text[stop:]
    newline = _newline(text)
    if not suffix and prefix.endswith(newline):
        prefix = prefix[: -len(newline)]
    return Section(prefix + suffix, "removed")


def unbuilt() -> tuple[str, ...]:
    """What 10 section 7.1 names that is not here, and why."""
    return (
        "self-healing pruning (10:1654). It is per command inside hook rules and needs 10:1690's "
        "four-spelling ownership parse and 10:1695's matcher convergence; it ships with the "
        "json-hook-rules mode",
        "refresh_targets() (10:1656). It re-runs AgentTarget.install(), and no target exists yet",
        "what install does with a config that will not round-trip (D441). ReadJson.round_trips "
        "says so before the write; whether to write anyway, refuse, or keep a pre-image is the "
        "plan's",
        "whether install writes over a config that would not parse (D443). 10:1652 returns {} "
        "after the backup, which a caller then fills; for a JSONC host (VS Code) that is every "
        "file with a comment in it",
    )
