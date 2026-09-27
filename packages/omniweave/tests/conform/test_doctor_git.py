"""D-02 against real git: the index reader against `git ls-files`, and `ow doctor` as a process.

`conform` because every test here starts `git` or `python`, which 13-quality.md section 2.7 puts in
this tier. The children run through `omniweave_core.host.subproc.run_captured`, so this file needs
no `subprocess` exemption.

This is V01-16's instrument (00:717), and it covers all three clauses:
- *"`ow doctor` on a store tracked in git **fails** with `OW-S-060`"*: a real repository, a real
  commit and a real child;
- *"the shipped `.gitignore` covers `.owstore`"*: `git check-ignore` over this checkout;
- *"no `.owstore` is ever a git artefact"*: this checkout's own index, read both ways.

The unit tests pin the format's rules byte by byte. What they cannot show is that git writes what
the format says, so here git writes, and the reader must agree with `git ls-files` exactly (D610).

Every git child gets an empty global config and no system config. `feature.manyFiles`,
`index.version` and `core.splitIndex` in a developer's `~/.gitconfig` change which index is
written, and a test whose subject is the index cannot let the machine choose it.
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
from typing import TYPE_CHECKING

import pytest
from omniweave.doctor import check_tracked_store, gitindex
from omniweave_core.host.subproc import Captured, run_captured

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.conform,
    pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH"),
]

TIMEOUT_S = 60
GIT = shutil.which("git") or "git"
TREE = {
    ".gitignore": "*.log\n",
    "src/a.py": "x = 1\n",
    "docs/deep/er/x.txt": "text\n",
    "my corpus/notes.md": "spaced\n",
    "契約/c.txt": "two CJK characters in a directory name\n",
}
STORES = (".omniweave/index.owstore", "my corpus/b.owstore")


def _env(tmp_path: Path) -> dict[str, str]:
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env |= {"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1"}
    return env


def _git(tree: Path, env: dict[str, str], *args: str) -> Captured:
    argv = (GIT, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args)
    done = run_captured(argv, stdin=b"", cwd=str(tree), env=env, timeout_s=TIMEOUT_S)
    assert done.returncode == 0, (args, done.stderr.decode("utf-8", "replace"), done.failed)
    return done


def _ls_files(tree: Path, env: dict[str, str]) -> tuple[str, ...]:
    raw = _git(tree, env, "ls-files", "-z").stdout
    return tuple(one.decode("utf-8") for one in raw.split(b"\0") if one)


def _populate(tree: Path, env: dict[str, str], *, object_format: str = "sha1") -> bool:
    tree.mkdir()
    done = run_captured(
        (GIT, "init", "-q", f"--object-format={object_format}", "."),
        stdin=b"",
        cwd=str(tree),
        env=env,
        timeout_s=TIMEOUT_S,
    )
    if done.returncode != 0:
        return False
    for name, text in TREE.items():
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text(text, encoding="utf-8")
    for name in STORES:
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_bytes(b"SQLite format 3\0")
    _git(tree, env, "add", "--", *TREE)
    _git(tree, env, "add", "-f", "--", *STORES)
    return True


def _version(tree: Path) -> int:
    return struct.unpack(">I", (tree / ".git" / "index").read_bytes()[4:8])[0]


@pytest.mark.parametrize("version", [2, 3, 4])
def test_the_reader_agrees_with_git_ls_files(tmp_path: Path, version: int) -> None:
    """Version 3 is only written when an entry carries extended flags, so that case adds an
    intent-to-add entry (`git add -N`), which sets one. The header is read back, so the test
    proves it covered the version it names."""
    env = _env(tmp_path)
    tree = tmp_path / "repo"
    assert _populate(tree, env)
    if version >= 3:  # the first version with extended flags
        (tree / "later.txt").write_text("not yet\n", encoding="utf-8")
        _git(tree, env, "add", "-N", "--", "later.txt")
    _git(tree, env, "update-index", f"--index-version={version}")
    assert _version(tree) == version
    read = gitindex.read_tracked(tree / "src")
    assert read.unreadable == ""
    assert read.repo_root == tree.resolve()
    assert read.paths == _ls_files(tree, env)


def test_the_reader_agrees_with_git_in_a_sha256_repository(tmp_path: Path) -> None:
    env = _env(tmp_path)
    tree = tmp_path / "repo"
    if not _populate(tree, env, object_format="sha256"):
        pytest.skip("this git cannot create a sha256 repository")
    read = gitindex.read_tracked(tree)
    assert (read.paths, read.unreadable) == (_ls_files(tree, env), "")


def test_a_linked_worktree_is_read_through_its_gitdir_file(tmp_path: Path) -> None:
    env = _env(tmp_path)
    tree = tmp_path / "repo"
    assert _populate(tree, env)
    _git(tree, env, "commit", "-q", "-m", "seed")
    _git(tree, env, "worktree", "add", "-q", str(tmp_path / "wt"))
    read = gitindex.read_tracked(tmp_path / "wt")
    assert (tmp_path / "wt" / ".git").is_file()
    assert (read.paths, read.unreadable) == (_ls_files(tmp_path / "wt", env), "")


def _doctor(tree: Path, env: dict[str, str]) -> Captured:
    return run_captured(
        (sys.executable, "-m", "omniweave", "doctor"),
        stdin=b"",
        cwd=str(tree),
        env=env,
        timeout_s=TIMEOUT_S,
    )


def test_ow_doctor_fails_with_ow_s_060_on_a_committed_store_and_its_fix_clears_it(
    tmp_path: Path,
) -> None:
    """00:717, V01-16 as a process: commit a store, run `ow doctor`, then run the command it
    printed, and run `ow doctor` again."""
    env = _env(tmp_path)
    tree = tmp_path / "repo"
    assert _populate(tree, env)
    _git(tree, env, "commit", "-q", "-m", "a store committed by mistake")
    failed = _doctor(tree, env)
    out = failed.stdout.decode("ascii")
    assert failed.returncode == 1, out
    assert "FAIL D-02: OW-S-060 OW_STORE_TRACKED_IN_GIT: 2 store file(s)" in out
    fix = next(line for line in out.splitlines() if line.strip().startswith("fix: git rm"))
    assert fix.strip() == 'fix: git rm --cached -- .omniweave/index.owstore "my corpus/b.owstore"'
    _git(tree, env, "rm", "-q", "--cached", "--", *STORES)
    cleared = _doctor(tree, env)
    assert cleared.returncode == 0, cleared.stdout.decode("ascii")
    assert "ok   D-02: no .owstore is tracked" in cleared.stdout.decode("ascii")


@pytest.mark.parametrize(
    "path",
    [
        ".omniweave/index.owstore",
        "index.owstore",
        "some/where/index.vec.owstore",
        "events.owstore",
        ".omniweave/index.owstore-wal",
        ".omniweave/index.owstore-shm",
    ],
)
def test_the_shipped_gitignore_covers_every_store_spelling(
    repo_root: Path, tmp_path: Path, path: str
) -> None:
    """00:717's second clause, over this checkout's `.gitignore`: `--no-index`, so the answer is
    the ignore rules' and not whether the path happens to be tracked."""
    done = run_captured(
        (GIT, "check-ignore", "-q", "--no-index", "--", path),
        stdin=b"",
        cwd=str(repo_root),
        env=_env(tmp_path),
        timeout_s=TIMEOUT_S,
    )
    assert done.returncode == 0, f"{path} is not ignored by {repo_root / '.gitignore'}"


def test_this_checkout_tracks_no_store_read_both_ways(repo_root: Path, tmp_path: Path) -> None:
    """00:717's third clause, *"no `.owstore` is ever a git artefact"*, over this repository's
    own index. The reader is held to `git ls-files` over the largest real index this suite
    touches, then D-02 is asked the question."""
    if not (repo_root / ".git").exists():
        pytest.skip("not a git checkout")
    env = _env(tmp_path)
    read = gitindex.read_tracked(repo_root)
    if read.unreadable:
        pytest.skip(f"this checkout's index is not one the reader reads fully: {read.unreadable}")
    assert read.paths == _ls_files(repo_root, env)
    assert not [p for p in read.paths if ".owstore" in p.rsplit("/", 1)[-1]]
    assert check_tracked_store(repo_root).severity == "ok"
