"""`omniweave.doctor.gitindex`: the index reader D-02 stands on, over hand-built indexes.

Every index here is built byte by byte from git's `index-format.txt`, by `conftest.py`'s
`git_index`, so each test pins one clause of the format. `tests/conform/test_doctor_git.py` then
holds the reader to `git ls-files` over indexes real git wrote, in all three versions. These tests
pin the format's rules, and that one pins them against git. Neither is enough alone (D610).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.doctor import gitindex

if TYPE_CHECKING:
    from pathlib import Path

PATHS = (
    b".gitignore",
    b".omniweave/index.owstore",
    b"docs/a/b/contract.pdf",
    b"docs/a/b/contract.txt",
    b"src/main.py",
)
DECODED = tuple(p.decode() for p in PATHS)


@pytest.mark.parametrize("version", [2, 3, 4])
def test_every_version_reads_back_every_path(git_index: Any, version: int) -> None:
    assert gitindex.parse_index(git_index.build(PATHS, version=version)) == (DECODED, "")


def test_an_extended_entry_is_skipped_by_its_two_extra_bytes(git_index: Any) -> None:
    """Version 3's clause: the extended flag adds 16 bits before the path. An entry read without
    that skip starts its path two bytes early, and so does every entry after it."""
    data = git_index.build(PATHS, version=3, extended=frozenset({PATHS[1]}))
    assert gitindex.parse_index(data) == (DECODED, "")


def test_version_4_strips_long_prefixes_with_a_multi_byte_varint(git_index: Any) -> None:
    """A strip count above 127 takes two varint bytes, and git's varint adds one per continuation.
    A plain base-128 decode reads 128 as 256."""
    deep = b"d/" + b"x" * 300
    paths = (deep + b"/a.owstore", deep + b"/b", b"e" * 200 + b"/c", b"f")
    got = gitindex.parse_index(git_index.build(paths, version=4))
    assert got == (tuple(p.decode() for p in paths), "")


@pytest.mark.parametrize("value", [0, 1, 127, 128, 129, 16_511, 16_512, 2_097_279, 2_097_280])
def test_the_varint_decodes_what_git_encodes(git_index: Any, value: int) -> None:
    encoded = git_index.varint(value)
    assert gitindex._varint(encoded + b"\xff", 0) == (value, len(encoded))


def test_a_path_longer_than_the_12_bit_length_field_is_read_to_its_nul(git_index: Any) -> None:
    long = b"a/" + b"n" * 5000 + b".owstore"
    assert gitindex.parse_index(git_index.build((long, b"z"))) == ((long.decode(), "z"), "")


def test_a_sha256_repository_has_32_byte_object_ids(git_index: Any, tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("[extensions]\n\tobjectformat = sha256\n", encoding="utf-8")
    (git / "index").write_bytes(git_index.build(PATHS, hash_bytes=32))
    read = gitindex.read_tracked(tmp_path)
    assert (read.paths, read.unreadable) == (DECODED, "")


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "no DIRC signature"),
        (b"XXXX" + b"\0" * 20, "no DIRC signature"),
        (b"DIRC" + struct.pack(">II", 5, 0), "version 5"),
        (b"DIRC" + struct.pack(">II", 2, 3) + b"\0" * 70, "truncated"),
    ],
)
def test_bad_bytes_are_a_reason_and_never_an_exception(data: bytes, reason: str) -> None:
    _paths, why = gitindex.parse_index(data)
    assert reason in why


def test_a_path_with_no_nul_is_malformed_and_not_an_exception(git_index: Any) -> None:
    whole = git_index.build((b"a.txt",))
    assert "malformed" in gitindex.parse_index(whole[: 12 + 62 + 3])[1]


def test_a_sparse_directory_entry_makes_the_read_incomplete(git_index: Any) -> None:
    """A sparse index folds a subtree into one `040000` entry, and a store could be inside it. So
    the read reports that it is incomplete and never answers "not tracked" over the fold."""
    paths = (b"a.txt", b"vendor/", b"z.txt")
    got, why = gitindex.parse_index(git_index.build(paths, modes={b"vendor/": git_index.DIRECTORY}))
    assert got == ("a.txt", "z.txt")
    assert "sparse index" in why


def test_a_split_index_makes_the_read_incomplete(git_index: Any) -> None:
    link = b"link" + struct.pack(">I", 20) + b"\0" * 20
    got, why = gitindex.parse_index(git_index.build(PATHS, extensions=link))
    assert got == DECODED
    assert "split index" in why


def test_an_optional_extension_is_not_mistaken_for_a_split_index(git_index: Any) -> None:
    tree = b"TREE" + struct.pack(">I", 6) + b"\0" * 6
    assert gitindex.parse_index(git_index.build(PATHS, extensions=tree)) == (DECODED, "")


def test_outside_any_work_tree_there_is_no_repo(tmp_path: Path) -> None:
    #  `tmp_path` sits under the system temp directory, which no test run makes a work tree.
    assert gitindex.read_tracked(tmp_path) == gitindex.IndexRead(repo_root=None, paths=())


def test_a_repo_with_no_index_tracks_nothing_and_says_so_cleanly(tmp_path: Path) -> None:
    """`git init` with nothing added writes no index file: an empty index, and a complete read."""
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "sub"
    sub.mkdir()
    read = gitindex.read_tracked(sub)
    assert read == gitindex.IndexRead(repo_root=tmp_path.resolve(), paths=())


def test_a_gitdir_file_is_followed_to_the_worktree_index(git_index: Any, tmp_path: Path) -> None:
    """A linked worktree or a submodule: `.git` is a file, and its index is in the directory that
    file names. The object format is read from the `commondir`'s config, where git keeps it."""
    common = tmp_path / "main.git"
    worktree_git = common / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (common / "config").write_text("[extensions]\nobjectformat = sha256\n", encoding="utf-8")
    (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")
    (worktree_git / "index").write_bytes(git_index.build(PATHS, hash_bytes=32))
    tree = tmp_path / "wt"
    tree.mkdir()
    (tree / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")
    read = gitindex.read_tracked(tree)
    assert read == gitindex.IndexRead(repo_root=tree.resolve(), paths=DECODED)
