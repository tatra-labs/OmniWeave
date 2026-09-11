"""Suite 10 of 12 -- `licence`: both graphs are scanned, and a violation fails rather than warns.

04-driver-system.md:2081: "the **resolved dependency graph and the import graph** are both scanned;
a violation **fails**, never warns". The defect is a specific package: **`cairosvg`, undeclared and
LGPL-3.0**.

Two graphs and not one, because each misses what the other catches. The **resolved dependency
graph** is what the author declared and a resolver pinned; it misses a package imported without
being declared, which is exactly `cairosvg`'s shape -- present in the environment for some other
reason, imported at runtime, listed nowhere. The **import graph** is what the code actually reaches
for; it misses a package pulled in transitively and never named in an `import` statement of the
driver's own. A scan of either alone has a hole the other one closes.

## The allowlist is `tools/licences.toml`, and it is not re-declared here

That file "governs what omniweave may depend on at BUILD time" and is read by G3 over three scans.
This suite reads the same `[allow]` table, because a second list would be a second policy and the
failure mode is a driver that passes the kit and fails the gate, or the reverse. What this suite
does NOT do is re-implement `compute_tier`: the driver's own licence facts are `[licence.code]`'s
and `omniweave_core.drivers.licence.tier_from_card` computes the tier from them. One home each.

## What "fails, never warns" costs, and why it is still right

An author whose driver depends on something outside the allowlist gets a failing mandatory suite
and no badge. That is severe, and DR18 is explicit that it should be: a warning in a build log is
a licence violation that ships. The assertion names the distribution and the licence, so the
author knows which dependency to replace rather than which log line to grep.

## Two scans, and the third one is a different check entirely

The row gives this suite exactly two: "the **resolved dependency graph and the import graph**
are both scanned". `tools/licences.toml`'s own header gives **G3** three -- "the resolved
dependency graph, the import graph, and the unpacked artifacts" -- and the third is a
repository-wide gate over built wheels, run by `tools/gate_licences.py` over omniweave's own
artefacts at build time.

They are not one check with two subjects. G3 asks what **omniweave** may depend on; this suite
asks what a **driver** depends on, and a driver's wheel is not omniweave's to build. An earlier
draft of this file asserted the artifact scan here and failed the mandatory tier for a driver
that had done nothing wrong: a gate's scope imported into a suite that was never given it.
Two scans is the row; two scans is what runs.

Specified in 04-driver-system.md section 8.2 row 10 and section 7; DR18, G3.
"""

from __future__ import annotations

import ast
import re
import sys
import time
import tomllib
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.licence import LicenceSeeds, tier_from_card
from omniweave_ports.types import LicenceTier

from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from omniweave_conform.subject import Subject

SUITE = "licence"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

_ALLOWLIST_NAME: Final = "licences.toml"
_STDLIB: Final = frozenset(sys.stdlib_module_names)

ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "psfl": "PSF-2.0",
        "psf": "PSF-2.0",
        "python software foundation license": "PSF-2.0",
        "apache software license": "Apache-2.0",
        "apache 2.0": "Apache-2.0",
        "apache-2": "Apache-2.0",
        "mit license": "MIT",
        "bsd license": "BSD-3-Clause",
        "the unlicense": "Unlicense",
    }
)
"""Spellings PyPI metadata actually uses, mapped to the SPDX ids `[allow] spdx` names.

**This widens no policy.** Every value is an identifier already on the allowlist; the keys are
the strings distributions write instead of it. `defusedxml` declares `PSFL` and the allowlist
names `PSF-2.0`; they are one licence with two spellings, and refusing the first would refuse
a licence the policy permits for a reason that is about typography.

**Why it is here and not in `tools/licences.toml`.** That file's `[allow]` is "VERBATIM from
14-security.md section 9.2" and is the POLICY. A spelling table is input normalisation, which
is the reader's job rather than the policy's. Ledger D9 already records that G3's own scan
trips on the same class of thing -- four permissive ids absent from the allowlist -- and the
resolution there is the user's, because it is a policy question. This one is not."""

_EXPRESSION_SPLIT: Final = re.compile(r"\s+OR\s+|\s+AND\s+|\s*[,;/]\s*", re.IGNORECASE)
_NOISE: Final = frozenset({"", "dependency licenses", "see license", "other/proprietary"})
"""Imported through a plain `import sys`, never `__import__("sys")`.

`tools/semgrep/omniweave.yaml`'s `omniweave-no-dunder-import-outside-host` bans
`__import__` across `packages/*/src/**` -- it is "`importlib.import_module` with the
module-name validation and the reviewer's attention removed". An earlier draft of this
line used it as a one-liner and `test_omniweave_conform_skeleton.py` caught it, which is
the AST check doing exactly the job the semgrep rule does at a different tier."""


def run(subject: Subject) -> SuiteResult:
    """The `licence` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731

    allow, allow_source = _allowlist(subject)
    checks = list(_card_assertions(subject))
    declared = _declared_dependencies(subject)
    imported = _imported_roots(subject)
    checks.extend(_graph_assertions(declared, imported, allow, allow_source))
    summary = (
        f"resolved graph {len(declared)} dists, import graph {len(imported)} roots, "
        f"tier={_tier(subject).value}"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _tier(subject: Subject) -> LicenceTier:
    return tier_from_card(subject.card, seeds=LicenceSeeds())


def _card_assertions(subject: Subject) -> Iterator[Assertion]:
    """The driver's own facts, and the tier core computes from them.

    `tier_from_card` is called rather than re-derived: 04 section 7.1 makes the tier "COMPUTED BY
    THE LOADER, NEVER SELF-REPORTED", and a kit that computed its own would be a second answer to
    a question the plan says has one.
    """
    facts = subject.card.licence_code
    yield Assertion(
        "[licence.code] declares an SPDX identifier",
        ok=bool(facts.spdx.strip()),
        detail="a driver with no declared licence is a driver an operator cannot clear",
        locus="card:spdx",
    )
    tier = _tier(subject)
    yield Assertion(
        "the computed licence tier is not forbidden",
        ok=tier is not LicenceTier.FORBIDDEN,
        detail=(
            "computed by omniweave_core.drivers.licence.tier_from_card from the card's own "
            "facts; a forbidden tier is a tombstoned licence hash or a redistribution bar"
        ),
        locus="card:tier",
        expected="open / restricted / commercial",
        actual=tier.value,
    )
    if subject.card.licence_weights is not None:
        yield Assertion(
            "[licence.weights] declares its own SPDX identifier",
            ok=bool(subject.card.licence_weights.spdx.strip()),
            detail="weights carry their own licence, and it is usually not the code's",
            locus="card:weights",
        )


def _allowlist(subject: Subject) -> tuple[frozenset[str], str]:
    """`tools/licences.toml`'s `[allow] spdx` list, and where it was found.

    Searched in three places, nearest first: up from the driver's distribution root, up from the
    card itself, and finally up from **this package**. The third is not a fallback of convenience.
    `tools/licences.toml`'s own header says it is "Shipped inside the wheel so `ow doctor
    --licences` can re-run it at runtime (14-security.md section 8.6)", so the kit carrying its own
    copy of the policy is the intended arrangement -- and it is what lets `ow conform` check a card
    that lives anywhere at all, which is every third-party card by definition.

    Returns an empty set and an empty source when nothing is found, and the graph assertions then
    report having had no policy to check against rather than reporting a pass.
    """
    here = Path(__file__).resolve()
    for start in (subject.dist_root, subject.card_path.parent, here.parent):
        if start is None:
            continue
        for parent in [start, *start.parents]:
            candidate = parent / "tools" / _ALLOWLIST_NAME
            if candidate.is_file():
                document = tomllib.loads(candidate.read_text(encoding="utf-8"))
                allow = document.get("allow")
                # `[allow]` is `spdx = [ ... ]`: a table with ONE key holding the identifier
                # list, not a table keyed by identifier. Reading the table keys would produce
                # an allowlist of exactly {"spdx"}, which no real licence matches and which
                # would fail every driver ever written. It did; this comment is the receipt.
                if isinstance(allow, dict) and isinstance(allow.get("spdx"), list):
                    return frozenset(str(x) for x in allow["spdx"]), str(candidate)
    return frozenset(), ""


def _declared_dependencies(subject: Subject) -> dict[str, str]:
    """The resolved dependency graph: every distribution the driver's `pyproject` names, resolved.

    Resolved through `importlib.metadata`, so what is reported is what is INSTALLED under that
    name -- which is the graph a runtime actually has, rather than the constraint string an author
    wrote. A dependency named and not installed is reported as such.
    """
    found: dict[str, str] = {}
    if subject.dist_root is None:
        return found
    pyproject = subject.dist_root / "pyproject.toml"
    if not pyproject.is_file():
        return found
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = document.get("project", {})
    requirements = project.get("dependencies", []) if isinstance(project, dict) else []
    for requirement in requirements:
        name = _dist_name(str(requirement))
        found[name] = _licence_of(name)
    return found


_NOT_INSTALLED: Final = "<not installed>"
"""What `_licence_of` answers for a name no distribution in this environment provides.

A constant rather than a repeated literal because two readers now compare against it: the one that
reports a declared-but-absent dependency, and `_licence_of_root`, which uses it to decide whether a
root resolved through `packages_distributions()` told it anything."""


def _dist_name(requirement: str) -> str:
    for separator in (" ", ">", "<", "=", "!", "~", "[", ";"):
        requirement = requirement.partition(separator)[0]
    return requirement.strip()


def _licence_of(distribution: str) -> str:
    """The `License-Expression`, `License`, or the first `License ::` classifier. `""` if absent."""
    try:
        meta = metadata.metadata(distribution)
    except metadata.PackageNotFoundError:
        return _NOT_INSTALLED
    for key in ("License-Expression", "License"):
        value = meta.get(key)
        if value and len(str(value)) < 200:  # noqa: PLR2004 -- a full licence TEXT, not an id.
            return str(value)
    for classifier in meta.get_all("Classifier") or ():
        if str(classifier).startswith("License ::"):
            return str(classifier).rpartition("::")[2].strip()
    return ""


def _imported_roots(subject: Subject) -> dict[str, str]:
    """The import graph: every top-level module the driver's own source imports.

    Read by parsing the source with `ast` rather than by importing anything. That is not a
    convenience -- importing to find imports is exactly the load-then-gate order INV-4 forbids, and
    `cairosvg` is a package whose import can have side effects.
    """
    roots: dict[str, str] = {}
    own = subject.import_root
    for path in subject.source_files():
        for name in _imports_in(path):
            root = name.split(".")[0]
            if root == own or root in _STDLIB or root in roots:
                continue
            roots[root] = _licence_of_root(root)
    return roots


def _licence_of_root(root: str) -> str:
    """The licence of whatever DISTRIBUTION installs this import root.

    An import root and a distribution name are different namespaces, and reading metadata under
    the import root is only right when they happen to coincide. `anydoc` is installed by
    `firecrawl-anydoc`, so the direct lookup answered `<not installed>` and reported a finding
    against a driver whose dependency is installed, pinned and MIT -- a bug in this reader, not a
    fact about the driver, and exactly the shape `_roots_of`'s own docstring already warns about
    for `pyyaml`/`yaml`.

    `packages_distributions()` is the authoritative mapping. A root with several distributions
    (namespace packages) contributes all of their licences joined, because every one of them is a
    thing the driver's import actually pulls in and the allowlist has to hold for each.
    """
    providers = metadata.packages_distributions().get(root, [])
    licences = [value for value in (_licence_of(name) for name in providers) if value]
    known = [value for value in licences if value != _NOT_INSTALLED]
    if known:
        return ", ".join(dict.fromkeys(known))
    return _licence_of(root)


def _terms(licence: str) -> list[str]:
    """Split a licence metadata value into the SPDX identifiers it actually names.

    A distribution's `License` or `License-Expression` is not one identifier. `pypdfium2`
    declares `BSD-3-Clause, Apache-2.0, dependency licenses`; an SPDX expression joins terms
    with `OR` and `AND`; classifiers arrive as prose. Comparing the whole string against a set
    of atoms fails every compound value, which is a bug in the reader rather than a finding
    about the driver -- and it reported one against `parse.pdf.pdfium` for two licences both
    of which the policy permits.

    Every term is required to be permitted, including under `OR`. That is stricter than SPDX
    semantics, where `A OR B` needs only one, and it is deliberate: a dual-licensed dependency
    whose other half is unacceptable is a dependency whose acceptability depends on a choice
    nobody recorded, and DR18 makes a violation a failure rather than a warning.
    """
    terms: list[str] = []
    for raw in _EXPRESSION_SPLIT.split(licence or ""):
        term = raw.strip().strip("()").strip()
        if term.lower() in _NOISE:
            continue
        terms.append(ALIASES.get(term.lower(), term))
    return terms


def _normalised(name: str) -> str:
    """PEP 503 normalisation plus the underscore form.

    So `omniweave-ports` and `omniweave_ports` compare equal. A distribution name and an
    import root are different namespaces and usually differ by exactly this character;
    comparing them raw reported the template driver's one declared dependency as undeclared.
    """
    return name.lower().replace("-", "_").replace(".", "_")


def _roots_of(declared: dict[str, str]) -> set[str]:
    """The import roots each declared distribution actually installs.

    `packages_distributions()` is the authoritative mapping and the only way to know that
    `pyyaml` installs `yaml`: no amount of string normalisation gets there. A distribution
    that is declared and not installed contributes nothing here and is covered by the
    normalised name instead, which is the best available answer for one nobody installed.
    """
    wanted = {_normalised(name) for name in declared}
    roots: set[str] = set()
    for root, dists in metadata.packages_distributions().items():
        if any(_normalised(dist) in wanted for dist in dists):
            roots.add(_normalised(root))
    return roots


def _imports_in(path: Path) -> Iterable[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ()
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _graph_assertions(
    declared: dict[str, str],
    imported: dict[str, str],
    permitted: frozenset[str],
    allow_source: str,
) -> Iterator[Assertion]:
    """Both graphs against the allowlist, and the two graphs against each other."""
    if not permitted:
        yield Assertion(
            "the allowlist was found, so there is a policy to check against",
            ok=False,
            detail=(
                f"no tools/{_ALLOWLIST_NAME} above the driver. DR18 makes a violation a failure "
                f"rather than a warning, and a scan with no policy is neither"
            ),
            locus="allowlist",
        )
        return
    yield Assertion(
        "the allowlist was found",
        ok=True,
        detail=f"{len(permitted)} identifiers from {allow_source}",
        locus="allowlist",
    )
    for graph, rows in (("resolved", declared), ("import", imported)):
        offenders = []
        for name, licence in sorted(rows.items()):
            unmatched = [term for term in _terms(licence) if term not in permitted]
            if licence and unmatched:
                offenders.append(f"{name} ({', '.join(unmatched)})")
        yield Assertion(
            f"every distribution in the {graph} graph carries an allowlisted licence",
            ok=not offenders,
            detail="; ".join(offenders[:4]) if offenders else f"{len(rows)} checked, all allowed",
            locus=f"scan:{graph}",
            expected="one of " + ", ".join(sorted(permitted)[:6]) + ", ...",
            actual="; ".join(offenders[:4]) or "none",
        )
    known = {_normalised(name) for name in declared} | _roots_of(declared)
    undeclared = sorted(root for root in imported if _normalised(root) not in known)
    yield Assertion(
        "nothing is imported that the dependency graph does not declare",
        ok=not undeclared,
        detail=(
            f"imported and undeclared: {', '.join(undeclared[:6])}. This is `cairosvg`'s exact "
            f"shape and the reason the row names two graphs rather than one"
            if undeclared
            else "the two graphs agree"
        ),
        locus="scan:agreement",
        expected="every imported root is a declared dependency",
        actual=", ".join(undeclared[:6]) or "none",
    )
