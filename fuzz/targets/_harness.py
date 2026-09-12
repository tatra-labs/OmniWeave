"""The shared half of every target in this directory: a corpus, a property, and two ways to run.

`fuzz/targets/*.py` are atheris targets (11-repo-layout.md:390, 14-security.md:477) and they have
to work on a machine where atheris cannot be installed at all. The root `pyproject.toml` marks it
`atheris; sys_platform == 'linux'`, with 11-repo-layout.md:1480's reason -- it "requires clang and
publishes no Windows wheel" -- and six of the nine `test` cells are macOS or Windows. So each
target has two entry points over one property:

* **`--replay`**, which reads the committed seeds, applies `omniweave_conform.mutate`'s six, and
  asserts the property over every one. Pure Python, no fuzzer, every platform. This is the half
  16-roadmap.md:520 runs -- `uv run pytest tests/host tests/drivers fuzz/ -q` -- and it is a
  regression test over a fixed corpus rather than a search.
* **the default**, `atheris.Setup(...).Fuzz()`, which is a search and is 14-security.md:477's
  nightly job. On a machine with no atheris it exits 4 and says which of the two halves ran.

A target that only worked under atheris would be written blind on three of the nine cells and
would never have run at all before it landed. A target that only replayed would be a corpus with
no fuzzer attached. Both, over one `probe()`, is the only shape where neither is true.

## The property, and what "allowed" means

`04-driver-system.md:2082`: **a crash is allowed, a hang is not.** `03-document-model.md:3012`
(P28) gives the same rule at the row grain: "a corrupt fixture yields `status='partial'` with
`Diag` rows, or a typed `DriverError` from the closed `FailureClass`; a crash is allowed (one
unit), a hang is not."

So a `Target` declares `allowed` -- the exception types that are the code *working* -- and
everything else is a `Finding`. That inversion is the point. A fuzz target that asserted "nothing
raises" would fail on the first refusal a driver is specified to make, and a target that caught
`Exception` would pass on a `RecursionError` escaping a protocol decoder, which is precisely what
`omniweave_core.host.wire`'s own docstring says the fuzz property forbids.

## The three outcomes a replay can report, and why a crash is not one of them

`clean` (the property held), `finding` (something outside `allowed` escaped) and `slow` (the input
took longer than the budget). A **crash** cannot be reported from here, because a process that
segfaults does not reach its own reporting code -- 04-driver-system.md:2089's asymmetry is exactly
that the host survives a crash and the crashing thing does not. That half belongs to the parent:
`--journal` writes the input's name *before* each call and flushes, so a parent that finds a dead
child can name the input that killed it. `fuzz/test_targets.py` is that parent, and it treats a
crash as allowed-and-named and a hang as a failure.

The same split is already made one layer up, and for the same reason:
`omniweave_conform.suites.fuzz` measures a hang budget in-process and defers the *stopping* to
`tools/ow_conform.py`, "where a child process and `host/subproc.py`'s deadline ladder are both
available".

## Exit codes

`0` clean. `1` findings. `2` usage. `3` an input exceeded the budget. `4` the target could not
run -- no atheris for the fuzzing half, or an absent driver for a driver target. Four is never
silent: it prints what was missing and what would install it.

Specified in 11-repo-layout.md:390, 14-security.md:477-481, 04-driver-system.md:2082-2094,
03-document-model.md:3012 and 16-roadmap.md:520.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

REPO: Final = Path(__file__).resolve().parent.parent.parent
SEEDS: Final = REPO / "fuzz" / "seeds"

# The workspace packages, for a bare `python fuzz/targets/wire.py` outside `uv run`. Under
# `uv run` they are already installed and this is a no-op; `tools/ow_eval.py` does the same at
# the top of the file for the same reason.
for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.append(str(_src))

from omniweave_conform.mutate import mutations  # noqa: E402 -- after the sys.path block above

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "EXIT_FINDING",
    "EXIT_HANG",
    "EXIT_OK",
    "EXIT_UNAVAILABLE",
    "EXIT_USAGE",
    "Finding",
    "Input",
    "Report",
    "Target",
    "UnavailableError",
    "corpus",
    "emit",
    "main",
    "replay",
]

EXIT_OK: Final = 0
EXIT_FINDING: Final = 1
EXIT_USAGE: Final = 2
EXIT_HANG: Final = 3
EXIT_UNAVAILABLE: Final = 4

BUDGET_S: Final = 5.0
"""Per-input wall clock beyond which an input is reported as slow.

The same five seconds `omniweave_conform.suites.fuzz.HANG_BUDGET_S` uses, and deliberately the
same number rather than a second opinion: a driver that is a hang here and not there would mean
the framework holds two views of how long is too long. Five seconds against inputs the drivers
parse in single-digit milliseconds is not a performance budget -- it is stuck, and the usual cause
is a length field read from the input and trusted."""

SKIP_NAMES: Final = frozenset({"MIRROR.toml"})
"""Corpus bookkeeping this directory adds on top of `harness.NOT_INPUTS`.

`MIRROR.toml` is `fuzz/seeds/`'s own provenance record, written by `tools/mirror_fuzz_seeds.py`.
It is named here rather than added to `NOT_INPUTS` because that set is the *fixture* corpus's
bookkeeping and this is the *seed* corpus's; a kit that skipped a driver author's `MIRROR.toml`
would be skipping a file it has no business knowing about."""


class UnavailableError(Exception):
    """The target cannot run here, and that is a fact about the machine, not a finding.

    Carries the sentence a reader needs: what was missing and what installs it. `main()` prints it
    and exits 4, which `fuzz/test_targets.py` distinguishes from every other non-zero exit.
    """


class FindingError(Exception):
    """Raised into libFuzzer so it records the input. Never raised under `--replay`."""


@dataclass(frozen=True, slots=True)
class Input:
    """One thing to feed the property: a seed, or one mutation of one."""

    corpus: str
    seed: str
    mutation: str
    data: bytes

    @property
    def label(self) -> str:
        return f"{self.corpus}/{self.seed}:{self.mutation}"


@dataclass(frozen=True, slots=True)
class Finding:
    """An escape outside `Target.allowed`. The thing a target exists to produce."""

    label: str
    kind: str
    detail: str

    def line(self) -> str:
        return f"{self.label}  {self.kind}: {self.detail}"[:160]


@dataclass(frozen=True, slots=True)
class Report:
    """What a replay saw. `execs` is the denominator every other number is read against."""

    target: str
    execs: int = 0
    clean: int = 0
    refused: int = 0
    findings: tuple[Finding, ...] = ()
    slow: tuple[str, ...] = ()
    corpora: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        if self.findings:
            return EXIT_FINDING
        if self.slow:
            return EXIT_HANG
        return EXIT_OK

    def lines(self) -> list[str]:
        where = ", ".join(self.corpora) or "<no corpus>"
        out = [
            f"{self.target}: {self.execs} execs over {where}",
            f"  {self.clean} clean, {self.refused} refused as specified, "
            f"{len(self.findings)} finding(s), {len(self.slow)} over {BUDGET_S}s",
        ]
        out.extend(f"  FINDING  {finding.line()}" for finding in self.findings[:10])
        out.extend(f"  SLOW     {label}" for label in self.slow[:10])
        return out


@dataclass(frozen=True, slots=True)
class Target:
    """One target: what it reads, what it does to a byte string, and what may escape."""

    name: str
    probe: Callable[[bytes], None]
    allowed: tuple[type[BaseException], ...]
    corpora: tuple[tuple[str, Path], ...] = ()
    """`(label, directory)` pairs. The label is what a finding is reported under, and it is given
    rather than derived from the directory name because two of them are called `fixtures`: a
    driver target reads its own distribution's corpus as well as the mirrored seeds, and
    `fixtures/rich.docx:bitflip` does not say which distribution. Empty is legal and reports as a
    vacuous replay rather than as a pass."""
    setup: Callable[[], None] | None = None
    """Run once before anything is read. Raises `UnavailableError` when this machine cannot
    host the target -- an absent driver, an absent binding -- which is exit 4 and not a finding."""
    write_seeds: Callable[[Path], list[Path]] | None = None
    """Writes this target's own starting corpus, for a target whose format this repository owns.
    `None` for a target seeded from `vendor/anydoc`, whose corpus is mirrored and not authored."""
    extras: tuple[Input, ...] = field(default_factory=tuple)
    """Inputs that are not files: the degenerate cases a corpus cannot hold. Replayed unmutated."""


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def corpus(directories: tuple[tuple[str, Path], ...]) -> Iterator[Input]:
    """Every seed, then every mutation of it. Sorted, so two runs feed inputs in one order.

    The mutations come from `omniweave_conform.mutate`, which is also what the `fuzz` conformance
    suite runs over a driver author's own fixtures. One definition of "malformed" for both, which
    is the whole reason that module was extracted (INV-21).
    """
    from omniweave_conform.harness import NOT_INPUTS  # noqa: PLC0415 -- after the sys.path block

    for label, directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.name.endswith(".meta.toml")
                or path.name in NOT_INPUTS
                or path.name in SKIP_NAMES
            ):
                continue
            data = path.read_bytes()
            name = path.relative_to(directory).as_posix()
            yield Input(label, name, "seed", data)
            for mutation, mutated in mutations(data):
                yield Input(label, name, mutation, mutated)


def replay(target: Target, *, budget_s: float = BUDGET_S, journal: Path | None = None) -> Report:
    """Run the property over the corpus and report. Never raises on a finding -- it records one."""
    findings: list[Finding] = []
    slow: list[str] = []
    execs = clean = refused = 0
    handle = journal.open("w", encoding="utf-8", newline="\n") if journal is not None else None
    try:
        for item in (*corpus(target.corpora), *target.extras):
            if handle is not None:
                # Written and FLUSHED before the call, never after: the whole point is to be
                # readable by a parent whose child did not come back from this line.
                handle.seek(0)
                handle.truncate()
                handle.write(item.label + "\n")
                handle.flush()
            execs += 1
            at = time.monotonic_ns()
            try:
                target.probe(item.data)
                clean += 1
            except target.allowed:
                refused += 1
            # Ctrl-C and a deliberate exit are the operator, not the property. Without this
            # clause a replay would record an interrupt as a finding and carry on to the next
            # input, which is a corpus that cannot be stopped.
            except (KeyboardInterrupt, SystemExit):
                raise
            # A bare `BaseException` otherwise, on purpose: classifying an escape IS the
            # property, and the narrow set that is not one lives in `Target.allowed` above.
            except BaseException as exc:
                findings.append(Finding(item.label, type(exc).__name__, str(exc)))
            if (time.monotonic_ns() - at) / 1e9 > budget_s:
                slow.append(item.label)
    finally:
        if handle is not None:
            handle.close()
    return Report(
        target=target.name,
        execs=execs,
        clean=clean,
        refused=refused,
        findings=tuple(findings),
        slow=tuple(slow),
        corpora=tuple(label for label, _ in target.corpora),
    )


def _fuzz(target: Target) -> int:
    """The atheris half. 14-security.md:477's nightly job; exits 4 where atheris cannot install."""
    try:
        import atheris  # noqa: PLC0415 -- Linux-only by pyproject marker; absence is exit 4
    except ImportError as exc:
        emit(
            f"{target.name}: atheris is not importable here ({exc}). The root pyproject.toml pins "
            f"it `sys_platform == 'linux'` because it needs clang and publishes no Windows wheel "
            f"(11-repo-layout.md:1480), so this half runs in the nightly Linux job only. The "
            f"replay half runs everywhere: --replay."
        )
        return EXIT_UNAVAILABLE

    def one_input(data: bytes) -> None:
        try:
            target.probe(data)
        except target.allowed:
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # re-raised as a finding, so libFuzzer records the input
            raise FindingError(f"{type(exc).__name__}: {exc}") from exc

    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
    return EXIT_OK  # unreachable: Fuzz() does not return.


def main(target: Target, argv: list[str] | None = None) -> int:
    """`--replay` | `--write-seeds` | fuzz. See the module docstring for the exit codes."""
    parser = argparse.ArgumentParser(
        description=f"fuzz target {target.name}", allow_abbrev=False, add_help=False
    )
    parser.add_argument("--replay", action="store_true", help="run the committed corpus and exit")
    parser.add_argument("--write-seeds", action="store_true", help="write this target's own seeds")
    parser.add_argument("--journal", type=Path, default=None, help="last-input file for a parent")
    parser.add_argument("--help", "-h", action="help", help="show this message")
    args, rest = parser.parse_known_args(argv)
    if rest and (args.replay or args.write_seeds):
        emit(f"{target.name}: unrecognised argument(s) {' '.join(rest)}")
        return EXIT_USAGE

    if args.write_seeds:
        if target.write_seeds is None:
            emit(
                f"{target.name}: this target's corpus is mirrored from vendor/anydoc, not "
                f"authored. `uv run tools/mirror_fuzz_seeds.py` is the writer."
            )
            return EXIT_USAGE
        written = target.write_seeds(SEEDS / target.name)
        emit(f"{target.name}: wrote {len(written)} seed(s)")
        return EXIT_OK

    if target.setup is not None:
        try:
            target.setup()
        except UnavailableError as exc:
            emit(f"{target.name}: {exc}")
            return EXIT_UNAVAILABLE

    if not args.replay:
        return _fuzz(target)

    report = replay(target, journal=args.journal)
    for line in report.lines():
        emit(line)
    return report.exit_code


def declared(module: Any) -> Target:
    """The `TARGET` a target module exposes, checked. Used by `fuzz/test_targets.py`."""
    found = getattr(module, "TARGET", None)
    if not isinstance(found, Target):
        raise TypeError(f"{module.__name__} exposes no TARGET")
    return found
