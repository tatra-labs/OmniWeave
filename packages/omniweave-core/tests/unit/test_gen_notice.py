"""`tools/gen_notice.py`: G3's second half, over a fake workspace and over this one. **D988.**

11-repo-layout.md section 1.5 rule 2 makes the four attribution artefacts generated and
`--check` gated, and section 9.1 gives the reason there is a copy per project directory rather
than one at the root: PEP 639 resolves `license-files` relative to the project directory and
rejects a pattern that escapes it. The defect this exists against is attribution drift, which the
mined collection supplies twice over -- codegraph's three LICENSE files among 27 vendored
grammars, hyperframes' 212 MB of binaries with no ffmpeg notice anywhere.

Every assertion about the generator's shape runs over a FAKE workspace in `tmp_path`, because a
test that could only run against this repository's sixteen trees would be a test of this
repository. The last four run over the real tree: `--check` is clean, every distribution carries
the four artefacts, every `pyproject.toml` declares the `license-files` globs that make them travel
inside the wheel -- which is the whole point, since "a notice that exists only in the git
repository is a notice that does not travel with the distribution" -- and the four counts the plan
spells for this set agree with the set.

**D999, a user ruling of 2026-10-27, closed the fifteen-to-sixteen erratum**, and the test that
recorded it is replaced here rather than deleted. It asserted that the real tree held one more
than section 9.1 counted, which is a true sentence about a stale document and an unhelpful one
about an amended one: it passes just as well if the prose drifts a second time. What replaces it
reads each of the four counts out of the document and compares it with `len(trees())`, so the
amendment is a measurement and the next distribution to land fails four named cells rather than
quietly making a fifth number wrong.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest

REPO: Final = Path(__file__).resolve().parents[4]
SCRIPT: Final = REPO / "tools" / "gen_notice.py"
GLOBS: Final = ["LICENSE", "NOTICE", "THIRD_PARTY.md", "LICENSES/*"]
ARTEFACTS: Final = ("LICENSE", "NOTICE", "THIRD_PARTY.md", "LICENSES/Apache-2.0.txt")


def _load(root: Path) -> Any:
    """The script, with its `REPO` pointed at `root`. One module per call, so no test leaks.

    Registered in `sys.modules` BEFORE `exec_module`, because `@dataclass` resolves its own
    `__module__` through there and raises `AttributeError: 'NoneType' object has no attribute
    '__dict__'` when a module executes unregistered -- which is a confusing way to learn that a
    `tools/` script holds dataclasses.
    """
    name = f"gen_notice_{root.name}_{id(root)}"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    #  `setattr` and not `module.X =`: the module is typed `ModuleType`, whose attributes are
    #  not assignable, and a per-attribute ignore would be four of them.
    for attribute, value in (
        ("REPO", root),
        ("LOCK", root / "uv.lock"),
        ("LICENCE", root / "LICENSE"),
        ("INDEX", root / "tools" / "licences_captured.toml"),
    ):
        setattr(module, attribute, value)
    return module


def _workspace(tmp_path: Path, *, dists: dict[str, dict[str, Any]], captured: str = "") -> Path:
    """A fake workspace: a root LICENSE, a uv.lock, and one package per entry."""
    (tmp_path / "LICENSE").write_text("Apache License 2.0, the fake one.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fake-monorepo"\nversion = "0"\n', encoding="utf-8"
    )
    (tmp_path / "tools").mkdir(exist_ok=True)
    if captured:
        (tmp_path / "tools" / "licences_captured.toml").write_text(captured, encoding="utf-8")
    lock = ["version = 1", "", "[manifest]", f"members = {sorted(dists)!r}", ""]
    for name, body in sorted(dists.items()):
        where = tmp_path / "packages" / name
        where.mkdir(parents=True, exist_ok=True)
        lines = ["[project]", f'name = "{name}"', 'version = "0.1.0"', 'license = "Apache-2.0"']
        requires = body.get("dependencies", [])
        lines.append(f"dependencies = {requires!r}")
        for extra, entries in (body.get("optional-dependencies") or {}).items():
            lines.append(f"[project.optional-dependencies]\n{extra} = {entries!r}")
        (where / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        lock += ["[[package]]", f'name = "{name}"', 'version = "0.1.0"', ""]
    declared = {
        d
        for body in dists.values()
        for group in (
            body.get("dependencies", []),
            *(body.get("optional-dependencies") or {}).values(),
        )
        for d in group
    }
    #  The lock names a package, not a requirement: `requests>=2` resolves to `requests`.
    for dep in sorted({re.split(r"[<>=!~\[;]", d)[0].strip() for d in declared}):
        lock += ["[[package]]", f'name = "{dep}"', 'version = "9.9.9"', ""]
    (tmp_path / "uv.lock").write_text("\n".join(lock), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Ruling 1: the set of trees
# ---------------------------------------------------------------------------


def test_a_tree_is_every_package_plus_the_root_and_the_count_is_not_written_down(
    tmp_path: Path,
) -> None:
    """Ruling 1: `glob`, not a number. Section 9.1's fifteen was right when it was written."""
    module = _load(_workspace(tmp_path, dists={"a": {}, "b": {}, "c": {}}))
    trees = module.trees()
    assert [one.relative for one in trees] == ["packages/a", "packages/b", "packages/c", "."]
    assert len(trees) == 4, "three packages and the root; adding a fourth needs no edit here"


def test_the_real_tree_is_every_package_plus_the_root() -> None:
    """Ruling 1 over this workspace, which is the set the four plan counts are checked against."""
    module = _load(REPO)
    assert len(module.trees()) == len(list((REPO / "packages").glob("*/pyproject.toml"))) + 1


LAYOUT: Final = REPO / "docs" / "plan" / "11-repo-layout.md"

NUMBER_WORDS: Final[dict[str, int]] = {
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
}
"""Enough of the ladder to catch a count that moved by one in either direction."""

#  Each pattern is anchored on words the sentence cannot lose without someone noticing, and the
#  offset says what the count is OF: a tree per project directory, or a project directory.
PLAN_COUNTS: Final[tuple[tuple[str, str, int], ...]] = (
    (
        "section 9.1, the paragraph",
        r"\*\*There are (\w+) copies of those files and not one",
        0,
    ),
    (
        "section 9.1, the sentence naming the directories",
        r"into each of the (\w+) `packages/<dist>/` directories plus the repository root",
        -1,
    ),
    (
        "section 6.4, G3's cell",
        r"\*\*and the (\w+) `gen_notice\.py --check` trees\*\*",
        0,
    ),
    (
        "section 7.6, step 5",
        r"for all (\w+) `NOTICE`/`LICENSES/`/`THIRD_PARTY\.md` trees",
        0,
    ),
    (
        "section 1, rule 3",
        r"why there are (\w+) copies of them and not one",
        0,
    ),
)


@pytest.mark.parametrize(("where", "pattern", "offset"), PLAN_COUNTS)
def test_the_plan_count_for_this_set_is_the_set(where: str, pattern: str, offset: int) -> None:
    """D999: every count the plan spells for these trees, read back and compared with the trees.

    The offset is the whole content of the check. Four of the five cells count TREES and one counts
    the `packages/<dist>/` directories inside them, which is one fewer, and a reading that let the
    two be the same number is the reading that made the erratum invisible for as long as it was.
    """
    found = re.search(pattern, LAYOUT.read_text(encoding="utf-8"))
    assert found is not None, f"{where}: the sentence this count lives in has moved"
    said = NUMBER_WORDS.get(found.group(1))
    assert said is not None, f"{where}: spells {found.group(1)!r}, which is not a count"
    assert said == len(_load(REPO).trees()) + offset, where


def test_g3s_assertion_quotes_the_cell_it_came_from() -> None:
    """The register's string is section 6.4's cell, so a count may not move in only one of them."""
    rows = tomllib.loads((REPO / "tools" / "gates.toml").read_text(encoding="utf-8"))["gate"]
    (g3,) = [row for row in rows if row["id"] == "G3"]
    quoted = re.search(r"\*\*and the (\w+) `gen_notice\.py --check` trees\*\*", g3["assertion"])
    assert quoted is not None, g3["assertion"]
    assert NUMBER_WORDS[quoted.group(1)] == len(_load(REPO).trees())


# ---------------------------------------------------------------------------
# Ruling 2: the declaration, not the closure
# ---------------------------------------------------------------------------


def test_third_party_lists_the_declaration_and_labels_an_extra(tmp_path: Path) -> None:
    root = _workspace(
        tmp_path,
        dists={
            "a": {"dependencies": ["requests>=2", "b"], "optional-dependencies": {"x": ["lxml"]}},
            "b": {},
        },
    )
    module = _load(root)
    (tree,) = [one for one in module.trees() if one.dist == "a"]
    names = [(one.name, one.extra) for one in tree.requires]
    assert names == [("lxml", "x"), ("requests", "")], "sorted by key, first-party `b` dropped"
    module.emit()
    text = (root / "packages" / "a" / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "| `requests` | 9.9.9 |" in text, "ruling 3: the version is uv.lock's"
    assert "the `x` extra" in text
    assert "required" in text


def test_a_distribution_with_no_requirement_says_so_in_words(tmp_path: Path) -> None:
    root = _workspace(tmp_path, dists={"a": {}})
    module = _load(root)
    module.emit()
    text = (root / "packages" / "a" / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "**None.**" in text
    assert "INV-2" in text, "section 9.1: this is the file a reviewer checks the rule against"


def test_a_distribution_whose_only_requirement_is_an_extra_leads_with_inv_2(tmp_path: Path) -> None:
    root = _workspace(tmp_path, dists={"a": {"optional-dependencies": {"sqlite": ["pysqlite3"]}}})
    module = _load(root)
    module.emit()
    text = (root / "packages" / "a" / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "**No required third-party dependency.**" in text
    assert text.index("No required third-party") < text.index("| `pysqlite3` |"), (
        "the INV-2 sentence comes before the table an extras-only row would otherwise bury"
    )


# ---------------------------------------------------------------------------
# Rulings 4, 5 and 6: the texts, the gaps, and the project's own licence
# ---------------------------------------------------------------------------


def test_every_tree_carries_the_four_artefacts_and_the_licence_is_byte_identical(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path, dists={"a": {}, "b": {}})
    module = _load(root)
    module.emit()
    own = (root / "LICENSE").read_bytes()
    for where in (root, root / "packages" / "a", root / "packages" / "b"):
        for relative in ARTEFACTS:
            assert (where / relative).is_file(), f"{where.name}/{relative}"
        assert (where / "LICENSE").read_bytes() == own
        assert (where / "LICENSES" / "Apache-2.0.txt").read_bytes() == own


def test_check_is_clean_after_emit_and_names_every_drift(tmp_path: Path) -> None:
    root = _workspace(tmp_path, dists={"a": {}})
    module = _load(root)
    module.emit()
    assert module.check() == []
    (root / "packages" / "a" / "NOTICE").write_text("hand-edited\n", encoding="utf-8")
    (root / "packages" / "a" / "THIRD_PARTY.md").unlink()
    findings = module.check()
    assert "packages/a/NOTICE: differs from what this script emits" in findings
    assert "packages/a/THIRD_PARTY.md: missing" in findings


def test_check_reads_no_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 4: the half CI runs cannot depend on what is installed on the runner."""
    root = _workspace(tmp_path, dists={"a": {"dependencies": ["requests"]}})
    module = _load(root)
    module.emit()

    def boom() -> list[object]:
        raise AssertionError("--check read the installed environment")

    monkeypatch.setattr(module, "distributions", boom)
    assert module.check() == []


def test_a_captured_text_whose_digest_moved_is_a_finding(tmp_path: Path) -> None:
    """Ruling 4's digest: a silent edit to a committed licence text fails, as vendor.toml does."""
    index = (
        "schema = 1\n\n[[licence]]\n"
        'name = "requests"\nversion = "9.9.9"\nsource = "LICENSE"\n'
        f'sha256 = "{"0" * 64}"\nspdx = "Apache-2.0"\n'
    )
    root = _workspace(tmp_path, dists={"a": {"dependencies": ["requests"]}}, captured=index)
    texts = root / "tools" / "licence-texts"
    texts.mkdir(parents=True, exist_ok=True)
    (texts / "requests.txt").write_text("the requests licence\n", encoding="utf-8")
    module = _load(root)
    module.emit()
    assert "tools/licence-texts/requests.txt: sha256 is not the index's" in module.check()


def test_a_text_in_the_index_and_not_on_disk_is_a_finding(tmp_path: Path) -> None:
    index = (
        "schema = 1\n\n[[licence]]\n"
        'name = "requests"\nversion = "9.9.9"\nsource = "LICENSE"\n'
        f'sha256 = "{"a" * 64}"\nspdx = "Apache-2.0"\n'
    )
    root = _workspace(tmp_path, dists={"a": {"dependencies": ["requests"]}}, captured=index)
    module = _load(root)
    assert "tools/licence-texts/requests.txt: in the index and not on disk" in module.check()


def test_a_dependency_with_no_captured_text_is_named_in_the_file(tmp_path: Path) -> None:
    """Ruling 5: a gap is a row, never a silence. `firecrawl-anydoc` is the real case."""
    index = (
        "schema = 1\n\n[[licence]]\n"
        'name = "oddball"\nversion = "9.9.9"\nsource = ""\nsha256 = ""\nspdx = ""\n'
        'note = "its wheel ships no licence file at all"\n'
    )
    root = _workspace(tmp_path, dists={"a": {"dependencies": ["oddball"]}}, captured=index)
    module = _load(root)
    module.emit()
    text = (root / "packages" / "a" / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "## Where a text is not here" in text
    assert "its wheel ships no licence file at all" in text
    assert "| `oddball` | 9.9.9 |  | -- | required |" in text
    assert module.check() == [], "a named gap is not a drift"


def test_a_workspace_with_no_lock_or_licence_cannot_run(tmp_path: Path) -> None:
    """Exit 2 is "could not be made", never a pass: section 6.8 refuses a check that cannot fail."""
    module = _load(tmp_path)
    assert module.main([]) == module.EXIT_NOT_RUN
    assert module.main(["--check"]) == module.EXIT_NOT_RUN


# ---------------------------------------------------------------------------
# This repository
# ---------------------------------------------------------------------------


def test_this_repository_passes_g3s_second_half() -> None:
    module = _load(REPO)
    assert module.check() == []


def test_every_distribution_declares_the_license_files_globs_that_ship_them() -> None:
    """Section 9.1 prints the line verbatim. Without it the four artefacts are committed and never
    reach a wheel, which is the defect generating them is supposed to prevent."""
    missing = []
    for path in sorted((REPO / "packages").glob("*/pyproject.toml")):
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        if project.get("license-files") != GLOBS:
            missing.append(f"{path.parent.name}: {project.get('license-files')}")
    assert missing == []


@pytest.mark.parametrize(
    "dist", sorted(one.parent.name for one in (REPO / "packages").glob("*/pyproject.toml"))
)
def test_every_distribution_carries_the_four_artefacts(dist: str) -> None:
    where = REPO / "packages" / dist
    for relative in ARTEFACTS:
        assert (where / relative).is_file(), f"{dist}/{relative}"
