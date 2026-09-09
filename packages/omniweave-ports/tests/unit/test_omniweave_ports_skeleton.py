"""The omniweave-ports skeleton holds its declared shape.

Both properties are read off declarations rather than a hand-maintained list, which is the
same discipline tools/gate_layers.py applies at G4: no author picks their own row
(02-architecture.md section 3.2, 11-repo-layout.md section 1.10 site 3).
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

DIST = "omniweave-ports"
PKG = "omniweave_ports"

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]


def _project() -> dict[str, object]:
    text = (DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]


def _layers_row() -> list[str]:
    text = (REPO / "tools" / "layers.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)[PKG]


def test_init_is_a_re_export_facade_and_not_a_body() -> None:
    """`omniweave_ports/__init__.py` is a docstring, imports, and `__all__` — nothing else.

    The scaffold's rule was "docstring only", which held while every package was a home
    waiting for its phase. This package's body landed in P1 (16-roadmap.md section 4 makes
    the ports vocabulary an exit criterion), so the rule tightens rather than relaxes: a
    facade may re-export, and may not compute. Anything else here would be behaviour, and
    "it has no function with a side effect" (02-architecture.md section 2 row 1).
    """
    source = (DIST_ROOT / "src" / PKG / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert ast.get_docstring(tree), f"{PKG}/__init__.py must cite the plan section it serves"
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "ban-relative-imports = all"
            assert str(node.module).startswith(PKG), f"{DIST} re-exports {node.module}"
            continue
        assert isinstance(node, ast.Assign), f"{DIST} __init__.py computes: {ast.dump(node)}"
        assert [t.id for t in node.targets if isinstance(t, ast.Name)] == ["__all__"]
        assert isinstance(node.value, ast.List)


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
