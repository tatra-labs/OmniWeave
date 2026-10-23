"""`ow doctor`'s three project rows: D-06, D-13 and D-17. D956.

Each row is asked of a configuration `load()` resolved from a temp project, with today's date
handed in where the row reads it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omniweave.doctor import project
from omniweave.route.policy import POLICY_D
from omniweave_core.config import load

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.config import Config

CORPUS = '[corpora.docs]\npath = ".omniweave/docs.owstore"\n[serve]\ndefault_corpus = "docs"\n'


def _config(project_dir: Path, text: str = CORPUS) -> Config:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "omniweave.toml").write_text(text, encoding="utf-8")
    return load(cwd=project_dir, env={"OMNIWEAVE_HOME": str(project_dir.parent / "home")})


# --- D-06 -----------------------------------------------------------------------------------


def test_d06_the_shipped_policy_warns_only_for_the_rule_that_expects_its_driver_absent(
    tmp_path: Path,
) -> None:
    """05:1622-1625: `fields.extract`'s `expect_unavailable` makes `parse.fields.lift`'s absence a
    warning naming the rule, so a fresh install does not fail D-06."""
    root = tmp_path / "p"
    (found,) = project.check_named_drivers(_config(root), project_root=root)
    assert found.severity == "warning"
    assert found.detail.startswith("parse.fields.lift is named by rule fields.extract")
    assert found.fix == "add parse.fields.lift to [drivers] enabled to serve that rule's lane"


def test_d06_a_project_rule_naming_a_driver_not_enabled_fails(tmp_path: Path) -> None:
    root = tmp_path / "p"
    config = _config(root)
    (root / POLICY_D).mkdir(parents=True)
    (root / POLICY_D / "10-mine.toml").write_text(
        'surface = "route"\n\n[[rule]]\nid = "mine.text"\nrung = "DECODE"\n'
        'when = { "unit.format" = { in = ["txt"] } }\n'
        'then = { driver = "parse.text.mine", terminal = true }\n',
        encoding="utf-8",
    )
    failed = [
        one
        for one in project.check_named_drivers(config, project_root=root)
        if one.severity == "error"
    ]
    assert [one.detail for one in failed] == [
        "parse.text.mine is named by rule mine.text and is not in [drivers] enabled (INV-5)"
    ]
    assert failed[0].fix == "add parse.text.mine to [drivers] enabled, or remove what names it"


def test_d06_a_pass_not_enabled_fails_and_everything_enabled_is_ok(tmp_path: Path) -> None:
    root = tmp_path / "p"
    text = CORPUS + '[graph.passes]\nenable = ["derive.not.enabled"]\n'
    failed = [
        one
        for one in project.check_named_drivers(_config(root, text), project_root=root)
        if one.severity == "error"
    ]
    assert [one.detail for one in failed] == [
        "derive.not.enabled is named by [graph.passes] enable and is not in [drivers] enabled "
        "(INV-5)"
    ]
    enabled = '[drivers]\nenabled = ["parse.fields.lift", "parse.office.anydoc", '
    text = (
        CORPUS + enabled + '"parse.page.olmocr", "parse.pdf.pdfium", "parse.text.builtin"]\n'
        "[graph.passes]\nenable = []\n"
    )
    (only,) = project.check_named_drivers(
        _config(tmp_path / "q", text), project_root=tmp_path / "q"
    )
    assert only.severity == "ok"


# --- D-13 -----------------------------------------------------------------------------------


def _pricebook(root: Path, text: str) -> Path:
    path = root / ".omniweave" / "pricebook.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_d13_no_pricebook_is_reported_and_not_a_warning(tmp_path: Path) -> None:
    root = tmp_path / "p"
    (found,) = project.check_pricebooks(_config(root), cwd=root, today="2026-10-23")
    assert found.severity == "ok"
    assert "every attempt is unpriced, and billed_api cannot be admitted" in found.detail


def test_d13_a_pricebook_missing_its_currency_warns_with_the_loaders_own_fix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "p"
    config = _config(root)
    _pricebook(root, 'version = 1\neffective_from = "2026-01-01"\n')
    (found,) = project.check_pricebooks(config, cwd=root, today="2026-10-23")
    assert found.severity == "warning"
    assert "a pricebook declares 'currency'" in found.detail
    assert found.fix == "add currency to .omniweave/pricebook.toml"


def test_d13_a_pricebook_effective_after_today_warns_and_one_before_is_ok(tmp_path: Path) -> None:
    root = tmp_path / "p"
    config = _config(root)
    path = _pricebook(root, 'version = 1\ncurrency = "USD"\neffective_from = "2027-01-01"\n')
    (later,) = project.check_pricebooks(config, cwd=root, today="2026-10-23")
    assert later.severity == "warning"
    assert later.fix == f"set effective_from to 2026-10-23 or earlier in {path.as_posix()}"
    path.write_text('version = 1\ncurrency = "USD"\neffective_from = "2026-10-23"\n', "utf-8")
    (now,) = project.check_pricebooks(config, cwd=root, today="2026-10-23")
    assert (now.severity, now.detail.endswith("version 1, currency USD")) == ("ok", True)


def test_d13_with_no_corpus_reads_no_pricebook(tmp_path: Path) -> None:
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "home")})
    (found,) = project.check_pricebooks(config, cwd=tmp_path, today="2026-10-23")
    assert (found.severity, found.detail) == (
        "ok",
        "no corpus is declared, so no pricebook is read",
    )


# --- D-17 -----------------------------------------------------------------------------------


def test_d17_no_installed_skill_is_ok(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path / "u"), "OMNIWEAVE_HOME": str(tmp_path / "ow")}
    found = project.check_skills(env, cwd=tmp_path)
    assert found.severity == "ok"
    assert "records no installed skill" in found.detail


def test_d17_a_bundle_that_no_longer_matches_its_hash_warns_with_skills_update(
    tmp_path: Path,
) -> None:
    """`ow skills verify`'s own check, over a lock its own writer wrote: the bundle on disk no
    longer hashes to what the lock recorded."""
    from omniweave.install.skills_lock import Locked, write  # noqa: PLC0415

    home = tmp_path / "ow"
    bundle = tmp_path / "u" / ".claude" / "skills" / "omniweave"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text("edited after install", encoding="utf-8")
    recorded = Locked("omniweave", "0" * 64, 1, 5, ("~/.claude/skills/omniweave",))
    assert write(home, {"omniweave": recorded}, release="0", pid=1) == ""
    found = project.check_skills(
        {"HOME": str(tmp_path / "u"), "OMNIWEAVE_HOME": str(home)}, cwd=tmp_path
    )
    assert found.severity == "warning", found
    assert "OW_SKILL_HASH_MISMATCH omniweave: expected " + "0" * 64 in found.detail
    assert found.fix == "ow skills update"


def test_d17_with_no_home_says_it_did_not_run(tmp_path: Path) -> None:
    found = project.check_skills({}, cwd=tmp_path)
    assert (found.severity, found.fix) == ("warning", "set HOME or USERPROFILE")
    assert found.detail.startswith("not run: neither HOME nor USERPROFILE is set")
