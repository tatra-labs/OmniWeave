"""What git tracks under a directory, read from `.git/index` itself and not from `git ls-files`.

D-02 (15-observability.md:1515) asks whether any `.owstore` *"is tracked in git"*, and the one
authoritative answer is the index: a path is tracked exactly when it has an index entry.
`git ls-files` prints that list, but running it needs `subprocess`, and `subprocess` has exactly
two homes -- `omniweave_core.toolchain` and `omniweave_core.host.subproc` (02 section 3.4, G8's
semgrep rule), neither of them a place a doctor check belongs. Reading the file is also the
better instrument on its own terms: it needs no `git` on `PATH`, and a machine without git can
still have a checkout that tracks a store (D610).

**The format read is git's `index-format.txt`, versions 2, 3 and 4:**
- a 12-byte header: `DIRC`, the version, the entry count;
- per entry, 40 bytes of stat data, the object id, 16 bits of flags;
- a further 16 bits when the extended flag is set (version 3 and later);
- the path. Versions 2 and 3 end it with NULs up to an 8-byte boundary. Version 4 gives a varint
  count of bytes to strip from the previous path, then a NUL-terminated suffix.

The object id is 20 bytes, or 32 in a repository whose `extensions.objectformat` is `sha256`.

**What this reader cannot see, it says, and never answers "nothing tracked" over.** A split index
(the `link` extension) keeps most entries in a second file, and a sparse index (directory entries
with mode `040000`) folds whole subtrees into one entry. Either one leaves `unreadable` set, and
the doctor turns that into a warning with the command that checks by hand. So "could not read"
never reads as "clean": that is ST8's rule, applied to a doctor rather than to a Channel.

`GIT_DIR` and `GIT_INDEX_FILE` are not honoured. The doctor asks about the checkout the operator is
standing in, which is the `.git` found by walking up from it.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["IndexRead", "read_tracked"]

_SIGNATURE: Final = b"DIRC"
_VERSIONS: Final = frozenset({2, 3, 4})
_STAT_BYTES: Final = 40
"""ctime, mtime (8 bytes each), then dev, ino, mode, uid, gid and size (4 each)."""
_MODE_OFFSET: Final = 24
_EXTENDED: Final = 0x4000
_DIRECTORY: Final = 0o040000
_FILE_TYPE: Final = 0o170000
_SHA1_BYTES: Final = 20
_SHA256_BYTES: Final = 32
_SPLIT_INDEX: Final = b"link"
_OBJECT_FORMAT: Final = re.compile(r"^\s*objectformat\s*=\s*sha256\s*$", re.I | re.M)


@dataclass(frozen=True, slots=True)
class IndexRead:
    """One read of one index.

    `repo_root` is None when the start directory is inside no git work tree, and then `paths` is
    empty and says nothing. `unreadable` is empty only when every entry was read; otherwise it
    names what stopped the read, and `paths` holds what was read before it (possibly nothing).
    """

    repo_root: Path | None
    paths: tuple[str, ...]
    unreadable: str = ""


def read_tracked(start: Path) -> IndexRead:
    """Every path tracked by the work tree containing `start`: repo-relative and `/`-joined."""
    found = _find_git(start)
    if found is None:
        return IndexRead(repo_root=None, paths=())
    root, git_dir = found
    index = git_dir / "index"
    if not index.is_file():
        #  `git init` with nothing added writes no index at all: an empty one, not a missing fact.
        return IndexRead(repo_root=root, paths=())
    try:
        data = index.read_bytes()
    except OSError as exc:
        return IndexRead(repo_root=root, paths=(), unreadable=f"{index} could not be read: {exc}")
    paths, why = parse_index(data, hash_bytes=_hash_bytes(git_dir))
    return IndexRead(repo_root=root, paths=paths, unreadable=why)


def parse_index(  # noqa: PLR0911 -- one return per way a read can stop, each with its reason
    data: bytes, *, hash_bytes: int = _SHA1_BYTES
) -> tuple[tuple[str, ...], str]:
    """The index's paths and, when the read was incomplete, why. Never raises on bad bytes."""
    if len(data) < 12 or data[:4] != _SIGNATURE:  # noqa: PLR2004 -- the header's own width
        return (), "not a git index: no DIRC signature"
    version, count = struct.unpack(">II", data[4:12])
    if version not in _VERSIONS:
        return (), f"index version {version} is not one this reader knows (2, 3 or 4)"
    fixed = _STAT_BYTES + hash_bytes + 2
    names: list[str] = []
    sparse = 0
    previous = b""
    pos = 12
    try:
        for _ in range(count):
            start = pos
            if pos + fixed > len(data):
                return tuple(names), f"the index is truncated after {len(names)} of {count} entries"
            (mode,) = struct.unpack(">I", data[start + _MODE_OFFSET : start + _MODE_OFFSET + 4])
            (flags,) = struct.unpack(">H", data[pos + fixed - 2 : pos + fixed])
            pos += fixed
            if flags & _EXTENDED:
                pos += 2
            if version == 4:  # noqa: PLR2004 -- the prefix-compressed version, by number
                strip, pos = _varint(data, pos)
                end = data.index(b"\0", pos)
                if strip > len(previous):
                    why = f"entry {len(names)} strips more than its predecessor holds"
                    return tuple(names), why
                name = previous[: len(previous) - strip] + data[pos:end]
                pos = end + 1
            else:
                end = data.index(b"\0", pos)
                name = data[pos:end]
                pos = start + ((pos - start + len(name) + 8) & ~7)
            previous = name
            if mode & _FILE_TYPE == _DIRECTORY:
                sparse += 1
                continue
            names.append(name.decode("utf-8", "surrogateescape"))
    except (ValueError, IndexError, struct.error):
        return tuple(names), f"the index is malformed after {len(names)} of {count} entries"
    if sparse:
        return tuple(names), (
            f"a sparse index: {sparse} directory entr{'y' if sparse == 1 else 'ies'} fold paths "
            "this reader cannot list"
        )
    if _has_extension(data, pos, hash_bytes, _SPLIT_INDEX):
        return tuple(names), "a split index: most entries live in a sharedindex file not read here"
    return tuple(names), ""


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    """git's offset varint (`varint.c`): each continuation adds one before shifting."""
    byte = data[pos]
    pos += 1
    value = byte & 0x7F
    while byte & 0x80:
        byte = data[pos]
        pos += 1
        value = ((value + 1) << 7) | (byte & 0x7F)
    return value, pos


def _has_extension(data: bytes, pos: int, hash_bytes: int, signature: bytes) -> bool:
    """Whether the extension block after the entries carries `signature`."""
    end = len(data) - hash_bytes
    while pos + 8 <= end:
        (size,) = struct.unpack(">I", data[pos + 4 : pos + 8])
        if data[pos : pos + 4] == signature:
            return True
        pos += 8 + size
    return False


def _find_git(start: Path) -> tuple[Path, Path] | None:
    """The work tree root and its git directory, walking up from `start`."""
    here = start.resolve()
    for directory in (here, *here.parents):
        dot_git = directory / ".git"
        if dot_git.is_dir():
            return directory, dot_git
        if dot_git.is_file():
            #  A worktree or a submodule: `.git` is a file holding `gitdir: <path>`, relative to
            #  the directory that holds it.
            text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            if text.startswith("gitdir:"):
                return directory, (directory / text.removeprefix("gitdir:").strip()).resolve()
            return None
    return None


def _hash_bytes(git_dir: Path) -> int:
    """32 for a sha256 repository, else 20. A worktree's config lives in its `commondir`."""
    common = git_dir
    pointer = git_dir / "commondir"
    if pointer.is_file():
        common = (git_dir / pointer.read_text(encoding="utf-8").strip()).resolve()
    config = common / "config"
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _SHA1_BYTES
    return _SHA256_BYTES if _OBJECT_FORMAT.search(text) else _SHA1_BYTES
