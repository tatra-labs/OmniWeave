"""The second host, Cursor: one file and one registry row, and what that claim cost to make true.

**The sharpest test is `test_a_local_install_leaves_the_project_as_it_was`.** The rule file must
open with its frontmatter (D477), so install creates it with a head the marker block does not
cover, and the file, `rules/` and `.cursor/` must all go again. The second is
`test_this_machines_cursor_mcp_file_comes_back_byte_for_byte`, over a copy of this machine's own
`~/.cursor/mcp.json`, which Cursor wrote.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.gen.instructions import TOOL_PREFIX
from omniweave.install import verbs
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.cursor import MCP_KEY, RULE_HEAD, Cursor, mcp_entry
from omniweave.install.engine import HostEnv, instruction_block
from omniweave.install.primitives import BEGIN, END
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


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


def _env(tmp: Path, *, root: Path | None = None, which: Any = None) -> HostEnv:
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
        which=which or (lambda _name: None),
        lock_wait_ms=0,
        skills_root=tmp / "skills",
    )


def _host(tmp: Path, **kwargs: Any) -> Cursor:
    return Cursor(_env(tmp, **kwargs))


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


def _cursor_style(path: Path, value: object) -> None:
    """How Cursor writes `mcp.json`: two spaces, LF, nothing after the brace (D441's table)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2).encode())


# ---------------------------------------------------------------------------------------------
# One file, one row.
# ---------------------------------------------------------------------------------------------


def test_the_host_is_an_agent_target_and_one_registry_row(tmp_path: Path) -> None:
    target: AgentTarget = build("cursor", _env(tmp_path))
    assert isinstance(target, Cursor)
    assert TARGETS["cursor"] is Cursor
    assert target.supports_location("global")
    assert target.supports_location("local")


def test_the_paths_are_the_ones_cursor_names_for_itself(tmp_path: Path) -> None:
    """D474: no document gives them; Cursor's own shipped skills do."""
    root = tmp_path / "proj"
    host = _host(tmp_path, root=root)
    assert host.describe_paths("global") == ("~/.cursor/mcp.json", "~/.cursor/skills/omniweave")
    base = root.as_posix()
    assert host.describe_paths("local") == (
        f"{base}/.cursor/mcp.json",
        f"{base}/.cursor/rules/omniweave.mdc",
        f"{base}/.cursor/skills/omniweave",
    )


def test_the_entry_is_10_1675s_without_the_type_cursor_does_not_write() -> None:
    """D475."""
    entry = mcp_entry(LAUNCH, windows=True)
    assert entry == {
        "command": "C:/Program Files (x86)/Python/python.exe",
        "args": ["-m", "omniweave", "serve", "--mcp"],
        "env": {},
    }
    assert "type" not in entry


def test_the_rule_is_the_block_without_claude_codes_tool_prefix(tmp_path: Path) -> None:
    """D476: `mcp__omniweave__` is Claude Code's spelling of a tool; nothing measured Cursor's."""
    host = _host(tmp_path, root=tmp_path / "proj")
    (rule,) = [one for one in host.steps("local", _opts()) if one.kind == "instructions"]
    assert rule.head == RULE_HEAD
    assert rule.body == instruction_block(None)
    assert TOOL_PREFIX not in rule.body
    assert TOOL_PREFIX in instruction_block()
    assert instruction_block().startswith(rule.body)


def test_permissions_and_hooks_are_never_steps_and_the_plan_says_so(tmp_path: Path) -> None:
    """D478."""
    host = _host(tmp_path, root=tmp_path / "proj")
    for loc in ("global", "local"):
        steps = host.steps(loc, _opts("steer", allow_cli=True))
        assert {one.kind for one in steps} <= {"mcp", "instructions", "skill"}
    result = host.install("global", _opts("steer", dry_run=True))
    assert any(note.startswith("permissions NOT written") for note in result.notes)
    assert any(note.startswith("hooks NOT written") for note in result.notes)
    assert any(note.startswith("instructions NOT written at global") for note in result.notes)
    quiet = host.install("local", _opts("none", dry_run=True))
    assert not any(note.startswith("hooks NOT written") for note in quiet.notes)


def test_print_config_writes_nothing_and_names_what_it_leaves_out(tmp_path: Path) -> None:
    host = _host(tmp_path, root=tmp_path / "proj")
    before = _tree(tmp_path)
    text = host.print_config("local")
    assert _tree(tmp_path) == before
    assert text.startswith(f"# {(tmp_path / 'proj').as_posix()}/.cursor/mcp.json  json-key  ")
    assert f"marker-section\n{RULE_HEAD}\n{BEGIN}\n" in text
    assert "# permissions NOT written" in text
    assert "# hooks NOT written" in text


# ---------------------------------------------------------------------------------------------
# Reversal.
# ---------------------------------------------------------------------------------------------


def test_a_global_install_into_a_file_with_other_servers_reverses_byte_for_byte(
    tmp_path: Path,
) -> None:
    host = _host(tmp_path)
    mcp = tmp_path / "home" / ".cursor" / "mcp.json"
    _cursor_style(mcp, {"mcpServers": {"docs": {"url": "https://example.invalid/mcp"}}})
    before = _tree(tmp_path / "home")
    done = _ok(host.install("global", _opts(skills="core")))
    assert done == {
        "mcp:~/.cursor/mcp.json": "updated",
        "skill:~/.cursor/skills/omniweave": "created",
    }
    servers = json.loads(mcp.read_text("utf-8"))["mcpServers"]
    assert list(servers) == ["docs", "omniweave"]
    assert host.detect("global").already_configured
    undone = _ok(host.uninstall("global"))
    assert set(undone.values()) == {"removed"}
    assert _tree(tmp_path / "home") == before
    assert list(load(tmp_path / "owhome", pid=PID).receipt.entries) == []


def test_a_local_install_leaves_the_project_as_it_was(tmp_path: Path) -> None:
    """D477: the file install created begins with the head, and the head alone is not the user's."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "README.md").write_bytes(b"hi\n")
    host = _host(tmp_path, root=root)
    before = _tree(root)
    done = _ok(host.install("local", _opts(skills="core")))
    shown = root.as_posix()
    assert done == {
        f"mcp:{shown}/.cursor/mcp.json": "created",
        f"instructions:{shown}/.cursor/rules/omniweave.mdc": "created",
        f"skill:{shown}/.cursor/skills/omniweave": "created",
    }
    rule = (root / ".cursor" / "rules" / "omniweave.mdc").read_text("utf-8")
    assert rule == f"{RULE_HEAD}\n{BEGIN}\n{instruction_block(None)}\n{END}\n"
    _ok(host.uninstall("local"))
    assert _tree(root) == before


def test_other_rules_and_a_users_own_omniweave_rule_are_left_as_they_were(
    tmp_path: Path,
) -> None:
    root = tmp_path / "proj"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "style.mdc").write_bytes(b"---\nalwaysApply: false\n---\n\nTabs.\n")
    (rules / "omniweave.mdc").write_bytes(b"---\nalwaysApply: true\n---\n\nMine.\n")
    host = _host(tmp_path, root=root)
    before = _tree(root)
    _ok(host.install("local", _opts()))
    mine = (rules / "omniweave.mdc").read_text("utf-8")
    assert mine.startswith("---\nalwaysApply: true\n---\n\nMine.\n\n" + BEGIN)
    assert mine.count("---\n") == 2
    _ok(host.uninstall("local"))
    assert _tree(root) == before


def test_a_head_the_user_edited_is_theirs_and_the_file_stays(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    host = _host(tmp_path, root=root)
    _ok(host.install("local", _opts()))
    rule = root / ".cursor" / "rules" / "omniweave.mdc"
    rule.write_bytes(rule.read_bytes().replace(b"alwaysApply: true", b"alwaysApply: false"))
    done = _ok(host.uninstall("local"))
    assert done[f"instructions:{rule.as_posix()}"] == "removed"
    assert rule.read_text("utf-8") == "---\nalwaysApply: false\n---"


def test_two_hosts_in_one_home_uninstalling_one_leaves_the_other(tmp_path: Path) -> None:
    env = _env(tmp_path)
    claude, cursor = ClaudeCode(env), Cursor(env)
    before = _tree(tmp_path / "home")
    _ok(claude.install("global", _opts(skills="core")))
    after_claude = _tree(tmp_path / "home")
    _ok(cursor.install("global", _opts(skills="core")))
    _ok(cursor.uninstall("global"))
    assert _tree(tmp_path / "home") == after_claude
    rows = load(tmp_path / "owhome", pid=PID).receipt.entries
    assert {one.target for one in rows} == {"claude-code"}
    _ok(claude.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_uninstall_with_no_rows_re_derives_the_entry_and_nothing_else(tmp_path: Path) -> None:
    """10:1758: a lost receipt never strands a user."""
    host = _host(tmp_path)
    mcp = tmp_path / "home" / ".cursor" / "mcp.json"
    _cursor_style(mcp, {"mcpServers": {"docs": {"url": "u"}}})
    before = mcp.read_bytes()
    _ok(host.install("global", _opts()))
    (tmp_path / "owhome" / "install-receipt.json").unlink()
    done = _ok(host.uninstall("global"))
    assert done["mcp:~/.cursor/mcp.json"] == "removed"
    assert mcp.read_bytes() == before


def test_this_machines_cursor_mcp_file_comes_back_byte_for_byte(tmp_path: Path) -> None:
    """This machine's own `~/.cursor/mcp.json`, copied -- the real one is only read."""
    source = REAL / ".cursor" / "mcp.json"
    if not source.is_file():
        pytest.skip("no Cursor MCP file on this machine")
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    shutil.copyfile(source, home / ".cursor" / "mcp.json")
    host = _host(tmp_path)
    before = _tree(home)
    assert _ok(host.install("global", _opts()))["mcp:~/.cursor/mcp.json"] == "updated"
    assert _tree(home) != before
    _ok(host.uninstall("global"))
    assert _tree(home) == before


# ---------------------------------------------------------------------------------------------
# --check, and what `auto` now finds.
# ---------------------------------------------------------------------------------------------


def test_check_reads_cursors_rows_by_their_own_digests(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    env = _env(tmp_path, root=root, which=lambda name: f"/bin/{name}")
    _ok(Cursor(env).install("local", _opts(skills="core")))
    outcome = verbs.check("cursor", "local", env)
    assert outcome.exit_code == verbs.OK
    assert outcome.lines == (
        "cursor      local    configured    mcp ok · instructions ok · skill hash ok",
    )


def test_a_machine_with_cursor_that_wired_only_claude_code_checks_9(tmp_path: Path) -> None:
    """D479: `auto` is every host found, so a host found and not wired is a host not configured."""
    env = _env(tmp_path, which=lambda name: f"/bin/{name}" if name == "cursor" else None)
    (tmp_path / "home" / ".claude").mkdir()
    _ok(ClaudeCode(env).install("global", _opts()))
    outcome = verbs.check("auto", "global", env)
    assert outcome.exit_code == verbs.NOT_CONFIGURED
    assert outcome.lines[1] == "cursor      global   not configured"
    assert verbs.check("claude-code", "global", env).exit_code == verbs.OK
    assert MCP_KEY == "mcpServers.omniweave"
