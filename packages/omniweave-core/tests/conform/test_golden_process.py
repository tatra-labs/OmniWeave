"""The committed goldens are what a real `ow add` of the Tier-A fixtures reduces to. D848.

`tools/ow_golden.py --check`, run for real: every fixture `fixtures/index.toml` lists is ingested
by a child `python -m omniweave add`, every stored document is reduced, and the result must equal
`fixtures/goldens/core@2026.10/` byte for byte. A child process, so this lives in the conform tier
(Q-G25).
"""

from __future__ import annotations

import importlib.util
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


def test_the_committed_goldens_are_the_ingest(capsys: pytest.CaptureFixture[str]) -> None:
    code = TOOL.main([])
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.splitlines()[-1] == "golden ok  0 document(s) changed"
