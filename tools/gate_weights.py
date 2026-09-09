"""G2: the fourteen per-distribution weight ceilings and the one 250 MB union.

11-repo-layout.md section 2.5 owns `tools/weights.toml` and this tool is its only reader.
16-roadmap.md section 4's P1 exit line names both halves — *"14 rows + the 250 MB `[recommended]`
aggregate"* — and section 6.4 gives G2 its job (`build`) and its budget (90 s).

**The column reads marginal, and that is a ruling rather than a preference.** Read as a *closure*
the charter's `ceiling` column is internally inconsistent: `omniweave-target-deck`'s ceiling is 1 MB
while its dependency `omniweave-core`'s is 3 MB, and a closure cannot be smaller than something it
contains. ADR-10 settled it, charter erratum E79 carried it, and section 2.5 is the reading's sole
home: a row is the distribution's own installed files plus the third-party closure it introduces,
excluding first-party siblings, each of which is counted in its own row. `aggregate_mb` is then the
only *union* number, measured by installing `omniweave[recommended]` into a fresh environment and
summing every `RECORD` with each installed path counted once.

**Both numbers are printed on every run, pass or fail** — the per-row sum and the deduplicated union
— so the gap between them is never inferred (section 2.5; `11#OQ-2`'s discharge names this tool by
name). On a failure the per-row table names the row, its ceiling, its measured value and the largest
three files in it.

Section 2.5's four failure modes are each answered rather than assumed away:

1. **Runtime-downloaded data contributes nothing to `RECORD`.** A wheel that fetches a model is
   unbounded weight the measurement cannot see, which is why `omniweave-vision` is `unbounded` and
   why `revision="main"` is a lint error (G8). An `unbounded` row is reported with its measured size
   and never fails; `ow doctor` prints the resolved number, and the plan does not promise one.
2. **A shared third-party dependency counted in two rows double-counts against `aggregate_mb`.** The
   union deduplicates on installed path, never by summing rows.
3. **`RECORD` is a manifest, not a filesystem.** A wheel may install a file it does not list. Both
   are measured — the `RECORD` sum and a walk of `site-packages` — and a discrepancy above
   `DISCREPANCY` fails, naming the unlisted paths.
4. **Compiled artefacts appear after first import.** `__pycache__` is written on first run, not on
   install, so it is reported as its own line and an environment with none is flagged as measured
   before first import, which understates a pure-Python distribution by roughly its source size.

A `RECORD` walk is forbidden as a discovery mechanism anywhere else in the framework — it measured
2,124 ms over 328 distributions against `entry_points()`'s 15.3 ms — and is permitted **only here**,
where it runs once in CI and never on a user's machine (section 2.3).

Without `--measure` this tool checks the declaration and the arithmetic only, says so in as many
words, and never reports a measurement it did not take.

Specified in 11-repo-layout.md sections 2.5, 2.3, 2.4, 1.2 and 1.10 row 4; gate row G2 in section
6.4; run by 16-roadmap.md section 4's P1 exit criteria.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DISCREPANCY",
    "MB",
    "PROFILES",
    "REPO",
    "Distribution",
    "Measurement",
    "Result",
    "Row",
    "check_declaration",
    "first_party_closure",
    "load_weights",
    "main",
    "measure",
    "profile_roots",
    "read_recommended",
]

REPO = Path(__file__).resolve().parents[1]

MB = 1_000_000
"""Bytes in one `MB` of `tools/weights.toml`.

The plan spells 2^20 as `MiB` where it means it — section 1.6's "1 MiB stdout cap",
12-performance.md's GiB budgets — and spells this column `MB`, so the two are not the same unit and
this is the SI one. The plan does not state the conversion explicitly; the spelling is the evidence,
and `tools/weights.toml`'s header comment is the only other place this is written down.
"""

DISCREPANCY = 0.05
"""Section 2.5 failure mode 3: fail when the filesystem exceeds the `RECORD` manifest by more
than 5%, naming the unlisted paths. *"Without the second measurement the gate can be defeated by
any dependency that writes outside its own `RECORD`."*"""

PROFILES: tuple[str, ...] = ("minimum", "recommended", "cpu-server", "gpu-server", "ci")
"""The five install profiles of section 2.3 that have a ceiling sum.

The sixth, **browser**, is 0 MB and has no install command: omniweave does not run in a browser, and
what a browser gets is a generated client from `ow surface typescript`. Inventing a browser install
profile would be the wrong answer, so this tool has no row for it.
"""

_EXTRA_PROFILE: Mapping[str, tuple[str, ...]] = {
    "minimum": (),
    "recommended": ("recommended",),
    "cpu-server": ("recommended", "graph", "llm", "docx"),
    "gpu-server": ("recommended", "graph", "llm", "vision"),
}
"""Each profile's extras, transcribed from section 2.3's `command` column.

`ci` is not here: it is `uv sync --frozen --all-packages --group dev`, which is every distribution
rather than an extras selection, and is handled by `profile_roots`. The **GPU server** row is *not*
the CPU-server sum plus vision — it drops `docx` and adds `vision`, so its ceiling sum is smaller
than the row above it while its real installed size is an order of magnitude larger. That asymmetry
is why `omniweave-vision`'s exemption is stated on its row rather than in a footnote.
"""

_RECORD_COLUMNS = 3
"""`path,hash,size` - a `RECORD` row's three columns. A row with an empty size column contributes a
path and no declared bytes, which is why the filesystem walk exists beside the manifest (section
2.5 failure mode 3)."""

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTRA_MARKER = re.compile(r";.*\bextra\s*==")


@dataclass(frozen=True, slots=True)
class Row:
    """One `[dist."…"]` table of `tools/weights.toml`.

    `why` is not decoration. Section 4.3's packaging row makes *raising a `weights.toml` ceiling
    with a `why` line* the non-breaking half of a pair whose other half is breaking, and section 1.7
    calls this *"the one file where raising a number is a reviewable act with its own justification
    line"*. A row without one is refused here, so the reviewable act cannot be performed silently.
    """

    dist: str
    marginal_mb: int
    unbounded: bool
    why: str

    @property
    def ceiling_bytes(self) -> int:
        return self.marginal_mb * MB


@dataclass(frozen=True, slots=True)
class Distribution:
    """One installed distribution as `RECORD` and the filesystem jointly describe it."""

    name: str
    requires: frozenset[str]
    paths: frozenset[Path]
    listed_bytes: int
    actual_bytes: int


@dataclass(slots=True)
class Measurement:
    """What one `site-packages` tree actually holds. Absent without `--measure`."""

    site_packages: Path
    dists: dict[str, Distribution] = field(default_factory=dict)
    walk_bytes: int = 0
    pycache_bytes: int = 0
    unlisted: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class Result:
    """The verdict, the two numbers section 2.5 requires on every run, and the failure table."""

    findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    row_sum_bytes: int = 0
    union_bytes: int = 0
    table: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


# ---------------------------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------------------------


def load_weights(path: Path) -> tuple[int, int, dict[str, Row]]:
    """Parse `tools/weights.toml` into `(schema, aggregate_mb, rows)`.

    Raises rather than returning a finding when the file will not parse at all: a gate that cannot
    read its own declaration has nothing to report, and section 1.7's rule that no file in `tools/`
    may be edited to make a gate pass only means anything if an unreadable one stops the build.
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, Row] = {}
    for dist, table in (data.get("dist") or {}).items():
        rows[dist] = Row(
            dist=dist,
            marginal_mb=int(table.get("marginal_mb", -1)),
            unbounded=bool(table.get("unbounded", False)),
            why=str(table.get("why", "")).strip(),
        )
    return int(data.get("schema", 0)), int(data.get("aggregate_mb", 0)), rows


def _pyproject_deps(path: Path) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    return [r for r in project.get("dependencies", []) if isinstance(r, str)]


def _requirement_name(requirement: str) -> str:
    match = _REQ_NAME.match(requirement)
    return match.group(1).lower().replace("_", "-") if match else ""


def _dist_paths(repo: Path) -> dict[str, Path]:
    return {p.parent.name: p for p in sorted(repo.glob("packages/*/pyproject.toml"))}


def first_party_closure(repo: Path, roots: Iterable[str]) -> set[str]:
    """Every first-party distribution a set of roots pulls in, transitively.

    Walks `[project] dependencies` in the workspace's own `pyproject.toml` files, so it reads the
    graph section 1.2's `deps` column renders rather than a second copy of it. `tools/layers.toml`
    is the *import* DAG and is not this: two distributions may share an import root and differ in
    their dependency edges, which is exactly `omniweave-office`'s shape (rule 3 of the dependency
    rule, and the one first-party edge not forced by a protocol).
    """
    paths = _dist_paths(repo)
    seen: set[str] = set()
    queue = [r for r in roots if r in paths]
    while queue:
        dist = queue.pop()
        if dist in seen:
            continue
        seen.add(dist)
        for requirement in _pyproject_deps(paths[dist]):
            name = _requirement_name(requirement)
            if name in paths and name not in seen:
                queue.append(name)
    return seen


def read_recommended(repo: Path) -> tuple[str, ...]:
    """`[recommended]`'s siblings, read from `packages/omniweave/pyproject.toml`.

    Read rather than declared: the extras block is the fact's home, `tools/check_versions.py`
    asserts its contents against section 2.2's printed block, and a second copy here would be the
    second home for one fact INV-21 forbids. G14 having already run in the same `gates` job means a
    wrong block fails there with a better message than a weight gate could give it.
    """
    data = tomllib.loads(
        (repo / "packages" / "omniweave" / "pyproject.toml").read_text(encoding="utf-8")
    )
    extras = data.get("project", {}).get("optional-dependencies", {})
    return tuple(_requirement_name(r) for r in extras.get("recommended", []))


def profile_roots(repo: Path, profile: str) -> set[str]:
    """The distribution set one install profile of section 2.3 installs.

    `ci` is `uv sync --frozen --all-packages --group dev` — every distribution — minus
    `omniweave-vision`, which section 2.3's row states as "all 14 except vision" and section 6.5
    confirms from the other end: `ow-gpu-1` is *"the only cell where `omniweave-vision` is
    installed"*. The dev group's own weight is not gated, is not shipped, and the `parity` container
    installs `pytest` alone, so it contributes nothing here.
    """
    paths = _dist_paths(repo)
    if profile == "ci":
        return set(paths) - {"omniweave-vision"}
    extras = (
        tomllib.loads(
            (repo / "packages" / "omniweave" / "pyproject.toml").read_text(encoding="utf-8")
        )
        .get("project", {})
        .get("optional-dependencies", {})
    )
    roots = {"omniweave"}
    for extra in _EXTRA_PROFILE[profile]:
        roots.update(_requirement_name(r) for r in extras.get(extra, []))
    return first_party_closure(repo, roots)


def check_declaration(
    repo: Path, schema: int, aggregate_mb: int, rows: Mapping[str, Row]
) -> Result:
    """The half of G2 that needs no environment: the fourteen rows and the aggregate arithmetic.

    Section 1.10 row 4 states the failure mode this closes — *"an unlisted distribution has no
    ceiling and fails closed"* — so the row set is checked against
    `glob("packages/*/pyproject.toml")` and never against a list written here.
    """
    result = Result()
    if schema != 1:
        result.findings.append(f"tools/weights.toml: schema is {schema}, expected 1 (section 2.5)")
    dists = set(_dist_paths(repo))
    for dist in sorted(dists - set(rows)):
        result.findings.append(
            f'{dist}: no [dist."{dist}"] row in tools/weights.toml. An unlisted distribution has '
            "no ceiling and fails closed (11-repo-layout.md section 1.10 row 4)."
        )
    for dist in sorted(set(rows) - dists):
        result.findings.append(
            f'{dist}: a [dist."{dist}"] row with no packages/{dist}/pyproject.toml. The fourteen '
            "distribution names froze at the P1 exit (16-roadmap.md section 4)."
        )
    for dist, row in sorted(rows.items()):
        if not row.why:
            result.findings.append(
                f"{dist}: no `why` line. Raising a ceiling is non-breaking only with one "
                "(11-repo-layout.md section 4.3, packaging row; section 1.7)."
            )
        if row.marginal_mb < 0:
            result.findings.append(f"{dist}: no `marginal_mb`.")
        if row.unbounded and row.marginal_mb != 0:
            result.findings.append(
                f"{dist}: unbounded rows carry marginal_mb = 0, not {row.marginal_mb}. A number "
                "beside `unbounded` is a promise the row exists to refuse to make (section 1.2)."
            )

    bounded = {d: r for d, r in rows.items() if not r.unbounded}
    for profile in PROFILES:
        members = profile_roots(repo, profile) & set(rows)
        total = sum(rows[d].marginal_mb for d in members if d in bounded)
        exempt = sorted(d for d in members if d not in bounded)
        suffix = f" + {' + '.join(exempt)}" if exempt else ""
        result.notes.append(f"profile {profile:<11} ceiling sum {total:>4} MB{suffix}")
        if profile == "recommended" and total > aggregate_mb:
            result.findings.append(
                f"[recommended]'s ceiling sum is {total} MB, above aggregate_mb = {aggregate_mb}. "
                "The aggregate is a union and the sum is an upper bound on it, so a sum above the "
                "aggregate makes the gate unsatisfiable before anything is installed (section 2.3)."
            )
    return result


# ---------------------------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------------------------


def _record_paths(dist_info: Path) -> tuple[frozenset[Path], int]:
    """Read one `RECORD`, returning its resolved paths and the byte total it declares.

    `RECORD` rows are `path,hash,size` with the path relative to `site-packages`. A row with an
    empty size is a directory-creating or generated entry (`RECORD` itself, `.pyc` files an
    installer wrote); it contributes a path and no declared bytes, which is the honest reading and
    is why the filesystem walk exists beside this.
    """
    record = dist_info / "RECORD"
    if not record.is_file():
        return frozenset(), 0
    root = dist_info.parent
    paths: set[Path] = set()
    listed = 0
    for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        parts = line.rsplit(",", 2)
        target = (root / parts[0].strip('"')).resolve()
        paths.add(target)
        if len(parts) == _RECORD_COLUMNS and parts[2].strip().isdigit():
            listed += int(parts[2])
    return frozenset(paths), listed


def _metadata_requires(dist_info: Path) -> frozenset[str]:
    """`Requires-Dist` names, with extras-gated requirements dropped.

    A requirement carrying `; extra == "…"` is only installed when that extra was asked for; the
    installed set already reflects whichever were, so following the edge unconditionally would
    attribute a package to a row that did not pull it in.
    """
    metadata = dist_info / "METADATA"
    if not metadata.is_file():
        return frozenset()
    names: set[str] = set()
    for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("Requires-Dist:"):
            if not line.strip():
                break
            continue
        value = line.split(":", 1)[1]
        if _EXTRA_MARKER.search(value):
            continue
        name = _requirement_name(value)
        if name:
            names.add(name)
    return frozenset(names)


def measure(site_packages: Path) -> Measurement:
    """Walk one `site-packages`: every `*.dist-info`, its `RECORD`, and the tree itself.

    The two measurements are taken independently on purpose. `RECORD` is a manifest and the walk is
    a filesystem, and section 2.5's third failure mode is that a wheel may install a file it does
    not list — a `.pth`-installed package lists almost nothing. Comparing them is the only way the
    gate cannot be defeated by a dependency that writes outside its own `RECORD`.
    """
    out = Measurement(site_packages=site_packages)
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        name = dist_info.name.split("-")[0].lower().replace("_", "-")
        paths, listed = _record_paths(dist_info)
        actual = sum(p.stat().st_size for p in paths if p.is_file())
        out.dists[name] = Distribution(
            name=name,
            requires=_metadata_requires(dist_info),
            paths=paths,
            listed_bytes=listed,
            actual_bytes=actual,
        )
    known = {p for d in out.dists.values() for p in d.paths}
    for path in site_packages.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        out.walk_bytes += size
        if "__pycache__" in path.parts:
            out.pycache_bytes += size
        elif path.resolve() not in known:
            out.unlisted.append(path)
    return out


def _third_party_closure(m: Measurement, root: str, first_party: frozenset[str]) -> set[str]:
    """The third-party distributions `root` introduces, not passing through a first-party sibling.

    Section 2.5's marginal reading in one function: a first-party sibling is counted in its own row,
    so an edge into one is not followed. A third-party package reachable from two first-party rows
    is counted in **both** — that is the acknowledged double-count, and it is why `aggregate_mb` is
    measured as a union over installed paths rather than as a sum of these rows.
    """
    seen: set[str] = set()
    queue = list(m.dists[root].requires)
    while queue:
        name = queue.pop()
        if name in seen or name in first_party or name not in m.dists:
            continue
        seen.add(name)
        queue.extend(m.dists[name].requires)
    return seen


def _largest(m: Measurement, names: Iterable[str], limit: int = 3) -> list[str]:
    files = [
        (p.stat().st_size, p)
        for n in names
        if n in m.dists
        for p in m.dists[n].paths
        if p.is_file()
    ]
    files.sort(reverse=True)
    return [f"{size / MB:8.2f} MB  {path.name}" for size, path in files[:limit]]


def _apply_measurement(result: Result, m: Measurement, rows: Mapping[str, Row]) -> None:
    """Score every installed first-party row against its ceiling and compute the two numbers."""
    first_party = frozenset(rows)
    row_paths: dict[str, set[Path]] = {}
    for dist, row in sorted(rows.items()):
        if dist not in m.dists:
            continue
        closure = _third_party_closure(m, dist, first_party)
        members = [dist, *sorted(closure)]
        paths = {p for n in members for p in m.dists[n].paths}
        row_paths[dist] = paths
        measured = sum(m.dists[n].actual_bytes for n in members)
        result.row_sum_bytes += measured
        verdict = "exempt" if row.unbounded else ("over" if measured > row.ceiling_bytes else "ok")
        ceiling = "UNBOUNDED" if row.unbounded else f"{row.marginal_mb} MB"
        result.table.append(
            f"  {verdict:<6} {dist:<24} ceiling {ceiling:>10}   measured {measured / MB:8.2f} MB"
            f"   (+{len(closure)} third-party)"
        )
        if verdict == "over":
            result.findings.append(
                f"{dist}: {measured / MB:.2f} MB measured against a {row.marginal_mb} MB ceiling. "
                f"Largest three files in the row: {'; '.join(_largest(m, members)) or 'none'}. "
                "Raising the ceiling requires a `why` line and a reviewer (section 4.3)."
            )

    bounded_paths = {p for d, ps in row_paths.items() if not rows[d].unbounded for p in ps}
    result.union_bytes = sum(p.stat().st_size for p in bounded_paths if p.is_file())

    listed = sum(d.actual_bytes for d in m.dists.values())
    unlisted_bytes = m.walk_bytes - m.pycache_bytes - listed
    if listed and unlisted_bytes / listed > DISCREPANCY:
        biggest = sorted(m.unlisted, key=lambda p: p.stat().st_size, reverse=True)[:5]
        sample = ", ".join(p.relative_to(m.site_packages).as_posix() for p in biggest)
        result.findings.append(
            f"the filesystem exceeds the RECORD manifest by {unlisted_bytes / MB:.2f} MB "
            f"({unlisted_bytes / listed:.1%} > {DISCREPANCY:.0%}). RECORD is a manifest, not a "
            f"filesystem (section 2.5 failure mode 3). Unlisted paths include: {sample}"
        )
    if m.pycache_bytes == 0:
        result.notes.append(
            "__pycache__ is empty: this environment was measured BEFORE first import, which "
            "understates a pure-Python distribution by roughly its source size (failure mode 4). "
            'Run `python -c "import omniweave"` first.'
        )


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def _say(text: str) -> None:
    """Write one line to stdout.

    `sys.stdout.write` rather than `print` because ruff's `T20` is selected repo-wide and
    `tools/*.py` carries no `per-file-ignores` row. `T20`'s premise — a library that prints cannot
    be quiet inside a hook with a 400 ms deadline (section 8.1) — does not hold for a gate whose
    output contract is a printed table; the correct fix is a `per-file-ignores` entry for
    `tools/*.py`, and this helper keeps the file green until one lands.
    """
    sys.stdout.write(f"{text}\n")


def _render(result: Result, *, measured: bool, aggregate_mb: int) -> None:
    _say("G2 gate_weights: tools/weights.toml (11-repo-layout.md section 2.5)")
    for note in result.notes:
        _say(f"  {note}")
    for line in result.table:
        _say(line)
    if measured:
        _say(
            f"  per-row sum        {result.row_sum_bytes / MB:8.2f} MB   "
            "(rows summed, duplicates counted twice)"
        )
        _say(
            f"  deduplicated union {result.union_bytes / MB:8.2f} MB   "
            f"against aggregate_mb = {aggregate_mb} MB"
        )
    else:
        _say("  per-row sum        not measured   (no --measure; declaration and arithmetic only)")
        _say("  deduplicated union not measured   (no --measure; declaration and arithmetic only)")
    for finding in result.findings:
        _say(f"  FAIL {finding}")
    _say("G2 PASS" if result.ok else "G2 FAIL")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gate_weights.py",
        description="G2: the fourteen weight ceilings of tools/weights.toml and the 250 MB union.",
    )
    parser.add_argument(
        "--repo", type=Path, default=REPO, help="workspace root (default: this checkout)"
    )
    parser.add_argument("--weights", type=Path, default=None, help="path to weights.toml")
    parser.add_argument(
        "--measure",
        type=Path,
        default=None,
        metavar="SITE_PACKAGES",
        help="measure this site-packages tree; without it, only the declaration is checked",
    )
    args = parser.parse_args(argv)

    repo: Path = args.repo.resolve()
    weights: Path = args.weights or (repo / "tools" / "weights.toml")
    schema, aggregate_mb, rows = load_weights(weights)
    result = check_declaration(repo, schema, aggregate_mb, rows)

    if args.measure is not None:
        m = measure(args.measure.resolve())
        _apply_measurement(result, m, rows)
        if result.union_bytes > aggregate_mb * MB:
            result.findings.append(
                f"the deduplicated union is {result.union_bytes / MB:.2f} MB against an "
                f"aggregate_mb of {aggregate_mb}. This is the one union number in the file "
                "(section 2.5) and the 250 MB promise of V10-2."
            )
    else:
        result.notes.append(
            f"no environment measured. G2's measured half runs in the `build` job over an offline "
            f"wheelhouse install (section 2.4); pass --measure <site-packages> to run it here. "
            f"aggregate_mb = {aggregate_mb} MB."
        )

    _render(result, measured=args.measure is not None, aggregate_mb=aggregate_mb)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
