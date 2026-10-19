"""`tools/check_out_determinism.py`: its inputs, its lines and its exits. D878.

The compiles are faked by replacing the tool's `run`, so nothing here spawns; the real run is
`omniweave-conform`'s conform tier and V10-10's instrument. Loaded by file path under a private
name at module scope, as `test_gate_leakage.py` loads its gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from omniweave_conform.out_determinism import Compile, judge

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "check_out_determinism.py"
    spec = importlib.util.spec_from_file_location("_owcheck_out_determinism", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load()
A = Compile("in-process a", "1" * 64, "5" * 64, {"x.xml": "7" * 64})
B = Compile("PYTHONHASHSEED=0", "2" * 64, "5" * 64, {"x.xml": "8" * 64})


def _faked(monkeypatch: pytest.MonkeyPatch, compiles: list[Compile]) -> list[str]:
    seen: list[str] = []

    def fake(target: Any, **_kw: Any) -> Any:
        seen.append(target.target)
        return judge(target.target, ("part",), compiles)

    monkeypatch.setattr(TOOL, "run", fake)
    return seen


def test_every_register_target_runs_and_agreement_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _faked(monkeypatch, [A, A])
    assert TOOL.main([]) == 0
    out = capsys.readouterr().out.splitlines()
    assert seen == ["docx", "pptx"]
    assert out[0] == "docx  declares part; part 2 of 2 agree, byte 2 of 2"
    assert out[-1] == "OUT13 ok  2 target(s), one cell; the nine-cell matrix is CI's"


def test_a_disagreement_exits_1_naming_the_compile_and_the_member(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _faked(monkeypatch, [A, B])
    assert TOOL.main(["--target", "pptx"]) == 1
    out = capsys.readouterr().out
    assert "  DIFFER part: PYTHONHASHSEED=0 is sha256:222222222222" in out
    assert f"x.xml: {'7' * 12} -> {'8' * 12}" in out
    assert out.splitlines()[-1].startswith("OUT13 FAILED  1 target(s)")


def test_no_such_target_or_no_register_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _faked(monkeypatch, [A])
    assert TOOL.main(["--target", "video"]) == 2
    assert "names no [[target]] among ['video']" in capsys.readouterr().out
    assert TOOL.main(["--register", str(tmp_path / "absent.toml")]) == 2
    assert capsys.readouterr().out.startswith("OUT13 did not run: FileNotFoundError")
