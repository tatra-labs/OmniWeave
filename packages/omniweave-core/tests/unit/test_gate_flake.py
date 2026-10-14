"""Q-G18 tested as a program: `tools/gate_flake.py`, over a real `.oweval`. D836.

The window, the line and the register are `omniweave_conform.flake`'s, which
`test_conform_flake.py` holds to the plan. This file holds the program to its docstring:
- each absent input is named;
- `eval_flake` rows are read back through `oweval.flakes()`;
- an unquarantined flaky test exits 1;
- `--window` takes `<n>d`;
- anything unreadable exits 2.

Loaded by file path under a private name and at module scope, as `test_gate_metric_rot.py` loads
its gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omniweave_core.store.oweval import Batch, Flake, flakes, open_oweval
from omniweave_core.store.oweval import write as store

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_flake.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_flake", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
TODAY = "2026-10-14"

REGISTER = """\
[gate]
owner = "quality"
review_by = "2027-06-01"

[[quarantined]]
test_id = "tests/unit/test_q.py::test_quarantined"
since = "2026-09-20"
expires = "2026-11-10"
owner = "quality"
reason = "one run in twelve"
"""


def _oweval(path: Path, *rows: Flake) -> Path:
    connection = open_oweval(path)
    try:
        store(connection, Batch(flake=rows))
    finally:
        connection.close()
    return path


def _argv(tmp_path: Path, *extra: str, register: str | None = REGISTER) -> list[str]:
    quarantine = tmp_path / "quarantine.toml"
    if register is not None:
        quarantine.write_bytes(register.encode())
    rows = (
        Flake("tests/unit/test_a.py::test_flaky", "2026-10-10", 40, 3, 3),
        Flake("tests/unit/test_q.py::test_quarantined", "2026-10-10", 40, 3, 0),
        Flake("tests/unit/test_b.py::test_old", "2026-08-01", 40, 30, 0),
    )
    oweval = tmp_path / "e.oweval"
    if not oweval.exists():
        _oweval(oweval, *rows)
    return ["--oweval", str(oweval), "--quarantine", str(quarantine), "--today", TODAY, *extra]


def test_the_repository_passes_and_names_what_is_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert GATE.main(["--window", "30d", "--today", TODAY]) == GATE.EXIT_CLEAN
    out = capsys.readouterr().out
    assert "  eval_flake   not run: no .oweval at " in out
    assert "  quarantine   absent: no quarantine.toml, so nothing is quarantined" in out


def test_the_store_reads_back_its_flake_rows(tmp_path: Path) -> None:
    rows = (Flake("t", "2026-10-02", 3, 1, 1), Flake("a", "2026-10-01", 2, 0, 0))
    connection = open_oweval(_oweval(tmp_path / "e.oweval", *rows))
    try:
        assert flakes(connection) == (rows[1], rows[0])
    finally:
        connection.close()


def test_an_unquarantined_flaky_test_fails_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GATE.main(_argv(tmp_path, "--window", "30d")) == GATE.EXIT_FAIL
    assert capsys.readouterr().out.splitlines() == [
        "Q-G18  as of 2026-10-14, a 30-day window",
        "  eval_flake   2 test(s) with runs in the window",
        "  quarantine   1 row(s)",
        "  FAIL  tests/unit/test_a.py::test_flaky: 3 of 40 runs failed (7.5%, 3 green on "
        "re-run); quarantine it to informational",
        "Q-G18 FAIL  1 finding(s)",
    ]


def test_the_window_decides_what_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The August row is 74 days back: inside a 90-day window, `test_old` is flaky too."""
    assert GATE.main(_argv(tmp_path, "--window", "90d")) == GATE.EXIT_FAIL
    assert "  FAIL  tests/unit/test_b.py::test_old: 30 of 40 runs" in capsys.readouterr().out
    assert GATE.main(_argv(tmp_path, "--window", "1d")) == GATE.EXIT_CLEAN


def test_a_recovered_quarantined_test_is_a_note_and_not_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    oweval = _oweval(tmp_path / "e.oweval", Flake("t_ok", "2026-10-10", 100, 1, 0))
    quarantine = tmp_path / "quarantine.toml"
    quarantine.write_bytes(
        REGISTER.replace("tests/unit/test_q.py::test_quarantined", "t_ok").encode()
    )
    argv = ["--oweval", str(oweval), "--quarantine", str(quarantine), "--today", TODAY]
    assert GATE.main(argv) == GATE.EXIT_CLEAN
    out = capsys.readouterr().out.splitlines()
    assert out[-2:] == [
        "  note  t_ok: no longer flaky over the window; it may return to its tier",
        "Q-G18 ok  0 finding(s)",
    ]


def test_without_a_register_every_flaky_test_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GATE.main(_argv(tmp_path, register=None)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out
    assert "  quarantine   absent: no quarantine.toml" in out
    assert "Q-G18 FAIL  2 finding(s)" in out


@pytest.mark.parametrize(
    ("register", "match"),
    [
        ("[[quarantined]\n", "Q-G18 DID NOT RUN"),
        ('[[quarantined]]\ntest_id = "t"\n', "missing ["),
    ],
)
def test_a_register_that_cannot_be_read_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], register: str, match: str
) -> None:
    assert GATE.main(_argv(tmp_path, register=register)) == GATE.EXIT_NOT_RUN
    assert match in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--window", "30"], ["--window", "0d"], ["--today", "x"]])
def test_a_bad_argument_did_not_run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(argv) == GATE.EXIT_NOT_RUN
    capsys.readouterr()
