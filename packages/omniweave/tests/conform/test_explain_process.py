"""`python -m omniweave explain` as a real child with piped stdio, printing text cp1252 lacks.

`conform` because it starts a process (13-quality.md section 2.7). Some register rows hold
characters cp1252 has no byte for (`≠`, for one), so `ow explain` needs `ow query`'s reconfigure
(10:1553-1561). The row is found in the register, not named, so a register edit cannot quietly
turn this into a test of ASCII. The child runs without `PYTHONUTF8` and `PYTHONIOENCODING`, as
`test_query_process.py`'s do.
"""

from __future__ import annotations

import os
import sys

import pytest
from omniweave_core.errors import load_register
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

TIMEOUT_S = 60


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}


def _outside_cp1252(text: str) -> bool:
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return True
    return False


def test_a_piped_child_prints_a_register_row_cp1252_cannot_encode(tmp_path: object) -> None:
    rows = [row for row in load_register().rows if _outside_cp1252(row.meaning + row.fix)]
    assert rows, "the register holds a row whose text cp1252 cannot carry"
    row = rows[0]
    done = run_captured(
        (sys.executable, "-m", "omniweave", "explain", row.numeric),
        stdin=b"",
        cwd=str(tmp_path),
        env=_env(),
        timeout_s=TIMEOUT_S,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    text = done.stdout.decode("utf-8")
    assert text.startswith(f"{row.numeric}  {row.symbol}")
    assert (row.meaning or row.fix) in text
