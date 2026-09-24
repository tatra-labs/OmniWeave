"""`ow skills ls | verify | check | hash`: the read-only half of 10:1429's `ow skills` row.

None of the four writes anything. Each returns an `Outcome` whose exit is 10:1429's 0/1/2.

## `verify` ITERATES THE LOCK, AND `--all` ADDS THE RECEIPT

10:1368: *"`ow skills verify` re-hashes every installed bundle and reports `OW-A-031 /
OW_SKILL_HASH_MISMATCH` naming the skill, the expected digest, the observed digest and the **first
differing path**"*. 10:1389 says what it walks: *"it iterates the lock"*. Since D490 the lock lists
only what `ow skills install` placed, and the core skill is normally placed by `ow install --skills
core` and recorded in the install receipt instead. So a plain `verify` would never look at the one
skill every session loads. `--all`, which the plan names and does not define, adds the receipt's
`dir` rows. D493.

The first differing path needs a tree that still has the expected digest to compare against. That
is this release's source bundle when its digest is the recorded one, and nothing otherwise, so the
path is named only then.

## `check`: A STALE OR MISSING CORE SKILL FAILS, NOTHING ELSE DOES

10:1199: *"`ow skills check` exits non-zero on a stale *or* missing **core** skill only"*, and
*"a missing on-demand skill is not 'out of date'"*. The core skill is looked for in every
discovered skills directory, whichever record put it there: the receipt, the lock or the user.
Missing means no discovered directory holds it. Stale means a copy's digest is not this release's.

On-demand skills come from the lock. One whose digest is not this release's is `update available`,
and one the lock attributes to `omniweave/skills` that this release no longer ships is `removed`
(10:1376-1378). Both are reported and neither fails. With no lock, `check` prints `lock_missing:
true` and does not print *"up to date"* (10:1380-1382). An unreadable lock is the same case: *"a
zero-removed result from an unreadable lock is not a clean bill of health"*.

`--check` adds 10:1371's byte diff of the rendered `SKILL.md` set against `skills/expected/`, which
is `omniweave.skills.router.check`. It fails on a difference, because it is a gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave.install import skills_lock
from omniweave.install.receipt import expand, load, tildify
from omniweave.install.skilldir import HASH_MISMATCH, is_link
from omniweave.install.skills_lock import SOURCE
from omniweave.install.skillset import discovered, shipped
from omniweave.install.verbs import OK, USAGE, Outcome
from omniweave.skills import router
from omniweave.skills.hash import ALGO, bundle_sha256, first_difference
from omniweave.skills.tier import CORE, is_core

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave.install.engine import HostEnv
    from omniweave.install.skills_lock import SkillsLock

__all__ = ["check", "digests", "ls", "verify"]

MISMATCH_SYMBOL: Final = "OW_SKILL_HASH_MISMATCH"
"""codes.toml's symbol for `OW-A-031`, which 10:1369 prints beside the numeric."""

_NO_BUNDLES: Final = "this build ships no skill bundles (skills/ is not shipped)"


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(path))


def _short(digest: str) -> str:
    return f"{digest[:4]}…" if digest else "-"


def _tier(name: str) -> str:
    return "core" if is_core(name) else "on-demand"


def _refused(message: str) -> Outcome:
    return Outcome(USAGE, (f"ow: {message}",))


def _source_digests(env: HostEnv) -> dict[str, str]:
    root = env.skills_root
    if root is None:
        return {}
    return {name: bundle_sha256(root / name)[0] for name in shipped(root)}


# ---------------------------------------------------------------------------------------------
# Who recorded a tree.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Recorded:
    """One tree a record says was installed: where, which skill, on which digest, by whom."""

    path: Path
    name: str
    digest: str
    owner: str


def _lock_rows(lock: SkillsLock, env: HostEnv) -> list[_Recorded]:
    return [
        _Recorded(expand(stored, env.user_home), name, entry.bundle_sha256, "skills-lock")
        for name, entry in sorted(lock.skills.items())
        for stored in entry.installed_to
    ]


def _receipt_rows(env: HostEnv) -> list[_Recorded]:
    """The receipt's skill `dir` rows, one per tree: Claude Code's and Codex's share a path."""
    loaded = load(env.omniweave_home, pid=env.pid, release=env.release, back_up=False)
    found: dict[tuple[str, str], _Recorded] = {}
    for entry in loaded.receipt.entries:
        if entry.kind != "skill" or entry.mode != "dir":
            continue
        path = expand(entry.path, env.user_home)
        key = (_norm(path), entry.bundle_sha256)
        seen = found.get(key)
        owner = f"{entry.target} receipt"
        if seen is None:
            found[key] = _Recorded(path, path.name, entry.bundle_sha256, owner)
        elif owner not in seen.owner:
            found[key] = _Recorded(path, path.name, entry.bundle_sha256, f"{seen.owner}, {owner}")
    return list(found.values())


def _owner(path: Path, recorded: list[_Recorded]) -> str:
    owners = [one.owner for one in recorded if _norm(one.path) == _norm(path)]
    return "; ".join(owners) or "unrecorded"


# ---------------------------------------------------------------------------------------------
# ow skills hash.
# ---------------------------------------------------------------------------------------------


def digests(env: HostEnv) -> Outcome:
    """10:1370: each shipped bundle's full digest, file count and byte count, and the algorithm."""
    root = env.skills_root
    names = shipped(root)
    if root is None or not names:
        return _refused(_NO_BUNDLES)
    lines = [f"  {ALGO}"]
    for name in names:
        digest, files, size = bundle_sha256(root / name)
        lines.append(f"  {name:<24} {digest}  {files} files  {size} bytes")
    return Outcome(OK, tuple(lines))


# ---------------------------------------------------------------------------------------------
# ow skills ls.
# ---------------------------------------------------------------------------------------------


def ls(env: HostEnv) -> Outcome:
    """Each shipped skill, its tier and digest, and each discovered directory holding it."""
    want = _source_digests(env)
    lock = skills_lock.read(env.omniweave_home)
    recorded = [*_lock_rows(lock, env), *_receipt_rows(env)]
    places = discovered(env)
    lines: list[str] = []
    for name, digest in want.items():
        where = []
        for place in places:
            tree = place.path / name
            if not tree.is_dir():
                continue
            differs = "" if bundle_sha256(tree)[0] == digest else ", differs"
            where.append(f"{tildify(tree, env.user_home)} ({_owner(tree, recorded)}{differs})")
        held = "; ".join(where) or "not installed"
        lines.append(f"  {name:<24} {_tier(name):<9} {_short(digest):<6} {held}")
    for name, entry in sorted(lock.skills.items()):
        if name not in want:
            places_text = ", ".join(entry.installed_to)
            lines.append(f"  {name:<24} {_tier(name):<9} {'-':<6} not shipped; lock: {places_text}")
    if not lines:
        return _refused(_NO_BUNDLES)
    if lock.state not in {"missing", "read"}:
        lines.append(f"  {skills_lock.LOCK_FILE} cannot be read: {lock.reason}")
    return Outcome(OK, tuple(lines))


# ---------------------------------------------------------------------------------------------
# ow skills verify.
# ---------------------------------------------------------------------------------------------


def verify(env: HostEnv, *, every: bool = False) -> Outcome:
    """Re-hash every tree the lock (and with `every`, the receipt) says was installed."""
    lock = skills_lock.read(env.omniweave_home)
    if lock.state not in {"missing", "read"}:
        return _refused(f"{lock.reason}; nothing verified")
    rows = _lock_rows(lock, env) + (_receipt_rows(env) if every else [])
    if not rows:
        where = "skills-lock.json or the install receipt" if every else "skills-lock.json"
        return Outcome(OK, (f"  nothing to verify: {where} records no installed skill",))
    lines: list[str] = []
    clean = True
    for row in rows:
        line, ok = _verified(row, env)
        lines.append(line)
        clean = clean and ok
    return Outcome(OK if clean else USAGE, tuple(lines))


def _verified(row: _Recorded, env: HostEnv) -> tuple[str, bool]:
    lead = f"  {tildify(row.path, env.user_home):<36} {row.owner:<24}"
    if is_link(row.path):
        return f"{lead} not verified -- a link; the record does not cover its target", True
    if not row.path.is_dir():
        return f"{lead} MISSING -- no directory", False
    have = bundle_sha256(row.path)[0]
    if have == row.digest:
        return f"{lead} ok", True
    detail = f"expected {row.digest}, observed {have}"
    root = env.skills_root
    source = root / row.name if root is not None else None
    if source is not None and source.is_dir() and bundle_sha256(source)[0] == row.digest:
        differs = first_difference(source, row.path)
        detail += f", first differing path {differs}" if differs else ""
    return f"{lead} {HASH_MISMATCH} {MISMATCH_SYMBOL} {row.name}: {detail}", False


# ---------------------------------------------------------------------------------------------
# ow skills check.
# ---------------------------------------------------------------------------------------------


def check(env: HostEnv, *, byte_diff: bool = False) -> Outcome:
    """10:1199's exit, 10:1376-1382's report, and 10:1371's byte diff under `byte_diff`."""
    want = _source_digests(env)
    if CORE not in want:
        return _refused(_NO_BUNDLES)
    recorded = [*_lock_rows(skills_lock.read(env.omniweave_home), env), *_receipt_rows(env)]
    lines, failed = _core_lines(env, want[CORE], recorded)
    warned = _lock_lines(env, want, lines)
    if byte_diff and env.skills_root is not None:
        differences = router.check(env.skills_root)
        lines.extend(f"  --check: {one}" for one in differences)
        if not differences:
            lines.append("  --check: skills/expected/ matches the render")
        failed = failed or bool(differences)
    if not failed and not warned:
        lines.append("up to date")
    elif not failed:
        lines.append("core skill up to date; see the warnings above")
    return Outcome(USAGE if failed else OK, tuple(lines))


def _core_lines(env: HostEnv, want: str, recorded: list[_Recorded]) -> tuple[list[str], bool]:
    """One line per discovered copy of the core skill; failed when none is this release's.

    A copy that is not this release's is one of two things, and they have different fixes. STALE:
    it still has the digest its record wrote, so it is an older release, and the verb that wrote it
    replaces it. MODIFIED: it has no digest any record wrote, and neither verb will replace it
    (`OW-A-031`, 10:1758's *"kept -- modified since install"*), so the fix is to move it aside.
    Measured before the split: a hand-edited copy was called stale and told to run `ow install`,
    which then kept it.
    """
    copies = [one.path / CORE for one in discovered(env) if (one.path / CORE).is_dir()]
    if not copies:
        return [f"  {CORE:<24} core      MISSING -- run `ow install --skills core`"], True
    lines: list[str] = []
    failed = False
    for tree in copies:
        shown = tildify(tree, env.user_home)
        have = bundle_sha256(tree)[0]
        if have == want:
            lines.append(f"  {shown:<36} core      up to date")
            continue
        failed = True
        mine = [one for one in recorded if _norm(one.path) == _norm(tree)]
        owner = "; ".join(one.owner for one in mine) or "unrecorded"
        versus = f"{_short(have)} is not this release's {_short(want)} ({owner})"
        if any(one.digest == have for one in mine):
            lines.append(f"  {shown:<36} core      STALE -- {versus}; {_core_fix(owner)}")
        else:
            aside = "move it aside and run `ow install --skills core`"
            why = "no record wrote these bytes" if mine else "it is on no record"
            lines.append(
                f"  {shown:<36} core      {HASH_MISMATCH} MODIFIED -- {versus}; {why}, so {aside}"
            )
    return lines, failed


def _core_fix(owner: str) -> str:
    if owner == "skills-lock":
        return f"run `ow skills install {CORE}`"
    return "run `ow install --skills core`"


def _lock_lines(env: HostEnv, want: dict[str, str], lines: list[str]) -> bool:
    """The on-demand half, from the lock. Appends to `lines`; true when anything was a warning."""
    lock = skills_lock.read(env.omniweave_home)
    path = tildify(skills_lock.lock_file(env.omniweave_home), env.user_home)
    if lock.state == "missing":
        lines.append(
            f"  lock_missing: true -- {path} is not there, so on-demand staleness and orphans "
            "are unknown (10:1380)"
        )
        return True
    if lock.state != "read":
        lines.append(f"  lock_unreadable: true -- {lock.reason} (10:1381-1382)")
        return True
    warned = False
    for name, entry in sorted(lock.skills.items()):
        if is_core(name):
            continue
        if name not in want:
            if entry.source == SOURCE:
                lines.append(
                    f"  {name:<24} on-demand removed -- this release no longer publishes it "
                    "(10:1377)"
                )
                warned = True
            continue
        if entry.bundle_sha256 != want[name]:
            lines.append(
                f"  {name:<24} on-demand update available -- run `ow skills install {name}`"
            )
            warned = True
        else:
            lines.append(f"  {name:<24} on-demand up to date")
    return warned
