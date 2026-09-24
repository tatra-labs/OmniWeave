"""The first host: Claude Code. 10:1665-1671's table, as `Step`s for `engine.py` to run.

This file is what 10:1628 means by *"one file"*: the paths per location, the steps in the table's
order, and how the host is detected. Everything else -- the lock, the receipt, the order of
undoing, the dry run -- is the engine's, and is the same for the next host.

## THE ORDER IS THE TABLE'S

10:1665-1671 lists mcp, permissions, instructions, hooks, skill, and 10:1705-1726's receipt rows
come in that order. 18:2975-2980's dry run prints hooks before instructions. The table and the
receipt are the specification and the transcript a rendering of it, so the steps follow the table;
the one order that matters -- permissions before hooks, both in `settings.json` -- is the same in
all three.

## WHAT THE MCP ENTRY RUNS, AND THAT IT DOES NOT RUN YET

10:1675's entry is `{"type":"stdio","command":"<ABS>/ow","args":["serve","--mcp"],"env":{}}`. With
no `ow` to resolve (D456) the launcher is the interpreter, so the entry is `<python> -m omniweave
serve --mcp`, forward-slashed on Windows as 18:3037 says of the entry. It is not quoted: the host
spawns it as an argv, not through a shell, so the space and the parentheses in this machine's
interpreter path are the path's and nothing else's (a conform test spawns it exactly so).

**And it exits 70.** `python -m omniweave` dispatches `hook` and nothing else (D433), so the host
would start a server that refuses at once with *"'serve' is not dispatched by this build"*. The
entry is still written, in the plan's shape: it is what a user needs the day `serve` is wired, and
refusing to install it would leave the other four steps pointing at a server that was never
registered. The action says so, from `DISPATCHED` itself, so the note goes away when `serve` joins
it. D460.

## `Bash(ow:*)` PERMITS A COMMAND THAT IS NOT ON PATH

10:1681: `--allow-cli` writes `Bash(ow:*)`, off by default. It grants the agent `ow ...` in its
shell, which is how the skills reach omniweave (10:102-103: *"The skills shell out to `ow`"*).
With no console script there is no `ow` for that grant to reach, so an install that writes it says
so rather than implying the agent can now run the CLI. D456's consequence, noted, not coined.

## THE SKILL: THE MODE IS HERE, THE BUNDLE IS W7.6'S

10:1671's fifth row is the `dir` mode (`skilldir.py`), recorded by its `sha256-bundle-1` digest
(10:2805). `--skills core` copies `<skills_root>/omniweave`; `--skills all` adds every other bundle
under `skills_root` that has a `SKILL.md`, each to its own `skills/<name>` beside the core one.
`--skills none` writes no skill and removes none -- unlike `--hooks none`, whose hooks live inside a
file omniweave shares and are converged to empty (W7.5d): a skill directory is a whole artefact, and
the verb that takes it away is `ow uninstall` or `ow skills remove` (16:720).

A bundle without a `SKILL.md` is refused by name. That is this repository today:
`skills/omniweave/` holds `references/actions.md` and no router body, which W7.6 generates (16:720).
So on this machine `--skills core` reports the skill `kept` and writes the other four steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave.install.engine import (
    HostEnv,
    Step,
    configured,
    install,
    instruction_block,
    render_step,
    scope_of,
    uninstall,
)
from omniweave.install.hookrules import desired
from omniweave.install.modes import Site
from omniweave.install.types import HOOK_SETS, LOCATIONS, DetectionResult

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave.install.types import (
        InstallOptions,
        Location,
        SkillSet,
        TargetId,
        WriteResult,
    )

__all__ = [
    "ALLOW_CLI",
    "BUNDLE_ENTRY",
    "CORE_SKILL",
    "MCP_KEY",
    "WILDCARD",
    "ClaudeCode",
    "mcp_entry",
]

MCP_KEY: Final = "mcpServers.omniweave"
"""10:1667."""

ALLOW_KEY: Final = "permissions.allow"
"""10:1676's `{"permissions":{"allow":[...]}}`."""

WILDCARD: Final = "mcp__omniweave__*"
"""10:1674-1676, *"the ONE permission wildcard"*."""

ALLOW_CLI: Final = "Bash(ow:*)"
"""10:1681, written only under `--allow-cli`."""

CORE_SKILL: Final = "omniweave"
"""10:1151: *"THE ONLY ALWAYS-RESIDENT SKILL"*."""

BUNDLE_ENTRY: Final = "SKILL.md"
"""The file that makes a directory a skill bundle (10:1152)."""

_SERVE: Final = ("serve", "--mcp")
_SERVE_ROOT: Final = "serve"


@dataclass(frozen=True, slots=True)
class Paths:
    """The four files and the one directory 10:1667-1671 name for one location."""

    mcp: Path
    settings: Path
    instructions: Path
    skill: Path


def mcp_entry(launch: tuple[str, ...], *, windows: bool) -> dict[str, Any]:
    """10:1675's entry for `launch`: forward-slashed on Windows, never quoted. D460."""
    head = launch[0].replace("\\", "/") if windows else launch[0]
    return {"type": "stdio", "command": head, "args": [*launch[1:], *_SERVE], "env": {}}


def _serve_note() -> str:
    from omniweave.__main__ import DISPATCHED  # noqa: PLC0415 -- the dispatcher, read live

    if _SERVE_ROOT in DISPATCHED:
        return ""
    return (
        "the host will start `serve --mcp`, which this build does not dispatch: it exits 70 "
        "until it does (D460)"
    )


class ClaudeCode:
    """`AgentTarget` for Claude Code, at both locations. 10:1665-1671."""

    id: TargetId = "claude-code"
    display_name: str = "Claude Code"
    #  None rather than a guess: no document gives the URL, and a wrong one is a dead link in help.
    docs_url: str | None = None

    def __init__(self, env: HostEnv) -> None:
        self.env = env

    def supports_location(self, loc: Location) -> bool:
        return loc in LOCATIONS

    def skills_dir(self, loc: Location) -> Path:
        """`<home or root>/.agents/skills`, the directory 10:1671's skill rows live in."""
        base = (
            self.env.user_home if loc == "global" else self.env.project_root or self.env.user_home
        )
        return base / ".agents" / "skills"

    def skill_names(self, skills: SkillSet) -> tuple[str, ...]:
        """`core` is the router alone (10:1151); `all` adds every bundle with a `SKILL.md`."""
        if skills == "none":
            return ()
        root = self.env.skills_root
        if skills == "core" or root is None or not root.is_dir():
            return (CORE_SKILL,)
        others = sorted(
            one.name
            for one in root.iterdir()
            if one.name != CORE_SKILL and (one / BUNDLE_ENTRY).is_file()
        )
        return (CORE_SKILL, *others)

    def _skill_step(self, loc: Location, name: str, *, check: bool) -> Step:
        path = self.skills_dir(loc) / name
        root = self.env.skills_root
        source = root / name if root is not None else None
        refusal = ""
        if check and source is None:
            refusal = "no skill bundle source was given"
        elif check and source is not None and not (source / BUNDLE_ENTRY).is_file():
            refusal = (
                f"{source.as_posix()} has no {BUNDLE_ENTRY}: the router body is W7.6's (16:720)"
            )
        return Step("skill", "dir", path, source=source, refusal=refusal)

    def paths(self, loc: Location) -> Paths:
        """10:1667-1671: the global column under the user's home, the local one under the root."""
        home = self.env.user_home
        if loc == "global":
            base = home / ".claude"
            return Paths(home / ".claude.json", base / "settings.json", base / "CLAUDE.md",
                         home / ".agents" / "skills" / "omniweave")  # fmt: skip
        root = self.env.project_root or home
        base = root / ".claude"
        return Paths(root / ".mcp.json", base / "settings.json", base / "CLAUDE.md",
                     root / ".agents" / "skills" / "omniweave")  # fmt: skip

    def steps(
        self, loc: Location, opts: InstallOptions | None, *, check: bool = True
    ) -> tuple[Step, ...]:
        """What install writes, in 10:1665's order.

        `opts=None` is uninstall's list: every kind, with what re-derivation needs when a row is
        missing (10:1758). Re-derivation removes the wildcard and not `Bash(ow:*)`: without a row
        nothing says the CLI grant was ours rather than the user's.
        """
        where = self.paths(loc)
        if opts is None:
            return (
                Step("mcp", "json-key", where.mcp, key=MCP_KEY),
                Step("permissions", "json-array-add", where.settings, key=ALLOW_KEY,
                     values=(WILDCARD,)),
                Step("instructions", "marker-section", where.instructions),
                Step("hooks", "json-hook-rules", where.settings),
                self._skill_step(loc, CORE_SKILL, check=False),
            )  # fmt: skip
        launch = self.env.launch
        windows = self.env.windows
        grants = (WILDCARD, ALLOW_CLI) if opts.allow_cli else (WILDCARD,)
        if isinstance(launch, str):
            mcp = Step("mcp", "json-key", where.mcp, key=MCP_KEY, refusal=launch)
        else:
            entry = mcp_entry(launch, windows=windows)
            mcp = Step("mcp", "json-key", where.mcp, key=MCP_KEY, value=entry, note=_serve_note())
        steps = [
            mcp,
            Step("permissions", "json-array-add", where.settings, key=ALLOW_KEY, values=grants),
            Step("instructions", "marker-section", where.instructions, body=instruction_block()),
        ]
        if opts.hooks is not None:
            events = HOOK_SETS[opts.hooks]
            if isinstance(launch, str) and events:
                hooks = Step("hooks", "json-hook-rules", where.settings, refusal=launch)
            else:
                wanted = desired(events, launch, windows=windows) if events else ()
                hooks = Step("hooks", "json-hook-rules", where.settings, hooks=wanted)
            steps.append(hooks)
        steps.extend(
            self._skill_step(loc, name, check=check) for name in self.skill_names(opts.skills)
        )
        return tuple(steps)

    def _notes(self, opts: InstallOptions) -> tuple[str, ...]:
        notes: list[str] = []
        if not opts.allow_cli:
            notes.append(f"{ALLOW_CLI} NOT written (--allow-cli is OFF BY DEFAULT)")
        elif not (isinstance(self.env.launch, tuple) and len(self.env.launch) == 1):
            notes.append(
                f"{ALLOW_CLI} written, but there is no `ow` on PATH for it to permit (D456)"
            )
        return tuple(notes)

    def _shown(self, loc: Location, path: Path) -> str:
        scope, _ = scope_of(self.env, loc)
        return Site(self.id, loc, path, self.env.user_home, scope_root=scope).shown

    def detect(self, loc: Location) -> DetectionResult:
        """Installed: `~/.claude` or `~/.claude.json` exists, or `claude` is on PATH. Reads only."""
        home = self.env.user_home
        found = [
            name
            for name, present in (
                ("~/.claude", (home / ".claude").is_dir()),
                ("~/.claude.json", (home / ".claude.json").is_file()),
                ("claude on PATH", self.env.which("claude") is not None),
            )
            if present
        ]
        mcp = self.paths(loc).mcp
        done = configured(mcp, MCP_KEY, pid=self.env.pid)
        note = f"{'found ' + ', '.join(found) if found else 'not found'}; " + (
            f"{MCP_KEY} is in {self._shown(loc, mcp)}" if done else f"no {MCP_KEY}"
        )
        return DetectionResult(installed=bool(found), already_configured=done, note=note)

    def install(self, loc: Location, opts: InstallOptions) -> WriteResult:
        return install(
            self.id, loc, self.steps(loc, opts), self.env,
            dry_run=opts.dry_run, notes=self._notes(opts),
        )  # fmt: skip

    def uninstall(
        self, loc: Location, *, dry_run: bool = False, keep_cli: bool = False
    ) -> WriteResult:
        """Everything this target's rows name at `loc`, and by re-derivation what they do not.

        `keep_cli` is 10:1428's `--keep-cli`: `Bash(ow:*)` stays granted when the rest goes.
        """
        keep = frozenset({ALLOW_CLI}) if keep_cli else frozenset()
        steps = self.steps(loc, None)
        return uninstall(self.id, loc, steps, self.env, dry_run=dry_run, keep=keep)

    def print_config(self, loc: Location) -> str:
        """`--hooks steer --skills core --allow-cli`, rendered. Touches no file (10:1641)."""
        from omniweave.install.types import InstallOptions  # noqa: PLC0415 -- a runtime value

        opts = InstallOptions(hooks="steer", skills="core", allow_cli=True)
        steps = self.steps(loc, opts, check=False)
        blocks = [render_step(step, self._shown(loc, step.path)) for step in steps]
        return "\n\n".join(blocks) + "\n"

    def describe_paths(self, loc: Location) -> tuple[str, ...]:
        """Every path install may write at `loc`, as rows and plans spell them. G-install's list."""
        where = self.paths(loc)
        skills = tuple(self.skills_dir(loc) / name for name in self.skill_names("all"))
        paths = (where.mcp, where.settings, where.instructions, *skills)
        return tuple(self._shown(loc, path) for path in paths)
