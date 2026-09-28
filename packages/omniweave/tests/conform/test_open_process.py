"""`python -m omniweave open` as a real child with piped stdio, over document text cp1252 lacks.

`conform` because it starts a process (13-quality.md section 2.7). An opened block is document
text, so `ow open` needs `ow query`'s reconfigure (10:1553-1561), and this is the only kind of test
that can see a child's encoding. The child runs without `PYTHONUTF8` and `PYTHONIOENCODING`, as
`test_query_process.py`'s do.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.host.subproc import Captured, run_captured

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.conform

TIMEOUT_S = 60
CJK = "契約"
TEXTS = {
    1: "Termination",
    2: f"Either party may terminate this agreement ({CJK}) with thirty days notice.",
    3: "Fees are payable monthly in arrears.",
}


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}


@pytest.fixture
def project(tmp_path: Path, seeded_store: Any) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    seeded_store(tmp_path / ".omniweave" / "index.owstore", TEXTS)
    return tmp_path


def _open(project: Path, *args: str) -> Captured:
    return run_captured(
        (sys.executable, "-m", "omniweave", "open", *args),
        stdin=b"",
        cwd=str(project),
        env=_env(),
        timeout_s=TIMEOUT_S,
    )


def test_a_piped_child_prints_the_opened_cjk_block_as_utf8(project: Path) -> None:
    done = _open(project, "d1#2")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert CJK in done.stdout.decode("utf-8")


def test_a_piped_child_exits_2_on_a_stale_ref_and_still_prints_the_answer(project: Path) -> None:
    done = _open(project, "d1#2", "d1#99", "--render", "json")
    assert done.returncode == 2
    document = json.loads(done.stdout.decode("utf-8"))
    assert [block["cite"] for block in document["evidence"]] == ["d1#2"]
    assert CJK in document["evidence"][0]["text"]
