"""Q-G3 tested as a program: `tools/gate_bless.py`, over real git repositories. D841.

The row grammar, append-only, coverage and the second-reviewer share are
`omniweave_conform.bless`'s, which `test_conform_bless.py` holds to the plan. This file holds the
gate to its docstring:
- `judge()` rule by rule over one landed change;
- `main()` over a repository built under `tmp_path`, where a pull request's fix-up commit, the base
  branch's last commit and a root commit are each the change that lands;
- anything git cannot answer exits 2.

Loaded by file path under a private name and at module scope, as `test_gate_flake.py` loads its
gate.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess  # noqa: TID251 -- the gate reads git, so its tests build real repositories.
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_bless.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_bless", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
SHAPE = "fixtures/goldens/core@2026.09/parse.pdf.pdfium@1/report.shape"
BASELINE = "eval/baselines/coldstart-linux-3.12.json"
REASON = "pdfium 6721 merges ligature runs; shape counters move"


def _row(glob: str = "fixtures/goldens/core@2026.09/parse.pdf.pdfium@1/*", **counts: int) -> str:
    tally = {"incidental": 1, "structural": 0, "unexplained": 0, **counts}
    classes = ",".join(f"{cls}={tally[cls]}" for cls in ("incidental", "structural", "unexplained"))
    return f"2026-10-15\tq@example.org\t{glob}\t{classes}\t{REASON}\n"


def _judge(
    changed: list[str],
    new_log: str = "",
    old_log: str = "",
    messages: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
) -> list[tuple[bool, str, str]]:
    found = GATE.judge(changed, old_log, new_log, list(messages), env or {})
    return [(one.failing, one.subject, one.detail) for one in found]


# --- ruling 2: what is guarded ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "is_guarded"),
    [
        (SHAPE, True),
        ("fixtures/goldens/core@2026.09/parse.pdf.pdfium@1/report.pages", True),
        ("fixtures/goldens/core@2026.09/parse.pdf.pdfium@1/report.outline", True),
        ("fixtures/goldens/DECOMPOSITION.toml", False),
        ("fixtures/report.shape", False),
        ("schema/expected/owdoc.json", True),
        ("schema/expected/.gitkeep", False),
        (BASELINE, True),
        ("eval/BLESS.log", False),
        ("eval/gates.toml", False),
        ("packages/omniweave/src/omniweave/eval/baselines/x.py", False),
    ],
)
def test_a_guarded_path_is_a_reduction_or_under_the_two_footed_trees(
    path: str, is_guarded: bool
) -> None:
    assert GATE.guarded(path) is is_guarded


# --- rulings 3-8: judge() ------------------------------------------------------------------------


def test_nothing_guarded_and_nothing_added_is_clean() -> None:
    assert _judge(["README.md", "eval/gates.toml"]) == []


def test_a_guarded_change_with_no_row_fails_naming_it_and_the_fix() -> None:
    [(failing, subject, detail)] = _judge([SHAPE, "README.md"])
    assert (failing, subject) == (True, SHAPE)
    assert detail.startswith("changed with no eval/BLESS.log row whose glob matches it; ")
    assert "OMNIWEAVE_BLESS=1 ow eval golden --bless --reason" in detail


def test_a_row_whose_glob_matches_the_change_covers_it() -> None:
    assert _judge([SHAPE], _row()) == []


def test_a_row_only_counts_when_this_change_added_it() -> None:
    assert _judge([SHAPE], new_log=_row(), old_log=_row())[0][1] == SHAPE


def test_a_row_that_blesses_nothing_fails() -> None:
    other = _row("fixtures/goldens/core@2026.09/parse.office.anydoc@3/*")
    assert _judge([SHAPE], _row() + other) == [
        (
            True,
            "eval/BLESS.log row fixtures/goldens/core@2026.09/parse.office.anydoc@3/*",
            "blesses no guarded change in this commit",
        )
    ]


def test_a_rewritten_log_fails_once_and_is_judged_no_further() -> None:
    [(failing, subject, detail)] = _judge([SHAPE], new_log=_row(), old_log=_row(incidental=2))
    assert (failing, subject) == (True, "eval/BLESS.log")
    assert "was rewritten, not appended to" in detail
    assert detail.endswith("; restore the old rows and append")


def test_an_added_row_that_does_not_parse_fails() -> None:
    [(failing, subject, detail)] = _judge([SHAPE], "2026-10-15\tq@example.org\tshort\n")
    assert (failing, subject) == (True, "eval/BLESS.log")
    assert "has 3 fields, not 5" in detail


def test_an_unexplained_row_fails_with_no_override() -> None:
    [(failing, _, detail)] = _judge([SHAPE], _row(unexplained=1))
    assert failing
    assert detail == (
        "blesses 1 unexplained change(s), and there is no override: ow eval golden --explain <file>"
    )


def test_a_structural_share_above_a_fifth_is_a_note_and_never_a_failure() -> None:
    assert _judge([SHAPE], _row(incidental=8, structural=2)) == []
    [(failing, _, detail)] = _judge([SHAPE], _row(incidental=7, structural=3))
    assert not failing
    assert detail == "needs a second reviewer: 3/10 structural is above 20%"


def test_a_baseline_change_needs_a_bless_footer_mirroring_a_row() -> None:
    row = _row("eval/baselines/*")
    [(failing, subject, detail)] = _judge([BASELINE], row)
    assert (failing, subject) == (True, "Bless: footer")
    assert "no commit message carries a Bless: footer" in detail
    assert _judge([BASELINE], row, messages=(f"Re-baseline\n\nBless: {REASON}\n",)) == []
    assert _judge([BASELINE], row, messages=(f"x\n\nBless:   {REASON}  \n",)) == []
    assert _judge([BASELINE], row, messages=("x\n\nBless: another reason entirely, long\n",))
    assert _judge([BASELINE], row, messages=(f"x\n\nNot-Bless: {REASON}\n",))


def test_a_schema_expected_change_needs_the_footer_too() -> None:
    row = _row("schema/expected/*")
    assert _judge(["schema/expected/owdoc.json"], row)[0][1] == "Bless: footer"


def test_a_reduction_needs_no_footer() -> None:
    assert _judge([SHAPE], _row(), messages=("no footer here",)) == []


def test_the_bless_flag_in_the_gates_environment_fails() -> None:
    assert _judge([], env={"OMNIWEAVE_BLESS": "1"}) == [
        (
            True,
            "OMNIWEAVE_BLESS",
            "is 1 in the gate's environment: unset it in CI (test_bless_flag_is_off)",
        )
    ]
    assert _judge([], env={"OMNIWEAVE_BLESS": "0"}) == []


def test_the_flag_is_reported_beside_a_rewritten_log() -> None:
    found = _judge([], new_log="", old_log=_row(), env={"OMNIWEAVE_BLESS": "1"})
    assert [subject for _, subject, _ in found] == ["OMNIWEAVE_BLESS", "eval/BLESS.log"]


# --- main() over real repositories ---------------------------------------------------------------

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


def _git(repo: Path, *args: str) -> str:
    assert GIT is not None
    done = subprocess.run(  # noqa: S603 - fixed argv, argv[0] from shutil.which.
        [GIT, "-c", "user.name=q", "-c", "user.email=q@example.org", *args],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return done.stdout.decode()


def _commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "master")
    _commit(tmp_path, "start", {"README.md": "x\n"})
    return tmp_path


def _main(
    repo: Path, capsys: pytest.CaptureFixture[str], *argv: str, env: dict[str, str] | None = None
) -> tuple[int, str]:
    code = GATE.main(["--repo", str(repo), *argv], env=env or {})
    return code, capsys.readouterr().out


@needs_git
def test_a_branch_whose_fix_up_commit_adds_the_row_is_clean(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, "move a counter", {SHAPE: "owshape/1\nblocks.total 3\n"})
    _commit(repo, "bless it", {"eval/BLESS.log": _row()})
    code, out = _main(repo, capsys, "--base", "master")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].endswith(": 2 changed path(s), 1 guarded")
    assert lines[-1] == "Q-G3 ok  0 finding(s)"


@needs_git
def test_a_branch_with_an_unblessed_reduction_exits_1(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, "move a counter", {SHAPE: "owshape/1\n"})
    code, out = _main(repo, capsys, "--base", "master")
    assert code == 1
    assert f"  FAIL  {SHAPE}: changed with no eval/BLESS.log row" in out
    assert out.splitlines()[-1] == "Q-G3 FAIL  1 finding(s)"


@needs_git
def test_on_the_base_branch_the_last_commit_is_judged_alone(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit(repo, "unblessed", {SHAPE: "owshape/1\n"})
    assert _main(repo, capsys, "--base", "master")[0] == 1
    _commit(repo, "later", {"README.md": "y\n"})
    code, out = _main(repo, capsys, "--base", "master")
    assert code == 0
    assert out.splitlines()[0].endswith(": 1 changed path(s), 0 guarded")


@needs_git
def test_a_root_commit_is_judged_against_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, "init", "-q", "-b", "master")
    _commit(tmp_path, "root", {SHAPE: "owshape/1\n", "eval/BLESS.log": _row()})
    code, out = _main(tmp_path, capsys, "--base", "master")
    assert code == 0
    assert out.startswith("Q-G3  the root commit: 2 changed path(s), 1 guarded\n")


@needs_git
def test_a_deleted_reduction_needs_a_bless_too(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit(repo, "add", {SHAPE: "owshape/1\n", "eval/BLESS.log": _row()})
    _git(repo, "checkout", "-q", "-b", "feat")
    (repo / SHAPE).unlink()
    _commit(repo, "drop it", {})
    assert _main(repo, capsys, "--base", "master")[0] == 1


@needs_git
def test_a_baseline_blessed_with_its_footer_is_clean(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "checkout", "-q", "-b", "feat")
    files = {BASELINE: "{}\n", "eval/BLESS.log": _row("eval/baselines/*")}
    _commit(repo, f"Re-baseline coldstart\n\nBless: {REASON}", files)
    assert _main(repo, capsys, "--base", "master")[0] == 0


@needs_git
def test_a_footer_in_an_earlier_commit_of_the_range_counts(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "checkout", "-q", "-b", "feat")
    files = {BASELINE: "{}\n", "eval/BLESS.log": _row("eval/baselines/*")}
    _commit(repo, f"Re-baseline coldstart\n\nBless: {REASON}", files)
    _commit(repo, "fix a typo", {"README.md": "y\n"})
    assert _main(repo, capsys, "--base", "master")[0] == 0


@needs_git
def test_a_second_reviewer_note_prints_and_still_exits_0(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "checkout", "-q", "-b", "feat")
    files = {SHAPE: "owshape/1\n", "eval/BLESS.log": _row(incidental=7, structural=3)}
    _commit(repo, "bless a structural change", files)
    code, out = _main(repo, capsys, "--base", "master")
    assert code == 0
    assert "  note  eval/BLESS.log row fixtures/goldens/" in out
    assert out.splitlines()[-1] == "Q-G3 ok  0 finding(s)"


@needs_git
def test_a_baseline_without_its_footer_exits_1(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, "Re-baseline", {BASELINE: "{}\n", "eval/BLESS.log": _row("eval/baselines/*")})
    code, out = _main(repo, capsys, "--base", "master")
    assert code == 1
    assert "  FAIL  Bless: footer: " in out


@needs_git
def test_the_flag_in_the_environment_fails_a_clean_change(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _main(repo, capsys, "--base", "master", env={"OMNIWEAVE_BLESS": "1"})
    assert code == 1
    assert "  FAIL  OMNIWEAVE_BLESS: is 1 in the gate's environment" in out


@needs_git
@pytest.mark.parametrize("argv", [("--base", "no-such-ref"), ("--head", "no-such-ref")])
def test_an_unknown_ref_did_not_run(
    repo: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    code, out = _main(repo, capsys, *argv)
    assert code == 2
    assert out.startswith("Q-G3 DID NOT RUN  git rev-parse")


@needs_git
def test_a_directory_that_is_no_repository_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _main(tmp_path, capsys, "--base", "master")
    assert code == 2
    assert out.startswith("Q-G3 DID NOT RUN  ")


def test_a_bad_argument_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--no-such-flag"], env={}) == 2
    capsys.readouterr()


@needs_git
def test_without_git_the_gate_did_not_run(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GATE.shutil, "which", lambda _name: None)
    assert _main(repo, capsys, "--base", "master") == (2, "Q-G3 DID NOT RUN  git is not on PATH\n")
