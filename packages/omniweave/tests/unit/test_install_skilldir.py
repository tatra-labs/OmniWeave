"""The `dir` mode through the claude-code host: a bundle copied, recorded by digest, taken back.

**The sharpest test is `test_this_repositorys_bundle_is_refused_by_name_and_the_rest_installs`.** It
points the host at the repository's own `skills/` and shows what `--skills core` does on this
machine today: the router has no `SKILL.md` yet (W7.6), so the skill is refused by name and the
other four steps are written.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.engine import HostEnv
from omniweave.install.receipt import load, receipt_path
from omniweave.install.skilldir import HASH_MISMATCH
from omniweave.install.types import InstallOptions
from omniweave.skills.hash import bundle_sha256

if TYPE_CHECKING:
    from omniweave.install.types import FileAction, SkillSet, WriteResult

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
REPO = Path(__file__).resolve().parents[4]
ROUTER = {"SKILL.md": b"# omniweave\r\n\r\nroute\r\n", "references/actions.md": b"catalog\n"}


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


def _host(tmp: Path, *, skills_root: Path | None = None, root: Path | None = None) -> ClaudeCode:
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    if skills_root is None:
        skills_root = tmp / "skills"
        _bundle(skills_root / "omniweave", ROUTER)
    env = HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=("C:/Py/python.exe", "-m", "omniweave"),
        project_root=root,
        windows=True,
        which=lambda _name: None,
        lock_wait_ms=0,
        skills_root=skills_root,
    )
    return ClaudeCode(env)


def _opts(skills: SkillSet = "core", **kwargs: Any) -> InstallOptions:
    return InstallOptions(hooks=None, skills=skills, **kwargs)


def _skill(result: WriteResult, name: str = "omniweave") -> FileAction:
    assert not result.refused, result.refused
    return next(one for one in result.actions if one.kind == "skill" and one.path.endswith(name))


def _tree(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        one.relative_to(root).as_posix(): (one.read_bytes() if one.is_file() else None)
        for one in sorted(root.rglob("*"))
    }


def _installed(tmp: Path) -> Path:
    return tmp / "home" / ".agents" / "skills" / "omniweave"


def test_a_bundle_is_copied_recorded_by_digest_and_taken_back(tmp_path: Path) -> None:
    host = _host(tmp_path)
    before = _tree(tmp_path / "home")
    assert _skill(host.install("global", _opts())).action == "created"
    dest = _installed(tmp_path)
    assert _tree(dest) == _tree(tmp_path / "skills" / "omniweave")
    rows = load(host.env.omniweave_home, pid=PID).receipt.entries
    row = next(e for e in rows if e.kind == "skill")
    assert row.mode == "dir"
    assert row.path == "~/.agents/skills/omniweave"
    assert row.bundle_sha256 == bundle_sha256(dest)[0]
    assert row.created_file
    assert row.created_dirs == ("~/.agents", "~/.agents/skills")
    assert '"bundle_sha256"' in receipt_path(host.env.omniweave_home).read_text()
    assert _skill(host.install("global", _opts())).action == "unchanged"
    assert _skill(host.uninstall("global")).action == "removed"
    assert _tree(tmp_path / "home") == before


def test_an_upgraded_bundle_replaces_an_untouched_install(tmp_path: Path) -> None:
    host = _host(tmp_path)
    _skill(host.install("global", _opts()))
    (tmp_path / "skills" / "omniweave" / "SKILL.md").write_bytes(b"# omniweave\n\nv2\n")
    assert _skill(host.install("global", _opts())).action == "updated"
    assert (_installed(tmp_path) / "SKILL.md").read_bytes() == b"# omniweave\n\nv2\n"
    assert not list(_installed(tmp_path).parent.glob("*.tmp.*"))
    assert not list(_installed(tmp_path).parent.glob("*.old.*"))
    assert _skill(host.uninstall("global")).action == "removed"


def test_a_tree_the_user_edited_is_kept_named_and_not_replaced(tmp_path: Path) -> None:
    """10:1369's three facts: the expected digest, the observed one, the first differing path."""
    host = _host(tmp_path)
    _skill(host.install("global", _opts()))
    edited = _installed(tmp_path) / "references" / "actions.md"
    edited.write_bytes(b"mine\n")
    (tmp_path / "skills" / "omniweave" / "SKILL.md").write_bytes(b"v2\n")
    kept = _skill(host.install("global", _opts()))
    assert (kept.action, kept.code) == ("kept", HASH_MISMATCH)
    (tmp_path / "skills" / "omniweave" / "SKILL.md").write_bytes(ROUTER["SKILL.md"])
    undone = _skill(host.uninstall("global"))
    assert (undone.action, undone.code) == ("kept", HASH_MISMATCH)
    assert "first differing path references/actions.md" in undone.note
    assert f"observed {bundle_sha256(_installed(tmp_path))[0]}" in undone.note
    assert edited.read_bytes() == b"mine\n"


def test_an_identical_tree_already_there_is_recorded_as_not_ours_and_left(tmp_path: Path) -> None:
    """D454's rule for a value the user already had, applied to a directory."""
    host = _host(tmp_path)
    _bundle(_installed(tmp_path), ROUTER)
    before = _tree(tmp_path / "home")
    first = _skill(host.install("global", _opts()))
    assert (first.action, first.note) == (
        "unchanged",
        "already present with this digest; recorded as not ours",
    )
    undone = _skill(host.uninstall("global"))
    assert undone.action == "not-found"
    assert _tree(tmp_path / "home") == before


def test_with_no_row_only_this_releases_bundle_is_removed(tmp_path: Path) -> None:
    host = _host(tmp_path)
    _skill(host.install("global", _opts()))
    receipt_path(host.env.omniweave_home).unlink()
    undone = _skill(host.uninstall("global"))
    assert undone.action == "removed"
    assert "exactly this release's bundle" in undone.note
    other = _host(tmp_path / "second")
    _bundle(_installed(tmp_path / "second"), {"SKILL.md": b"someone else's\n"})
    assert _skill(other.uninstall("global")).action == "kept"


def test_a_linked_destination_is_theirs_at_install_and_uninstall(tmp_path: Path) -> None:
    host = _host(tmp_path)
    checkout = _bundle(tmp_path / "checkout", ROUTER)
    dest = _installed(tmp_path)
    dest.parent.mkdir(parents=True)
    try:
        dest.symlink_to(checkout, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot create a directory symlink")
    assert _skill(host.install("global", _opts())).action == "kept"
    assert _skill(host.uninstall("global")).action == "kept"
    assert (checkout / "SKILL.md").read_bytes() == ROUTER["SKILL.md"]


def test_a_tree_holding_a_link_is_not_removed_on_the_digests_word(tmp_path: Path) -> None:
    host = _host(tmp_path)
    _skill(host.install("global", _opts()))
    outside = _bundle(tmp_path / "outside", {"notes.md": b"mine\n"})
    try:
        (_installed(tmp_path) / "notes.md").symlink_to(outside / "notes.md")
    except OSError:
        pytest.skip("this account cannot create a symlink")
    undone = _skill(host.uninstall("global"))
    assert undone.action == "kept"
    assert "notes.md" in undone.note


def test_all_adds_every_bundle_with_a_skill_md(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _bundle(skills / "omniweave", ROUTER)
    _bundle(skills / "omniweave-pptx", {"SKILL.md": b"pptx\n"})
    _bundle(skills / "notes", {"README.md": b"not a bundle\n"})
    host = _host(tmp_path, skills_root=skills)
    result = host.install("global", _opts("all"))
    assert [one.path for one in result.actions if one.kind == "skill"] == [
        "~/.agents/skills/omniweave",
        "~/.agents/skills/omniweave-pptx",
    ]
    assert host.describe_paths("global")[-2:] == (
        "~/.agents/skills/omniweave",
        "~/.agents/skills/omniweave-pptx",
    )
    undone = host.uninstall("global")
    assert {one.path: one.action for one in undone.actions if one.kind == "skill"} == {
        "~/.agents/skills/omniweave": "removed",
        "~/.agents/skills/omniweave-pptx": "removed",
    }
    assert not (tmp_path / "home" / ".agents").exists()


def test_a_local_install_puts_the_bundle_under_the_project(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    host = _host(tmp_path, root=project)
    placed = _skill(host.install("local", _opts())).path
    assert placed == f"{project.as_posix()}/.agents/skills/omniweave"
    assert (project / ".agents" / "skills" / "omniweave" / "SKILL.md").is_file()
    _skill(host.uninstall("local"))
    assert _tree(project) == {}


def test_a_dry_run_copies_nothing(tmp_path: Path) -> None:
    host = _host(tmp_path)
    before = _tree(tmp_path)
    assert _skill(host.install("global", _opts(dry_run=True))).action == "created"
    assert _tree(tmp_path) == before


def test_none_writes_no_skill_and_removes_none(tmp_path: Path) -> None:
    host = _host(tmp_path)
    _skill(host.install("global", _opts()))
    result = host.install("global", _opts("none"))
    assert not [one for one in result.actions if one.kind == "skill"]
    assert (_installed(tmp_path) / "SKILL.md").is_file()


def test_print_config_names_the_skill_without_reading_the_bundle(tmp_path: Path) -> None:
    host = _host(tmp_path, skills_root=tmp_path / "nowhere")
    text = host.print_config("global")
    assert "# ~/.agents/skills/omniweave  dir  a copy of" in text
    assert not (tmp_path / "nowhere").exists()


def test_this_repositorys_bundle_is_refused_by_name_and_the_rest_installs(tmp_path: Path) -> None:
    """The measurement: `skills/omniweave/` has no `SKILL.md` until W7.6 generates it."""
    skills = REPO / "skills"
    assert (skills / "omniweave" / "references" / "actions.md").is_file()
    host = _host(tmp_path, skills_root=skills)
    result = host.install("global", InstallOptions(hooks="context", skills="core"))
    actions = {one.kind: one.action for one in result.actions}
    if (skills / "omniweave" / "SKILL.md").is_file():
        assert actions["skill"] == "created"
        return
    skill = _skill(result)
    assert skill.action == "kept"
    assert "has no SKILL.md: the router body is W7.6's (16:720)" in skill.note
    assert actions == {
        "mcp": "created",
        "permissions": "created",
        "instructions": "created",
        "hooks": "updated",
        "skill": "kept",
    }


def test_no_source_given_is_refused_by_name(tmp_path: Path) -> None:
    host = ClaudeCode(replace(_host(tmp_path).env, skills_root=None))
    skill = _skill(host.install("global", _opts()))
    assert (skill.action, skill.note) == ("kept", "no skill bundle source was given")


def test_a_bundle_with_a_file_held_open_is_left_whole_for_the_next_attempt(
    tmp_path: Path,
) -> None:
    """D465. On Windows an open handle stops the rename; nothing in the tree is deleted."""
    host = _host(tmp_path)
    _skill(host.install("global", _opts()))
    whole = _tree(_installed(tmp_path))
    with (_installed(tmp_path) / "SKILL.md").open("rb"):
        first = _skill(host.uninstall("global"))
        if first.action == "removed":
            assert not _installed(tmp_path).exists()
            return
        assert first.action == "kept"
        assert "nothing in it was deleted" in first.note
        assert _tree(_installed(tmp_path)) == whole
    second = _skill(host.uninstall("global"))
    assert second.action == "removed"
    assert not (tmp_path / "home" / ".agents").exists()
