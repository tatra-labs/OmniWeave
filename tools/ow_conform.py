"""Run the twelve conformance suites against a driver card, with the four halves a library cannot.

`omniweave_conform` holds the mechanism. This file holds the process control, and that division is
ledger D25's standing pattern -- worked by `tools/schemagen.py` for `ow schema emit`,
`tools/gate_crash.py` for `ow test crash-matrix`, `tools/measure_store.py` for `ow eval perf`,
`tools/ow_drivers.py` for `ow drivers` and `tools/ow_host.py` for the `subproc` host. There is no
`ow` verb yet: 16-roadmap.md section 10 puts the CLI at P7, so `ow conform` cannot wrap anything
today, and this is the half that will be wrapped.

## The four assertions that only exist here, and why each one needs a process

`packages/*/src/**` may not call `subprocess` -- `tools/semgrep/omniweave.yaml`'s
`omniweave-no-subprocess-outside-toolchain-and-host-subproc` names the only two homes, and neither
is the kit. So four claims are unmakeable from inside `omniweave_conform` and are made here:

* **`idempotence`** -- "and again through two processes" (04:2077). There must BE a second one.
* **`determinism`** -- `byte_exact` across differing `PYTHONHASHSEED` and cwd (04:2077).
  `PYTHONHASHSEED` is read at interpreter startup and cannot be changed afterwards, and cwd is an
  ambient input library code may not touch at all.
* **`fuzz`** -- "ships a deliberate segfault fixture and asserts the run completes" (04:2082). A
  segfault must be survived by something outside the segfaulting thing.
* **`purity`** -- discovery imported no driver module. Once a process has imported the module for
  its own reasons `sys.modules` cannot say who did it, and
  `test_discovery_never_imports.py:23-25` makes the fresh interpreter "the only place either is
  observable".

Each result is passed back through `Subject.measurements`, where the suite that needs it reads
it by key. It is NOT `Subject.config`: that field is the DRIVER's `[config]` values and its card
declares `additionalProperties = false`, so the kit's own bookkeeping travelling through it hands
every driver four keys its schema is obliged to reject. It did, once.
The suites do not know a subprocess happened; they know a measurement arrived or did not, and they
say which.

## One varied child, not two

The child runs with `PYTHONHASHSEED=1`, a different cwd, a different `TMPDIR`, `TZ` and `LC_ALL`,
and its digests are handed to BOTH `idempotence` and `determinism`. That is deliberate: what
`idempotence` asks for is "another process", and a process that differs in five ambient inputs is
strictly more demanding than one that differs in none. Spawning a second, unvaried child to satisfy
the weaker claim separately would cost a process to ask an easier question, and a difference in
either would be a real finding either way.

## What this does NOT do, and says so

G3's third scan -- the unpacked artifacts -- is not performed and is not this tool's to perform:
it is a repository-wide gate over omniweave's own built wheels, and `tools/gate_licences.py`
runs it. The conform `licence` suite's row (04:2081) names two graphs, and both of them run
in-process. `--bench` is
13-quality.md section 12.2's benchmark run and needs a registered corpus fetched by `ow eval fetch`,
which is P10's; this tool refuses the flag by naming what is missing rather than writing an empty
`[quality]` block.

Usage:

    python tools/ow_conform.py --card <driver.toml> --fixtures <dir>
    python tools/ow_conform.py --card <driver.toml> --fixtures <dir> --badge
    python tools/ow_conform.py --card <driver.toml> --fixtures <dir> --write
    python tools/ow_conform.py --template          # the shipped conformance-template driver

Exit codes: 0 the mandatory tier passed, 1 it did not, 2 the card or the fixtures could not be
read. `ow doctor`'s convention, and the same one every other `tools/` gate uses.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess  # noqa: TID251 -- D25: the mechanism is in the package, the spawn is here.
import sys
import tempfile
from pathlib import Path

# The badge carries U+00B7 and an author copies it out of this terminal. On a Windows console
# defaulting to cp1252 that renders as a replacement character, which would make the one
# string 04-driver-system.md:2115 requires to be GENERATED unusable the moment it is.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "packages/omniweave-conform/src/omniweave_conform/template"

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform import Subject, badge, report_lines, run, sentence  # noqa: E402
from omniweave_conform.harness import load_fixtures, run_parse  # noqa: E402
from omniweave_conform.publish import check as publish_check  # noqa: E402
from omniweave_conform.publish import write_results  # noqa: E402
from omniweave_conform.result import MANDATORY  # noqa: E402
from omniweave_conform.runner import mandatory_budget_exceeded  # noqa: E402
from omniweave_conform.suites import determinism as determinism_suite  # noqa: E402
from omniweave_conform.suites import fuzz as fuzz_suite  # noqa: E402
from omniweave_conform.suites import idempotence as idempotence_suite  # noqa: E402
from omniweave_conform.suites import purity as purity_suite  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

CHILD_TIMEOUT_S = 120
"""Wall clock for a child. Generous against the five-minute mandatory budget, and finite because
this tool is the thing that enforces "a hang is not allowed" -- a hang detector that can itself
hang is a hang detector with an extra process."""

VARIED_ENV = {
    "PYTHONHASHSEED": "1",
    "TZ": "Pacific/Kiritimata",
    "LC_ALL": "tr_TR.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}
"""The ambient inputs the child differs in. `PYTHONHASHSEED=1` rather than `random`, so a failure
reproduces: a parent that cannot tell you which seed broke the child has reported a flake."""


def _child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(VARIED_ENV)
    env["PYTHONPATH"] = os.pathsep.join(
        str(d / "src") for d in sorted((REPO / "packages").iterdir()) if (d / "src").is_dir()
    )
    env.update(extra or {})
    return env


def _spawn(
    mode: str, card: Path, fixtures: Path | None, *, cwd: Path
) -> subprocess.CompletedProcess[str]:
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child-mode",
        mode,
        "--card",
        str(card),
    ]
    if fixtures is not None:
        argv += ["--fixtures", str(fixtures)]
    return subprocess.run(  # noqa: S603 -- argv is built here, never from the card or a fixture.
        argv,
        check=False,
        capture_output=True,
        text=True,
        env=_child_env(),
        cwd=str(cwd),
        timeout=CHILD_TIMEOUT_S,
    )


# ---------------------------------------------------------------------------------------------
# The child modes. Each prints one JSON object on stdout and nothing else, so the parent parses
# the last line rather than the whole stream -- a driver that writes to stdout during a parse is
# a badly behaved driver, not a broken protocol.
# ---------------------------------------------------------------------------------------------


def _child_digests(card: Path, fixtures: Path) -> int:
    """Parse every fixture and print `{fixture name: sha256(fragment body)}`."""
    with tempfile.TemporaryDirectory() as scratch:
        subject = Subject.of(card, fixtures_dir=fixtures, workdir=Path(scratch))
        driver = subject.instantiate()
        out: dict[str, str] = {}
        for index, fixture in enumerate(subject.fixtures):
            try:
                result = run_parse(driver, fixture, Path(scratch) / f"f{index}")
            except Exception as exc:
                # A refusal is the parent's finding to report, through the suite that owns it.
                # Omitting the name from the map is how this child says "no digest for that one".
                del exc
                continue
            out[fixture.name] = hashlib.sha256(result.body).hexdigest()
    print(json.dumps(out))  # noqa: T201 -- this IS the child's return value.
    return EXIT_OK


def _child_purity(card: Path, fixtures: Path | None) -> int:
    """Run the `purity` suite in an interpreter that has imported no driver module."""
    with tempfile.TemporaryDirectory() as scratch:
        subject = Subject.of(card, fixtures_dir=fixtures, workdir=Path(scratch))
        result = purity_suite.run(subject)
    print(  # noqa: T201
        json.dumps(
            {
                "verdict": result.verdict.value,
                "summary": result.summary,
                "watched": list(purity_suite.watched_names(subject)),
                "failures": [a.line() for a in result.failures()],
            }
        )
    )
    return EXIT_OK


def _child_segfault(card: Path, fixtures: Path) -> int:
    """Parse one fixture, then die the way a native extension dies. Never returns.

    `ctypes.string_at(1)` dereferences address 1. That is a real access violation on Windows and a
    real SIGSEGV on Linux and macOS -- not `sys.exit`, not an exception, and not something a
    `try`/`except` in this process can catch, which is the whole point: 04-driver-system.md:2082
    wants the run to complete *around* a crash, and a crash a parent can be talked out of noticing
    would not test that.
    """
    import ctypes  # noqa: PLC0415 -- only this mode needs it.

    with tempfile.TemporaryDirectory() as scratch:
        subject = Subject.of(card, fixtures_dir=fixtures, workdir=Path(scratch))
        driver = subject.instantiate()
        if subject.fixtures:
            # The crash below is the subject; whether the parse succeeded is irrelevant to it, and
            # a refusal here must not stop this child from reaching the line that matters.
            with contextlib.suppress(Exception):
                run_parse(driver, subject.fixtures[0], Path(scratch) / "pre")
    sys.stdout.flush()
    ctypes.string_at(1)
    return EXIT_FAIL  # pragma: no cover -- unreachable; the line above does not return.


CHILD_MODES = {
    "digests": _child_digests,
    "purity": _child_purity,
    "segfault": _child_segfault,
}


# ---------------------------------------------------------------------------------------------
# The parent.
# ---------------------------------------------------------------------------------------------


def _cross_process(card: Path, fixtures: Path, *, quiet: bool) -> tuple[dict[str, str], str]:
    """One varied child, whose digests both `idempotence` and `determinism` read."""
    with tempfile.TemporaryDirectory() as elsewhere:
        done = _spawn("digests", card, fixtures, cwd=Path(elsewhere))
    if done.returncode != EXIT_OK or not done.stdout.strip():
        note = f"the child exited {done.returncode}: {(done.stderr or '').strip()[:200]}"
        if not quiet:
            print(f"  cross-process child FAILED: {note}")  # noqa: T201
        return {}, note
    try:
        digests = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return {}, f"the child printed something that is not JSON: {exc}"
    return digests, f"{len(digests)} fixtures, PYTHONHASHSEED=1, a different cwd, TZ and LC_ALL"


def _segfault_survived(card: Path, fixtures: Path) -> tuple[bool, str]:
    """Spawn the deliberate segfault and report whether this process is still here to say so."""
    with tempfile.TemporaryDirectory() as elsewhere:
        try:
            done = _spawn("segfault", card, fixtures, cwd=Path(elsewhere))
        except subprocess.TimeoutExpired:
            return False, (
                f"the child neither crashed nor returned within {CHILD_TIMEOUT_S}s: a hang, "
                f"which is the one outcome this row forbids"
            )
    crashed = done.returncode != EXIT_OK
    return crashed, (
        f"the child died with exit status {done.returncode} and this process continued; "
        f"a crash is one row, a hang is the run"
        if crashed
        else "the child returned 0, so nothing crashed and the containment was not exercised"
    )


def _purity_in_a_clean_process(card: Path, fixtures: Path | None) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as elsewhere:
        done = _spawn("purity", card, fixtures, cwd=Path(elsewhere))
    if done.returncode != EXIT_OK or not done.stdout.strip():
        return "unknown", f"the child exited {done.returncode}: {(done.stderr or '').strip()[:200]}"
    try:
        payload = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return "unknown", f"the child printed something that is not JSON: {exc}"
    watched = ", ".join(payload.get("watched", ()))
    failures = "; ".join(payload.get("failures", ()))
    return payload.get("verdict", "unknown"), (
        f"{payload.get('summary', '')} [watched in a clean interpreter: {watched}]"
        + (f" FAILURES: {failures}" if failures else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ow_conform",
        description="Run the twelve conformance suites against a driver card.",
    )
    parser.add_argument("--card", type=Path, help="path to the driver's driver.toml")
    parser.add_argument("--fixtures", type=Path, help="directory of inputs to run the driver over")
    parser.add_argument(
        "--template",
        action="store_true",
        help="run against the shipped conformance-template driver and its fixtures",
    )
    parser.add_argument("--badge", action="store_true", help="print the badge string and exit")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write [quality.suites] and a recomputed attestation into the card",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--bench", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--child-mode", choices=sorted(CHILD_MODES), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.template:
        args.card = args.card or TEMPLATE / "driver.toml"
        args.fixtures = args.fixtures or TEMPLATE / "fixtures"
    if args.card is None:
        parser.error("--card is required (or --template)")
    if not args.card.is_file():
        print(f"{args.card}: no such card", file=sys.stderr)  # noqa: T201
        return EXIT_USAGE

    if args.child_mode:
        handler = CHILD_MODES[args.child_mode]
        return handler(args.card, args.fixtures)  # type: ignore[arg-type]

    if args.bench:
        print(  # noqa: T201
            "--bench needs a registered corpus fetched by `ow eval fetch`, which is "
            "13-quality.md section 13.3's `ow eval` group and lands at P10. Refusing rather than "
            "writing an empty [quality] block: 13:1749 makes the SHAPE of the number "
            "non-optional, and a block of zeroes is a measurement claim nobody made.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    return _run(args)


def _run(args: argparse.Namespace) -> int:
    quiet = bool(args.json)
    fixtures = args.fixtures
    if fixtures is not None and not fixtures.is_dir():
        print(f"{fixtures}: no such directory", file=sys.stderr)  # noqa: T201
        return EXIT_USAGE

    if not quiet:
        found = len(load_fixtures(fixtures)) if fixtures else 0
        print(f"card      {args.card}")  # noqa: T201
        print(f"fixtures  {fixtures or '(none)'}  ({found} files)")  # noqa: T201
        print("spawning the children a library may not spawn ...")  # noqa: T201

    measured: dict[str, object] = {}
    notes: list[str] = []
    if fixtures is not None:
        digests, note = _cross_process(args.card, fixtures, quiet=quiet)
        if digests:
            measured[idempotence_suite.CROSS_PROCESS_KEY] = digests
            measured[determinism_suite.CROSS_PROCESS_KEY] = digests
        notes.append(f"cross-process: {note}")

        survived, note = _segfault_survived(args.card, fixtures)
        notes.append(f"segfault: {note}")
        measured[fuzz_suite.SEGFAULT_KEY] = survived

    verdict, note = _purity_in_a_clean_process(args.card, fixtures)
    measured[purity_suite.CLEAN_PROCESS_KEY] = {"verdict": verdict, "summary": note}
    notes.append(f"purity in a clean interpreter: {verdict} -- {note}")

    with tempfile.TemporaryDirectory() as workdir:
        subject = Subject.of(
            args.card, fixtures_dir=fixtures, workdir=Path(workdir), measurements=measured
        )
        report = run(subject)

        if args.badge:
            print(badge(report))  # noqa: T201
            return EXIT_OK if report.passed else EXIT_FAIL

        if args.json:
            print(json.dumps(_as_json(report, notes), indent=2))  # noqa: T201
            return EXIT_OK if report.passed else EXIT_FAIL

        print()  # noqa: T201
        for line in notes:
            print(f"  {line}")  # noqa: T201
        print()  # noqa: T201
        for line in report_lines(report):
            print(line)  # noqa: T201
        print()  # noqa: T201
        print(badge(report))  # noqa: T201
        claim = sentence(report)
        if claim:
            print(f'and the sentence: "{claim}"')  # noqa: T201
        if mandatory_budget_exceeded(report):
            print("the mandatory tier is over its five-minute laptop budget")  # noqa: T201

        if args.write and not _write_card(args.card, report):
            return EXIT_FAIL

    return EXIT_OK if report.passed else EXIT_FAIL


def _write_card(card: Path, report: object) -> bool:
    """`--write`, refusing first if the author filled in a region only the kit may write (DR13)."""
    findings = publish_check(card.read_bytes())
    if findings:
        print()  # noqa: T201
        print("--write refused: the author wrote a kit-written region (DR13)")  # noqa: T201
        for finding in findings:
            print(f"  {finding}")  # noqa: T201
        return False
    write_results(card, report)  # type: ignore[arg-type]
    print()  # noqa: T201
    print(f"wrote [quality] and attestation into {card}")  # noqa: T201
    return True


def _as_json(report: object, notes: list[str]) -> dict[str, object]:
    rep = report  # type: ignore[assignment]
    return {
        "driver_id": rep.driver_id,  # type: ignore[attr-defined]
        "kit_version": rep.kit_version,  # type: ignore[attr-defined]
        "card_sha256": rep.card_sha256,  # type: ignore[attr-defined]
        "passed": rep.passed,  # type: ignore[attr-defined]
        "mandatory": f"{rep.mandatory_passed}/{rep.mandatory_total}",  # type: ignore[attr-defined]
        "children": notes,
        "suites": [
            {
                "suite": result.suite,
                "verdict": result.verdict.value,
                "mandatory": result.suite in MANDATORY,
                "summary": result.summary,
                "elapsed_ms": round(result.elapsed_ms, 2),
                "failures": [a.line() for a in result.failures()],
            }
            for result in rep.results  # type: ignore[attr-defined]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
