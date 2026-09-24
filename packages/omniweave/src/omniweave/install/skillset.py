"""`ow skills install <name>...` and `ow skills remove <name>...`: W7.6's verb pair (16:720).

10:1429 gives the group `ls | install <name>... | verify [--all] | check [--check] | update | hash`,
exit 0/1/2, and the note *"`remove` is human-only"*. 16:720 schedules two of them. The router
skill's section 4 tells an agent to run the first (10:1261), and the other five wait for cells of
their own.

## WHERE A BUNDLE GOES: EVERY HOST'S SKILLS DIRECTORY THAT EXISTS

10:1393: *"`ow skills install` writes into every discovered `<host>/skills` directory rather than an
enumerated agent list ... hyperframes discovers them by structure, and structure is the version
that survives a new host."* The plan does not say what discovery looks at. Two readings were
available, and the wider one was refused:

- **a glob, `~/.*/skills` and `./.*/skills`.** It finds Claude Code's, Codex's and Cursor's
  directories, and every other tool's `skills/` besides -- a directory omniweave has no host row
  for, whose loader it has never read, and whose owner never asked for omniweave's bundles;
- **each built host's own `skills_dir`, at both locations, kept where it exists.** A new host
  brings its directory with its registry row (10:1628's *"one registry row"*), so this survives a
  new host too, and it writes only where a host omniweave knows reads.

Shipped: the second. A directory that does not exist is not created -- a host that is not
installed has no directory, and creating one would be the enumeration the plan rejects. With
none, the verb refuses and names `ow install --skills core`, which makes the first. D491.

## WHICH SCOPE A DIRECTORY IS, AND WHY THE ORDER IS THE POINT

10:1399-1403, as `scope_of_dir()`: containment in the working directory FIRST, then the home, then
`project` as the safe default, each base compared with a trailing separator. The scope is printed
beside each directory. Nothing prunes yet -- the prune is `ow skills update`'s -- so nothing reads
it but the reader; the rule is here, and tested on 10:1403's `/home/user2` case, so that the day a
prune lands it cannot land with the order reversed.

## TWO LEDGERS, AND NEVER BOTH FOR ONE TREE

The install receipt records what `ow install --skills` wrote, and `skills-lock.json` what this verb
wrote. `skills_lock`'s docstring is the rule (D490): a directory already holding the bundle's
bytes is `unchanged` and is not claimed, and a directory the receipt says `ow install` created is
left to `ow install` and `ow uninstall`, with the note saying so.

## `update`

10:1429 gives it a cell and 15:1530 a use -- D-17's fix -- and nothing else. It is built from the
plan's other sentences about what the lock is for. An entry this release still ships is refreshed
wherever the lock lists it, by `install`'s own decision, so a modified copy is kept. An entry
attributed to `omniweave/skills` that this release no longer ships is pruned by `remove`'s
decision (10:1376-1377). A listed directory that is gone is forgotten and not recreated, because
*"a missing on-demand skill is not 'out of date'"* (10:1197-1198). 10:1402's *"never prune
globally for an unknown path"* is the one place the scope rule acts: an orphan under neither the
working directory nor the home is left for a run from its own project. D498-D500.

## `remove`

The plan is printed first, and nothing is written without `--yes` or a *yes* at the terminal
(10:1620-1621, `ow uninstall`'s rule). Each directory the lock lists is removed when its digest is
the entry's, and kept with `OW-A-031`, both digests and the first differing path (10:1368-1370)
when it is not. A name the lock does not have is `not-found`; exit 2 when every name is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from omniweave.install import skills_lock
from omniweave.install.engine import BUNDLE_ENTRY
from omniweave.install.receipt import RECEIPT_LOCKED, expand, load, take_lock, tildify
from omniweave.install.registry import BUILT, build
from omniweave.install.skilldir import HASH_MISMATCH, MODIFIED, discard, is_link, place
from omniweave.install.skills_lock import SERIAL_LOCK, Locked
from omniweave.install.types import LOCATIONS, FileAction
from omniweave.install.verbs import OK, USAGE, Outcome, row
from omniweave.skills.hash import bundle_sha256, first_difference, walk

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from omniweave.install.engine import HostEnv
    from omniweave.install.receipt import Taken
    from omniweave.install.types import Action, TargetId

__all__ = [
    "NOT_FOUND",
    "Destination",
    "candidates",
    "discovered",
    "install",
    "remove",
    "scope_of_dir",
    "shipped",
    "update",
]

NOT_FOUND: Final = 2
"""10:1485, *"not found"*: 10:1429's third exit, for a name this release does not ship."""

_HOLDERS: Final = "ow skills install, remove or update"
_RECEIPT_REMOVES: Final = "the install receipt names it; `ow uninstall` removes it (D490)"
_RECEIPT_UPDATES: Final = "the install receipt names it; `ow install` updates it (D490)"
_NOT_OURS: Final = "already present with this digest; not recorded as this verb's (D490)"
_FOREIGN: Final = "the directory is not the bundle and not what ow skills install wrote there"

Scope = Literal["project", "global"]


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(path))


def _same(left: Path, right: Path) -> bool:
    return _norm(left) == _norm(right)


def _within(path: Path, base: Path) -> bool:
    """10:1403: *"Each base is normalised with a trailing separator"*, so `user2` is not `user`."""
    return (_norm(path).rstrip(os.sep) + os.sep).startswith(_norm(base).rstrip(os.sep) + os.sep)


def scope_of_dir(directory: Path, cwd: Path | None, home: Path) -> Scope:
    """10:1399-1403: the working directory FIRST, then the home, else `project`."""
    if cwd is not None and _within(directory, cwd):
        return "project"
    if _within(directory, home):
        return "global"
    return "project"


@dataclass(frozen=True, slots=True)
class Destination:
    """One `<host>/skills` directory, the hosts that read it, and its 10:1399-1403 scope."""

    path: Path
    scope: Scope
    hosts: tuple[TargetId, ...]


def candidates(env: HostEnv) -> tuple[Destination, ...]:
    """Every built host's skills directory at every location it supports, one row per directory.

    Claude Code and Codex share `~/.agents/skills` (W7.5k), so the two are one destination read by
    two hosts. A `local` directory needs a project root; a global-only caller has none.
    """
    found: dict[str, tuple[Path, list[TargetId]]] = {}
    for target_id in BUILT:
        host = build(target_id, env)
        for loc in LOCATIONS:
            if not host.supports_location(loc) or (loc == "local" and env.project_root is None):
                continue
            path = host.skills_dir(loc)
            hosts = found.setdefault(_norm(path), (path, []))[1]
            if target_id not in hosts:
                hosts.append(target_id)
    return tuple(
        Destination(path, scope_of_dir(path, env.project_root, env.user_home), tuple(hosts))
        for path, hosts in found.values()
    )


def discovered(env: HostEnv) -> tuple[Destination, ...]:
    """The candidates that exist. D491."""
    return tuple(one for one in candidates(env) if one.path.is_dir())


def shipped(root: Path | None) -> tuple[str, ...]:
    """The bundles under `root` with a `SKILL.md` (10:1152), sorted; `skills/expected/` has none."""
    if root is None or not root.is_dir():
        return ()
    return tuple(sorted(one.name for one in root.iterdir() if (one / BUNDLE_ENTRY).is_file()))


def _refused(message: str, code: int = USAGE) -> Outcome:
    return Outcome(code, (f"ow: {message}",))


def _lock_refusal(taken: Taken) -> Outcome:
    return _refused(f"refused -- {taken.code}: {taken.reason}; nothing written")


def _receipt_created(env: HostEnv) -> Callable[[Path], bool]:
    """Whether the install receipt says `ow install` created the tree at a path. Read-only."""
    loaded = load(env.omniweave_home, pid=env.pid, release=env.release, back_up=False)
    created = tuple(
        expand(entry.path, env.user_home)
        for entry in loaded.receipt.entries
        if entry.mode == "dir" and entry.created_file
    )
    return lambda path: any(_same(path, one) for one in created)


def _hash_detail(digest: str) -> str:
    """18:2980's third column, `bundle_hash 4c1f...`."""
    return f"bundle_hash {digest[:4]}…"


def _act(dest: Path, env: HostEnv, action: Action, note: str = "", **rest: str) -> FileAction:
    shown = tildify(dest, env.user_home)
    return FileAction(shown, action, "skill", "dir", note, **rest)


def _listed(entry: Locked | None, dest: Path, env: HostEnv) -> bool:
    if entry is None:
        return False
    return any(_same(expand(one, env.user_home), dest) for one in entry.installed_to)


# ---------------------------------------------------------------------------------------------
# ow skills install.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Placed:
    """One directory's outcome, and whether the lock lists it afterwards."""

    action: FileAction
    listed: bool


def install(names: Sequence[str], env: HostEnv) -> Outcome:
    """Place each named bundle in every discovered directory, and record what was placed."""
    wanted = tuple(dict.fromkeys(names))
    root = env.skills_root
    ships = shipped(root)
    if root is None or not ships:
        return _refused("this build has no skill bundles to install from (skills/ is not shipped)")
    unknown = [name for name in wanted if name not in ships]
    if unknown:
        return _refused(
            f"this release ships no skill named {', '.join(unknown)}; it ships {', '.join(ships)}",
            NOT_FOUND,
        )
    places = discovered(env)
    if not places:
        looked = ", ".join(tildify(one.path, env.user_home) for one in candidates(env))
        return _refused(
            f"no agent host's skills directory exists (looked for {looked}); "
            "run `ow install --skills core` to wire a host first (D491)"
        )
    taken = take_lock(
        env.omniweave_home, clock=env.clock, wait_ms=env.lock_wait_ms, file=SERIAL_LOCK,
        holders=_HOLDERS,
    )  # fmt: skip
    if taken.lock is None:
        return _lock_refusal(taken)
    with taken.lock:
        return _install_locked(wanted, places, env, root=root, broke=taken)


def _install_locked(
    wanted: Sequence[str],
    places: Sequence[Destination],
    env: HostEnv,
    *,
    root: Path,
    broke: Taken,
) -> Outcome:
    lock = skills_lock.read(env.omniweave_home)
    if not lock.writable:
        return _refused(f"refused -- {lock.reason}; nothing written")
    receipt_created = _receipt_created(env)
    entries = dict(lock.skills)
    lines = [f"  {RECEIPT_LOCKED}: {broke.reason}"] if broke.broke is not None else []
    lines.extend(f"  {one.scope:<7} {tildify(one.path, env.user_home)}  ({', '.join(one.hosts)})"
                 for one in places)  # fmt: skip
    clean = True
    for name in wanted:
        source = root / name
        want, count, total = bundle_sha256(source)
        previous = entries.get(name)
        outcomes = [
            _place_one(
                source,
                one.path / name,
                want=want,
                previous=previous,
                env=env,
                receipt_created=receipt_created,
            )
            for one in places
        ]
        lines.extend(row(one.action, planned=False) for one in outcomes)
        clean = clean and all(one.action.action != "kept" for one in outcomes)
        handled = {_norm(one.path / name) for one in places}
        earlier = [
            one
            for one in (previous.installed_to if previous else ())
            if _norm(expand(one, env.user_home)) not in handled
        ]
        now = [one.action.path for one in outcomes if one.listed]
        installed_to = tuple(dict.fromkeys((*earlier, *now)))
        if installed_to:
            entries[name] = Locked(name, want, count, total, installed_to, f"skills/{name}")
        else:
            entries.pop(name, None)
    if entries != dict(lock.skills):
        home = env.omniweave_home
        why = skills_lock.write(home, entries, release=env.release, pid=env.pid)
        if why:
            shown = tildify(skills_lock.lock_file(home), env.user_home)
            lines.append(f"  {shown} not written -- {why}")
            clean = False
    return Outcome(OK if clean else USAGE, tuple(lines))


def _place_one(
    source: Path,
    dest: Path,
    *,
    want: str,
    previous: Locked | None,
    env: HostEnv,
    receipt_created: Callable[[Path], bool],
) -> _Placed:
    """What one destination decides, and the placement when it may be written."""
    detail = _hash_detail(want)
    listed = _listed(previous, dest, env)
    decided = _decided(dest, want, previous, env, receipt_created, detail=detail, listed=listed)
    if decided is not None:
        return decided
    action: Action = "updated" if dest.exists() else "created"
    why = place(source, dest, want, env.pid)
    if why:
        return _Placed(_act(dest, env, "kept", why, detail=detail), listed)
    return _Placed(_act(dest, env, action, detail=detail), listed=True)


def _unwritable(dest: Path) -> str:
    if is_link(dest):
        return "is a link; not writing or deleting through it"
    if dest.exists() and not dest.is_dir():
        return "is a file, not a directory"
    return ""


def _decided(
    dest: Path,
    want: str,
    previous: Locked | None,
    env: HostEnv,
    receipt_created: Callable[[Path], bool],
    *,
    detail: str,
    listed: bool,
) -> _Placed | None:
    """What an existing destination decides: `None` when this verb may write it."""
    why = _unwritable(dest)
    if why:
        return _Placed(_act(dest, env, "kept", why, detail=detail), listed)
    have = bundle_sha256(dest)[0] if dest.exists() else ""
    if have and receipt_created(dest):
        verdict: Action = "unchanged" if have == want else "kept"
        note = _RECEIPT_REMOVES if have == want else _RECEIPT_UPDATES
        return _Placed(_act(dest, env, verdict, note, detail=detail), listed=False)
    if have == want:
        note = "" if listed else _NOT_OURS
        return _Placed(_act(dest, env, "unchanged", note, detail=detail), listed)
    recorded = previous.bundle_sha256 if previous is not None and listed else ""
    if not have or have == recorded:
        return None
    if not recorded:
        return _Placed(_act(dest, env, "kept", _FOREIGN, detail=detail), listed=False)
    note = f"{MODIFIED}; expected {recorded}; observed {have}"
    return _Placed(_act(dest, env, "kept", note, code=HASH_MISMATCH, detail=detail), listed)


# ---------------------------------------------------------------------------------------------
# ow skills remove.
# ---------------------------------------------------------------------------------------------


def remove(
    names: Sequence[str],
    env: HostEnv,
    *,
    yes: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> Outcome:
    """Print the plan, confirm, then remove each named skill from the directories the lock lists."""
    wanted = tuple(dict.fromkeys(names))
    lock = skills_lock.read(env.omniweave_home)
    if not lock.writable:
        return _refused(f"refused -- {lock.reason}; nothing removed")
    plan = _removals(wanted, lock.skills, env, dry_run=True)
    lines = ["plan", *(row(one, planned=True) for one in plan.actions), *plan.absent]
    if len(plan.absent) == len(wanted):
        return Outcome(NOT_FOUND, tuple(lines))
    if not (yes or (confirm is not None and confirm("Remove these skills?"))):
        lines.append("not confirmed; nothing removed (pass --yes to remove without asking)")
        return Outcome(USAGE, tuple(lines))
    taken = take_lock(
        env.omniweave_home, clock=env.clock, wait_ms=env.lock_wait_ms, file=SERIAL_LOCK,
        holders=_HOLDERS,
    )  # fmt: skip
    if taken.lock is None:
        return _lock_refusal(taken)
    with taken.lock:
        fresh = skills_lock.read(env.omniweave_home)
        if not fresh.writable:
            return _refused(f"refused -- {fresh.reason}; nothing removed")
        done = _removals(wanted, fresh.skills, env, dry_run=False)
        lines.extend(row(one, planned=False) for one in done.actions)
        why = ""
        if done.left != dict(fresh.skills):
            why = skills_lock.write(env.omniweave_home, done.left, release=env.release, pid=env.pid)
    if why:
        lines.append(f"  {skills_lock.LOCK_FILE} not written -- {why}")
    kept = why or any(one.action == "kept" for one in done.actions)
    return Outcome(USAGE if kept else OK, tuple(lines))


@dataclass(frozen=True, slots=True)
class _Removals:
    actions: tuple[FileAction, ...]
    absent: tuple[str, ...]
    left: Mapping[str, Locked]


def _removals(
    wanted: Sequence[str], skills: Mapping[str, Locked], env: HostEnv, *, dry_run: bool
) -> _Removals:
    left = dict(skills)
    actions: list[FileAction] = []
    absent: list[str] = []
    receipt_created = _receipt_created(env)
    for name in wanted:
        entry = skills.get(name)
        if entry is None:
            absent.append(f"  {name}: not-found -- {skills_lock.LOCK_FILE} has no entry for it")
            continue
        remaining: list[str] = []
        for stored in entry.installed_to:
            dest = expand(stored, env.user_home)
            action = _remove_one(dest, entry, env, receipt_created, dry_run=dry_run)
            actions.append(action)
            if action.action == "kept":
                remaining.append(stored)
        if remaining:
            left[name] = Locked(
                name, entry.bundle_sha256, entry.files, entry.bytes, tuple(remaining),
                entry.skill_path, entry.source, entry.source_type,
            )  # fmt: skip
        else:
            left.pop(name, None)
    return _Removals(tuple(actions), tuple(absent), left)


def _remove_one(
    dest: Path,
    entry: Locked,
    env: HostEnv,
    receipt_created: Callable[[Path], bool],
    *,
    dry_run: bool,
) -> FileAction:
    detail = _hash_detail(entry.bundle_sha256)
    blocked = _removal_blocked(dest, entry, env, receipt_created, detail=detail)
    if blocked is not None:
        return blocked
    if dry_run:
        return _act(dest, env, "removed", detail=detail)
    shown = tildify(dest, env.user_home)
    removed, left = discard(dest, shown, lambda one: tildify(one, env.user_home), env.pid)
    return _act(dest, env, "removed" if removed else "kept", left, detail=detail)


def _removal_blocked(
    dest: Path,
    entry: Locked,
    env: HostEnv,
    receipt_created: Callable[[Path], bool],
    *,
    detail: str,
) -> FileAction | None:
    """What stops the removal, or `None` when the tree is this verb's to delete."""
    if is_link(dest):
        return _act(dest, env, "kept", "is a link; not removing through it", detail=detail)
    if not dest.exists():
        return _act(dest, env, "not-found", "no directory", detail=detail)
    if receipt_created(dest):
        return _act(dest, env, "not-found", _RECEIPT_REMOVES, detail=detail)
    have = bundle_sha256(dest)[0]
    if have != entry.bundle_sha256:
        note = f"{MODIFIED}; expected {entry.bundle_sha256}; observed {have}"
        differs = _first_difference(entry, dest, env)
        if differs:
            note += f"; first differing path {differs}"
        return _act(dest, env, "kept", note, code=HASH_MISMATCH, detail=detail)
    links = walk(dest).links
    if links:
        why = f"holds {', '.join(links)}, a link the digest does not cover; not removing it"
        return _act(dest, env, "kept", why, detail=detail)
    return None


def _first_difference(entry: Locked, dest: Path, env: HostEnv) -> str:
    """10:1369's *"first differing path"*, when the source at hand still has the entry's digest."""
    root = env.skills_root
    source = root / entry.name if root is not None else None
    if source is None or not source.is_dir() or bundle_sha256(source)[0] != entry.bundle_sha256:
        return ""
    return first_difference(source, dest) or ""


# ---------------------------------------------------------------------------------------------
# ow skills update.
# ---------------------------------------------------------------------------------------------

_FORGOTTEN: Final = (
    "no directory; forgotten, not reinstalled -- a missing on-demand skill is not out of date "
    "(10:1197-1198)"
)
_PRUNED: Final = "this release no longer publishes it (10:1377)"
_UNKNOWN_PATH: Final = (
    "under neither this project nor the home, so not pruned from here (10:1402); run `ow skills "
    "update` from the project it belongs to"
)


def update(env: HostEnv) -> Outcome:
    """Refresh what the lock records and prune what this release no longer ships. D498-D500.

    Each entry attributed to `omniweave/skills` is one of two cases:
    - **shipped:** each listed directory goes through `install`'s own decision against this
      release's bundle -- `updated` on the recorded digest, `unchanged` on the new one, `kept` with
      `OW-A-031` when modified. A listed directory that is gone is forgotten, not recreated;
    - **not shipped:** each listed directory goes through `remove`'s decision -- `removed` on the
      recorded digest, `kept` otherwise -- except one under neither the working directory nor the
      home, which 10:1402's *"never prune globally for an unknown path"* leaves alone.

    An entry from another source is never touched (10:1378). Nothing is asked: every write is to a
    tree the lock says this verb placed, on the digest it recorded.
    """
    root = env.skills_root
    ships = shipped(root)
    if root is None or not ships:
        return _refused("this build has no skill bundles to update from (skills/ is not shipped)")
    taken = take_lock(
        env.omniweave_home, clock=env.clock, wait_ms=env.lock_wait_ms, file=SERIAL_LOCK,
        holders=_HOLDERS,
    )  # fmt: skip
    if taken.lock is None:
        return _lock_refusal(taken)
    with taken.lock:
        return _update_locked(env, root, ships)


def _update_locked(env: HostEnv, root: Path, ships: Sequence[str]) -> Outcome:
    lock = skills_lock.read(env.omniweave_home)
    if not lock.writable:
        return _refused(f"refused -- {lock.reason}; nothing updated")
    if lock.state == "missing":
        shown = tildify(skills_lock.lock_file(env.omniweave_home), env.user_home)
        return Outcome(OK, (f"  lock_missing: true -- {shown} is not there; nothing to update",))
    receipt_created = _receipt_created(env)
    entries = dict(lock.skills)
    lines: list[str] = []
    clean = True
    for name, entry in sorted(lock.skills.items()):
        if entry.source != skills_lock.SOURCE:
            lines.append(f"  {name}: left alone -- attributed to {entry.source} (10:1378)")
            continue
        if name in ships:
            actions, kept = _refreshed(entry, root / name, env, receipt_created)
        else:
            actions, kept = _pruned(entry, env, receipt_created)
        lines.extend(row(one, planned=False) for one in actions)
        clean = clean and all(one.action != "kept" for one in actions)
        if kept is None:
            entries.pop(name, None)
        else:
            entries[name] = kept
    if entries != dict(lock.skills):
        why = skills_lock.write(env.omniweave_home, entries, release=env.release, pid=env.pid)
        if why:
            lines.append(f"  {skills_lock.LOCK_FILE} not written -- {why}")
            clean = False
    return Outcome(OK if clean else USAGE, tuple(lines))


def _refreshed(
    entry: Locked, source: Path, env: HostEnv, receipt_created: Callable[[Path], bool]
) -> tuple[list[FileAction], Locked | None]:
    """One shipped entry, brought to this release's bundle wherever the lock lists it."""
    want, count, total = bundle_sha256(source)
    actions: list[FileAction] = []
    remaining: list[str] = []
    for stored in entry.installed_to:
        dest = expand(stored, env.user_home)
        if not dest.exists() and not is_link(dest):
            actions.append(_act(dest, env, "not-found", _FORGOTTEN, detail=_hash_detail(want)))
            continue
        placed = _place_one(
            source, dest, want=want, previous=entry, env=env, receipt_created=receipt_created
        )
        actions.append(placed.action)
        if placed.listed:
            remaining.append(stored)
    if not remaining:
        return actions, None
    return actions, Locked(entry.name, want, count, total, tuple(remaining), entry.skill_path)


def _pruned(
    entry: Locked, env: HostEnv, receipt_created: Callable[[Path], bool]
) -> tuple[list[FileAction], Locked | None]:
    """One entry this release no longer ships, removed wherever its digest still holds."""
    actions: list[FileAction] = []
    remaining: list[str] = []
    cwd, home = env.project_root, env.user_home
    for stored in entry.installed_to:
        dest = expand(stored, home)
        known = (cwd is not None and _within(dest, cwd)) or _within(dest, home)
        if not known:
            detail = _hash_detail(entry.bundle_sha256)
            action = _act(dest, env, "kept", _UNKNOWN_PATH, detail=detail)
        else:
            action = _remove_one(dest, entry, env, receipt_created, dry_run=False)
            if action.action == "removed" and not action.note:
                action = replace(action, note=_PRUNED)
        actions.append(action)
        if action.action == "kept":
            remaining.append(stored)
    if not remaining:
        return actions, None
    return actions, replace(entry, installed_to=tuple(remaining))
