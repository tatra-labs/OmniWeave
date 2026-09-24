"""The third host, Codex: a TOML table written as text, and one skill directory for two hosts.

**The sharpest test is `test_uninstalling_claude_code_first_leaves_codex_its_skill`.** Codex reads
Claude Code's skill directory (`~/.agents/skills`), so the second install finds the first one's
tree. Without D481 the first uninstall takes the skill from the host still wired to it. The second
is `test_a_users_own_omniweave_table_is_refused_with_the_parsers_reason`: text cannot see a
duplicate TOML table, and the step's `validate` must.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.gen.instructions import TOOL_PREFIX
from omniweave.install import verbs
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.codex import SERVER, Codex, mcp_entry, mcp_table
from omniweave.install.engine import HostEnv, instruction_block
from omniweave.install.hookrules import owned_pairs
from omniweave.install.primitives import HASH, HTML, markers_for, section_span
from omniweave.install.receipt import load
from omniweave.install.registry import TARGETS, build
from omniweave.install.types import InstallOptions

if TYPE_CHECKING:
    from omniweave.install.types import AgentTarget, HookSet, WriteResult

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
LAUNCH = ("C:\\Program Files (x86)\\Python\\python.exe", "-m", "omniweave")
REAL = Path.home()
ROUTER = "---\nname: omniweave\n---\nthe router\n"
USER_TOML = 'model = "gpt-5"\npersonality = "pragmatic"\n\n[profiles.fast]\nmodel = "mini"\n'
FOUR = ["SessionStart", "PreCompact", "UserPromptSubmit", "SessionEnd"]


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


def _env(tmp: Path, *, root: Path | None = None, environ: dict[str, str] | None = None) -> HostEnv:
    (tmp / "home").mkdir(exist_ok=True)
    bundle = tmp / "skills" / "omniweave"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_bytes(ROUTER.encode())
    return HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=LAUNCH,
        project_root=root,
        windows=True,
        which=lambda _name: None,
        lock_wait_ms=0,
        skills_root=tmp / "skills",
        environ=environ or {},
    )


def _tree(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        one.relative_to(root).as_posix(): (one.read_bytes() if one.is_file() else None)
        for one in sorted(root.rglob("*"))
    }


def _ok(result: WriteResult) -> dict[str, str]:
    assert not result.refused, result.refused
    return {f"{one.kind}:{one.path}": one.action for one in result.actions}


def _opts(hooks: HookSet | None = "none", skills: Any = "none", **kwargs: Any) -> InstallOptions:
    return InstallOptions(hooks=hooks, skills=skills, **kwargs)


def _config(tmp: Path) -> Path:
    return tmp / "home" / ".codex" / "config.toml"


# ---------------------------------------------------------------------------------------------
# One file, one row, and what came with them.
# ---------------------------------------------------------------------------------------------


def test_the_host_is_an_agent_target_and_one_registry_row(tmp_path: Path) -> None:
    target: AgentTarget = build("codex", _env(tmp_path))
    assert isinstance(target, Codex)
    assert TARGETS["codex"] is Codex


def test_the_paths_are_the_manuals_and_codex_home_moves_three_of_them(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    assert Codex(_env(tmp_path, root=root)).describe_paths("global") == (
        "~/.codex/config.toml",
        "~/.codex/AGENTS.md",
        "~/.codex/hooks.json",
        "~/.agents/skills/omniweave",
    )
    moved = Codex(_env(tmp_path, environ={"CODEX_HOME": str(tmp_path / "ch")}))
    named = (tmp_path / "ch").as_posix()
    assert moved.describe_paths("global")[:3] == tuple(
        f"{named}/{name}" for name in ("config.toml", "AGENTS.md", "hooks.json")
    )
    base = root.as_posix()
    assert Codex(_env(tmp_path, root=root)).describe_paths("local") == (
        f"{base}/.codex/config.toml",
        f"{base}/AGENTS.md",
        f"{base}/.codex/hooks.json",
        f"{base}/.agents/skills/omniweave",
    )


def test_the_table_is_toml_that_parses_to_the_entry() -> None:
    entry = mcp_entry(LAUNCH, windows=True)
    assert entry == {
        "command": "C:/Program Files (x86)/Python/python.exe",
        "args": ["-m", "omniweave", "serve", "--mcp"],
        "env": {},
    }
    assert tomllib.loads(mcp_table(entry)) == {"mcp_servers": {SERVER: entry}}
    odd = mcp_entry(('/opt/a "b"\\c/python',), windows=False)
    assert tomllib.loads(mcp_table(odd))["mcp_servers"][SERVER] == odd


def test_the_hash_markers_see_no_fences_and_a_row_names_its_pair() -> None:
    """D480: a TOML multi-line string may hold a ``` line, which is text and not a fence."""
    text = 'x = """\n```\n"""\n# omniweave:begin\n[t]\n# omniweave:end\n'
    assert isinstance(section_span(text, HASH), tuple)
    assert section_span(text, HTML) is None
    assert markers_for("# omniweave:begin") is HASH
    assert markers_for("<!-- omniweave:begin -->") is HTML
    assert markers_for("") is HTML


# ---------------------------------------------------------------------------------------------
# config.toml.
# ---------------------------------------------------------------------------------------------


def test_a_global_install_into_a_users_config_reverses_byte_for_byte(tmp_path: Path) -> None:
    host = Codex(_env(tmp_path))
    config = _config(tmp_path)
    config.parent.mkdir(parents=True)
    config.write_bytes(USER_TOML.encode())
    before = _tree(tmp_path / "home")
    done = _ok(host.install("global", _opts()))
    assert done["mcp:~/.codex/config.toml"] == "updated"
    document = tomllib.loads(config.read_text("utf-8"))
    assert document["profiles"] == {"fast": {"model": "mini"}}
    assert document["mcp_servers"][SERVER] == mcp_entry(LAUNCH, windows=True)
    assert host.detect("global").already_configured
    assert _ok(host.install("global", _opts()))["mcp:~/.codex/config.toml"] == "unchanged"
    _ok(host.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_a_config_with_no_final_newline_comes_back_without_one(tmp_path: Path) -> None:
    host = Codex(_env(tmp_path))
    config = _config(tmp_path)
    config.parent.mkdir(parents=True)
    config.write_bytes(b'model = "gpt-5"')
    _ok(host.install("global", _opts()))
    _ok(host.uninstall("global"))
    assert config.read_bytes() == b'model = "gpt-5"'


@pytest.mark.parametrize(
    "text",
    [
        '[mcp_servers.omniweave]\ncommand = "mine"\n',
        'mcp_servers = { other = { command = "x" } }\n',
        "this is = = not toml\n",
    ],
    ids=["own-table", "inline-table", "not-toml"],
)
def test_a_users_own_omniweave_table_is_refused_with_the_parsers_reason(
    tmp_path: Path, text: str
) -> None:
    host = Codex(_env(tmp_path))
    config = _config(tmp_path)
    config.parent.mkdir(parents=True)
    config.write_bytes(text.encode())
    result = host.install("global", _opts())
    (mcp,) = [one for one in result.actions if one.kind == "mcp"]
    assert mcp.action == "kept"
    assert "would not be valid TOML" in mcp.note
    assert config.read_bytes() == text.encode()
    assert not any(one.kind == "mcp" for one in load(tmp_path / "owhome", pid=PID).receipt.entries)


# ---------------------------------------------------------------------------------------------
# Hooks and AGENTS.md.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("hooks", ["context", "steer"])
def test_the_hooks_are_the_four_that_can_do_their_work_there(
    tmp_path: Path, hooks: HookSet
) -> None:
    """D482: PreToolUse cannot match a Codex tool, and PostToolUse gets no file path."""
    host = Codex(_env(tmp_path))
    before = _tree(tmp_path / "home")
    result = host.install("global", _opts(hooks))
    _ok(result)
    document = json.loads((tmp_path / "home" / ".codex" / "hooks.json").read_text("utf-8"))
    assert [event for event, _ in owned_pairs(document)] == FOUR
    assert any(note.startswith("PostToolUse NOT written") for note in result.notes)
    assert any("trusted in /hooks" in note for note in result.notes)
    assert any(note.startswith("PreToolUse NOT written") for note in result.notes) == (
        hooks == "steer"
    )
    _ok(host.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_agents_md_carries_the_block_with_the_prefix_the_manual_names(tmp_path: Path) -> None:
    """The manual's hook table matches MCP tools as `mcp__filesystem__read_file`."""
    host = Codex(_env(tmp_path))
    _ok(host.install("global", _opts()))
    text = (tmp_path / "home" / ".codex" / "AGENTS.md").read_text("utf-8")
    assert instruction_block(TOOL_PREFIX) in text
    assert TOOL_PREFIX in text


def test_a_local_install_names_the_trust_codex_needs_and_reverses(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "AGENTS.md").write_bytes(b"# House rules\n\nTabs.\n")
    host = Codex(_env(tmp_path, root=root))
    before = _tree(root)
    result = host.install("local", _opts("context", skills="core"))
    assert set(_ok(result).values()) == {"created", "updated"}
    assert any("only in a project it trusts" in note for note in result.notes)
    _ok(host.uninstall("local"))
    assert _tree(root) == before


# ---------------------------------------------------------------------------------------------
# One skill directory, two hosts. D481.
# ---------------------------------------------------------------------------------------------


def _both(tmp: Path) -> tuple[ClaudeCode, Codex]:
    env = _env(tmp)
    return ClaudeCode(env), Codex(env)


def test_uninstalling_claude_code_first_leaves_codex_its_skill(tmp_path: Path) -> None:
    claude, codex = _both(tmp_path)
    before = _tree(tmp_path / "home")
    _ok(claude.install("global", _opts(skills="core")))
    shared = _ok(codex.install("global", _opts(skills="core")))
    assert shared["skill:~/.agents/skills/omniweave"] == "unchanged"
    done = claude.uninstall("global")
    (skill,) = [one for one in done.actions if one.kind == "skill"]
    assert skill.action == "kept"
    assert "codex's row names it too" in skill.note
    assert (tmp_path / "home" / ".agents" / "skills" / "omniweave" / "SKILL.md").is_file()
    status = verbs.check("codex", "global", codex.env)
    assert status.lines[0].endswith("skill hash ok")
    (heir,) = [
        one for one in load(tmp_path / "owhome", pid=PID).receipt.entries if one.kind == "skill"
    ]
    assert heir.target == "codex"
    assert heir.created_file
    _ok(codex.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_uninstalling_codex_first_leaves_claude_code_its_skill(tmp_path: Path) -> None:
    claude, codex = _both(tmp_path)
    before = _tree(tmp_path / "home")
    _ok(claude.install("global", _opts(skills="core")))
    _ok(codex.install("global", _opts(skills="core")))
    _ok(codex.uninstall("global"))
    assert (tmp_path / "home" / ".agents" / "skills" / "omniweave").is_dir()
    _ok(claude.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_a_host_with_no_row_does_not_re_derive_another_hosts_skill_away(tmp_path: Path) -> None:
    """D455's re-derivation removes a tree equal to this release's bundle; not a sibling's."""
    claude, codex = _both(tmp_path)
    _ok(claude.install("global", _opts(skills="core")))
    done = codex.uninstall("global")
    (skill,) = [one for one in done.actions if one.kind == "skill"]
    assert skill.action == "not-found"
    assert "claude-code's row names it" in skill.note
    assert (tmp_path / "home" / ".agents" / "skills" / "omniweave" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------------------------
# --check, and this machine.
# ---------------------------------------------------------------------------------------------


def test_check_reads_each_row_by_its_own_markers_and_digests(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "home" / ".codex").mkdir()
    _ok(Codex(env).install("global", _opts("context", skills="core")))
    outcome = verbs.check("codex", "global", env)
    assert outcome.exit_code == verbs.OK
    assert outcome.lines == (
        "codex       global   configured    "
        "mcp ok · instructions ok · hooks 4/4 ok · skill hash ok",
    )


def test_print_config_writes_nothing(tmp_path: Path) -> None:
    host = Codex(_env(tmp_path))
    before = _tree(tmp_path)
    text = host.print_config("global")
    assert _tree(tmp_path) == before
    assert text.startswith("# ~/.codex/config.toml  marker-section\n# omniweave:begin\n")
    assert "# permissions NOT written" in text


def test_this_machines_codex_config_comes_back_byte_for_byte(tmp_path: Path) -> None:
    """This machine's own `~/.codex/config.toml`, copied -- the real one is only read."""
    source = REAL / ".codex" / "config.toml"
    if not source.is_file():
        pytest.skip("no Codex config on this machine")
    config = _config(tmp_path)
    config.parent.mkdir(parents=True)
    shutil.copyfile(source, config)
    host = Codex(_env(tmp_path))
    before = _tree(tmp_path / "home")
    assert _ok(host.install("global", _opts()))["mcp:~/.codex/config.toml"] == "updated"
    _ok(host.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_hooks_none_into_no_file_writes_no_file(tmp_path: Path) -> None:
    """D483: converging to no hooks wrote `{}`, a file no row named and no uninstall removed."""
    host = Codex(_env(tmp_path))
    result = _ok(host.install("global", _opts("none")))
    assert result["hooks:~/.codex/hooks.json"] == "unchanged"
    assert not (tmp_path / "home" / ".codex" / "hooks.json").exists()
