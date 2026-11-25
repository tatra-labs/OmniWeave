"""G-sbom: each of the six SBOMs is sanity-checked before anything signs it.

11-repo-layout.md section 7.3 rule 4 is the whole specification, and it names the threat rather
than a style: *"trivy is SHA-pinned and its output is sanity-checked before signing. Trivy can emit
a near-empty SBOM on a partial scan failure without a non-zero exit; signing that produces a
fraudulent SBOM carrying a legitimate Sigstore certificate."* A signature over an empty inventory
is worse than no signature, because it is believed.

A cap and a floor, and THE FLOOR HAS TWO ARMS OF WHICH EXACTLY ONE RUNS:

* **the cap** -- 2000, against runaway drift, and it runs over every document;
* **the floor, prior arm** -- 80% of the previous stable release's component count, PER FORMAT,
  because SPDX and CycloneDX disagree on virtual and metadata-only entries and one number for both
  would be a floor for neither;
* **the floor, no-prior arm** -- the install profile's declared direct dependency count. The rule
  carries the mined repository's *"hard floor of 50 when no prior SBOM is fetchable"* and says
  omniweave *"replaces the hard floor of 50"* with this count, so this is the arm that runs when
  there is no prior count to read -- which is every format and profile at 1.0.0. The rule states
  its reason: *"A floor of 50 on a two-dependency profile would either never fire or always fire,
  and neither is a check."*

Section 7.1's row gives the six: SPDX-JSON and CycloneDX-JSON, one pair per install profile, the
profiles being `minimum`, `recommended` and `all-minus-vision`.

## Rulings

1. **The floor is one bound with two arms, not two bounds.** Rule 4's floor is 80% of the prior
   count "with a hard floor of 50 when no prior SBOM is fetchable", and omniweave "replaces the
   hard floor of 50" with the declared direct dependency count. So the direct-dependency count is
   the FALLBACK, and running it alongside the 80% arm would be inventing a bound rule 4 does not
   state. Whichever arm has an input runs; the other is reported as the arm that did not apply.
   At 1.0.0 the prior arm has no input for any of the six, so the no-prior arm is the whole floor.

2. **"The install profile's declared direct dependency count" is read as the distinct THIRD-PARTY
   requirements of the profile's first-party closure** -- 2 for `minimum`, 10 for `recommended`,
   12 for `all-minus-vision`, measured 2026-11-24. Rule 4 fixes the first of these at 2 and that
   agrees, but by a different derivation: the rule's own parenthetical reads 2 as "the `minimum`
   profile's core (itself plus `omniweave-ports`)", which counts first-party distributions over the
   core alone. That derivation does not generalise -- section 2.3's `minimum` profile is four
   distributions rather than two, and "the core and ports" names no quantity for the other two
   profiles -- so the generalising reading is taken here. The agreement at 2 is a coincidence of
   this repository's dependency shape and is recorded as one, so that a reader who re-derives it
   from the parenthetical and gets a different number for `recommended` knows which way was taken.
   D1035 carries both this and ruling 3 into the plan.

3. **Section 7.1's `all-minus-vision` is section 2.3's CI row, and the mapping is written here
   because nothing else writes it.** Section 7.1 names three profiles; section 2.3's table has six
   rows and `tools/gate_weights.py`'s `PROFILES` has five, and `all-minus-vision` is in neither
   list. It is section 2.3's CI row -- "all 14 except vision" -- which is exactly
   `gate_weights.profile_roots(repo, "ci")`.

4. **The arm that did not apply is reported, never passed over in silence.** Section 6.8 refuses a
   check that cannot fail, so the report names the cap, names which arm of the floor ran with the
   number it ran at, and prints the other as `did not apply` with its reason. A reader of the step
   summary can tell a two-bound pass from a three-bound one, which at 1.0.0 is the difference
   between what this check actually proved and what its name suggests.

5. **The baseline is written by a release, not by a developer.** `--write-baseline` records the
   counts a release actually published into `tools/sbom_baseline.toml`, which is what moves the
   floor onto its prior arm from 1.0.1 onward. Hand-editing it would set the floor to whatever
   passes, which is the same defeat as not having it.

6. **The requirement-name normaliser has one home.** `gate_weights` already owns it, and INV-21
   forbids a second: a profile whose names normalise differently in two tools is a profile two
   gates disagree about. That is why this module imports it rather than carrying the regex.

## Exit codes

`0` every bound that could run, ran and held. `1` a bound was violated -- the SBOM is not fit to
sign. `2` the check did not run: a bad argument, an unknown profile or format, or a document whose
component array is absent rather than empty, which is a malformed SBOM and not a small one.

Specified in 11-repo-layout.md section 7.3 rule 4 and section 7.1, and D1035.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_weights  # same directory as this module, and ruling 6 is why it is imported

__all__ = [
    "BASELINE",
    "CAP",
    "FORMATS",
    "PREVIOUS_FRACTION",
    "PROFILES",
    "Result",
    "check",
    "component_count",
    "direct_dependency_floor",
    "load_baseline",
    "main",
]

REPO: Final = Path(__file__).resolve().parents[1]

FORMATS: Final[tuple[str, ...]] = ("spdx", "cyclonedx")
"""Section 7.1's two formats. The count is read from a different key in each, which is the whole
reason rule 4's floor is per format."""

PROFILES: Final[tuple[str, ...]] = ("minimum", "recommended", "all-minus-vision")
"""Section 7.1's three install profiles, spelled as section 7.1 spells them."""

_WEIGHTS_PROFILE: Final[Mapping[str, str]] = {
    "minimum": "minimum",
    "recommended": "recommended",
    "all-minus-vision": "ci",
}
"""Ruling 2: section 7.1's names against `gate_weights.PROFILES`'. Only the third differs."""

_COMPONENT_KEY: Final[Mapping[str, str]] = {"spdx": "packages", "cyclonedx": "components"}

CAP: Final = 2000
"""Rule 4's cap against runaway drift."""

PREVIOUS_FRACTION: Final = 0.8
"""Rule 4's floor, as a fraction of the previous stable release's count for the same format."""

BASELINE: Final = REPO / "tools" / "sbom_baseline.toml"


@dataclass(frozen=True)
class Result:
    """What the check found. `findings` empty is the only pass."""

    report: tuple[str, ...]
    findings: tuple[str, ...]


def component_count(document: Mapping[str, object], fmt: str) -> int:
    """The component count of one SBOM, read from the key its format uses.

    An absent array is not an empty one: trivy writing no `packages` key at all is a malformed
    document, so this raises rather than returning 0, and the caller turns that into exit 2.
    """
    if fmt not in _COMPONENT_KEY:
        raise ValueError(f"unknown format {fmt!r}, expected one of {', '.join(FORMATS)}")
    key = _COMPONENT_KEY[fmt]
    value = document.get(key)
    if value is None:
        raise ValueError(f"{fmt} document has no {key!r} array; it is malformed, not empty")
    if not isinstance(value, list):
        raise TypeError(f"{fmt} document's {key!r} is {type(value).__name__}, not a list")
    return len(value)


def direct_dependency_floor(repo: Path, profile: str) -> int:
    """Ruling 1's floor: distinct third-party requirements across the profile's first-party closure.

    `gate_weights.profile_roots` owns what a profile installs, including the CI row's "all 14
    except vision"; this function only partitions that closure's requirements into first-party and
    not, and counts the second half.
    """
    if profile not in _WEIGHTS_PROFILE:
        raise ValueError(f"unknown profile {profile!r}, expected one of {', '.join(PROFILES)}")
    roots = gate_weights.profile_roots(repo, _WEIGHTS_PROFILE[profile])
    first_party = {path.parent.name for path in repo.glob("packages/*/pyproject.toml")}
    third_party: set[str] = set()
    for dist in sorted(roots):
        pyproject = repo / "packages" / dist / "pyproject.toml"
        if not pyproject.exists():
            continue
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for requirement in data.get("project", {}).get("dependencies", []) or []:
            name = gate_weights._requirement_name(requirement)
            if name and name not in first_party:
                third_party.add(name)
    return len(third_party)


def load_baseline(path: Path) -> dict[tuple[str, str], int]:
    """The previous stable release's counts, keyed by (format, profile).

    A missing file is not an error: before the first release there is no previous release, and
    ruling 3 says that case is reported rather than invented.
    """
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    counts: dict[tuple[str, str], int] = {}
    components = data.get("components", {})
    if not isinstance(components, dict):
        return counts
    for fmt, profiles in components.items():
        if not isinstance(profiles, dict):
            continue
        for profile, count in profiles.items():
            if isinstance(count, int):
                counts[(fmt, profile)] = count
    return counts


def check(
    *,
    document: Mapping[str, object],
    fmt: str,
    profile: str,
    repo: Path = REPO,
    baseline: Mapping[tuple[str, str], int] | None = None,
) -> Result:
    """Rule 4's cap and its two-armed floor over one SBOM. `findings` empty is the only pass."""
    counts: Mapping[tuple[str, str], int] = {} if baseline is None else baseline
    count = component_count(document, fmt)
    previous = counts.get((fmt, profile))

    report = [f"{fmt}/{profile}  {count} component(s)"]
    findings: list[str] = []

    report.append(f"  cap                  {CAP}  ran")
    if count > CAP:
        findings.append(
            f"{fmt}/{profile}: {count} component(s) exceeds the cap of {CAP}; rule 4 calls this "
            f"runaway drift and refuses to sign it unsupervised"
        )

    if previous is None:
        floor = direct_dependency_floor(repo, profile)
        report.append(
            f"  floor, no-prior arm  {floor}  ran  the profile's declared direct dependency count"
        )
        report.append(
            "  floor, prior arm     did not apply  no baseline row for this format and profile, "
            "so there is no previous stable release to read a count from (ruling 4)"
        )
        if count < floor:
            findings.append(
                f"{fmt}/{profile}: {count} component(s) is below the profile's own {floor} "
                f"declared third-party dependenc(ies); a scan that found fewer components than "
                f"the profile declares did not scan the profile"
            )
    else:
        bound = int(previous * PREVIOUS_FRACTION)
        report.append(
            f"  floor, prior arm     {bound}  ran  "
            f"{PREVIOUS_FRACTION:.0%} of the previous release's {previous}"
        )
        report.append(
            "  floor, no-prior arm  did not apply  rule 4 makes the declared direct dependency "
            "count the fallback for a missing prior count, and a prior count was read (ruling 1)"
        )
        if count < bound:
            findings.append(
                f"{fmt}/{profile}: {count} component(s) is below {bound}, which is "
                f"{PREVIOUS_FRACTION:.0%} of the previous release's {previous}; a drop that large "
                f"is a partial scan until proven otherwise"
            )

    return Result(report=tuple(report), findings=tuple(findings))


def _render_baseline(rows: Mapping[tuple[str, str], int]) -> str:
    lines = [
        "# The component count of each SBOM the last stable release actually published.",
        "#",
        "# Written by `tools/check_sbom.py --write-baseline`, never by hand: ruling 5 in that",
        "# module says a hand-edited baseline sets the floor to whatever passes, which is the same",
        "# defeat as having no floor at all. 11-repo-layout.md section 7.3 rule 4 owns the 80% it",
        "# is read at, and section 7.1 owns the six rows this file can hold.",
        "",
    ]
    for fmt in FORMATS:
        present = {p: c for (f, p), c in sorted(rows.items()) if f == fmt}
        if not present:
            continue
        lines.append(f"[components.{fmt}]")
        for profile in PROFILES:
            if profile in present:
                lines.append(f'"{profile}" = {present[profile]}')
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G-sbom: sanity-check one SBOM before it is signed (section 7.3 rule 4).",
    )
    parser.add_argument("--sbom", type=Path, required=True, help="the SBOM JSON to check")
    parser.add_argument("--format", dest="fmt", choices=FORMATS, required=True)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record this SBOM's count into the baseline; ruling 4, a release does this",
    )
    args = parser.parse_args(argv)

    try:
        document = json.loads(args.sbom.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.stderr.write(f"G-sbom did not run: {args.sbom} does not exist\n")
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"G-sbom did not run: {args.sbom} is not JSON: {exc}\n")
        return 2
    if not isinstance(document, dict):
        sys.stderr.write(f"G-sbom did not run: {args.sbom} is not a JSON object\n")
        return 2

    try:
        result = check(
            document=document,
            fmt=args.fmt,
            profile=args.profile,
            repo=args.repo,
            baseline=load_baseline(args.baseline),
        )
    except ValueError as exc:
        sys.stderr.write(f"G-sbom did not run: {exc}\n")
        return 2

    for line in result.report:
        sys.stdout.write(line + "\n")
    if result.findings:
        for finding in result.findings:
            sys.stderr.write(f"G-sbom FAILED: {finding}\n")
        return 1

    if args.write_baseline:
        rows = dict(load_baseline(args.baseline))
        rows[(args.fmt, args.profile)] = component_count(document, args.fmt)
        args.baseline.write_text(_render_baseline(rows), encoding="utf-8")
        sys.stdout.write(f"  baseline updated: {args.baseline}\n")

    sys.stdout.write("G-sbom ok  0 finding(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
