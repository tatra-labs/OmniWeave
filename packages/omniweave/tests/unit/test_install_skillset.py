"""`ow skills install | remove` and `skills-lock.json`: two ledgers, and never both for one tree.

**The sharpest test is `test_uninstalls_rederivation_leaves_a_tree_the_skills_lock_owns`.** With
no receipt row, `ow uninstall` re-derives (10:1758-1759), and a tree equal to this release's
bundle is removed on the digest's word (D455). With D490's check switched off, that is the tree
`ow skills install` just placed: it goes, and the lock is left naming a directory that is not there.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave.install import skills_lock
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.engine import HostEnv
from omniweave.install.receipt import take_lock
from omniweave.install.registry import BUILT, build
from omniweave.install.skills_lock import SERIAL_LOCK, Locked, claimant, lock_file
from omniweave.install.skillset import (
    NOT_FOUND,
    candidates,
    discovered,
    install,
    remove,
    scope_of_dir,
    shipped,
    update,
)
from omniweave.install.types import InstallOptions
from omniweave.install.verbs import OK, USAGE
from omniweave.skills.hash import ALGO, bundle_sha256

if TYPE_CHECKING:
    from omniweave.install.verbs import Outcome

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
REPO = Path(__file__).resolve().parents[4]
ROUTER = {"SKILL.md": b"---\nname: omniweave\n---\nroute\n", "references/actions.md": b"catalog\n"}
DEMO = {"SKILL.md": b"---\nname: omniweave-demo\n---\ndemo\n"}


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


def _env(tmp: Path, *, skills_root: Path | None = None, project: Path | None = None) -> HostEnv:
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    if skills_root is None:
        skills_root = tmp / "skills"
        _bundle(skills_root / "omniweave", ROUTER)
        _bundle(skills_root / "omniweave-demo", DEMO)
    return HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=("python", "-m", "omniweave"),
        project_root=project,
        windows=False,
        which=lambda _name: None,
        lock_wait_ms=0,
        skills_root=skills_root,
    )


def _agents(env: HostEnv) -> Path:
    return env.user_home / ".agents" / "skills"


def _cursor(env: HostEnv) -> Path:
    return env.user_home / ".cursor" / "skills"


def _lock(env: HostEnv) -> dict[str, object]:
    return json.loads(lock_file(env.omniweave_home).read_bytes())


def _tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        one.relative_to(root).as_posix(): one.read_bytes()
        for one in root.rglob("*")
        if one.is_file()
    }


def _actions(outcome: Outcome) -> list[str]:
    return [line for line in outcome.lines if line.startswith("  ~") or line.startswith("  /")]


# ---------------------------------------------------------------------------------------------
# 10:1399-1403: the scope rule, and the order that is the point.
# ---------------------------------------------------------------------------------------------


def test_a_directory_under_the_working_directory_is_project_even_under_home(tmp_path: Path) -> None:
    """10:1400: *"(EVEN when cwd is itself under $HOME)"* -- reversing the order is the defect."""
    home = tmp_path / "home"
    project = home / "work" / "proj"
    assert scope_of_dir(project / ".claude" / "skills", project, home) == "project"
    assert scope_of_dir(home / ".agents" / "skills", project, home) == "global"
    assert scope_of_dir(tmp_path / "elsewhere" / "skills", project, home) == "project"
    assert scope_of_dir(home / ".agents" / "skills", None, home) == "global"


def test_a_sibling_home_with_a_longer_name_is_not_under_the_shorter(tmp_path: Path) -> None:
    """10:1403: *"so /home/user2 does not match /home/user"*."""
    user, user2 = tmp_path / "user", tmp_path / "user2"
    assert scope_of_dir(user2 / ".agents" / "skills", None, user) == "project"
    assert scope_of_dir(user / ".agents" / "skills", None, user) == "global"


# ---------------------------------------------------------------------------------------------
# 10:1393: where a bundle goes. D491.
# ---------------------------------------------------------------------------------------------


def test_every_built_host_names_its_skills_directory(tmp_path: Path) -> None:
    env = _env(tmp_path, project=tmp_path / "proj")
    for target in BUILT:
        host = build(target, env)
        assert host.skills_dir("global").is_relative_to(env.user_home), target
        assert host.skills_dir("local").is_relative_to(tmp_path / "proj"), target


def test_claude_code_and_codex_share_one_destination(tmp_path: Path) -> None:
    env = _env(tmp_path, project=tmp_path / "proj")
    rows = {one.path: (one.scope, one.hosts) for one in candidates(env)}
    assert rows[_agents(env)] == ("global", ("claude-code", "codex"))
    assert rows[_cursor(env)] == ("global", ("cursor",))
    assert rows[tmp_path / "proj" / ".agents" / "skills"] == ("project", ("claude-code", "codex"))
    assert len(rows) == 4


def test_a_global_only_caller_has_no_project_candidates(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert {one.scope for one in candidates(env)} == {"global"}


def test_only_the_directories_that_exist_are_discovered(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert discovered(env) == ()
    _cursor(env).mkdir(parents=True)
    assert [one.path for one in discovered(env)] == [_cursor(env)]


def test_the_shipped_names_are_the_bundles_with_a_skill_md(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "skills" / "expected" / "omniweave").mkdir(parents=True)
    assert shipped(env.skills_root) == ("omniweave", "omniweave-demo")
    assert shipped(REPO / "skills") == ("omniweave",)
    assert shipped(None) == ()


# ---------------------------------------------------------------------------------------------
# ow skills install.
# ---------------------------------------------------------------------------------------------


def test_an_unshipped_name_is_exit_2_and_writes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    outcome = install(["omniweave-pptx", "omniweave"], env)
    assert outcome.exit_code == NOT_FOUND == 2
    assert (
        "ships no skill named omniweave-pptx; it ships omniweave, omniweave-demo" in outcome.text()
    )
    assert not (_agents(env) / "omniweave").exists()
    assert not env.omniweave_home.exists()


def test_no_skills_directory_is_refused_with_the_command_that_makes_one(tmp_path: Path) -> None:
    env = _env(tmp_path)
    outcome = install(["omniweave"], env)
    assert outcome.exit_code == USAGE
    assert "~/.agents/skills, ~/.cursor/skills" in outcome.text()
    assert "`ow install --skills core`" in outcome.text()


def test_no_bundles_at_all_is_refused(tmp_path: Path) -> None:
    env = _env(tmp_path, skills_root=tmp_path / "nothing")
    assert install(["omniweave"], env).exit_code == USAGE


def test_install_places_in_every_discovered_directory_and_locks_what_it_placed(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    _cursor(env).mkdir(parents=True)
    outcome = install(["omniweave-demo"], env)
    assert outcome.exit_code == OK, outcome.text()
    source = tmp_path / "skills" / "omniweave-demo"
    digest, files, size = bundle_sha256(source)
    for root in (_agents(env), _cursor(env)):
        assert bundle_sha256(root / "omniweave-demo")[0] == digest
    assert _lock(env) == {
        "version": 1,
        "release": env.release,
        "algo": ALGO,
        "skills": {
            "omniweave-demo": {
                "source": "omniweave/skills",
                "source_type": "path",
                "skill_path": "skills/omniweave-demo",
                "bundle_sha256": digest,
                "files": files,
                "bytes": size,
                "installed_to": [
                    "~/.agents/skills/omniweave-demo",
                    "~/.cursor/skills/omniweave-demo",
                ],
                "tier": "on-demand",
            }
        },
    }
    assert [line.split()[-1] for line in _actions(outcome)] == ["created", "created"]
    assert "  global  ~/.agents/skills  (claude-code, codex)" in outcome.lines


def test_a_second_install_is_unchanged_and_rewrites_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    assert install(["omniweave"], env).exit_code == OK
    before = lock_file(env.omniweave_home).read_bytes()
    again = install(["omniweave", "omniweave"], env)
    assert again.exit_code == OK
    assert [line.split()[-1] for line in _actions(again)] == ["unchanged"]
    assert lock_file(env.omniweave_home).read_bytes() == before
    assert _lock(env)["skills"]["omniweave"]["tier"] == "core"  # type: ignore[index]


def test_a_changed_source_updates_a_directory_the_lock_placed(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave-demo"], env)
    source = tmp_path / "skills" / "omniweave-demo"
    (source / "SKILL.md").write_bytes(DEMO["SKILL.md"] + b"a second line\n")
    outcome = install(["omniweave-demo"], env)
    assert [line.split()[-1] for line in _actions(outcome)] == ["updated"]
    assert _tree(_agents(env) / "omniweave-demo") == _tree(source)
    entry = _lock(env)["skills"]["omniweave-demo"]  # type: ignore[index]
    assert entry["bundle_sha256"] == bundle_sha256(source)[0]


def test_a_directory_already_holding_the_bytes_is_unchanged_and_not_claimed(
    tmp_path: Path,
) -> None:
    """D490: whoever put it there takes it away, so the lock does not list it."""
    env = _env(tmp_path)
    _bundle(_agents(env) / "omniweave-demo", DEMO)
    outcome = install(["omniweave-demo"], env)
    assert outcome.exit_code == OK
    assert "unchanged -- already present with this digest; not recorded" in outcome.text()
    assert not lock_file(env.omniweave_home).exists()


def test_a_foreign_tree_is_kept_and_the_exit_says_so(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _bundle(_agents(env) / "omniweave-demo", {"SKILL.md": b"someone else's\n"})
    outcome = install(["omniweave-demo"], env)
    assert outcome.exit_code == USAGE
    assert "kept -- the directory is not the bundle" in outcome.text()
    assert (_agents(env) / "omniweave-demo" / "SKILL.md").read_bytes() == b"someone else's\n"


def test_a_modified_tree_the_lock_placed_is_kept_with_ow_a_031(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave-demo"], env)
    placed = _agents(env) / "omniweave-demo" / "SKILL.md"
    placed.write_bytes(b"my edit\n")
    outcome = install(["omniweave-demo"], env)
    assert outcome.exit_code == USAGE
    assert "kept -- modified since install; expected " in outcome.text()
    assert placed.read_bytes() == b"my edit\n"
    assert _lock(env)["skills"]["omniweave-demo"]["installed_to"] == [  # type: ignore[index]
        "~/.agents/skills/omniweave-demo"
    ]


def test_a_tree_the_install_receipt_created_is_left_to_ow_install(tmp_path: Path) -> None:
    """D490's first half: `ow install --skills core` created it, so `ow uninstall` removes it."""
    env = _env(tmp_path)
    host = ClaudeCode(env)
    host.install("global", InstallOptions(hooks="none", skills="core"))
    outcome = install(["omniweave"], env)
    assert outcome.exit_code == OK
    assert "the install receipt names it; `ow uninstall` removes it (D490)" in outcome.text()
    assert not lock_file(env.omniweave_home).exists()
    (skill,) = [one for one in host.uninstall("global").actions if one.kind == "skill"]
    assert skill.action == "removed"


def test_an_older_receipt_tree_is_kept_for_ow_install_to_update(tmp_path: Path) -> None:
    env = _env(tmp_path)
    ClaudeCode(env).install("global", InstallOptions(hooks="none", skills="core"))
    router = tmp_path / "skills" / "omniweave" / "SKILL.md"
    router.write_bytes(router.read_bytes() + b"newer\n")
    outcome = install(["omniweave"], env)
    assert outcome.exit_code == USAGE
    assert "the install receipt names it; `ow install` updates it (D490)" in outcome.text()


def test_uninstalls_rederivation_leaves_a_tree_the_skills_lock_owns(tmp_path: Path) -> None:
    """D490's second half. No receipt row, and the tree is exactly this release's bundle."""
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    assert install(["omniweave"], env).exit_code == OK
    placed = _agents(env) / "omniweave"
    (skill,) = [one for one in ClaudeCode(env).uninstall("global").actions if one.kind == "skill"]
    assert skill.action == "not-found"
    assert "skills-lock.json names it; `ow skills remove omniweave` removes it" in skill.note
    assert bundle_sha256(placed)[0] == bundle_sha256(tmp_path / "skills" / "omniweave")[0]


def test_an_unreadable_lock_refuses_every_write_and_claims_the_unknown(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    path = lock_file(env.omniweave_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{not json")
    outcome = install(["omniweave"], env)
    assert outcome.exit_code == USAGE
    assert "is not JSON" in outcome.text()
    assert path.read_bytes() == b"{not json"
    assert not (_agents(env) / "omniweave").exists()
    assert "whether it owns this is unknown" in claimant(
        env.omniweave_home, _agents(env) / "omniweave", env.user_home
    )
    assert remove(["omniweave"], env, yes=True).exit_code == USAGE


def test_a_held_skills_lock_is_refused_by_name(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    held = take_lock(env.omniweave_home, clock=env.clock, wait_ms=0, file=SERIAL_LOCK)
    assert held.lock is not None
    with held.lock:
        outcome = install(["omniweave"], env)
    assert outcome.exit_code == USAGE
    assert "OW-A-033: another ow skills install, remove or update holds" in outcome.text()
    assert SERIAL_LOCK in outcome.text()
    assert not (_agents(env) / "omniweave").exists()


def test_a_linked_destination_is_not_written_through(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    checkout = _bundle(tmp_path / "checkout", {"SKILL.md": b"a checkout\n"})
    try:
        (_agents(env) / "omniweave").symlink_to(checkout, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot create a directory symlink")
    outcome = install(["omniweave"], env)
    assert "kept -- is a link" in outcome.text()
    assert (checkout / "SKILL.md").read_bytes() == b"a checkout\n"


# ---------------------------------------------------------------------------------------------
# ow skills remove.
# ---------------------------------------------------------------------------------------------


def test_remove_prints_its_plan_and_without_yes_removes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave-demo"], env)
    outcome = remove(["omniweave-demo"], env)
    assert outcome.exit_code == USAGE
    assert outcome.lines[0] == "plan"
    assert outcome.lines[1].endswith(" remove")
    assert outcome.lines[-1].startswith("not confirmed; nothing removed")
    assert (_agents(env) / "omniweave-demo").is_dir()
    declined = remove(["omniweave-demo"], env, confirm=lambda _question: False)
    assert declined.exit_code == USAGE


def test_install_then_remove_leaves_every_directory_as_it_was(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    _cursor(env).mkdir(parents=True)
    before = _tree(tmp_path / "home")
    install(["omniweave", "omniweave-demo"], env)
    outcome = remove(["omniweave-demo", "omniweave"], env, confirm=lambda _question: True)
    assert outcome.exit_code == OK, outcome.text()
    assert [line.split()[-1] for line in _actions(outcome)][-4:] == ["removed"] * 4
    assert _tree(tmp_path / "home") == before
    assert sorted(p.name for p in _agents(env).iterdir()) == []
    assert not lock_file(env.omniweave_home).exists()


def test_a_name_the_lock_does_not_have_is_not_found(tmp_path: Path) -> None:
    env = _env(tmp_path)
    outcome = remove(["omniweave"], env, yes=True)
    assert outcome.exit_code == NOT_FOUND
    assert "  omniweave: not-found -- skills-lock.json has no entry for it" in outcome.lines


def test_a_modified_tree_is_kept_named_and_stays_in_the_lock(tmp_path: Path) -> None:
    """10:1368-1370's three facts: both digests and the first differing path."""
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    _cursor(env).mkdir(parents=True)
    install(["omniweave"], env)
    (_cursor(env) / "omniweave" / "references" / "actions.md").write_bytes(b"edited\n")
    outcome = remove(["omniweave"], env, yes=True)
    assert outcome.exit_code == USAGE
    text = outcome.text()
    assert "modified since install; expected " in text
    assert "first differing path references/actions.md" in text
    assert not (_agents(env) / "omniweave").exists()
    assert _lock(env)["skills"]["omniweave"]["installed_to"] == [  # type: ignore[index]
        "~/.cursor/skills/omniweave"
    ]


def test_a_listed_tree_ow_install_has_since_created_is_left_to_ow_uninstall(
    tmp_path: Path,
) -> None:
    """The lock is stale -- the user deleted the tree -- and `ow install` created it again."""
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    shutil.rmtree(_agents(env) / "omniweave")
    ClaudeCode(env).install("global", InstallOptions(hooks="none", skills="core"))
    outcome = remove(["omniweave"], env, yes=True)
    assert outcome.exit_code == OK
    assert "not-found -- the install receipt names it; `ow uninstall` removes it" in outcome.text()
    assert (_agents(env) / "omniweave" / "SKILL.md").is_file()
    assert not lock_file(env.omniweave_home).exists()


def test_a_directory_already_gone_is_forgotten(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    shutil.rmtree(_agents(env) / "omniweave")
    outcome = remove(["omniweave"], env, yes=True)
    assert outcome.exit_code == OK
    assert "not-found -- no directory" in outcome.text()
    assert not lock_file(env.omniweave_home).exists()


# ---------------------------------------------------------------------------------------------
# The lock file.
# ---------------------------------------------------------------------------------------------


def _locked(name: str = "omniweave") -> Locked:
    return Locked(name, "a" * 64, 2, 40, ("~/.agents/skills/omniweave",), f"skills/{name}")


def test_the_lock_round_trips(tmp_path: Path) -> None:
    skills = {"omniweave": _locked(), "omniweave-pptx": _locked("omniweave-pptx")}
    assert skills_lock.write(tmp_path, skills, release="0.1.0", pid=PID) == ""
    read = skills_lock.read(tmp_path)
    assert read.state == "read"
    assert dict(read.skills) == skills
    assert list(_lock_document(tmp_path)["skills"]) == ["omniweave", "omniweave-pptx"]


def _lock_document(home: Path) -> dict[str, dict[str, object]]:
    return json.loads(lock_file(home).read_bytes())


@pytest.mark.parametrize(
    ("change", "state"),
    [
        ({"version": 2}, "newer"),
        ({"algo": "sha256-bundle-2"}, "unparseable"),
        ({"version": "1"}, "unparseable"),
    ],
)
def test_a_lock_this_release_cannot_rewrite_is_not_writable(
    tmp_path: Path, change: dict[str, object], state: str
) -> None:
    skills_lock.write(tmp_path, {"omniweave": _locked()}, release="0.1.0", pid=PID)
    document = {**_lock_document(tmp_path), **change}
    lock_file(tmp_path).write_text(json.dumps(document), "utf-8")
    read = skills_lock.read(tmp_path)
    assert (read.state, read.writable) == (state, False)


@pytest.mark.parametrize(
    "field", ["bundle_sha256", "installed_to", "files", "skill_path", "source", "source_type"]
)
def test_a_malformed_entry_makes_the_lock_unparseable(tmp_path: Path, field: str) -> None:
    skills_lock.write(tmp_path, {"omniweave": _locked()}, release="0.1.0", pid=PID)
    document = _lock_document(tmp_path)
    document["skills"]["omniweave"][field] = True  # type: ignore[index]
    lock_file(tmp_path).write_text(json.dumps(document), "utf-8")
    assert skills_lock.read(tmp_path).state == "unparseable"


def test_the_last_skill_removed_deletes_the_lock(tmp_path: Path) -> None:
    skills_lock.write(tmp_path, {"omniweave": _locked()}, release="0.1.0", pid=PID)
    assert skills_lock.write(tmp_path, {}, release="0.1.0", pid=PID) == ""
    assert not lock_file(tmp_path).exists()


# ---------------------------------------------------------------------------------------------
# ow skills update.
# ---------------------------------------------------------------------------------------------

GONE = {"SKILL.md": b"---\nname: omniweave-gone\n---\nan older release's skill\n"}


def _orphan(env: HostEnv, where: Path, *, source: str = "omniweave/skills") -> Path:
    """A bundle this release no longer ships, placed and recorded as an older release would have."""
    tree = _bundle(where / "omniweave-gone", GONE)
    digest, files, size = bundle_sha256(tree)
    stored = (
        tree.relative_to(env.user_home).as_posix() if tree.is_relative_to(env.user_home) else ""
    )
    shown = f"~/{stored}" if stored else tree.as_posix()
    lock = dict(skills_lock.read(env.omniweave_home).skills)
    lock["omniweave-gone"] = Locked(
        "omniweave-gone", digest, files, size, (shown,), "skills/omniweave-gone", source
    )
    skills_lock.write(env.omniweave_home, lock, release="0", pid=PID)
    return tree


def test_update_refreshes_a_stale_entry_and_a_second_run_is_unchanged(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    _cursor(env).mkdir(parents=True)
    install(["omniweave-demo"], env)
    source = tmp_path / "skills" / "omniweave-demo"
    (source / "SKILL.md").write_bytes(DEMO["SKILL.md"] + b"newer\n")
    outcome = update(env)
    assert outcome.exit_code == OK, outcome.text()
    assert [line.split()[-1] for line in _actions(outcome)] == ["updated", "updated"]
    for root in (_agents(env), _cursor(env)):
        assert bundle_sha256(root / "omniweave-demo") == bundle_sha256(source)
    entry = _lock(env)["skills"]["omniweave-demo"]  # type: ignore[index]
    assert entry["bundle_sha256"] == bundle_sha256(source)[0]
    before = lock_file(env.omniweave_home).read_bytes()
    again = update(env)
    assert [line.split()[-1] for line in _actions(again)] == ["unchanged", "unchanged"]
    assert lock_file(env.omniweave_home).read_bytes() == before


def test_update_forgets_a_directory_that_is_gone_and_does_not_recreate_it(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave-demo"], env)
    shutil.rmtree(_agents(env) / "omniweave-demo")
    outcome = update(env)
    assert outcome.exit_code == OK
    assert "not-found -- no directory; forgotten, not reinstalled" in outcome.text()
    assert not (_agents(env) / "omniweave-demo").exists()
    assert not lock_file(env.omniweave_home).exists()


def test_update_keeps_a_modified_copy_and_exits_1(tmp_path: Path) -> None:
    """15:1530 names `update` as D-17's fix for a hash mismatch; it does not overwrite one. D499."""
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave-demo"], env)
    placed = _agents(env) / "omniweave-demo" / "SKILL.md"
    placed.write_bytes(b"my edit\n")
    outcome = update(env)
    assert outcome.exit_code == USAGE
    assert "kept -- modified since install" in outcome.text()
    assert placed.read_bytes() == b"my edit\n"


def test_update_prunes_what_this_release_no_longer_ships(tmp_path: Path) -> None:
    """10:1376-1377: attributed to omniweave/skills and no longer published."""
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    tree = _orphan(env, _agents(env))
    outcome = update(env)
    assert outcome.exit_code == OK, outcome.text()
    assert "removed -- this release no longer publishes it (10:1377)" in outcome.text()
    assert not tree.exists()
    assert list(_lock(env)["skills"]) == ["omniweave"]  # type: ignore[call-overload]


def test_a_modified_orphan_is_kept(tmp_path: Path) -> None:
    env = _env(tmp_path)
    tree = _orphan(env, _agents(env))
    (tree / "SKILL.md").write_bytes(b"mine now\n")
    outcome = update(env)
    assert outcome.exit_code == USAGE
    assert tree.is_dir()
    assert "omniweave-gone" in _lock(env)["skills"]  # type: ignore[operator]


def test_an_orphan_under_neither_the_project_nor_the_home_is_not_pruned(tmp_path: Path) -> None:
    """10:1402: *"never prune globally for an unknown path"*."""
    env = _env(tmp_path, project=tmp_path / "proj")
    (tmp_path / "proj").mkdir()
    tree = _orphan(env, tmp_path / "elsewhere" / ".agents" / "skills")
    outcome = update(env)
    assert outcome.exit_code == USAGE
    assert "under neither this project nor the home, so not pruned from here" in outcome.text()
    assert tree.is_dir()
    inside = _env(tmp_path, project=tmp_path / "elsewhere")
    assert update(inside).exit_code == OK
    assert not tree.exists()


def test_update_never_touches_an_entry_from_another_source(tmp_path: Path) -> None:
    env = _env(tmp_path)
    tree = _orphan(env, _agents(env), source="their/skills")
    outcome = update(env)
    assert outcome.exit_code == OK
    assert outcome.lines == (
        "  omniweave-gone: left alone -- attributed to their/skills (10:1378)",
    )
    assert tree.is_dir()


def test_update_with_no_lock_writes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    outcome = update(env)
    assert outcome.exit_code == OK
    assert outcome.lines[0].startswith("  lock_missing: true -- ")
    assert not env.omniweave_home.joinpath("skills-lock.json").exists()


def test_update_refuses_an_unreadable_lock_and_a_held_one(tmp_path: Path) -> None:
    env = _env(tmp_path)
    path = lock_file(env.omniweave_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{")
    assert update(env).exit_code == USAGE
    path.unlink()
    held = take_lock(env.omniweave_home, clock=env.clock, wait_ms=0, file=SERIAL_LOCK)
    assert held.lock is not None
    with held.lock:
        assert "OW-A-033" in update(env).text()
