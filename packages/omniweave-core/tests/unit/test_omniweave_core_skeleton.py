"""The omniweave-core skeleton holds its declared shape.

Both properties are read off declarations rather than a hand-maintained list, which is the
same discipline tools/gate_layers.py applies at G4: no author picks their own row
(02-architecture.md section 3.2, 11-repo-layout.md section 1.10 site 3).
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import omniweave_core

DIST = "omniweave-core"
PKG = "omniweave_core"

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]


def _project() -> dict[str, object]:
    text = (DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]


def _layers_row() -> list[str]:
    text = (REPO / "tools" / "layers.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)[PKG]


# The nine lazy names, verbatim from 11-repo-layout.md section 1.3.
LAZY = (
    "model",
    "store",
    "archive",
    "retrieve",
    "answer",
    "out",
    "host",
    "toolchain",
    "modelserver",
)


def _init_tree() -> ast.Module:
    source = (DIST_ROOT / "src" / PKG / "__init__.py").read_text(encoding="utf-8")
    return ast.parse(source)


def test_init_cites_the_plan_section_it_serves() -> None:
    """Every module in the tree opens with a docstring naming its specification."""
    assert ast.get_docstring(_init_tree()), f"{PKG}/__init__.py has no docstring"


def test_init_imports_none_of_the_nine_lazy_names_at_module_level() -> None:
    """G17, read off the source rather than off `sys.modules`.

    tests/unit/test_core_eager_surface.py already asserts the *runtime* half from a fresh
    interpreter, and that is the property that matters to `ow hook prompt`'s 250 ms budget. This
    is the static half, and it is not redundant: the runtime test can only observe what today's
    code happens to import, whereas this one names the failure -- a module-level `import
    omniweave_core.store` -- at the line that would introduce it, before anyone has to read a
    diff of module names to work out why cold start regressed.

    Only module level is checked. `__getattr__`'s nine function-local imports are the mechanism
    G17 exists to require (11-repo-layout.md section 1.3: laziness is "a STRUCTURAL property,
    not a convention"), so a walk of the whole tree would forbid the very thing being specified.
    """
    eager: list[str] = []
    for node in _init_tree().body:
        if isinstance(node, ast.Import):
            eager += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            eager += [f"{node.module}.{alias.name}" for alias in node.names]
    offenders = sorted(
        name
        for name in eager
        for lazy in LAZY
        if name == f"{PKG}.{lazy}" or name.startswith(f"{PKG}.{lazy}.")
    )
    assert offenders == [], f"{PKG}/__init__.py eagerly imports {offenders}"


def test_init_binds_nothing_but_the_lazy_surface() -> None:
    """The eager module is a *surface*, not a body: it holds no logic of its own.

    16-roadmap.md section 4 puts every module body in a later phase, which is what the original
    docstring-only assertion here was checking. That assertion stopped being expressible once
    11-repo-layout.md section 1.3's `__getattr__` landed -- a lazy surface is a body -- so the
    property is now stated as an allow-list of top-level names instead of an emptiness check.
    A new helper function or constant in this file fails until it is named here on purpose.
    """
    allowed = {"annotations", "ModuleType", "__all__", "LAZY", "__getattr__", "__dir__"}
    bound: list[str] = []
    for node in _init_tree().body:
        if isinstance(node, ast.FunctionDef):
            bound.append(node.name)
        elif isinstance(node, ast.ImportFrom):
            bound += [alias.asname or alias.name for alias in node.names]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.append(node.target.id)
        elif isinstance(node, ast.Assign):
            bound += [t.id for t in node.targets if isinstance(t, ast.Name)]
    assert sorted(set(bound) - allowed) == [], f"{PKG}/__init__.py grew a body: {sorted(bound)}"


def test_the_lazy_tuple_here_matches_the_one_the_module_declares() -> None:
    """This file's `LAZY` and `__init__.py`'s are two transcriptions of one plan row.

    INV-21 forbids a second home for one fact, and a test that hard-codes an expected list is
    exactly that unless something ties the copies together. Importing the module is safe: the
    tuple is eager, and reading it loads none of the nine -- which is why this module can
    import it at the top rather than deferring it inside the test.
    """
    assert tuple(sorted(omniweave_core.LAZY)) == tuple(sorted(LAZY))
    assert tuple(omniweave_core.__all__) == tuple(sorted(LAZY))


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
