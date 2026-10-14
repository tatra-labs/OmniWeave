"""Q-G27, metric rot, as a program: `eval/results/**.json` against `eval/gates.toml`. **D829.**

13-quality.md section 13.1 (:103): *"`Q-G27` | `eval/results/**.json` plus `eval/gates.toml` | no
metric published ungated for more than two corpus releases"*, and section 15 (:2011) its class,
`G`: *"a two-release clock on every ungated published metric"*.

The arithmetic is `omniweave_conform.rot`'s, and its module docstring holds the rulings. This file
reads two paths, prints every ungated clock, rotten or not, and exits. That follows the standing
pattern (ledger D25): the library function is in the package and a `tools/` script drives it.

**Every ungated clock is printed, not only the rotten ones.** A metric at two of two releases is
the one a reviewer can still act on before it fails, so the edge is reported alongside the
failures.

**An absent tree passes, and says so.** Nothing is published until `ow eval publish` first writes
`eval/results/`, and a board with no rows has no metric to rot. The line names the absence rather
than reporting a clean board it never read.

**Registration.** This is a `Q-G` script, so `tools/gates.toml` may not name it (11-repo-layout.md
section 1.7). `test_gates_register.py`'s `QG_SERIES_SCRIPTS` exempts it with its citation, as it
does `tools/gate_budgets.py`.

## Exit codes

`0` no metric rots. `1` a metric rots, and the report names it and the fix. `2` the gate did not
run: a register or tree that does not parse, or a bad argument.

Specified in 13-quality.md sections 8.3, 13.1 and 15, and 16-roadmap.md W10.11.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.rot import FIX, RELEASES, Clock, rot  # noqa: E402
from omniweave_conform.scoreboard import tree  # noqa: E402
from omniweave_core.errors import QualityError  # noqa: E402

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "GATES", "RESULTS", "main"]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

GATES: Final = Path("eval") / "gates.toml"
RESULTS: Final = Path("eval") / "results"


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _mark(clock: Clock) -> str:
    """`ROT` past the clock, `edge` at it, blank before it."""
    if clock.rotten:
        return "ROT "
    return "edge" if len(clock.versions) == RELEASES else "    "


def main(argv: list[str] | None = None) -> int:
    """0 no metric rots, 1 one does, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_metric_rot.py",
        description=(
            "Q-G27: no metric published in eval/results/**.json without an eval/gates.toml row "
            f"for more than {RELEASES} corpus releases."
        ),
    )
    parser.add_argument("--gates", type=Path, default=REPO / GATES, metavar="PATH")
    parser.add_argument("--results", type=Path, default=REPO / RESULTS, metavar="DIR")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN

    try:
        register = tomllib.loads(args.gates.read_text(encoding="utf-8"))
        files = tree(args.results)
        clocks = rot(files, register)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, QualityError) as exc:
        _say(f"Q-G27 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    if not files:
        _say(f"Q-G27 ok  nothing published: no *.json under {args.results}")
        return EXIT_CLEAN
    rotten = [clock for clock in clocks if clock.rotten]
    _say(f"Q-G27  {len(files)} file(s), {len(clocks)} ungated clock(s)")
    for clock in clocks:
        _say(f"  {_mark(clock)}  {clock.line()}")
    if rotten:
        _say(f"  fix: {FIX}")
    _say(f"Q-G27 {'FAIL' if rotten else 'ok'}  {len(rotten)} rotten metric clock(s)")
    return EXIT_FAIL if rotten else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
