"""The omniweave-conform skeleton holds its declared shape.

Both properties are read off declarations rather than a hand-maintained list, which is the
same discipline tools/gate_layers.py applies at G4: no author picks their own row
(02-architecture.md section 3.2, 11-repo-layout.md section 1.10 site 3).
"""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path

DIST = "omniweave-conform"
PKG = "omniweave_conform"

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]


def _project() -> dict[str, object]:
    text = (DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]


def _layers_row() -> list[str]:
    text = (REPO / "tools" / "layers.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)[PKG]


def test_init_is_a_surface_and_every_name_it_exports_resolves() -> None:
    """P1 created the home; W3.6 filled it (16-roadmap.md:486).

    This test used to assert the `__init__.py` had NO body -- P1's "the homes exist, the module
    bodies are later phases'" rule. That phase is over for this distribution, so the assertion it
    is replaced with is the one that matters once there IS a body: every name in `__all__` is real.
    A stale `__all__` is how a package advertises a symbol it no longer has, and the failure lands
    on the importer rather than on the author.
    """
    module = importlib.import_module(PKG)
    assert module.__doc__, f"{PKG}/__init__.py must cite the plan section it serves"
    exported = getattr(module, "__all__", None)
    assert exported, f"{PKG} has a body and must declare its surface"
    # NOT asserted sorted: ruff's RUF022 owns `__all__` ordering and its order is not
    # `sorted()` -- constants first, then classes, then functions. Two orderings would
    # disagree and the linter would win, so only the linter states one.
    missing = [name for name in exported if not hasattr(module, name)]
    assert missing == [], f"{PKG}.__all__ names symbols that are not there: {missing}"


def test_the_kit_imports_without_importing_any_driver() -> None:
    """Importing the kit must not import driver code, and the ban is a build failure.

    `tools/semgrep/omniweave.yaml`'s `omniweave-no-import-module-outside-host` covers
    `packages/*/src/**` and excludes only `omniweave_core/host/`, so this package may not call
    `importlib.import_module` at all. The AST is read rather than the behaviour observed, because
    a module that imports a driver only on some path would pass a behavioural check on the other
    one -- which is `purity`'s whole subject, one level up.
    """
    banned = {"import_module", "__import__"}
    offenders: list[str] = []
    for path in sorted((DIST_ROOT / "src" / PKG).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in banned:
                    offenders.append(f"{path.name}:{node.lineno} {name}()")
    assert offenders == [], f"only omniweave_core/host/ may import a driver; found {offenders}"


def test_first_party_dependencies_are_exactly_the_layers_row() -> None:
    """tools/layers.toml row == the first-party half of [project] dependencies.

    A row is the complete allowed set of first-party import roots for that package,
    transitively closed (02-architecture.md section 3.2). A distribution that depends on a
    sibling it may not import, or imports a sibling it does not depend on, is a G4 failure.
    """
    declared = _project()["dependencies"]
    assert isinstance(declared, list)
    roots = sorted(
        {
            str(spec).split()[0].replace("-", "_")
            for spec in declared
            if str(spec).startswith("omniweave")
        }
    )
    assert roots == sorted(_layers_row())
