"""The second host: Cursor. The file 10:1628 says a new host is, and the measurement of that claim.

## WHERE THE PATHS COME FROM, SINCE NO DOCUMENT GIVES THEM

10:1665-1671's table has one column pair, claude-code's. 16:719 budgets *"three hosts at v1"* and
names none, and 10:1632 lists seven ids. So nothing in the plan says where Cursor keeps anything
(D474). The paths here are the ones Cursor itself says, read from the skills it ships and manages
on this machine (`~/.cursor/skills-cursor/`), and the MCP file it wrote:

| kind | global | local | Cursor's own word |
|---|---|---|---|
| mcp | `~/.cursor/mcp.json` | `./.cursor/mcp.json` | the file on this machine |
| instructions | none | `./.cursor/rules/omniweave.mdc` | `create-rule`: `.mdc` files |
| skill | `~/.cursor/skills/<name>` | `./.cursor/skills/<name>` | `create-skill`'s table |

Claude Code's skill row is `~/.agents/skills` (10:1671). Cursor's own guide names
`~/.cursor/skills` and nothing else, so that is where this writes. With both hosts installed the
bundle is in two places, each recorded by its own row.

## THE ENTRY HAS NO `type`

10:1675's entry is `{"type":"stdio", ...}`. Of the seven servers in this machine's
`~/.cursor/mcp.json`, four are stdio and none carries `type`; they are `command`, `args` and,
for two, `env`. The entry here is 10:1675's without the key the host does not write (D475).

## TWO KINDS ARE NOT WRITTEN, AND THE PLAN SAYS WHY

**Permissions.** 10:1674's wildcard is Claude Code's grammar. Cursor's editor asks per tool and
keeps the answer in its own settings; the one file-backed allowlist is the Cursor *CLI*'s
`~/.cursor/cli-config.json`, whose `permissions` block `update-cli-config` calls *required* and
whose MCP grammar is `Mcp(server, tool)`. Writing a CLI's config to grant an editor nothing is not
the grant 10:1674 means, so nothing is written and the plan says so (D478).

**Hooks.** `create-hook`: Cursor reads `hooks.json` with `"version": 1`, camelCase events
(`sessionStart`, `beforeSubmitPrompt`, `preCompact`, ...) and its own stdin and stdout fields.
`ow hook <event>` speaks Claude Code's envelope (W7.4). A Cursor hook running it would get a
payload it does not parse and exit 0 in silence -- every failure path is a silent exit 0 by
design (10:1843-1844) -- which is G26's breach with no symptom, installed on purpose. So `--hooks`
other than `none` is not written for Cursor, and the plan says so (D478).

## THE RULE MUST OPEN WITH ITS FRONTMATTER

`create-rule`: a rule is read with YAML frontmatter, and `alwaysApply: true` is what makes it
apply to every session. The marker block's first line is an HTML comment, so a file that *began*
with the block would be a rule without frontmatter -- applied only when asked for. The step gives
the file it creates a `head` (D477), the three lines below, and uninstall deletes a file it
created when that head is all that is left. Global instructions have no file to write: Cursor's
own guide names project rules only, so the global plan says so.

## THE LAST LINE OF THE BLOCK IS CLAUDE CODE'S

`instruction_block()` ends *"Their host-side names start `mcp__omniweave__`"*, which is how Claude
Code spells an MCP tool. Nothing measured says how Cursor spells one to its model, so the line is
left out here rather than written wrong (D476).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave.install.engine import (
    CORE_SKILL,
    HostEnv,
    Step,
    configured,
    install,
    instruction_block,
    render_step,
    scope_of,
    serve_note,
    skill_names,
    skill_step,
    uninstall,
)
from omniweave.install.modes import Site
from omniweave.install.types import LOCATIONS, DetectionResult

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave.install.types import InstallOptions, Location, SkillSet, TargetId, WriteResult

__all__ = ["MCP_KEY", "RULE_HEAD", "Cursor", "mcp_entry"]

MCP_KEY: Final = "mcpServers.omniweave"
"""The same key as claude-code's (10:1667): the top-level `mcpServers` this machine's file has."""

RULE_HEAD: Final = "---\nalwaysApply: true\n---"
"""`create-rule`'s *"Always Apply"* frontmatter, alone: no document writes a `description`."""

_SERVE: Final = ("serve", "--mcp")

_NO_PERMISSIONS: Final = (
    "permissions NOT written: Cursor's editor asks per tool and keeps the answer in its own "
    "settings, so no file grants mcp__omniweave__* or Bash(ow:*) (D478)"
)
_NO_HOOKS: Final = (
    "hooks NOT written: Cursor's hooks.json v1 is not the envelope `ow hook` speaks, and a hook "
    "that cannot parse its payload exits 0 in silence (D478)"
)
_NO_GLOBAL_RULE: Final = (
    "instructions NOT written at global: Cursor names project rules only (.cursor/rules/); "
    "--location local writes one"
)


@dataclass(frozen=True, slots=True)
class Paths:
    """The MCP file, the rule file where there is one, and the skills directory."""

    mcp: Path
    rule: Path | None
    skills: Path


def mcp_entry(launch: tuple[str, ...], *, windows: bool) -> dict[str, Any]:
    """10:1675's entry without `type`, which Cursor's own entries do not carry. D475."""
    head = launch[0].replace("\\", "/") if windows else launch[0]
    return {"command": head, "args": [*launch[1:], *_SERVE], "env": {}}


class Cursor:
    """`AgentTarget` for Cursor, at both locations: the MCP entry, the project rule, the skills."""

    id: TargetId = "cursor"
    display_name: str = "Cursor"
    docs_url: str | None = None

    def __init__(self, env: HostEnv) -> None:
        self.env = env

    def supports_location(self, loc: Location) -> bool:
        return loc in LOCATIONS

    def paths(self, loc: Location) -> Paths:
        home = self.env.user_home
        if loc == "global":
            base = home / ".cursor"
            return Paths(base / "mcp.json", None, base / "skills")
        base = (self.env.project_root or home) / ".cursor"
        return Paths(base / "mcp.json", base / "rules" / "omniweave.mdc", base / "skills")

    def skills_dir(self, loc: Location) -> Path:
        return self.paths(loc).skills

    def skill_names(self, skills: SkillSet) -> tuple[str, ...]:
        return skill_names(self.env, skills)

    def steps(
        self, loc: Location, opts: InstallOptions | None, *, check: bool = True
    ) -> tuple[Step, ...]:
        """mcp, the rule (local only), the skills: claude-code's order without its two absent rows.

        `opts=None` is uninstall's list, with what re-derivation needs when a row is missing.
        """
        where = self.paths(loc)
        rule = (
            ()
            if where.rule is None
            else (
                Step(
                    "instructions", "marker-section", where.rule,
                    body=instruction_block(None), head=RULE_HEAD,
                ),
            )
        )  # fmt: skip
        if opts is None:
            return (
                Step("mcp", "json-key", where.mcp, key=MCP_KEY),
                *rule,
                skill_step(self.env, where.skills, CORE_SKILL, check=False),
            )
        launch = self.env.launch
        if isinstance(launch, str):
            mcp = Step("mcp", "json-key", where.mcp, key=MCP_KEY, refusal=launch)
        else:
            entry = mcp_entry(launch, windows=self.env.windows)
            mcp = Step("mcp", "json-key", where.mcp, key=MCP_KEY, value=entry, note=serve_note())
        skills = tuple(
            skill_step(self.env, where.skills, name, check=check)
            for name in self.skill_names(opts.skills)
        )
        return (mcp, *rule, *skills)

    def _notes(self, loc: Location, opts: InstallOptions) -> tuple[str, ...]:
        notes = [_NO_PERMISSIONS]
        if opts.hooks not in {None, "none"}:
            notes.append(_NO_HOOKS)
        if self.paths(loc).rule is None:
            notes.append(_NO_GLOBAL_RULE)
        return tuple(notes)

    def _shown(self, loc: Location, path: Path) -> str:
        scope, _ = scope_of(self.env, loc)
        return Site(self.id, loc, path, self.env.user_home, scope_root=scope).shown

    def detect(self, loc: Location) -> DetectionResult:
        """Installed: `~/.cursor` exists or `cursor` is on PATH. Reads only."""
        home = self.env.user_home
        found = [
            name
            for name, present in (
                ("~/.cursor", (home / ".cursor").is_dir()),
                ("cursor on PATH", self.env.which("cursor") is not None),
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
            dry_run=opts.dry_run, notes=self._notes(loc, opts),
        )  # fmt: skip

    def uninstall(
        self, loc: Location, *, dry_run: bool = False, keep_cli: bool = False
    ) -> WriteResult:
        """Everything this target's rows name at `loc`. `keep_cli` has nothing to keep here."""
        del keep_cli  # no `Bash(ow:*)` is ever written for Cursor (D478)
        return uninstall(self.id, loc, self.steps(loc, None), self.env, dry_run=dry_run)

    def print_config(self, loc: Location) -> str:
        """What `--skills core` writes, rendered, and what is not. Touches no file (10:1641)."""
        from omniweave.install.types import InstallOptions  # noqa: PLC0415 -- a runtime value

        opts = InstallOptions(hooks="steer", skills="core", allow_cli=True)
        steps = self.steps(loc, opts, check=False)
        blocks = [render_step(step, self._shown(loc, step.path)) for step in steps]
        blocks.extend(f"# {note}" for note in self._notes(loc, opts))
        return "\n\n".join(blocks) + "\n"

    def describe_paths(self, loc: Location) -> tuple[str, ...]:
        """Every path install may write at `loc`, as rows and plans spell them. G-install's list."""
        where = self.paths(loc)
        skills = tuple(where.skills / name for name in self.skill_names("all"))
        paths = (where.mcp, *((where.rule,) if where.rule is not None else ()), *skills)
        return tuple(self._shown(loc, path) for path in paths)
