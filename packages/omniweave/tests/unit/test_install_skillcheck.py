"""`ow skills ls | verify | check | hash`: the read-only half of 10:1429's row.

**The sharpest test is `test_plain_verify_never_sees_the_core_skill_ow_install_placed`.** 10:1389
says `verify` iterates the lock, and D490 keeps the core skill that `ow install --skills core`
placed out of the lock. So a plain `verify` finds nothing to check on a machine whose only skill is
the one every session loads, and `--all` is what reaches it (D493).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from omniweave.install import skills_lock
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.codex import Codex
from omniweave.install.engine import HostEnv
from omniweave.install.skillcheck import check, digests, ls, verify
from omniweave.install.skills_lock import Locked, lock_file
from omniweave.install.skillset import install
from omniweave.install.types import InstallOptions
from omniweave.install.verbs import OK, USAGE
from omniweave.skills.hash import ALGO, bundle_sha256

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
REPO = Path(__file__).resolve().parents[4]
ROUTER = {"SKILL.md": b"---\nname: omniweave\n---\nroute\n", "references/actions.md": b"catalog\n"}
DEMO = {"SKILL.md": b"---\nname: omniweave-demo\n---\ndemo\n"}
CORE_ONLY = InstallOptions(hooks="none", skills="core")


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


def _env(tmp: Path, *, skills_root: Path | None = None) -> HostEnv:
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
        windows=False,
        which=lambda _name: None,
        lock_wait_ms=0,
        skills_root=skills_root,
    )


def _agents(env: HostEnv) -> Path:
    return env.user_home / ".agents" / "skills"


def _source(tmp: Path, name: str = "omniweave") -> Path:
    return tmp / "skills" / name


# ---------------------------------------------------------------------------------------------
# hash.
# ---------------------------------------------------------------------------------------------


def test_hash_prints_every_shipped_bundles_full_digest(tmp_path: Path) -> None:
    env = _env(tmp_path)
    outcome = digests(env)
    assert outcome.exit_code == OK
    assert outcome.lines[0] == f"  {ALGO}"
    for line, name in zip(outcome.lines[1:], ("omniweave", "omniweave-demo"), strict=True):
        digest, files, size = bundle_sha256(_source(tmp_path, name))
        assert line == f"  {name:<24} {digest}  {files} files  {size} bytes"
        assert len(digest) == 64


def test_hash_over_this_repositorys_skills_is_the_router_alone() -> None:
    names = [line.split()[0] for line in digests(_repo_env()).lines[1:]]
    assert names == ["omniweave"]


def _repo_env() -> HostEnv:
    return HostEnv(
        omniweave_home=REPO / ".nonexistent-owhome",
        user_home=REPO / ".nonexistent-home",
        clock=_Clock(),
        pid=PID,
        launch=("python",),
        skills_root=REPO / "skills",
    )


def test_hash_with_no_bundles_is_refused(tmp_path: Path) -> None:
    assert digests(_env(tmp_path, skills_root=tmp_path / "none")).exit_code == USAGE


# ---------------------------------------------------------------------------------------------
# ls.
# ---------------------------------------------------------------------------------------------


def test_ls_names_each_copy_and_the_record_it_is_on(tmp_path: Path) -> None:
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    install(["omniweave-demo"], env)
    (_agents(env) / "omniweave-demo" / "SKILL.md").write_bytes(b"edited\n")
    lines = ls(env).lines
    assert lines[0].startswith("  omniweave                core      ")
    assert lines[0].endswith("~/.agents/skills/omniweave (claude-code receipt)")
    assert lines[1].endswith("~/.agents/skills/omniweave-demo (skills-lock, differs)")


def test_ls_says_not_installed_and_lists_a_lock_entry_this_release_does_not_ship(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    orphan = Locked("omniweave-gone", "b" * 64, 1, 5, ("~/.agents/skills/omniweave-gone",))
    skills_lock.write(env.omniweave_home, {"omniweave-gone": orphan}, release="0", pid=PID)
    lines = ls(env).lines
    assert lines[0].endswith("not installed")
    assert lines[-1].endswith("not shipped; lock: ~/.agents/skills/omniweave-gone")


# ---------------------------------------------------------------------------------------------
# verify.
# ---------------------------------------------------------------------------------------------


def test_verify_with_nothing_recorded_says_so_and_exits_0(tmp_path: Path) -> None:
    outcome = verify(_env(tmp_path))
    assert outcome.exit_code == OK
    assert outcome.lines == ("  nothing to verify: skills-lock.json records no installed skill",)


def test_plain_verify_never_sees_the_core_skill_ow_install_placed(tmp_path: Path) -> None:
    """D493. Claude Code's and Codex's receipt rows name one tree, so it is one line."""
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    Codex(env).install("global", CORE_ONLY)
    assert verify(env).lines[0].startswith("  nothing to verify")
    every = verify(env, every=True)
    assert every.exit_code == OK
    (line,) = every.lines
    assert "claude-code receipt, codex receipt" in line
    assert line.endswith(" ok")


def test_verify_names_the_four_facts_of_a_mismatch(tmp_path: Path) -> None:
    """10:1368-1370: the skill, the expected and observed digests, the first differing path."""
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    expected = bundle_sha256(_source(tmp_path))[0]
    assert verify(env).exit_code == OK
    (_agents(env) / "omniweave" / "references" / "actions.md").write_bytes(b"edited\n")
    observed = bundle_sha256(_agents(env) / "omniweave")[0]
    outcome = verify(env)
    assert outcome.exit_code == USAGE
    (line,) = outcome.lines
    assert line.endswith(
        f"OW-A-031 OW_SKILL_HASH_MISMATCH omniweave: expected {expected}, observed {observed}, "
        "first differing path references/actions.md"
    )


def test_verify_names_no_path_when_the_source_is_not_the_recorded_bundle(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    (_agents(env) / "omniweave" / "SKILL.md").write_bytes(b"edited\n")
    (_source(tmp_path) / "SKILL.md").write_bytes(b"a newer release\n")
    (line,) = verify(env).lines
    assert "first differing path" not in line


def test_verify_reports_a_missing_directory(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    shutil.rmtree(_agents(env) / "omniweave")
    outcome = verify(env)
    assert outcome.exit_code == USAGE
    assert outcome.lines[0].endswith("MISSING -- no directory")


def test_verify_refuses_an_unreadable_lock(tmp_path: Path) -> None:
    env = _env(tmp_path)
    lock_file(env.omniweave_home).parent.mkdir(parents=True)
    lock_file(env.omniweave_home).write_bytes(b"[]")
    assert verify(env).exit_code == USAGE


# ---------------------------------------------------------------------------------------------
# check.
# ---------------------------------------------------------------------------------------------


def test_check_fails_when_no_directory_holds_the_core_skill(tmp_path: Path) -> None:
    outcome = check(_env(tmp_path))
    assert outcome.exit_code == USAGE
    assert (
        outcome.lines[0]
        == "  omniweave                core      MISSING -- run `ow install --skills core`"
    )


def test_a_missing_lock_warns_instead_of_saying_up_to_date(tmp_path: Path) -> None:
    """10:1380-1382, and a missing on-demand skill is not out of date (10:1197-1199)."""
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    outcome = check(env)
    assert outcome.exit_code == OK
    assert outcome.lines[0].endswith("core      up to date")
    assert outcome.lines[1].startswith("  lock_missing: true -- ")
    assert outcome.lines[-1] == "core skill up to date; see the warnings above"
    assert not any("omniweave-demo" in line for line in outcome.lines)


def test_everything_current_is_up_to_date(tmp_path: Path) -> None:
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    install(["omniweave-demo"], env)
    outcome = check(env)
    assert outcome.exit_code == OK
    assert outcome.lines[1] == "  omniweave-demo           on-demand up to date"
    assert outcome.lines[-1] == "up to date"


def test_a_stale_core_skill_fails_and_names_the_verb_that_owns_it(tmp_path: Path) -> None:
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    (_source(tmp_path) / "SKILL.md").write_bytes(b"a newer router\n")
    outcome = check(env)
    assert outcome.exit_code == USAGE
    assert "STALE -- " in outcome.lines[0]
    assert outcome.lines[0].endswith("(claude-code receipt); run `ow install --skills core`")


def test_a_stale_core_skill_the_lock_placed_names_ow_skills_install(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _agents(env).mkdir(parents=True)
    install(["omniweave"], env)
    (_source(tmp_path) / "SKILL.md").write_bytes(b"a newer router\n")
    line = check(env).lines[0]
    assert line.endswith("(skills-lock); run `ow skills install omniweave`")
    assert install(["omniweave"], env).exit_code == OK
    assert check(env).exit_code == OK


def test_a_hand_edited_core_skill_is_modified_not_stale(tmp_path: Path) -> None:
    """Measured end to end: this was called stale and told to run `ow install`, which keeps it."""
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    (_agents(env) / "omniweave" / "SKILL.md").write_bytes(b"my edit\n")
    outcome = check(env)
    assert outcome.exit_code == USAGE
    line = outcome.lines[0]
    assert "core      OW-A-031 MODIFIED -- " in line
    assert line.endswith(
        "(claude-code receipt); no record wrote these bytes, so move it aside and run "
        "`ow install --skills core`"
    )
    (skill,) = [
        one for one in ClaudeCode(env).install("global", CORE_ONLY).actions if one.kind == "skill"
    ]
    assert skill.action == "kept", "which is why the fix is not `ow install` alone"


def test_a_core_skill_on_no_record_says_so(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _bundle(_agents(env) / "omniweave", {"SKILL.md": b"copied by hand\n"})
    line = check(env).lines[0]
    assert line.endswith(
        "(unrecorded); it is on no record, so move it aside and run `ow install --skills core`"
    )


def test_an_outdated_or_orphaned_on_demand_skill_is_reported_and_does_not_fail(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    install(["omniweave-demo"], env)
    (_source(tmp_path, "omniweave-demo") / "SKILL.md").write_bytes(b"newer\n")
    lock = dict(skills_lock.read(env.omniweave_home).skills)
    lock["omniweave-gone"] = Locked("omniweave-gone", "b" * 64, 1, 5, ("~/x",))
    lock["someone-else"] = Locked("someone-else", "c" * 64, 1, 5, ("~/y",), source="their/skills")
    skills_lock.write(env.omniweave_home, lock, release="0", pid=PID)
    outcome = check(env)
    assert outcome.exit_code == OK
    text = outcome.text()
    assert "omniweave-demo           on-demand update available -- run `ow skills install" in text
    assert "omniweave-gone           on-demand removed -- this release no longer publishes" in text
    assert "someone-else" not in text
    assert outcome.lines[-1] == "core skill up to date; see the warnings above"


def test_check_check_is_the_routers_byte_diff(tmp_path: Path) -> None:
    """10:1371. The fixture's router is not the render and has no blessed copy: two failures."""
    env = _env(tmp_path)
    ClaudeCode(env).install("global", CORE_ONLY)
    assert check(env).exit_code == OK
    outcome = check(env, byte_diff=True)
    assert outcome.exit_code == USAGE
    assert "  --check: skills/omniweave/SKILL.md differs from the render (shipped copy)" in (
        outcome.lines
    )
    assert "  --check: skills/expected/omniweave/SKILL.md is missing (blessed copy)" in (
        outcome.lines
    )


def test_check_check_passes_on_this_repositorys_skills(tmp_path: Path) -> None:
    env = _env(tmp_path, skills_root=REPO / "skills")
    ClaudeCode(env).install("global", CORE_ONLY)
    outcome = check(env, byte_diff=True)
    assert "  --check: skills/expected/ matches the render" in outcome.lines
    assert outcome.exit_code == OK
