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

D953 adds four rows that read only this machine and the configuration: D-01, D-05, D-11 and
D-15, in `omniweave.doctor.local`. D956 adds three that read what the project declares: D-06,
D-13 and D-17, in `omniweave.doctor.project`, and D957 D-16 beside them. D958 adds D-10, the
one row only `--runtime` runs (`local.RUNTIME`); a run without the flag names it as not run.
D959 adds D-24, a live `store.write` lock, in `omniweave.doctor.store`, and D969 D-23,
pages an abandoned parse left above their document's committed generation.
D961 adds D-25, the redaction canary over the newest event shard, in `local`, and D963
D-26, whether an OTLP endpoint is set and how many runs recorded it. D965 adds D-19,
`omniweave-vision`'s resolved installed size, the second row only `--runtime` runs.

**The rows of 15:1514-1540 not built are named, not skipped silently.** Every run prints the
ids it did not check, because a doctor that exits 0 is read as *"this deployment is fine"*,
and here it can only mean that the rows in `BUILT` are. `UNBUILT` is that list, and it
shrinks as rows land.

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

from omniweave.doctor import gitindex, local, project, store
from omniweave.sdk.reports import DoctorFinding, DoctorReport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
    "class_memory_mb",
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

BUILT: Final[tuple[str, ...]] = tuple(
    sorted(("D-02", "D-08", *local.LOCAL, *local.RUNTIME, *project.PROJECT, *store.STORE))
)
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

REQUIRE_LOCK: Final = "OMNIWEAVE_DRIVERS_REQUIRE_LOCK"
INPROC: Final = "OMNIWEAVE_DRIVERS_INPROC"
"""`drivers.require_lock` and `drivers.inproc`'s declared twins: the fixes D954's two trust
findings print, beside the `omniweave.toml` lines that do the same."""

PARSE_PORT: Final = "parse"
"""The one Port `resolve()` is asked for (`run.routing.PORT`, `parse/1`)."""


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
    require_lock: bool = False,
    inproc: Sequence[str] = (),
) -> tuple[DoctorFinding, ...]:
    """The catalog rebuild, and D-08 over it (15:1521).

    D-08 reads: *"every enabled driver's card validates; `attested = true` unless
    `allow_unattested`"*. A card in the catalog has validated, because `load_card()` is the only
    constructor of `DriverCard`. So the row's question is attestation, asked of every enabled id
    that has a card.

    **D954: and the two trust gates `resolve()` applies after it.** A doctor that passed D-08 while
    `resolve()` routed nothing was the failure a fresh source checkout showed: every first-party
    distribution computes as `unpinned` there, because the release manifest is written at build
    time, and `[drivers] require_lock = true` (the shipped default) refuses an unpinned driver as
    `NOT_IN_LOCKFILE`. `ow add` left a text file `no_driver`, and `ow doctor` passed the very parse
    drivers it refused. So, for every enabled card `resolve()` routes (a `parse` card; the derive
    passes are pinned by their operators and never resolved):
    - `require_lock` with a trust tier outside `resolve.LOCK_SATISFIED` fails, as `_gate_lockfile`
      refuses it, with `require_lock = false` as the fix;
    - an id in `[drivers] inproc` with a trust tier outside `resolve.INPROC_TRUST` fails, as
      `_gate_isolation` refuses it, with `inproc = []` as the fix.
    The attestation finding no longer says `resolve()` refuses a card it never routes.

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
    from omniweave_core.drivers.resolve import (  # noqa: PLC0415
        INPROC_TRUST,
        LOCK_SATISFIED,
        MANIFEST_PINNED,
    )

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
    #  D894: the release manifest is the pin that waives attestation for a first-party card
    #  (D576, a user ruling of 2026-10-20), as `resolve()`'s gate waives it.
    pinned = sorted(
        one
        for one in carded
        if not built.cards[one].attested and built.trust.get(one) in MANIFEST_PINNED
    )
    unattested = [one for one in carded if not built.cards[one].attested and one not in pinned]
    failures: list[DoctorFinding] = []
    if not allow_unattested:
        failures.extend(
            DoctorFinding(
                check="D-08",
                detail=(
                    f"{one} is in [drivers] enabled and its card carries no attestation, and no "
                    "release manifest pins it (D576)"
                    + (", so resolve() refuses it as unattested" if _routed(built, one) else "")
                ),
                severity="error",
                fix=f"{ALLOW_UNATTESTED}=true   # or allow_unattested = true under [drivers]",
            )
            for one in unattested
        )
    routed = [one for one in carded if _routed(built, one)]
    failures.extend(
        DoctorFinding(
            check="D-08",
            detail=(
                f"{one} computes as {_tier(built, one)!r}: no release manifest pins it, which a "
                "source checkout never has, and [drivers] require_lock = true refuses an unpinned "
                "driver, so resolve() routes nothing to it (NOT_IN_LOCKFILE)"
            ),
            severity="error",
            fix=f"{REQUIRE_LOCK}=false   # or require_lock = false under [drivers]",
        )
        for one in routed
        if require_lock and built.trust.get(one) not in LOCK_SATISFIED
    )
    failures.extend(
        DoctorFinding(
            check="D-08",
            detail=(
                f"[drivers] inproc names {one}, which computes as {_tier(built, one)!r} and not "
                "first_party or vendored, so resolve() refuses it (TRUST_INSUFFICIENT)"
            ),
            severity="error",
            fix=f"{INPROC}=[]   # or inproc = [] under [drivers]",
        )
        for one in routed
        if one in inproc and built.trust.get(one) not in INPROC_TRUST
    )
    if failures:
        findings.extend(failures)
        return tuple(findings)
    waived = f"; attestation waived for {', '.join(unattested)}" if unattested else ""
    if pinned:
        waived += f"; the release manifest pins {', '.join(pinned)}"
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


def class_memory_mb(
    *, env: Mapping[str, str], project_root: Path | None, enabled: Sequence[str]
) -> dict[str, int]:
    """D-10's `memory_mb`: per cost class, the heaviest enabled card's `[isolation] memory_mb`.

    08:707's `max(card.isolation.memory_mb for card in catalog.enabled_in(c))`: a worker runs one
    driver at a time, so a class's worst case is its heaviest member. A card with no `[cost.model]`
    is `free`, as `resolve()` reads it. An enabled id with no card weighs nothing here, as it
    routes nothing (D-08).
    """
    from omniweave_core.discovery import catalog  # noqa: PLC0415 -- only --runtime pays

    cards = catalog(env=env, project_root=project_root).cards
    heaviest: dict[str, int] = {}
    for one in enabled:
        card = cards.get(one)
        if card is None:
            continue
        model = getattr(card, "cost_model", None)
        cost = str(getattr(model, "cost_class", "free")) if model is not None else "free"
        weight = int(getattr(getattr(card, "isolation", None), "memory_mb", 0))
        heaviest[cost] = max(heaviest.get(cost, 0), weight)
    return heaviest


def _routed(built: object, driver_id: str) -> bool:
    """Whether `resolve()` routes this card: a `parse` card. A derive pass is pinned and is not."""
    card = built.cards[driver_id]  # type: ignore[attr-defined]
    identity = getattr(card, "identity", None)
    port = getattr(identity, "port", None)
    return getattr(port, "value", port) == PARSE_PORT


def _tier(built: object, driver_id: str) -> str:
    """The computed trust tier's name, or `unpinned` when the catalog computed none."""
    tier = built.trust.get(driver_id)  # type: ignore[attr-defined]
    return str(getattr(tier, "value", tier or "unpinned"))


def run(
    *, cwd: Path, env: Mapping[str, str], runtime: bool = False, explicit: Path | None = None
) -> DoctorReport:
    """The Action: load the configuration, run every built check, sort the findings three ways.

    `runtime` runs D-10 (D958) over the catalog D-08 rebuilt, and D-19 (D965).
    `explicit` is `--config`, 18:891's *"highest-precedence config source; skips the upward
    walk"*. Before W7.8x the verb dropped it and checked the configuration the walk found (D631).
    """
    from omniweave_core import config  # noqa: PLC0415 -- only the doctor verb pays for the loader
    from omniweave_core.errors import OwError  # noqa: PLC0415

    findings: list[DoctorFinding] = []
    sources: dict[str, str] = {}
    config_digest = semantic_digest = ""
    try:
        resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    except OwError as exc:
        #  A configuration that does not resolve is 15:1509's exit-1 class. The two digests stay
        #  empty rather than naming a configuration that never existed.
        findings.append(DoctorFinding("config", str(exc), "error", exc.fix))
        #  The rows that read the configuration cannot run, and say so rather than going quiet.
        findings.extend(
            DoctorFinding(row, "not run: the configuration did not resolve", "warning", exc.fix)
            for row in (
                "D-05",
                "D-06",
                "D-08",
                *(("D-10",) if runtime else ()),  # D-19 reads no configuration, and runs
                "D-11",
                "D-13",
                "D-15",
                "D-23",
                "D-24",
                "D-25",
                "D-26",
            )
        )
    else:
        sources = {key: source.render() for key, source in sorted(resolved.sources.items())}
        config_digest, semantic_digest = resolved.config_digest, resolved.semantic_digest
        enabled = resolved.get("drivers.enabled")
        inproc = resolved.get("drivers.inproc")
        findings.extend(
            check_driver_cards(
                env=env,
                project_root=config.project_root(resolved),
                enabled=[str(one) for one in enabled] if isinstance(enabled, tuple) else [],
                allow_unattested=resolved.get("drivers.allow_unattested") is True,
                require_lock=resolved.get("drivers.require_lock") is True,
                inproc=[str(one) for one in inproc] if isinstance(inproc, tuple) else [],
            )
        )
        if runtime:
            findings.append(
                local.check_ram(
                    resolved,
                    memory_mb=class_memory_mb(
                        env=env,
                        project_root=config.project_root(resolved),
                        enabled=[str(one) for one in enabled] if isinstance(enabled, tuple) else [],
                    ),
                    cwd=cwd,
                )
            )
        findings.extend(local.check_corpora(resolved, cwd=cwd))
        findings.extend(local.check_free_space(resolved, cwd=cwd))
        findings.append(local.check_events_dir(resolved, env=env))
        findings.append(local.check_canary(resolved, env=env, cwd=cwd))
        findings.append(local.check_otlp(resolved, cwd=cwd))
        findings.extend(
            project.check_named_drivers(resolved, project_root=config.project_root(resolved))
        )
        findings.extend(project.check_pricebooks(resolved, cwd=cwd, today=_today()))
        findings.extend(store.check_abandoned(resolved, cwd=cwd))
        findings.extend(store.check_write_locks(resolved, cwd=cwd, now_ns=_wall_ns()))
    if runtime:
        #  D965: D-19 reads installed metadata and no configuration.
        findings.append(local.check_vision_size())
    findings.append(project.check_hooks(env, cwd=cwd))
    findings.append(project.check_skills(env, cwd=cwd))
    findings.append(local.check_sqlite())
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
    checked = {one.check for one in (*report.ok, *report.warned, *report.failed)}
    waiting = [row for row in local.RUNTIME if row not in checked]
    if waiting:
        verb = "runs" if len(waiting) == 1 else "run"
        lines.append(f"doctor: {' and '.join(waiting)} {verb} only with --runtime")
    verdict = "fails" if report.failed else "passes"
    lines.append(f"doctor: {verdict} the {len(BUILT) - len(waiting)} check(s) it ran")
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


def _quoted(path: str) -> str:
    """A path as one shell word. Git's own `ls-files` quoting is not reproduced; spaces are."""
    return f'"{path}"' if any(ch in path for ch in " \t'") else path


def _today() -> str:
    """D-13's date: today, UTC, read once from `SystemClock` as the other surfaces read the wall."""
    import datetime as dt  # noqa: PLC0415

    seconds = _wall_ns() // 1_000_000_000
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).date().isoformat()


def _wall_ns() -> int:
    """The wall clock D-13's date and D-24's lock ages are read against: `SystemClock`'s."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415

    return SystemClock().wall_ns()
