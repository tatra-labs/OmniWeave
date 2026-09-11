"""G16 tested as a program: the vacuous path, and all three clauses shown a red.

`tools/gate_contract.py` enforces `04-driver-system.md:1511` — *"**G16** loads the previous **two**
releases' conformance-template drivers against HEAD, so the window in which a third-party driver
keeps working without a rebuild is two minor releases — stated as a number so an author can plan"* —
and `11-repo-layout.md:1124` adds the consequence: *"a failure blocks the merge"*.

**This repository has no `v*` tag, so the gate is vacuous here and every interesting path is dead
code.** That is the problem this file exists to solve. `16-roadmap.md:516` asks for G16 at P3
precisely so the mechanism is not written under pressure at the first release, and a mechanism that
has never executed is written rather than wired. So the fixture below clones this repository into
`tmp_path` — locally, no network — tags five commits, and drives the real
`git worktree` → `uv build` → load-against-HEAD path against them.

Five tags, one clean pair and three sabotages, each aimed at one clause:

* `v1.0.0`, `v1.1.0` — the template exactly as it ships. Both must load.
* `bad-card-1` — `card_schema = 2`. HEAD's `load_card()` must refuse it as `CARD_SCHEMA_TOO_NEW`,
  which is the `card` clause: a narrowed grammar is what a `card_schema` bump does to an old driver.
* `bad-class-1` — the entrypoint's class renamed. HEAD's `activate()` must fail to find it, which is
  the `activate` clause. This one also proves the gate's central asymmetry actually holds: the
  tagged wheel is first on `PYTHONPATH` and HEAD's own installed `omniweave_conform` is behind it,
  so if the shadowing were broken this test would find HEAD's `PlainTextParser` and pass.
* `bad-contract-1` — `CONTRACT = 99`. HEAD's `CONTRACTS_SUPPORTED` must not contain it, which is the
  `contract` clause and the only one of the three that is a deliberate product decision rather than
  an accident.

**Cost.** The clone is ~0.8 s and each release is ~1.5 s of `uv build` plus a fresh interpreter, so
this file is a few seconds. It spawns `git` and `uv`; that is what it is testing.

Specified in 11-repo-layout.md sections 4.1 and 4.4, 04-driver-system.md section 5.2, and
16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import importlib.util
import subprocess  # noqa: TID251 — the fixture builds a real repository with real tags.
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TEMPLATE = Path("packages/omniweave-conform/src/omniweave_conform/template")
CARD = TEMPLATE / "driver.toml"
DRIVER = TEMPLATE / "driver.py"
CONTRACT_PY = Path("packages/omniweave-core/src/omniweave_core/contract.py")


@pytest.fixture(scope="session")
def gate(repo_root: Path) -> ModuleType:
    """`tools/gate_contract.py`, loaded by path and never put on `sys.path`."""
    path = repo_root / "tools" / "gate_contract.py"
    spec = importlib.util.spec_from_file_location("_owgate_contract", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(  # noqa: S603 — a fixed argv, no shell.
        ["git", "-C", str(repo), *args],  # noqa: S607 — `git` on PATH is the subject here.
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    return proc.stdout


def edit(repo: Path, relative: Path, old: str, new: str) -> None:
    path = repo / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{relative}: {old!r} is no longer there to break"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.fixture(scope="session")
def clone(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """This repository, cloned locally, with five tags: a clean pair and three sabotages.

    `--no-hardlinks` is not decoration. A local clone hardlinks the object store by default and
    that fails outright when the source and the destination are on different volumes — which they
    are here, `E:` to the temp directory on `C:` — with `fatal: failed to create link ... Improper
    link`. A test that only ever ran on a one-drive machine would be a test that fails for its
    first Windows contributor.
    """
    target = tmp_path_factory.mktemp("g16") / "clone"
    subprocess.run(  # noqa: S603 — a fixed argv, no shell, and no network: `--local`.
        ["git", "clone", "--quiet", "--local", "--no-hardlinks", str(repo_root), str(target)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    git(target, "config", "user.name", "g16-fixture")
    git(target, "config", "user.email", "g16@example.invalid")

    # The clean pair, plus two that exist only so the semver ordering has something to get wrong.
    for tag in ("v1.0.0", "v1.1.0", "v1.9.0", "v1.10.0"):
        git(target, "tag", tag, "HEAD")

    edit(target, CARD, "card_schema = 1", "card_schema = 2")
    git(target, "commit", "-qam", "a card from a grammar HEAD does not implement")
    git(target, "tag", "bad-card-1")
    git(target, "checkout", "-q", "HEAD~1", "--", str(CARD.as_posix()))

    edit(target, DRIVER, "class PlainTextParser", "class RenamedParser")
    git(target, "commit", "-qam", "the entrypoint's class, renamed")
    git(target, "tag", "bad-class-1")
    git(target, "checkout", "-q", "HEAD~1", "--", str(DRIVER.as_posix()))

    edit(target, CONTRACT_PY, "CONTRACT: int = 1", "CONTRACT: int = 99")
    git(target, "commit", "-qam", "a CONTRACT major HEAD has never supported")
    git(target, "tag", "bad-contract-1")
    return target


def run(gate: ModuleType, clone: Path, glob: str, releases: int = 1) -> int:
    return gate.main(["--repo", str(clone), "--tag-glob", glob, "--releases", str(releases)])


def clauses(findings: list[Any]) -> list[str]:
    return [finding.clause for finding in findings]


# ---------------------------------------------------------------------------
# the vacuous path — which is the only one this repository can take today
# ---------------------------------------------------------------------------


def test_no_tags_is_vacuous_and_exits_zero(gate: ModuleType, capsys: Any) -> None:
    """`16-roadmap.md:516` marks G16 "vacuous at P3; wired for later", so exit 0 is correct."""
    assert gate.main(["--releases", "2"]) == 0
    assert "vacuous" in capsys.readouterr().out


def test_a_vacuous_run_says_what_it_searched_and_what_it_would_have_done(
    gate: ModuleType, capsys: Any
) -> None:
    """A gate indistinguishable from a gate nobody wired up is a gate nobody notices has stopped
    running. Exit 0 is shared with a real pass; the output must not be."""
    gate.main(["--releases", "2"])
    out = capsys.readouterr().out
    assert "0 release tag(s) matching 'v*', 2 wanted" in out
    assert "git worktree add" in out
    assert "uv build --package omniweave-conform" in out
    assert "CONTRACTS_SUPPORTED" in out


def test_one_tag_when_two_are_wanted_is_still_vacuous(
    gate: ModuleType, clone: Path, capsys: Any
) -> None:
    """Partial history is not partial enforcement. Loading one release and reporting a pass would
    claim a two-release window that was never checked."""
    assert run(gate, clone, "v1.0.0", releases=2) == 0
    out = capsys.readouterr().out
    assert "1 release tag(s)" in out
    assert "found: v1.0.0" in out


# ---------------------------------------------------------------------------
# tag selection
# ---------------------------------------------------------------------------


def test_tags_are_ordered_by_version_and_not_lexically(gate: ModuleType, clone: Path) -> None:
    """`v1.10.0` is newer than `v1.9.0` and sorts BELOW it as text. Getting this wrong does not
    fail — it silently checks the wrong two releases, which is worse."""
    assert gate.find_tags(clone, "v1.*", 2) == ["v1.10.0", "v1.9.0"]


def test_only_the_requested_number_of_releases_is_built(gate: ModuleType, clone: Path) -> None:
    assert gate.find_tags(clone, "v1.*", 1) == ["v1.10.0"]
    assert len(gate.find_tags(clone, "v1.*", 99)) == 4


# ---------------------------------------------------------------------------
# the real path — a clean release loads
# ---------------------------------------------------------------------------


def test_a_clean_release_loads_against_head(gate: ModuleType, clone: Path, capsys: Any) -> None:
    """THE WHOLE MECHANISM, end to end: `git worktree add` at the tag, `uv build --package
    omniweave-conform` from source in that tree, then HEAD's `load_card()` and `activate()` over
    the wheel's own template. Nothing is downloaded."""
    assert run(gate, clone, "v1.[01].0", releases=2) == 0
    out = capsys.readouterr().out
    assert "2 release(s) load against HEAD: v1.1.0, v1.0.0" in out
    assert "parse.text.plain -> PlainTextParser" in out


def test_the_gate_leaves_no_worktree_behind(gate: ModuleType, clone: Path) -> None:
    """git keeps its own administrative entry under `.git/worktrees/` even after the directory is
    gone, so a gate that forgot to prune would slowly fill the repository it guards."""
    run(gate, clone, "v1.0.0", releases=1)
    assert git(clone, "worktree", "list").strip().count("\n") == 0


# ---------------------------------------------------------------------------
# the three clauses, each shown its own red
# ---------------------------------------------------------------------------


def test_a_card_from_a_newer_grammar_fails_the_card_clause(
    gate: ModuleType, clone: Path, capsys: Any
) -> None:
    """What a `card_schema` bump does to an old driver, from the old driver's side."""
    assert run(gate, clone, "bad-card-*", releases=1) == 1
    out = capsys.readouterr().out
    assert "[card]" in out
    assert "card_schema = 2 is newer than this build's 1" in out


def test_a_renamed_entrypoint_class_fails_the_activate_clause(
    gate: ModuleType, clone: Path, capsys: Any
) -> None:
    """AND proves the shadowing works. HEAD's own `omniweave_conform` is installed in this
    workspace and still exports `PlainTextParser`; if the tagged wheel were not first on
    `PYTHONPATH`, `activate()` would find HEAD's class and this would pass for the worst possible
    reason — the gate measuring HEAD against HEAD."""
    assert run(gate, clone, "bad-class-*", releases=1) == 1
    out = capsys.readouterr().out
    assert "[activate]" in out
    assert "has no attribute 'PlainTextParser'" in out


def test_an_unsupported_contract_major_fails_the_contract_clause(
    gate: ModuleType, clone: Path, capsys: Any
) -> None:
    """The only one of the three that is a deliberate decision rather than an accident: dropping a
    major from `CONTRACTS_SUPPORTED` ends the two-release window for every driver built against
    it, and `04:1511` makes that an announced, migration-guided product event."""
    assert run(gate, clone, "bad-contract-*", releases=1) == 1
    out = capsys.readouterr().out
    assert "[contract]" in out
    assert "declares CONTRACT = 99 and HEAD supports [1]" in out


def test_the_tagged_contract_is_read_as_text_not_imported(
    gate: ModuleType, clone: Path, tmp_path: Path
) -> None:
    """Two builds of `omniweave_core` cannot be imported into one interpreter, and this clause has
    to hold both numbers at once. Same discipline as `gate_vendor.py`'s `_core_limits()`."""
    worktree = tmp_path / "tree"
    git(clone, "worktree", "add", "--detach", str(worktree), "bad-contract-1")
    try:
        assert gate.tagged_contract(worktree) == 99
        from omniweave_core.contract import CONTRACT  # noqa: PLC0415 — HEAD's, for the contrast.

        assert CONTRACT == 1, "the interpreter's own CONTRACT was not disturbed"
    finally:
        git(clone, "worktree", "remove", "--force", str(worktree))
        git(clone, "worktree", "prune")


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------


def test_zero_releases_is_exit_two(gate: ModuleType) -> None:
    """2 is "the gate did not get to ask" and 1 is "the contract is broken". CI fails on both."""
    assert gate.main(["--releases", "0"]) == 2


def test_a_directory_that_is_not_a_repository_is_exit_two(
    gate: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    assert gate.main(["--repo", str(tmp_path)]) == 2
    assert "not a git repository" in capsys.readouterr().out
