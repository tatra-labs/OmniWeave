"""`tools/ci_job_seconds.py`: V01-14's CI budgets over a saved `gh run view --json jobs`. D970.

The tool reads real timings through `gh`; these tests hand it a saved document instead, so they
need no network. Loaded by file path, as every `tools/` gate's test loads its tool.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ci_job_seconds", REPO / "tools" / "ci_job_seconds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load()

START = "2026-10-23T16:00:00Z"


def _job(name: str, seconds: int, conclusion: str = "success") -> dict[str, str]:
    minutes, rest = divmod(seconds, 60)
    return {
        "name": name,
        "startedAt": START,
        "completedAt": f"2026-10-23T16:{minutes:02d}:{rest:02d}Z",
        "conclusion": conclusion,
    }


def _run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *jobs: dict[str, str]
) -> tuple[int, str]:
    saved = tmp_path / "jobs.json"
    saved.write_text(json.dumps({"jobs": list(jobs)}), encoding="utf-8")
    code = tool.main(["--jobs-json", str(saved)])
    return code, capsys.readouterr().out


GATES = "gates (G1 G3 G4)"
CONFORM = "conform (G15 socket-blocked, G16)"
PARITY = "parity (offline, GPU-free, Node-free)"


def test_the_budgets_are_v01_14s() -> None:
    """00-vision.md's V01-14: gates <= 3 min, conform <= 5 min, parity <= 7 min."""
    assert tool.BUDGETS_S == {"gates": 180, "conform": 300, "parity": 420}


def test_every_job_inside_its_budget_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(tmp_path, capsys, _job(GATES, 96), _job(CONFORM, 300), _job(PARITY, 9))
    assert code == 0
    assert out.splitlines()[0].startswith("V01-14 ok")
    assert "conform  ok      300 s of 300 s" in out, "the budget is inclusive"


def test_a_job_over_its_budget_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(tmp_path, capsys, _job(GATES, 181), _job(CONFORM, 32), _job(PARITY, 9))
    assert code == 1
    assert "gates    FAIL    181 s of 180 s" in out


def test_parity_must_have_succeeded(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(
        tmp_path, capsys, _job(GATES, 96), _job(CONFORM, 32), _job(PARITY, 9, "failure")
    )
    assert code == 1
    assert "parity   FAIL" in out


def test_a_missing_job_did_not_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(tmp_path, capsys, _job(GATES, 96), _job(PARITY, 9))
    assert code == 2
    assert "conform  DID NOT RUN: no job named 'conform' in the run" in out
    assert out.splitlines()[0].startswith("V01-14 DID NOT RUN")


def test_an_unreadable_document_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tool.main(["--jobs-json", str(tmp_path / "absent.json")]) == 2
    assert capsys.readouterr().out.startswith("V01-14 DID NOT RUN")
