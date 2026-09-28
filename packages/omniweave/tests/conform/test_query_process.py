"""`python -m omniweave query` as a real child with piped stdio, over document text cp1252 lacks.

`conform` because it starts a process (13-quality.md section 2.7). What it pins is 10:1553-1561:
*"`ow` reconfigures `sys.stdout`/`sys.stderr` to `encoding="utf-8", errors="replace"`"* before
anything is written, because an Answer prints document text. D431 is the measured reason: into a
pipe on Windows a child's stdout is cp1252, and two CJK characters in an Answer would end the
process with a `UnicodeEncodeError` mid-render. No in-process test can see a child's encoding.

The child runs with `PYTHONUTF8` and `PYTHONIOENCODING` removed, as `test_hooks_process.py`'s do:
those belong to the user's machine, and a verb that works only when one happens to be set is a
verb that works on the developer's machine.
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
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    seeded_store(tmp_path / ".omniweave" / "index.owstore", TEXTS)
    return tmp_path


def _query(project: Path, *args: str) -> Captured:
    return run_captured(
        (sys.executable, "-m", "omniweave", "query", *args),
        stdin=b"",
        cwd=str(project),
        env=_env(),
        timeout_s=TIMEOUT_S,
    )


def test_a_piped_child_prints_cjk_document_text_as_utf8(project: Path) -> None:
    done = _query(project, "terminate")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    text = done.stdout.decode("utf-8")
    assert CJK in text
    assert "d1#2" in text


def test_a_piped_child_under_render_json_prints_one_parseable_object(project: Path) -> None:
    done = _query(project, "terminate", "--render", "json")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    document = json.loads(done.stdout.decode("utf-8"))
    assert any(CJK in block["text"] for block in document["evidence"])


def test_a_piped_child_exits_3_under_fail_on_absent(project: Path) -> None:
    done = _query(project, "unicorn", "--quiet", "--fail-on", "absent")
    #  Text-mode stdout on Windows writes CRLF, as every Python CLI there does.
    assert (done.returncode, done.stdout.decode("utf-8").rstrip("\r\n")) == (3, "absent")
