"""`bench/serve/first_answer.py` as a process: `ow install` -> `ow add` -> `ow query`. V01-15.

Six documents rather than 00:716's hundred, so the tier stays inside its budget. The hundred is the
acceptance row's own run (`tools/acceptance_v01.py`). What is asserted here is that the three verbs
run as real children under a home of their own, the Answer cites the needle and states its notice
period, the page clause is reported false for an office folder, as D615 says it must be, and `ow
uninstall` leaves that home byte-identical (16:736-737).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

SCRIPT = Path(__file__).resolve().parents[4] / "bench" / "serve" / "first_answer.py"
TIMEOUT_S = 300


def test_three_children_answer_the_needle_question_within_the_budget(tmp_path: Path) -> None:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    done = run_captured(
        (sys.executable, str(SCRIPT), "--docs", "6", "--json", "--work", str(tmp_path)),
        stdin=b"",
        cwd=str(tmp_path),
        env=keep,
        timeout_s=TIMEOUT_S,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    result = json.loads(done.stdout)
    assert result["passed"] is True
    assert set(result["phases"]) == {"install", "add", "query"}
    assert result["first_answer_seconds"] <= result["budget_s"]
    judged = result["judgement"]
    assert (judged["needle_cited"], judged["answered"]) == (True, True)
    assert (judged["paged"], judged["page_kinds"]) == (False, ["stream"])
    #  16:736-737: the uninstall left the run's own home byte-identical to before the install.
    assert (result["reversed"], result["residue"]) == (True, [])
    assert not (tmp_path / "home" / ".claude.json").exists()
