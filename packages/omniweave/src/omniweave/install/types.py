"""The vocabulary `ow install` speaks: seven hosts, two locations, six file actions, one protocol.

10:1628 makes the claim this module exists to keep true -- *"a new host is one file plus one
registry row"* -- and 10:1630-1643 gives `AgentTarget` verbatim, which is below as written. The
five names that protocol refers to and no document defines (`InstallOptions`, `DetectionResult`,
`WriteResult`, `FileAction` and the `kind`/`mode` vocabulary the receipt rows use) are defined here
from the places they are *used*, and each field says where.

## TWO SPELLINGS OF "NO HOOKS", ONE LINE APART

`ow install --hooks none|context|steer` (10:1427) and `refresh_targets()`'s `hooks=None` (10:1657)
are one keystroke from each other and mean opposite things: `"none"` is *write no hooks* and `None`
is *leave whatever hooks are there alone*. Both are kept, because both are the plan's, and
`InstallOptions.hooks` spells the difference in its type: `HookSet | None`. D447.

**What `context` and `steer` install is written nowhere.** The one place the difference is visible
is 18:2977-2978, whose `--hooks context` plan lists five events and leaves out `PreToolUse` -- the
five-gate scope check, the only handler that can stop something (10 section 8.5). 10:1720's receipt
row lists all six. `HOOK_SETS` reads the two together: `steer` is `context` plus the one hook that
steers. That is a reading, and D447 records it as one.

## WHAT `--hooks` AND `--skills` DEFAULT TO IS ALSO WRITTEN NOWHERE

10:1681 gives `--allow-cli` a default -- *"off by default"* -- and nothing gives one to the other
two; 18:2973 passes both explicitly. So `InstallOptions` requires them. A default here would be a
decision about what an unqualified `ow install` does to a user's hosts, which is the plan's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, get_args

from omniweave.hooks.envelope import EVENTS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "ACTIONS",
    "HOOK_SETS",
    "KINDS",
    "LOCATIONS",
    "MODES",
    "SKILL_SETS",
    "TARGET_IDS",
    "Action",
    "AgentTarget",
    "DetectionResult",
    "FileAction",
    "HookSet",
    "HostTarget",
    "InstallOptions",
    "Kind",
    "Location",
    "Mode",
    "SkillSet",
    "TargetId",
    "WriteResult",
]

# 10:1632, verbatim and in the plan's order.
TargetId = Literal[
    "claude-code", "codex", "cursor", "opencode", "gemini", "copilot-vscode", "agents-md"
]
TARGET_IDS: Final[tuple[TargetId, ...]] = get_args(TargetId)

# 10:1633.
Location = Literal["global", "local"]
LOCATIONS: Final[tuple[Location, ...]] = get_args(Location)

# 10:1645: "FileAction.action in {created, updated, unchanged, removed, not-found, kept}".
Action = Literal["created", "updated", "unchanged", "removed", "not-found", "kept"]
ACTIONS: Final[tuple[Action, ...]] = get_args(Action)

# 10:1665-1671's "kind" column, in the table's order, as the receipt rows spell it (10:1707-1725).
Kind = Literal["mcp", "permissions", "instructions", "hooks", "skill"]
KINDS: Final[tuple[Kind, ...]] = get_args(Kind)

# 10:1665-1671's "mode" column, same order.
Mode = Literal["json-key", "json-array-add", "marker-section", "json-hook-rules", "dir"]
MODES: Final[tuple[Mode, ...]] = get_args(Mode)

# 10:1427's `--hooks none|context|steer` and `--skills core|all|none`.
HookSet = Literal["none", "context", "steer"]
SkillSet = Literal["core", "all", "none"]
SKILL_SETS: Final[tuple[SkillSet, ...]] = get_args(SkillSet)

_STEER: Final = "PreToolUse"

HOOK_SETS: Final[Mapping[HookSet, tuple[str, ...]]] = {
    "none": (),
    # 18:2977-2978: the `--hooks context` dry run lists these five, in EVENTS order.
    "context": tuple(name for name in EVENTS if name != _STEER),
    # 10:1720's receipt row: all six. D447 -- the difference is read, not stated.
    "steer": tuple(EVENTS),
}


@dataclass(frozen=True, slots=True)
class InstallOptions:
    """What `install()` is asked to do. `hooks=None` is `refresh_targets()`'s *leave them alone*.

    10:1656-1657: `refresh_targets()` re-runs `install()` *"with `allow_cli=False, hooks=None`, so
    an upgrade refreshes wording and tool names without re-asking or re-granting anything."* So
    `None` is not `"none"`: `"none"` writes no hook, and `None` does not look at hooks at all.
    `hooks` and `skills` have no default because the plan gives them none (the module docstring).
    """

    hooks: HookSet | None
    skills: SkillSet
    allow_cli: bool = False  # 10:1681, "off by default"
    dry_run: bool = False  # 10:1427's --dry-run; a target given this writes nothing


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """10:1638's comment is the whole specification: *"installed, already_configured"*.

    `installed` is whether the host itself is present; `already_configured` whether omniweave is
    wired into it at that location. `note` says how either was decided, for `--check`'s line.
    """

    installed: bool
    already_configured: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class FileAction:
    """One filesystem effect, reported. 10:1645 and the glossary's `FileAction` row.

    `path` is the path the user would recognise -- what `describe_paths` names and 18:2973 prints --
    and `written` is where the bytes actually went, which differs only when `path` is a symlink:
    `atomic_write` writes through a link rather than replacing it with a regular file (D444).
    `code` is the `OW-*` numeric when the action carries one, `OW-A-032` for a config that was
    backed up because it would not parse. `detail` is what the row is, in 18:2975-2980's third
    column: the key, `key += values`, the events, the marker, or `bundle_hash 4c1f...`.
    """

    path: str
    action: Action
    kind: Kind | None = None
    mode: Mode | None = None
    note: str = ""
    code: str = ""
    written: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What one `install()` or `uninstall()` did to one target at one location.

    `notes` are the lines that are not about a path written: 18:2981's *"Bash(ow:*) NOT written
    (--allow-cli is OFF BY DEFAULT)"* is one, a broken stale lock (`OW-A-033`) another. `refused`
    is set when nothing was attempted -- the lock is held, or the receipt could not be written --
    and then `actions` is empty.
    """

    target: TargetId
    location: Location
    actions: tuple[FileAction, ...] = ()
    notes: tuple[str, ...] = ()
    refused: str = ""

    def changed(self) -> bool:
        """Whether any path was written or removed; `unchanged`, `not-found` and `kept` were not."""
        return any(one.action in {"created", "updated", "removed"} for one in self.actions)


class AgentTarget(Protocol):
    """10:1635-1642, verbatim. A new host implements this and adds one registry row."""

    id: TargetId
    display_name: str
    docs_url: str | None

    def supports_location(self, loc: Location) -> bool: ...
    def detect(self, loc: Location) -> DetectionResult: ...  # installed, already_configured
    def install(self, loc: Location, opts: InstallOptions) -> WriteResult: ...
    def uninstall(self, loc: Location) -> WriteResult: ...  # removes ONLY what install wrote
    def print_config(self, loc: Location) -> str: ...  # MUST NOT touch the filesystem
    def describe_paths(self, loc: Location) -> tuple[str, ...]: ...


class HostTarget(AgentTarget, Protocol):
    """`AgentTarget` with the two uninstall options the verb needs and 10:1640 does not declare.

    10:1760 prints *"the whole plan before touching anything"*, which is an uninstall that writes
    nothing, and 10:1428 gives `ow uninstall` a `--keep-cli`. Both are keyword-only with defaults,
    so a `HostTarget` is still an `AgentTarget` as the plan wrote it. `skills_dir` is where the
    host reads skill bundles from at `loc`: `ow skills install` writes into every one of them that
    exists (10:1393), so a new host's directory is found by its registry row and no list.
    """

    def uninstall(
        self, loc: Location, *, dry_run: bool = False, keep_cli: bool = False
    ) -> WriteResult: ...

    def skills_dir(self, loc: Location) -> Path: ...
