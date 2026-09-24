"""`$OMNIWEAVE_HOME/skills-lock.json`: what `ow skills install` placed, and on which digest.

10:1321-1338 is the document and 10:1384-1388 the discipline: *"`ow skills install` takes an
exclusive `$OMNIWEAVE_HOME/.skills.lock` ... does a read-modify-write of `skills-lock.json` through
`atomic_write`, and releases"*. The lock is `receipt.take_lock` with the other file name -- the same
`O_CREAT|O_EXCL` and the same 120 s, so D450's rule holds for it unchanged: a dead holder's lock is
broken and the break reported, a live one is refused and named.

## `installed_to` IS WHAT THIS VERB WROTE, AND NOTHING ELSE

The plan's example gives the core skill `"installed_to": ["~/.agents/skills/omniweave"]`, and that
directory is also the one `ow install --skills core` writes (10:1671). Two ledgers would then both
name one tree, and each verb that removes -- `ow uninstall`, `ow skills remove` -- would take the
other's copy. So a directory is listed only when `ow skills install` created or replaced it. One it
found already holding the bundle's bytes is reported `unchanged` and not listed, which is D454's
rule and `skilldir`'s `created_file: false` read from the other side: whoever put it there takes
it away. `ow install` already records a tree this verb placed as not its own; `claimant()` is how
`ow uninstall`'s re-derivation, with no receipt row to go on (10:1758-1759), learns that a tree it
would otherwise remove belongs here. D490.

## ONE DIGEST PER SKILL, AS THE PLAN WRITES IT

`bundle_sha256` is per skill and `installed_to` is a list, so every listed directory is asserted
to hold that digest -- which is what `ow skills verify` checks (10:1368). A directory that could not
be brought to a new digest keeps the old bytes against the new record, and reads as modified. That
is the plan's model and it is honest about the one case it loses: an update that failed half-way.

## A LOCK THAT DOES NOT PARSE IS NOT REWRITTEN

The receipt backs up a file it cannot parse and starts again (10:1652). This file is not
re-derivable -- it is the only record of which directories this verb owns -- so an unreadable or
newer one refuses every write, names the file, and `claimant()` answers that ownership is unknown
rather than that there is none.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave.install.primitives import atomic_write, render_json
from omniweave.install.receipt import expand
from omniweave.skills.hash import ALGO
from omniweave.skills.tier import is_core

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "LOCK_FILE",
    "SERIAL_LOCK",
    "SOURCE",
    "SOURCE_TYPE",
    "VERSION",
    "Locked",
    "SkillsLock",
    "claimant",
    "lock_file",
    "read",
    "render",
    "write",
]

LOCK_FILE: Final = "skills-lock.json"
"""10:1321."""

SERIAL_LOCK: Final = ".skills.lock"
"""10:1385: the exclusive lock `ow skills install` takes around the read-modify-write."""

VERSION: Final = 1
"""10:1322's `"version": 1`."""

SOURCE: Final = "omniweave/skills"
"""10:1327's first-party attribution. Orphan detection reads it (10:1376-1377)."""

SOURCE_TYPE: Final = "path"
"""One of 10:1328's `wheel | github | path`. The wheel does not ship `skills/` yet (W7.5f): the
bundles are read from the checkout's tree, and a `"wheel"` here would name bytes nobody built."""

_HEX64: Final = re.compile(r"[0-9a-f]{64}")

LockState = Literal["missing", "read", "unparseable", "newer"]


@dataclass(frozen=True, slots=True)
class Locked:
    """One `skills.<name>` entry, 10:1326-1333's fields in that order."""

    name: str
    bundle_sha256: str
    files: int
    bytes: int
    installed_to: tuple[str, ...]
    skill_path: str = ""
    source: str = SOURCE
    source_type: str = SOURCE_TYPE

    @property
    def tier(self) -> str:
        """10:1333: `core` for the router, `on-demand` for everything else (10:1185-1188)."""
        return "core" if is_core(self.name) else "on-demand"

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "skill_path": self.skill_path or f"skills/{self.name}",
            "bundle_sha256": self.bundle_sha256,
            "files": self.files,
            "bytes": self.bytes,
            "installed_to": list(self.installed_to),
            "tier": self.tier,
        }


@dataclass(frozen=True, slots=True)
class SkillsLock:
    """The lock as read. `writable` is false when a rewrite would lose what it cannot read."""

    skills: Mapping[str, Locked] = field(default_factory=dict)
    state: LockState = "missing"
    reason: str = ""

    @property
    def writable(self) -> bool:
        return self.state in {"missing", "read"}


def lock_file(home: Path) -> Path:
    """`$OMNIWEAVE_HOME/skills-lock.json`."""
    return home / LOCK_FILE


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _count(raw: dict[str, Any], key: str) -> int | None:
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _entry(name: str, raw: object) -> Locked | None:
    """One entry, or `None` when any field is missing or of the wrong type."""
    if not isinstance(raw, dict):
        return None
    digest, stored = _text(raw, "bundle_sha256"), raw.get("installed_to")
    places = tuple(stored) if isinstance(stored, list) else None
    source, source_type = _text(raw, "source"), _text(raw, "source_type")
    skill_path = _text(raw, "skill_path")
    files, size = _count(raw, "files"), _count(raw, "bytes")
    listed = places is not None and all(isinstance(one, str) for one in places)
    if not (_HEX64.fullmatch(digest) and listed and source and source_type and skill_path):
        return None
    if places is None or files is None or size is None:
        return None
    return Locked(
        name=name,
        bundle_sha256=digest,
        files=files,
        bytes=size,
        installed_to=places,
        skill_path=skill_path,
        source=source,
        source_type=source_type,
    )


def read(home: Path) -> SkillsLock:
    """Read the lock. Never raises; see the module docstring for what an unreadable one does."""
    path = lock_file(home)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return SkillsLock()
    except OSError as error:
        return SkillsLock(state="unparseable", reason=f"{path}: {type(error).__name__}")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        return SkillsLock(state="unparseable", reason=f"{path} is not JSON: {error}")
    return _document(path, document)


def _document(path: Path, document: object) -> SkillsLock:
    if not isinstance(document, dict) or not isinstance(document.get("version"), int):
        return SkillsLock(state="unparseable", reason=f"{path} has no integer version")
    if document["version"] > VERSION:
        why = f"{path} is version {document['version']}, newer than this release's {VERSION}"
        return SkillsLock(state="newer", reason=why)
    skills = document.get("skills")
    if document.get("algo") != ALGO or not isinstance(skills, dict):
        return SkillsLock(state="unparseable", reason=f"{path} is not a {ALGO} skills lock")
    found: dict[str, Locked] = {}
    for name, raw_entry in skills.items():
        entry = _entry(name, raw_entry)
        if entry is None:
            return SkillsLock(state="unparseable", reason=f"{path}: skills.{name} is malformed")
        found[name] = entry
    return SkillsLock(found, "read")


def render(skills: Mapping[str, Locked], *, release: str) -> bytes:
    """10:1322-1325's document: sorted by skill, two-space JSON, one trailing newline."""
    document = {
        "version": VERSION,
        "release": release,
        "algo": ALGO,
        "skills": {name: skills[name].to_json() for name in sorted(skills)},
    }
    return render_json(document)


def write(home: Path, skills: Mapping[str, Locked], *, release: str, pid: int) -> str:
    """Write the lock through `atomic_write`: `""`, or why it was not written. Under `SERIAL_LOCK`.

    A lock with no skill left is deleted rather than written empty, so `ow skills remove` of the
    last skill leaves `$OMNIWEAVE_HOME` as it was before the first install.
    """
    path = lock_file(home)
    if not skills:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            return f"could not delete {path}: {type(error).__name__}"
        return ""
    wrote = atomic_write(path, render(skills, release=release), pid=pid)
    return "" if wrote.ok else wrote.reason


def _same(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def claimant(home: Path, path: Path, user_home: Path) -> str:
    """Why `ow skills install` owns the tree at `path`, or `""` when it does not.

    An unreadable lock answers that it cannot tell, which a caller about to delete must treat as a
    claim: the one wrong answer here is *"nobody's"* for a tree that is somebody's.
    """
    lock = read(home)
    if lock.state == "missing":
        return ""
    if lock.state != "read":
        return f"{LOCK_FILE} cannot be read, so whether it owns this is unknown; left in place"
    for entry in lock.skills.values():
        if any(_same(expand(one, user_home), path) for one in entry.installed_to):
            return f"{LOCK_FILE} names it; `ow skills remove {entry.name}` removes it (D490)"
    return ""
