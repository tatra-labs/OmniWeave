"""A nightly-only CI step's verdict, read off master's latest scheduled run. **D974.**

Some acceptance rows are measured by a step that runs only on `ci.yml`'s `schedule:` trigger, so
no local instrument can run it and a pull request never does. V10-14's pdfium axis is one: by a
user ruling of 2026-10-23 (D966), the `golden` job's nightly step installs the previous pdfium
minor and compares two pdfium builds across the nine cells. This reads that step's conclusion
where it exists: `gh run view <id> --json jobs`, by default for the newest completed scheduled
`ci.yml` run on `master`.

The verdict is the step's own, not the run's. Another nightly step may fail without touching this
one, and this one's exit code already holds what it measures (`--pdfium-minors 2 --cells 9`
exits 0 only when both builds and all nine cells were present and matched).

`--jobs-json FILE` reads a saved `gh run view --json jobs` document instead, which is how the tests
run it without a network. Exit 0 when the step concluded `success`, 1 when it concluded anything
else that ran, and 2 when it did not run: no `gh`, no scheduled run, no such job or step, or a
skipped step. "Did not run" is never a pass.

    uv run tools/ci_nightly_step.py
    uv run tools/ci_nightly_step.py --run 40058737353
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # noqa: TID251 -- `gh` is the one place a nightly step's verdict exists.
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

WORKFLOW: Final = "ci.yml"
BRANCH: Final = "master"
JOB: Final = "golden ("
"""The job-name prefix `ci.yml` gives the `golden` job."""
STEP: Final = "Q-G4 pdfium axis (nightly)"
"""The step-name prefix of V10-14's pdfium axis (D966)."""
_TIMEOUT_S: Final = 120


def _gh(*args: str) -> str:
    gh = shutil.which("gh")
    if gh is None:
        raise LookupError("`gh` is not on PATH")
    done = subprocess.run(  # noqa: S603 -- a fixed argv, no shell.
        [gh, *args], capture_output=True, text=True, check=False, timeout=_TIMEOUT_S
    )
    if done.returncode:
        raise LookupError(f"gh {' '.join(args[:2])} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def latest_nightly() -> str:
    """The newest completed scheduled `ci.yml` run on `master`, whatever its conclusion."""
    rows = json.loads(
        _gh(
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            BRANCH,
            "--event",
            "schedule",
            "--status",
            "completed",
            "--limit",
            "1",
            "--json",
            "databaseId",
        )
    )
    if not rows:
        raise LookupError(f"no completed scheduled {WORKFLOW} run on {BRANCH}")
    return str(rows[0]["databaseId"])


def judge(jobs: Sequence[dict[str, Any]], job: str = JOB, step: str = STEP) -> tuple[int, str]:
    """The named step's conclusion in the named job: 0 success, 1 failed, 2 did not run."""
    found = [one for one in jobs if str(one.get("name", "")).startswith(job)]
    if not found:
        return 2, f"no job named {job!r}... in the run"
    steps = [one for one in found[0].get("steps", []) if str(one.get("name", "")).startswith(step)]
    if not steps:
        return 2, f"{found[0]['name']} has no step named {step!r}..."
    conclusion = str(steps[0].get("conclusion") or "")
    shown = f"{steps[0]['name']}: {conclusion or 'no conclusion'}"
    if conclusion == "success":
        return 0, shown
    if conclusion in {"", "skipped", "cancelled"}:
        return 2, shown
    return 1, shown


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_nightly_step", description="a nightly-only CI step's verdict (V10-14)"
    )
    parser.add_argument("--run", default=None, help="a run id; default: master's latest nightly")
    parser.add_argument("--jobs-json", type=Path, default=None, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        if args.jobs_json is not None:
            document = json.loads(args.jobs_json.read_text(encoding="utf-8"))
            source = str(args.jobs_json)
        else:
            run = args.run or latest_nightly()
            document = json.loads(_gh("run", "view", run, "--json", "jobs"))
            source = f"run {run}"
    except (LookupError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        _say(f"V10-14 DID NOT RUN  {exc}")
        return 2
    code, line = judge(document.get("jobs", []))
    _say(f"V10-14 {('ok', 'FAIL', 'DID NOT RUN')[code]}  {source}")
    _say(f"  {line}")
    return code


if __name__ == "__main__":
    sys.exit(main())
