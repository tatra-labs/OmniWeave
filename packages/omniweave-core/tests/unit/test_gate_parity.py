"""Q-G22 tested as a program: `tools/gate_parity.py`. D842.

The two steps run through an injected runner and clock, so this file holds the gate to its
docstring without running the suite inside the suite:
- the three flags;
- each constraint's environment;
- the ceiling read from `eval/perf.toml`;
- the steps, their order and the time each is given;
- every exit.

The blocker is the one part run for real. A fresh interpreter under `arm()`'s environment is
refused a TEST-NET connection and a name lookup, and still reaches a loopback listener, since a
hook that only a fake ever met would be the instrument G15's negative control exists to catch.

Loaded by file path under a private name and at module scope, as `test_gate_flake.py` loads its
gate.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess  # noqa: TID251 -- the blocker is held to a real interpreter.
import sys
import time
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_parity.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_parity", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
FLAGS = ["--offline", "--no-gpu", "--no-node"]
UV = str(Path("bin") / "uv")


def _which(name: str, path: str | None = None) -> str | None:
    """`node` lives only in `node-dir`, and `uv` anywhere on a non-empty PATH."""
    entries = (path or "").split(os.pathsep)
    if name == "node":
        return "node-dir/node" if "node-dir" in entries else None
    return UV if name == "uv" and any(entries) else None


class _Runs:
    """A runner that records each step and answers from a script."""

    def __init__(self, *codes: int | None, seconds: tuple[float, ...] = (10.0, 100.0)) -> None:
        self.codes = list(codes)
        self.seconds = list(seconds)
        self.now = 0.0
        self.calls: list[tuple[list[str], dict[str, str], float]] = []

    def run(self, argv: list[str], env: Any, log: Path, timeout: float) -> int | None:
        self.calls.append((argv, dict(env), timeout))
        self.now += self.seconds[len(self.calls) - 1]
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as sink:
            sink.write(f"step {len(self.calls)}\n")
        return self.codes[len(self.calls) - 1]

    def clock(self) -> float:
        return self.now


def _main(
    capsys: pytest.CaptureFixture[str],
    runs: _Runs,
    *argv: str,
    env: dict[str, str] | None = None,
    blocks: bool = True,
) -> tuple[int, str]:
    code = GATE.main(
        [*argv],
        env=env if env is not None else {"PATH": os.pathsep.join(["bin", "node-dir"])},
        run=runs.run,
        clock=runs.clock,
        which=_which,
        blocks=lambda _env, _log: blocks,
    )
    return code, capsys.readouterr().out


# --- ruling 1: the flags ---------------------------------------------------------------------


@pytest.mark.parametrize("dropped", FLAGS)
def test_a_run_missing_a_constraint_flag_did_not_run(
    capsys: pytest.CaptureFixture[str], dropped: str
) -> None:
    runs = _Runs(0, 0)
    code, out = _main(capsys, runs, *[f for f in FLAGS if f != dropped])
    assert code == 2
    assert out == f"Q-G22 DID NOT RUN  {dropped} not given: a run without it is not parity\n"
    assert runs.calls == []


def test_all_three_missing_are_named_together(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(capsys, _Runs())
    assert code == 2
    assert out.startswith("Q-G22 DID NOT RUN  --offline, --no-gpu, --no-node not given")


def test_an_unknown_flag_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(capsys, _Runs(), *FLAGS, "--strict")[0] == 2


# --- rulings 2-4: each constraint's environment -------------------------------------------------


def test_offline_sets_the_four_switches_and_keeps_the_rest() -> None:
    env = GATE.offline_env({"HOME": "h", "UV_OFFLINE": "0"})
    assert env == {
        "HOME": "h",
        "UV_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PIP_NO_INDEX": "1",
    }


def test_gpu_free_hides_every_device() -> None:
    env = GATE.no_gpu_env({"CUDA_VISIBLE_DEVICES": "0,1"})
    names = ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES")
    assert env == dict.fromkeys(names, "")


def test_node_free_drops_each_node_directory_and_keeps_the_case_of_path() -> None:
    env = GATE.no_node_env({"Path": os.pathsep.join(["bin", "node-dir", "", "lib"])}, _which)
    assert env == {"Path": os.pathsep.join(["bin", "lib"])}
    assert GATE.no_node_env({}, _which) == {"PATH": ""}


def _cwd_node(name: str, path: str | None = None) -> str | None:
    """`node` in no PATH entry alone, yet found on the joined PATH: Windows' current directory."""
    if name == "node":
        return "./node.exe" if path == os.pathsep.join(["bin", "lib"]) else None
    return UV if name == "uv" and path else None


def test_node_that_still_resolves_is_refused() -> None:
    with pytest.raises(ValueError, match=r"node still resolves at \./node\.exe"):
        GATE.no_node_env({"PATH": os.pathsep.join(["bin", "lib"])}, _cwd_node)


def test_node_on_path_after_the_strip_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    runs = _Runs(0, 0)
    code = GATE.main(
        FLAGS,
        env={"PATH": os.pathsep.join(["bin", "lib"])},
        run=runs.run,
        clock=runs.clock,
        which=_cwd_node,
        blocks=lambda _env, _log: True,
    )
    assert code == 2
    assert capsys.readouterr().out.startswith(
        "Q-G22 DID NOT RUN  node still resolves at ./node.exe"
    )
    assert runs.calls == []


def test_arm_puts_the_blocker_first_on_pythonpath(tmp_path: Path) -> None:
    env = GATE.arm(tmp_path, {"PYTHONPATH": "lib"})
    assert env["PYTHONPATH"] == os.pathsep.join([str(tmp_path), "lib"])
    assert (tmp_path / "sitecustomize.py").read_bytes() == GATE.BLOCKER.encode()
    assert GATE.arm(tmp_path, {"PythonPath": ""}) == {"PythonPath": str(tmp_path)}


# --- ruling 6: the ceiling -----------------------------------------------------------------------


def test_the_ceiling_is_the_budget_rows_value_plus_tolerance() -> None:
    shipped = tomllib.loads((REPO / "eval" / "perf.toml").read_text(encoding="utf-8"))
    assert GATE.ceiling(shipped) == 600.0
    row = {"id": "contributor_parity_s", "value": 10, "tol_abs": 2.5}
    assert GATE.ceiling({"budget": [{"id": "x", "value": 1}, row]}) == 12.5
    assert GATE.ceiling({"budget": [{"id": "contributor_parity_s", "value": 7}]}) == 7.0


@pytest.mark.parametrize(
    "perf",
    [
        {},
        {"budget": {"id": "contributor_parity_s"}},
        {"budget": [{"id": "contributor_parity_s", "value": "600"}]},
        {"budget": [{"id": "contributor_parity_s", "value": 420, "tol_abs": True}]},
    ],
)
def test_a_missing_or_unreadable_row_is_refused(perf: dict[str, Any]) -> None:
    with pytest.raises(
        ValueError, match="no numeric \\[\\[budget\\]\\] row 'contributor_parity_s'"
    ):
        GATE.ceiling(perf)


def test_no_budget_row_did_not_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    perf = tmp_path / "perf.toml"
    perf.write_bytes(b"")
    code, out = _main(capsys, _Runs(0, 0), *FLAGS, "--perf", str(perf))
    assert code == 2
    assert out.startswith("Q-G22 DID NOT RUN  eval/perf.toml has no numeric [[budget]] row")


# --- rulings 5-7: the run ------------------------------------------------------------------------


def test_both_steps_run_in_order_under_the_constraints(capsys: pytest.CaptureFixture[str]) -> None:
    runs = _Runs(0, 0)
    code, out = _main(capsys, runs, *FLAGS)
    assert code == 0
    (sync, sync_env, sync_budget), (tests, tests_env, tests_budget) = runs.calls
    assert sync == [UV, "sync", "--frozen", "--all-packages", "--group", "dev", "--offline"]
    assert tests[:4] == [UV, "run", "--frozen", "--no-sync"]
    assert tests[4:] == [
        "pytest",
        "-n",
        "auto",
        "-q",
        "-m",
        "not conform",
        "-p",
        "no:cacheprovider",
    ]
    assert (sync_budget, tests_budget) == (600.0, 590.0)
    for env in (sync_env, tests_env):
        assert env["UV_OFFLINE"] == "1"
        assert env["CUDA_VISIBLE_DEVICES"] == ""
        assert env["PATH"] == "bin"
        assert env["PYTHONPATH"].endswith(
            "ow-parity-" + env["PYTHONPATH"].rsplit("ow-parity-", 1)[1]
        )
    assert out.splitlines() == [
        "Q-G22  offline (audited), GPU-free, Node-free; ceiling 600 s",
        "  uv sync   exit 0",
        "  pytest    exit 0",
        "  wall      110.0 s of 600 s",
        "  | step 2",
        "Q-G22 ok  110.0 s",
    ]


def test_a_failing_sync_stops_the_run_and_prints_the_tail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = _Runs(1, 0)
    code, out = _main(capsys, runs, *FLAGS)
    assert code == 1
    assert len(runs.calls) == 1
    assert "  uv sync   exit 1" in out
    assert "pytest" not in out
    assert "  | step 1" in out
    assert out.splitlines()[-1] == "Q-G22 FAIL  10.0 s"


def test_a_failing_suite_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(capsys, _Runs(0, 3), *FLAGS)
    assert code == 1
    assert "  pytest    exit 3" in out
    assert [x for x in out.splitlines() if x.startswith("  |")] == ["  | step 1", "  | step 2"]


def test_a_run_killed_at_the_ceiling_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(capsys, _Runs(0, None, seconds=(10.0, 590.0)), *FLAGS)
    assert code == 1
    assert "  pytest    killed at the ceiling" in out


def test_a_run_past_the_ceiling_fails_even_when_green(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(capsys, _Runs(0, 0, seconds=(10.0, 590.5)), *FLAGS)
    assert code == 1
    assert "  wall      600.5 s of 600 s" in out
    assert _main(capsys, _Runs(0, 0, seconds=(10.0, 590.0)), *FLAGS)[0] == 0


def test_log_keeps_the_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "parity.log"
    assert _main(capsys, _Runs(0, 0), *FLAGS, "--log", str(log))[0] == 0
    assert log.read_text(encoding="utf-8") == "step 1\nstep 2\n"


def test_a_blocker_that_does_not_block_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    runs = _Runs(0, 0)
    code, out = _main(capsys, runs, *FLAGS, blocks=False)
    assert code == 2
    assert out == (
        "Q-G22 DID NOT RUN  the blocker did not block: a fresh interpreter reached the network\n"
    )
    assert runs.calls == []


def test_no_uv_on_the_runs_path_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(capsys, _Runs(0, 0), *FLAGS, env={"PATH": "node-dir"})
    assert code == 2
    assert out == "Q-G22 DID NOT RUN  uv is not on the run's PATH\n"


# --- ruling 2, for real ---------------------------------------------------------------------------


def _armed(tmp_path: Path, statement: str) -> subprocess.CompletedProcess[str]:
    env = GATE.arm(tmp_path, {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"})
    return subprocess.run(  # noqa: S603 - sys.executable and a literal statement.
        [sys.executable, "-c", statement],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "statement",
    [
        "import socket; socket.create_connection(('192.0.2.1', 9), timeout=5)",
        "import socket; s = socket.socket(); s.settimeout(5); s.connect(('192.0.2.1', 9))",
        "import socket; s = socket.socket(socket.AF_INET6); s.settimeout(5);"
        " s.connect(('2001:db8::1', 9))",
        "import socket; socket.getaddrinfo('parity.invalid', 80)",
        "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM);"
        " s.sendto(b'x', ('192.0.2.1', 9))",
    ],
)
def test_the_blocker_refuses_the_network_in_a_fresh_interpreter(
    tmp_path: Path, statement: str
) -> None:
    done = _armed(tmp_path, statement)
    assert done.returncode != 0
    assert "Q-G22: the parity run" in done.stderr


def test_the_blocker_leaves_loopback_open(tmp_path: Path) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        statement = (
            f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=5).close();"
            " socket.getaddrinfo('localhost', 80); socket.getaddrinfo('0.0.0.0', 80);"
            " socket.getaddrinfo('::1', 80); socket.getaddrinfo('::ffff:127.0.0.1', 80);"
            " socket.getaddrinfo('127.9.9.9', 80); print('ok')"
        )
        done = _armed(tmp_path, statement)
    finally:
        listener.close()
    assert (done.returncode, done.stdout.strip()) == (0, "ok"), done.stderr


def test_the_negative_control_passes_under_the_real_blocker(tmp_path: Path) -> None:
    env = GATE.arm(tmp_path, {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"})
    assert GATE._blocks(env, tmp_path / "control.log")
    assert not GATE._blocks(
        {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}, tmp_path / "bare.log"
    )


# --- ruling 7: the runner, for real --------------------------------------------------------------


def test_the_runner_appends_to_the_log_and_passes_the_environment(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    env = {**os.environ, "OW_PARITY_PROBE": "seen"}
    probe = "import os, sys; print(os.environ['OW_PARITY_PROBE']); sys.exit(3)"
    assert GATE._run([sys.executable, "-c", probe], env, log, 60.0) == 3
    assert GATE._run([sys.executable, "-c", "print('again')"], env, log, 60.0) == 0
    assert log.read_text(encoding="utf-8").split() == ["seen", "again"]


def test_the_runner_kills_a_child_that_outruns_its_time(tmp_path: Path) -> None:
    marker = tmp_path / "survived"
    late = f"import pathlib, time; time.sleep(3); pathlib.Path({str(marker)!r}).write_text('x')"
    assert GATE._run([sys.executable, "-c", late], os.environ, tmp_path / "run.log", 0.5) is None
    time.sleep(5)  # past the child's own 3 s: a child that was not killed has written by now
    assert not marker.exists()


def test_the_blocker_loads_nothing_a_bare_interpreter_does_not(tmp_path: Path) -> None:
    """The first real parity run failed seven import-purity tests: the blocker imported `socket`,
    which imports `selectors`, into every interpreter of the run."""
    listing = "import sys; print(' '.join(sorted(sys.modules)))"
    bare_env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    bare = subprocess.run(  # noqa: S603 - sys.executable and a literal statement.
        [sys.executable, "-c", listing], env=bare_env, capture_output=True, text=True, check=True
    )
    armed = _armed(tmp_path, listing)
    assert armed.returncode == 0, armed.stderr
    assert set(armed.stdout.split()) - set(bare.stdout.split()) == {"sitecustomize"}
