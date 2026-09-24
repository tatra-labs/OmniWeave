"""`sha256-bundle-1`, against 10:1342-1366 and 10:2805, and the sort the plan's code gets wrong.

**The sharpest test is `test_the_plans_path_sort_hashes_the_router_differently_per_platform`.** It
runs 10:1348's function with its `sorted(Path)` under both pure path flavours over the bundle's own
two names, shows the two digests differ, and shows the shipped digest is the same under both. D464.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from omniweave.skills.hash import (
    ALGO,
    SKIP_NAMES,
    TEXT_EXT,
    bundle_sha256,
    first_difference,
    walk,
)


def _bundle(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


ROUTER = {"SKILL.md": b"router\n", "references/actions.md": b"catalog\n"}


def _plan_digest(root: Path, flavour: type[PurePosixPath] | type[PureWindowsPath]) -> str:
    """10:1348-1358 as printed, with `sorted()` over paths of the given flavour."""
    files = [p for p in root.rglob("*") if p.is_file()]
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda one: flavour(one.as_posix())):
        rel = f.relative_to(root).as_posix()
        digest.update(rel.encode())
        digest.update(b"\0")
        data = f.read_bytes()
        if f.suffix in TEXT_EXT:
            data = data.replace(b"\r\n", b"\n")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def test_the_constants_are_10_1344s() -> None:
    assert ALGO == "sha256-bundle-1"
    assert {".md", ".txt", ".toml", ".json", ".jsonc", ".py", ".sql", ".svg", ".csv",
                        ".yml"} == TEXT_EXT  # fmt: skip
    assert {".DS_Store", "__pycache__", "Thumbs.db"} == SKIP_NAMES


def test_the_plans_path_sort_hashes_the_router_differently_per_platform(tmp_path: Path) -> None:
    """D464: 10:1350's `sorted(Path)` is case-folded on Windows and part-wise on POSIX."""
    root = _bundle(tmp_path / "omniweave", ROUTER)
    windows = _plan_digest(root, PureWindowsPath)
    posix = _plan_digest(root, PurePosixPath)
    assert windows != posix
    assert bundle_sha256(root)[0] == posix
    assert [rel for rel, _ in walk(root).files] == ["SKILL.md", "references/actions.md"]


def test_the_order_is_the_relative_path_as_a_string_not_part_wise(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "b", {"references/actions.md": b"a", "references-old.md": b"b"})
    assert [rel for rel, _ in walk(root).files] == ["references-old.md", "references/actions.md"]


def test_the_digest_is_full_and_counts_files_and_normalised_bytes(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "b", {"SKILL.md": b"a\r\nb\r\n", "logo.png": b"\x89\r\n"})
    digest, files, total = bundle_sha256(root)
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert (files, total) == (2, len(b"a\nb\n") + len(b"\x89\r\n"))


def test_crlf_is_folded_in_text_files_only(tmp_path: Path) -> None:
    """10:1355: *"a Windows checkout is not stale"* -- for `TEXT_EXT` members, and only those."""
    lf = _bundle(tmp_path / "lf", {"SKILL.md": b"a\nb\n", "x.bin": b"\r\n"})
    crlf = _bundle(tmp_path / "crlf", {"SKILL.md": b"a\r\nb\r\n", "x.bin": b"\r\n"})
    binary = _bundle(tmp_path / "bin", {"SKILL.md": b"a\nb\n", "x.bin": b"\n"})
    assert bundle_sha256(lf)[0] == bundle_sha256(crlf)[0]
    assert bundle_sha256(lf)[0] != bundle_sha256(binary)[0]


def test_a_move_changes_the_digest_and_equal_trees_agree(tmp_path: Path) -> None:
    one = _bundle(tmp_path / "one", ROUTER)
    two = _bundle(tmp_path / "two", ROUTER)
    moved = _bundle(tmp_path / "moved", {"SKILL.md": b"router\n", "refs/actions.md": b"catalog\n"})
    assert bundle_sha256(one) == bundle_sha256(two)
    assert bundle_sha256(one)[0] != bundle_sha256(moved)[0]


def test_skipped_names_and_suffixes_are_not_hashed(tmp_path: Path) -> None:
    clean = _bundle(tmp_path / "clean", ROUTER)
    junk = _bundle(
        tmp_path / "junk",
        {**ROUTER, ".DS_Store": b"x", "__pycache__/a.cpython-312.pyc": b"x", "tool.pyc": b"x"},
    )
    assert bundle_sha256(clean) == bundle_sha256(junk)
    assert walk(junk).skipped == (".DS_Store", "__pycache__", "tool.pyc")


def test_a_link_is_neither_followed_nor_hashed_but_is_reported(tmp_path: Path) -> None:
    """10:1361-1362: *"follows no symlink"*."""
    root = _bundle(tmp_path / "b", ROUTER)
    outside = _bundle(tmp_path / "outside", {"secret.md": b"x"})
    try:
        (root / "linked.md").symlink_to(outside / "secret.md")
    except OSError:
        pytest.skip("this account cannot create a symlink")
    assert bundle_sha256(root) == bundle_sha256(_bundle(tmp_path / "plain", ROUTER))
    assert walk(root).links == ("linked.md",)


def test_the_first_difference_is_named_in_digest_order(tmp_path: Path) -> None:
    """10:1369: the mismatch names *"the first differing path"*."""
    one = _bundle(tmp_path / "one", ROUTER)
    two = _bundle(tmp_path / "two", {**ROUTER, "references/actions.md": b"changed\n"})
    three = _bundle(tmp_path / "three", {**ROUTER, "extra.md": b"x"})
    assert first_difference(one, two) == "references/actions.md"
    assert first_difference(one, three) == "extra.md"
    assert first_difference(one, _bundle(tmp_path / "four", ROUTER)) is None
