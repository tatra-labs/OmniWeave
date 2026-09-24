"""`ow install | uninstall | --check`: the verbs' engine, over the registry's hosts.

10:1427-1428 give the two rows and 10 section 7 the flow. This module is what those verbs do; the
argv they are parsed from is `run.py`'s. Each function returns an `Outcome` -- an exit code and the
lines to print -- and reads the terminal only through the `confirm` it is handed, so 10:1620's
*"No verb reads the terminal"* outside these two holds by construction and every flow is testable
without one.

## HOW `ow install` REACHES THIS

The CLI tree is artefact 3 of the seven, generated from `ACTIONS` and byte-diff gated (G25). When
this module was written there was no `install` or `uninstall` row, so there was no `ow install` to
dispatch it from, and it was not wired by hand: a CLI the generator does not know about is what G25
exists to refuse (D467). W7.5h added both rows -- `mcp_name = None`, 10:53's row 1 (D469) -- the
generated tree gained the two commands, and `__main__` routes them to `run.py`, which calls these.

## `--target`, FOUR WAYS

10:1662-1663: *"`auto` (detected, falling back to `claude-code`), `all`, `none`, or a CSV list -- an
unknown id raises with the known list in the message."* `auto` is every built host whose `detect`
says it is installed at that location, and `claude-code` when none is. An id declared by 10:1632
and not yet built says so rather than calling it unknown (`registry.build`).

## `--check`: 0 CONFIGURED, 9 NOT

10:1780: *"`ow install --check` exits 9 when not configured and 0 when configured"*. Per host,
18:2986's line: `configured` with each receipt row checked against the file as it is now --
the owned part, by its own digest -- or `not configured`, or `not installed`. The exit is 0 when
every resolved host that is installed is configured, and 9 otherwise, including when none is
installed: 18:2987 prints a `codex ... not installed` line and still exits 0, so a host that is not
there is not a host that is unconfigured.

## A PLAN THAT IS NOT CONFIRMED WRITES NOTHING, AND SAYS SO WITH EXIT 1

10:1620-1621: both verbs *"take `--yes`, and both of which print their whole plan first"*. Without
`--yes` the plan is printed and `confirm` asked; a refusal, or no `confirm` at all -- a pipe, CI --
writes nothing and exits 1, *"usage or configuration error"* (10:1484), with the flag named. Exit 0
for a run that did nothing would tell a script the hosts are wired.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave.hooks.session import anchor, sessions_dir
from omniweave.install.hookrules import owned_pairs
from omniweave.install.primitives import decode_text, read_json
from omniweave.install.receipt import (
    expand,
    load,
    owned_array,
    owned_key,
    owned_section,
    receipt_path,
    tildify,
)
from omniweave.install.registry import BUILT, build
from omniweave.install.skilldir import HASH_MISMATCH
from omniweave.install.types import LOCATIONS, TARGET_IDS, InstallOptions
from omniweave.skills.hash import bundle_sha256

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from omniweave.install.engine import HostEnv
    from omniweave.install.receipt import Entry
    from omniweave.install.types import FileAction, HostTarget, Location, WriteResult

__all__ = [
    "NOT_CONFIGURED",
    "OK",
    "USAGE",
    "Outcome",
    "check",
    "install",
    "location_hint",
    "print_config",
    "refresh_targets",
    "resolve_targets",
    "uninstall",
]

# 10:1483-1492.
OK: Final = 0
USAGE: Final = 1
NOT_CONFIGURED: Final = 9

FALLBACK: Final = "claude-code"
"""10:1662: `auto` is *"detected, falling back to `claude-code`"*."""

_IMPERATIVE: Final = {"created": "create", "updated": "update", "removed": "remove"}
_MIDDOT: Final = " · "


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a verb did: its exit code, the lines it prints, and each host's result."""

    exit_code: int
    lines: tuple[str, ...]
    results: tuple[WriteResult, ...] = ()

    def text(self) -> str:
        return "".join(f"{line}\n" for line in self.lines)


# ---------------------------------------------------------------------------------------------
# --target.
# ---------------------------------------------------------------------------------------------


def resolve_targets(spec: str, env: HostEnv, loc: Location) -> tuple[HostTarget, ...]:
    """10:1662's four resolutions. `ValueError`, naming the known ids, for an unknown one."""
    word = spec.strip()
    if word == "none":
        return ()
    if word == "all":
        return tuple(build(one, env) for one in BUILT)
    if word == "auto":
        found = tuple(
            target
            for target in (build(one, env) for one in BUILT)
            if target.supports_location(loc) and target.detect(loc).installed
        )
        return found or (build(FALLBACK, env),)
    ids = [part.strip() for part in word.split(",") if part.strip()]
    if not ids:
        raise ValueError(f"--target is empty; known: {', '.join(TARGET_IDS)}")
    return tuple(build(one, env) for one in dict.fromkeys(ids))


def _resolved(spec: str, env: HostEnv, loc: Location) -> tuple[HostTarget, ...] | Outcome:
    try:
        return resolve_targets(spec, env, loc)
    except ValueError as error:
        return Outcome(USAGE, (f"ow: {error}",))


# ---------------------------------------------------------------------------------------------
# Rendering: 18:2974-2981's plan.
# ---------------------------------------------------------------------------------------------


def _row(action: FileAction, *, planned: bool) -> str:
    verb = _IMPERATIVE.get(action.action, action.action) if planned else action.action
    line = f"  {action.path:<28} {action.mode or '':<15} {action.detail:<39} {verb}"
    return f"{line} -- {action.note}" if action.note else line


def _rendered(results: Sequence[WriteResult], *, planned: bool) -> list[str]:
    lines: list[str] = []
    for result in results:
        if result.refused:
            lines.append(f"  {result.target} {result.location}: refused -- {result.refused}")
            continue
        lines.extend(_row(action, planned=planned) for action in result.actions)
        lines.extend(f"  {note}" for note in result.notes)
    return lines


def _confirmed(yes: bool, confirm: Callable[[str], bool] | None, question: str) -> bool:
    return yes or (confirm is not None and confirm(question))


# ---------------------------------------------------------------------------------------------
# ow install.
# ---------------------------------------------------------------------------------------------


def install(
    spec: str,
    loc: Location,
    opts: InstallOptions,
    env: HostEnv,
    *,
    yes: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> Outcome:
    """Print the plan; unless `--dry-run`, confirm and write it. 18:2973-2983."""
    targets = _resolved(spec, env, loc)
    if isinstance(targets, Outcome):
        return targets
    unsupported = [one.id for one in targets if not one.supports_location(loc)]
    targets = tuple(one for one in targets if one.supports_location(loc))
    planned = tuple(one.install(loc, _dry(opts)) for one in targets)
    lines = [
        "plan (nothing written)" if opts.dry_run else "plan",
        *_rendered(planned, planned=True),
    ]
    lines.extend(f"  {one} {loc}: skipped -- does not support {loc}" for one in unsupported)
    if opts.dry_run:
        return Outcome(OK, tuple(lines), planned)
    if not _confirmed(yes, confirm, "Write this plan?"):
        lines.append("not confirmed; nothing written (pass --yes to write without asking)")
        return Outcome(USAGE, tuple(lines), planned)
    results = tuple(one.install(loc, opts) for one in targets)
    lines.extend(_rendered(results, planned=False))
    written = sum(one.action in {"created", "updated"} for r in results for one in r.actions)
    receipt = tildify(receipt_path(env.omniweave_home), env.user_home)
    lines.append(f"wrote {written} entries · receipt {receipt} (a post-write sha256 per path)")
    failed = any(r.refused or any(one.action == "kept" for one in r.actions) for r in results)
    return Outcome(USAGE if failed else OK, tuple(lines), results)


def _dry(opts: InstallOptions) -> InstallOptions:
    return InstallOptions(opts.hooks, opts.skills, allow_cli=opts.allow_cli, dry_run=True)


def print_config(target: str, loc: Location, env: HostEnv) -> Outcome:
    """`ow install --print-config <id>`: the host's `print_config`, which writes nothing."""
    try:
        host = build(target, env)
    except ValueError as error:
        return Outcome(USAGE, (f"ow: {error}",))
    return Outcome(OK, tuple(host.print_config(loc).rstrip("\n").split("\n")))


# ---------------------------------------------------------------------------------------------
# ow install --check.
# ---------------------------------------------------------------------------------------------


def check(spec: str, loc: Location, env: HostEnv) -> Outcome:
    """18:2985-2989: one line per host, and 0 when every installed host is configured."""
    targets = _resolved(spec, env, loc)
    if isinstance(targets, Outcome):
        return targets
    rows = load(env.omniweave_home, pid=env.pid, release=env.release, back_up=False).receipt
    lines: list[str] = []
    every = True
    for target in targets:
        found = target.detect(loc)
        if not found.installed:
            lines.append(f"{target.id:<11} {loc:<8} not installed")
            continue
        if not found.already_configured:
            every = False
            lines.append(f"{target.id:<11} {loc:<8} not configured")
            continue
        scope = str(env.project_root) if loc == "local" and env.project_root else None
        mine = [one for one in rows.for_scope(loc, scope) if one.target == target.id]
        parts = [_row_status(entry, env) for entry in mine] or ["no receipt rows"]
        lines.append(f"{target.id:<11} {loc:<8} configured    {_MIDDOT.join(parts)}")
    configured = every and any("configured    " in line for line in lines)
    return Outcome(OK if configured else NOT_CONFIGURED, tuple(lines))


def _row_status(entry: Entry, env: HostEnv) -> str:
    """One kind's word on the check line: its owned part, by its own digest, as it is now."""
    path = expand(entry.path, env.user_home)
    if entry.mode == "dir":
        return _dir_status(entry, path)
    if entry.mode == "marker-section":
        return _section_status(entry, path)
    read = read_json(path, pid=env.pid, back_up=False)
    if read.state != "parsed":
        return f"{entry.kind} {read.state}"
    if entry.mode == "json-hook-rules":
        present = {event for event, _ in owned_pairs(read.value)}
        have = sum(event in present for event in entry.events)
        return (
            f"hooks {have}/{len(entry.events)} {'ok' if have == len(entry.events) else 'MISSING'}"
        )
    if entry.mode == "json-array-add":
        ok = owned_array(read.value, entry.key, entry.values) == entry.owned_sha256
        return _said(entry.kind, ok)
    return _said(entry.kind, owned_key(read.value, entry.key) == entry.owned_sha256)


def _dir_status(entry: Entry, path: Path) -> str:
    if not path.is_dir():
        return "skill missing"
    ok = bundle_sha256(path)[0] == entry.bundle_sha256
    return "skill hash ok" if ok else f"skill hash MISMATCH ({HASH_MISMATCH})"


def _section_status(entry: Entry, path: Path) -> str:
    try:
        text = decode_text(path.read_bytes())[0]
    except (OSError, UnicodeDecodeError):
        return f"{entry.kind} missing"
    return _said(entry.kind, owned_section(text) == entry.owned_sha256)


def _said(kind: str, ok: bool) -> str:
    return f"{kind} ok" if ok else f"{kind} MODIFIED"


# ---------------------------------------------------------------------------------------------
# ow uninstall. 10:1749-1773's seven steps.
# ---------------------------------------------------------------------------------------------


def location_hint(spec: str, env: HostEnv) -> str:
    """Step 1's question: *"with the hint text listing the actual directories it will sweep"*."""
    try:
        targets = resolve_targets(spec, env, "global")
    except ValueError as error:
        return f"ow: {error}"
    lines = ["Uninstall from which location?"]
    for loc in LOCATIONS:
        paths = [path for one in targets if one.supports_location(loc)
                 for path in one.describe_paths(loc)]  # fmt: skip
        lines.append(f"  {loc}: {', '.join(paths) if paths else 'nothing'}")
    return "\n".join(lines)


def uninstall(
    spec: str,
    loc: Location,
    env: HostEnv,
    *,
    yes: bool = False,
    confirm: Callable[[str], bool] | None = None,
    keep_cli: bool = False,
) -> Outcome:
    """Steps 2-7: read, plan, confirm, remove, name leftovers, never throw, sweep sessions."""
    targets = _resolved(spec, env, loc)
    if isinstance(targets, Outcome):
        return targets
    lines = ["plan"]
    planned: list[WriteResult] = []
    for target in targets:
        if not target.supports_location(loc):
            lines.append(f"  {target.id} {loc}: skipped -- does not support {loc}")
            continue
        result = target.uninstall(loc, dry_run=True, keep_cli=keep_cli)
        planned.append(result)
        if result.actions and all(one.action == "not-found" for one in result.actions):
            lines.append(f"  {target.id} {loc}: not configured -- nothing to remove")
        else:
            lines.extend(_rendered([result], planned=True))
    sessions = _sessions(env)
    if sessions is not None:
        lines.append(f"  {tildify(sessions, env.user_home):<28} {'sessions':<15} {'':<39} remove")
    if not _confirmed(yes, confirm, "Remove all of this?"):
        lines.append("not confirmed; nothing removed (pass --yes to remove without asking)")
        return Outcome(USAGE, tuple(lines), tuple(planned))
    results = [
        _undone(target, loc, keep_cli) for target in targets if target.supports_location(loc)
    ]
    lines.extend(_rendered(results, planned=False))
    lines.extend(_swept(sessions, env))
    lines.extend(_index_message(env))
    refused = any(one.refused for one in results)
    return Outcome(USAGE if refused else OK, tuple(lines), tuple(results))


def _undone(target: HostTarget, loc: Location, keep_cli: bool) -> WriteResult:
    """The outer of 10:1765's two nested `try/except`s: a host that raises is named, not fatal."""
    try:
        return target.uninstall(loc, keep_cli=keep_cli)
    except Exception as error:  # 10:1765
        from omniweave.install.types import WriteResult  # noqa: PLC0415 -- the failure path only

        return WriteResult(target.id, loc, refused=f"failed: {type(error).__name__}: {error}")


def _sessions(env: HostEnv) -> Path | None:
    root = env.project_root
    if root is None:
        return None
    found = sessions_dir(root)
    return found if found is not None and found.is_dir() else None


def _swept(sessions: Path | None, env: HostEnv) -> list[str]:
    """Step 7: *"uninstall removes it and says so in one line"*."""
    if sessions is None:
        return []
    shown = tildify(sessions, env.user_home)
    shutil.rmtree(sessions, ignore_errors=True)
    if sessions.exists():
        return [f"Could not remove {shown} -- delete it manually"]
    return [f"removed {shown}: session journals and ledger markers, which have no durable value"]


def _index_message(env: HostEnv) -> list[str]:
    """Step 6: the index stays, and the message names the verb that deletes it."""
    root = env.project_root
    project = anchor(root) if root is not None else None
    if project is None or not (project.parent / ".omniweave").is_dir():
        return []
    names = _corpora(project) or ["<name>"]
    return [
        f"The .omniweave/ index for this project is still here. Run 'ow store rm --corpus {name}' "
        "to delete it."
        for name in names
    ]


def _corpora(project: Path) -> list[str]:
    try:
        table = tomllib.loads(project.read_text(encoding="utf-8")).get("corpora", {})
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return []
    return (
        sorted(name for name in table if isinstance(name, str)) if isinstance(table, dict) else []
    )


# ---------------------------------------------------------------------------------------------
# refresh_targets. 10:1656-1658.
# ---------------------------------------------------------------------------------------------


def refresh_targets(env: HostEnv) -> tuple[WriteResult, ...]:
    """Re-run `install()` for already-configured hosts only, re-granting and re-asking nothing.

    10:1656-1657: *"with `allow_cli=False, hooks=None`"*. `InstallOptions` also needs `skills`,
    which 10:1656 does not name: a host with a skill row gets `core` -- the skill it already has,
    refreshed -- and one without gets `none`, so an upgrade never installs a skill nobody asked for.
    """
    rows = load(env.omniweave_home, pid=env.pid, release=env.release, back_up=False).receipt
    results: list[WriteResult] = []
    for loc in LOCATIONS:
        if loc == "local" and env.project_root is None:
            continue
        for target in (build(one, env) for one in BUILT):
            if not target.supports_location(loc) or not target.detect(loc).already_configured:
                continue
            scope = str(env.project_root) if loc == "local" else None
            skilled = any(
                one.target == target.id and one.kind == "skill"
                for one in rows.for_scope(loc, scope)
            )
            opts = InstallOptions(hooks=None, skills="core" if skilled else "none")
            results.append(target.install(loc, opts))
    return tuple(results)
