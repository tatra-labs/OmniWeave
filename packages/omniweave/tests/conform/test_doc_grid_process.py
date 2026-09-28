"""`python -m omniweave doc grid` as a real child with piped stdio, over cell text cp1252 lacks.

`conform` because it starts a process (13-quality.md section 2.7). A cell's text is document text,
so `ow doc grid` needs `ow query`'s reconfigure (10:1553-1561), and only a child can show it. The
child runs without `PYTHONUTF8` and `PYTHONIOENCODING`, as `test_query_process.py`'s do.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.host.subproc import run_captured

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.conform

TIMEOUT_S = 60
CJK = "契約"


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}


def test_a_piped_child_prints_a_cjk_cell_as_utf8(
    tmp_path: Path, seeded_store: Any, seeded_table: Any
) -> None:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    store = seeded_store(tmp_path / ".omniweave" / "index.owstore")
    seeded_table(store, {11: (0, 0, 1, 1, "Term"), 12: (0, 1, 1, 1, CJK)})
    for render in ("text", "json"):
        done = run_captured(
            (sys.executable, "-m", "omniweave", "doc", "grid", "d1#10", "--render", render),
            stdin=b"",
            cwd=str(tmp_path),
            env=_env(),
            timeout_s=TIMEOUT_S,
        )
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        out = done.stdout.decode("utf-8")
        assert CJK in out
        if render == "json":
            assert json.loads(out)["cells"][1]["text"] == CJK
