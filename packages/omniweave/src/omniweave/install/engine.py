"""The one engine every host runs: a host names its writes as `Step`s, and this runs them.

10:1628's claim -- *"a new host is one file plus one registry row"* -- is only true if the lock, the
receipt, the order of writes and their undoing, the dry run and the never-throwing uninstall live
somewhere that is not the host's file. They live here. A host says *what* it writes where
(`Step`), and in what order; `install()` and `uninstall()` are the same for all seven.

## THE RECEIPT IS WRITTEN AS THE WRITES HAPPEN, UNDER THE LOCK

10:1739: *"The receipt is appended per entry, immediately after each write"*, and 10:1744: under
`$OMNIWEAVE_HOME/.install.lock`. So `install()` takes the lock before its first write, records each
step's row the moment its mode returns one, and stops -- naming what it did not reach -- if a row
cannot be recorded, because every write after that would be an artefact with no row. A receipt it
cannot rewrite at all (unreadable, or a newer schema) refuses the install before anything is
written. A dry run takes no lock and writes nothing, not even a backup (D453).

## UNDOING IS NOT THE ROWS IN REVERSE, AND WHAT A ROW CREATED IS PER FILE

Two of claude-code's steps write one file: permissions, then hooks, both into `settings.json`. The
first write creates the file, so only the permissions row says `created_file`. Undo them in the
wrong order -- permissions first, while the hooks are still there -- and the file is not empty when
the row that may delete it is undone; the hooks row that empties it next never created it, so it
writes `{}` and the user is left with a file they never had. The receipt's own order cannot be
trusted to be right: D449 moves a re-recorded row last, so a re-install that grants `Bash(ow:*)`
puts the permissions row after the hooks row.

So uninstall runs the host's steps in **reverse step order**, and gives every row for one file the
union of what any of them created: whichever removal empties the file is the one that deletes it.
The directories install created are swept **once, after every step**, innermost first:
`~/.claude` holds both `settings.json` and `CLAUDE.md`, and a sweep after the first removal would
find it not yet empty and report a leftover that the next step was about to clear. D459.

## A ROW NO STEP NAMES IS STILL UNDONE

A later release that moves a file leaves rows naming the old path. Uninstall finds them in the
receipt, filtered to this target and scope (10:1738), and undoes each by its mode at the path it
names, after the steps. *"removes ONLY what install wrote"* (10:1640) is a promise about the
receipt, not about the current release's table.

## ONE ARTEFACT, TWO HOSTS: THE LAST ONE OUT REMOVES IT

Codex reads skills from `$HOME/.agents/skills` and `.agents/skills` -- the directories 10:1671
gives Claude Code. So both hosts' rows can name one `~/.agents/skills/omniweave`, and the second
install finds the first one's tree and records it as not its own. Without a rule, uninstalling
the host that created it takes the skill from the host still wired to it. So a row whose kind,
mode and path another target's row in the same scope also names is **kept and forgotten**, and
what it created -- the file flag and its directories -- is handed to that row, which then removes
it when its own host goes. Byte identity still holds, whatever the order. D481.

## NEVER THROW

10:1765: *"Two nested `try/except`; a failed cleanup must not block the uninstall."* One around
each step and one around the sweep; an exception becomes a `kept` action or a note naming it, and
every later step still runs.
"""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.contract import RELEASE
from omniweave_core.locks import INTERACTIVE_WAIT_MS

from omniweave.gen.instructions import FRONT_DOOR, TOOL_PREFIX
from omniweave.install.hookrules import Desired, converge
from omniweave.install.modes import (
    Applied,
    Site,
    add_values,
    remove_section,
    remove_values,
    set_hooks,
    set_key,
    unset_hooks,
    unset_key,
    upsert_section,
)
from omniweave.install.primitives import (
    HTML,
    Markers,
    read_json,
    remove_empty_dirs,
    render_json,
)
from omniweave.install.receipt import (
    Entry,
    expand,
    forget,
    identity_of,
    load,
    owned_key,
    record,
    take_lock,
    tildify,
)
from omniweave.install.skilldir import install_dir, remove_dir
from omniweave.install.skills_lock import claimant
from omniweave.install.types import FileAction, WriteResult
from omniweave.skills.hash import bundle_sha256
from omniweave.skills.tier import CORE
from omniweave.surface.registry import ACTIONS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from omniweave_core.clock import Clock

    from omniweave.install.receipt import InstallLock, Receipt
    from omniweave.install.types import Kind, Location, Mode, SkillSet, TargetId

__all__ = [
    "BUNDLE_ENTRY",
    "CORE_SKILL",
    "HostEnv",
    "Step",
    "configured",
    "entry_detail",
    "install",
    "instruction_block",
    "render_step",
    "scope_of",
    "serve_note",
    "skill_names",
    "skill_step",
    "step_detail",
    "uninstall",
]

_WINDOWS: Final = sys.platform == "win32"

_INSTRUCTION_LEAD: Final = (
    "omniweave indexes documents with page-level citations. Ask its MCP tools rather than "
    "reading whole files:"
)


@dataclass(frozen=True, slots=True)
class HostEnv:
    """What a target needs that is not the target: where, whose home, which clock, which launcher.

    All of it injected. The working directory, the clock and randomness are banned in library
    code (the semgrep rules), and `launch` is `hookrules.launcher()`'s answer resolved once by the
    caller, so `print_config` -- which *"MUST NOT touch the filesystem"* (10:1641) -- need not look
    for `ow`. `project_root` is the resolved, absolute root a `local` install writes under and keys
    its rows by (10:1734); a global-only caller leaves it `None`. `skills_root` is where the skill
    bundles come from -- 10:1327's `"source":"omniweave/skills"`, the shipped tree. `environ` is
    the process environment, handed in for the variables a host names its own home by: Codex's
    `CODEX_HOME` (W7.5k). Empty by default, so a host reads its documented default.
    """

    omniweave_home: Path
    user_home: Path
    clock: Clock
    pid: int
    launch: tuple[str, ...] | str
    project_root: Path | None = None
    release: str = RELEASE
    windows: bool = _WINDOWS
    sleep: Callable[[float], None] = time.sleep
    which: Callable[[str], str | None] = shutil.which
    lock_wait_ms: int = INTERACTIVE_WAIT_MS
    skills_root: Path | None = None
    environ: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Step:
    """One write a host makes, and what undoing it needs when there is no row to say.

    Which fields matter is the mode's: `json-key` takes `key` and `value`; `json-array-add` `key`
    and `values`; `marker-section` `body`; `json-hook-rules` `hooks`. `refusal` makes the step a
    `kept` action without a write -- no launcher to put in a command, say -- and `note` is appended
    to whatever the step reports. `dir` takes `source`, the bundle to copy; uninstall uses it to
    re-derive (a tree equal to it is this release's) and to name the first differing path.
    `marker-section` also takes `head`, the first lines of a file it creates (D477), `markers`,
    its comment syntax, and `validate`, which refuses a text that must not be written (D480).
    """

    kind: Kind
    mode: Mode
    path: Path
    key: str = ""
    value: Any = None
    values: tuple[str, ...] = ()
    body: str = ""
    hooks: tuple[Desired, ...] = ()
    source: Path | None = None
    refusal: str = ""
    note: str = ""
    head: str = ""
    markers: Markers = HTML
    validate: Callable[[str], str] | None = None


def scope_of(env: HostEnv, loc: Location) -> tuple[str | None, str]:
    """`(scope_root, refusal)`: `None` for global, the project root for local (10:1734)."""
    if loc == "global":
        return None, ""
    root = env.project_root
    if root is None or not root.is_absolute():
        return None, "a local install needs the absolute project root it writes under"
    return str(root), ""


def _notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _coded(code: str, reason: str) -> str:
    return f"{code}: {reason}" if code else reason


def _site(target: TargetId, loc: Location, scope: str | None, path: Path, env: HostEnv) -> Site:
    return Site(target, loc, path, env.user_home, scope_root=scope)


# ---------------------------------------------------------------------------------------------
# install.
# ---------------------------------------------------------------------------------------------


def install(
    target: TargetId,
    loc: Location,
    steps: Sequence[Step],
    env: HostEnv,
    *,
    dry_run: bool = False,
    notes: Sequence[str] = (),
) -> WriteResult:
    """Run `steps` in order, recording each row as it is written. See the module docstring."""
    scope, refusal = scope_of(env, loc)
    if refusal:
        return WriteResult(target, loc, notes=tuple(notes), refused=refusal)
    if dry_run:
        loaded = load(env.omniweave_home, pid=env.pid, release=env.release, back_up=False)
        planned = _planned(target, loc, scope, steps, env, receipt=loaded.receipt)
        return WriteResult(target, loc, planned, notes=tuple(notes))
    taken = take_lock(env.omniweave_home, clock=env.clock, wait_ms=env.lock_wait_ms)
    if taken.lock is None:
        return WriteResult(
            target, loc, notes=tuple(notes), refused=_coded(taken.code, taken.reason)
        )
    lines = [*notes, _coded(taken.code, taken.reason)] if taken.reason else [*notes]
    with taken.lock as lock:
        loaded = load(env.omniweave_home, pid=env.pid, release=env.release)
        if not loaded.writable:
            why = loaded.reason or loaded.state
            return WriteResult(
                target,
                loc,
                notes=tuple(lines),
                refused=f"the receipt cannot be rewritten ({why}), so nothing was installed: "
                "10:1739 records each write as it happens",
            )
        if loaded.code:
            lines.append(_coded(loaded.code, f"the receipt would not parse: {loaded.reason}"))
        actions: list[FileAction] = []
        for index, step in enumerate(steps):
            applied = _apply(_site(target, loc, scope, step.path, env), step, env, loaded.receipt)
            actions.append(applied.action)
            failed = _keep(lock, applied, env)
            if failed:
                rest = ", ".join(one.path.as_posix() for one in steps[index + 1 :])
                lines.append(failed + (f"; stopped before {rest}" if rest else ""))
                break
    return WriteResult(target, loc, tuple(actions), notes=tuple(lines))


def _planned(
    target: TargetId,
    loc: Location,
    scope: str | None,
    steps: Sequence[Step],
    env: HostEnv,
    *,
    receipt: Receipt,
) -> tuple[FileAction, ...]:
    """Each step's dry-run action, as the real run would report it. D468.

    A dry run writes nothing, so a second step into a file the first would create still finds no
    file and says `created`. Measured: claude-code's plan read `create` twice for `settings.json`,
    where the install that followed reported `created` then `updated`, and 18:2976-2978 prints the
    hooks row of a two-step file as `update`. A path an earlier step would create is an update to
    every later one.
    """
    created: set[Path] = set()
    planned: list[FileAction] = []
    for step in steps:
        action = _apply(_site(target, loc, scope, step.path, env), step, env, receipt, dry_run=True)
        one = action.action
        if one.action == "created" and step.path in created:
            one = replace(one, action="updated")
        elif one.action == "created":
            created.add(step.path)
        planned.append(one)
    return tuple(planned)


def _apply(
    site: Site, step: Step, env: HostEnv, receipt: Receipt, *, dry_run: bool = False
) -> Applied:
    if step.refusal:
        action = site.act("kept", step.kind, step.mode, step.refusal)
        return Applied(replace(action, detail=step_detail(step)))
    found = receipt.find(
        identity_of(site.target, site.location, site.scope_root, step.kind, site.shown)
    )
    applied = _write(site, step, found, env, dry_run=dry_run)
    note = _notes(applied.action.note, step.note)
    return replace(applied, action=replace(applied.action, note=note, detail=step_detail(step)))


def _write(
    site: Site, step: Step, previous: Entry | None, env: HostEnv, *, dry_run: bool
) -> Applied:
    clock, pid, sleep = env.clock, env.pid, env.sleep
    if step.mode == "json-key":
        return set_key(
            site, step.kind, step.key, step.value,
            previous=previous, clock=clock, pid=pid, dry_run=dry_run, sleep=sleep,
        )  # fmt: skip
    if step.mode == "json-array-add":
        return add_values(
            site, step.kind, step.key, step.values,
            previous=previous, clock=clock, pid=pid, dry_run=dry_run, sleep=sleep,
        )  # fmt: skip
    if step.mode == "marker-section":
        return upsert_section(
            site, step.kind, step.body,
            previous=previous, clock=clock, pid=pid, dry_run=dry_run, sleep=sleep, head=step.head,
            markers=step.markers, validate=step.validate,
        )  # fmt: skip
    if step.mode == "json-hook-rules":
        return set_hooks(
            site, step.hooks,
            previous=previous, clock=clock, pid=pid, dry_run=dry_run, sleep=sleep,
        )  # fmt: skip
    if step.source is None:
        return Applied(site.act("kept", step.kind, step.mode, "no bundle to copy"))
    return install_dir(site, step.source, previous=previous, clock=clock, pid=pid, dry_run=dry_run)


def _keep(lock: InstallLock, applied: Applied, env: HostEnv) -> str:
    """Record or forget the row `applied` names; why not, when the receipt refused it."""
    if applied.record is not None:
        done = record(lock, applied.record, release=env.release, pid=env.pid, sleep=env.sleep)
    elif applied.forget is not None:
        identities = [applied.forget.identity()]
        done = forget(lock, identities, release=env.release, pid=env.pid, sleep=env.sleep)
    else:
        return ""
    if done.ok:
        return ""
    return f"{applied.action.path} was written but its receipt row was not: {done.reason}"


# ---------------------------------------------------------------------------------------------
# uninstall.
# ---------------------------------------------------------------------------------------------


def uninstall(
    target: TargetId,
    loc: Location,
    steps: Sequence[Step],
    env: HostEnv,
    *,
    dry_run: bool = False,
    keep: frozenset[str] = frozenset(),
) -> WriteResult:
    """Undo `steps` in reverse, then any row they do not name; never raises. D459.

    `keep` names array values to leave in place: 10:1428's `--keep-cli` keeps `Bash(ow:*)`. A value
    kept leaves with its row, so from then on it is the user's grant, not omniweave's.
    """
    scope, refusal = scope_of(env, loc)
    if refusal:
        return WriteResult(target, loc, refused=refusal)
    if dry_run:
        loaded = load(env.omniweave_home, pid=env.pid, release=env.release, back_up=False)
        actions, lines = _undo_all(
            target, loc, scope, steps, env,
            receipt=loaded.receipt, lock=None, dry_run=True, keep=keep,
        )  # fmt: skip
        return WriteResult(target, loc, actions, notes=lines)
    taken = take_lock(env.omniweave_home, clock=env.clock, wait_ms=env.lock_wait_ms)
    if taken.lock is None:
        return WriteResult(target, loc, refused=_coded(taken.code, taken.reason))
    lines = [_coded(taken.code, taken.reason)] if taken.reason else []
    with taken.lock as lock:
        loaded = load(env.omniweave_home, pid=env.pid, release=env.release)
        if not loaded.writable:
            lines.append(
                f"the receipt cannot be read ({loaded.reason or loaded.state}): every path is "
                "undone by re-derivation (10:1758) and the receipt is left as it is"
            )
        writer = lock if loaded.writable else None
        actions, more = _undo_all(
            target, loc, scope, steps, env,
            receipt=loaded.receipt, lock=writer, dry_run=False, keep=keep,
        )  # fmt: skip
    return WriteResult(target, loc, actions, notes=(*lines, *more))


def _undo_all(
    target: TargetId,
    loc: Location,
    scope: str | None,
    steps: Sequence[Step],
    env: HostEnv,
    *,
    receipt: Receipt,
    lock: InstallLock | None,
    dry_run: bool,
    keep: frozenset[str],
) -> tuple[tuple[FileAction, ...], tuple[str, ...]]:
    scoped = receipt.for_scope(loc, scope)
    rows = [entry for entry in scoped if entry.target == target]
    shared = _sharers(scoped, target)
    creators = _creators(rows)
    by_place = {(entry.kind, entry.path): entry for entry in rows}
    work: list[tuple[Site, Kind, Mode, Entry | None, Step | None]] = []
    for step in reversed(steps):
        site = _site(target, loc, scope, step.path, env)
        work.append((site, step.kind, step.mode, by_place.pop((step.kind, site.shown), None), step))
    for entry in reversed([one for one in rows if (one.kind, one.path) in by_place]):
        site = _site(target, loc, scope, expand(entry.path, env.user_home), env)
        work.append((site, entry.kind, entry.mode, entry, None))
    return _run_undo(work, creators, env, lock, dry_run=dry_run, keep=keep, shared=shared)


def _sharers(rows: Sequence[Entry], target: TargetId) -> dict[tuple[str, str, str], Entry]:
    """Per `(kind, mode, path)`, another target's row naming the same artefact. D481."""
    found: dict[tuple[str, str, str], Entry] = {}
    for entry in rows:
        if entry.target != target:
            found.setdefault((entry.kind, entry.mode, entry.path), entry)
    return found


def _hand_over(
    site: Site,
    kind: Kind,
    mode: Mode,
    *,
    entry: Entry | None,
    sibling: Entry,
    env: HostEnv,
    lock: InstallLock | None,
) -> tuple[Applied, str]:
    """Keep what `sibling`'s host still uses; give it what `entry` created. D481.

    With no row of this target's there is nothing of its own to remove, and re-derivation must not
    take the sibling's artefact on a digest's word: that is `not-found`, not `kept`.
    """
    if entry is None:
        note = f"{sibling.target}'s row names it; not this host's to remove (D481)"
        return Applied(site.act("not-found", kind, mode, note)), ""
    note = f"{sibling.target}'s row names it too, and removes it when it goes (D481)"
    applied = Applied(site.act("kept", kind, mode, note), forget=entry)
    if lock is None or not (entry.created_file or entry.created_dirs):
        return applied, ""
    heir = replace(
        sibling,
        created_file=sibling.created_file or entry.created_file,
        created_dirs=tuple(dict.fromkeys((*sibling.created_dirs, *entry.created_dirs))),
    )
    done = record(lock, heir, release=env.release, pid=env.pid, sleep=env.sleep)
    if done.ok:
        return applied, ""
    return applied, f"{site.shown}: handing it to {sibling.target}'s row failed: {done.reason}"


def _run_undo(
    work: Sequence[tuple[Site, Kind, Mode, Entry | None, Step | None]],
    creators: Mapping[str, bool],
    env: HostEnv,
    lock: InstallLock | None,
    *,
    dry_run: bool,
    keep: frozenset[str] = frozenset(),
    shared: Mapping[tuple[str, str, str], Entry] | None = None,
) -> tuple[tuple[FileAction, ...], tuple[str, ...]]:
    """Each undo in `work`'s order, then the one sweep of created directories. D459.

    `lock` is `None` on a dry run and when the receipt cannot be rewritten; rows are then left.
    A row another target's row shares is kept and handed over instead of undone (D481).
    """
    actions: list[FileAction] = []
    lines: list[str] = []
    swept: list[Path] = []
    for site, kind, mode, entry, step in work:
        sibling = (shared or {}).get((kind, mode, site.shown))
        if sibling is not None:
            own = replace(entry, created_file=creators.get(entry.path, False)) if entry else None
            applied, failed = _hand_over(
                site, kind, mode, entry=own, sibling=sibling, env=env, lock=lock
            )
            lines.extend([failed] if failed else [])
            detail = entry_detail(entry) if entry is not None else step_detail(step)
            actions.append(replace(applied.action, detail=detail))
            if entry is not None and lock is not None:
                done = forget(lock, [entry.identity()], release=env.release, pid=env.pid)
                if not done.ok:
                    lines.append(f"{site.shown} was kept but its receipt row was not forgotten")
            continue
        merged = _merged(entry, creators, keep)
        try:
            applied = _undo(site, kind, mode, entry=merged, step=step, env=env, dry_run=dry_run)
        except Exception as error:  # 10:1765: a failed undo must not block the rest
            note = f"failed: {type(error).__name__}: {error}"
            applied = Applied(site.act("kept", kind, mode, note))
        detail = entry_detail(entry) if entry is not None else step_detail(step)
        actions.append(replace(applied.action, detail=detail))
        if applied.forget is None or entry is None:
            continue
        swept.extend(expand(one, env.user_home) for one in entry.created_dirs)
        if lock is not None:
            done = forget(lock, [entry.identity()], release=env.release, pid=env.pid)
            if not done.ok:
                lines.append(f"{site.shown} was removed but its receipt row was not: {done.reason}")
    if not dry_run:
        try:
            left = remove_empty_dirs(swept)
        except Exception as error:  # 10:1765, the second of the two
            left = ()
            lines.append(f"the directory sweep failed: {type(error).__name__}: {error}")
        lines.extend(f"Could not remove {_spell(one, env)} -- it is not empty" for one in left)
    return tuple(actions), tuple(lines)


def _creators(rows: Sequence[Entry]) -> dict[str, bool]:
    """Per path, whether any row for it created the file. D459."""
    created: dict[str, bool] = {}
    for entry in rows:
        created[entry.path] = created.get(entry.path, False) or entry.created_file
    return created


def _merged(
    entry: Entry | None, creators: Mapping[str, bool], keep: frozenset[str] = frozenset()
) -> Entry | None:
    """`entry` with its file's creator flag, no directories -- the sweep removes those -- and
    none of the array values the caller asked to keep."""
    if entry is None:
        return None
    values = tuple(one for one in entry.values if one not in keep)
    return replace(
        entry, created_file=creators.get(entry.path, False), created_dirs=(), values=values
    )


def _undo(
    site: Site,
    kind: Kind,
    mode: Mode,
    *,
    entry: Entry | None,
    step: Step | None,
    env: HostEnv,
    dry_run: bool,
) -> Applied:
    key = step.key if step is not None else ""
    pid, sleep = env.pid, env.sleep
    if mode == "json-key":
        return unset_key(site, kind, key, entry=entry, pid=pid, dry_run=dry_run, sleep=sleep)
    if mode == "json-array-add":
        values = step.values if step is not None else ()
        return remove_values(
            site, kind, key, values, entry=entry, pid=pid, dry_run=dry_run, sleep=sleep
        )
    if mode == "marker-section":
        head = step.head if step is not None else ""
        markers = step.markers if step is not None else HTML
        return remove_section(
            site, kind, entry=entry, pid=pid, dry_run=dry_run, sleep=sleep, head=head,
            markers=markers,
        )  # fmt: skip
    if mode == "json-hook-rules":
        return unset_hooks(site, entry=entry, pid=pid, dry_run=dry_run, sleep=sleep)
    source = step.source if step is not None else None
    if entry is None:
        #  10:1758-1759's re-derivation has no row to say whose the tree is; `skills-lock.json` may.
        owner = claimant(env.omniweave_home, site.path, env.user_home)
        if owner:
            return Applied(site.act("not-found", kind, mode, owner))
    return remove_dir(site, entry=entry, source=source, pid=pid, dry_run=dry_run)


def _spell(path: Path, env: HostEnv) -> str:
    return tildify(path, env.user_home)


def _bundle_hash(digest: str) -> str:
    return f"bundle_hash {digest[:4]}\u2026" if digest else "bundle"


def step_detail(step: Step | None) -> str:
    """18:2975-2980's third column for a step: what it writes, in a few words."""
    if step is None:
        return ""
    if step.mode == "json-key":
        return step.key
    if step.mode == "json-array-add":
        return f"{step.key} += {' '.join(step.values)}"
    if step.mode == "json-hook-rules":
        return " ".join(one.event for one in step.hooks) or "none of ours"
    if step.mode == "marker-section":
        return step.markers.begin
    source = step.source
    digest = bundle_sha256(source)[0] if source is not None and source.is_dir() else ""
    return _bundle_hash(digest)


def entry_detail(entry: Entry) -> str:
    """The same column for a receipt row: what omniweave wrote there."""
    if entry.mode == "json-key":
        return entry.key
    if entry.mode == "json-array-add":
        return f"{entry.key} += {' '.join(entry.values)}".strip()
    if entry.mode == "json-hook-rules":
        return " ".join(entry.events)
    if entry.mode == "marker-section":
        return entry.marker
    return _bundle_hash(entry.bundle_sha256)


# ---------------------------------------------------------------------------------------------
# What a host shows without writing: detection, print_config, the instruction block.
# ---------------------------------------------------------------------------------------------


def configured(path: Path, key: str, *, pid: int) -> bool:
    """Whether `path` has a value at `key`. Reads only: nothing is backed up (D453)."""
    read = read_json(path, pid=pid, back_up=False)
    return read.state == "parsed" and owned_key(read.value, key) is not None


def render_step(step: Step, shown: str) -> str:
    """One step as `print_config` shows it: the path, the mode, and the exact value. Pure."""
    head = f"# {shown}  {step.mode}"
    if step.refusal:
        return f"{head}  NOT written: {step.refusal}"
    if step.mode == "json-key":
        return f"{head}  {step.key}\n{_json(step.value)}"
    if step.mode == "json-array-add":
        return f"{head}  {step.key} += {' '.join(step.values)}"
    if step.mode == "json-hook-rules":
        document: dict[str, Any] = {}
        converge(document, step.hooks)
        return f"{head}  {' '.join(one.event for one in step.hooks)}\n{_json(document)}"
    if step.mode == "marker-section":
        first = f"{step.head}\n" if step.head else ""
        marks = step.markers
        return f"{head}\n{first}{marks.begin}\n{step.body}\n{marks.end}"
    return f"{head}  a copy of {step.source}, recorded by its sha256-bundle-1 digest"


def _json(value: object) -> str:
    return render_json(value).decode("utf-8").rstrip("\n")


def instruction_block(prefix: str | None = TOOL_PREFIX) -> str:
    """The `marker-section` body: the listed tools and their `decision` clauses. D461.

    10:1669 names the section and no document writes its body. 10:209 gives the recipe for the
    one steering prose that is generated -- *"the listed set plus `decision` clauses"* -- and 10:111
    is why nothing else will do: an always-on block written against a surface rather than from it
    is jcodemunch's bug #397. So each line is an Action in the front door's order with its
    registry `decision`, and a fifth listed tool changes this text without anyone editing it.

    `prefix` is the host's spelling of a tool's name, and the last line says it. It is Claude
    Code's `mcp__omniweave__` by default; a host whose spelling no measurement has shown passes
    `None` and the line is left out rather than guessed (D476).
    """
    lines = [_INSTRUCTION_LEAD]
    for name in FRONT_DOOR:
        spec = ACTIONS[name]
        lines.append(f"- `{spec.mcp_name}` when {spec.decision}")
    if prefix:
        lines.append(f"Their host-side names start `{prefix}`.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# What two hosts share and neither owns: the skill steps, and the serve note.
# ---------------------------------------------------------------------------------------------

CORE_SKILL: Final = CORE
"""10:1151: *"THE ONLY ALWAYS-RESIDENT SKILL"*, by `skills.tier`'s rule (10:1185-1188)."""

BUNDLE_ENTRY: Final = "SKILL.md"
"""The file that makes a directory a skill bundle (10:1152)."""

_SERVE_ROOT: Final = "serve"


def serve_note() -> str:
    """What an MCP step says while `python -m omniweave` does not dispatch `serve`. D460."""
    from omniweave.__main__ import DISPATCHED  # noqa: PLC0415 -- the dispatcher, read live

    if _SERVE_ROOT in DISPATCHED:
        return ""
    return (
        "the host will start `serve --mcp`, which this build does not dispatch: it exits 70 "
        "until it does (D460)"
    )


def skill_names(env: HostEnv, skills: SkillSet) -> tuple[str, ...]:
    """`core` is the router alone (10:1151); `all` adds every bundle with a `SKILL.md`."""
    if skills == "none":
        return ()
    root = env.skills_root
    if skills == "core" or root is None or not root.is_dir():
        return (CORE_SKILL,)
    others = sorted(
        one.name
        for one in root.iterdir()
        if one.name != CORE_SKILL and (one / BUNDLE_ENTRY).is_file()
    )
    return (CORE_SKILL, *others)


def skill_step(env: HostEnv, skills_dir: Path, name: str, *, check: bool) -> Step:
    """The `dir` step for bundle `name` into `skills_dir`; refused without a `SKILL.md` (W7.5f)."""
    root = env.skills_root
    source = root / name if root is not None else None
    refusal = ""
    if check and source is None:
        refusal = "no skill bundle source was given"
    elif check and source is not None and not (source / BUNDLE_ENTRY).is_file():
        bare = source.as_posix()
        refusal = f"{bare} has no {BUNDLE_ENTRY}, so it is not a skill bundle (10:1152)"
    return Step("skill", "dir", skills_dir / name, source=source, refusal=refusal)
