"""`python -m omniweave corpora` as a real child with piped stdio, printing a path cp1252 lacks.

`conform` because it starts a process (13-quality.md section 2.7). An unreadable store is listed
with its own `reason` (10:1031-1032), and the reason names the store's path, which is the user's.
So `ow corpora` needs `ow query`'s reconfigure (10:1553-1561), and only a child can show it. The
child runs without `PYTHONUTF8` and `PYTHONIOENCODING`, as `test_query_process.py`'s do.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

import pytest
from omniweave_core.host.subproc import Captured, run_captured

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.conform

TIMEOUT_S = 60
CJK = "契約"


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}


def _corpora(project: Path, *args: str) -> Captured:
    return run_captured(
        (sys.executable, "-m", "omniweave", "corpora", *args),
        stdin=b"",
        cwd=str(project),
        env=_env(),
        timeout_s=TIMEOUT_S,
    )


def test_a_piped_child_lists_an_unreadable_store_whose_path_is_cjk(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(
        f'[corpora.handbook]\npath = ".omniweave/{CJK}/index.owstore"\n', encoding="utf-8"
    )
    done = _corpora(tmp_path)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    text = done.stdout.decode("utf-8")
    assert text.startswith("handbook")
    assert "unreadable: " in text
    assert CJK in text

    done = _corpora(tmp_path, "--render", "json")
    (row,) = json.loads(done.stdout.decode("utf-8"))["corpora"]
    assert (row["readable"], CJK in row["reason"]) == (False, True)
