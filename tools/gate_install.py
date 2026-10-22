"""G35, G-install: `ow install` then `ow uninstall` leaves every host's files byte-identical.

10-interfaces.md:1775 names *"The symmetry gate (G-install)"* and :1775-1780 give its procedure:
a fixture home, the byte state of every path the install will touch, install, uninstall, and byte
identity, over four cases (files that already hold the user's servers and hooks, the user's text
on both sides of our block, a second tool writing after us, two local installs). 16-roadmap.md:719
calls it W7.5's *"byte-identity reversal gate"*, and 00-vision.md's V10-15 asks it of each path's
post-write sha256 in the install receipt.

The gate itself is `packages/omniweave/tests/unit/test_gate_install.py`, which has stood in for
it since W7.5 because no register row named it (D484). This script is that row's runner: it runs
the module in a child `pytest` and reads its verdict, so the gate has one body and two callers,
the `test` job's T1 run and this step.

## Rulings

1. **The gate is the module, not a re-implementation of it.** The four cases and the receipt
   clause are parametrised there by `registry.BUILT`, so a fourth host is gated the day it is
   added; a second copy here would be a second place to forget it.
2. **A run that collected nothing did not run.** `pytest` exits 5 when no test is collected, and
   a module that skips every test is the same silence. Either is exit 2 here, never 0: a symmetry
   gate that checked no host is 11-repo-layout.md section 6.8's check that cannot fail.
3. **One child, bounded.** The child is killed past `--timeout-s` and that is a FAIL, not a
   hang: a reversal that never finishes has not reversed. The bound is a hang guard and not the
   budget: hosted Windows cells ran the module in 43-51 s where Linux and macOS took 5-7 s, and
   a 60 s bound killed two of them (D920's follow-up on #178).
4. **The scratch directory never decides the verdict.** On Windows a killed process tree can
   still hold the log for a moment, so its removal ignores errors; the log is read first.

## Exit codes

`0` every case held on every built host. `1` a case failed, or the run outran its time. `2` the
gate did not run: nothing was collected, everything skipped, or a bad argument.

Specified in 10-interfaces.md section 7.4 (:1775-1780), 16-roadmap.md:719 and D484.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess  # noqa: TID251 - the gate's whole job is to run `pytest` as a child.
import sys
import tempfile
from pathlib import Path
from typing import Final

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "MODULE", "main", "verdict"]

REPO = Path(__file__).resolve().parent.parent

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

MODULE: Final = "packages/omniweave/tests/unit/test_gate_install.py"
"""Ruling 1: the gate's one body."""

TIMEOUT_S: Final = 600.0
"""A hang guard: five times G35's `budget_s = 120`, which is itself over twice the slowest cell
measured (hosted Windows, 51 s)."""

PYTEST_NO_TESTS: Final = 5
"""`pytest.ExitCode.NO_TESTS_COLLECTED`, spelled here so the runner imports nothing from pytest."""

_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)")
_TAIL: Final = 25


def verdict(code: int | None, summary: str) -> tuple[int, str]:
    """Rulings 2 and 3 over a child's exit code and its last summary line: `(exit, why)`."""
    counts = {kind.rstrip("s"): int(n) for n, kind in _COUNT.findall(summary)}
    passed, failed = counts.get("passed", 0), counts.get("failed", 0) + counts.get("error", 0)
    if code is None:
        return EXIT_FAIL, "the run outran its time and was killed"
    if code == PYTEST_NO_TESTS or (code == 0 and passed == 0):
        return EXIT_NOT_RUN, f"no case ran ({summary.strip() or 'nothing collected'})"
    if code != 0 or failed:
        return EXIT_FAIL, summary.strip() or f"pytest exited {code}"
    return EXIT_CLEAN, summary.strip()


def _run(argv: list[str], log: Path, timeout: float) -> int | None:
    """One child, its output in `log`; `None` when it outran `timeout` and was killed."""
    with log.open("wb") as sink:
        proc = subprocess.Popen(  # noqa: S603 - argv is this interpreter, -m pytest, a path.
            argv, cwd=REPO, stdout=sink, stderr=subprocess.STDOUT
        )
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            taskkill = shutil.which("taskkill") if os.name == "nt" else None
            if taskkill is not None:
                subprocess.run(  # noqa: S603 - argv[0] from `shutil.which`, a pid, no shell.
                    [taskkill, "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
                )
            else:
                proc.kill()
            proc.wait()
            return None


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """0 symmetric on every built host, 1 a case failed, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_install.py",
        description="G35: ow install then ow uninstall restores every host's files byte for byte.",
    )
    parser.add_argument("--module", default=MODULE, metavar="PATH", help=argparse.SUPPRESS)
    parser.add_argument("--timeout-s", type=float, default=TIMEOUT_S, metavar="S")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    module = Path(args.module)
    if not (module if module.is_absolute() else REPO / module).is_file():
        _say(f"G35 DID NOT RUN  {args.module} does not exist")
        return EXIT_NOT_RUN
    with tempfile.TemporaryDirectory(
        prefix="ow-install-gate-", ignore_cleanup_errors=True
    ) as scratch:
        log = Path(scratch) / "pytest.log"
        argv_child = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(module)]
        code = _run(argv_child, log, args.timeout_s)
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = next((line for line in reversed(lines) if _COUNT.search(line)), "")
    exit_code, why = verdict(code, summary)
    if exit_code != EXIT_CLEAN:
        for line in lines[-_TAIL:]:
            _say(f"  | {line}")
    word = {EXIT_CLEAN: "ok", EXIT_FAIL: "FAIL", EXIT_NOT_RUN: "DID NOT RUN"}[exit_code]
    _say(f"G35 {word}  {why}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
