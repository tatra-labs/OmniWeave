"""Q-G19's row clause and Q-G21's pairing tested as a program: `tools/gate_results.py`. D832.

The rules are `omniweave_conform.scoreboard`'s `check()` and `unpaired()`, and
`test_conform_scoreboard.py` holds them to the plan. This file holds the program to its
docstring. An absent tree passes and says so. A failing row exits 1 with its gate, file and
reason, and each gate gets its own verdict line. A file that is not a list of rows exits 2.

Loaded by file path under a private name and at module scope, as `test_gate_metric_rot.py` loads
its gate. `test_errors.py` reloads `omniweave_core.errors`, and the `QualityError` this program
catches must be the class `scoreboard.check()` raises.
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
    path = REPO / "tools" / "gate_results.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_results", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()


def _row(metric: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "r1",
        "suite": "extract",
        "subject": "s",
        "metric": metric,
        "slice_key": "__macro__",
        "value": 0.5,
        "n": 40,
        "ci_lo": 0.3,
        "ci_hi": 0.7,
        "method": "closed_form",
        "truth_kind": "human",
        "measured_on": {"runtime": "x"},
        "witness": "ci",
        "unpinned": False,
        "entrant_bias": False,
        "not_measured": ["handwriting"],
        "confounders": ["one embedder"],
        "standing": "RANKED",
    }
    row.update(over)
    return row


def _results(tmp_path: Path, files: dict[str, Any]) -> list[str]:
    root = tmp_path / "results"
    for rel, rows in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((rows if isinstance(rows, str) else json.dumps(rows)).encode())
    return ["--results", str(root)]


def test_the_repository_passes() -> None:
    assert GATE.main([]) == GATE.EXIT_CLEAN


def test_an_absent_tree_passes_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GATE.main(["--results", str(tmp_path / "none")]) == GATE.EXIT_CLEAN
    assert "Q-G19/Q-G21 ok  nothing published: no *.json under" in capsys.readouterr().out


def test_a_complete_paired_tree_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = {"extract/s.json": [_row("doc_acc"), _row("field_acc")], "parse/t.json": [_row("m")]}
    assert GATE.main(_results(tmp_path, files)) == GATE.EXIT_CLEAN
    assert capsys.readouterr().out.splitlines() == [
        "Q-G19/Q-G21  2 file(s), 3 row(s)",
        "Q-G19 ok  0 row(s) missing or empty",
        "Q-G21 ok  0 metric(s) without a partner",
    ]


def test_each_gate_names_its_own_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "extract/s.json": [_row("doc_acc", confounders=[]), _row("field_acc")],
        "extract/t.json": [_row("hallucination_rate")],
    }
    assert GATE.main(_results(tmp_path, files)) == GATE.EXIT_FAIL
    assert capsys.readouterr().out.splitlines() == [
        "Q-G19/Q-G21  2 file(s), 3 row(s)",
        "  Q-G19 extract/s.json row 1: extract/s doc_acc@__macro__: confounders empty; every "
        "benchmark has a scope",
        "  Q-G21 extract/t.json: hallucination_rate@__macro__ in run r1 ships without field_acc",
        "  fix: re-export with ow eval publish after fixing the run; never edit a committed row",
        "Q-G19 FAIL  1 row(s) missing or empty",
        "Q-G21 FAIL  1 metric(s) without a partner",
    ]


def test_one_gate_failing_alone_still_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    row = _row("m")
    del row["witness"]
    assert GATE.main(_results(tmp_path, {"parse/a.json": [row]})) == GATE.EXIT_FAIL
    out = capsys.readouterr().out
    assert "  Q-G19 parse/a.json row 1: extract/s m@__macro__: missing ['witness']" in out
    assert "Q-G21 ok  0 metric(s) without a partner" in out


def test_pairing_failing_alone_still_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {"extract/s.json": [_row("field_acc")]}
    assert GATE.main(_results(tmp_path, files)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out
    assert "Q-G19 ok  0 row(s) missing or empty" in out
    assert "Q-G21 FAIL  1 metric(s) without a partner" in out


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("[{", "parse/a.json: not JSON ("),
        ("{}", "parse/a.json: not a list of rows"),
        ('["x"]', "parse/a.json: not a list of rows"),
    ],
)
def test_a_file_that_is_not_rows_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, match: str
) -> None:
    assert GATE.main(_results(tmp_path, {"parse/a.json": text})) == GATE.EXIT_NOT_RUN
    out = capsys.readouterr().out
    assert out.startswith("Q-G19/Q-G21 DID NOT RUN  ")
    assert match in out


def test_a_bad_argument_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--no-such-flag"]) == GATE.EXIT_NOT_RUN
    capsys.readouterr()


def test_the_committed_tree_holds_and_the_gates_job_checks_it() -> None:
    """D922: `eval/results` is published, so the gates job runs the static checks over it and the
    committed rows hold them here too, rather than a CI step being the only place they are read."""
    assert (REPO / "eval" / "results").is_dir()
    assert GATE.main([]) == GATE.EXIT_CLEAN
    for name in ("gate_measured_on", "gate_metric_rot"):
        spec = importlib.util.spec_from_file_location(
            f"_owgate_{name}", REPO / "tools" / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None, name
        other = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = other
        spec.loader.exec_module(other)
        assert other.main([]) == other.EXIT_CLEAN, name
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gates_job = workflow.split("\n  gates:\n", 1)[1].split("\n  test:\n", 1)[0]
    for script in ("gate_measured_on.py", "gate_results.py", "gate_metric_rot.py"):
        assert f"uv run tools/{script}" in gates_job, script
