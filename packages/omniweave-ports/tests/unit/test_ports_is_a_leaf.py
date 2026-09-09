"""`omniweave_ports` is the leaf of the first-party graph and imports nothing but stdlib.

Its tools/layers.toml row is `[]`, which is why a `trust_class` field on a ports dataclass
would be unspellable (04-driver-system.md sections 1.3 and 5.1) and why a third-party driver's
whole omniweave surface is ~40 KB with an empty `dependencies` list.

Specified in 02-architecture.md sections 2 row 1 and 3.2 rule 1, and 11-repo-layout.md
section 1.2.
"""

from __future__ import annotations

import json
import subprocess  # noqa: TID251 — a fresh interpreter is the only witness for an import graph.
import sys
import tomllib
from pathlib import Path

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]


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


def test_the_layers_row_is_empty() -> None:
    """Rule 1: omniweave-ports depends on nothing. The only row in the file that is []."""
    text = (REPO / "tools" / "layers.toml").read_text(encoding="utf-8")
    rows = tomllib.loads(text)
    assert rows["omniweave_ports"] == []
    assert [name for name, row in rows.items() if row == []] == ["omniweave_ports"]


def test_the_dependencies_list_is_empty() -> None:
    """G1 resolves omniweave-ports in a clean environment and asserts it resolves to itself
    alone. The empty list here is the declaration that makes that true."""
    text = (DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["project"]["dependencies"] == []


def test_importing_ports_reaches_no_other_first_party_package() -> None:
    """A driver that imports omniweave_ports must not thereby import the framework."""
    loaded = _modules_loaded_by("import omniweave_ports")
    others = sorted(
        name
        for name in loaded
        if name.startswith("omniweave") and not name.startswith("omniweave_ports")
    )
    assert others == [], f"import omniweave_ports reached {others}"


def test_importing_ports_adds_only_stdlib_modules() -> None:
    """The whole third-party-facing type surface, stdlib only (02-architecture.md row 1)."""
    baseline = _modules_loaded_by("")
    added = _modules_loaded_by("import omniweave_ports") - baseline
    third_party = sorted(
        name
        for name in added
        if not name.startswith("_")
        and name.split(".")[0] not in sys.stdlib_module_names
        and not name.startswith("omniweave_ports")
    )
    assert third_party == [], f"import omniweave_ports pulled in {third_party}"
