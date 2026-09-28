"""`ow doctor`: the environment report, and the checks this build can run. 15 section 9.2.

The `doctor` ActionSpec, `DoctorIn` and `DoctorReport` have existed since W7.1. What was missing was
a runner, and `python -m omniweave doctor` was refused as a root *"not dispatched by this build"*.
V01-16 (00:717) is the first criterion that needs it: *"`ow doctor` on a store tracked in git
**fails** with `OW-S-060`"*. So this module runs D-02, and the configuration load every row reads
through.

W7.8e adds the catalog rebuild and D-08. 15:1499 makes `ow doctor` *"the only command that rebuilds
the catalog"*, and V01-4 (00:705) makes that rebuild the thing a hostile wheel must not be able to
take down: *"`ow doctor` exits 0 and the file is absent"*. So the rebuild is `discover()` and
`catalog()` with this run's environment and project, and G11 now runs this verb as a process over
its rogue fixture (D612).

**The other twenty-five rows of 15:1514-1540 are named, not skipped silently.** Every run prints
the ids it did not check, because a doctor that exits 0 is read as *"this deployment is fine"*,
and here it can only mean that D-02 and D-08 are. `UNBUILT` is that list, and it shrinks as rows
land.

Exit 0 or 1, 18:222's rule: 1 exactly when `DoctorReport.failed` is non-empty. A warning never
fails the run (10:1785). 15:1509's exit 6, 7 and 9 belong to D-20, D-24 and an unconfigured
install, none of which this build checks.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave.doctor import gitindex
from omniweave.sdk.reports import DoctorFinding, DoctorReport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core import config

__all__ = [
    "BUILT",
    "DOCTOR_WORD",
    "FAILED",
    "OK",
    "STORE_GLOB",
    "STORE_TRACKED",
    "STORE_TRACKED_SYMBOL",
    "UNBUILT",
    "check_driver_cards",
    "check_tracked_store",
    "main",
    "run",
]

DOCTOR_WORD: Final[str] = "doctor"

OK: Final[int] = 0
FAILED: Final[int] = 1
"""18:222: `ow doctor` exits 1 iff `DoctorReport.failed` is non-empty."""

_ARGPARSE_USAGE: Final[int] = 2

STORE_TRACKED: Final = "OW-S-060"
STORE_TRACKED_SYMBOL: Final = "OW_STORE_TRACKED_IN_GIT"
"""`codes.toml`'s row, which `test_doctor.py` holds these two spellings to."""

STORE_GLOB: Final = "*.owstore*"
"""The shipped `.gitignore`'s own pattern, which covers the store, its two sidecars
(`index.vec.owstore`, `events.owstore`) and SQLite's `-wal` and `-shm` files. It is matched
against the final path component, as a `.gitignore` line with no slash is."""

BUILT: Final[tuple[str, ...]] = ("D-02", "D-08")
UNBUILT: Final[tuple[str, ...]] = tuple(
    f"D-{n:02d}" for n in range(1, 28) if f"D-{n:02d}" not in BUILT
)
"""15:1514-1540's rows that no code checks yet. `BUILT` and `UNBUILT` together are D-01 to D-27."""

_BY_HAND: Final = "git ls-files -- '*.owstore*'"

ALLOW_UNATTESTED: Final = "OMNIWEAVE_DRIVERS_ALLOW_UNATTESTED"
"""`drivers.allow_unattested`'s declared twin: D576's opt-in, and the one command that clears an
unattested card today. 15:1521's fix cell names `ow drivers verify`, which checks digests and
attests nothing (`tools/ow_drivers.py`), and `ow conform`, which writes attestations, is not
built."""


def check_tracked_store(cwd: Path) -> DoctorFinding:
    """D-02: *"no `.owstore` is tracked in git"* (15:1515), for the work tree containing `cwd`."""
    read = gitindex.read_tracked(cwd)
    if read.repo_root is None:
        return DoctorFinding(
            check="D-02",
            detail=f"{cwd} is inside no git work tree, so no .owstore can be tracked from here",
            severity="ok",
            fix="",
        )
    tracked = tuple(
        path for path in read.paths if fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], STORE_GLOB)
    )
    if tracked:
        #  Named before anything unreadable: a store seen in the index is tracked, whatever else
        #  the rest of the index would have said.
        return DoctorFinding(
            check="D-02",
            detail=(
                f"{STORE_TRACKED} {STORE_TRACKED_SYMBOL}: {len(tracked)} store file(s) tracked in "
                f"git at {read.repo_root}: {', '.join(tracked)}. A tracked store is a corpus "
                "committed to git (11:89)"
            ),
            severity="error",
            fix="git rm --cached -- " + " ".join(_quoted(path) for path in tracked),
        )
    if read.unreadable:
        return DoctorFinding(
            check="D-02",
            detail=f"the git index at {read.repo_root} was not read completely: {read.unreadable}",
            severity="warning",
            fix=_BY_HAND,
        )
    return DoctorFinding(
        check="D-02",
        detail=f"no .owstore is tracked in the git index at {read.repo_root}",
        severity="ok",
        fix="",
    )


def check_driver_cards(
    *,
    env: Mapping[str, str],
    project_root: Path | None,
    enabled: Sequence[str],
    allow_unattested: bool,
) -> tuple[DoctorFinding, ...]:
    """The catalog rebuild, and D-08 over it (15:1521).

    D-08 reads: *"every enabled driver's card validates; `attested = true` unless
    `allow_unattested`"*. A card in the catalog has validated, because `load_card()` is the only
    constructor of `DriverCard`. So the row's question is attestation, asked of every enabled id
    that has a card.

    **An enabled id with no card is not a D-08 failure.** 00:116 names `parse.page.olmocr` in
    `[drivers] enabled` *"so the escalation rule can fire even where the distribution is absent"*,
    and `resolve()` reports that as unavailable. The ids are printed, and they fail nothing.

    **A discovery fault is a warning, with the fault's own `fix`.** `DiscoveryFault` carries the
    code and the fix *"so `ow drivers check` and `ow doctor` print the same code"* (discovery.py).
    A fault names a source, not always a driver id, so it cannot always be tied to an enabled
    driver, and D-08 fails only what it can show.

    Two passes: `discover()` for the faults, which `catalog()` does not keep, then `catalog()`.
    G11 reads the same pair the same way. Neither pass imports a card's entrypoint (INV-4).
    """
    from omniweave_core.discovery import catalog, discover  # noqa: PLC0415 -- the verb pays

    faults = discover(env=env, project_root=project_root).faults
    built = catalog(env=env, project_root=project_root)
    findings = [
        DoctorFinding(
            check="catalog",
            detail=f"{fault.symbol}: {fault.detail} ({fault.source})",
            severity="warning",
            fix=fault.fix or "python tools/ow_drivers.py list",
        )
        for fault in faults
    ]
    findings.append(
        DoctorFinding(
            check="catalog",
            detail=f"rebuilt: {len(built.cards)} card(s): {', '.join(sorted(built.cards))}",
            severity="ok",
            fix="",
        )
    )
    carded = sorted(one for one in enabled if one in built.cards)
    absent = sorted(one for one in enabled if one not in built.cards)
    unattested = [one for one in carded if not built.cards[one].attested]
    if unattested and not allow_unattested:
        findings.extend(
            DoctorFinding(
                check="D-08",
                detail=(
                    f"{one} is in [drivers] enabled and its card carries no attestation, so "
                    "resolve() refuses it as unattested (D576)"
                ),
                severity="error",
                fix=f"{ALLOW_UNATTESTED}=true   # or allow_unattested = true under [drivers]",
            )
            for one in unattested
        )
        return tuple(findings)
    waived = f"; attestation waived for {', '.join(unattested)}" if unattested else ""
    missing = (
        f"; {len(absent)} enabled id(s) have no installed card and resolve as unavailable: "
        f"{', '.join(absent)}"
        if absent
        else ""
    )
    findings.append(
        DoctorFinding(
            check="D-08",
            detail=f"{len(carded)} enabled driver(s) have a valid card{waived}{missing}",
            severity="ok",
            fix="",
        )
    )
    return tuple(findings)


def run(
    *, cwd: Path, env: Mapping[str, str], runtime: bool = False, explicit: Path | None = None
) -> DoctorReport:
    """The Action: load the configuration, run every built check, sort the findings three ways.

    `runtime` is accepted and changes nothing yet: D-10, the only `--runtime` row, is in `UNBUILT`.
    `explicit` is `--config`, 18:891's *"highest-precedence config source; skips the upward
    walk"*. Before W7.8x the verb dropped it and checked the configuration the walk found (D631).
    """
    from omniweave_core import config  # noqa: PLC0415 -- only the doctor verb pays for the loader
    from omniweave_core.errors import OwError  # noqa: PLC0415

    del runtime
    findings: list[DoctorFinding] = []
    sources: dict[str, str] = {}
    config_digest = semantic_digest = ""
    try:
        resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    except OwError as exc:
        #  A configuration that does not resolve is 15:1509's exit-1 class. The two digests stay
        #  empty rather than naming a configuration that never existed.
        findings.append(DoctorFinding("config", str(exc), "error", exc.fix))
        #  D-08 reads `[drivers] enabled`, so it cannot run, and says so rather than going quiet.
        findings.append(
            DoctorFinding("D-08", "not run: the configuration did not resolve", "warning", exc.fix)
        )
    else:
        sources = {key: source.render() for key, source in sorted(resolved.sources.items())}
        config_digest, semantic_digest = resolved.config_digest, resolved.semantic_digest
        enabled = resolved.get("drivers.enabled")
        findings.extend(
            check_driver_cards(
                env=env,
                project_root=_project_root(resolved),
                enabled=[str(one) for one in enabled] if isinstance(enabled, tuple) else [],
                allow_unattested=resolved.get("drivers.allow_unattested") is True,
            )
        )
    findings.append(check_tracked_store(cwd))
    return DoctorReport(
        ok=tuple(one for one in findings if one.severity == "ok"),
        warned=tuple(one for one in findings if one.severity == "warning"),
        failed=tuple(one for one in findings if one.severity == "error"),
        config_sources=sources,
        config_digest=config_digest,
        semantic_digest=semantic_digest,
    )


def render(report: DoctorReport) -> tuple[str, ...]:
    """The lines `ow doctor` prints: every finding, its fix, and what was not checked."""
    lines: list[str] = []
    for label, group in (("FAIL", report.failed), ("warn", report.warned), ("ok", report.ok)):
        for one in group:
            lines.append(f"{label:4} {one.check}: {one.detail}")
            if one.fix:
                lines.append(f"     fix: {one.fix}")
    if report.config_digest:
        lines.append(
            f"ok   config: {len(report.config_sources)} keys resolved, "
            f"config_digest {report.config_digest[:12]}"
        )
    lines.append(
        f"doctor: {len(UNBUILT)} of 27 checks are not built yet and were not run: "
        f"{', '.join(UNBUILT)}"
    )
    verdict = "fails" if report.failed else "passes"
    lines.append(f"doctor: {verdict} the {len(BUILT)} check(s) it ran")
    return tuple(lines)


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow doctor ...` from argv (starting at the root word), through the generated tree.

    `--quiet` prints nothing and speaks only through the exit code (10:1543). A global flag this
    verb does not serve is refused by name before anything is checked (`switches.READS`, D631).
    """
    from omniweave_core.errors import OwError  # noqa: PLC0415

    from omniweave.cli import build_parser  # noqa: PLC0415 -- only a CLI verb pays for the tree
    from omniweave.surface import switches  # noqa: PLC0415

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            parsed: argparse.Namespace = build_parser().parse_args(list(argv))
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else _ARGPARSE_USAGE
    try:
        switches.check(DOCTOR_WORD, parsed)
    except OwError as error:
        return switches.report(error, parsed, stdout=stdout, stderr=stderr)
    explicit = Path(parsed.config) if parsed.config else None
    report = run(
        cwd=cwd, env=env, runtime=bool(getattr(parsed, "runtime", False)), explicit=explicit
    )
    if not parsed.quiet:
        for line in render(report):
            stdout.write(line.encode("ascii", "backslashreplace").decode("ascii") + "\n")
    return FAILED if report.failed else OK


def _project_root(resolved: config.Config) -> Path | None:
    """The directory of the `omniweave.toml` that supplied any value, or None when none did.

    `discover()` resolves `.omniweave/drivers/` against it, and takes None as "no project" --
    it never defaults to the working directory, and neither does this.
    """
    from omniweave_core.config import ConfigLayer  # noqa: PLC0415

    for source in resolved.sources.values():
        if source.layer is ConfigLayer.PROJECT_FILE and source.path is not None:
            return source.path.parent
    return None


def _quoted(path: str) -> str:
    """A path as one shell word. Git's own `ls-files` quoting is not reproduced; spaces are."""
    return f'"{path}"' if any(ch in path for ch in " \t'") else path
