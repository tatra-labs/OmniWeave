"""The third host: Codex. TOML, a shared skill directory, and the one host whose hooks speak ours.

## WHERE THE PATHS COME FROM

10:1665-1671 gives Claude Code's paths and no other host's (D474). Codex's are from its own manual,
the one its shipped `openai-docs` skill names (`developers.openai.com/codex/codex-manual.md`,
which answers with a 308 to `learn.chatgpt.com/docs/codex-manual.md`), and from the skills it
ships under `~/.codex/skills/.system/`. `$CODEX_HOME` defaults to `~/.codex` (`skill-installer`,
and the manual's AGENTS.md section):

| kind | global | local | the manual |
|---|---|---|---|
| mcp | `$CODEX_HOME/config.toml` | `./.codex/config.toml` | `[mcp_servers.<name>]` |
| instructions | `$CODEX_HOME/AGENTS.md` | `./AGENTS.md` | global, then root down |
| hooks | `$CODEX_HOME/hooks.json` | `./.codex/hooks.json` | *"most useful locations"* |
| skill | `~/.agents/skills/<name>` | `./.agents/skills/<name>` | `USER` and `REPO` rows |

A project's `.codex/` is read only when Codex trusts the project, and every local plan says so.

## THE MCP ENTRY IS A TOML TABLE, WRITTEN AS TEXT

`config.toml` is TOML, and nothing here writes TOML back byte for byte: the standard library
reads it and does not write it. So the entry is a marked section -- the same mode as the
instructions, with `# omniweave:begin` / `# omniweave:end`, because a TOML comment starts `#`
(D480). A table appended at the end of the file is valid wherever the file's last table ends,
and the insert and its removal are text, so byte identity is D446's argument over again.

What text cannot see, TOML can. The step's `validate` parses the whole file the write would leave
and checks `mcp_servers.omniweave` is exactly the entry: a user's own `[mcp_servers.omniweave]`
elsewhere, or `mcp_servers` as an inline table, is a file that would not parse, and it is `kept`
with the parser's own reason.

## HOOKS: THE SAME ENVELOPE, ONE MATCHER THAT CANNOT FIRE, AND A TRUST STEP

The manual's hooks are Claude Code's: `hooks.json` holds `{"hooks": {<Event>: [matcher groups]}}`
with the same PascalCase events, the same stdin fields (`session_id`, `transcript_path`, `cwd`,
`hook_event_name`, `prompt`, `source`, `trigger`), and the same `hookSpecificOutput` with
`additionalContext` or `permissionDecision: "deny"` -- the only shapes `ow hook` emits
(`hooks.envelope.emission`). So `json-hook-rules` writes `hooks.json` unchanged, and the payloads
the manual prints were run through `ow hook` before this was written (D482).

Two of the six cannot do their work there, so neither is written, and the plan says why (D482):

- `PreToolUse`'s matcher is `Read|Grep|Glob` (10:1849). Codex has no tool by those names -- its
  shell is `Bash`, its edits `apply_patch` -- so the rule could never fire.
- `PostToolUse` fires on `apply_patch` (its `Edit|Write` aliases), but the edit arrives as patch
  text in `tool_input.command`, and the handler reads a file path (`posttool._PATH_FIELDS`).
  Measured: Codex's documented payload counts `noop-no-path` where Claude Code's counts an edit.

So both `context` and `steer` write `SessionStart`, `PreCompact`, `UserPromptSubmit` and
`SessionEnd`. And Codex runs a new or changed hook only after the user trusts it in `/hooks`, so
every plan with hooks says that too.

## ONE SKILL DIRECTORY, TWO HOSTS

The manual's skill locations are `$HOME/.agents/skills` and `.agents/skills`, which are 10:1671's
Claude Code rows exactly. Two hosts' rows name one directory; the engine keeps it for whichever
is still installed (D481).

## WHAT IS NOT WRITTEN

**Permissions.** A server's approval is `default_tools_approval_mode` inside its own table,
`auto | prompt | writes | approve`; the manual says `writes` *"prompts for tools that aren't
marked read-only"* and does not say what `auto` or `approve` do. 10:1674's grant is *never prompt
for omniweave's tools*, and which value is that is not stated, so none is written (D482).
`--allow-cli` has no Codex counterpart here either.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave.gen.instructions import TOOL_PREFIX
from omniweave.install.engine import (
    CORE_SKILL,
    HostEnv,
    Step,
    install,
    instruction_block,
    render_step,
    scope_of,
    serve_note,
    skill_names,
    skill_step,
    uninstall,
)
from omniweave.install.hookrules import desired
from omniweave.install.modes import Site
from omniweave.install.primitives import HASH, decode_text
from omniweave.install.types import HOOK_SETS, LOCATIONS, DetectionResult

if TYPE_CHECKING:
    from omniweave.install.types import InstallOptions, Location, SkillSet, TargetId, WriteResult

__all__ = ["CODEX_HOME", "SERVER", "Codex", "mcp_entry", "mcp_table"]

CODEX_HOME: Final = "CODEX_HOME"
"""The variable Codex names its home by; `~/.codex` when it is unset."""

SERVER: Final = "omniweave"
"""The `[mcp_servers.<name>]` this writes, 10:1667's `mcpServers.omniweave` in Codex's spelling."""

_SERVE: Final = ("serve", "--mcp")
_UNREACHABLE: Final = frozenset({"PreToolUse", "PostToolUse"})

_NO_PERMISSIONS: Final = (
    "permissions NOT written: Codex's default_tools_approval_mode has four values and the manual "
    "does not say which is mcp__omniweave__*'s never-prompt grant; nor has Bash(ow:*) a "
    "counterpart (D482)"
)
_NO_STEER: Final = (
    "PreToolUse NOT written: its matcher is Read|Grep|Glob and Codex has no tool by those names, "
    "so the rule could never fire (D482)"
)
_NO_POSTTOOL: Final = (
    "PostToolUse NOT written: Codex sends an edit as apply_patch text with no file path, so the "
    "handler would record nothing (D482)"
)
_TRUST: Final = "Codex runs a new or changed hook only after it is trusted in /hooks"
_TRUSTED_PROJECT: Final = (
    "Codex reads ./.codex/ (the MCP entry and the hooks) only in a project it trusts"
)


@dataclass(frozen=True, slots=True)
class Paths:
    config: Path
    instructions: Path
    hooks: Path
    skills: Path


def mcp_entry(launch: tuple[str, ...], *, windows: bool) -> dict[str, Any]:
    """10:1675's entry as Codex keys it: `command`, `args`, `env`, and no `type`."""
    head = launch[0].replace("\\", "/") if windows else launch[0]
    return {"command": head, "args": [*launch[1:], *_SERVE], "env": {}}


def _toml_string(value: str) -> str:
    """A TOML basic string. JSON's escapes are a subset of TOML's, `\\uXXXX` included."""
    return json.dumps(value, ensure_ascii=False)


def mcp_table(entry: dict[str, Any]) -> str:
    """The `[mcp_servers.omniweave]` table for `entry`, as the marked section's body."""
    args = ", ".join(_toml_string(one) for one in entry["args"])
    return "\n".join((
        f"[mcp_servers.{SERVER}]",
        f"command = {_toml_string(entry['command'])}",
        f"args = [{args}]",
        "env = {}",
    ))  # fmt: skip


def _validator(entry: dict[str, Any]) -> Any:
    def validate(text: str) -> str:
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            return f"the file would not be valid TOML with this table in it ({error}); not writing"
        servers = document.get("mcp_servers")
        found = servers.get(SERVER) if isinstance(servers, dict) else None
        if found != entry:
            return f"mcp_servers.{SERVER} would not be this entry after the write; not writing"
        return ""

    return validate


def _configured(path: Path) -> bool:
    """Whether `path` parses and has `mcp_servers.omniweave`. Reads only."""
    try:
        document = tomllib.loads(decode_text(path.read_bytes())[0])
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    servers = document.get("mcp_servers")
    return isinstance(servers, dict) and SERVER in servers


class Codex:
    """`AgentTarget` for Codex, at both locations: the MCP table, AGENTS.md, the hooks, skills."""

    id: TargetId = "codex"
    display_name: str = "Codex"
    docs_url: str | None = None

    def __init__(self, env: HostEnv) -> None:
        self.env = env

    def supports_location(self, loc: Location) -> bool:
        return loc in LOCATIONS

    def home(self) -> Path:
        """`$CODEX_HOME`, or `~/.codex`."""
        named = self.env.environ.get(CODEX_HOME)
        return Path(named) if named else self.env.user_home / ".codex"

    def paths(self, loc: Location) -> Paths:
        if loc == "global":
            home = self.home()
            skills = self.env.user_home / ".agents" / "skills"
            return Paths(home / "config.toml", home / "AGENTS.md", home / "hooks.json", skills)
        root = self.env.project_root or self.env.user_home
        base = root / ".codex"
        return Paths(base / "config.toml", root / "AGENTS.md", base / "hooks.json",
                     root / ".agents" / "skills")  # fmt: skip

    def skill_names(self, skills: SkillSet) -> tuple[str, ...]:
        return skill_names(self.env, skills)

    def _mcp_step(self, path: Path) -> Step:
        launch = self.env.launch
        if isinstance(launch, str):
            return Step("mcp", "marker-section", path, refusal=launch, markers=HASH)
        entry = mcp_entry(launch, windows=self.env.windows)
        return Step(
            "mcp", "marker-section", path,
            body=mcp_table(entry), markers=HASH, validate=_validator(entry), note=serve_note(),
        )  # fmt: skip

    def _hooks_step(self, path: Path, opts: InstallOptions) -> Step | None:
        if opts.hooks is None:
            return None
        events = tuple(one for one in HOOK_SETS[opts.hooks] if one not in _UNREACHABLE)
        launch = self.env.launch
        if isinstance(launch, str) and events:
            return Step("hooks", "json-hook-rules", path, refusal=launch)
        wanted = desired(events, launch, windows=self.env.windows) if events else ()
        return Step("hooks", "json-hook-rules", path, hooks=wanted)

    def steps(
        self, loc: Location, opts: InstallOptions | None, *, check: bool = True
    ) -> tuple[Step, ...]:
        """10:1665's order: mcp, instructions, hooks, skills. `opts=None` is uninstall's list."""
        where = self.paths(loc)
        rule = Step(
            "instructions", "marker-section", where.instructions,
            body=instruction_block(TOOL_PREFIX),
        )  # fmt: skip
        if opts is None:
            return (
                Step("mcp", "marker-section", where.config, markers=HASH),
                rule,
                Step("hooks", "json-hook-rules", where.hooks),
                skill_step(self.env, where.skills, CORE_SKILL, check=False),
            )
        hooks = self._hooks_step(where.hooks, opts)
        skills = tuple(
            skill_step(self.env, where.skills, name, check=check)
            for name in self.skill_names(opts.skills)
        )
        return (self._mcp_step(where.config), rule, *((hooks,) if hooks else ()), *skills)

    def _notes(self, loc: Location, opts: InstallOptions) -> tuple[str, ...]:
        notes = [_NO_PERMISSIONS]
        if opts.hooks == "steer":
            notes.append(_NO_STEER)
        if opts.hooks not in {None, "none"}:
            notes.extend((_NO_POSTTOOL, _TRUST))
        if loc == "local":
            notes.append(_TRUSTED_PROJECT)
        return tuple(notes)

    def _shown(self, loc: Location, path: Path) -> str:
        scope, _ = scope_of(self.env, loc)
        return Site(self.id, loc, path, self.env.user_home, scope_root=scope).shown

    def detect(self, loc: Location) -> DetectionResult:
        """Installed: `$CODEX_HOME` exists or `codex` is on PATH. Reads only."""
        home = self.home()
        found = [
            name
            for name, present in (
                (self._shown("global", home), home.is_dir()),
                ("codex on PATH", self.env.which("codex") is not None),
            )
            if present
        ]
        config = self.paths(loc).config
        done = _configured(config)
        table = f"mcp_servers.{SERVER}"
        note = f"{'found ' + ', '.join(found) if found else 'not found'}; " + (
            f"{table} is in {self._shown(loc, config)}" if done else f"no {table}"
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
        del keep_cli  # no `Bash(ow:*)` is ever written for Codex (D482)
        return uninstall(self.id, loc, self.steps(loc, None), self.env, dry_run=dry_run)

    def print_config(self, loc: Location) -> str:
        """`--hooks steer --skills core`, rendered, and what is not written. Touches no file."""
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
        paths = (where.config, where.instructions, where.hooks, *skills)
        return tuple(self._shown(loc, path) for path in paths)
