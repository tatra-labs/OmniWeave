"""The claude-code host through the engine: G-install's four cases, and the order D459 fixes.

**The sharpest test is `test_a_reinstall_that_moves_the_permissions_row_last_still_reverses`.** A
re-install that grants `Bash(ow:*)` re-records the permissions row, and D449 moves it after the
hooks row. Undone in receipt order, the hooks row would empty `settings.json` without having created
it and leave `{}` behind; the engine undoes in reverse step order with the creator flag per file.
The second is `test_this_machines_claude_configs_come_back_byte_for_byte`, which runs the whole host
over copies of this machine's own Claude Code files.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.__main__ import DISPATCHED
from omniweave.gen.instructions import TOOL_PREFIX
from omniweave.install import engine
from omniweave.install.claude_code import ALLOW_CLI, MCP_KEY, WILDCARD, ClaudeCode, mcp_entry
from omniweave.install.engine import HostEnv, instruction_block
from omniweave.install.hookrules import owned_pairs
from omniweave.install.primitives import BEGIN, END, render_json
from omniweave.install.receipt import (
    RECEIPT_LOCKED,
    Entry,
    Recorded,
    load,
    receipt_path,
    record,
    take_lock,
)
from omniweave.install.registry import BUILT, TARGETS, build
from omniweave.install.types import TARGET_IDS, InstallOptions
from omniweave.surface.registry import ACTIONS, listed

if TYPE_CHECKING:
    from omniweave.install.types import AgentTarget, HookSet, Location, WriteResult

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
PYTHON = "C:/Program Files (x86)/Python/python.exe"
LAUNCH = (PYTHON, "-m", "omniweave")
STEER = InstallOptions(hooks="steer", skills="none")
REAL = Path.home()


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


def _env(tmp: Path, *, launch: tuple[str, ...] | str = LAUNCH, root: Path | None = None) -> HostEnv:
    return HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=launch,
        project_root=root,
        windows=True,
        which=lambda _name: None,
        lock_wait_ms=0,
    )


def _host(tmp: Path, **kwargs: Any) -> ClaudeCode:
    (tmp / "home").mkdir(exist_ok=True)
    return ClaudeCode(_env(tmp, **kwargs))


def _tree(root: Path) -> dict[str, bytes | None]:
    """Every path under `root`: a file's bytes, or `None` for a directory."""
    if not root.exists():
        return {}
    return {
        one.relative_to(root).as_posix(): (one.read_bytes() if one.is_file() else None)
        for one in sorted(root.rglob("*"))
    }


def _ok(result: WriteResult) -> dict[str, str]:
    assert not result.refused, result.refused
    return {f"{one.kind}:{one.path}": one.action for one in result.actions}


def _opts(hooks: HookSet | None = "steer", **kwargs: Any) -> InstallOptions:
    return InstallOptions(hooks=hooks, skills=kwargs.pop("skills", "none"), **kwargs)


def _write(path: Path, value: object, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=indent) + "\n").encode())


def _rows(host: ClaudeCode) -> list[Entry]:
    return list(load(host.env.omniweave_home, pid=PID).receipt.entries)


# ---------------------------------------------------------------------------------------------
# The shape of the host.
# ---------------------------------------------------------------------------------------------


def test_the_host_is_an_agent_target_and_one_registry_row(tmp_path: Path) -> None:
    target: AgentTarget = build("claude-code", _env(tmp_path))
    assert target.id == "claude-code"
    assert target.supports_location("global")
    assert target.supports_location("local")
    assert BUILT == ("claude-code", "codex", "cursor")
    assert set(TARGETS) <= set(TARGET_IDS)


def test_an_unknown_id_names_the_known_list_and_an_unbuilt_one_says_not_yet(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="unknown target 'claude'; known: claude-code, codex"):
        build("claude", _env(tmp_path))
    with pytest.raises(ValueError, match=r"'gemini' is declared .* built: claude-code, codex, cur"):
        build("gemini", _env(tmp_path))


def test_the_paths_are_10_1667s_table_in_both_columns(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    host = _host(tmp_path, root=root)
    assert host.describe_paths("global") == (
        "~/.claude.json",
        "~/.claude/settings.json",
        "~/.claude/CLAUDE.md",
        "~/.agents/skills/omniweave",
    )
    base = root.as_posix()
    assert host.describe_paths("local") == (
        f"{base}/.mcp.json",
        f"{base}/.claude/settings.json",
        f"{base}/.claude/CLAUDE.md",
        f"{base}/.agents/skills/omniweave",
    )


def test_the_mcp_entry_is_10_1675s_shape_over_this_launcher() -> None:
    entry = mcp_entry(("C:\\Py (x86)\\python.exe", "-m", "omniweave"), windows=True)
    assert entry == {
        "type": "stdio",
        "command": "C:/Py (x86)/python.exe",
        "args": ["-m", "omniweave", "serve", "--mcp"],
        "env": {},
    }
    assert mcp_entry(("/usr/local/bin/ow",), windows=False)["args"] == ["serve", "--mcp"]


def test_the_instruction_block_is_the_listed_set_and_carries_no_cite() -> None:
    """D461. 10:1826's dead-cite example is `d7#412`, which the plan's own `ow_open` line holds."""
    block = instruction_block()
    named = set(re.findall(r"`(ow_[a-z_]+)`", block))
    assert named == {ACTIONS[name].mcp_name for name in listed("default")}
    assert TOOL_PREFIX in block
    assert not re.search(r"\b[deck]\d+#\d+\b|\bp\d+/\d+\b", block)
    assert BEGIN not in block
    assert END not in block


# ---------------------------------------------------------------------------------------------
# G-install: install, re-install, uninstall, byte for byte.
# ---------------------------------------------------------------------------------------------


def test_an_empty_home_is_created_into_and_comes_back_empty(tmp_path: Path) -> None:
    host = _host(tmp_path)
    before = _tree(tmp_path / "home")
    first = _ok(host.install("global", STEER))
    assert first == {
        "mcp:~/.claude.json": "created",
        "permissions:~/.claude/settings.json": "created",
        "instructions:~/.claude/CLAUDE.md": "created",
        "hooks:~/.claude/settings.json": "updated",
    }
    assert [row.kind for row in _rows(host)] == ["mcp", "permissions", "instructions", "hooks"]
    again = _ok(host.install("global", STEER))
    assert set(again.values()) == {"unchanged"}
    undone = host.uninstall("global")
    actions = _ok(undone)
    assert actions.pop("skill:~/.agents/skills/omniweave") == "not-found"
    assert set(actions.values()) == {"removed"}, undone
    assert undone.notes == ()
    assert _tree(tmp_path / "home") == before
    assert _rows(host) == []


def test_unrelated_servers_permissions_and_hooks_survive_byte_for_byte(tmp_path: Path) -> None:
    """G-install case 1 (10:1778), with someone else's hook beside ours in 4-space indent."""
    host = _host(tmp_path)
    home = tmp_path / "home"
    _write(home / ".claude.json", {"numStartups": 7, "mcpServers": {"other": {"command": "x"}}})
    _write(
        home / ".claude" / "settings.json",
        {
            "permissions": {"allow": ["Bash(git:*)"], "deny": []},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "their.sh"}]}]},
        },
        indent=4,
    )
    before = _tree(home)
    _ok(host.install("global", STEER))
    settings = json.loads((home / ".claude" / "settings.json").read_bytes())
    assert settings["permissions"]["allow"] == ["Bash(git:*)", WILDCARD]
    assert len(owned_pairs(settings)) == 6
    assert "their.sh" in json.dumps(settings)
    _ok(host.uninstall("global"))
    assert _tree(home) == before


def test_a_claude_md_with_the_users_text_around_the_block_keeps_it(tmp_path: Path) -> None:
    """G-install case 2 (10:1778-1779): the user writes on both sides of the block after install."""
    host = _host(tmp_path)
    claude_md = tmp_path / "home" / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True)
    claude_md.write_bytes(b"# Mine\n\nKeep this.\n")
    _ok(host.install("global", STEER))
    text = claude_md.read_bytes().decode()
    assert text.startswith("# Mine\n\nKeep this.\n\n" + BEGIN)
    claude_md.write_bytes(("Above.\n\n" + text + "\nBelow.\n").encode())
    actions = _ok(host.uninstall("global"))
    assert actions["instructions:~/.claude/CLAUDE.md"] == "removed"
    assert claude_md.read_bytes() == b"Above.\n\n# Mine\n\nKeep this.\n\nBelow.\n"


def test_a_second_tool_writing_the_same_files_is_left_as_it_wrote_them(tmp_path: Path) -> None:
    """G-install case 3 (10:1779): what remains is exactly the other tool's install alone."""
    ours, alone = tmp_path / "ours", tmp_path / "alone"
    for root in (ours, alone):
        root.mkdir()
        _write(root / "home" / ".claude.json", {"mcpServers": {}})
    host = _host(ours)
    _ok(host.install("global", STEER))
    other = ClaudeCode(_env(ours))
    for root in (ours, alone):
        _other_tool(root / "home")
    _ok(other.uninstall("global"))
    assert _tree(ours / "home") == _tree(alone / "home")


def _other_tool(home: Path) -> None:
    """Another installer that adds its own server and grant, preserving the file's style."""
    for path, change in (
        (home / ".claude.json", lambda d: d.setdefault("mcpServers", {}).update(tool={"x": 1})),
        (
            home / ".claude" / "settings.json",
            lambda d: d.setdefault("permissions", {}).setdefault("allow", []).append("mcp__t__*"),
        ),
    ):
        document = json.loads(path.read_bytes()) if path.exists() else {}
        change(document)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_json(document))


def test_two_local_installs_uninstalling_one_leaves_the_other(tmp_path: Path) -> None:
    """G-install case 4 (10:1780): two project roots, one receipt."""
    one, two = tmp_path / "one", tmp_path / "two"
    for root in (one, two):
        root.mkdir()
    first, second = _host(tmp_path, root=one), _host(tmp_path, root=two)
    empty = _tree(one)
    _ok(first.install("local", STEER))
    _ok(second.install("local", STEER))
    installed_two = _tree(two)
    _ok(first.uninstall("local"))
    assert _tree(one) == empty
    assert _tree(two) == installed_two
    assert {row.scope_root for row in _rows(second)} == {str(two)}
    _ok(second.uninstall("local"))
    assert _tree(two) == empty


def test_a_reinstall_that_moves_the_permissions_row_last_still_reverses(tmp_path: Path) -> None:
    """D459. D449 moves the re-recorded permissions row after the hooks row."""
    host = _host(tmp_path)
    before = _tree(tmp_path / "home")
    _ok(host.install("global", STEER))
    _ok(host.install("global", _opts(allow_cli=True)))
    assert [row.kind for row in _rows(host)] == ["mcp", "instructions", "hooks", "permissions"]
    assert next(r for r in _rows(host) if r.kind == "permissions").values == (WILDCARD, ALLOW_CLI)
    _ok(host.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_upgrading_the_hook_set_converges_and_hooks_none_takes_ours_out(tmp_path: Path) -> None:
    host = _host(tmp_path)
    before = _tree(tmp_path / "home")
    settings = tmp_path / "home" / ".claude" / "settings.json"
    _ok(host.install("global", _opts("context")))
    assert len(owned_pairs(json.loads(settings.read_bytes()))) == 5
    _ok(host.install("global", STEER))
    assert len(owned_pairs(json.loads(settings.read_bytes()))) == 6
    actions = _ok(host.install("global", _opts("none")))
    assert actions["hooks:~/.claude/settings.json"] == "removed"
    assert owned_pairs(json.loads(settings.read_bytes())) == []
    assert "hooks" not in [row.kind for row in _rows(host)]
    _ok(host.uninstall("global"))
    assert _tree(tmp_path / "home") == before


def test_a_refresh_with_hooks_none_leaves_the_hooks_alone(tmp_path: Path) -> None:
    """10:1656: `refresh_targets()` passes `hooks=None` and `allow_cli=False`."""
    host = _host(tmp_path)
    _ok(host.install("global", _opts(allow_cli=True)))
    settings = tmp_path / "home" / ".claude" / "settings.json"
    written = settings.read_bytes()
    refreshed = _ok(host.install("global", _opts(None)))
    assert not any(key.startswith("hooks:") for key in refreshed)
    assert set(refreshed.values()) == {"unchanged"}
    assert settings.read_bytes() == written


def test_this_machines_claude_configs_come_back_byte_for_byte(tmp_path: Path) -> None:
    """This machine's own Claude Code files, copied -- the real ones are only read."""
    home = tmp_path / "home"
    copied = []
    for relative in (".claude.json", ".claude/settings.json", ".claude/CLAUDE.md"):
        source = REAL / relative
        if source.is_file():
            (home / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, home / relative)
            copied.append(relative)
    if not copied:
        pytest.skip("no Claude Code files on this machine")
    host = _host(tmp_path)
    before = _tree(home)
    _ok(host.install("global", _opts(allow_cli=True)))
    _ok(host.install("global", STEER))
    _ok(host.uninstall("global"))
    assert _tree(home) == before, copied


# ---------------------------------------------------------------------------------------------
# What writes nothing.
# ---------------------------------------------------------------------------------------------


def test_a_dry_run_reports_the_plan_and_writes_nothing_not_even_the_home(tmp_path: Path) -> None:
    host = _host(tmp_path)
    before = _tree(tmp_path)
    planned = _ok(host.install("global", _opts(dry_run=True)))
    assert planned["mcp:~/.claude.json"] == "created"
    assert _tree(tmp_path) == before
    _ok(host.install("global", STEER))
    installed = _tree(tmp_path)
    removal = _ok(host.uninstall("global", dry_run=True))
    assert removal.pop("skill:~/.agents/skills/omniweave") == "not-found"
    assert set(removal.values()) == {"removed"}
    assert _tree(tmp_path) == installed


def test_print_config_names_every_value_and_touches_nothing(tmp_path: Path) -> None:
    """10:1641: *"MUST NOT touch the filesystem"*."""
    host = _host(tmp_path)
    before = _tree(tmp_path)
    text = host.print_config("global")
    assert _tree(tmp_path) == before
    assert "# ~/.claude.json  json-key  mcpServers.omniweave" in text
    assert '"command": "C:/Program Files (x86)/Python/python.exe"' in text
    assert f"permissions.allow += {WILDCARD} {ALLOW_CLI}" in text
    assert "SessionStart PreCompact UserPromptSubmit PreToolUse PostToolUse SessionEnd" in text
    assert f"{BEGIN}\n{instruction_block()}\n{END}" in text


def test_detection_reads_and_reports_what_it_found(tmp_path: Path) -> None:
    host = _host(tmp_path)
    before = _tree(tmp_path)
    absent = host.detect("global")
    assert (absent.installed, absent.already_configured) == (False, False)
    assert _tree(tmp_path) == before
    _ok(host.install("global", STEER))
    present = host.detect("global")
    assert (present.installed, present.already_configured) == (True, True)
    assert "~/.claude" in present.note
    assert MCP_KEY in present.note


# ---------------------------------------------------------------------------------------------
# Notes, refusals, and the paths that are not the happy one.
# ---------------------------------------------------------------------------------------------


def test_the_notes_say_what_was_not_written_and_why(tmp_path: Path) -> None:
    host = _host(tmp_path)
    plain = host.install("global", _opts(skills="core", dry_run=True))
    assert f"{ALLOW_CLI} NOT written (--allow-cli is OFF BY DEFAULT)" in plain.notes
    skill = next(one for one in plain.actions if one.kind == "skill")
    assert (skill.action, skill.note) == ("kept", "no skill bundle source was given")
    granted = host.install("global", _opts(allow_cli=True, dry_run=True))
    assert any("no `ow` on PATH" in note for note in granted.notes)


def test_the_mcp_action_says_serve_is_not_dispatched_while_it_is_not(tmp_path: Path) -> None:
    """D460, read from the dispatcher, so this flips the day `serve` is wired."""
    host = _host(tmp_path)
    result = host.install("global", STEER)
    mcp = next(one for one in result.actions if one.kind == "mcp")
    assert ("does not dispatch" in mcp.note) is ("serve" not in DISPATCHED)


def test_no_launcher_keeps_the_two_steps_that_need_one_and_writes_the_rest(
    tmp_path: Path,
) -> None:
    host = _host(tmp_path, launch="no absolute `ow` on PATH")
    actions = {one.kind: one for one in host.install("global", STEER).actions}
    assert actions["mcp"].action == "kept"
    assert actions["hooks"].action == "kept"
    assert "no absolute" in actions["mcp"].note
    assert actions["permissions"].action == "created"
    assert actions["instructions"].action == "created"
    assert [row.kind for row in _rows(host)] == ["permissions", "instructions"]


def test_a_held_lock_refuses_before_anything_is_written(tmp_path: Path) -> None:
    host = _host(tmp_path)
    held = take_lock(host.env.omniweave_home, clock=_Clock(), wait_ms=0)
    assert held.lock is not None
    before = _tree(tmp_path / "home")
    with held.lock:
        refused = host.install("global", STEER)
        undo = host.uninstall("global")
    assert refused.refused.startswith(RECEIPT_LOCKED)
    assert refused.actions == ()
    assert undo.refused.startswith(RECEIPT_LOCKED)
    assert _tree(tmp_path / "home") == before


def test_a_local_install_without_a_project_root_is_refused(tmp_path: Path) -> None:
    host = _host(tmp_path)
    assert "project root" in host.install("local", STEER).refused
    assert "project root" in host.uninstall("local").refused


def test_a_newer_receipt_refuses_install_and_uninstall_re_derives_around_it(
    tmp_path: Path,
) -> None:
    host = _host(tmp_path)
    _ok(host.install("global", STEER))
    newer = {"release": "9.0.0", "schema": 99, "entries": []}
    receipt_path(host.env.omniweave_home).write_bytes(json.dumps(newer).encode())
    receipt = receipt_path(host.env.omniweave_home).read_bytes()
    assert "cannot be rewritten" in host.install("global", STEER).refused
    undone = host.uninstall("global")
    assert any("re-derivation" in note for note in undone.notes)
    actions = _ok(undone)
    assert actions.pop("skill:~/.agents/skills/omniweave") == "not-found"
    assert set(actions.values()) == {"removed"}
    assert receipt_path(host.env.omniweave_home).read_bytes() == receipt
    settings = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_bytes())
    assert WILDCARD not in json.dumps(settings)
    assert owned_pairs(settings) == []


def test_a_lost_receipt_still_unwires_everything_by_re_derivation(tmp_path: Path) -> None:
    """10:1758: *"a lost receipt never strands a user"*. What it created is not known."""
    host = _host(tmp_path)
    _ok(host.install("global", _opts(allow_cli=True)))
    receipt_path(host.env.omniweave_home).unlink()
    _ok(host.uninstall("global"))
    home = tmp_path / "home"
    servers = json.loads((home / ".claude.json").read_bytes())["mcpServers"]
    assert MCP_KEY.split(".")[1] not in servers
    settings = json.loads((home / ".claude" / "settings.json").read_bytes())
    assert settings["permissions"]["allow"] == [ALLOW_CLI]
    assert owned_pairs(settings) == []
    assert BEGIN not in (home / ".claude" / "CLAUDE.md").read_bytes().decode()


def test_a_value_the_user_edited_is_kept_and_its_row_survives(tmp_path: Path) -> None:
    host = _host(tmp_path)
    _ok(host.install("global", STEER))
    path = tmp_path / "home" / ".claude.json"
    document = json.loads(path.read_bytes())
    document["mcpServers"]["omniweave"]["env"] = {"OW_PROFILE": "full"}
    path.write_bytes(render_json(document))
    actions = _ok(host.uninstall("global"))
    assert actions["mcp:~/.claude.json"] == "kept"
    assert [row.kind for row in _rows(host)] == ["mcp"]
    assert json.loads(path.read_bytes())["mcpServers"]["omniweave"]["env"] == {"OW_PROFILE": "full"}


def test_a_failing_undo_is_reported_and_the_rest_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """10:1765: never throw."""
    host = _host(tmp_path)
    _ok(host.install("global", STEER))

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(engine, "unset_hooks", boom)
    result = host.uninstall("global")
    actions = {one.kind: one for one in result.actions}
    assert actions["hooks"].action == "kept"
    assert actions["hooks"].note == "failed: OSError: disk on fire"
    assert actions["mcp"].action == "removed"
    assert actions["instructions"].action == "removed"
    assert [row.kind for row in _rows(host)] == ["hooks"]


def test_a_row_no_step_names_is_undone_at_the_path_it_names(tmp_path: Path) -> None:
    """A release that moved a file leaves a row at the old path; uninstall still takes it back."""
    host = _host(tmp_path)
    old = tmp_path / "home" / ".claude" / "old.json"
    _write(old, {"keep": 1})
    before = old.read_bytes()
    site = engine.Site("claude-code", "global", old, tmp_path / "home")
    applied = engine.set_key(site, "mcp", MCP_KEY, {"x": 1}, previous=None, clock=_Clock(), pid=PID)
    assert applied.record is not None
    taken = take_lock(host.env.omniweave_home, clock=_Clock(), wait_ms=0)
    assert taken.lock is not None
    with taken.lock as lock:
        assert record(lock, applied.record, release="0.1.0", pid=PID).ok
    actions = _ok(host.uninstall("global"))
    assert actions["mcp:~/.claude/old.json"] == "removed"
    assert old.read_bytes() == before
    assert _rows(host) == []


def test_a_row_that_cannot_be_recorded_stops_the_install_and_says_where(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _host(tmp_path)
    monkeypatch.setattr(engine, "record", lambda *_a, **_k: Recorded(ok=False, reason="full"))
    result = host.install("global", STEER)
    assert [one.kind for one in result.actions] == ["mcp"]
    assert any(
        "~/.claude.json was written but its receipt row was not: full; stopped before" in note
        for note in result.notes
    )


@pytest.mark.parametrize("location", ["global", "local"])
def test_every_row_names_its_target_location_and_scope(tmp_path: Path, location: Location) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    host = _host(tmp_path, root=root)
    _ok(host.install(location, STEER))
    scope = None if location == "global" else str(root)
    assert {(row.target, row.location, row.scope_root) for row in _rows(host)} == {
        ("claude-code", location, scope)
    }
