"""Q-G18, flake control, as a program: `eval_flake` against `eval/quarantine.toml`. **D836.**

16-roadmap.md:983: `uv run tools/gate_flake.py --window 30d  # >2% quarantines to
informational`. The arithmetic and the register's rules are `omniweave_conform.flake`'s. This
file reads the two inputs, prints every flaky test and every quarantine row, and exits, following
the standing pattern (ledger D25).

**Two inputs, each absent until something writes it.**
- **`eval_flake` lives in the `.oweval`,** which is generated and `.gitignore`d (13:1624). With
  none, the rates clause is not run, and the report says so by name rather than finding nothing
  flaky.
- **`eval/quarantine.toml` is a committed register.** With none, nothing is quarantined, which
  is a fact and is printed as one.

The register's own rules (a well-formed row, an expiry at most 60 days out, and one row per test)
run whenever the file exists, `.oweval` or not.

**The clock is an argument.** `--today` defaults to the UTC wall date, the one impure call here,
and a test passes a fixed date. `--window` takes `<n>d`, the spelling the exit criterion prints.

**Registration.** A `Q-G` script, so `test_gates_register.py`'s `QG_SERIES_SCRIPTS` exempts it.

## Exit codes

`0` no unquarantined flaky test and no expired quarantine. `1` either, named with the test and
the fix. `2` the gate did not run: an unreadable register or `.oweval`, or a bad argument.

Specified in 13-quality.md sections 2.7, 13.1 and 15, and 16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tomllib
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.flake import WINDOW_DAYS, judge, register, window  # noqa: E402
from omniweave_core.errors import QualityError  # noqa: E402
from omniweave_core.store.oweval import Flake, flakes, open_oweval  # noqa: E402

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "OWEVAL", "QUARANTINE", "main", "today"]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

OWEVAL: Final = Path("eval") / "omniweave.oweval"
QUARANTINE: Final = Path("eval") / "quarantine.toml"
_DAYS: Final = re.compile(r"([1-9][0-9]*)d")


def today() -> dt.date:
    """The wall clock, UTC. The one impure call here."""
    return dt.datetime.now(tz=dt.UTC).date()


def _days(text: str) -> int:
    """`--window`'s spelling, `<n>d` (16:983)."""
    match = _DAYS.fullmatch(text)
    if match is None:
        raise argparse.ArgumentTypeError(f"{text!r} is not <n>d, e.g. 30d")
    return int(match.group(1))


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """0 nothing flaky unquarantined and nothing expired, 1 either, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_flake.py",
        description="Q-G18: a test above 2% failure over the window is quarantined, visibly.",
    )
    parser.add_argument("--window", type=_days, default=WINDOW_DAYS, metavar="<n>d")
    parser.add_argument("--oweval", type=Path, default=REPO / OWEVAL, metavar="PATH")
    parser.add_argument("--quarantine", type=Path, default=REPO / QUARANTINE, metavar="PATH")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    now: dt.date = args.today or today()

    try:
        rows = register(_load(args.quarantine)) if args.quarantine.is_file() else ()
        measured = args.oweval.is_file()
        windows = window(_read(args.oweval), now, args.window) if measured else {}
    except (OSError, ValueError, QualityError) as exc:
        _say(f"Q-G18 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    findings = judge(windows, rows, now)
    _say(f"Q-G18  as of {now.isoformat()}, a {args.window}-day window")
    if measured:
        _say(f"  eval_flake   {len(windows)} test(s) with runs in the window")
    else:
        _say(f"  eval_flake   not run: no .oweval at {args.oweval}")
    if args.quarantine.is_file():
        _say(f"  quarantine   {len(rows)} row(s)")
    else:
        _say(f"  quarantine   absent: no {args.quarantine.name}, so nothing is quarantined")
    for one in findings:
        _say(f"  {'FAIL' if one.failing else 'note'}  {one.test_id}: {one.detail}")
    failing = [one for one in findings if one.failing]
    _say(f"Q-G18 {'FAIL' if failing else 'ok'}  {len(failing)} finding(s)")
    return EXIT_FAIL if failing else EXIT_CLEAN


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _read(path: Path) -> tuple[Flake, ...]:
    connection = open_oweval(path)
    try:
        return flakes(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
