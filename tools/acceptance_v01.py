"""V01-1 .. V01-17: v0.1's acceptance set, rolled up from the instruments that measure it.

16-roadmap.md:747 runs this as P7's last exit criterion, and 16:750 fixes its content: *"Its
acceptance set is 00-vision.md section 9.1's seventeen criteria, verbatim; this document adds
nothing to it and subtracts nothing from it."* So this script measures nothing itself. Every row
names the gates and tests that already measure it, runs them, and reports what they could and
could not say.

## Four verdicts, and only one of them is acceptance

* **PASS** -- every instrument exits 0 AND the instruments together assert every clause of the
  criterion.
* **PARTIAL** -- every instrument exits 0, and some clause of the criterion is asserted by none of
  them. The row names the clause. A green test over half a criterion is not the criterion, and a
  roll-up that printed PASS for it would be the defect INV-20 names: a front door that lies.
* **FAIL** -- an instrument exited non-zero. A mistyped pytest node collects nothing and exits
  non-zero, so the table cannot silently point at nothing.
* **UNMEASURED** -- nothing in the tree measures it, or its instrument needs what a local run
  cannot have (CI job timings, a clean machine, recorded agent sessions), or it is slow and
  `--slow` was not passed.

Exit 0 only when all seventeen are PASS. Today that is false, and the report says which rows and
why: the P7 exit command is meant to fail until v0.1 is actually accepted.

## Where the coverage judgments come from

Each row's `coverage` and `gap` were read off the instruments' bodies, not their names, in W7.8a:
every named file and test was opened, every fast one run. They are declarations, and a reviewer
checks them the way a register row is checked. A row moves to FULL when a clause's instrument
lands, in the same commit, which is how `tools/gates.toml` moves `runner_planned` to `runner`.

Run it:

    uv run tools/acceptance_v01.py              # every row but the slow one
    uv run tools/acceptance_v01.py --slow       # V01-10/11's 5,000-page measurement (minutes)
    uv run tools/acceptance_v01.py --only V01-3,V01-12
    uv run tools/acceptance_v01.py --json

Exit codes: `0` all seventeen PASS, `1` any row is not PASS, `2` a usage error from argparse.

Specified in 00-vision.md section 9.1 (:695-718) and 16-roadmap.md section 10 (:747-751).
"""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: TID251 - every instrument is a gate or a test run as its own process.
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

__all__ = ["CRITERIA", "Coverage", "Criterion", "Instrument", "Result", "Verdict", "judge", "main"]

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE = "packages/omniweave-core/tests"
CLI = "packages/omniweave/tests/unit"


class Coverage(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class Verdict(StrEnum):
    PASS = "PASS"  # noqa: S105 -- a verdict, not a credential
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True, slots=True)
class Instrument:
    """One command. `argv` after the interpreter: a `tools/` script, or `-m pytest ...`."""

    label: str
    argv: tuple[str, ...]
    slow: bool = False
    timeout_s: int = 600


def tool(script: str, *args: str, slow: bool = False) -> Instrument:
    return Instrument(
        label=f"tools/{script} {' '.join(args)}".strip(), argv=(f"tools/{script}", *args), slow=slow
    )


def pytest(*selectors: str, label: str = "") -> Instrument:
    shown = label or " ".join(selectors)
    return Instrument(
        label=f"pytest {shown}", argv=("-m", "pytest", "-q", "-p", "no:cacheprovider", *selectors)
    )


def module(*args: str) -> Instrument:
    return Instrument(label=f"python -m {' '.join(args)}", argv=("-m", *args))


@dataclass(frozen=True, slots=True)
class Criterion:
    id: str
    text: str
    instruments: tuple[Instrument, ...]
    coverage: Coverage
    gap: str = ""
    """What no instrument asserts. Required unless `coverage` is FULL."""

    def __post_init__(self) -> None:
        if (self.coverage is Coverage.FULL) == bool(self.gap):
            msg = f"{self.id}: a gap is required exactly when coverage is not full"
            raise ValueError(msg)
        if (self.coverage is Coverage.NONE) != (not self.instruments):
            msg = f"{self.id}: coverage NONE exactly when there is no instrument"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# The seventeen, in 00-vision.md:702-718's order. Criterion text is abridged, never restated.
# ---------------------------------------------------------------------------

CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "V01-1",
        "omniweave-core resolves to core + ports and zero third-party; ports to itself alone",
        (tool("gate_core_pure.py"),),
        Coverage.FULL,
    ),
    Criterion(
        "V01-2",
        "import omniweave_core loads no third-party module, no asyncio/selectors, none of the nine",
        (tool("gate_importtime.py"), tool("gate_lazy_core.py")),
        Coverage.FULL,
    ),
    Criterion(
        "V01-3",
        "import core <= 80 ms; ow --version <= 150; ow --help <= 250; 20-dist discovery <= 20",
        (tool("gate_coldstart.py"),),
        Coverage.PARTIAL,
        "the import, `ow --version` and `ow --help` rows are timed against their ceilings "
        "(the console script landed in W7.8l, D619); the 20-dist row needs a 20-dist "
        "environment; the 25% band fails only on the pinned runner that calibrated the "
        "baseline, and no runner is pinned until CI returns at P10, so OQ-4 is measured on one "
        "unpinned Windows machine and on no runner class (D622)",
    ),
    Criterion(
        "V01-4",
        "a rogue driver never runs; ow doctor exits 0, the file is absent; 30 cards import nothing",
        (
            tool("gate_discovery_no_import.py"),
            pytest(
                f"{CORE}/unit/test_discovery_never_imports.py",
                label="thirty cards discovered, no driver key in sys.modules (INV-4 layer 3)",
            ),
        ),
        Coverage.FULL,
    ),
    Criterion(
        "V01-5",
        "span_exact_rate == 1.000 over claimed-verbatim Blocks; none verbatim without store_ref",
        (
            tool("ow_eval.py", "golden", "--check", "span_exact_rate"),
            pytest(
                f"{CORE}/unit/test_owdoc_roundtrip.py::"
                "test_owcheck_passes_over_both_ends_of_the_corpus_round_trip",
                f"{CORE}/unit/test_archive_owcheck.py",
                "-k",
                "verbatim or owcheck_passes",
                label="owcheck's verbatim clause over the round-trip corpus",
            ),
        ),
        Coverage.FULL,
    ),
    Criterion(
        "V01-6",
        "Locus.reason iff quad is None; only Quad.from_driver reached; no quad/bbox/poly L3 column",
        (
            tool("gate_schema_lint.py"),
            pytest(f"{CORE}/unit/test_model_spans.py", label="Quad and 01:1191's scan (W7.8f)"),
            pytest(f"{CORE}/unit/test_model_locus.py", label="Locus: INV-9 as a type (W7.8r)"),
            pytest(
                f"{CORE}/unit/test_owdoc_roundtrip.py",
                "-k",
                "v01_6",
                label="every block of the three fixture stores locates (W7.8r)",
            ),
        ),
        Coverage.FULL,
    ),
    Criterion(
        "V01-7",
        "import(export(store)) == store over the fixture corpus",
        (pytest(f"{CORE}/unit/test_owdoc_roundtrip.py", label="G28's runner"),),
        Coverage.FULL,
    ),
    Criterion(
        "V01-8",
        "fifteen absence gates, one fixture each, one ABSENT site; a corrupt block_fts is degraded",
        (
            tool("gate_one_absent_site.py"),
            pytest(f"{CORE}/unit/test_retrieve_verdict.py", label="the fifteen, one test each"),
            pytest(
                f"{CORE}/unit/test_retrieve_execute.py",
                "-k",
                "corrupt_block_fts or store_verify_fts or malformed_match",
                label="ST8's fault injection: a corrupt block_fts is degraded (W7.8b)",
            ),
        ),
        Coverage.FULL,
    ),
    Criterion(
        "V01-9",
        "SIGKILL at every statement boundary of Store.complete() converges; three random points",
        (tool("gate_crash.py", "--all"), tool("gate_crash.py")),
        Coverage.FULL,
    ),
    Criterion(
        "V01-10",
        "store.bytes_per_block <= 660 B +/- 10% on the 5,000-page generated PDF",
        (),  # replaced by `_with_workspace`: a per-run workspace, never the tree
        Coverage.NONE,
        "placeholder",
    ),
    Criterion(
        "V01-11",
        "peak RSS on the 5,000-page fixture <= 1,610,612,736 bytes +/- 10%",
        (),  # replaced by `_with_workspace`: the same run as V01-10's, reused
        Coverage.NONE,
        "placeholder",
    ),
    Criterion(
        "V01-12",
        "tools/list <= 1,900 tokens, per-tool <= 700, instructions <= 1,000 chars; seven artefacts",
        (
            pytest(f"{CLI}/test_gen_budget.py", label="SV2 (D375: the test is its home)"),
            module("omniweave", "surface", "emit", "--check"),
            pytest(
                f"{CLI}/test_gen_cli_tree.py",
                "-k",
                "grammar or trailing_s",
                label="no two CLI groups differ by a trailing s",
            ),
        ),
        Coverage.PARTIAL,
        "the `full` profile's instructions are 1,031 and 1,050 chars against the 1,000 cap, which "
        "the SV2 test accepts as a known breach (D313); the instructions string has no file for "
        "`emit --check` to diff",
    ),
    Criterion(
        "V01-13",
        "set(listed) <= set(enabled) and no human-only Action on an agent surface, at startup",
        (
            pytest(f"{CLI}/test_surface_registry.py", "-k", "sv1", label="SV1, the registry"),
            pytest(f"{CLI}/test_surface_startup.py", "-k", "sv1", label="SV1, at startup"),
        ),
        Coverage.FULL,
    ),
    Criterion(
        "V01-14",
        "CI: gates <= 3 min, conform <= 5 min, contributor-parity clean, <= 7 min (600 s ceiling)",
        (),
        Coverage.NONE,
        "job timings exist only in CI, which is off until P10; `ci.job_seconds` and "
        "`eval/counters.toml` do not exist",
    ),
    Criterion(
        "V01-15",
        "first_answer_seconds <= 600: ow install -> ow add -> ow query, cited, 100 office docs",
        (
            pytest(
                "bench/serve/test_first_answer.py", label="the folder, the judge, the exit (W7.7c)"
            ),
            Instrument(
                label="bench/serve/first_answer.py: 100 office documents, three children, timed",
                argv=("bench/serve/first_answer.py",),
                timeout_s=900,
            ),
        ),
        Coverage.PARTIAL,
        "timed on this machine, which is not a clean 4-core one; and no cite can carry a page: "
        "every office document is one `stream` page, because anydoc flattens a PPTX's slides and "
        "a DOCX has no page boxes (D615, D634)",
    ),
    Criterion(
        "V01-16",
        "ow doctor fails with OW-S-060 on a git-tracked store; .gitignore covers .owstore",
        (
            pytest(f"{CLI}/test_doctor.py", label="D-02 and the ow doctor verb (W7.8c)"),
            pytest(
                "packages/omniweave/tests/conform/test_doctor_git.py",
                label="against real git: a committed store, the shipped .gitignore, this index",
            ),
        ),
        Coverage.FULL,
    ),
    Criterion(
        "V01-17",
        "every format class has an enabled covering Driver or a named reason; Kind.SECTION out",
        (
            pytest(
                "packages/omniweave-office/tests/unit/test_office_card.py::"
                "test_the_declared_formats_are_exactly_the_drivers_media_types",
                label="the office card's twelve formats",
            ),
            pytest(
                f"{CLI}/test_format_classes.py",
                label="section 2.1's classes against [drivers] enabled cards (W7.8d)",
            ),
        ),
        Coverage.FULL,
    ),
)


def _with_workspace(workspace: Path) -> tuple[Criterion, ...]:
    """V01-10's and V01-11's rows, over ONE real-driver run kept in a scratch directory.

    Both read `measure_store.py --driver pdfium` (D629): `ow add` over the 5,000-page fixture, the
    product's store sized for V01-10 and the worker's sampled peak for V01-11. `--reuse` makes the
    second row size the first row's kept project rather than ingest again, and the first row that
    runs -- either one under `--only` -- is the one that ingests.
    """

    def measured(gate: str) -> Instrument:
        return tool(
            "measure_store.py",
            "--driver",
            "pdfium",
            gate,
            "--reuse",
            "--workspace",
            str(workspace / "store"),
            "--out",
            str(workspace / "gen_5000p.pdf"),
            slow=True,
        )

    v0110 = Criterion(
        "V01-10",
        CRITERIA[9].text,
        (measured("--gate"),),
        Coverage.PARTIAL,
        "measured through `ow add` and parse.pdf.pdfium, and an indication rather than a budget "
        "until `ow-bench-1` exists (D25, D31)",
    )
    v0111 = Criterion(
        "V01-11",
        CRITERIA[10].text,
        (measured("--gate-rss"),),
        Coverage.PARTIAL,
        "the worker's peak, an indication until `ow-bench-1` (D25). The row is anydoc's fork "
        "tripwire and anydoc refuses a PDF, and pdfium's card caps its worker at memory_mb = 1024, "
        "under the row, so the row cannot fire on the driver that parses this fixture (D629)",
    )
    return (*CRITERIA[:9], v0110, v0111, *CRITERIA[11:])


# ---------------------------------------------------------------------------
# Running and judging
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Result:
    id: str
    verdict: Verdict
    gap: str
    ran: list[dict[str, object]] = field(default_factory=list)


def _run(instrument: Instrument) -> dict[str, object]:
    started = time.perf_counter()
    try:
        done = subprocess.run(  # noqa: S603 -- fixed argv from the table, argv[0] is sys.executable
            [sys.executable, *instrument.argv],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            timeout=instrument.timeout_s,
        )
        code = done.returncode
        tail = (done.stdout + done.stderr).decode("utf-8", "replace").strip().splitlines()[-1:]
    except subprocess.TimeoutExpired:
        code, tail = -1, [f"timed out after {instrument.timeout_s} s"]
    return {
        "instrument": instrument.label,
        "exit": code,
        "seconds": round(time.perf_counter() - started, 1),
        "last_line": tail[0] if tail else "",
    }


def judge(criterion: Criterion, exits: list[int] | None) -> Verdict:
    """The verdict from the declared coverage and the instruments' exits (None: not run). Pure."""
    if criterion.coverage is Coverage.NONE or exits is None:
        return Verdict.UNMEASURED
    if any(code != 0 for code in exits):
        return Verdict.FAIL
    return Verdict.PASS if criterion.coverage is Coverage.FULL else Verdict.PARTIAL


def evaluate(criterion: Criterion, *, slow: bool) -> Result:
    if criterion.instruments and any(one.slow for one in criterion.instruments) and not slow:
        return Result(criterion.id, Verdict.UNMEASURED, f"slow: pass --slow. {criterion.gap}")
    ran = [_run(one) for one in criterion.instruments]
    exits = [int(str(one["exit"])) for one in ran] if criterion.instruments else None
    return Result(criterion.id, judge(criterion, exits), criterion.gap, ran)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="acceptance_v01", description=(__doc__ or "").split("\n", 1)[0]
    )
    parser.add_argument(
        "--slow", action="store_true", help="also run V01-10 and V01-11's 5,000-page measurement"
    )
    parser.add_argument("--only", default="", help="comma-separated criterion ids")
    parser.add_argument("--json", action="store_true", help="print the results as JSON")
    args = parser.parse_args(argv)
    wanted = {one.strip() for one in args.only.split(",") if one.strip()}
    with tempfile.TemporaryDirectory() as scratch:
        rows = [one for one in _with_workspace(Path(scratch)) if not wanted or one.id in wanted]
        unknown = wanted - {one.id for one in rows}
        if unknown:
            parser.error(f"unknown criterion id(s): {', '.join(sorted(unknown))}")
        results = [evaluate(one, slow=args.slow) for one in rows]
    if args.json:
        sys.stdout.write(json.dumps([asdict(one) for one in results], indent=2) + "\n")
    else:
        for result, criterion in zip(results, rows, strict=True):
            sys.stdout.write(f"{result.verdict:<10} {result.id:<6} {criterion.text}\n")
            for ran in result.ran:
                shown = f"exit {ran['exit']:<3} {ran['seconds']:>6} s  {ran['instrument']}"
                sys.stdout.write(f"             {shown}\n")
            if result.gap:
                sys.stdout.write(f"             gap: {result.gap}\n")
        tally = {
            verdict: sum(1 for one in results if one.verdict is verdict) for verdict in Verdict
        }
        shown = "  ".join(f"{verdict} {count}" for verdict, count in tally.items())
        sys.stdout.write(f"V01: {shown}  of {len(results)}\n")
    return 0 if all(one.verdict is Verdict.PASS for one in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
