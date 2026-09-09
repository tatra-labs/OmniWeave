"""Every distribution's sdist carries its own `src/` tree, and no build target reaches outside it.

Written because a real defect got past the whole gate set. Adding
`[tool.hatch.build.targets.wheel.force-include]` with `"../../schema/migrations"` as its source --
an attempt to satisfy 11-repo-layout.md:1186 ("packaged with `omniweave-core` as package data, read
through `importlib.resources` at use time") while keeping the files at the repo-root path
`11-repo-layout.md:2304`'s CODEOWNERS line anchors -- dropped `omniweave-core`'s sdist from 34
members to three. `.gitignore`, `PKG-INFO`, `pyproject.toml`, and **no `src/` at all**, while
`uv build --sdist` still printed `Successfully built`. Adding the same force-include to the sdist
target restored the members and then broke the other direction: the wheel build from an unpacked
sdist runs with the sdist as its project root, where `../../schema/migrations` does not exist, and
`hatchling.build.build_wheel` exits 1.

An installable-looking sdist containing no source is the worst available failure mode, and it is
invisible: G7 reads wheel metadata, nothing in `tools/gates.toml` builds an sdist at all. The full
finding, including the ruling that the migrations' canonical tracked home is
`omniweave_core/store/schema/migrations/`, is `_plan/_notes/build-defects.md` D12.

WHY THIS IS STATIC AND NOT A BUILD. Building fourteen sdists and then fourteen wheels from them is
the direct assertion and it is minutes of IO per run, which is how a check ends up marked slow and
then skipped. The two properties below are the ones the defect actually violated, both readable off
`pyproject.toml`: the sdist declares `src`, and no target's `force-include` source escapes the
project directory. A future gate may build the artefacts; this is the cheap floor that would have
caught it, and it is deliberately not a substitute -- the docstring says so rather than the gate
register, because a new gate id is a register allocation governed by 11-repo-layout.md section 5.2's
three-part mechanism.

Loci: 11-repo-layout.md sections 1.3 (the build half, "identical in shape in all fourteen"), 2.6
(package data is read at use time), 5.1 (migrations ship in the wheel).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PYPROJECTS = tuple(sorted(REPO.glob("packages/*/pyproject.toml")))

# The four build-target tables hatchling reads. `force-include` may appear under any of them, and
# under `[tool.hatch.build]` itself, where it applies to every target at once.
TARGETS = ("wheel", "sdist", "custom", "binary")


def _build(path: Path) -> dict:
    return (
        tomllib.loads(path.read_text(encoding="utf-8"))
        .get("tool", {})
        .get("hatch", {})
        .get("build", {})
    )


def _force_includes(build: dict) -> list[tuple[str, str]]:
    """Every `(source, destination)` pair declared anywhere in a distribution's build config."""
    found: list[tuple[str, str]] = []
    scopes = [("build", build)]
    scopes += [(f"targets.{name}", build.get("targets", {}).get(name, {})) for name in TARGETS]
    for label, scope in scopes:
        for source, destination in scope.get("force-include", {}).items():
            found.append((f"{label}: {source}", str(destination)))
    return found


def test_the_repository_has_fourteen_distributions_to_check() -> None:
    """Guards every test below against silently iterating an empty glob."""
    assert len(PYPROJECTS) == 14, [p.parent.name for p in PYPROJECTS]


@pytest.mark.parametrize("path", PYPROJECTS, ids=lambda p: p.parent.name)
def test_every_sdist_declares_its_src_tree(path: Path) -> None:
    """An sdist with no `src/` installs an empty distribution and reports success doing it.

    11-repo-layout.md:1097's block is the shape all fourteen share:
    `include = ["src", "LICENSE", "NOTICE", "THIRD_PARTY.md", "LICENSES", "pyproject.toml"]`.
    `src` is the only entry whose absence is unrecoverable, so it is the one asserted here.
    """
    sdist = _build(path).get("targets", {}).get("sdist", {})
    include = sdist.get("include")
    assert include is not None, f"{path.parent.name}: no [tool.hatch.build.targets.sdist] include"
    assert "src" in include, f"{path.parent.name}: sdist include does not carry 'src': {include}"


@pytest.mark.parametrize("path", PYPROJECTS, ids=lambda p: p.parent.name)
def test_no_build_target_force_includes_a_path_outside_the_distribution(path: Path) -> None:
    """The exact defect. A `..` in a force-include source is what empties the sdist.

    Verified rather than assumed: `"../../schema/migrations"` on the wheel target alone took
    `omniweave-core`'s sdist to three members, and on both targets it made `sdist` -> `wheel` fail
    with exit 1. Either way the source has to live inside the project directory, so a relative
    source that climbs out of it is banned here by shape.
    """
    offenders = [
        (source, destination)
        for source, destination in _force_includes(_build(path))
        if ".." in Path(source.split(": ", 1)[-1]).parts
    ]
    assert offenders == [], (
        f"{path.parent.name}: force-include source escapes the project directory: {offenders}. "
        f"An sdist cannot carry a file above its own root, so the wheel built from that sdist "
        f"cannot find it. See _plan/_notes/build-defects.md D12."
    )


def test_the_escape_check_would_actually_fire() -> None:
    """The mutation, kept as a test, because the check above passes on a clean tree either way.

    Without this, `test_no_build_target_force_includes_a_path_outside_the_distribution` is
    indistinguishable from `assert [] == []` -- it reads the real files, finds no force-include at
    all today, and passes. This drives the same predicate over the config that broke the build.
    """
    poisoned = {
        "targets": {
            "wheel": {"force-include": {"../../schema/migrations": "omniweave_core/store/schema"}}
        }
    }
    found = _force_includes(poisoned)
    assert found == [("targets.wheel: ../../schema/migrations", "omniweave_core/store/schema")]
    assert any(".." in Path(source.split(": ", 1)[-1]).parts for source, _ in found)

    innocent = {"targets": {"wheel": {"force-include": {"assets/logo.svg": "pkg/logo.svg"}}}}
    assert not any(
        ".." in Path(source.split(": ", 1)[-1]).parts for source, _ in _force_includes(innocent)
    )


def test_a_force_include_under_the_bare_build_table_is_also_seen() -> None:
    """`[tool.hatch.build.force-include]` applies to every target, so it cannot be skipped.

    Scoping the check to `targets.*` would leave the one spelling that affects the most targets
    unchecked, which is the shape of hole this file exists to close.
    """
    assert _force_includes({"force-include": {"../x": "pkg/x"}}) == [("build: ../x", "pkg/x")]
