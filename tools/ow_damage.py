"""The absence suite's deterministic half, printed: every built Injector over its fixtures.

Q-G7's paired-damage half (13-quality.md section 8.6), and the line of P6's exit criteria it stands
for (16-roadmap.md, section 9):

    uv run ow eval run --suite absence --deterministic-half

That verb exists since D869, and writes its run into the `.oweval`. This script is its printed
twin for a developer and for `tools/acceptance_v10.py`: it runs the same harness,
`omniweave_conform.absence.run_suite()`, with the same admission,
`omniweave.surface.admit.admit()`, and prints every pair's four clauses, which the verb does not.
The harness lived here until D869; it moved so the verb could run it without a script.

## Exit codes

`0` every pair passed. `1` a pair failed. `2` the suite could not run: no register row, a fixture
that would not build, or an unknown `--injector`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

REPO: Final = Path(__file__).resolve().parent.parent
REGISTER: Final = REPO / "eval" / "gates.toml"

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave.surface.admit import admit  # noqa: E402
from omniweave_conform.absence import FIXTURES, PROJECT, Fixture, build, run_suite  # noqa: E402
from omniweave_conform.absence import documents_of as _documents_of  # noqa: E402
from omniweave_conform.damage import INJECTORS, TABLE  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["FIXTURES", "METRIC", "PROJECT", "Fixture", "admit", "build", "main"]

METRIC: Final = "degradation_detection"
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _documents(fixture: Fixture) -> dict[str, bytes]:
    """The fixture's documents, generated from this checkout.

    Reached only from `test_ow_damage.py`, which asserts the fixtures are
    `fixtures/gen/gen_reference_corpora.py`'s files byte for byte. `pyright` reports it
    unused because the pyright scope excludes the test tier -- see pyproject.toml.
    """
    return _documents_of(fixture, REPO)


def _row(register: Path) -> Mapping[str, Any] | None:
    if not register.is_file():
        return None
    rows = tomllib.loads(register.read_text(encoding="utf-8")).get("gate", [])
    return next((row for row in rows if row.get("metric") == METRIC), None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow_damage",
        description="The deterministic half of the absence suite: every built Injector, "
        "damaged, read, fixed and read again (13-quality.md section 8.6).",
    )
    parser.add_argument("--deterministic-half", action="store_true", help="the only half built")
    parser.add_argument("--injector", action="append", help="run only these Injectors")
    parser.add_argument("--keep", type=Path, help="keep every fixture project under this folder")
    parser.add_argument("--json", type=Path, help="also write the report as JSON here")
    parser.add_argument(
        "--workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="fixture builds run at once; each is one `ow add` (default: min(4, cores))",
    )
    parser.add_argument("--register", type=Path, default=REGISTER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run every built Injector over its fixtures. 0 passed, 1 failed, 2 could not run."""
    args = _parser().parse_args(argv)
    row = _row(args.register)
    if row is None:
        emit(f"ow_damage: {args.register} has no {METRIC} row; the gate has no budget to meet")
        return EXIT_USAGE
    chosen = list(INJECTORS) if not args.injector else list(dict.fromkeys(args.injector))
    unknown = [name for name in chosen if name not in INJECTORS]
    if unknown:
        owed = [one.name for one in TABLE if one.name not in INJECTORS]
        emit(f"ow_damage: {unknown} are not built; built: {list(INJECTORS)}; owed: {owed}")
        return EXIT_USAGE
    emit(
        f"{METRIC}  (hard at {float(row['budget']):.4f} over every (Injector, fixture) pair; "
        f"owner {row.get('owner')}, review by {row.get('review_by')})"
    )
    emit()
    try:
        suite = run_suite(
            chosen,
            root=REPO,
            admit=admit,
            now_ns=time.time_ns,
            workers=args.workers,
            keep=args.keep,
        )
    except (RuntimeError, OSError) as exc:
        emit(f"ow_damage: the suite could not run: {type(exc).__name__}: {exc}")
        return EXIT_USAGE
    results = suite.assessments
    for result in results:
        emit(f"  {'ok  ' if result.ok else 'FAIL'}  {result.injector} x {result.fixture}")
        for clause in result.clauses:
            mark = "ok  " if clause.ok else "FAIL"
            emit(f"          {mark}  {clause.name}: {clause.why}")
        emit()
    passed = sum(1 for result in results if result.ok)
    owed = [one.name for one in TABLE if one.name not in INJECTORS]
    value = passed / len(results) if results else None
    emit(f"  population: {len(INJECTORS)} of {len(TABLE)} Injectors built; owed: {', '.join(owed)}")
    if args.json is not None:
        report = {
            "metric": METRIC,
            "value": value,
            "pairs": [
                {
                    "injector": result.injector,
                    "fixture": result.fixture,
                    "ok": result.ok,
                    "clauses": [{"name": c.name, "ok": c.ok, "why": c.why} for c in result.clauses],
                }
                for result in results
            ],
            "built": list(INJECTORS),
            "owed": owed,
        }
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if value is None:
        emit("ow_damage: no pair ran")
        return EXIT_USAGE
    emit(f"{METRIC} = {value:.4f} over {len(results)} pair(s)")
    return EXIT_OK if passed == len(results) else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
