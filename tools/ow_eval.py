"""`ow eval golden --check <metric>` — the metric gates of `eval/gates.toml`, run.

`16-roadmap.md:519` is the P3 exit line this implements:

    uv run ow eval golden --check span_exact_rate        # Q-G6, hard, at 1.000

**Why a `tools/` script and not a CLI in the package.** `omniweave.cli` is P7's and
`packages/omniweave/src/omniweave/` is a bare skeleton, so this is the fifth application of the
standing pattern (ledger D25): the LIBRARY FUNCTION lives in the package and a `tools/` script
drives it. `omniweave_conform.evaluate` is the library half — `span_exact_rate()` and the
deterministic sampler — and everything in this file is argument parsing, driver activation, and
printing. There is no arithmetic here, which is what makes it a driver of the harness rather than
a second implementation of one. `tools/ow_conform.py` and `tools/ow_drivers.py` are the worked
examples and this follows their shape.

**Q-G6 is two halves and this is one of them.** `13-quality.md:1990` gives the row as
`G` (hard) + `L`: the `G` half is `span_exact_rate == 1.000` and the `L` half is *"`owcheck`'s
verbatim-implies-retained-part clause"*, which `omniweave_core.archive.owcheck` already
implements. A block that claims `verbatim` without a retained part is caught there, at archive
level, over a document that exists; this half asks the complementary question of a driver's
output at parse time, which is the only place the part's bytes are still in hand.

**What this needs that the accuracy gates need and it does not: nothing.** `13-quality.md:44` —
*"That needs no corpus, no labels and no model, which is why `span_exact_rate` is a **hard gate at
1.000** ... rather than a score with a floor."* The subjects in `eval/gates.toml` are the two
shipped drivers and their own fixtures. `fixtures/docs/`, the Tier A corpus with its ≥40%
real-public-domain-scan requirement, is what `structure_f1` and the rest of section 8.3's table
need, and conflating the two is how a hard gate gets deferred behind a licensing problem it never
had.

**A vacuous slice is printed, not hidden.** `parse.office.anydoc` claims verbatimness on no block
at all, so its denominator is zero and its rate is undefined. That is reported as `vacuous` — a
third state, never 1.0000 — beside the denominator share `17-risks.md` R-T16 names as its
indicator. R-T16's trigger is that share below 0.5 *while* the rate reports 1.000; the two read
together are the finding, so both are on the line.

## Exit codes

`0` every checked row met its budget (a vacuous slice does not fail; it has nothing to fail with).
`1` a row missed. `2` the gate could not run — an unknown metric, an unreadable register, a driver
that would not activate.

Specified in 13-quality.md sections 8.3 and 1.1, 11-repo-layout.md section 3.3, 01-principles.md
INV-10, and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
REGISTER = REPO / "eval" / "gates.toml"

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.evaluate import MetricResult, span_exact_rate  # noqa: E402
from omniweave_conform.harness import run_parse  # noqa: E402
from omniweave_conform.subject import Subject  # noqa: E402
from omniweave_ports.types import DriverError  # noqa: E402

__all__ = ["MEASURED", "GateRow", "Subject_", "main", "measure", "verdict"]

Subject_ = Subject  # re-exported so a test can build one without a second import path.

MEASURED: dict[str, Any] = {"span_exact_rate": span_exact_rate}
"""Metric name -> the function in `omniweave_conform.evaluate` that computes it.

A metric named in `eval/gates.toml` with no entry here is an **error**, not a skip: the register's
whole job is to say what is being measured, and a row nobody computes is a claim that something is
under a gate when it is not. `main()` exits 2 on one, naming it."""

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


@dataclass(frozen=True, slots=True)
class GateRow:
    """One `[[gate]]` row of `eval/gates.toml`."""

    metric: str
    kind: str
    budget: float
    guard: float | None
    row_class: str
    owner: str
    review_by: str
    sample_n: int

    @classmethod
    def of(cls, raw: dict[str, Any]) -> GateRow:
        return cls(
            metric=str(raw.get("metric", "")),
            kind=str(raw.get("kind", "")),
            budget=float(raw.get("budget", 0.0)),
            guard=float(raw["guard"]) if "guard" in raw else None,
            row_class=str(raw.get("class", "blocking")),
            owner=str(raw.get("owner", "")),
            review_by=str(raw.get("review_by", "")),
            sample_n=int(raw.get("sample_n", 1000)),
        )


@dataclass(frozen=True, slots=True)
class Measurement:
    """One metric over one subject slice."""

    slice_name: str
    driver_id: str
    result: MetricResult
    parsed: int = 0
    refused: tuple[str, ...] = ()
    """Fixtures the driver declined. NOT an error and NOT hidden.

    A driver's fixture set contains its abuse cases on purpose -- `truncated.docx`,
    `encrypted.odt`, `not_a_document.bin` -- and a `DriverError` over one of those is the driver
    working. Such a fixture yields no blocks and therefore no claims, which is correct. But
    swallowing refusals silently would let this metric report a clean 1.0000 for a driver that
    refused everything it was shown, so the count travels with the measurement and is printed.
    `capability._parse_all` takes the same decision for the same reason and reports it as an
    assertion; here it is a column.
    """


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def verdict(row: GateRow, result: MetricResult) -> tuple[bool, str]:
    """Does this measurement meet this row's budget?

    The comparison lives here and the measurement lives in `evaluate.py`, deliberately: a
    `MetricResult` that knew its own floor would be a floor with two homes, and `eval/gates.toml`
    is the one the plan names. `13-quality.md:1083` — "a downgrade is a `class` change in that
    file, a reviewed diff with an owner" — only works if the number in the file is the only number.
    """
    if result.value is None:
        return True, "vacuous: nothing claimed verbatimness, so nothing could fail"
    if row.kind == "hard":
        ok = result.value == row.budget
        return ok, f"hard at {row.budget:.4f}"
    if row.kind == "floor":
        return result.value >= row.budget, f"floor {row.budget:.4f}"
    if row.kind == "ceiling":
        return result.value <= row.budget, f"ceiling {row.budget:.4f}"
    return False, f"unknown kind {row.kind!r}"


def measure(metric: str, subject_row: dict[str, Any], row: GateRow) -> Measurement:
    """Activate one driver, parse its fixtures, and compute one metric over the result."""
    card = REPO / str(subject_row.get("card", ""))
    fixtures = REPO / str(subject_row.get("fixtures", ""))
    with tempfile.TemporaryDirectory(prefix="ow-eval-") as scratch:
        workdir = Path(scratch)
        subject = Subject.of(card, fixtures_dir=fixtures, workdir=workdir)
        driver = subject.instantiate()
        runs = []
        refused: list[str] = []
        for index, fixture in enumerate(subject.fixtures):
            try:
                runs.append(run_parse(driver, fixture, workdir / f"run-{index}"))
            except DriverError as exc:
                refused.append(f"{fixture.name} ({exc.cls.value})")
        result = MEASURED[metric](runs, driver, n=row.sample_n)
    return Measurement(
        slice_name=str(subject_row.get("slice", "?")),
        driver_id=subject.driver_id,
        result=result,
        parsed=len(runs),
        refused=tuple(refused),
    )


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911
    """`ow eval golden --check <metric>`. 0 met, 1 missed, 2 could not run.

    Seven returns, and `PLR0911` is silenced rather than satisfied: six of them are distinct
    ways the gate could not RUN -- no register, no row, a row nobody computes, no subject, a
    driver that would not activate -- and each names which one it was. Collapsing them into one
    "usage error" would be the branch counter improving the message a reader gets when a gate
    fails to run, which is the moment the message matters most.
    """
    parser = argparse.ArgumentParser(description="ow eval golden — the metric gates, run.")
    parser.add_argument("verb", choices=("golden",), help="the eval family. `golden` at P3.")
    parser.add_argument("--check", required=True, help="the metric name, e.g. span_exact_rate")
    parser.add_argument("--register", type=Path, default=REGISTER)
    args = parser.parse_args(argv)

    if not args.register.is_file():
        emit(f"ow eval: no register at {args.register}")
        return EXIT_USAGE
    register = tomllib.loads(args.register.read_text(encoding="utf-8"))

    rows = [GateRow.of(raw) for raw in register.get("gate", [])]
    matching = [row for row in rows if row.metric == args.check]
    if not matching:
        known = ", ".join(sorted(row.metric for row in rows)) or "<none>"
        emit(f"ow eval: {args.check!r} has no row in {args.register.name}; it holds: {known}")
        return EXIT_USAGE
    row = matching[0]
    if row.metric not in MEASURED:
        emit(
            f"ow eval: {row.metric!r} has a register row and no implementation. A row nobody "
            f"computes is a claim that something is under a gate when it is not."
        )
        return EXIT_USAGE

    subjects = register.get("subject", [])
    if not subjects:
        emit(f"ow eval: {args.register.name} names no [[subject]] to measure over")
        return EXIT_USAGE

    measurements: list[Measurement] = []
    for subject_row in subjects:
        try:
            measurements.append(measure(row.metric, subject_row, row))
        except Exception as exc:
            emit(f"ow eval ERROR  {subject_row.get('slice', '?')}: {type(exc).__name__}: {exc}")
            return EXIT_USAGE

    failed = 0
    emit(
        f"{row.metric}  ({row.kind} at {row.budget:.4f}, owner {row.owner}, "
        f"review by {row.review_by})"
    )
    emit()
    for measurement in measurements:
        ok, why = verdict(row, measurement.result)
        mark = "ok  " if ok else "FAIL"
        emit(f"  {mark}  {measurement.slice_name:<20} {measurement.result.line()}")
        emit(
            f"        {measurement.driver_id} — {why}; "
            f"{measurement.parsed} fixture(s) parsed, {len(measurement.refused)} refused"
        )
        for refusal in measurement.refused[:4]:
            emit(f"        refused: {refusal}")
        if not ok:
            failed += 1
            for failure in measurement.result.failures[:10]:
                emit(f"        {failure}")
        emit()

    vacuous = sum(1 for m in measurements if m.result.value is None)
    measured = len(measurements) - vacuous
    if failed:
        emit(f"Q-G6 FAIL  {failed} of {len(measurements)} slice(s) missed {row.metric}.")
        return EXIT_FAIL
    emit(
        f"Q-G6 ok  {measured} slice(s) measured, {vacuous} vacuous, over "
        f"{len(measurements)} subject(s)."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
