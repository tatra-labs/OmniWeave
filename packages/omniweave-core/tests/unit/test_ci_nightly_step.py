"""`tools/ci_nightly_step.py`: V10-14's nightly pdfium step over a saved `gh run view --json jobs`.
D974.

The tool reads the verdict through `gh`; these tests hand it a saved document instead, so they
need no network. Loaded by file path, as every `tools/` gate's test loads its tool.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ci_nightly_step", REPO / "tools" / "ci_nightly_step.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load()

PDFIUM = "Q-G4 pdfium axis (nightly) -- the same shapes under the previous pdfium minor"


def _golden(conclusion: str | None, *, step: str = PDFIUM) -> dict[str, Any]:
    return {
        "name": "golden (Reductions + Counters + Cassette replay)",
        "conclusion": "success",
        "steps": [
            {"name": "Q-G4 -- shape byte-identical across the nine cells", "conclusion": "success"},
            {"name": step, "conclusion": conclusion},
        ],
    }


@pytest.mark.parametrize(
    ("conclusion", "code"),
    [("success", 0), ("failure", 1), ("skipped", 2), ("cancelled", 2), (None, 2)],
)
def test_the_verdict_is_the_pdfium_steps_own(conclusion: str | None, code: int) -> None:
    """A skipped or cancelled step, or one with no conclusion, did not run, and is never a pass."""
    assert tool.judge([_golden(conclusion)])[0] == code


def test_another_job_failing_does_not_move_the_verdict() -> None:
    gates = {"name": "gates (G1 ...)", "conclusion": "failure", "steps": []}
    assert tool.judge([gates, _golden("success")]) == (0, f"{PDFIUM}: success")


def test_a_missing_job_or_step_did_not_run() -> None:
    assert tool.judge([])[0] == 2
    assert tool.judge([_golden("success", step="Q-G4 something else")])[0] == 2


def test_main_reads_a_saved_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    saved = tmp_path / "jobs.json"
    saved.write_text(json.dumps({"jobs": [_golden("success")]}), encoding="utf-8")
    assert tool.main(["--jobs-json", str(saved)]) == 0
    assert capsys.readouterr().out.startswith(f"V10-14 ok  {saved}\n")
    saved.write_text(json.dumps({"jobs": [_golden("failure")]}), encoding="utf-8")
    assert tool.main(["--jobs-json", str(saved)]) == 1
    assert tool.main(["--jobs-json", str(tmp_path / "absent.json")]) == 2


def test_the_step_it_reads_is_the_one_ci_yml_runs_on_the_schedule() -> None:
    """The prefix is the step's name in `ci.yml`, in the `golden` job, schedule-gated (D966)."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    golden = workflow.split("\n  golden:\n", 1)[1].split("\n  conform:\n", 1)[0]
    assert f'- name: "{tool.STEP}' in golden
    step = golden.split(f'- name: "{tool.STEP}', 1)[1].split("\n      - ", 1)[0]
    assert "if: github.event_name == 'schedule'" in step
    assert "--pdfium-minors 2 --cells 9" in step
    assert golden.split("\n", 1)[0].strip().startswith(f'name: "{tool.JOB}')
