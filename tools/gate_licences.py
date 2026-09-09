"""G3 — the build-time licence gate, over three surfaces rather than one.

`tools/licences.toml` is the policy; this is its only reader. The roadmap's P1 exit line is
`uv run tools/gate_licences.py  # G3: resolved graph + import graph + artifacts`
(16-roadmap.md section 4), and the three names in that comment are the whole point: layer 2 of
11-repo-layout.md section 9.2 requires **the resolved graph, the import graph and the unpacked
artefacts**, and gives the proof that any one of them alone is insufficient — `cairosvg` is
LGPL-3.0, is imported at `ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_package/media.py:15`
and is **absent from `ppt-master/requirements.txt`**, so it is invisible to every manifest-based
SBOM (DR18, restated at 04-driver-system.md section 7.4). A gate that scanned only manifests would
have passed the single worst licence defect in the mined collection.

**This is not `compute_tier` and it is not `drivers/licence.py`.** 04-driver-system.md section 7.4
says so in the plan's own words — "Build-time licence policy is a *different* mechanism with a
different owner and is not this report". `compute_tier` (P3 W3.3) reads a driver card's
`[licence.code]` and `[licence.weights]` at **resolve** time and returns a `LicenceTier` checked
against `[licence] allow_tiers`; this gate reads omniweave's **own dependency graph** at **build**
time and returns an exit code. They share a vocabulary and no code. The one place the two touch is
R-L1's detector, which is written over both: `licence.tombstone_hits > 0` **or** any G3 hit on
`marker-pdf`, `surya-ocr`, `texify` or `lift` — which is why those four are `[deny] name` rows.

**What each surface can and cannot see.**

1. `resolved_graph()` walks `uv.lock` — the resolution itself, not a manifest — from the fourteen
   workspace members (runtime scope) and from the workspace root's `[dependency-groups] dev` (dev
   scope). Licence evidence comes from `importlib.metadata` over the **installed** tree, because
   `uv.lock` records hashes and versions and carries no licence field at all. A lock package whose
   every inbound path crosses an environment marker or an extra is `conditional`: it is in the
   graph and is name-checked, but this platform's environment cannot supply its metadata, so it is
   reported and not failed. A package reachable by an **unconditional** path that is nevertheless
   absent from the environment fails loudly — that is an unsynced venv, and a gate that cannot see
   the graph must say so rather than pass.
2. `import_graph()` parses every first-party `.py` under `packages/` with `ast` and resolves each
   import root against stdlib, first-party, a sibling file, and `packages_distributions()`. A root
   that maps to no installed distribution, or to one outside the closure for that file's scope, is
   the `cairosvg` shape and fails.
3. `unpacked_artifacts()` reads the licence **texts** in each installed distribution's unpacked
   tree, because 14-security.md section 9.2 rules that "`SPDX-License-Identifier` metadata is a
   claim, not a licence" and that where a distribution's declared SPDX and its bundled `LICENSE`
   files disagree the gate "takes the **more restrictive** of the two and names both". Its bounded
   default reads only each distribution's **primary** licence files (its `License-File` metadata,
   or its `.dist-info` licence files when that is absent); `--deep` additionally classifies every
   bundled notice, which over this environment's seventeen thousand licence files costs about
   ninety seconds cold and under a second warm.

**Severity and exit code.** `deny` is a licence blocker and exits 1. `unreviewed` is a licence in
the graph that is neither on `[allow] spdx` nor waived by an `[exception.<name>]`, and exits 2 —
14-security.md section 9 says "**A row marked `VERIFY` is a task, not a claim**", and a gate that
could not tell a blocker from an unfinished register row would teach its readers to ignore both.
`notice` never changes the exit code: it carries the enumeration 14-security.md section 9.4 asks
for (pypdfium2's bundled FreeType / libjpeg-turbo / lcms2 / zlib / libopenjpeg set) and the
per-distribution bundled-artefact counts, whose FAILING register is `tools/vendor.toml` under G12
and `THIRD_PARTY.md`, not this gate.

Stdlib only, and `tomllib` is the TOML reader (D1/G1). Output goes through `_emit` to
`sys.stdout` rather than `print`, which the repo bans under ruff `T20`.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import re
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import Distribution, distributions, packages_distributions
from pathlib import Path

__all__ = [
    "DENY",
    "EXCEPTION_KEYS",
    "EXIT_BLOCKED",
    "EXIT_CLEAN",
    "EXIT_UNREVIEWED",
    "NOTICE",
    "SCOPES",
    "UNREVIEWED",
    "Evidence",
    "Finding",
    "Policy",
    "Resolved",
    "Waiver",
    "classify_licence_text",
    "denied_reason",
    "expression_alternatives",
    "import_graph",
    "load_policy",
    "main",
    "pep503",
    "resolved_graph",
    "spdx_evidence",
    "unpacked_artifacts",
]

REPO = Path(__file__).resolve().parents[1]
"""The workspace root. `tools/` sits directly under it, so one `parents` hop, never a search."""

LOCK = REPO / "uv.lock"
POLICY = REPO / "tools" / "licences.toml"

DENY = "deny"
UNREVIEWED = "unreviewed"
NOTICE = "notice"

EXIT_CLEAN = 0
EXIT_BLOCKED = 1
EXIT_UNREVIEWED = 2

SCOPES = ("dev", "bench", "test", "runtime")
"""The four `[exception.<name>] scope` values, verbatim from 14-security.md section 9.2's comment.

`bench` has no graph of its own at release 1 — there is no bench dependency group — so a `bench`
exception is accepted and reported as matching nothing. The vocabulary is fixed here because an
exception whose scope is a typo would otherwise waive nothing while looking like a waiver.
"""

EXCEPTION_KEYS = frozenset({"approver", "reason", "review_by", "scope", "spdx"})
"""ALL FIVE KEYS REQUIRED; a missing key fails the gate (14-security.md section 9.2).

An **unknown** key fails too. The plan does not say so, and it follows: a misspelled `reviewby`
already fails as a missing `review_by`, so rejecting the extra key only changes the message from
"a key is missing" to "and here is the typo that lost it".
"""

PLACEHOLDER_APPROVERS = frozenset({"", "name@example.com"})
"""Values the `approver` field may not hold when `scope = "runtime"`.

14-security.md section 9.2 attaches "`runtime` additionally requires a named approver" to the
`scope` line while also requiring all five keys always. Both readings are honoured: every scope
needs the key, and `runtime` needs it to name someone rather than the plan's own template address.
"""

MIN_LICENCE_TEXT_BYTES = 200
"""Below this, a `License:` metadata field is a name, not a grant, and is not classified as one.

`tiktoken` puts its whole MIT text in that field, which no normalisation table can ever hold; a
field this long is a licence to read rather than a spelling to look up. Two hundred bytes is under
the shortest full grant in `TEXT_MARKERS` (0BSD-shaped ISC is ~700) and far above every prose
spelling in `[normalise]`, so the two paths cannot both claim the same value.
"""

MAX_LICENCE_BYTES = 400_000
"""Ceiling on a licence file this gate will read.

torch's unpacked tree carries 95 `License-File` entries and pyright's carries five thousand more
files; a licence text above this size is an aggregated notice bundle, not a grant, and reading it
buys nothing the `--deep` enumeration does not already report by path.
"""

LICENCE_FILENAME = re.compile(r"(^|/)(licen[cs]e|copying|notice)", re.IGNORECASE)
"""Matches a licence-bearing filename anywhere in a tree, on the posix form of the path."""

BINARY_SUFFIXES = frozenset({".dll", ".dylib", ".exe", ".pyd", ".so"})
"""Extensions that make a file a redistributed binary artefact.

`ffmpeg-static` and `pypandoc-binary` are two of 14-security.md section 9.2's five named hazards
and neither is visible as an import or as an SPDX string: what they are is a GPL binary inside a
wheel. Counting them per distribution is what makes that shape reportable at all.
"""

_WITH = re.compile(r"\s+WITH\s+.+$")
_OR = re.compile(r"\s+OR\s+")
_AND = re.compile(r"\s+AND\s+")
_SPDX_SHAPED = re.compile(r"^[A-Za-z0-9.+\-]+(?:\s+(?:AND|OR|WITH)\s+[A-Za-z0-9.+\-]+)*$")

TEXT_MARKERS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("AGPL-3.0", ("gnu affero general public license", "version 3, 19 november 2007"), ()),
    ("LGPL-3.0", ("gnu lesser general public license", "version 3, 29 june 2007"), ()),
    ("LGPL-2.1", ("gnu lesser general public license", "version 2.1, february 1999"), ()),
    (
        "GPL-3.0",
        ("gnu general public license", "version 3, 29 june 2007"),
        ("version 3, 19 november 2007",),
    ),
    (
        "GPL-2.0",
        (
            "gnu general public license",
            "version 2, june 1991",
            "terms and conditions for copying, distribution and modification",
        ),
        (),
    ),
    ("SSPL-1.0", ("server side public license",), ()),
    ("BUSL-1.1", ("business source license",), ()),
    ("Commons-Clause", ("commons clause",), ()),
    ("Elastic-2.0", ("elastic license 2.0",), ()),
    ("CC-BY-NC-4.0", ("creative commons", "noncommercial"), ()),
    ("CC-BY-SA-4.0", ("creative commons", "sharealike"), ()),
    ("LicenseRef-AIPubs-OpenRAIL", ("openrail",), ()),
    ("LicenseRef-Tencent-Hunyuan", ("tencent hunyuan",), ()),
    ("MIT", ("permission is hereby granted, free of charge",), ()),
    ("BSD-3-Clause", ("redistributions of source code must retain", "neither the name of"), ()),
    ("BSD-2-Clause", ("redistributions of source code must retain",), ("neither the name of",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software",), ()),
    ("Apache-2.0", ("apache license", "version 2.0, january 2004"), ()),
    ("MPL-2.0", ("mozilla public license version 2.0",), ()),
    ("PSF-2.0", ("psf license agreement",), ()),
)
"""Which licence FAMILY a text is, by phrases that appear in the grant and nowhere else.

Every requirement is a phrase from the licence body, never its name, because a name is what a
*mention* looks like: `typing_extensions`' PSF text recites "the GNU General Public License (GPL)"
in its CNRI history and Pillow's `LICENSE` lists a bundled file called `copying.lgplv2.1`. Both
matched a name-only detector and neither is copyleft. The version datelines
("version 3, 29 june 2007") and GPL-2's section header are what separate a grant from a citation.

The permissive families at the tail are not decoration. They are what makes a **mixed** text
distinguishable from a copyleft one, which is the difference between numpy — whose primary
`LICENSE.txt` is a 45 KB aggregate carrying BSD-3 plus the GPL-3 text of the gfortran runtime its
Windows wheel bundles — and omniparse, whose `LICENSE` is GPL-3.0 alone while its
`pyproject.toml:7` claims "Apache" (14-security.md section 9.1). The first is a notice; the second
is a blocker.

Only ONE forbidden phrase survives, and it earns its place: the GPL-3 text itself carries "GNU
Affero General Public License" in its section 13 heading, so guarding GPL-3.0 against that phrase —
the obvious first draft, and the one that shipped for an hour — made the detector unable to fire on
any genuine GPL-3 file at all. The datelines separate the family cleanly instead: 19 November 2007
is AGPL-3's alone. What remains is deliberate over-detection between GPL-3.0 and LGPL-3.0, whose
text recites the GPL's title throughout; both are `[deny]` rows, so the verdict is identical and
only the label is coarse.

The residual is named rather than hidden: a text listing many licences in which one component is
pure copyleft reads as mixed and is downgraded to a notice here. Failing on that is G12's job over
`tools/vendor.toml` and the generated `THIRD_PARTY.md`, not this gate's.
"""


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing the gate saw. `severity` is `deny`, `unreviewed` or `notice` (module docstring)."""

    surface: str
    severity: str
    subject: str
    detail: str


@dataclass(frozen=True, slots=True)
class Waiver:
    """One `[exception.<name>]` table, validated. `review_by` is a date: CI fails a stale one."""

    name: str
    spdx: str
    reason: str
    scope: str
    review_by: dt.date
    approver: str


@dataclass(frozen=True, slots=True)
class Policy:
    """`tools/licences.toml`, parsed. The single in-memory home of the build-time licence policy."""

    allow: frozenset[str]
    deny_spdx: tuple[str, ...]
    deny_prefix: tuple[str, ...]
    deny_name: frozenset[str]
    deny_module: frozenset[str]
    normalise: dict[str, tuple[str, ...]]
    classifier: dict[str, tuple[str, ...]]
    waivers: dict[str, Waiver]


@dataclass(frozen=True, slots=True)
class Resolved:
    """A lock-closure package. `conditional`: every inbound path crosses a marker or extra."""

    name: str
    version: str
    scopes: frozenset[str]
    conditional: bool


@dataclass(frozen=True, slots=True)
class Evidence:
    """What this gate knows about a distribution's licence, and how strongly.

    `alternatives` is the SPDX expression in disjunctive normal form: the distribution clears if
    **any** alternative's ids all clear. That is what `OR` means in an SPDX expression — a choice
    the redistributor makes — and reading `Apache-2.0 OR BSD-3-Clause` as a conjunction would fail
    `cryptography` over a licence it also grants permissively.
    """

    alternatives: tuple[frozenset[str], ...]
    kind: str
    raw: str


def _emit(line: str) -> None:
    """The gate's one write. `print` is banned repo-wide by ruff `T20`; this needs no waiver."""
    sys.stdout.write(line + "\n")


def pep503(name: str) -> str:
    """Normalise a distribution name per PEP 503, so `PyMuPDF` and `py_mu_pdf` are one entry."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _canon_id(token: str) -> str:
    """One SPDX id: `WITH <exception>` dropped, a trailing `+` spelled `-or-later`.

    A `WITH` clause only ADDS permissions (torch declares `Apache-2.0 WITH LLVM-exception`), so the
    licence the policy must judge is the id in front of it. The `+` form is the legacy spelling of
    `-or-later` and the denylist is written in the modern one.
    """
    tok = _WITH.sub("", token.strip().strip("()")).strip()
    return tok[:-1] + "-or-later" if tok.endswith("+") else tok


def expression_alternatives(expr: str) -> tuple[frozenset[str], ...]:
    """A flat SPDX expression as disjunctive normal form.

    A parenthesised expression is read CONSERVATIVELY as one alternative requiring every id in it,
    because a wrong `OR` grouping would grant permission the expression does not. No distribution
    in the release-1 lock uses parentheses; the branch exists so that the first one that does fails
    safe rather than silently.
    """
    if "(" in expr or ")" in expr:
        flat = _AND.split(_OR.sub(" AND ", expr.replace("(", " ").replace(")", " ")))
        return (frozenset(_canon_id(t) for t in flat if t.strip()),)
    alternatives = []
    for branch in _OR.split(expr):
        ids = frozenset(_canon_id(t) for t in _AND.split(branch) if t.strip())
        if ids:
            alternatives.append(ids)
    return tuple(alternatives)


def classify_licence_text(text: str) -> frozenset[str]:
    """Every licence family `TEXT_MARKERS` can prove is present in `text`. Case-insensitive."""
    lowered = text.lower()
    return frozenset(
        spdx
        for spdx, required, forbidden in TEXT_MARKERS
        if all(phrase in lowered for phrase in required)
        and not any(phrase in lowered for phrase in forbidden)
    )


def denied_reason(spdx_id: str, policy: Policy) -> str | None:
    """The `[deny]` row this id trips, or `None`.

    Matching is family-wise in both directions: a declared bare `GPL-3.0` trips `GPL-3.0-only`, and
    `CC-BY` trips `CC-BY-NC-4.0`. 11-repo-layout.md section 9.4 item 1 names that second case
    exactly — "use version-specific CC-BY entries so `CC-BY-NC` and `CC-BY-SA` cannot match" — and
    a bare-prefix comparison is the only reading under which a bare `CC-BY` is not a way past both.
    """
    lowered = spdx_id.lower()
    for denied in policy.deny_spdx:
        low = denied.lower()
        if lowered == low or low.startswith(lowered + "-") or lowered.startswith(low + "-"):
            return denied
    for prefix in policy.deny_prefix:
        if lowered.startswith(prefix.lower()):
            return prefix
    return None


def _waiver_from(name: str, table: dict[str, object]) -> Waiver:
    """Validate one `[exception.<name>]` table into a `Waiver`, or raise `ValueError` naming why."""
    keys = set(table)
    if keys != EXCEPTION_KEYS:
        missing = sorted(EXCEPTION_KEYS - keys)
        unknown = sorted(keys - EXCEPTION_KEYS)
        raise ValueError(f"[exception.{name}] missing={missing} unknown={unknown}")
    scope = str(table["scope"])
    if scope not in SCOPES:
        raise ValueError(f"[exception.{name}] scope={scope!r} is not one of {list(SCOPES)}")
    approver = str(table["approver"]).strip()
    if scope == "runtime" and approver in PLACEHOLDER_APPROVERS:
        raise ValueError(
            f"[exception.{name}] scope=runtime needs a named approver, got {approver!r}"
        )
    if not str(table["reason"]).strip():
        raise ValueError(f"[exception.{name}] reason is empty")
    return Waiver(
        name=pep503(name),
        spdx=str(table["spdx"]),
        reason=str(table["reason"]),
        scope=scope,
        review_by=dt.date.fromisoformat(str(table["review_by"])),
        approver=approver,
    )


def load_policy(path: Path = POLICY) -> Policy:
    """Read and validate `tools/licences.toml`. Raises `ValueError` on a bad exception table."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    allow = raw.get("allow", {})
    deny = raw.get("deny", {})
    return Policy(
        allow=frozenset(s.lower() for s in allow.get("spdx", ())),
        deny_spdx=tuple(deny.get("spdx", ())),
        deny_prefix=tuple(deny.get("prefix", ())),
        deny_name=frozenset(pep503(n) for n in deny.get("name", ())),
        deny_module=frozenset(deny.get("module", ())),
        normalise={k.strip().lower(): tuple(v) for k, v in raw.get("normalise", {}).items()},
        classifier={k: tuple(v) for k, v in raw.get("classifier", {}).items()},
        waivers={
            pep503(name): _waiver_from(name, table)
            for name, table in raw.get("exception", {}).items()
        },
    )


def _lock_edges(package: dict[str, object]) -> list[tuple[str, bool]]:
    """`(dependency name, crosses a condition)` for one lock package.

    An `[package.optional-dependencies]` edge is conditional unconditionally: an extra materialises
    only when someone asks for it, and `omniweave-core[sqlite]` -> `pysqlite3-binary` is in the lock
    of every environment that has never installed it.
    """
    edges = [(e["name"], "marker" in e) for e in package.get("dependencies", ())]
    for entries in package.get("optional-dependencies", {}).values():
        edges.extend((e["name"], True) for e in entries)
    return edges


def _walk(packages: dict[str, dict], roots: list[tuple[str, bool]]) -> dict[str, bool]:
    """Reachability with least-conditional wins: `False` (unconditional) beats `True` and stops."""
    best: dict[str, bool] = {}
    queue = list(roots)
    while queue:
        name, conditional = queue.pop()
        if name in best and (best[name] is False or best[name] == conditional):
            continue
        best[name] = conditional
        for dep, crosses in _lock_edges(packages.get(name, {})):
            queue.append((dep, conditional or crosses))
    return best


def resolved_graph(lock_path: Path = LOCK) -> dict[str, Resolved]:
    """Surface 1's graph: `uv.lock` closed over the fourteen members and the workspace dev group.

    The workspace root (`omniweave-monorepo`, `source = { virtual = "." }`) is excluded from the
    runtime roots and supplies only the dev roots: it is never published and holds no code
    (11-repo-layout.md section 1.1), so treating it as a runtime root would put `ruff` and `pyright`
    in the shipped graph.
    """
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = {p["name"]: p for p in lock["package"]}
    root_name = "omniweave-monorepo"
    members = [m for m in lock["manifest"]["members"] if m != root_name]
    runtime = _walk(packages, [(m, False) for m in members])
    dev_roots = [
        (e["name"], "marker" in e)
        for entries in packages[root_name].get("dev-dependencies", {}).values()
        for e in entries
    ]
    dev = _walk(packages, dev_roots)
    graph: dict[str, Resolved] = {}
    for name in set(runtime) | set(dev):
        scopes = {s for s, seen in (("runtime", runtime), ("dev", dev)) if name in seen}
        conditional = all(seen[name] for seen in (runtime, dev) if name in seen)
        graph[pep503(name)] = Resolved(
            name=name,
            version=str(packages.get(name, {}).get("version", "?")),
            scopes=frozenset(scopes),
            conditional=conditional,
        )
    return graph


def _installed() -> dict[str, Distribution]:
    """Every installed distribution, keyed PEP-503. Later duplicates lose, per `sys.path` order."""
    found: dict[str, Distribution] = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name and pep503(name) not in found:
            found[pep503(name)] = dist
    return found


def _license_field(dist: Distribution) -> str:
    return (dist.metadata.get("License") or "").strip()


def spdx_evidence(dist: Distribution, policy: Policy) -> Evidence:
    """The strongest licence evidence available for one installed distribution.

    Order: PEP 639 `License-Expression` (an SPDX expression, and authoritative), then a `License:`
    field that is either a known prose spelling or itself SPDX-shaped over ids the policy already
    knows, then a `License:` field holding a whole licence TEXT (`tiktoken` ships the MIT text
    there), then a trove classifier. A distribution reaching the end has evidence kind `none`, and
    14-security.md section 9.2's rule for that is not silence: "a denylist misses `UNKNOWN`".
    """
    expression = dist.metadata.get("License-Expression")
    if expression:
        return Evidence(expression_alternatives(expression), "expression", expression)
    field = _license_field(dist)
    mapped = policy.normalise.get(field.lower())
    if mapped:
        return Evidence((frozenset(mapped),), "normalised", field)
    if field and "\n" not in field and _SPDX_SHAPED.match(field):
        alternatives = expression_alternatives(field)
        known = policy.allow | {d.lower() for d in policy.deny_spdx}
        if alternatives and all(i.lower() in known for a in alternatives for i in a):
            return Evidence(alternatives, "expression", field)
    if len(field) >= MIN_LICENCE_TEXT_BYTES:
        families = classify_licence_text(field)
        if len(families) == 1:
            return Evidence((families,), "text", next(iter(families)))
    classifiers = [c for c in (dist.metadata.get_all("Classifier") or ()) if c in policy.classifier]
    if classifiers:
        ids = frozenset(i for c in classifiers for i in policy.classifier[c])
        return Evidence((ids,), "classifier", "; ".join(classifiers))
    return Evidence((), "none", field[:60])


def _judge(key: str, subject: str, evidence: Evidence, policy: Policy) -> list[Finding]:
    """Turn one distribution's evidence into findings, waivers applied.

    `key` is the PEP-503 name and is what a waiver is looked up by; `subject` carries the version
    and is what the report prints. They are separate arguments because conflating them once meant
    every message advertised an `[exception.cffi==2-1-1]` that no author could ever write.
    """
    if not evidence.alternatives:
        detail = f"no licence metadata (evidence={evidence.kind}, raw={evidence.raw!r})"
        return [Finding("resolved-graph", UNREVIEWED, subject, detail)]
    waiver = policy.waivers.get(key)
    findings: list[Finding] = []
    cleared = False
    for alternative in evidence.alternatives:
        problems: list[Finding] = []
        for spdx_id in sorted(alternative):
            if waiver and waiver.spdx.lower() == spdx_id.lower():
                continue
            denied = denied_reason(spdx_id, policy)
            if denied:
                problems.append(
                    Finding(
                        "resolved-graph",
                        DENY,
                        subject,
                        f"{spdx_id} trips [deny] {denied}"
                        f" (evidence={evidence.kind}: {evidence.raw})",
                    )
                )
            elif spdx_id.lower() not in policy.allow:
                problems.append(
                    Finding(
                        "resolved-graph",
                        UNREVIEWED,
                        subject,
                        f"{spdx_id} is not on [allow] spdx and has no [exception.{key}]"
                        f" (evidence={evidence.kind}: {evidence.raw})",
                    )
                )
        if not problems:
            cleared = True
            break
        findings.extend(problems)
    return [] if cleared else findings


def scan_resolved_graph(graph: dict[str, Resolved], policy: Policy) -> list[Finding]:
    """Surface 1. Name denial is total over the lock; SPDX judgement needs installed metadata."""
    installed = _installed()
    findings: list[Finding] = []
    for key, resolved in sorted(graph.items()):
        subject = f"{resolved.name}=={resolved.version}"
        if key in policy.deny_name:
            findings.append(
                Finding(
                    "resolved-graph",
                    DENY,
                    subject,
                    f"[deny] name -- {sorted(resolved.scopes)} scope; see 17-risks.md R-L1"
                    " and 11-repo-layout.md section 9.3",
                )
            )
            continue
        dist = installed.get(key)
        if dist is None:
            if resolved.conditional:
                findings.append(
                    Finding(
                        "resolved-graph",
                        NOTICE,
                        subject,
                        "in the lock but not materialised on this platform (every inbound path"
                        " crosses a marker or an extra); no licence evidence available here",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "resolved-graph",
                        DENY,
                        subject,
                        "reachable unconditionally but absent from the environment -- the gate"
                        " cannot see this graph; run `uv sync --all-groups --all-extras`",
                    )
                )
            continue
        findings.extend(_judge(key, subject, spdx_evidence(dist, policy), policy))
    findings.extend(_stale_waivers(graph, policy))
    return findings


def _stale_waivers(graph: dict[str, Resolved], policy: Policy) -> list[Finding]:
    """An exception past its `review_by` fails; one naming nothing in the graph is a notice.

    "CI FAILS an exception past its review date, so an exception cannot become permanent by
    silence" (14-security.md section 9.2). The second rule is this module's and follows from the
    same sentence read the other way: a waiver for a distribution that left the graph is a row
    nobody will ever be asked about again.
    """
    today = dt.datetime.now(tz=dt.UTC).date()
    findings: list[Finding] = []
    for key, waiver in sorted(policy.waivers.items()):
        if waiver.review_by < today:
            findings.append(
                Finding(
                    "resolved-graph",
                    DENY,
                    f"[exception.{waiver.name}]",
                    f"review_by {waiver.review_by.isoformat()} has passed (approver"
                    f" {waiver.approver}, scope {waiver.scope})",
                )
            )
        elif key not in graph:
            findings.append(
                Finding(
                    "resolved-graph",
                    NOTICE,
                    f"[exception.{waiver.name}]",
                    "waives a distribution that is not in the resolved graph; delete the row",
                )
            )
    return findings


def _first_party_sources() -> list[tuple[Path, str]]:
    """Every first-party `.py` this gate reads, paired with the closure scope its imports face.

    `packages/*/src/**` is the shipped code and faces the runtime closure alone. Everything else
    under `packages/` is a test, and `tools/*.py` is a build script; both face runtime plus dev,
    because `pytest`, `hypothesis` and `ruff` are in the dev group and in no wheel. `tools/` is
    included because a gate script is first-party source like any other and an undeclared import
    there fails a CI job rather than a user's install — which makes it cheaper to catch, not less
    important to.
    """
    sources = [
        (p, "runtime" if "/src/" in p.as_posix() else "test")
        for p in REPO.glob("packages/*/**/*.py")
    ]
    sources += [(p, "dev") for p in (REPO / "tools").glob("*.py")]
    return sorted(sources)


def _import_roots(source: Path) -> dict[str, int]:
    """Top-level import roots in one file, mapped to the first line each is seen on."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    roots: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            roots.setdefault(name.split(".")[0], node.lineno)
    return roots


def _is_local(root: str, source: Path) -> bool:
    """A path-resolved first-party module rather than a distribution, so not a licence question.

    Three real shapes in this tree, all of them `sys.path` tricks rather than dependencies: a
    sibling module; `conftest`, which pytest supplies from an ANCESTOR directory
    (`packages/omniweave-core/tests/conftest.py` is imported from `tests/unit/`); and `tools/`,
    which `packages/omniweave-core/tests/unit/test_config_axes.py` puts on `sys.path` to import
    `gate_config_axes` because a script directory is not a distribution and cannot be installed.
    Treating any of these as an undeclared dependency would make the gate cry wolf on its own
    test suite, and a gate whose findings are routinely ignored protects nothing.
    """
    for parent in (source.parent, *source.parents):
        if (parent / f"{root}.py").exists() or (parent / root / "__init__.py").exists():
            return True
        if parent == REPO:
            break
    return (REPO / "tools" / f"{root}.py").exists()


def import_graph(policy: Policy, graph: dict[str, Resolved]) -> list[Finding]:
    """Surface 2. Every third-party import root must resolve to a distribution in scope's closure.

    A runtime import resolving only through the dev closure is a dependency the wheel does not
    declare, which is the same defect as `cairosvg` with a different cause.
    """
    modules = packages_distributions()
    stdlib = sys.stdlib_module_names
    findings: list[Finding] = []
    for source, scope in _first_party_sources():
        rel = source.relative_to(REPO).as_posix()
        allowed_scopes = {"runtime"} if scope == "runtime" else {"runtime", "dev"}
        for root, lineno in sorted(_import_roots(source).items()):
            where = f"{rel}:{lineno}"
            if root in policy.deny_module:
                findings.append(
                    Finding("import-graph", DENY, where, f"imports [deny] module {root!r}")
                )
                continue
            if root in stdlib or root.startswith("omniweave") or _is_local(root, source):
                continue
            owners = [pep503(d) for d in modules.get(root, ())]
            if not owners:
                findings.append(
                    Finding(
                        "import-graph",
                        DENY,
                        where,
                        f"imports {root!r}, which maps to no installed distribution -- an"
                        " undeclared dependency invisible to any manifest scan (DR18)",
                    )
                )
                continue
            in_scope = [o for o in owners if o in graph and graph[o].scopes & allowed_scopes]
            if not in_scope:
                findings.append(
                    Finding(
                        "import-graph",
                        DENY,
                        where,
                        f"imports {root!r} from {owners}, which is outside the {scope} closure",
                    )
                )
    return findings


def _primary_licence_paths(dist: Distribution) -> list[str]:
    """The distribution's OWN licence files, as posix strings from its `RECORD`.

    `License-File` (PEP 639) is authoritative when present; the entries with no `/` are the
    distribution's own and the rest are its vendored components' — that is how numpy declares one
    `LICENSE.txt` and sixteen bundled ones, and torch ninety-five. With no `License-File` at all,
    fall back to the licence files sitting directly in `.dist-info/` or `.dist-info/licenses/`.

    A candidate is matched by WHOLE PATH against the two places a `License-File` value may land —
    `<dist-info>/<value>` and `<dist-info>/licenses/<value>` — never by suffix. Suffix matching cost
    two false blockers before this line was written: `License-File = "LICENSE"` also caught
    `setuptools/_vendor/autocommand-2.2.2.dist-info/LICENSE` (LGPL-3.0, vendored, and reported as
    MIT-licensed setuptools' own claim) and `torch-2.14.0.dist-info/licenses/third_party/FP16/
    LICENSE`. A vendored or bundled notice is a notice; only the distribution's own top-level file
    is its claim, and the difference between the two is the difference between G3 and G12.
    """
    files = [str(f).replace("\\", "/") for f in (dist.files or ())]
    tops = sorted({f.split("/")[0] for f in files if f.split("/")[0].endswith(".dist-info")})
    if len(tops) != 1:
        return []
    prefix = tops[0] + "/"
    declared = [v for v in (dist.metadata.get_all("License-File") or ()) if "/" not in v]
    if declared:
        wanted = {prefix + v for v in declared} | {prefix + "licenses/" + v for v in declared}
        return [f for f in files if f in wanted]
    return [
        f
        for f in files
        if f.startswith(prefix)
        and LICENCE_FILENAME.search(f)
        and re.fullmatch(r"[^/]+\.dist-info/(licenses/)?[^/]+", f) is not None
    ]


def _read(dist: Distribution, relative: str) -> str | None:
    try:
        path = Path(str(dist.locate_file(relative)))
        if path.stat().st_size > MAX_LICENCE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _artefact_verdict(
    subject: str, rel: str, families: frozenset[str], policy: Policy
) -> Finding | None:
    """Apply 14-security.md section 9.2's "more restrictive of the two, and name both" rule."""
    denied = {f: denied_reason(f, policy) for f in families}
    hits = {f: d for f, d in denied.items() if d}
    if not hits:
        return None
    permissive = sorted(f for f in families if not denied[f])
    named = ", ".join(f"{f} -> [deny] {d}" for f, d in sorted(hits.items()))
    if permissive:
        return Finding(
            "unpacked-artifacts",
            NOTICE,
            subject,
            f"{rel} is an aggregate: {named}; it also grants {permissive}. Enumerated here;"
            " the failing register is tools/vendor.toml (G12) and THIRD_PARTY.md",
        )
    return Finding(
        "unpacked-artifacts",
        DENY,
        subject,
        f"{rel} is {named} with no permissive grant in the same text -- the unpacked artefact"
        " is more restrictive than the declared SPDX, and the gate takes the more restrictive",
    )


def unpacked_artifacts(
    graph: dict[str, Resolved], policy: Policy, *, deep: bool = False
) -> list[Finding]:
    """Surface 3. Licence TEXTS and redistributed binaries in each installed distribution's tree."""
    installed = _installed()
    findings: list[Finding] = []
    for key, resolved in sorted(graph.items()):
        dist = installed.get(key)
        if dist is None:
            continue
        subject = f"{resolved.name}=={resolved.version}"
        primary = _primary_licence_paths(dist)
        files = [str(f).replace("\\", "/") for f in (dist.files or ())]
        for rel in primary:
            text = _read(dist, rel)
            if text is None:
                continue
            verdict = _artefact_verdict(subject, rel, classify_licence_text(text), policy)
            if verdict:
                findings.append(verdict)
        own = set(primary)
        bundled = [f for f in files if LICENCE_FILENAME.search(f) and f not in own]
        # `../../Scripts/x.exe` is a console-script launcher generated at install time, outside the
        # site-packages tree and carrying nobody's licence. Counting it would inflate every row.
        binaries = [
            f
            for f in files
            if not f.startswith("../") and Path(f).suffix.lower() in BINARY_SUFFIXES
        ]
        if bundled:
            findings.append(
                Finding(
                    "unpacked-artifacts",
                    NOTICE,
                    subject,
                    f"{len(bundled)} bundled notice file(s), first {bundled[0]}",
                )
            )
        if binaries:
            findings.append(
                Finding(
                    "unpacked-artifacts",
                    NOTICE,
                    subject,
                    f"{len(binaries)} redistributed binary artefact(s), first {binaries[0]}",
                )
            )
        if deep:
            findings.extend(_deep(dist, subject, bundled, policy))
    return findings


def _deep(dist: Distribution, subject: str, bundled: list[str], policy: Policy) -> list[Finding]:
    """`--deep`: classify every bundled notice text too. Cold, that is about ninety seconds."""
    findings: list[Finding] = []
    for rel in bundled:
        text = _read(dist, rel)
        if text is None:
            continue
        families = classify_licence_text(text)
        hits = sorted(f for f in families if denied_reason(f, policy))
        if hits:
            findings.append(Finding("unpacked-artifacts", NOTICE, subject, f"{rel} bundles {hits}"))
    return findings


def _report(findings: list[Finding], *, show_notices: bool) -> None:
    for severity in (DENY, UNREVIEWED):
        for finding in findings:
            if finding.severity == severity:
                _emit(f"{severity.upper():10} {finding.surface:19} {finding.subject}")
                _emit(f"{'':10} {'':19} {finding.detail}")
    notices = [f for f in findings if f.severity == NOTICE]
    if show_notices:
        for finding in notices:
            _emit(f"{NOTICE.upper():10} {finding.surface:19} {finding.subject}")
            _emit(f"{'':10} {'':19} {finding.detail}")
    elif notices:
        subjects = len({f.subject for f in notices})
        _emit(f"{len(notices)} notice(s) across {subjects} subject(s); --notices to list them")


def main(argv: list[str] | None = None) -> int:
    """Run all three surfaces. Exit 1 on a blocker, 2 on an unreviewed licence, 0 otherwise."""
    parser = argparse.ArgumentParser(description="G3 -- the build-time licence gate.")
    parser.add_argument("--notices", action="store_true", help="list every notice finding")
    parser.add_argument("--deep", action="store_true", help="classify bundled notice texts too")
    args = parser.parse_args(argv)

    policy = load_policy()
    graph = resolved_graph()
    findings = scan_resolved_graph(graph, policy)
    findings += import_graph(policy, graph)
    findings += unpacked_artifacts(graph, policy, deep=args.deep)

    runtime = sum(1 for r in graph.values() if "runtime" in r.scopes)
    conditional = sum(1 for r in graph.values() if r.conditional)
    _emit(f"G3 licences  {POLICY.relative_to(REPO).as_posix()} over three surfaces")
    _emit(
        f"  resolved graph      {len(graph)} lock packages ({runtime} runtime,"
        f" {conditional} not materialised on this platform)"
    )
    _emit(f"  import graph        {len(_first_party_sources())} first-party modules")
    _emit(f"  unpacked artifacts  {len(_installed())} installed distributions")
    _emit("")
    _report(findings, show_notices=args.notices)

    blocked = [f for f in findings if f.severity == DENY]
    unreviewed = [f for f in findings if f.severity == UNREVIEWED]
    if blocked:
        _emit(f"\nG3 FAIL  {len(blocked)} denial(s), {len(unreviewed)} unreviewed licence(s).")
        return EXIT_BLOCKED
    if unreviewed:
        _emit(
            f"\nG3 FAIL  {len(unreviewed)} licence(s) in the graph are neither on [allow] spdx"
            " nor waived by an [exception.<name>]."
        )
        return EXIT_UNREVIEWED
    _emit(f"\nG3 ok  {len(graph)} lock packages, three surfaces, no denial and nothing unreviewed.")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
