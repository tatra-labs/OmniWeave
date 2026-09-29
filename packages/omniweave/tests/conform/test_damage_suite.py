"""Q-G7's paired-damage half, end to end: every built Injector damaged, read, fixed, read again.

`tools/ow_damage.py` is P6's `ow eval run --suite absence --deterministic-half`. Each pair builds
real stores through `ow add`, reads the real `Verdict` of a real query, and executes the emitted
`DegradeCause.fix` with no shell, so this is the conform tier's by Q-G25's rule: it spawns
workers. 13:1297's three assertions, and the counterfactual before them, are each a line of the
report, and every one must hold on every pair: `degradation_detection` is hard at 1.000.

It runs as a child, as `test_bench_agent_process.py` runs its script: `tools/` is not a
distribution, and importing it here would be a `sys.path` mutation that leaks into later tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from omniweave_conform.damage import INJECTORS, TABLE
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

SCRIPT = Path(__file__).resolve().parents[4] / "tools" / "ow_damage.py"
TIMEOUT_S = 600
CLAUSES = ["counterfactual", "degraded", "named cause", "fix fixes"]


def test_every_built_injector_degrades_to_its_named_cause_and_its_fix_fixes_it(
    tmp_path: Path,
) -> None:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    report_path = tmp_path / "report.json"
    done = run_captured(
        (
            sys.executable,
            str(SCRIPT),
            "--deterministic-half",
            "--keep",
            str(tmp_path / "work"),
            "--json",
            str(report_path),
        ),
        stdin=b"",
        cwd=str(tmp_path),
        env=keep,
        timeout_s=TIMEOUT_S,
    )
    shown = (done.stdout + done.stderr).decode("utf-8", "replace")[-4000:]
    assert done.returncode == 0, shown
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["metric"] == "degradation_detection"
    assert report["value"] == 1.0
    assert report["built"] == list(INJECTORS)
    assert report["owed"] == [row.name for row in TABLE if row.name not in INJECTORS]
    assert {pair["injector"] for pair in report["pairs"]} == set(INJECTORS)
    for pair in report["pairs"]:
        assert [clause["name"] for clause in pair["clauses"]] == CLAUSES, pair
        assert all(clause["ok"] for clause in pair["clauses"]), pair
    population = f"population: {len(INJECTORS)} of {len(TABLE)} Injectors built"
    assert population in done.stdout.decode("utf-8", "replace")
