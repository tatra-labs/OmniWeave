"""The scripted agent's omniweave arm against a real `ow serve --mcp` child (ADR-14 D14.3).

`bench/serve/smoke.py` drives the agent's real path end to end: `ow add` over a small generated
office folder, then `ow serve --mcp` reached through the official MCP client, as a host reaches
it, with a scripted model standing in for a real one. It needs no key, and records nothing.

It runs as a child, as `test_first_answer_process.py` runs its script: `bench/serve/` is not a
distribution, so importing it here would be an undeclared dependency (DR18) or a `sys.path`
mutation that leaks into later tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

SCRIPT = Path(__file__).resolve().parents[4] / "bench" / "serve" / "smoke.py"
TIMEOUT_S = 300


def test_the_omniweave_arm_asks_a_real_server_and_the_answer_names_the_needle(
    tmp_path: Path,
) -> None:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    done = run_captured(
        (sys.executable, str(SCRIPT), "--work", str(tmp_path), "--docs", "6"),
        stdin=b"",
        cwd=str(tmp_path),
        env=keep,
        timeout_s=TIMEOUT_S,
    )
    assert done.returncode == 0, (done.stdout + done.stderr).decode("utf-8", "replace")[-3000:]
    report = json.loads(done.stdout)
    assert report["passed"] is True
    assert {"ow_query", "ow_open"} <= set(report["tools"])
    assert report["instructions_chars"] > 0
    assert report["system_ends_with_instructions"] is True
    assert report["first_call"] == "ow_query"
    assert (report["result_is_error"], report["needle_named"]) == (False, True)
