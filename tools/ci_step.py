"""CI steps' verdicts, read off master's latest run. **D974, D975, D976.**

Some acceptance rows are measured by a CI step that no local instrument can run:
- **V10-14's pdfium axis** runs only on `ci.yml`'s `schedule:` trigger. By a user ruling of
  2026-10-23 (D966), the `golden` job's nightly step installs the previous pdfium minor and
  compares two pdfium builds across the nine cells.
- **V10-2's measured half** is the `build` job's (D897-D899). It installs the three offline
  profiles from the built wheels, then holds G2's weight ceilings and the 250 MB `[recommended]`
  union over them, on every push.

This reads those steps' conclusions where they exist, through `gh run view <id> --json jobs`.
- **`--event schedule`** (the default) takes the newest completed nightly on `master`, whatever its
  conclusion. The verdict is each named step's own, because another nightly step may fail without
  touching it.
- **`--event push`** takes the newest *successful* push run. A push run is often cancelled by the
  nightly sharing its concurrency group, and a cancelled run measured nothing.

A step's exit code holds what it measures. For example, `--pdfium-minors 2 --cells 9` exits 0 only
when both builds and all nine cells were present and matched.

`--jobs-json FILE` reads a saved `gh run view --json jobs` document instead, which is how the tests
run it without a network. Exit 0 when every named step concluded `success`, 1 when one concluded
anything else that ran, and 2 when one did not run: no `gh`, no run, no such job or step, or a
skipped or cancelled step. "Did not run" is never a pass.

    uv run tools/ci_step.py                    # V10-14: the nightly pdfium step
    uv run tools/ci_step.py --run 40058737353
    uv run tools/ci_step.py --label V10-2 --event push --job "build (" --step "G2 -- "
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # noqa: TID251 -- `gh` is the one place a CI step's verdict exists.
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

WORKFLOW: Final = "ci.yml"
BRANCH: Final = "master"
JOB: Final = "golden ("
"""The default job-name prefix: the `golden` job, as `ci.yml` names it."""
STEP: Final = "Q-G4 pdfium axis (nightly)"
"""The default step-name prefix: V10-14's pdfium axis (D966)."""
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


def latest_run(event: str) -> str:
    """The newest completed nightly, or the newest successful push run, on `master`."""
    status = "completed" if event == "schedule" else "success"
    rows = json.loads(
        _gh(
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            BRANCH,
            "--event",
            event,
            "--status",
            status,
            "--limit",
            "1",
            "--json",
            "databaseId",
        )
    )
    if not rows:
        raise LookupError(f"no {status} {event} {WORKFLOW} run on {BRANCH}")
    return str(rows[0]["databaseId"])


def judge_step(job: dict[str, Any], step: str) -> tuple[int, str]:
    """One named step's conclusion in `job`: 0 success, 1 failed, 2 did not run."""
    steps = [one for one in job.get("steps", []) if str(one.get("name", "")).startswith(step)]
    if not steps:
        return 2, f"{job['name']} has no step named {step!r}..."
    conclusion = str(steps[0].get("conclusion") or "")
    shown = f"{steps[0]['name']}: {conclusion or 'no conclusion'}"
    if conclusion == "success":
        return 0, shown
    if conclusion in {"", "skipped", "cancelled"}:
        return 2, shown
    return 1, shown


def judge(
    jobs: Sequence[dict[str, Any]], job: str = JOB, steps: Sequence[str] = (STEP,)
) -> tuple[int, list[str]]:
    """Every named step in every job the prefix names: the worst code, and one line per step.

    A prefix may name several jobs, such as a matrix's cells (`test (macos-latest`, D976). Each
    line then names its job.
    """
    found = [one for one in jobs if str(one.get("name", "")).startswith(job)]
    if not found:
        return 2, [f"no job named {job!r}... in the run"]
    verdicts = [
        (code, f"{one['name']}: {line}" if len(found) > 1 else line)
        for one in found
        for code, line in (judge_step(one, step) for step in steps)
    ]
    return max(code for code, _ in verdicts), [line for _, line in verdicts]


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci_step", description="CI steps' verdicts (V10-14)")
    parser.add_argument("--run", default=None, help="a run id; default: master's latest")
    parser.add_argument("--event", choices=("schedule", "push"), default="schedule")
    parser.add_argument("--job", default=JOB, help="a job-name prefix")
    parser.add_argument(
        "--step", action="append", default=None, help="a step-name prefix (repeatable)"
    )
    parser.add_argument("--label", default="V10-14", help="the criterion the verdict is for")
    parser.add_argument("--jobs-json", type=Path, default=None, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        if args.jobs_json is not None:
            document = json.loads(args.jobs_json.read_text(encoding="utf-8"))
            source = str(args.jobs_json)
        else:
            run = args.run or latest_run(args.event)
            document = json.loads(_gh("run", "view", run, "--json", "jobs"))
            source = f"run {run}"
    except (LookupError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        _say(f"{args.label} DID NOT RUN  {exc}")
        return 2
    code, lines = judge(document.get("jobs", []), args.job, args.step or [STEP])
    _say(f"{args.label} {('ok', 'FAIL', 'DID NOT RUN')[code]}  {source}")
    for line in lines:
        _say(f"  {line}")
    return code


if __name__ == "__main__":
    sys.exit(main())
