"""Q-G8's static half tested as a program: `tools/gate_measured_on.py`. D831.

The row rule is `omniweave_conform.scoreboard.unmeasured()`'s and `test_conform_scoreboard.py`
holds it to `MeasuredOn`. This file holds the program to its docstring: an absent tree passes
and says so, an unmeasured row exits 1 with its file, position, metric, slice and reason, and a
file that is not a list of rows exits 2.

Loaded by file path under a private name and at module scope, as `test_gate_metric_rot.py` loads
its gate.
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
    path = REPO / "tools" / "gate_measured_on.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_measured_on", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()

MEASURED = {
    "weights": "n/a",
    "weights_revision": "n/a",
    "runtime": "pdfium",
    "runtime_version": "6721",
    "sampling": "{}",
    "prompt_version": "n/a",
    "hardware": "ow-bench-1",
    "corpus": "golden@2026.09",
    "corpus_digest": "sha256:" + "ab" * 32,
    "harness_version": "0.1.0",
}


def _row(metric: str, **measured: Any) -> dict[str, Any]:
    return {"metric": metric, "slice_key": "__macro__", "measured_on": {**MEASURED, **measured}}


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
    assert "Q-G8 ok  nothing published: no *.json under" in capsys.readouterr().out


def test_every_row_measured_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = _results(tmp_path, {"parse/a.json": [_row("m"), _row("n")], "parse/b.json": [_row("m")]})
    assert GATE.main(argv) == GATE.EXIT_CLEAN
    assert capsys.readouterr().out.splitlines() == [
        "Q-G8  2 file(s), 3 row(s)",
        "Q-G8 ok  0 unmeasured row(s)",
    ]


def test_an_unmeasured_row_fails_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = {"metric": "doc_acc", "slice_key": "office/*", "measured_on": {}}
    files = {
        "parse/a.json": [_row("order_acc"), _row("field_acc", weights_revision="main")],
        "parse/b.json": [bare],
    }
    assert GATE.main(_results(tmp_path, files)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Q-G8  2 file(s), 3 row(s)"
    assert out[1].startswith(
        "  parse/a.json row 2 (field_acc@__macro__): MeasuredOn.weights_revision must be an exact"
    )
    assert out[2].startswith("  parse/b.json row 1 (doc_acc@office/*): measured_on has missing [")
    assert out[3:] == [
        "  fix: re-export with ow eval publish; a committed row is never edited by hand",
        "Q-G8 FAIL  2 unmeasured row(s)",
    ]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("[{", "parse/a.json: not JSON ("),
        ("{}", "parse/a.json: not a list of rows"),
        ("[1]", "parse/a.json: not a list of rows"),
    ],
)
def test_a_file_that_is_not_rows_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, match: str
) -> None:
    assert GATE.main(_results(tmp_path, {"parse/a.json": text})) == GATE.EXIT_NOT_RUN
    out = capsys.readouterr().out
    assert out.startswith("Q-G8 DID NOT RUN  ")
    assert match in out


def test_a_bad_argument_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--no-such-flag"]) == GATE.EXIT_NOT_RUN
    capsys.readouterr()
