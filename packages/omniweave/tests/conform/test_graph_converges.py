"""GR8 at its smallest: an incremental store equals a full rebuild on `canonical_projection()`.

06 section 10.4's gate, over two documents and two edits through a real `ow add`, against a second
project built once from the final files (D675). The edits are the two that move the graph: a
heading renumbered, which removes one defined name and adds another, and a defined term deleted
from the other document. Before D675 the projection differed on exactly one member: the edited
documents' old versions were retired, and their defined terms stayed live entities. The full GR8
run -- 60 documents, 20 shuffled steps -- is `tools/gate_incremental_graph.py`'s.
"""

from __future__ import annotations

import os
import sqlite3  # noqa: TID251 -- the assertions read the stores the runs wrote.
from pathlib import Path

import pytest
from omniweave_core.store.projection import CanonicalProjection, canonical_projection
from test_free_passes_at_ingest import CONTRACT, PROJECT, _run

pytestmark = pytest.mark.conform

NOTES = """# Notes

See GL-4471 and Section 1 of the loan.

## 1. Scope

The "Notice" means a written notice, and "Agent" means the facility agent.
"""

FINAL = {
    "loan.md": CONTRACT.replace("Beta Bank.", "Beta Bank and Gamma Bank.").replace(
        "## 2. Payment", "## 4. Payment"
    ),
    "notes.md": NOTES.replace(', and "Agent" means the facility agent', ""),
}


def _project(root: Path, files: dict[str, str]) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    for name, text in files.items():
        (root / "docs" / name).write_text(text, encoding="utf-8")
    return root


def _add(project: Path, env: dict[str, str]) -> None:
    code, shown = _run(project, env, "add", "docs")
    assert code == 0, shown[-3000:]


def _projection(project: Path) -> CanonicalProjection:
    connection = sqlite3.connect(project / ".omniweave" / "docs.owstore")
    try:
        return canonical_projection(connection)
    finally:
        connection.close()


def test_an_incremental_store_converges_to_a_full_rebuild(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env = {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(tmp_path / "ow"),
    }
    incremental = _project(tmp_path / "incremental", {"loan.md": CONTRACT, "notes.md": NOTES})
    _add(incremental, env)
    for name, text in FINAL.items():
        (incremental / "docs" / name).write_text(text, encoding="utf-8")
        _add(incremental, env)
    full = _project(tmp_path / "full", FINAL)
    _add(full, env)

    after, rebuilt = _projection(incremental), _projection(full)
    assert after.differences(rebuilt) == {}
    assert after == rebuilt
    keys = {key for _scope, _etype, key in rebuilt.entities}
    assert {"lender", "notice"} <= keys, "the projection compared something"
    assert "agent" not in keys, "the deleted defined term is gone from both"
    names = {(name, akind) for _doc, name, akind in rebuilt.anchors}
    assert ("4", "section") in names
    assert ("2", "section") not in names, "the renumbered heading's old number is gone"
