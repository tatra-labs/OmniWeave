"""`import omniweave_core` costs the per-turn path nothing it does not have to.

The three properties here are the P1 half of gates G17, G23 and G1/G9, asserted from a fresh
interpreter because that is the only place they are observable: once a test process has
imported a lazy subpackage for its own reasons, sys.modules can no longer tell you whether the
eager import pulled it in.

Specified in 11-repo-layout.md section 1.3 ("The nine LAZY names are a STRUCTURAL property, not
a convention") and 02-architecture.md section 3.3.
"""

from __future__ import annotations

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


def test_the_eight_subpackage_homes_exist_and_are_empty() -> None:
    """P1 creates the homes so later phases have somewhere to land (11-repo-layout.md
    section 1.3's tree). Each is a package, and each is a docstring and nothing else."""
    for name in SUBPACKAGE_HOMES:
        init = CORE_SRC / name / "__init__.py"
        assert init.is_file(), f"missing subpackage home omniweave_core/{name}/"
        source = init.read_text(encoding="utf-8")
        assert source.lstrip().startswith('"""'), f"{name}/__init__.py has no docstring"
        assert "import " not in source, f"{name}/__init__.py carries an import at P1"
