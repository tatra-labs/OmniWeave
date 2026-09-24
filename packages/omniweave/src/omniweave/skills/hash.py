"""`sha256-bundle-1`: one digest over a whole skill bundle. 10:1342-1366, and 10:2805's definition.

*"ONE function hashes the source tree and the installed tree, so equal content implies equal
digest"* (10:1342-1343). The install receipt's `dir` row stores it as `bundle_sha256` (10:1726),
`ow skills verify` compares against it (10:1368), and 16:728 freezes the receipt at the end of P7,
so the algorithm has to be right before a single row carries it.

## THE PLAN'S CODE AND ITS PROSE DISAGREE ABOUT THE SORT, AND THE PROSE IS RIGHT

10:1350 sorts `_walk(skill_dir)` -- `Path` objects -- and 10:1363-1364 says *"The full-path sort is
over the POSIX relative path, so a Windows and a Linux checkout of the same tree hash
identically."* Those are different orders. `WindowsPath` compares case-folded; `PosixPath`
compares part by part, case-sensitively; and neither is the order of the relative path as a
string. Measured, on this bundle's own two names:

- `WindowsPath` sort: `references/actions.md`, `SKILL.md` -- `r` before `s` once folded;
- `PurePosixPath` sort (what Linux's `PosixPath` inherits): `SKILL.md`, `references/actions.md`;
- the plan's code, run both ways over those two files: `977c311d...` and `7d2cdd2f...`.

So the plan's own function would give the shipped router a different digest on each platform, and
`ow skills verify` on Windows would call a Linux-built bundle tampered with. **Shipped: the sort key
is the POSIX relative path as a string**, which is the prose's rule and has no platform in it.
Code-point order puts `references-old.md` before `references/actions.md` (`-` is 0x2D, `/` is 0x2F),
where a part-wise sort puts it after; the digest is defined by the string. D464.

## WHAT `_walk` SKIPS, AND THE LINKS IT REPORTS

10:1361-1362: *"`_walk` skips `SKIP_NAMES` and `SKIP_SUFFIX` and follows no symlink."* A skipped
name skips a whole directory (`__pycache__`). A symlink or Windows junction is neither followed nor
hashed -- and `walk()` returns the ones it passed over, because a digest that does not cover a link
cannot vouch for a tree containing one, and the `dir` mode's uninstall refuses to delete such a tree
on the digest's word.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "ALGO",
    "SKIP_NAMES",
    "SKIP_SUFFIX",
    "TEXT_EXT",
    "Walked",
    "bundle_sha256",
    "file_digests",
    "first_difference",
    "walk",
]

ALGO: Final = "sha256-bundle-1"
"""10:1324: *"named, so a future algorithm is a new value"*."""

# 10:1344-1346, verbatim.
TEXT_EXT: Final = frozenset(
    {".md", ".txt", ".toml", ".json", ".jsonc", ".py", ".sql", ".svg", ".csv", ".yml"}
)
SKIP_NAMES: Final = frozenset({".DS_Store", "__pycache__", "Thumbs.db"})
SKIP_SUFFIX: Final = frozenset({".pyc", ".pyo"})


@dataclass(frozen=True, slots=True)
class Walked:
    """A bundle's files as `(relative POSIX path, path)` in digest order, and what was passed over.

    `links` are symlinks and junctions, which are neither followed nor hashed; `skipped` are the
    `SKIP_NAMES` and `SKIP_SUFFIX` entries. Both are relative POSIX paths.
    """

    files: tuple[tuple[str, Path], ...]
    links: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or bool(getattr(entry, "is_junction", lambda: False)())


def walk(skill_dir: Path) -> Walked:
    """Every file under `skill_dir` the digest covers, sorted by relative POSIX path. D464."""
    files: list[tuple[str, Path]] = []
    links: list[str] = []
    skipped: list[str] = []
    pending: list[tuple[str, Path]] = [("", skill_dir)]
    while pending:
        prefix, directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                rel = f"{prefix}{entry.name}"
                if _is_link(entry):
                    links.append(rel)
                elif entry.name in SKIP_NAMES or PurePosixPath(entry.name).suffix in SKIP_SUFFIX:
                    skipped.append(rel)
                elif entry.is_dir(follow_symlinks=False):
                    pending.append((f"{rel}/", directory / entry.name))
                elif entry.is_file(follow_symlinks=False):
                    files.append((rel, directory / entry.name))
    files.sort(key=lambda one: one[0])
    return Walked(tuple(files), tuple(sorted(links)), tuple(sorted(skipped)))


def _content(rel: str, path: Path) -> bytes:
    data = path.read_bytes()
    if PurePosixPath(rel).suffix in TEXT_EXT:
        data = data.replace(b"\r\n", b"\n")  # 10:1355: a Windows checkout is not stale
    return data


def bundle_sha256(skill_dir: Path) -> tuple[str, int, int]:
    """10:1348's `(digest, files, bytes)`: the full 64 hex, never truncated (10:1364-1366)."""
    digest = hashlib.sha256()
    count = total = 0
    for rel, path in walk(skill_dir).files:
        data = _content(rel, path)
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        count += 1
        total += len(data)
    return digest.hexdigest(), count, total


def file_digests(skill_dir: Path) -> dict[str, str]:
    """Per file, the sha256 of the bytes the bundle digest folds in: for naming a difference."""
    return {
        rel: hashlib.sha256(_content(rel, path)).hexdigest() for rel, path in walk(skill_dir).files
    }


def first_difference(left: Path, right: Path) -> str | None:
    """The first relative path, in digest order, at which two trees differ; `None` if none does.

    10:1369 has `ow skills verify` name *"the first differing path"*. A file present on one side
    only differs at its own path.
    """
    one, two = file_digests(left), file_digests(right)
    for rel in sorted(one.keys() | two.keys()):
        if one.get(rel) != two.get(rel):
            return rel
    return None
