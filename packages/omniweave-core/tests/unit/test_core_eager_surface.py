"""`import omniweave_core` costs the per-turn path nothing it does not have to.

The three properties here are the P1 half of gates G17, G23 and G1/G9, asserted from a fresh
interpreter because that is the only place they are observable: once a test process has
imported a lazy subpackage for its own reasons, sys.modules can no longer tell you whether the
eager import pulled it in.

Specified in 11-repo-layout.md section 1.3 ("The nine LAZY names are a STRUCTURAL property, not
a convention") and 02-architecture.md section 3.3.
"""

from __future__ import annotations

import ast
import json
import subprocess  # noqa: TID251 — a fresh interpreter is the only witness for G17/G23/G9.
import sys
from pathlib import Path

# The nine names G17 names, verbatim from 11-repo-layout.md section 1.3.
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

# The eight subpackage homes P1 creates under src/omniweave_core/. `toolchain` and
# `modelserver` are single modules rather than packages, so they are not in this list.
SUBPACKAGE_HOMES = (
    "drivers",
    "host",
    "model",
    "archive",
    "store",
    "retrieve",
    "answer",
    "out",
)

DIST_ROOT = Path(__file__).resolve().parents[2]
CORE_SRC = DIST_ROOT / "src" / "omniweave_core"


def _modules_loaded_by(statement: str) -> set[str]:
    """sys.modules after `statement` runs in a fresh interpreter."""
    code = f"{statement}\nimport json as _j, sys as _s\nprint(_j.dumps(sorted(_s.modules)))"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_g17_a_bare_import_loads_none_of_the_nine_lazy_names() -> None:
    """G17. `ow hook prompt` pays for every module `import omniweave_core` touches."""
    loaded = _modules_loaded_by("import omniweave_core")
    eager = sorted(name for name in LAZY if f"omniweave_core.{name}" in loaded)
    assert eager == [], f"import omniweave_core eagerly loaded {eager}"


def test_g23_core_imports_neither_asyncio_nor_selectors() -> None:
    """G23. The single event loop lives in omniweave/run/, in the CLI distribution,
    precisely so core pays no loop-import tax (11-repo-layout.md section 2.1 test 4)."""
    loaded = _modules_loaded_by("import omniweave_core")
    assert "asyncio" not in loaded
    assert "selectors" not in loaded


def test_d1_the_eager_import_adds_only_stdlib_and_omniweave_modules() -> None:
    """INV-2 / G1 / G9: omniweave-core depends on nothing outside the standard library.

    Measured as a difference against a bare interpreter, so whatever a virtualenv injects at
    startup — an editable-install finder, a .pth hook — cancels out rather than being
    mistaken for a dependency.
    """
    baseline = _modules_loaded_by("")
    added = _modules_loaded_by("import omniweave_core") - baseline
    third_party = sorted(
        name
        for name in added
        if not name.startswith("_")
        and name.split(".")[0] not in sys.stdlib_module_names
        and not name.startswith(("omniweave_core", "omniweave_ports"))
    )
    assert third_party == [], f"import omniweave_core pulled in {third_party}"


# The homes a phase has FILLED, and the phase that filled each. A home leaves the
# still-empty set exactly once, when its phase lands, and the entry here is the record of that.
FILLED_HOMES: dict[str, str] = {
    "model": "P2 W2.1 -- enums, spans, block, and the flat re-export surface",
    "store": "P2 W2.3 -- the four Protocols, Snapshot, and the boundary types",
    "archive": "P2 W2.5 -- the .owdoc codec, frames.json, the manifest, and owcheck",
    "retrieve": "P6 W6.1 -- types.py and plan.py, plus the five scoring constants 07:1382 homes"
    " in the package rather than in a module",
}


def _imports(path: Path) -> list[str]:
    """Every module an `__init__.py` actually imports, by parsing rather than by grepping."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or ".")
    return found


def test_every_subpackage_home_exists() -> None:
    """P1 creates all eight so later phases have somewhere to land (11-repo-layout.md
    section 1.3's tree). This half never relaxes, filled or not."""
    for name in SUBPACKAGE_HOMES:
        init = CORE_SRC / name / "__init__.py"
        assert init.is_file(), f"missing subpackage home omniweave_core/{name}/"
        source = init.read_text(encoding="utf-8")
        assert source.lstrip().startswith('"""'), f"{name}/__init__.py has no docstring"


def test_the_still_empty_homes_carry_no_import() -> None:
    """A home no phase has filled holds a docstring and nothing else.

    SCOPED TO THE UNFILLED HOMES, and the scoping is the point rather than a relaxation. The
    original form asserted `"import " not in source` over all eight, which was true at P1 and
    became false the moment P2 filled `model/` -- 02-architecture.md:248 and
    18-api-sketch.md:834-838 put the flat `Block`/`BlockDraft`/`Capabilities` surface in
    `omniweave_core.model` itself, so the re-exports belong in that file and the assertion had to
    stop covering it.

    What must not happen is the assertion quietly becoming vacuous as phases land. So `FILLED_HOMES`
    is an explicit allow-list naming the phase that filled each entry, the still-empty set is
    computed as the difference, and `test_the_filled_homes_are_really_filled` below asserts the
    allow-list carries no name that is still a placeholder. A home cannot leave this test's scope
    by accident, only by someone adding a row and saying which phase did it.

    G17's runtime half is unaffected either way: laziness is a property of
    `omniweave_core/__init__.py` not importing the nine, not of the nine being empty.

    **The witness is the AST and not the substring `"import "`.** A home whose docstring argues
    about what `import omniweave_core` costs -- which is the argument every one of these files is
    obliged to make -- would fail a substring check on its own prose, and the repair a reader
    reaches for is to add a FILLED_HOMES row for a home nothing has filled. That turns the
    allow-list from a record into a way to switch the assertion off, which is the failure its own
    docstring above says it exists to prevent. Parsing catches strictly more: `import x`,
    `from x import y`, and an import nested inside a function, none of which a docstring can fake.
    """
    for name in sorted(set(SUBPACKAGE_HOMES) - set(FILLED_HOMES)):
        init = CORE_SRC / name / "__init__.py"
        assert not _imports(init), (
            f"{name}/__init__.py carries an import but is not in FILLED_HOMES. "
            f"If a phase filled it, add the row and name the phase."
        )


def test_the_filled_homes_are_really_filled() -> None:
    """Every `FILLED_HOMES` row names a home that actually has a body.

    Without this, the allow-list is a way to switch the assertion off: a name added here with no
    code behind it would exempt a home from the import rule while proving nothing. Read the other
    way, it also catches a row left behind after a revert.
    """
    for name, phase in FILLED_HOMES.items():
        assert name in SUBPACKAGE_HOMES, f"{name} is not a subpackage home"
        assert _imports(CORE_SRC / name / "__init__.py"), (
            f"{name} is listed as filled by {phase} but carries no import"
        )
