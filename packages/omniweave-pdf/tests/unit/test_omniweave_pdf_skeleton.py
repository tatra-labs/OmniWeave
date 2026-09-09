"""The omniweave-pdf skeleton holds its declared shape.

Both properties are read off declarations rather than a hand-maintained list, which is the
same discipline tools/gate_layers.py applies at G4: no author picks their own row
(02-architecture.md section 3.2, 11-repo-layout.md section 1.10 site 3).
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

DIST = "omniweave-pdf"
PKG = "omniweave_pdf"

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]


def _project() -> dict[str, object]:
    text = (DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]


def _layers_row() -> list[str]:
    text = (REPO / "tools" / "layers.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)[PKG]


def test_init_is_a_home_and_not_a_body() -> None:
    """P1 creates the homes; the module bodies are later phases' (16-roadmap.md section 4).

    A docstring-only __init__.py is also what makes G17 true for omniweave_core by
    construction: a module with no import statement can import no subpackage.
    """
    source = (DIST_ROOT / "src" / PKG / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert ast.get_docstring(tree), f"{PKG}/__init__.py must cite the plan section it serves"
    body = [node for node in tree.body if not isinstance(node, ast.Expr)]
    assert body == [], f"{DIST} __init__.py carries a body at P1: {body!r}"


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
