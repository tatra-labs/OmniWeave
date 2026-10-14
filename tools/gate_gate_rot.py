"""Q-G17, gate rot: every gate row has an owner and a `review_by`, and none is past it. **D830.**

13-quality.md section 13.1 (:97): *"`Q-G17` | `eval/gates.toml`, `eval/counters.toml`,
`eval/quarantine.toml` | every row carries an owner and a `review_by`; a row past its date
fails"*. Section 15 (:2001) adds `fixtures/index.toml`, and section 4.4 (:544-547) says why: *"a
fixture's licence is exactly as perishable"*. 16-roadmap.md:982 names this file in P10's exit
criteria, *"every gate row's `review_by`"*, and `tools/gates.toml`'s header (:88-92) names it as
a reader of that register's rows. Section 8.3 (:1082-1084): *"There is no `--warn-only` anywhere"*.

This script reads TOML and compares dates. It imports nothing from `omniweave`, as
`tools/gate_budgets.py` does not: a register linter has no library half to share.

## Rulings

1. **The registers are `REGISTERS`, each with where its rows are.**
   - `eval/gates.toml`: each `[[gate]]`.
   - `eval/counters.toml`: its one `[gate]` table, which owns every `[[counter]]` (D823's shape;
     the charter prints counters without an owner each).
   - `eval/quarantine.toml`: each `[[quarantine]]`.
   - `tools/gates.toml`: each `[[gate]]` and `[[job_assertion]]`. A `[[gate.clause]]` belongs to
     its gate and carries no date of its own.
2. **A register that does not exist yet is named `absent`, not passed in silence.**
   `eval/quarantine.toml` lands with Q-G18's flake work. A register that exists and does not
   parse is exit 2.
3. **`fixtures/index.toml`'s rows are read from the sidecars it is generated from** (13:493,
   *"generated from the sidecars"*): every `*.meta.toml` under `fixtures/` and
   `packages/*/fixtures/`, whether or not Q-G1's generator has written the index yet. The index
   is derived, so its rows are theirs, and reading the source cannot go stale. A sidecar is a
   row when its provenance is `cc0`, `cc_by` or `public_domain`, which :547 gives a twelve-month
   window. `generated` and `authored` have *"no external dependency to rot"* and carry no date.
4. **A row is past its date on the date itself**: `review_by <= today` fails. This is the reading
   `tools/gate_tombstones.py` gives the same phrase, because a review that falls due today has not
   been done today.
5. **A row needs a non-empty `owner` and a `YYYY-MM-DD` `review_by`.** A missing or unreadable
   one is a finding, never a skip: a row with no readable clock is the rot this gate exists for.
6. **The clock is an argument.** `--today` defaults to the UTC wall date, the one impure call
   here. A test passes a fixed date so that its result does not depend on the day it runs.

## Exit codes

`0` every row is owned and in date. `1` a finding, named with its register, row and fix. `2` the
gate did not run: a register that does not parse, or a bad argument.

Specified in 13-quality.md sections 4.4, 8.3, 13.1 and 15, and 16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "EXTERNAL",
    "REGISTERS",
    "SIDECARS",
    "Finding",
    "Row",
    "Scan",
    "audit",
    "main",
    "rows",
    "today",
]

REPO = Path(__file__).resolve().parent.parent

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

REGISTERS: Final = (
    ("eval/gates.toml", ("gate",)),
    ("eval/counters.toml", ("[gate]",)),
    ("eval/quarantine.toml", ("quarantine",)),
    ("tools/gates.toml", ("gate", "job_assertion")),
)
"""Ruling 1: a register's path and the tables its rows are. `[gate]` is a single table."""

_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
"""Ruling 5's spelling. `date.fromisoformat` alone would also take `20261203`."""

SIDECARS: Final = ("fixtures/**/*.meta.toml", "packages/*/fixtures/**/*.meta.toml")
"""Ruling 3: where `fixtures/index.toml`'s rows come from."""

EXTERNAL: Final = frozenset({"cc0", "cc_by", "public_domain"})
"""Ruling 3: the provenances with something outside this repository to rot."""


@dataclass(frozen=True, slots=True)
class Row:
    """One clock: where it is, who owns it, and when it falls due, as written."""

    register: str
    label: str
    owner: object
    review_by: object


@dataclass(frozen=True, slots=True)
class Scan:
    """What `rows()` read: the clocks, the registers absent, and how many sidecars it opened."""

    rows: tuple[Row, ...]
    absent: tuple[str, ...]
    sidecars: int


@dataclass(frozen=True, slots=True)
class Finding:
    """One row that fails, and what its owner has to go do."""

    register: str
    label: str
    detail: str

    def line(self) -> str:
        return f"  {self.register}  {self.label}: {self.detail}"


def today() -> dt.date:
    """The wall clock, UTC (ruling 6)."""
    return dt.datetime.now(tz=dt.UTC).date()


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _label(row: dict[str, Any], table: str, at: int) -> str:
    for key in ("id", "metric", "test_id", "name"):
        if isinstance(row.get(key), str):
            return f"{table} {row[key]}"
    return f"{table} #{at}"


def rows(root: Path) -> Scan:
    """Every clock under `root`, and the registers that are absent (rulings 1-3)."""
    found: list[Row] = []
    absent: list[str] = []
    for rel, tables in REGISTERS:
        path = root / rel
        if not path.is_file():
            absent.append(rel)
            continue
        doc = _load(path)
        for table in tables:
            if table == "[gate]":
                head = doc.get("gate", {})
                if not isinstance(head, dict):
                    raise TypeError(f"{rel}: `gate` is not a table")
                found.append(Row(rel, "[gate]", head.get("owner"), head.get("review_by")))
                continue
            listed = doc.get(table, [])
            if not isinstance(listed, list):
                raise TypeError(f"{rel}: `{table}` is not an array of tables")
            for at, entry in enumerate(listed, start=1):
                row = entry if isinstance(entry, dict) else {}
                label = _label(row, table, at)
                found.append(Row(rel, label, row.get("owner"), row.get("review_by")))
    sidecars = sorted(path for pattern in SIDECARS for path in root.glob(pattern))
    for path in sidecars:
        fixture = _load(path).get("fixture", {})
        if isinstance(fixture, dict) and fixture.get("provenance") in EXTERNAL:
            rel = path.relative_to(root).as_posix()
            found.append(Row(rel, "fixture", fixture.get("owner"), fixture.get("review_by")))
    return Scan(tuple(found), tuple(absent), len(sidecars))


def audit(found: tuple[Row, ...], now: dt.date) -> list[Finding]:
    """Rulings 4 and 5."""
    out = []
    for row in found:
        if not isinstance(row.owner, str) or not row.owner.strip():
            out.append(Finding(row.register, row.label, "no owner; name the role that reviews it"))
        due = _date(row.review_by)
        if due is None:
            out.append(
                Finding(
                    row.register,
                    row.label,
                    f"review_by {row.review_by!r} is not a YYYY-MM-DD date; give it one",
                )
            )
        elif due <= now:
            out.append(
                Finding(
                    row.register,
                    row.label,
                    f"review_by {due.isoformat()} is not after {now.isoformat()}; review the row, "
                    "then move review_by forward or change its class in a reviewed diff",
                )
            )
    return out


def _date(value: object) -> dt.date | None:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _next(found: list[Row], now: dt.date) -> str:
    """`, next due <date> (<n> days)` over the readable dates, or nothing."""
    dates = sorted(d for d in (_date(row.review_by) for row in found) if d is not None)
    return f", next due {dates[0].isoformat()} ({(dates[0] - now).days} days)" if dates else ""


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """0 every row owned and in date, 1 a finding, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_gate_rot.py",
        description="Q-G17: every gate row's owner and review_by, and none past its date.",
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="DIR")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    now: dt.date = args.today or today()
    try:
        scan = rows(args.root)
    except (OSError, TypeError, ValueError) as exc:
        _say(f"Q-G17 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    findings = audit(scan.rows, now)
    _say(f"Q-G17  as of {now.isoformat()}")
    for rel, _tables in REGISTERS:
        if rel in scan.absent:
            _say(f"  {rel:<22} absent")
            continue
        mine = [row for row in scan.rows if row.register == rel]
        _say(f"  {rel:<22} {len(mine)} row(s){_next(mine, now)}")
    fixtures = [row for row in scan.rows if row.label == "fixture"]
    _say(
        f"  {'fixture sidecars':<22} {scan.sidecars} read, {len(fixtures)} with an external "
        f"provenance{_next(fixtures, now)}"
    )
    for finding in findings:
        _say(finding.line())
    _say(f"Q-G17 {'FAIL' if findings else 'ok'}  {len(findings)} finding(s)")
    return EXIT_FAIL if findings else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
