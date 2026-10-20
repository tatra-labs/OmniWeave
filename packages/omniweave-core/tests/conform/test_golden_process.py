"""The committed goldens are what a real `ow add` of the Tier-A fixtures reduces to. D848.

`tools/ow_golden.py --check`, run for real: every fixture `fixtures/index.toml` lists is ingested
by a child `python -m omniweave add`, every stored document is reduced, and the result must equal
`fixtures/goldens/core@2026.10/` byte for byte. A child process, so this lives in the conform tier
(Q-G25).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]

_spec = importlib.util.spec_from_file_location(
    "_owtool_ow_golden_process", REPO / "tools" / "ow_golden.py"
)
assert _spec is not None and _spec.loader is not None
TOOL = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = TOOL
_spec.loader.exec_module(TOOL)


BLESSING_PLATFORM = "win32"
"""D886: the cell the committed goldens were blessed on. Bytes are that cell's promise."""
CHANGE = re.compile(r"^\s*(incidental|structural|unexplained)\s")
"""One change line of `ow_golden.py --check`: its churn class, then the document."""


def test_the_committed_goldens_are_the_ingest(capsys: pytest.CaptureFixture[str]) -> None:
    """Byte for byte on the blessing cell; elsewhere, every change must be `incidental`.

    D886. CI's first Linux run ingested the four pdfium fixtures to the same shape, counts and
    histograms with different digests, which `churn` classes `incidental`: Linux's pdfium build
    is not Windows'. Bytes across cells are not promised (V10-14 asks for the SHAPE across cells,
    which Q-G4's `gate_frozen_stability.py` compares). So another cell may differ only
    incidentally, and a `structural` or `unexplained` change fails on every cell.
    """
    code = TOOL.main([])
    out = capsys.readouterr().out
    if sys.platform == BLESSING_PLATFORM:
        assert code == 0, out
        assert out.splitlines()[-1] == "golden ok  0 document(s) changed"
        return
    classes = [line.split()[0] for line in out.splitlines() if CHANGE.match(line)]
    assert code in {0, 1}, out
    assert set(classes) <= {"incidental"}, out
