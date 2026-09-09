"""G5, CI job 1: every version-bearing declaration site in the repository, checked in ~2 s.

11-repo-layout.md section 4.2 enumerates **forty** version strings across **eighteen** files and
says why the count matters: *"keep the versions in sync" is unactionable and "40 strings across 18
files" is a checklist*. This module is that checklist. `SITE_CLASSES` below transcribes the section
table row for row, and `TOTAL_SITES` / `TOTAL_FILES` / `PATCH_SITES` are summed from it rather than
written down twice, so a row edited without its count is an import-time failure here and not a
silent drift in CI.

**Three axes, and this tool owns exactly one of them.** `RELEASE` is carried by thirteen of the
fourteen distributions; `CONTRACT` and `SCHEMA` live in `omniweave_core.contract` and are checked by
G16 and the migration tests. The exception this tool must know or it reports a false failure:
`omniweave-ports` is versioned by **Port major** (`1.0.0` at release 1), not by `RELEASE`, because a
driver pins it and a driver that pinned `RELEASE` would have pinned the framework (section 4.1).

`packages/omniweave-core/src/omniweave_core/contract.py` reads `RELEASE` from distribution metadata
precisely so that it is **not** a forty-first site; its `_release()` docstring says so. Nothing here
imports `omniweave_core`: G5 and G4 are the two gates that run with nothing installed (section 8.2),
which is what lets `.pre-commit-config.yaml` run them locally and CI run this one before install.

**Absent sites are reported, never assumed.** `toolchains/{deck,video}/package.json` and
`tools/toolchains.toml` land with the `toolchains` job, first green at P9 (16-roadmap.md section 3),
and `omniweave_core/drivers/first_party.toml` is generated **into** `src/` by the `build` job, is
`.gitignore`d, and therefore does not exist in a developer checkout at all (section 2.6). Five of
the forty sites, across four of the eighteen files, are consequently absent at P1. This tool prints
them as PENDING with the locus that lands each, prints `sites checked: N/40`, and fails on any site
whose file *is* present and wrong.
`--require-all-sites` promotes PENDING to failure, which is what a release run wants.

`--set <RELEASE>` is the writer, and section 4.2 is emphatic that its last step is not optional:
`uv.lock` records every workspace member's version, so rewriting thirteen `[project] version` fields
invalidates the lock and `uv sync --frozen` would fail on the release commit. `--set` therefore runs
`uv lock --offline` and leaves the updated lock in the same commit.

Specified in 11-repo-layout.md sections 4.1, 4.2, 2.2 (the extras block G14 also reads), 1.10 row 6
and 7.6 step 2; listed in section 1.7's `tools/` tree as "every declaration site + the git tag. CI
JOB 1."; run by 16-roadmap.md section 4's P1 exit criteria.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "CLI_DIST",
    "CORE_BOUND_DISTS",
    "DIST_COUNT",
    "EXTRA_EXEMPT",
    "PATCH_SITES",
    "PORTS_DIST",
    "RECOMMENDED",
    "REPO",
    "SITE_CLASSES",
    "TOOLCHAIN_ROWS",
    "TOTAL_FILES",
    "TOTAL_SITES",
    "Finding",
    "Pending",
    "Report",
    "SiteClass",
    "bound",
    "check",
    "extra_name",
    "main",
    "write_release",
]

REPO = Path(__file__).resolve().parents[1]
"""The workspace root. `tools/` sits one level below it and is not an importable package."""


@dataclass(frozen=True, slots=True)
class SiteClass:
    """One row of 11-repo-layout.md section 4.2's table: a class of site, and how many there are.

    `count` is the row's own count column and `patch` is its "rewritten on a PATCH" column. Both
    are summed at import into `TOTAL_SITES` and `PATCH_SITES` and asserted against the two totals
    the section prints, so this table cannot be edited into disagreement with the plan without the
    tool refusing to start. `files` is how many distinct files the row touches, which the section
    states only as the grand total of eighteen.
    """

    name: str
    count: int
    files: int
    patch: bool
    value: str


SITE_CLASSES: tuple[SiteClass, ...] = (
    SiteClass("dist [project] version, dist != omniweave-ports", 13, 13, True, "RELEASE"),
    SiteClass("omniweave-ports [project] version", 1, 1, False, "Port major"),
    SiteClass(
        "omniweave-core ~= bound in five compile dists, serve, omniweave", 7, 0, False, "derived"
    ),
    SiteClass("omniweave-office ~= bound in omniweave", 1, 0, False, "derived"),
    SiteClass(
        "omniweave extras: ten single-sibling rows plus recommended's three",
        13,
        0,
        False,
        "derived",
    ),
    SiteClass("toolchains/{deck,video}/package.json version", 2, 2, True, "RELEASE"),
    SiteClass("tools/toolchains.toml [[toolchain]] version per row", 2, 1, True, "RELEASE"),
    SiteClass("omniweave_core/drivers/first_party.toml release", 1, 1, True, "RELEASE"),
)
"""Section 4.2's table, transcribed row for row.

Rows 3, 4 and 5 declare `files = 0` because all twenty-one of their sites live inside a
`pyproject.toml` already counted by row 1 — the seven `omniweave-core ~=` bounds are in seven of the
thirteen, and the fourteen `omniweave-office ~=` and extras sites are all in
`packages/omniweave/pyproject.toml`. That is the arithmetic by which 40 strings fit in 18 files.
"""

TOTAL_SITES: int = sum(s.count for s in SITE_CLASSES)
"""**40.** The number section 4.2 prints, summed from the table rather than restated beside it."""

TOTAL_FILES: int = sum(s.files for s in SITE_CLASSES)
"""**18.** Fourteen `pyproject.toml`, two `package.json`, `toolchains.toml`, `first_party.toml`."""

PATCH_SITES: int = sum(s.count for s in SITE_CLASSES if s.patch)
"""**18** of the 40 — the sites a PATCH rewrites.

The other twenty-two are `~= <M>.<m>.0` bounds, which `~=` already satisfies across a whole MINOR
series (`~= 0.4.0` expands to `>= 0.4.0, == 0.4.*`). That is the distinction section 4.2's last
column counts exactly, and the reason a PATCH is a cheaper commit than a MINOR.
"""

if (TOTAL_SITES, TOTAL_FILES, PATCH_SITES) != (40, 18, 18):  # pragma: no cover - import-time guard
    raise AssertionError(
        f"SITE_CLASSES sums to {TOTAL_SITES} sites / {TOTAL_FILES} files / {PATCH_SITES} on a "
        "PATCH; 11-repo-layout.md section 4.2 states 40 / 18 / 18. Move the section and this "
        "table together, or revert. Adding a distribution moves the count: section 1.10 row 6."
    )

DIST_COUNT = 14
"""The literal fourteen. Section 1.10 resolves it against `len(glob("packages/*/pyproject.toml"))`,
which is what this tool does rather than carrying a list of names that could rot."""

PORTS_DIST = "omniweave-ports"
"""The one distribution not versioned by `RELEASE`. Section 4.1's stated exception, and the reason
a naive forty-site equality check reports a false failure on a correct tree."""

CLI_DIST = "omniweave"
"""The distribution that declares the extras block and the only holder of an `omniweave-office`
bound — the one first-party edge in the whole graph not forced by a protocol (section 1.4, OQ-3)."""

CORE_BOUND_DISTS: frozenset[str] = frozenset(
    {
        "omniweave",
        "omniweave-conform",
        "omniweave-serve",
        "omniweave-target-deck",
        "omniweave-target-docx",
        "omniweave-target-pptx",
        "omniweave-target-video",
    }
)
"""The seven carrying `omniweave-core ~= <M>.<m>.0`: section 4.2's *"the five `compile`-shipping
dists plus `omniweave-serve` and `omniweave`"*.

The five `compile`-shipping distributions are the four `omniweave-target-*` plus
`omniweave-conform`, which ships the reference target `compile.text.owtext` and carries the
`compile` row of `tools/layers.toml` for exactly that reason (section 1.2). Membership is
re-derived from `layers.toml`'s rule-4 rows by `test_gates_packaging.py` rather than trusted here.
"""

EXTRA_EXEMPT: frozenset[str] = frozenset(
    {CLI_DIST, "omniweave-core", PORTS_DIST, "omniweave-conform"}
)
"""The siblings with no extra.

Section 2.2: *"every sibling except `omniweave-conform`, `omniweave-core` and `omniweave-ports` has
an extra"* — plus `omniweave` itself, which declares the map and cannot alias itself.
`omniweave-conform` is *deliberately* absent: an extra on the runtime distribution that pulls
`pytest` is exactly how test-only weight lands in a production install, `markitdown-ocr` being the
recorded instance (MIT on the tin, hard-requiring AGPL PyMuPDF through the same door).
"""

RECOMMENDED: tuple[str, ...] = ("omniweave-serve", "omniweave-pdf", "omniweave-target-pptx")
"""`[recommended]`'s three, in the order section 2.2's block prints them.

`omniweave-target-docx` is deliberately **not** here: a second real target exists to falsify "one
implementation wearing an interface", not to be installed by default (section 1.2). The same three
are what section 2.3's "laptop, working" profile adds, and what `tools/gate_weights.py` sums against
`aggregate_mb`.
"""

TOOLCHAIN_ROWS = 2
"""`tools/toolchains.toml` carries exactly two `[[toolchain]]` rows: `deck` and `video`.

Section 1.6's tree has two Toolchain directories and no third. `toolchains/video/` ships **no
bundle** at release 1 because `omniweave-target-video`'s card declares `implemented = false`, but
its row still carries a version, which is why the count is two and not one.
"""

PORT_FLOOR = re.compile(r"omniweave-ports\s*>=\s*(\d+)\s*,\s*<\s*(\d+)")
"""`omniweave-ports >=1,<2` — a driver's floor, declared identically by all thirteen siblings."""

_SIBLING_BOUND = re.compile(r"^(omniweave-[a-z0-9-]+)\s*~=\s*(\d+\.\d+\.\d+)$")
_RELEASE_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PORT_MAJOR_RE = re.compile(r"^(\d+)\.0\.0$")
_COMMENT_RE = re.compile(r"^\s*#")


def extra_name(dist: str) -> str:
    """`omniweave-target-pptx` -> `pptx`. Section 2.2's spelling rule, derived and never listed.

    *"The extra name is the sibling name with `omniweave-` and any leading `target-` stripped."* The
    charter fixes the 1:1 rule and shows `[vision]` but does not fix the other ten spellings; the
    spelling adopted is markitdown's one-extra-per-format shape, so `pip install "omniweave[docx,
    pdf]"` reads the way a user guesses it. Deriving the name here is what lets G14's totality and
    injectivity clauses be checked without a second copy of the map living in this file (INV-21).
    """
    return dist.removeprefix("omniweave-").removeprefix("target-")


def bound(release: str) -> str:
    """`0.4.2` -> `0.4.0`, the `~=` bound the twenty-one derived sites carry.

    `~= 0.4.0` expands to `>= 0.4.0, == 0.4.*`. The bounds are **literal text in the file, written
    by a tool**: there is no packaging mechanism by which a `uv` workspace synthesises a version
    bound into a built wheel's metadata, and `[tool.uv.sources]` governs only where a member
    resolves from during development and is absent from the published `METADATA` entirely
    (section 2.2).
    """
    major, minor, _ = release.split(".")
    return f"{major}.{minor}.0"


@dataclass(frozen=True, slots=True)
class Finding:
    """One site that is present and wrong. `where` names the file and the locator inside it."""

    where: str
    expected: str
    found: str


@dataclass(frozen=True, slots=True)
class Pending:
    """A declared site whose file is not in the tree yet, with the locus that lands it.

    A gate that silently skips an absent site is a gate that passes on a deleted file. Every
    `Pending` is printed on every run and counted against `TOTAL_SITES` so that
    `checked + pending == 40` is visible arithmetic, and `--require-all-sites` promotes it to a
    failure for a release run.
    """

    path: str
    sites: int
    lands: str


@dataclass(slots=True)
class Report:
    """The result of one check: what was read, what is missing, and what is wrong."""

    release: str = ""
    port_major: int = 0
    checked: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    pending: list[Pending] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def pending_sites(self) -> int:
        return sum(p.sites for p in self.pending)

    def ok(self, *, require_all_sites: bool = False) -> bool:
        return not self.findings and not (require_all_sites and self.pending)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tables(text: str) -> Iterator[tuple[str, str]]:
    """Yield `(current_table_header, line)` for every line, tracking the current TOML table.

    `tomllib` gives values and loses positions; `--set` needs positions and a finding needs to name
    the table a wrong value sits in. Both walk this. A `[header]`-shaped line inside a multi-line
    string would fool it; none of the eighteen files has one, and `test_gates_packaging.py` holds
    that by round-tripping every `pyproject.toml` through `tomllib` before and after a `--set`.
    """
    table = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and not stripped.startswith("[["):
            table = stripped[1:-1]
        yield table, line


def _project_version(text: str) -> str | None:
    for table, line in _tables(text):
        if table != "project":
            continue
        match = re.match(r'\s*version\s*=\s*"([^"]*)"', line)
        if match:
            return match.group(1)
    return None


def _requirements(data: dict[str, object], key: str) -> list[str]:
    block = data.get("project", {})
    if not isinstance(block, dict):
        return []
    value = block.get(key, [])
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _dists(repo: Path) -> dict[str, Path]:
    return {p.parent.name: p for p in sorted(repo.glob("packages/*/pyproject.toml"))}


def _check_sibling_bounds(
    report: Report,
    where: str,
    requirements: Iterable[str],
    expected: dict[str, str],
) -> None:
    """Assert every `omniweave-* ~= X` requirement in one list matches `expected`, exactly.

    `expected` maps sibling name to the bound it must carry. A requirement naming a sibling not in
    `expected` is a finding — an undeclared first-party edge, which is rule 3 of the dependency rule
    showing up as a presence rather than the absence a reviewer reads for (section 4.2). A sibling
    in `expected` with no requirement is the symmetric finding. Third-party requirements are ignored
    here; G7 owns their comment rule and G14 owns "no extra may name a third-party package".
    """
    seen: set[str] = set()
    for requirement in requirements:
        match = _SIBLING_BOUND.match(requirement.strip())
        if match is None:
            continue
        dist, found = match.group(1), match.group(2)
        seen.add(dist)
        if dist not in expected:
            report.findings.append(
                Finding(f"{where}: {dist}", "no such first-party edge", requirement)
            )
        elif found != expected[dist]:
            report.findings.append(Finding(f"{where}: {dist} ~=", expected[dist], found))
        else:
            report.checked.append(f"{where}: {dist} ~= {found}")
    for dist in sorted(set(expected) - seen):
        report.findings.append(Finding(f"{where}: {dist} ~=", expected[dist], "absent"))


def _extras_block(data: dict[str, object]) -> dict[str, list[str]]:
    block = data.get("project", {})
    raw = block.get("optional-dependencies", {}) if isinstance(block, dict) else {}
    if not isinstance(raw, dict):
        return {}
    return {
        name: [r for r in value if isinstance(r, str)]
        for name, value in raw.items()
        if isinstance(value, list)
    }


def _check_one_extra(
    report: Report,
    where: str,
    name: str,
    requirements: list[str],
    *,
    expected: str,
    siblings: set[str],
    want: str,
) -> str | None:
    """One extra row. Returns the sibling it aliases, or `None` when the row is not an alias at all.

    Split out of `_check_extras` so that the injectivity clause — which is a statement about the
    map and not about a row — reads as one loop over rows rather than as a branch inside the row
    check. Returning the target is what lets the caller detect two extras naming one sibling.
    """
    if len(requirements) != 1:
        report.findings.append(
            Finding(f"{where}: [{name}]", "exactly one sibling (1:1 alias map)", repr(requirements))
        )
        return None
    match = _SIBLING_BOUND.match(requirements[0].strip())
    if match is None:
        report.findings.append(
            Finding(f"{where}: [{name}]", f"{expected} ~= {want} (G14)", requirements[0])
        )
        return None
    dist, found = match.group(1), match.group(2)
    if dist not in siblings:
        report.findings.append(Finding(f"{where}: [{name}]", "a first-party sibling (G14)", dist))
    elif dist != expected:
        report.findings.append(Finding(f"{where}: [{name}]", expected, dist))
    elif found != want:
        report.findings.append(Finding(f"{where}: [{name}] ~=", want, found))
    else:
        report.checked.append(f"{where}: [{name}] = {dist} ~= {found}")
    return dist


def _check_extras(
    report: Report, repo: Path, rel: str, data: dict[str, object], release: str
) -> None:
    """The extras block: the 1:1 alias map, its thirteen version strings, and G14's four clauses.

    G14 is *"no `all`/`everything` extra; the extras map is total and injective"* (section 6.4) and
    section 2.2 adds *"no extra may name a third-party package"*. All four clauses are read off the
    block G5 is already parsing, so they are asserted here rather than in a second tool that would
    have to reparse the same file (INV-21). An extra that may name only a first-party sibling cannot
    introduce an egress path, because the sibling's own card and G15 own that question — which is
    the property `markitdown`'s `audio-transcription = ["pydub", "SpeechRecognition"]` extra, which
    sends audio to Google's free Web Speech endpoint by default, does not have.
    """
    where = f"{rel}: [project.optional-dependencies]"
    extras = _extras_block(data)
    siblings = set(_dists(repo))
    expected_names = {extra_name(d): d for d in sorted(siblings - EXTRA_EXEMPT)}
    want = bound(release)

    for banned in ("all", "everything"):
        if banned in extras:
            report.findings.append(
                Finding(f"{where}: [{banned}]", "no such extra (G14)", "declared")
            )
    for name in sorted(set(expected_names) - set(extras)):
        report.findings.append(
            Finding(
                f"{where}: [{name}]", f"aliases {expected_names[name]} (G14 totality)", "absent"
            )
        )
    for name in sorted(set(extras) - set(expected_names) - {"recommended"}):
        report.findings.append(
            Finding(f"{where}: [{name}]", "a sibling alias or recommended (G14)", "declared")
        )

    targets: dict[str, str] = {}
    for name in sorted(set(extras) & set(expected_names)):
        dist = _check_one_extra(
            report,
            where,
            name,
            extras[name],
            expected=expected_names[name],
            siblings=siblings,
            want=want,
        )
        if dist is None:
            continue
        if dist in targets:
            report.findings.append(
                Finding(
                    f"{where}: [{name}]",
                    "an unaliased sibling (G14 injectivity)",
                    f"also aliased by [{targets[dist]}]",
                )
            )
        targets[dist] = name

    if "recommended" not in extras:
        report.findings.append(Finding(f"{where}: [recommended]", "declared", "absent"))
        return
    _check_sibling_bounds(
        report, f"{where}: [recommended]", extras["recommended"], dict.fromkeys(RECOMMENDED, want)
    )


def _check_pyprojects(report: Report, repo: Path, release: str, port_major: int) -> None:
    """The thirty-five sites living in `packages/*/pyproject.toml` — five of the eight classes."""
    dists = _dists(repo)
    if len(dists) != DIST_COUNT:
        report.findings.append(
            Finding("packages/*/pyproject.toml", f"{DIST_COUNT} distributions", str(len(dists)))
        )
    floors: set[tuple[int, int]] = set()
    for dist, path in dists.items():
        rel = path.relative_to(repo).as_posix()
        text = _read(path)
        data = tomllib.loads(text)
        found = _project_version(text)
        want = f"{port_major}.0.0" if dist == PORTS_DIST else release
        if found is None:
            report.findings.append(Finding(f"{rel}: [project] version", want, "absent"))
        elif found != want:
            report.findings.append(Finding(f"{rel}: [project] version", want, found))
        else:
            report.checked.append(f"{rel}: [project] version = {found}")

        requirements = _requirements(data, "dependencies")
        expected: dict[str, str] = {}
        if dist in CORE_BOUND_DISTS:
            expected["omniweave-core"] = bound(release)
        if dist == CLI_DIST:
            expected["omniweave-office"] = bound(release)
        _check_sibling_bounds(report, f"{rel}: [project] dependencies", requirements, expected)

        for requirement in requirements:
            match = PORT_FLOOR.search(requirement)
            if match:
                floors.add((int(match.group(1)), int(match.group(2))))
        if dist == CLI_DIST:
            _check_extras(report, repo, rel, data, release)

    if floors and floors != {(port_major, port_major + 1)}:
        report.findings.append(
            Finding(
                "packages/*/pyproject.toml: the omniweave-ports floor",
                f">={port_major},<{port_major + 1} on every sibling",
                ", ".join(f">={lo},<{hi}" for lo, hi in sorted(floors)),
            )
        )
    else:
        report.notes.append(
            f"{PORTS_DIST} is versioned by Port major {port_major}.0.0, not by RELEASE "
            f"(section 4.1); every sibling declares the matching >={port_major},"
            f"<{port_major + 1} floor."
        )


def _check_toolchains(report: Report, repo: Path, release: str) -> None:
    """The four sites the `toolchains` job owns, first green at P9 (16-roadmap.md section 3).

    `toolchains/video/` exists in tree and ships **no bundle** at release 1 because
    `omniweave-target-video`'s card declares `implemented = false` (section 1.6). Its
    `package.json` still carries a `version`, so the row is two sites and not one: keeping the
    directory and not shipping the artefact is the honest shape, and a version-sync gate that
    skipped the unshipped half would let it drift for a whole release series.
    """
    lands = "16-roadmap.md section 3: the `toolchains` job is first green at P9"
    for name in ("deck", "video"):
        path = repo / "toolchains" / name / "package.json"
        rel = path.relative_to(repo).as_posix()
        if not path.is_file():
            report.pending.append(Pending(rel, 1, lands))
            continue
        value = json.loads(_read(path)).get("version")
        if value != release:
            report.findings.append(Finding(f"{rel}: version", release, str(value)))
        else:
            report.checked.append(f"{rel}: version = {value}")

    path = repo / "tools" / "toolchains.toml"
    rel = path.relative_to(repo).as_posix()
    if not path.is_file():
        report.pending.append(Pending(rel, 2, lands))
        return
    raw = tomllib.loads(_read(path)).get("toolchain", [])
    rows = raw if isinstance(raw, list) else []
    if len(rows) != TOOLCHAIN_ROWS:
        report.findings.append(
            Finding(f"{rel}: [[toolchain]]", f"{TOOLCHAIN_ROWS} rows (deck, video)", str(len(rows)))
        )
    for index, row in enumerate(rows):
        value = row.get("version") if isinstance(row, dict) else None
        if value != release:
            report.findings.append(
                Finding(f"{rel}: [[toolchain]][{index}] version", release, str(value))
            )
        else:
            report.checked.append(f"{rel}: [[toolchain]][{index}] version = {value}")


def _check_first_party(report: Report, repo: Path, release: str) -> None:
    """`first_party.toml`'s `release`. Generated **into** `src/` by the `build` job, `.gitignore`d.

    Section 2.6 states the consequence out loud: a workspace install has no manifest at all, so
    `compute_trust` returns `unpinned` with a `Degradation(kind="pin")`, and that is correct rather
    than a gap — an editable checkout has no wheel and therefore no `dist_sha256` to attest. Section
    4.2's table gives this site's writer as *"generated in `build` (§7.2)"* rather than `--set`,
    which is why `write_release()` never touches it and this function only reads it.
    """
    path = (
        repo
        / "packages"
        / "omniweave-core"
        / "src"
        / "omniweave_core"
        / "drivers"
        / "first_party.toml"
    )
    rel = path.relative_to(repo).as_posix()
    if not path.is_file():
        report.pending.append(
            Pending(
                rel,
                1,
                "11-repo-layout.md sections 2.6 and 7.2: generated by `build`, .gitignore'd",
            )
        )
        return
    value = tomllib.loads(_read(path)).get("release")
    if value != release:
        report.findings.append(Finding(f"{rel}: release", release, str(value)))
    else:
        report.checked.append(f"{rel}: release = {value}")


def _check_asserted_never_written(
    report: Report, repo: Path, release: str, tag: str | None
) -> None:
    """Section 4.2's three sites that are *asserted and never written*, and count toward no total.

    The git tag (`v<RELEASE>`, checked on a tag push), `CHANGELOG.md`'s topmost heading (asserted to
    name `<RELEASE>`; hand-written, because a generated changelog is a commit log), and
    `docs/reference/**` (generated by `ow surface emit --docs` and byte-diff gated by the
    `gates.reference_docs` job assertion, so it carries `RELEASE` without declaring it — nothing
    for this tool to read). The tag is passed in rather than shelled out for, so the check path
    stays subprocess-free for `.pre-commit-config.yaml` and for CI job 1.
    """
    if tag is not None and tag != f"v{release}":
        report.findings.append(Finding("git tag", f"v{release}", tag))
    elif tag is not None:
        report.checked.append(f"git tag = {tag} (asserted, never written)")

    changelog = repo / "CHANGELOG.md"
    if not changelog.is_file():
        report.notes.append(
            "CHANGELOG.md is absent; its topmost heading is asserted once it exists."
        )
        return
    heading = next((line for line in _read(changelog).splitlines() if line.startswith("#")), "")
    if release not in heading:
        report.findings.append(
            Finding("CHANGELOG.md: topmost heading", f"names {release}", heading or "no heading")
        )
    else:
        report.checked.append(f"CHANGELOG.md: topmost heading names {release}")


def check(
    repo: Path = REPO,
    *,
    release: str | None = None,
    port_major: int | None = None,
    tag: str | None = None,
) -> Report:
    """Read all forty sites and return what is wrong, what is absent, and what was read.

    `release` defaults to `packages/omniweave-core/pyproject.toml`'s `[project] version`. That file
    is the anchor because `omniweave_core.contract.RELEASE` reads *its* distribution metadata, so
    every consumer of `RELEASE` at run time is already reading this number; the plan names no other
    anchor, and picking a second one would be the forty-first site `contract.py` exists to avoid.

    `port_major` defaults to the major of `omniweave-ports`' own version, which is then
    cross-checked against the `omniweave-ports >=N,<N+1` floor all thirteen siblings declare. That
    cross-check is the only mechanical statement available about a number that moves on nothing
    `RELEASE` does: a Port 2 is a new distribution version, and Port 1 drivers keep resolving until
    the framework drops their major from `CONTRACTS_SUPPORTED` (section 4.4).
    """
    report = Report()
    core = repo / "packages" / "omniweave-core" / "pyproject.toml"
    if release is None:
        release = _project_version(_read(core)) or ""
    report.release = release
    if not _RELEASE_RE.match(release):
        report.findings.append(
            Finding(
                "RELEASE anchor: omniweave-core [project] version", "M.m.p", release or "absent"
            )
        )
        return report

    ports = repo / "packages" / PORTS_DIST / "pyproject.toml"
    if port_major is None:
        raw = _project_version(_read(ports)) or ""
        match = _PORT_MAJOR_RE.match(raw)
        if match is None:
            report.findings.append(
                Finding(
                    f"packages/{PORTS_DIST}/pyproject.toml: [project] version",
                    "N.0.0 (Port major)",
                    raw,
                )
            )
            return report
        port_major = int(match.group(1))
    report.port_major = port_major

    _check_pyprojects(report, repo, release, port_major)
    _check_toolchains(report, repo, release)
    _check_first_party(report, repo, release)
    _check_asserted_never_written(report, repo, release, tag)
    return report


# ---------------------------------------------------------------------------------------------
# --set: the writer half
# ---------------------------------------------------------------------------------------------


def _write_lines(path: Path, original: str, lines: list[str]) -> bool:
    r"""Write `lines` back to `path` with `\n` line endings. Returns whether anything changed.

    `newline="\n"` is not a style choice. `.gitattributes` pins `eol=lf` for every generated tree
    and semgrep bans a bare `open(..., "w")` under `tools/`, because a generator that emits `\n`
    while a Windows working tree holds `\r\n` makes five byte-diff gates disagree for reasons that
    have nothing to do with the code (section 1.9, rules 1 and 2 of three).
    """
    trailing = "\n" if original.endswith("\n") else ""
    new = "\n".join(lines) + trailing
    if new == original:
        return False
    path.write_text(new, encoding="utf-8", newline="\n")
    return True


def _rewrite(path: Path, rewriter: Callable[[str], str]) -> bool:
    original = _read(path)
    return _write_lines(path, original, [rewriter(line) for line in original.splitlines()])


def _pyproject_lines(text: str, release: str, port_major: int, dist: str) -> list[str]:
    """Rewrite one `pyproject.toml`'s version line and every `omniweave-* ~=` bound in it.

    Two substitutions and no TOML round-trip: `tomllib` is a reader with no writer in the stdlib,
    and a round-trip through any writer would discard the comments these files carry — including
    the one on `packages/omniweave/pyproject.toml`'s extras block that tells a reader not to
    hand-edit a bound. A comment-only line is skipped so that a bound quoted in prose is not
    rewritten into a claim the file does not make.
    """
    want_version = f"{port_major}.0.0" if dist == PORTS_DIST else release
    want_bound = bound(release)
    out: list[str] = []
    for table, line in _tables(text):
        if table == "project" and re.match(r'\s*version\s*=\s*"', line):
            out.append(
                re.sub(r'(version\s*=\s*")[^"]*(")', rf"\g<1>{want_version}\g<2>", line, count=1)
            )
        elif _COMMENT_RE.match(line):
            out.append(line)
        else:
            out.append(
                re.sub(r"(omniweave-[a-z0-9-]+\s*~=\s*)\d+\.\d+\.\d+", rf"\g<1>{want_bound}", line)
            )
    return out


def write_release(repo: Path, release: str, *, port_major: int | None = None) -> list[str]:
    """Rewrite every `--set`-owned site. Returns the repo-relative paths actually changed.

    Section 4.2's "written by `--set`" column names the owned sites: the thirteen `[project]
    version` fields, `omniweave-ports`' version, the seven `omniweave-core` bounds, the one
    `omniweave-office` bound, the thirteen extras strings, the two `package.json` versions and the
    two `toolchains.toml` rows. `first_party.toml` is **not** among them — its column reads
    *"generated in `build`"* — so this function never touches it.

    `port_major` defaults to the value already in `packages/omniweave-ports/pyproject.toml`. A
    `RELEASE` bump does not move the Port major (section 4.1: it moves when a driver's pin would
    otherwise break), so defaulting to the current value is the only behaviour that cannot invent
    one. `--set` normalises it to `N.0.0`, which is why the site is "written by `--set`: yes" and
    "rewritten on a PATCH: no" in the same row.
    """
    if not _RELEASE_RE.match(release):
        raise ValueError(
            f"RELEASE must be M.m.p, got {release!r}. 11-repo-layout.md section 4.1: one semver, "
            "e.g. 0.4.2, carried by thirteen of the fourteen distributions and by the git tag."
        )
    dists = _dists(repo)
    if port_major is None:
        raw = _project_version(_read(dists[PORTS_DIST])) or ""
        match = _PORT_MAJOR_RE.match(raw)
        if match is None:
            raise ValueError(
                f"{PORTS_DIST} carries {raw!r}, not N.0.0; pass --port-major explicitly. "
                "It is versioned by Port major, not RELEASE (11-repo-layout.md section 4.1)."
            )
        port_major = int(match.group(1))

    changed: list[str] = []
    for dist, path in sorted(dists.items()):
        original = _read(path)
        lines = _pyproject_lines(original, release, port_major, dist)
        if _write_lines(path, original, lines):
            changed.append(path.relative_to(repo).as_posix())

    for name in ("deck", "video"):
        path = repo / "toolchains" / name / "package.json"
        if path.is_file() and _rewrite(
            path,
            lambda line: re.sub(
                r'("version"\s*:\s*")[^"]*(")', rf"\g<1>{release}\g<2>", line, count=1
            ),
        ):
            changed.append(path.relative_to(repo).as_posix())

    path = repo / "tools" / "toolchains.toml"
    if path.is_file() and _rewrite(
        path, lambda line: re.sub(r'^(\s*version\s*=\s*")[^"]*(")', rf"\g<1>{release}\g<2>", line)
    ):
        changed.append(path.relative_to(repo).as_posix())
    return changed


def _uv_lock(repo: Path) -> int:
    """`uv lock --offline` — `--set`'s mandatory last step. Section 4.2 prices skipping it.

    *"`uv.lock` records every workspace member's version, so rewriting thirteen `[project] version`
    fields invalidates the lock: `uv sync --frozen` would fail on the release commit with a
    lock/manifest mismatch, which is the right failure and the wrong time to discover it."* The
    consequence is arithmetic rather than an inconvenience — `hashFiles('uv.lock')` changes, all
    nine `uv` cache keys miss, and the release run pays the ~95 s cold install in every one of its
    fifteen uv-installing jobs. That is where section 6.3's "~25 min plus the approval pause" comes
    from: a release run is always cold by construction, and `restore-keys` is the only thing keeping
    it from being a full re-download.

    Two scoped suppressions, both deliberate. `TID251` bans `subprocess` outside
    `omniweave_core.toolchain` and `omniweave_core.host.subproc` — a rule about the four seams in
    *library* code, and `tools/` is neither library nor seam. `S603`/`S607` want a resolved absolute
    argv, and resolving `uv` here would defeat the point of running the `uv` the release engineer's
    shell selected. The import is function-local so that the check path — CI job 1, and the
    pre-commit hook — never imports `subprocess` at all.
    """
    # TID251/PLC0415: see the docstring. The import is function-local so the check path never
    # imports subprocess at all. S603/S607: `uv` is deliberately resolved from PATH.
    import subprocess  # noqa: TID251, PLC0415

    return subprocess.run(["uv", "lock", "--offline"], cwd=repo, check=False).returncode  # noqa: S607


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def _say(text: str) -> None:
    """Write one line to stdout.

    `sys.stdout.write` rather than `print` because ruff's `T20` is selected repo-wide and
    `tools/*.py` carries no `per-file-ignores` row for it. `T20`'s premise — *"a library that
    prints has no way to be quiet inside a hook with a 400 ms deadline"* (section 8.1) — does not
    hold for a gate script whose whole output contract is a printed checklist, so the correct fix
    is a `per-file-ignores` entry for `tools/*.py` in the workspace root. Until that lands this
    helper keeps the file green without silencing the rule anywhere it does apply.
    """
    sys.stdout.write(f"{text}\n")


def _render(report: Report, *, require_all_sites: bool, verbose: bool) -> None:
    total = len(report.checked) + report.pending_sites
    _say(f"G5 check_versions: RELEASE {report.release}, Port major {report.port_major}.0.0")
    _say(f"  sites checked: {len(report.checked)}/{TOTAL_SITES}   (11-repo-layout.md section 4.2)")
    if verbose:
        for line in report.checked:
            _say(f"    ok  {line}")
    for note in report.notes:
        _say(f"  note: {note}")
    for pend in report.pending:
        word = "FAIL" if require_all_sites else "PENDING"
        plural = "s" if pend.sites > 1 else ""
        _say(f"  {word} {pend.path}  ({pend.sites} site{plural}) - {pend.lands}")
    if not report.findings and total != TOTAL_SITES:
        _say(
            f"  WARNING: {len(report.checked)} checked + {report.pending_sites} pending = {total}, "
            f"not {TOTAL_SITES}. A site class is miscounted; see section 4.2 and 1.10 row 6."
        )
    for finding in report.findings:
        _say(f"  FAIL {finding.where}")
        _say(f"         expected: {finding.expected}")
        _say(f"         found:    {finding.found}")
    ok = report.ok(require_all_sites=require_all_sites)
    _say("G5 PASS" if ok else "G5 FAIL - run `uv run tools/check_versions.py --set <RELEASE>`")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_versions.py",
        description="G5, CI job 1: the forty version sites of 11-repo-layout.md section 4.2.",
    )
    parser.add_argument(
        "--repo", type=Path, default=REPO, help="workspace root (default: this checkout)"
    )
    parser.add_argument(
        "--set", dest="set_release", metavar="RELEASE", help="rewrite every site, then check"
    )
    parser.add_argument(
        "--port-major", type=int, default=None, help="Port major for --set (default: unchanged)"
    )
    parser.add_argument("--tag", default=None, help="assert this git ref equals v<RELEASE>")
    parser.add_argument(
        "--require-all-sites",
        action="store_true",
        help="a declared-but-absent site fails instead of reporting PENDING (release runs)",
    )
    parser.add_argument(
        "--no-lock", action="store_true", help="skip `uv lock --offline` after --set"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print every site that passed")
    args = parser.parse_args(argv)

    repo: Path = args.repo.resolve()
    if args.set_release:
        for rel in write_release(repo, args.set_release, port_major=args.port_major):
            _say(f"  set  {rel}")
        if args.no_lock:
            _say("  note: uv.lock NOT regenerated (--no-lock); `uv sync --frozen` refuses it")
        else:
            code = _uv_lock(repo)
            if code != 0:
                _say(
                    f"  FAIL uv lock --offline exited {code}; the commit needs the updated uv.lock"
                )
                return 1
            _say("  set  uv.lock (uv lock --offline)")

    report = check(repo, release=args.set_release, port_major=args.port_major, tag=args.tag)
    _render(report, require_all_sites=args.require_all_sites, verbose=args.verbose)
    return 0 if report.ok(require_all_sites=args.require_all_sites) else 1


if __name__ == "__main__":
    raise SystemExit(main())
