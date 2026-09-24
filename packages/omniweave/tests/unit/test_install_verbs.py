"""`ow install | uninstall | --check` as functions: the four `--target`s, the plan, 0 and 9.

**The sharpest test is `test_check_asserts_both_directions_around_an_install_and_uninstall`.**
10:1780's G-install needs `--check` to exit 9 before, 0 after install, and 9 again after uninstall;
this runs that cycle against one scratch home and asserts each line along the way.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.install import verbs
from omniweave.install.claude_code import ALLOW_CLI, ClaudeCode
from omniweave.install.engine import HostEnv
from omniweave.install.primitives import render_json
from omniweave.install.types import InstallOptions

if TYPE_CHECKING:
    from omniweave.install.types import HookSet, SkillSet

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
ROUTER = {"SKILL.md": b"# omniweave\n", "references/actions.md": b"catalog\n"}


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


def _bundle(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def _env(tmp: Path, *, root: Path | None = None) -> HostEnv:
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    _bundle(tmp / "skills" / "omniweave", ROUTER)
    return HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=("C:/Py/python.exe", "-m", "omniweave"),
        project_root=root,
        windows=True,
        which=lambda _name: None,
        lock_wait_ms=0,
        skills_root=tmp / "skills",
    )


def _opts(hooks: HookSet | None = "steer", skills: SkillSet = "none", **kw: Any) -> InstallOptions:
    return InstallOptions(hooks=hooks, skills=skills, **kw)


def _tree(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        one.relative_to(root).as_posix(): (one.read_bytes() if one.is_file() else None)
        for one in sorted(root.rglob("*"))
    }


def _yes(_question: str) -> bool:
    return True


# ---------------------------------------------------------------------------------------------
# --target.
# ---------------------------------------------------------------------------------------------


def test_the_four_resolutions_of_target(tmp_path: Path) -> None:
    """10:1662-1663."""
    env = _env(tmp_path)
    assert verbs.resolve_targets("none", env, "global") == ()
    everything = verbs.resolve_targets("all", env, "global")
    assert [one.id for one in everything] == ["claude-code", "codex", "cursor"]
    assert [one.id for one in verbs.resolve_targets("auto", env, "global")] == ["claude-code"]
    listed = verbs.resolve_targets("claude-code, claude-code", env, "global")
    assert [one.id for one in listed] == ["claude-code"]
    with pytest.raises(ValueError, match="unknown target 'vim'; known: claude-code, codex"):
        verbs.resolve_targets("claude-code,vim", env, "global")
    with pytest.raises(ValueError, match="not built yet"):
        verbs.resolve_targets("gemini", env, "global")
    with pytest.raises(ValueError, match="--target is empty"):
        verbs.resolve_targets(" , ", env, "global")


def test_auto_falls_back_to_claude_code_when_nothing_is_detected(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert not ClaudeCode(env).detect("global").installed
    assert [one.id for one in verbs.resolve_targets("auto", env, "global")] == ["claude-code"]


def test_an_unknown_target_is_a_usage_error_not_a_traceback(tmp_path: Path) -> None:
    outcome = verbs.install("vim", "global", _opts(), _env(tmp_path), yes=True)
    assert outcome.exit_code == verbs.USAGE
    assert outcome.lines[0].startswith("ow: unknown target 'vim'; known: ")


# ---------------------------------------------------------------------------------------------
# ow install.
# ---------------------------------------------------------------------------------------------


def test_a_dry_run_prints_18_2974s_plan_and_writes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    before = _tree(tmp_path)
    outcome = verbs.install("claude-code", "global", _opts("context", dry_run=True), env)
    assert outcome.exit_code == verbs.OK
    assert _tree(tmp_path) == before
    text = outcome.text()
    assert outcome.lines[0] == "plan (nothing written)"
    assert "  ~/.claude.json               json-key        mcpServers.omniweave" in text
    assert "json-array-add  permissions.allow += mcp__omniweave__*" in text
    assert "SessionStart PreCompact UserPromptSubmit PostToolUse SessionEnd" in text
    assert "<!-- omniweave:begin -->" in text
    assert f"{ALLOW_CLI} NOT written (--allow-cli is OFF BY DEFAULT)" in text
    rows = [line for line in outcome.lines if line.startswith("  ~") and " -- " not in line]
    assert rows
    assert all(line.endswith(("create", "update")) for line in rows)


def test_the_plan_says_what_the_install_then_does(tmp_path: Path) -> None:
    """D468. Two steps write `settings.json`; the second is an update, in the plan as in the run."""
    env = _env(tmp_path)
    opts = _opts("context", skills="core")
    planned = verbs.install("claude-code", "global", replace(opts, dry_run=True), env)
    done = verbs.install("claude-code", "global", opts, env, yes=True)
    plan = [(one.kind, one.action) for r in planned.results for one in r.actions]
    real = [(one.kind, one.action) for r in done.results for one in r.actions]
    assert plan == real
    assert ("hooks", "updated") in real


def test_an_unconfirmed_plan_writes_nothing_and_exits_1(tmp_path: Path) -> None:
    """10:1620-1621: the plan first, then `--yes` or the question."""
    env = _env(tmp_path)
    before = _tree(tmp_path)
    for confirm in (None, lambda _q: False):
        outcome = verbs.install("claude-code", "global", _opts(), env, confirm=confirm)
        assert outcome.exit_code == verbs.USAGE
        assert outcome.lines[0] == "plan"
        assert outcome.lines[-1].startswith("not confirmed; nothing written (pass --yes")
        assert _tree(tmp_path) == before


def test_a_confirmed_install_writes_and_names_the_receipt(tmp_path: Path) -> None:
    env = _env(tmp_path)
    asked: list[str] = []

    def confirm(question: str) -> bool:
        asked.append(question)
        return True

    outcome = verbs.install("claude-code", "global", _opts(), env, confirm=confirm)
    assert asked == ["Write this plan?"]
    assert outcome.exit_code == verbs.OK
    receipt = (tmp_path / "owhome" / "install-receipt.json").as_posix()
    assert outcome.lines[-1] == (
        f"wrote 4 entries \u00b7 receipt {receipt} (a post-write sha256 per path)"
    )
    assert (tmp_path / "home" / ".claude.json").is_file()


def test_a_step_that_was_kept_makes_the_install_exit_1(tmp_path: Path) -> None:
    env = replace(_env(tmp_path), skills_root=tmp_path / "empty")
    (tmp_path / "empty" / "omniweave").mkdir(parents=True)
    outcome = verbs.install("claude-code", "global", _opts(skills="core"), env, yes=True)
    assert outcome.exit_code == verbs.USAGE
    assert any(
        "dir" in line and "kept -- " in line and "SKILL.md" in line for line in outcome.lines
    )


def test_print_config_is_the_hosts_and_writes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    before = _tree(tmp_path)
    outcome = verbs.print_config("claude-code", "global", env)
    assert outcome.exit_code == verbs.OK
    assert outcome.lines[0] == "# ~/.claude.json  json-key  mcpServers.omniweave"
    assert _tree(tmp_path) == before
    assert verbs.print_config("gemini", "global", env).exit_code == verbs.USAGE


# ---------------------------------------------------------------------------------------------
# --check.
# ---------------------------------------------------------------------------------------------


def test_check_asserts_both_directions_around_an_install_and_uninstall(tmp_path: Path) -> None:
    """10:1780: 9 when not configured, 0 when configured -- so the gate can assert both."""
    env = _env(tmp_path)
    before = verbs.check("claude-code", "global", env)
    assert (before.exit_code, before.lines) == (9, ("claude-code global   not installed",))
    verbs.install("claude-code", "global", _opts(skills="core"), env, yes=True)
    after = verbs.check("claude-code", "global", env)
    assert after.exit_code == verbs.OK
    assert after.lines == (
        "claude-code global   configured    mcp ok \u00b7 permissions ok \u00b7 instructions ok"
        " \u00b7 hooks 6/6 ok \u00b7 skill hash ok",
    )
    verbs.uninstall("claude-code", "global", env, yes=True)
    assert verbs.check("claude-code", "global", env).exit_code == verbs.NOT_CONFIGURED


def test_a_present_host_without_omniweave_is_not_configured(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "home" / ".claude").mkdir()
    outcome = verbs.check("auto", "global", env)
    assert (outcome.exit_code, outcome.lines) == (9, ("claude-code global   not configured",))


def test_check_names_what_changed_and_still_says_configured(tmp_path: Path) -> None:
    env = _env(tmp_path)
    verbs.install("claude-code", "global", _opts(skills="core"), env, yes=True)
    path = tmp_path / "home" / ".claude.json"
    document = json.loads(path.read_bytes())
    document["mcpServers"]["omniweave"]["env"] = {"X": "1"}
    path.write_bytes(render_json(document))
    (tmp_path / "home" / ".agents" / "skills" / "omniweave" / "SKILL.md").write_bytes(b"mine\n")
    line = verbs.check("claude-code", "global", env).lines[0]
    assert "mcp MODIFIED" in line
    assert "skill hash MISMATCH (OW-A-031)" in line
    assert verbs.check("claude-code", "global", env).exit_code == verbs.OK


# ---------------------------------------------------------------------------------------------
# ow uninstall.
# ---------------------------------------------------------------------------------------------


def test_uninstall_prints_the_plan_asks_and_then_takes_everything_back(tmp_path: Path) -> None:
    env = _env(tmp_path)
    before = _tree(tmp_path / "home")
    verbs.install("claude-code", "global", _opts(allow_cli=True, skills="core"), env, yes=True)
    installed = _tree(tmp_path / "home")
    refused = verbs.uninstall("all", "global", env, confirm=lambda _q: False)
    assert refused.exit_code == verbs.USAGE
    assert refused.lines[0] == "plan"
    assert any("~/.claude.json" in line and line.endswith("remove") for line in refused.lines)
    assert _tree(tmp_path / "home") == installed
    done = verbs.uninstall("all", "global", env, confirm=_yes)
    assert done.exit_code == verbs.OK
    assert _tree(tmp_path / "home") == before


def test_nothing_installed_is_named_as_nothing_to_remove(tmp_path: Path) -> None:
    outcome = verbs.uninstall("all", "global", _env(tmp_path), yes=True)
    assert "  claude-code global: not configured -- nothing to remove" in outcome.lines
    assert outcome.exit_code == verbs.OK


def test_keep_cli_leaves_the_cli_grant_and_takes_the_rest(tmp_path: Path) -> None:
    """10:1428's `--keep-cli`."""
    env = _env(tmp_path)
    verbs.install("claude-code", "global", _opts(allow_cli=True), env, yes=True)
    verbs.uninstall("all", "global", env, yes=True, keep_cli=True)
    settings = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_bytes())
    assert settings == {"permissions": {"allow": [ALLOW_CLI]}}


def test_session_state_is_swept_and_the_index_is_named_not_deleted(tmp_path: Path) -> None:
    """10:1766-1773, steps 6 and 7."""
    project = tmp_path / "proj"
    control = project / ".omniweave"
    (control / "sessions").mkdir(parents=True)
    (control / "sessions" / "abc.jsonl").write_bytes(b"{}\n")
    (control / "index.owstore").write_bytes(b"store")
    (project / "omniweave.toml").write_bytes(
        b'[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    )
    env = _env(tmp_path, root=project)
    verbs.install("claude-code", "local", _opts(), env, yes=True)
    outcome = verbs.uninstall("all", "local", env, yes=True)
    assert not (control / "sessions").exists()
    assert (control / "index.owstore").read_bytes() == b"store"
    assert any(line.startswith("removed ") and "session journals" in line for line in outcome.lines)
    assert outcome.lines[-1] == (
        "The .omniweave/ index for this project is still here. "
        "Run 'ow store rm --corpus handbook' to delete it."
    )


def test_the_location_question_lists_what_it_will_sweep(tmp_path: Path) -> None:
    """10:1754-1755: *"with the hint text listing the actual directories it will sweep"*."""
    hint = verbs.location_hint("all", _env(tmp_path, root=tmp_path / "proj"))
    first, glob_line, local_line = hint.split("\n")
    assert first == "Uninstall from which location?"
    assert glob_line.startswith("  global: ~/.claude.json, ~/.claude/settings.json")
    assert local_line.startswith(f"  local: {(tmp_path / 'proj').as_posix()}/.mcp.json")


def test_a_host_that_raises_is_named_and_the_verb_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """10:1765: the outer of the two `try/except`s."""
    env = _env(tmp_path)
    verbs.install("claude-code", "global", _opts(), env, yes=True)
    real = ClaudeCode.uninstall

    def flaky(self: ClaudeCode, loc: Any, *, dry_run: bool = False, keep_cli: bool = False) -> Any:
        if not dry_run:
            raise RuntimeError("host exploded")
        return real(self, loc, dry_run=dry_run, keep_cli=keep_cli)

    monkeypatch.setattr(ClaudeCode, "uninstall", flaky)
    outcome = verbs.uninstall("all", "global", env, yes=True)
    assert outcome.exit_code == verbs.USAGE
    assert "  claude-code global: refused -- failed: RuntimeError: host exploded" in outcome.lines


# ---------------------------------------------------------------------------------------------
# refresh_targets.
# ---------------------------------------------------------------------------------------------


def test_refresh_touches_configured_hosts_only_and_re_grants_nothing(tmp_path: Path) -> None:
    """10:1656-1657: `allow_cli=False, hooks=None`; the skill it already has, refreshed."""
    env = _env(tmp_path)
    assert verbs.refresh_targets(env) == ()
    verbs.install("claude-code", "global", _opts(allow_cli=True, skills="core"), env, yes=True)
    (tmp_path / "skills" / "omniweave" / "SKILL.md").write_bytes(b"# omniweave v2\n")
    settings = tmp_path / "home" / ".claude" / "settings.json"
    granted = settings.read_bytes()
    (result,) = verbs.refresh_targets(env)
    kinds = {one.kind: one.action for one in result.actions}
    assert "hooks" not in kinds
    assert kinds["skill"] == "updated"
    assert kinds["permissions"] == "unchanged"
    assert settings.read_bytes() == granted


def test_refresh_does_not_install_a_skill_nobody_asked_for(tmp_path: Path) -> None:
    env = _env(tmp_path)
    verbs.install("claude-code", "global", _opts(), env, yes=True)
    (result,) = verbs.refresh_targets(env)
    assert not [one for one in result.actions if one.kind == "skill"]
    assert not (tmp_path / "home" / ".agents").exists()
