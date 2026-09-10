"""`tools/gate_crash.py` -- G21's runner, and the half of W2.9 that sends a real signal.

`tools/gates.toml`'s G21 row is the specification: *"kill-9 at three points; `ow resume`; store
equals an uninterrupted run"*, `jobs = ["crash"]`, `budget_s = 240`, PR and nightly,
`nightly_note = "full matrix"`. Both halves are asserted here -- the three-point PR run and the
`--all` nightly one -- because a register cell that only one half honours is a cell nobody
checks.

**WHAT THIS FILE TESTS THAT `test_store_crashmatrix.py` CANNOT.** That file kills in-process, by
`Connection.interrupt()` from inside a trace callback, which leaves the same rows a pre-COMMIT
SIGKILL leaves and is forty times faster. Three things it cannot show, and all three are here:

1. **A real uncatchable signal.** `Popen.kill()` -- `SIGKILL` on POSIX, `TerminateProcess` on
   Windows -- runs no `atexit`, no `__del__` and no `Connection.close()`. The child is asserted to
   die holding an uncommitted transaction.
2. **The leaked WAL, and heal-on-open.** A WAL only outlives its writer when that writer did not
   close, and a `wal_checkpoint(TRUNCATE)` needs every other connection gone. So the only process
   that can leave an oversized WAL for someone else to heal is a killed one. 07:181-183 measured
   what happens without the heal: **25.6 GB** across repeatedly-SIGKILLed sessions.
3. **A cycle that never killed anything is exit 2 and not exit 0.** A harness whose child exits
   before parking would report a green cycle over a store that was never crashed, which is the
   most expensive way for this gate to be useless.

`import subprocess` and `import sqlite3` are both banned by ruff's TID251 -- `subprocess` to
`omniweave_core.toolchain` and `host/subproc.py` (S2/S4), `sqlite3` to `omniweave_core.store`
(INV-17) -- and this file takes both escapes deliberately. It spawns and kills real processes,
which is the whole subject, and it reads `work.status` out of a store between the kill and the
resume, which no store-boundary method exposes. Neither escape reaches library code: the ban's
scope is `packages/*/src/**`.

Specified in 11-repo-layout.md sections 6.4 (G21), 6.5 and 6.8, 16-roadmap.md:422 and :436-445,
17-risks.md:861 and 07-store-and-retrieval.md:181-183, :2730-2733 and :2807.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess  # noqa: TID251 -- see the module docstring: real processes ARE the subject.
import sys
import time
import tomllib
from io import StringIO
from pathlib import Path

import pytest
from omniweave_core.store import crashmatrix as cm
from omniweave_core.store import sqlite as ow


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_crash.py"
REGISTER = REPO_ROOT / "tools" / "gates.toml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The gate is a script in `tools/`, not a distribution, so there is no package to import it from.
# `spec_from_file_location` loads it by path -- the same mechanism `test_gate_migrations.py` and
# `test_gate_incremental.py` use, and for the same reasons: not `importlib.import_module`, which
# is banned outside `host/`, and not a `sys.path` mutation, which would leak into every later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_gate_crash", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repository.
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)

FIRST = cm.SCENARIOS[0]


def _run(argv: list[str]) -> tuple[int, str]:
    """The gate, with its report captured. Nothing here writes to the real stdout."""
    buffer = StringIO()
    code = gate.main(argv, out=buffer)
    return code, buffer.getvalue()


# ---------------------------------------------------------------------------------------------
# The two halves of G21's row
# ---------------------------------------------------------------------------------------------


def test_the_pr_half_draws_three_points_kills_a_real_process_at_each_and_converges(
    tmp_path: Path,
) -> None:
    """G21's assertion, run: *"kill-9 at three points; `ow resume`; store equals an uninterrupted
    run"*.

    No `--in-process`, so every one of the three cycles spawns a child, waits for it to park at
    its boundary and sends the signal. Exit 0 is the whole claim.
    """
    code, report = _run(["--workspace", str(tmp_path), "--keep"])
    assert code == gate.EXIT_CLEAN, report
    assert "kill=SIGKILL" in report
    assert report.count("  ok  ") == cm.PR_POINTS
    assert "byte for byte in the .owdoc export" in report


def test_the_drawn_points_are_printed_so_a_ci_failure_is_reproducible(tmp_path: Path) -> None:
    """11-repo-layout.md:2185: *"Sampling is blake2b. Determinism is a gate, not a habit."*

    A CI failure at one of three sampled points is worth nothing if the three cannot be
    identified, so the gate prints them and the salt that drew them. `--point` then replays one.
    """
    _code, report = _run(["--workspace", str(tmp_path), "--in-process"])
    for mode, boundary in cm.kill_points():
        assert f"  point  {mode}/{boundary}" in report
    assert "salt='ow-crash-1'" in report


def test_list_prints_the_whole_matrix_and_the_three_it_would_draw() -> None:
    """`--list` is the reproduction aid: forty candidates, then the three this salt selects."""
    code, report = _run(["--list"])
    assert code == gate.EXIT_CLEAN
    assert report.count("\n") >= len(cm.matrix_boundaries()) + cm.PR_POINTS
    assert report.count("drawn  ") == cm.PR_POINTS
    for mode, boundary in cm.matrix_boundaries():
        assert f"{mode}/{boundary}" in report


def test_the_nightly_half_runs_every_boundary_of_every_fixture(tmp_path: Path) -> None:
    """`nightly_note = "full matrix"` -- 11-repo-layout.md section 6.5's *"the full G21 crash
    matrix"*.

    Run with `--in-process` here and not because the real signal is optional: the same forty
    cycles with real children take about fourteen seconds, which is fine for a nightly job and
    not for a unit test that runs on every commit. `test_the_pr_half...` above is what asserts the
    signal is real, and the two share every other line of the cycle by construction -- the `kill`
    seam is the only difference.
    """
    code, report = _run(["--workspace", str(tmp_path), "--all", "--in-process"])
    assert code == gate.EXIT_CLEAN, report
    assert report.count("  ok  ") == len(cm.matrix_boundaries()) == 40
    assert "full matrix in" in report


def test_a_named_point_runs_exactly_that_one(tmp_path: Path) -> None:
    """`--point mode/boundary` replays one reported failure and nothing else."""
    code, report = _run(
        ["--workspace", str(tmp_path), "--in-process", "--point", "no_fsync/after:commit"]
    )
    assert code == gate.EXIT_CLEAN, report
    assert report.count("  ok  ") == 1
    assert "no_fsync/after:commit" in report


def test_a_point_the_matrix_does_not_hold_is_exit_two(tmp_path: Path) -> None:
    """A typo in `--point` is a gate that did not run, not a gate that passed."""
    code, report = _run(["--workspace", str(tmp_path), "--point", "no_fsync/after:nowhere"])
    assert code == gate.EXIT_NOT_RUN
    assert "DID NOT RUN" in report


# ---------------------------------------------------------------------------------------------
# A real signal, and what it leaves behind
# ---------------------------------------------------------------------------------------------


def _child(root: Path, mode: str, boundary: str) -> subprocess.Popen[bytes]:
    """Spawn the gate's own child for one boundary. The parent kills it; it never exits."""
    return subprocess.Popen(  # noqa: S603 -- argv is this repository's own script plus flags.
        [
            sys.executable,
            str(TOOL_PATH),
            "--child",
            "--root",
            str(root),
            "--mode",
            mode,
            "--boundary",
            boundary,
        ]
    )


def _wait_for(path: Path, seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


def _status(path: Path, part: str) -> tuple[str, str]:
    connection = ow.connect_readonly(path)
    try:
        row = connection.execute(
            "SELECT status, cache_key FROM work WHERE unit_part = ?", (part,)
        ).fetchone()
    finally:
        connection.close()
    return str(row[0]), str(row[1])


def test_a_killed_child_dies_holding_an_uncommitted_transaction(tmp_path: Path) -> None:
    """The real signal, and the store it leaves: `claimed`, the placeholder key, no `dep` rows.

    This is 07:2730-2733 measured against a process that was actually destroyed rather than one
    that raised: *"one unit's derived rows, its `work` transition, its `dep` rows ... together or
    not at all."* The child parks at the boundary AFTER the `work` transition statement and BEFORE
    the first `dep` insert, which is the one boundary where a non-atomic `complete()` would leave a
    `done` row with nothing to back it.

    It also asserts what only a killed process leaves: the `-wal` and `-shm` sidecars are still on
    disk, because nothing closed the connection.
    """
    path = tmp_path / "index.owstore"
    cas = tmp_path / "cas"
    cm.seed(path, cas, now_ns=gate.NOW_NS)
    proc = _child(tmp_path, FIRST.mode, "after:work_transition/work_update")
    try:
        assert _wait_for(tmp_path / "ready"), "the child never parked at its boundary"
    finally:
        proc.kill()
        proc.wait(timeout=30)
    assert proc.returncode != 0, "a killed process does not exit cleanly"
    assert (tmp_path / "index.owstore-wal").exists(), "a killed writer leaves its WAL behind"
    assert _status(path, FIRST.part) == ("claimed", "planned")
    connection = ow.connect_readonly(path)
    try:
        assert connection.execute("SELECT count(*) FROM dep").fetchone()[0] == 0
    finally:
        connection.close()


def test_a_reopen_after_a_real_kill_heals_an_oversized_wal(tmp_path: Path) -> None:
    """07:2807's heal-on-open, over a WAL a killed process actually leaked.

    07:181-183 is the measurement: **25.6 GB** of leaked WAL across repeatedly-SIGKILLed sessions
    with no heal-on-open. This is the only shape in which the heal can be observed -- a WAL
    outlives its writer only when that writer did not close, and a `TRUNCATE` checkpoint needs
    every other connection gone -- which is why the in-process model cannot make this assertion
    and `test_store_crashmatrix.py` says so in as many words.

    Both directions of `heal_wal`'s `>` threshold, each over its own leaked store: a ~3 MB WAL
    is healed at a 1 MB threshold and a ~64 KB one is left alone. Two stores and not one, because
    the first `reopen()` is itself the last connection to close and SQLite deletes the WAL on that
    close -- so a second assertion against the same file would be asserting against nothing. The
    bulk write goes into `route_evidence.payload`, a nullable BLOB with no dependants, so a few
    megabytes there perturbs nothing else.
    """
    big = _leak(tmp_path / "big", rows=48)
    assert big[1] > 1 << 20, f"the leaked WAL is {big[1]} bytes; this test needs over 1 MiB"
    healed = cm.reopen(big[0], wal_heal_mb=1)
    with healed:
        inside = ow.wal_bytes(big[0])
    assert healed.wal_before == big[1]
    assert healed.reclaimed > 0, "the leaked WAL survived heal-on-open"
    assert inside < big[1], "the truncate did not shrink the sidecar"

    small = _leak(tmp_path / "small", rows=1)
    assert small[1] < 1 << 20, f"the small WAL is {small[1]} bytes; it must be under 1 MiB"
    untouched = cm.reopen(small[0], wal_heal_mb=1)
    with untouched:
        pass
    assert untouched.wal_before == small[1]
    assert untouched.reclaimed == 0, "a WAL under the threshold is not oversized"


def _leak(root: Path, *, rows: int) -> tuple[Path, int]:
    """Build a store, have a CHILD commit `rows` x 64 KiB into it, kill it, return the leaked WAL.

    The kill is what makes the WAL survive: a clean close checkpoints and deletes the sidecar, so
    there is no way to hand an oversized WAL to the next open except by destroying the process
    that made it. That is also the production shape 07:181-183 measured.
    """
    root.mkdir(parents=True)
    path = root / "index.owstore"
    ready = root / "bulk-ready"
    cm.seed(path, root / "cas", now_ns=gate.NOW_NS)
    script = _BULK_CHILD.format(path=path, ready=ready, rows=rows)
    proc = subprocess.Popen(  # noqa: S603 -- argv is this repository's own interpreter.
        [sys.executable, "-c", script]
    )
    try:
        assert _wait_for(ready), "the bulk writer never reported"
    finally:
        proc.kill()
        proc.wait(timeout=30)
    return path, ow.wal_bytes(path)


_BULK_CHILD = """
import threading
from pathlib import Path
from omniweave_core.store import sqlite as ow

path = Path(r"{path}")


def run(connection):
    for index in range({rows}):
        connection.execute(
            "INSERT OR REPLACE INTO route_evidence(evidence_digest, payload, first_seen_at) "
            "VALUES(?, ?, 1)",
            (f"bulk{{index}}", b"x" * 65536),
        )
    return None


thread = ow.StoreThread(lambda: ow.connect(path)).start()
thread.run(ow.Unit(name="bulk", run=run, cost_class="free"))
Path(r"{ready}").write_text("parked", encoding="utf-8")
threading.Event().wait()
"""
"""A writer that commits `rows` x 64 KiB and then parks forever, so the parent can kill it.

Spelled as source rather than as a `tools/` flag on purpose: inflating a WAL is this test's
business and not a mode `gate_crash.py` should offer. It goes through `ow.connect()` and a
`StoreThread`, so ST1 holds inside the child too."""


def test_a_child_that_never_reaches_its_boundary_is_exit_two_and_not_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cycle that killed nothing must not read as a cycle that converged.

    11-repo-layout.md section 6.8 refuses a check that cannot fail. The guard is
    `ChildNeverParkedError`, and it is exit 2 -- "the gate did not run" -- rather than exit 1,
    because a harness failure and a store failure send a human to different files. This drives it
    through the real spawn path with a boundary the child will refuse.
    """
    real = gate.spawn_kill

    def broken(**_kw: object) -> object:
        inner = real(timeout_s=5.0)

        def kill(path: Path, cas: Path, scenario: object, _boundary: str) -> object:
            return inner(path, cas, scenario, "after:nowhere")

        return kill

    monkeypatch.setattr(gate, "spawn_kill", broken)
    code, report = _run(["--workspace", str(tmp_path), "--point", f"{FIRST.mode}/after:begin"])
    assert code == gate.EXIT_NOT_RUN, report
    assert "DID NOT RUN" in report
    assert "never parked" in report or "before parking" in report


def test_the_gate_fails_when_the_resumed_store_does_not_equal_the_uninterrupted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 1, with the divergence named. The gate's own proof that it can report red.

    The baseline is replaced by one whose export digest is wrong, so every cycle diverges on
    `owdoc` and nothing else. That distinguishes exit 1 from exit 2 on the same run: the harness
    worked, the comparison failed, and the report says which field.
    """
    real = cm.baseline

    def wrong(root: Path, **kwargs: object) -> cm.Fingerprint:
        honest = real(root, **kwargs)  # type: ignore[arg-type]
        return cm.Fingerprint(
            owdoc="0" * 64,
            work=honest.work,
            tables=honest.tables,
            sidecars=honest.sidecars,
        )

    monkeypatch.setattr(cm, "baseline", wrong)
    code, report = _run(
        ["--workspace", str(tmp_path), "--in-process", "--point", f"{FIRST.mode}/after:commit"]
    )
    assert code == gate.EXIT_FAIL, report
    assert "did not converge" in report
    assert "diverged:  owdoc" in report


# ---------------------------------------------------------------------------------------------
# The budget cell, and the register
# ---------------------------------------------------------------------------------------------


def _cycle(ok: bool = True) -> object:
    return gate.Cycle(
        label="x/after:begin",
        ok=ok,
        seconds=1.0,
        integrity="ok",
        differences=(),
        reclaimed_wal_bytes=0,
    )


def test_the_budget_cell_gates_the_pr_half_and_not_the_nightly_full_matrix() -> None:
    """`budget_s = 240` is G21's row, and section 6.5 puts the full matrix on the nightly runner.

    So the cell is the three-point job's promise: PR mode past it is a failure, `--all` past it is
    a measurement. Asserted against `_report` directly with a synthetic 999 seconds, because a
    test that had to actually take four minutes to check a four-minute budget would be the slowest
    test in the suite and would still be a clock reading.
    """
    buffer = StringIO()
    emit = gate._emitter(buffer)
    pr = argparse.Namespace(all=False, budget_s=240)
    assert gate._report([_cycle()], 999.0, pr, emit) == gate.EXIT_FAIL
    assert "exceeds G21's 240s budget" in buffer.getvalue()

    buffer = StringIO()
    nightly = argparse.Namespace(all=True, budget_s=240)
    assert gate._report([_cycle()], 999.0, nightly, gate._emitter(buffer)) == gate.EXIT_CLEAN
    assert "full matrix in 999.0s" in buffer.getvalue()

    buffer = StringIO()
    disabled = argparse.Namespace(all=False, budget_s=0)
    assert gate._report([_cycle()], 999.0, disabled, gate._emitter(buffer)) == gate.EXIT_CLEAN


def test_a_diverged_cycle_beats_an_over_budget_one_in_the_report() -> None:
    """Two failures, one exit code, and the store's is the one a human needs to read first."""
    buffer = StringIO()
    args = argparse.Namespace(all=False, budget_s=1)
    code = gate._report([_cycle(ok=False)], 999.0, args, gate._emitter(buffer))
    assert code == gate.EXIT_FAIL
    assert "did not converge" in buffer.getvalue()
    assert "budget" not in buffer.getvalue().split("did not converge")[1]


def test_the_measured_budget_is_reported_on_every_run(tmp_path: Path) -> None:
    """A budget nobody measures is a number in a register. The gate prints both."""
    _code, report = _run(
        ["--workspace", str(tmp_path), "--in-process", "--point", f"{FIRST.mode}/after:begin"]
    )
    assert "(G21 budget 240s)" in report
    assert gate.BUDGET_S == 240


def test_g21s_register_row_names_this_script_as_a_live_runner() -> None:
    """The register's forcing function, from the other side.

    `test_gates_register.py` asserts every `runner` exists and every `runner_planned` does NOT, so
    landing this script without moving the path from one key to the other turns that suite red.
    This is the same claim asserted where a reader of G21 will look for it.
    """
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    rows = [row for row in register["gate"] if row["id"] == "G21"]
    assert len(rows) == 1, "G21 is one row"
    row = rows[0]
    assert "tools/gate_crash.py" in row.get("runner", [])
    assert "tools/gate_crash.py" not in row.get("runner_planned", [])
    assert row["jobs"] == ["crash"]
    assert row["budget_s"] == gate.BUDGET_S
    assert row["nightly_note"] == "full matrix"


def test_the_crash_job_invokes_the_runner_unconditionally() -> None:
    """A step named after a gate that does not run it is section 6.8's check that cannot fail.

    `test_ci_workflows.py::test_every_named_runner_is_actually_invoked_in_the_job_its_row_names`
    is the general assertion and its docstring records the mutation that found the hole. This is
    the specific one: the `crash` job runs `tools/gate_crash.py`, and it is no longer wrapped in
    the `if [ -f tools/gate_crash.py ]` existence guard the P2 placeholder carried -- a guard that
    passes when the file is missing is a gate that reports green on a tree without it.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "uv run tools/gate_crash.py" in text
    assert "if [ -f tools/gate_crash.py ]" not in text
    assert "G21 NOT ENFORCED" not in text
