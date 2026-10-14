"""Q-G8's static half: no committed scoreboard row without a complete `MeasuredOn`. **D831.**

13-quality.md section 2.1 (:95): *"`Q-G8` (static half) | `eval/results/**.json` | no committed
row without a complete ten-field `MeasuredOn`"*. Section 15 (:1992) gives the other half:
*"`MeasuredOn` frozen with no defaults (a `TypeError`, not a blank cell); the static half in T0
over committed results"*. 16-roadmap.md:981 puts `uv run tools/gate_measured_on.py  # every
published number's ten-field MeasuredOn` in P10's exit criteria.

The rule is `omniweave_conform.scoreboard.unmeasured()`'s, which builds each row's `measured_on`
through `MeasuredOn` itself. The construction half and this half therefore cannot disagree about
what complete means. This file reads the tree, prints every row that fails with its reason, and
exits. That follows the standing pattern (ledger D25).

**Every row is checked, whatever its standing.** An UNKNOWN row has no number but is still
published, and it carries its run's `MeasuredOn` like any other.

**An absent tree passes, and says so,** as `tools/gate_metric_rot.py` does: nothing is published
until `ow eval publish` first writes `eval/results/`.

**Registration.** A `Q-G` script, so `test_gates_register.py`'s `QG_SERIES_SCRIPTS` exempts it
with its citation.

## Exit codes

`0` every row is measured. `1` a row is not, named with its file, position, metric, slice and
reason. `2` the gate did not run: a file that is not a JSON list of rows, or a bad argument.

Specified in 13-quality.md sections 2.1 and 15, 04-driver-system.md section 2.6, and
16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.scoreboard import tree, unmeasured  # noqa: E402

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "RESULTS", "main"]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

RESULTS: Final = Path("eval") / "results"
FIX: Final = "re-export with ow eval publish; a committed row is never edited by hand"


class _UnreadableError(Exception):
    """A results file that is not a JSON list of objects."""


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _findings(files: dict[str, str]) -> tuple[int, list[str]]:
    """Every row read, and a line for each one `unmeasured()` refuses."""
    count = 0
    out = []
    for path, text in sorted(files.items()):
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _UnreadableError(f"{path}: not JSON ({exc.msg}, line {exc.lineno})") from exc
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise _UnreadableError(f"{path}: not a list of rows")
        for at, row in enumerate(rows, start=1):
            count += 1
            why = unmeasured(row)
            if why is not None:
                out.append(f"  {path} row {at} ({row.get('metric')}@{row.get('slice_key')}): {why}")
    return count, out


def main(argv: list[str] | None = None) -> int:
    """0 every row measured, 1 one is not, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_measured_on.py",
        description="Q-G8 static half: every eval/results/**.json row has a ten-field MeasuredOn.",
    )
    parser.add_argument("--results", type=Path, default=REPO / RESULTS, metavar="DIR")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN

    try:
        files = tree(args.results)
        count, findings = _findings(files)
    except (OSError, UnicodeDecodeError, _UnreadableError) as exc:
        _say(f"Q-G8 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    if not files:
        _say(f"Q-G8 ok  nothing published: no *.json under {args.results}")
        return EXIT_CLEAN
    _say(f"Q-G8  {len(files)} file(s), {count} row(s)")
    for line in findings:
        _say(line)
    if findings:
        _say(f"  fix: {FIX}")
    _say(f"Q-G8 {'FAIL' if findings else 'ok'}  {len(findings)} unmeasured row(s)")
    return EXIT_FAIL if findings else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
