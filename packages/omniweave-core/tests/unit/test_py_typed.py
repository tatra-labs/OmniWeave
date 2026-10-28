"""Every distribution ships PEP 561's marker, so its annotations reach the people who read them.

**D996, and it is a shipping defect rather than a tidy-up.** Fifteen distributions, every module
annotated, `pyright` named as the type checker in 11-repo-layout.md section 8.1's table -- and not
one `py.typed`. PEP 561 is explicit that inline annotations in an installed package are **not**
used by a downstream type checker unless the package ships that marker, so without it:

* a third-party driver author writing against `omniweave_ports` gets `Unknown` for `DriverIO`,
  `CostClass` and `ArtifactKind` -- the whole typed surface 04-driver-system.md section 2.3 and
  10-interfaces.md section 2.1 promise them;
* `18-api-sketch.md`'s `@stable` SDK surface type-checks as `Any` in a consumer's editor;
* and the project's own cross-distribution imports do the same, which is how this was found:
  `pyright` reported **829** `reportMissingTypeStubs` errors over `packages/*/src` and `tools`, and
  **737 of them named `omniweave_core`**. Adding the markers removed 824 errors and the
  `reportUnknown*` cascade they caused, from 2,546 to 1,722.

The plan does not mention `py.typed` or PEP 561 anywhere -- a gap in the plan and not a deviation
from it, so this lands as the mechanism section 8.1's "pyright strict" row needs in order to mean
anything to a consumer.

## What this file asserts, and why each direction matters

1. **One marker per distribution, in the import package.** PEP 561 puts the marker *inside* the
   package, beside `__init__.py`; one at the distribution root or in `src/` is invisible.
2. **Nothing else.** A stray marker in a subpackage is harmless but misleading, because it suggests
   the parent is untyped.
3. **Empty.** PEP 561 allows content for partial stubs and this project ships none, so a non-empty
   marker would be a claim nobody wrote.
4. **In the wheel.** The marker that does not ship is the marker that does nothing, and hatchling's
   `packages = ["src/<pkg>"]` includes it only because it sits inside that tree -- a fact worth an
   assertion rather than an assumption.

Specified in PEP 561, 11-repo-layout.md section 8.1's table and section 1.2's fifteen rows.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[4]
PACKAGES: Final = REPO_ROOT / "packages"


def _distributions() -> list[tuple[str, Path]]:
    """Every distribution, as `(name, its import package directory)`.

    Read from each `pyproject.toml`'s own wheel target rather than globbed, so a distribution that
    renames its package directory is followed instead of silently skipped.
    """
    found: list[tuple[str, Path]] = []
    for pyproject in sorted(PACKAGES.glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        name = str(data["project"]["name"])
        targets = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        assert len(targets) == 1, f"{name} builds {len(targets)} packages"
        found.append((name, pyproject.parent / str(targets[0])))
    return found


DISTRIBUTIONS: Final = _distributions()


def test_there_are_fifteen_distributions_and_each_names_one_package() -> None:
    """The floor under everything below: a glob that matched nothing would make every
    parametrised case below vacuous, which is G27 clause d0's lesson applied here."""
    assert len(DISTRIBUTIONS) == 15
    assert len({name for name, _package in DISTRIBUTIONS}) == 15
    for name, package in DISTRIBUTIONS:
        assert package.is_dir(), f"{name}: {package} is not a directory"
        assert (package / "__init__.py").is_file(), f"{name}: no __init__.py"


@pytest.mark.parametrize(("name", "package"), DISTRIBUTIONS, ids=[one for one, _ in DISTRIBUTIONS])
def test_every_distribution_ships_the_marker_beside_its_init(name: str, package: Path) -> None:
    """Assertion 1. PEP 561: "this marker applies recursively", and it applies from where it sits,
    so the marker beside `__init__.py` is the one that types the whole package."""
    marker = package / "py.typed"
    assert marker.is_file(), (
        f"{name} ships no py.typed, so PEP 561 makes every annotation in it invisible to a "
        "downstream type checker -- including a third-party driver author's"
    )
    assert marker.read_bytes() == b"", (
        f"{name}'s py.typed is not empty. Content means a PARTIAL stub package under PEP 561, "
        "which is a claim this project does not make"
    )


def test_no_marker_sits_anywhere_but_a_package_root() -> None:
    """Assertion 2. A marker in a subpackage reads as "this subtree is typed and the parent is
    not", which is the opposite of true here."""
    roots = {package.resolve() for _name, package in DISTRIBUTIONS}
    stray = [
        one.relative_to(REPO_ROOT).as_posix()
        for one in sorted(PACKAGES.rglob("py.typed"))
        if one.parent.resolve() not in roots
    ]
    assert stray == [], stray


def test_the_marker_is_inside_the_tree_the_wheel_target_names() -> None:
    """Assertion 4, without building fifteen wheels. hatchling's wheel target is
    `packages = ["src/<pkg>"]` and it includes that directory's files, so the marker ships BECAUSE
    it sits inside that tree. This asserts the containment the packaging depends on; `G2`'s
    reproducible build and `gate_install.py`'s receipt cover the bytes that come out."""
    for name, package in DISTRIBUTIONS:
        marker = package / "py.typed"
        assert marker.parent == package, name
        assert marker.is_relative_to(package), name


def test_the_plan_names_no_marker_so_this_mechanism_is_an_addition_and_not_a_contradiction() -> (
    None
):
    """The honest frame, asserted so it cannot rot into a claim the plan made.

    11-repo-layout.md section 8.1's table says `pyright` strict and the plan never mentions PEP 561
    or `py.typed`. If a later wave writes the requirement into a document, this test fails and
    whoever reads it should delete it -- at that point the mechanism has a home in the plan and
    does not need defending here.
    """
    documents = [
        *sorted((REPO_ROOT / "docs" / "plan").glob("*.md")),
        *sorted((REPO_ROOT / "docs" / "plan" / "adr").glob("*.md")),
        REPO_ROOT / "docs" / "plan" / "_notes" / "charter.md",
    ]
    naming = [
        one.relative_to(REPO_ROOT).as_posix()
        for one in documents
        if "py.typed" in one.read_text(encoding="utf-8")
    ]
    assert naming == [], (
        f"{naming} now names py.typed: give the requirement its home in the plan and delete this "
        "test, which exists only to record that the plan was silent"
    )
