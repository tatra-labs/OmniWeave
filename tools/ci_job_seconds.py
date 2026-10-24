"""V01-14's three CI budgets, read off a real run's job timings. **D970.**

00-vision.md's V01-14: *"CI: `gates` <= 3 min, `conform` <= 5 min, contributor-parity clean,
<= 7 min (600 s ceiling)"*. The timings exist only in GitHub Actions, so this reads them there:
`gh run view <id> --json jobs`, by default for the latest successful `ci.yml` run on `master`, and
holds each named job's wall time (`completedAt - startedAt`) to its budget. `parity` must also have
concluded `success`.

`--jobs-json FILE` reads a saved `gh run view --json jobs` document instead, which is how the tests
run it without a network. Exit 0 when every budget holds, 1 when one does not, 2 when the run could
not be read (no `gh`, no run, or a job missing), which is "did not run", never a pass.

What this does not do: write `ci.job_seconds.*` into `eval/counters.toml`. That row is registered
(`source = "ci"`) and its ratchet needs a writer in CI, which is not built.

    uv run tools/ci_job_seconds.py
    uv run tools/ci_job_seconds.py --run 39984230165
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # noqa: TID251 -- `gh` is the one place these timings exist.
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

BUDGETS_S: Final[dict[str, int]] = {"gates": 180, "conform": 300, "parity": 420}
"""V01-14's budgets in seconds, keyed by the job-name prefix `ci.yml` gives each job."""

WORKFLOW: Final = "ci.yml"
BRANCH: Final = "master"
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


def latest_run() -> str:
    """The newest successful `ci.yml` run on `master`, as its id."""
    rows = json.loads(
        _gh(
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            BRANCH,
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId",
        )
    )
    if not rows:
        raise LookupError(f"no successful {WORKFLOW} run on {BRANCH}")
    return str(rows[0]["databaseId"])


def _seconds(job: dict[str, Any]) -> float | None:
    start, end = job.get("startedAt") or "", job.get("completedAt") or ""
    if not start or not end or start.startswith("0001"):
        return None
    return (
        datetime.fromisoformat(end.replace("Z", "+00:00"))
        - datetime.fromisoformat(start.replace("Z", "+00:00"))
    ).total_seconds()


def judge(jobs: Sequence[dict[str, Any]]) -> tuple[int, list[str]]:
    """Each budgeted job's seconds against its budget; `parity` must have succeeded."""
    lines: list[str] = []
    code = 0
    for prefix, budget in BUDGETS_S.items():
        found = [job for job in jobs if str(job.get("name", "")).startswith(f"{prefix} (")]
        if not found:
            lines.append(f"  {prefix:8s} DID NOT RUN: no job named {prefix!r} in the run")
            code = max(code, 2)
            continue
        job = found[0]
        seconds = _seconds(job)
        if seconds is None:
            lines.append(f"  {prefix:8s} DID NOT RUN: the job has no start and end")
            code = max(code, 2)
            continue
        ok = seconds <= budget
        conclusion = str(job.get("conclusion", ""))
        if prefix == "parity" and conclusion != "success":
            ok = False
        verdict = "ok  " if ok else "FAIL"
        lines.append(
            f"  {prefix:8s} {verdict} {seconds:6.0f} s of {budget} s  ({conclusion}: {job['name']})"
        )
        code = max(code, 0 if ok else 1)
    return code, lines


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci_job_seconds", description="V01-14's CI budgets")
    parser.add_argument("--run", default=None, help="a run id; default: master's latest green")
    parser.add_argument("--jobs-json", type=Path, default=None, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        if args.jobs_json is not None:
            document = json.loads(args.jobs_json.read_text(encoding="utf-8"))
            source = str(args.jobs_json)
        else:
            run = args.run or latest_run()
            document = json.loads(_gh("run", "view", run, "--json", "jobs"))
            source = f"run {run}"
    except (LookupError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        _say(f"V01-14 DID NOT RUN  {exc}")
        return 2
    code, lines = judge(document.get("jobs", []))
    _say(f"V01-14 {('ok', 'FAIL', 'DID NOT RUN')[code]}  {source}")
    _say("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
