"""This machine is one Q-G4 cell, and its shapes are the committed goldens. D849.

`tools/gate_frozen_stability.py --emit`, run for real: every fixture `fixtures/index.toml` lists is
ingested by a child `python -m omniweave add`, and this cell's `shape` Reductions are written with
its `cell.toml`. The comparison then reads that one cell, at the plan's fallback coverage of one
pdfium build and one cell, and must find no difference. A child process, so this lives in the
conform tier (Q-G25).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]

_spec = importlib.util.spec_from_file_location(
    "_owgate_frozen_stability_process", REPO / "tools" / "gate_frozen_stability.py"
)
assert _spec is not None and _spec.loader is not None
GATE = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = GATE
_spec.loader.exec_module(GATE)


def test_this_cell_emits_the_committed_shapes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = GATE.main(["--emit", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    cell = GATE.here()
    assert out.splitlines() == [f"Q-G4  emitted 49 shape(s) to {tmp_path / cell.name}"]
    code = GATE.main(["--artifacts", str(tmp_path), "--pdfium-minors", "1", "--cells", "1"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.splitlines() == [
        "Q-G4  49 golden shape(s); 1 cell(s): 1 pdfium build(s) of 1, 1 OS/Python cell(s) of 1",
        "Q-G4 ok  every cell matches the goldens",
    ]
