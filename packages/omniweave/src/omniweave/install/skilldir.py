"""The fifth write mode, `dir`: a skill bundle copied into place, and taken back on its digest.

10:1671 puts the core skill at `~/.agents/skills/omniweave` (global) or `./.agents/skills/omniweave`
(local), and 10:1723-1726's row records it as `"mode":"dir","bundle_sha256":"<full sha256>"`. The
digest is `sha256-bundle-1` (`omniweave.skills.hash`), the same function over the source tree and
the installed one, so a row's digest is a claim anyone can re-check.

## WHAT INSTALL WRITES, AND WHAT IT WILL NOT REPLACE

The bundle is copied file by file into a staged sibling `<name>.tmp.<pid>`, the staged tree is
hashed and must equal the source's digest, and only then is it renamed into place -- so a crash
leaves either nothing or a whole bundle, never a half-copied one. Only the files the digest covers
are copied: no link, no `__pycache__`. A directory already at the destination is:

- **unchanged** when its digest is the bundle's. With no earlier row it is recorded as **not
  ours** (`created_file: false`): somebody -- `ow skills install` (10:1393), or the user -- put the
  same bytes there first, and uninstall must not take them away. This is D454's rule for an array
  value the user already granted;
- **updated** when it still has the digest omniweave's own row recorded: the user has not touched
  it, so an upgrade may replace it;
- **kept** otherwise, with `OW-A-031` when a row exists: the tree is not what omniweave wrote.

A destination that is itself a link is kept, at install and at uninstall: a developer who links
`~/.agents/skills/omniweave` to a checkout has made that directory theirs.

## WHAT UNINSTALL REMOVES

A row whose digest matches the tree removes the tree -- *"removes exactly that ... directory"*
(10:1756) -- and a mismatch keeps it, naming both digests and the first differing path (10:1369's
three facts, taken from the source bundle when it is at hand). A row recorded as not ours leaves
the tree and forgets the row. With no row (10:1758's re-derivation), the tree is removed only when
its digest is the one this release ships: then every byte in it is republishable, and nothing of
the user's goes. A tree holding a link is never removed on the digest's word, since the digest
does not cover the link.
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING, Final

from omniweave.install.modes import Applied
from omniweave.install.primitives import remove_empty_dirs
from omniweave.skills.hash import bundle_sha256, first_difference, walk

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.clock import Clock

    from omniweave.install.modes import Site
    from omniweave.install.receipt import Entry
    from omniweave.install.types import Action

__all__ = ["HASH_MISMATCH", "install_dir", "remove_dir"]

HASH_MISMATCH: Final = "OW-A-031"
"""codes.toml: `OW_SKILL_HASH_MISMATCH`, *"skill bundle hash mismatch"*."""

_MODIFIED: Final = "kept -- modified since install"
_REDERIVED: Final = "no receipt row: removed because it is exactly this release's bundle (D455)"


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _missing_parents(target: Path) -> list[Path]:
    missing: list[Path] = []
    parent = target.parent
    while not parent.exists() and parent != parent.parent:
        missing.append(parent)
        parent = parent.parent
    return list(reversed(missing))


def install_dir(
    site: Site,
    source: Path,
    *,
    previous: Entry | None,
    clock: Clock,
    pid: int,
    dry_run: bool = False,
) -> Applied:
    """Copy the bundle at `source` to `site.path`. See the module docstring for what is replaced."""
    want, count, _ = bundle_sha256(source)
    if count == 0:
        return Applied(site.act("kept", "skill", "dir", f"{source} holds no bundle file"))
    dest = site.path
    existed = dest.exists()
    blocked = _occupied(site, want, previous, clock) if existed or _is_link(dest) else None
    if blocked is not None:
        return blocked
    action: Action = "updated" if existed else "created"
    if dry_run:
        return Applied(site.act(action, "skill", "dir"))
    parents = _missing_parents(dest)
    placed = _place(source, dest, want, pid)
    if placed:
        remove_empty_dirs(parents)
        return Applied(site.act("kept", "skill", "dir", placed))
    created = not existed or bool(previous and previous.created_file)
    before = previous.created_dirs if previous else ()
    dirs = tuple(dict.fromkeys((*before, *(site.spell(one) for one in parents))))
    row = site.row(
        "skill", "dir", clock, bundle_sha256=want, created_file=created, created_dirs=dirs
    )
    return Applied(site.act(action, "skill", "dir"), record=row)


def _occupied(site: Site, want: str, previous: Entry | None, clock: Clock) -> Applied | None:
    """What an existing destination decides: `None` when omniweave may replace it."""
    dest = site.path
    if _is_link(dest):
        return Applied(site.act("kept", "skill", "dir", "is a link; not writing through it"))
    if not dest.is_dir():
        return Applied(site.act("kept", "skill", "dir", "is a file, not a directory"))
    have = bundle_sha256(dest)[0]
    if have == want:
        return _unchanged(site, want, previous, clock)
    if previous is not None and have == previous.bundle_sha256:
        return None
    why = "the directory is not the bundle and not what omniweave last wrote there"
    code = HASH_MISMATCH if previous is not None else ""
    return Applied(site.act("kept", "skill", "dir", why, code=code))


def _unchanged(site: Site, want: str, previous: Entry | None, clock: Clock) -> Applied:
    if previous is not None:
        return Applied(site.act("unchanged", "skill", "dir"))
    note = "already present with this digest; recorded as not ours"
    row = site.row("skill", "dir", clock, bundle_sha256=want, created_file=False)
    return Applied(site.act("unchanged", "skill", "dir", note), record=row)


def _place(source: Path, dest: Path, want: str, pid: int) -> str:
    """Stage, verify, rename into place; `""`, or why not, with nothing left behind."""
    staged = dest.with_name(f"{dest.name}.tmp.{pid}")
    old = dest.with_name(f"{dest.name}.old.{pid}")
    try:
        _clear(staged)
        for rel, path in walk(source).files:
            target = staged.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        got = bundle_sha256(staged)[0]
        if got != want:
            _clear(staged)
            return f"the staged copy hashed {got}, not the bundle's {want}; nothing placed"
        if dest.exists():
            dest.replace(old)
        staged.replace(dest)
    except OSError as error:
        if old.exists() and not dest.exists():
            old.replace(dest)
        _clear(staged)
        return f"could not place the bundle: {type(error).__name__}: {error}"
    _clear(old)
    return ""


def _clear(path: Path) -> None:
    if path.exists() and not _is_link(path):
        shutil.rmtree(path, ignore_errors=True)


def remove_dir(
    site: Site,
    *,
    entry: Entry | None,
    source: Path | None,
    pid: int,
    dry_run: bool = False,
) -> Applied:
    """Remove the tree `entry` recorded, on its digest; with no row, only this release's bundle.

    The tree is renamed aside before anything in it is deleted. Measured on Windows: with one file
    in the bundle held open, `rmtree` deleted the others and stopped at that one, leaving half a
    bundle whose digest matched no row -- every later uninstall would report it modified. The
    rename is all or nothing: it fails with the handle open and touches no file, so the tree and
    its row survive for the next attempt. D465.
    """
    blocked = _removal_blocked(site, entry, source)
    if blocked is not None:
        return blocked
    note = _REDERIVED if entry is None else ""
    if dry_run:
        return Applied(site.act("removed", "skill", "dir", note), forget=entry)
    later = " after this window closes" if os.name == "nt" else ""
    aside = site.path.with_name(f"{site.path.name}.old.{pid}")
    try:
        site.path.replace(aside)
    except OSError as error:
        leftover = f"Could not remove {site.shown} -- delete it manually{later}"
        why = f"{type(error).__name__}; nothing in it was deleted"
        return Applied(site.act("kept", "skill", "dir", _notes(leftover, why, note)))
    shutil.rmtree(aside, ignore_errors=True)
    if aside.exists():
        note = _notes(note, f"Could not remove {site.spell(aside)} -- delete it manually{later}")
    return Applied(site.act("removed", "skill", "dir", note), forget=entry)


def _removal_blocked(site: Site, entry: Entry | None, source: Path | None) -> Applied | None:
    """What stops the removal, or `None` when the tree is omniweave's to delete."""
    dest = site.path
    if _is_link(dest):
        return Applied(site.act("kept", "skill", "dir", "is a link; not removing through it"))
    if not dest.exists():
        return Applied(site.act("not-found", "skill", "dir", "no directory"), forget=entry)
    if entry is not None and not entry.created_file:
        note = "was already here before install; left in place"
        return Applied(site.act("not-found", "skill", "dir", note), forget=entry)
    have = bundle_sha256(dest)[0]
    expected = entry.bundle_sha256 if entry is not None else _source_digest(source)
    if have != expected:
        return _mismatch(site, entry, source, expected=expected, have=have)
    links = walk(dest).links
    if links:
        why = f"holds {', '.join(links)}, a link the digest does not cover; not removing it"
        return Applied(site.act("kept", "skill", "dir", why))
    return None


def _source_digest(source: Path | None) -> str:
    if source is None or not source.is_dir():
        return ""
    return bundle_sha256(source)[0]


def _mismatch(
    site: Site, entry: Entry | None, source: Path | None, *, expected: str, have: str
) -> Applied:
    if entry is None:
        why = "no receipt row, and it is not this release's bundle; left in place"
        return Applied(site.act("kept", "skill", "dir", why))
    first = ""
    if source is not None and source.is_dir() and bundle_sha256(source)[0] == expected:
        differs = first_difference(source, site.path)
        first = f"first differing path {differs}" if differs else ""
    detail = _notes(_MODIFIED, f"expected {expected}", f"observed {have}", first)
    return Applied(site.act("kept", "skill", "dir", detail, code=HASH_MISMATCH))
