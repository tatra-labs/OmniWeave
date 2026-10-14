"""Q-G19's row clause and Q-G21's pairing over the committed `eval/results/**.json`. **D832.**

13-quality.md section 2.1 gives both as static checks over *"the same tree"*:
- **Q-G19** (:98): *"byte diff; every row's required fields non-empty"*.
- **Q-G21** (:99): *"`field_acc` never without `doc_acc`; `hallucination_rate` never alone;
  `source_reread_rate` never without `task_accuracy`"*.

Section 15 (:2003, :2005) gives each the class `G`.

The rules are `omniweave_conform.scoreboard`'s. `check()` is the row clause `export()` already
applies before it writes, and `unpaired()` is the pairing. This file holds the committed bytes to
both, prints every failure, and exits, following the standing pattern (ledger D25).

**Why the byte clause is not here.** Q-G19's byte half compares the committed tree with what
`ow eval publish` would write from the `.oweval`. That file is generated and `.gitignore`d
(13:1624), so a clean checkout has nothing to export from; `scoreboard.stale()` serves it where
the file exists. The row clause needs only the committed bytes, so it runs in T0.

**One script for two gates,** because both read the same tree and print against the same rows.
Each finding names its gate, and each gate gets its own verdict line.

**An absent tree passes, and says so,** as `tools/gate_metric_rot.py` and
`tools/gate_measured_on.py` do.

## Exit codes

`0` both gates hold. `1` a row fails either, named with its gate, file and reason. `2` the gate
did not run: a file that is not a JSON list of rows, or a bad argument.

Specified in 13-quality.md sections 2.1, 8.3, 11.1 and 15.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.scoreboard import check, tree, unpaired  # noqa: E402
from omniweave_core.errors import QualityError  # noqa: E402

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "RESULTS", "main"]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

RESULTS: Final = Path("eval") / "results"
FIX: Final = "re-export with ow eval publish after fixing the run; never edit a committed row"


class _UnreadableError(Exception):
    """A results file that is not a JSON list of objects."""


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _parse(path: str, text: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _UnreadableError(f"{path}: not JSON ({exc.msg}, line {exc.lineno})") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise _UnreadableError(f"{path}: not a list of rows")
    return rows


def _findings(files: dict[str, str]) -> tuple[int, list[str], list[str]]:
    """Rows read, then Q-G19's and Q-G21's findings, each line naming its file."""
    count = 0
    rowwise: list[str] = []
    pairing: list[str] = []
    for path, text in sorted(files.items()):
        rows = _parse(path, text)
        count += len(rows)
        for at, row in enumerate(rows, start=1):
            try:
                check([row])
            except QualityError as exc:
                rowwise.append(f"  Q-G19 {path} row {at}: {str(exc).removeprefix('Q-G19: ')}")
        pairing.extend(f"  Q-G21 {path}: {line}" for line in unpaired(rows))
    return count, rowwise, pairing


def main(argv: list[str] | None = None) -> int:
    """0 both gates hold, 1 a row fails one, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_results.py",
        description="Q-G19's row clause and Q-G21's pairing over eval/results/**.json.",
    )
    parser.add_argument("--results", type=Path, default=REPO / RESULTS, metavar="DIR")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN

    try:
        files = tree(args.results)
        count, rowwise, pairing = _findings(files)
    except (OSError, UnicodeDecodeError, _UnreadableError) as exc:
        _say(f"Q-G19/Q-G21 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    if not files:
        _say(f"Q-G19/Q-G21 ok  nothing published: no *.json under {args.results}")
        return EXIT_CLEAN
    _say(f"Q-G19/Q-G21  {len(files)} file(s), {count} row(s)")
    for line in [*rowwise, *pairing]:
        _say(line)
    if rowwise or pairing:
        _say(f"  fix: {FIX}")
    _say(f"Q-G19 {'FAIL' if rowwise else 'ok'}  {len(rowwise)} row(s) missing or empty")
    _say(f"Q-G21 {'FAIL' if pairing else 'ok'}  {len(pairing)} metric(s) without a partner")
    return EXIT_FAIL if rowwise or pairing else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
