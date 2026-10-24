"""`tools/gate_install.py`, G35's runner: it reads the G-install module's verdict and cannot pass
over nothing. **D920.**

The gate's body is `test_gate_install.py` and is tested there; what this file holds is the
runner's three rulings (one body, a run that checked nothing did not run, a bounded child) and
the row and step that make it a gate rather than a script.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_install.py"

# Loaded by path, as `test_gate_crash.py` loads its gate: `tools/` is not a distribution.
_SPEC = importlib.util.spec_from_file_location("omniweave_gate_install", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repository.
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


@pytest.mark.parametrize(
    ("code", "summary", "expected"),
    [
        (0, "117 passed, 1 skipped in 8.50s", gate.EXIT_CLEAN),
        (1, "1 failed, 116 passed, 1 skipped in 8.50s", gate.EXIT_FAIL),
        (1, "1 error in 0.30s", gate.EXIT_FAIL),
        (3, "117 passed in 8.50s", gate.EXIT_FAIL),
        (0, "1 failed, 116 passed in 8.50s", gate.EXIT_FAIL),
        (5, "no tests ran in 0.01s", gate.EXIT_NOT_RUN),
        (0, "118 skipped in 0.40s", gate.EXIT_NOT_RUN),
        (None, "", gate.EXIT_FAIL),
    ],
)
def test_the_verdict_never_passes_a_run_that_checked_nothing(
    code: int | None, summary: str, expected: int
) -> None:
    """Rulings 2 and 3: exit 5 or every case skipped is "did not run", and a killed run fails."""
    assert gate.verdict(code, summary)[0] == expected


def _module(tmp_path: Path, body: str) -> str:
    """A stand-in gate module, with a `pytest.ini` of its own beside it.

    Without the ini the child finds the repository's configuration from its cwd and walks the
    temp directory's ancestors, where under `-n auto` another worker's temp tree is being deleted
    (a `FileNotFoundError` at collection). The ini roots the child at `tmp_path`.
    """
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    path = tmp_path / "test_stand_in.py"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_a_passing_module_is_a_pass_and_a_failing_one_a_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    passing = _module(tmp_path, "def test_holds():\n    assert True\n")
    assert gate.main(["--module", passing]) == gate.EXIT_CLEAN
    assert "G35 ok  1 passed" in capsys.readouterr().out
    failing = _module(tmp_path, "def test_breaks():\n    assert False\n")
    assert gate.main(["--module", failing]) == gate.EXIT_FAIL
    assert "G35 FAIL" in capsys.readouterr().out


def test_a_module_that_skips_everything_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skipping = _module(tmp_path, "import pytest\n\n\n@pytest.mark.skip\ndef test_x():\n    pass\n")
    assert gate.main(["--module", skipping]) == gate.EXIT_NOT_RUN
    assert "G35 DID NOT RUN  no case ran" in capsys.readouterr().out
    assert gate.main(["--module", str(tmp_path / "absent.py")]) == gate.EXIT_NOT_RUN


def test_a_run_past_its_time_is_killed_and_fails(tmp_path: Path) -> None:
    slow = _module(tmp_path, "import time\n\n\ndef test_slow():\n    time.sleep(60)\n")
    assert gate.main(["--module", slow, "--timeout-s", "3"]) == gate.EXIT_FAIL


def test_the_register_row_and_the_test_job_step_name_this_runner() -> None:
    """G35 is a gate because a row names it and a CI step runs it, on every cell of the matrix."""
    register = tomllib.loads((REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(g for g in register["gate"] if g["id"] == "G35")
    assert row["runner"] == ["tools/gate_install.py"]
    assert row["jobs"] == ["test"]
    assert row["status"] == "law" and "pending" not in row, "ADR-16 made it law (D971)"
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    test_job = workflow.split("\n  test:\n", 1)[1].split("\n  golden:\n", 1)[0]
    assert "run: uv run tools/gate_install.py" in test_job
    assert gate.MODULE == "packages/omniweave/tests/unit/test_gate_install.py"
    assert (REPO_ROOT / gate.MODULE).is_file()
