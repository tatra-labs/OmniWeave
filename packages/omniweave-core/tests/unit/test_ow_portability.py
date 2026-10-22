"""`tools/ow_portability.py`: the parts table, checked or written. D903.

Every compile is faked through `portability.parts`, so these run in the unit tier; the real
compiles are the roundtrip suite's and `test_conform_eval_run.py`'s.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform import portability

REPO = Path(__file__).resolve().parents[4]

_spec = importlib.util.spec_from_file_location(
    "_owtool_ow_portability", REPO / "tools" / "ow_portability.py"
)
assert _spec is not None and _spec.loader is not None
TOOL = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = TOOL
_spec.loader.exec_module(TOOL)


def _root(tmp_path: Path) -> Path:
    (tmp_path / "eval").mkdir()
    shutil.copy(REPO / "eval" / "gates.toml", tmp_path / "eval" / "gates.toml")
    return tmp_path


def _compiles(monkeypatch: pytest.MonkeyPatch, members: dict[str, str]) -> None:
    def parts(target: Any) -> tuple[str, str, str, dict[str, str]]:
        return f"compile.{target.target}.native", "0.1.0", "f" * 64, dict(members)

    monkeypatch.setattr(TOOL, "parts", parts)


def test_write_then_check_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    _compiles(monkeypatch, {"a.xml": "1" * 64})
    assert TOOL.main(["--root", str(root), "--write"]) == TOOL.EXIT_CLEAN
    assert set(portability.read_parts(root)) == {"docx", "pptx"}
    assert TOOL.main(["--root", str(root)]) == TOOL.EXIT_CLEAN
    assert capsys.readouterr().out.splitlines()[-1] == "portability ok  every part matches"


def test_a_part_that_moved_fails_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    _compiles(monkeypatch, {"a.xml": "1" * 64})
    TOOL.main(["--root", str(root), "--write"])
    _compiles(monkeypatch, {"a.xml": "2" * 64})
    assert TOOL.main(["--root", str(root)]) == TOOL.EXIT_FAIL
    out = capsys.readouterr().out.splitlines()
    assert "  FAIL  docx: a.xml: differs" in out
    assert out[-1] == "portability FAIL  2 difference(s)"


def test_what_cannot_be_compared_did_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    _compiles(monkeypatch, {"a.xml": "1" * 64})
    assert TOOL.main(["--root", str(root)]) == TOOL.EXIT_NOT_RUN
    assert "no readable eval/portability.toml" in capsys.readouterr().out

    def broken(_target: Any) -> Any:
        raise RuntimeError("no compiler")

    monkeypatch.setattr(TOOL, "parts", broken)
    assert TOOL.main(["--root", str(root), "--write"]) == TOOL.EXIT_NOT_RUN
    assert "a compile failed: RuntimeError: no compiler" in capsys.readouterr().out
    (root / "eval" / "gates.toml").write_bytes(b"")
    assert TOOL.main(["--root", str(root)]) == TOOL.EXIT_NOT_RUN
    assert "names no [[target]]" in capsys.readouterr().out
    assert TOOL.main(["--bogus"]) == TOOL.EXIT_NOT_RUN


def test_the_pptx_row_also_yields_v10_10_s_forty_unit_golden(tmp_path: Path) -> None:
    """D914: the 40-unit golden, generated under the scratch directory, compiled with the `pptx`
    row's card and config, so every CI cell holds V10-10's deck to the committed table."""
    register = TOOL.tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
    rows = TOOL.targets(register, REPO)
    (golden40,) = TOOL._golden40(REPO, rows, str(tmp_path))
    (pptx,) = [row for row in rows if row.target == "pptx"]
    assert golden40.target == TOOL.GOLDEN40 == "pptx@golden40"
    assert (golden40.card, golden40.config) == (pptx.card, pptx.config)
    assert golden40.golden == tmp_path / "pptx"
    assert len(list((tmp_path / "pptx" / "il").glob("u*.svg"))) == 40
    assert "pptx@golden40" in portability.read_parts(REPO)
    assert TOOL._golden40(REPO, tuple(r for r in rows if r.target != "pptx"), str(tmp_path)) == ()


def test_this_cell_reproduces_the_committed_table_forty_unit_deck_included(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D914: the CI step's own command, here: real in-process compiles against the real table."""
    assert TOOL.main([]) == TOOL.EXIT_CLEAN
    out = capsys.readouterr().out.splitlines()
    assert "portability  pptx@golden40: 116 of 116 part(s) match" in out
    assert out[-1] == "portability ok  every part matches"
