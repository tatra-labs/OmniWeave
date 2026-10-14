"""Q-G27 tested as a program: `tools/gate_metric_rot.py`'s report and exit codes. D829.

The clock's arithmetic is `omniweave_conform.rot`'s and `test_conform_rot.py` holds it to the
plan; this file holds the program to its docstring: an absent tree passes and says so, a rotten
clock exits 1 with its fix, the edge is printed before it fails, and anything unreadable exits 2.

The gate is loaded by file path under a private name, as `test_gate_budgets.py` loads its gate,
and at module scope: `test_errors.py` reloads `omniweave_core.errors`, and a gate loaded after it
would catch a different `QualityError` class than the one `omniweave_conform.rot` raises.
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
    path = REPO / "tools" / "gate_metric_rot.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_metric_rot", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()

REGISTER = '[[gate]]\nmetric = "span_exact_rate"\nslice = "*"\n'


def _rows(metric: str, *versions: str) -> list[dict[str, Any]]:
    return [{"metric": metric, "corpus_id": "golden", "corpus_version": v} for v in versions]


def _paths(tmp_path: Path, rows: list[dict[str, Any]], register: str = REGISTER) -> list[str]:
    gates = tmp_path / "gates.toml"
    gates.write_bytes(register.encode())
    results = tmp_path / "results"
    (results / "parse").mkdir(parents=True)
    (results / "parse" / "s.json").write_bytes(json.dumps(rows).encode())
    return ["--gates", str(gates), "--results", str(results)]


def test_the_repository_passes() -> None:
    assert GATE.main([]) == GATE.EXIT_CLEAN


def test_an_absent_tree_passes_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = GATE.main(["--results", str(tmp_path / "none")])
    assert code == GATE.EXIT_CLEAN
    assert "Q-G27 ok  nothing published: no *.json under" in capsys.readouterr().out


def test_a_rotten_metric_fails_and_names_the_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        *_rows("field_acc", "1", "2", "3"),
        *_rows("order_acc", "1", "2"),
        *_rows("doc_acc", "3"),
        *_rows("span_exact_rate", "1", "2", "3"),
    ]
    assert GATE.main(_paths(tmp_path, rows)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "Q-G27  1 file(s), 3 ungated clock(s)",
        "        doc_acc on golden: 1 of 2 ungated release(s) (3)",
        "  ROT   field_acc on golden: 3 of 2 ungated release(s) (1, 2, 3)",
        "  edge  order_acc on golden: 2 of 2 ungated release(s) (1, 2)",
        "  fix: add a [[gate]] row for the metric to eval/gates.toml (a dated active_from"
        " counts), or stop publishing it",
        "Q-G27 FAIL  1 rotten metric clock(s)",
    ]


def test_the_edge_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(_paths(tmp_path, _rows("order_acc", "1", "2"))) == GATE.EXIT_CLEAN
    out = capsys.readouterr().out
    assert "  edge  order_acc" in out
    assert "fix:" not in out
    assert out.endswith("Q-G27 ok  0 rotten metric clock(s)\n")


def test_a_gate_row_stops_the_clock(tmp_path: Path) -> None:
    register = REGISTER + '\n[[gate]]\nmetric = "field_acc"\nactive_from = "v1.0"\n'
    assert GATE.main(_paths(tmp_path, _rows("field_acc", "1", "2", "3"), register)) == 0


@pytest.mark.parametrize(
    ("break_it", "match"),
    [
        ("gates", "Q-G27 DID NOT RUN"),
        ("register", "[[gate]] #1 names no metric"),
        ("tree", "parse/s.json: not JSON"),
        ("missing", "Q-G27 DID NOT RUN"),
    ],
)
def test_what_cannot_be_read_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], break_it: str, match: str
) -> None:
    argv = _paths(tmp_path, _rows("order_acc", "1"))
    if break_it == "gates":
        (tmp_path / "gates.toml").write_bytes(b"[[gate]\n")
    elif break_it == "register":
        (tmp_path / "gates.toml").write_bytes(b'[[gate]]\nslice = "*"\n')
        (tmp_path / "results" / "parse" / "s.json").unlink()
    elif break_it == "tree":
        (tmp_path / "results" / "parse" / "s.json").write_bytes(b"[{")
    else:
        (tmp_path / "gates.toml").unlink()
    assert GATE.main(argv) == GATE.EXIT_NOT_RUN
    assert match in capsys.readouterr().out


def test_a_bad_argument_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--no-such-flag"]) == GATE.EXIT_NOT_RUN
    capsys.readouterr()
