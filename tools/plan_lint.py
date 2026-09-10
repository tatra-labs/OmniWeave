"""`ow plan lint` -- the four rules that make "we did not edit settled law" a check.

`_plan/` is settled law and `.gitignore:3` is `_plan/`, so the whole directory is untracked and
`git diff HEAD -- _plan/` prints nothing whatever the directory contains. Measured:
`_plan/_notes/build-defects.md` C55 (:5935-5984) is the row -- 1,720 new lines were written into
`_plan/_notes/` and both `git diff HEAD -- _plan/` and `git status --porcelain -- _plan/`
returned zero lines, with `git check-ignore -v` naming `.gitignore:3:_plan/` as the cause. Five
`tools/gate_*.py` files mention `_plan` and every one of them READS it as a source of truth; none
verifies that it is unchanged. This script is the detector C55 asks for, and it is deliberately
not a `tools/gate_*.py` file -- see THE FILE NAME below.

## Why the manifest lives in `tools/` and not in `_plan/`

C55's own proposal is "one `_plan/PLAN.sha256` written once". A manifest at that path would
itself be matched by `.gitignore:3`, never committed, and therefore exactly as invisible as the
thing it protects -- the same defect one level up. So the manifest is `tools/plan.sha256`:
`tools/` is tracked and already holds this repository's registers (`tools/gates.toml`,
`tools/layers.toml`, `tools/weights.toml`, `tools/licences.toml`, `tools/config_axes.toml`), and
a digest change there appears in an ordinary `git diff`. **Choosing the path is our engineering
call, not the plan's**; what the plan states is the verb (`ow plan lint`) and two of its rules.

## THE FILE NAME, and why this is not `tools/gate_plan.py`

`packages/omniweave-core/tests/unit/test_gates_register.py:426-443` sweeps `tools/gate_*.py` on
disk and fails on any script `tools/gates.toml` does not name. There is no `G` row for
`ow plan lint` -- the verb appears in `_plan/18-api-sketch.md:3227` and
`_plan/_notes/charter.md:8762` and in no G-series cell -- and inventing one would be exactly the
transcription-versus-invention error the build-defect ledger warns about, so no row was added.
That leaves the file name: outside the `gate_*.py` glob this script needs no row, and
`plan_lint.py` is the verb's own spelling. Registering it is a human decision; the finding is
reported rather than settled here.

## The verb, and why it is a `tools/` script

`ow plan lint` is plan-named twice:

* `_plan/_notes/charter.md:8762`, open question **E-Q2**: *"A `ow plan lint` rule that resolves
  each row's quoted phrase against `charter.md` and fails on a miss, reporting the row's line
  number as advisory rather than authoritative"*, with the pre-committed fallback *"Until it
  exists, the quoted phrase is the locus and the line number is a hint."*
* `_plan/18-api-sketch.md:3227-3244`, which names a second rule of the same verb, `codes-unique`,
  *"because reading has now failed twice"*, and prints its clauses as a table.

The `omniweave` CLI distribution is a bare skeleton and the CLI is P7's (16-roadmap.md section
10), so the verb becomes a `tools/` script now. That is ledger D25's standing pattern, applied
here for the seventh time: `ow schema emit` -> `tools/schemagen.py`, `ow store verify` ->
`store/verify.py` + `tools/gate_crash.py`, `ow test crash-matrix` -> `store/crashmatrix.py`,
`ow eval perf` -> `tools/measure_store.py`, `ow drivers` -> `tools/ow_drivers.py`, `ow host` ->
`tools/ow_host.py`.

## The four rules

**1. `charter-frozen`.** `_plan/_notes/charter.md:8689` opens the paragraph under its section 9
heading with *"**Sections 1-8 are unchanged. Deliberately.** No line of 1-8 was edited during
stage 10's repair work or stage 11's, and none will be"*. Section 9 is the errata surface and MAY
grow (E-Q1's pre-committed fallback is "The errata stays"), so the digest covers 1-8 only.

*How the region is defined, and the failure mode of the other choice.* The region is every byte
strictly above the **unique** line matching `^## 9\\.` -- today `:8687`, which the manifest pins
alongside the digest. The alternative was a fixed line count. A fixed count of N covers lines
1..N, so a line INSERTED AFTER old line N but BEFORE the section 9 heading leaves lines 1..N
byte-identical: the digest does not move and the new line of section 1-8 is never covered. That
is a check that silently stops covering the thing it exists to cover, which is the C41/C55/D114
family, so it was not chosen. The anchored region has its own failure mode -- a SECOND `## 9.`
heading inserted anywhere moves or shrinks the region -- and that is why "exactly one match" is
an assertion of this rule rather than an assumption of the parser, and why the boundary line
number is pinned in the manifest as well as the digest. `test_plan_lint.py` tests both: the
anchored region catches the append a fixed count misses, and a duplicated heading fails loudly.

**2. `documents-frozen`.** One sha256 per settled file under `_plan/`, pinned in the manifest and
recomputed here. That is the nineteen numbered documents, `README.md`, `glossary.md`,
`_plan/adr/` and the settled `_notes/` material -- including `_notes/.snapshots/`, which holds
immutable point-in-time copies and is pinned rather than excluded, because a directory-wide
exclusion is an off switch and a stray `sed -i` reaches those bytes exactly as it reaches the
others.

`_notes/charter.md` is deliberately NOT a `documents-frozen` row: its section 9 may grow, so a
whole-file digest over it would cry wolf on every legitimate erratum. `charter-frozen` covers it
instead, and the coverage accounting counts it as covered. One file, one rule, not a hole.

`WRITABLE_NOTES` is the allow-list, and **the allow-list is the dangerous part**: it is a way to
switch this gate off. It follows the shape this repository already uses twice for exactly this
hazard -- `test_core_eager_surface.py`'s `FILLED_HOMES` and `test_p2_freeze.py`'s
`FROZEN_SURFACES` -- an explicit list, one row per path, each naming WHY that path is writable,
the covered set computed as a difference rather than declared, and a second test proving no row
is a placeholder. A file under `_plan/` that appears in neither the manifest nor the allow-list
**fails**, because that is how a newly added settled document gets covered instead of silently
escaping.

**3. `errata-phrases`.** E-Q2's own rule, implemented as the sentence E-Q2 writes it in: resolve
each section 9.2 row's quoted phrase against `charter.md` and fail on a miss, reporting the row's
line number as advisory rather than authoritative. Two consequences of taking that sentence
literally:

* the phrase is resolved against the **frozen region** and not against the whole file. A row
  quotes its own phrase, so a search over the whole file finds the row itself and the rule could
  never fail -- an assertion over a container that always holds the answer, which is C13's family
  and the reason this wave exists.
* a cited locus that does not contain the phrase is reported as `advisory drift` and is NOT a
  failure. E-Q2 says the line number is a hint; a rule that failed on the hint would contradict
  the sentence it implements. The row count is derived from the table and compared against the
  count the section 9 heading claims in words; a disagreement between a heading and its own
  enumeration IS a failure, because it is the defect class this ledger has now recorded three
  times.

**4. `codes-unique`.** `_plan/18-api-sketch.md:3227-3244` states this rule in a clause table and
also states that it is HALF of a pair: *"`codes-unique` covers the prose before the register
exists, `--check` covers the register after"*. The register half already exists --
`omniweave_core.errors.check_register()`, pinned by `test_errors.py:278-437` -- so it is NOT
re-implemented here; INV-21 forbids a second home for one fact and this script cites the existing
one. The prose half did not exist, and it is what this rule is. Its clauses, from that table:
corpus is `_plan/*.md` plus `_notes/charter.md` and `_notes/terminology.md` with snapshots
excluded; tokens are `OW-[A-Z]-\\d{3}` and `OW_[A-Z0-9_]{3,}` matched per line; a numeric binds to
a symbol when the two are textually adjacent with a separator matching `[\\s\\x60()/\\u00b7*|]{0,6}`
and no comma in it; it fails when a numeric binds to two symbols or a symbol to two numerics, in
both directions; and it reports every binding site.

*The one exclusion, and why it is derived rather than transcribed.* 18-api-sketch.md:3359 states
that "the documented exception list is **empty**, and `codes-unique` runs with no exceptions".
Run as written, it does not pass: `OW-A-021` binds to `OW_UNTRUSTED_INSTRUCTION_SHAPED`
(`14-security.md:594` and `:1751`) and to `OW_INSTRUCTION_SHAPED_TEXT` (`charter.md:6883`,
reprinted in the row at `:8735`). Charter `E18` is the reconciliation and says so in as many
words -- it is *"a symbol **rename**, not two conditions sharing one numeric, and that reading is
the only one under which `codes-unique` is repairable"* -- and section 1-8 is never edited, so the
retired spelling stays in the file forever. So the exclusion is READ OUT OF charter section 9: a
`(numeric, symbol)` pair that a section 9.2 row quotes as its superseded phrase is dropped from
the tally, every dropped site is PRINTED, and the count of drops is in the report. Delete `E18`
and this rule goes red. That keeps 18:3359's "no hand-written exceptions" true and keeps the rule
non-vacuous: a THIRD symbol on `OW-A-021` still fails.

## Exit codes

0 every rule passed, 1 a rule failed, 2 the gate did not run (a missing or unparseable manifest,
an unreadable document, a plan root that is not a directory, a bad argument). 1 and 2 are
distinguished because CI treats both as failure and a human needs to know which -- the same
contract `tools/gate_tombstones.py` and `tools/gate_crash.py` state.

One divergence, stated rather than smoothed: 18-api-sketch.md:3244's clause table gives
`codes-unique` `exit = 2` on failure. That is the exit code THIS repository reserves for "the gate
did not run", and collapsing the two would destroy the distinction the paragraph above is about.
So a `codes-unique` failure exits 1 here, and when `ow plan lint` lands as a real CLI verb at P7
the mapping to 18:3244's `2` is that verb's to make. Reported as a finding.

## `--bless`: the procedure, which is the point of it

C55 asks for "a **stated procedure** for the one legitimate case, an approved amendment, which
re-blesses the manifest in the same commit that changes the text". A `--bless` that can be run
absent-mindedly is how a manifest stops meaning anything, so:

1. **Decide the amendment first.** Settled law changes by a human decision with a written reason
   -- an ADR under `_plan/adr/`, a charter section 9 erratum row, or a build-defect ledger row.
   Not by a gate going green.
2. Edit the plan text.
3. `uv run python tools/plan_lint.py --bless --reason "<why, and what decided it>"`. The reason
   is REQUIRED, is written into the manifest as a comment line, and therefore appears in the
   `git diff` of `tools/plan.sha256` beside the digests it justifies. `--bless` refuses without
   it (exit 2).
4. **Commit `tools/plan.sha256` in the same commit as the plan edit.** The plan side is
   gitignored and invisible, so the manifest diff is the only trace the amendment leaves in
   history. A bless committed separately is a manifest that no longer says when it changed or why.
5. Re-run the gate with no arguments and confirm exit 0.

`--bless` prints every digest it adds, changes and removes before it writes, and prints nothing
quietly.

## Non-vacuity

C55's closing rule is *"before citing a command as evidence, run it against a deliberate
violation and check that it fails"*. `packages/omniweave-core/tests/unit/test_plan_lint.py`
builds a fake plan tree in `tmp_path`, blesses it, then mutates one byte of a settled document,
deletes a file, adds an unlisted file, mutates charter section 1-8, mutates charter section 9
(which must PASS), breaks an erratum phrase and collides a code -- asserting the exit code and the
rule name for each. One of those tests initialises a real git repository with the plan directory
gitignored and asserts that `git diff` and `git status --porcelain` return nothing while this gate
returns non-zero on the same mutation. That assertion is what this wave is about.

Specified in `_plan/_notes/charter.md:8687-8689` (the frozen boundary), `:8711-8737` (the section
9.2 record), `:8762` (E-Q2), `_plan/18-api-sketch.md:3227-3252` and `:3353-3359`
(`codes-unique`), and `_plan/_notes/build-defects.md:5935-5984` (C55).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from omniweave_core.errors import NUMERIC_RE, SYMBOL_RE

__all__ = [
    "BINDING_SEPARATOR",
    "CHARTER_REL",
    "DEFAULT_MANIFEST",
    "DEFAULT_PLAN_ROOT",
    "ERRATA_ROW_CELLS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "MANIFEST_VERSION",
    "NEVER_WRITABLE_NOTES",
    "PHRASE_MISS",
    "RULES",
    "RULE_CHARTER",
    "RULE_CODES",
    "RULE_DOCUMENTS",
    "RULE_ERRATA",
    "SCAN_NUMERIC",
    "SCAN_SYMBOL",
    "SECTION_9_HEADING",
    "SNAPSHOTS_PREFIX",
    "TERMINOLOGY_REL",
    "WRITABLE_NOTES",
    "Binding",
    "Erratum",
    "Finding",
    "GateNotRunError",
    "Manifest",
    "bindings",
    "build_manifest",
    "check_charter_frozen",
    "check_codes_unique",
    "check_documents_frozen",
    "check_errata_phrases",
    "codes_corpus",
    "digest",
    "errata_rows",
    "first_code_span",
    "format_manifest",
    "frozen_region",
    "heading_claim",
    "locus_intervals",
    "main",
    "markdown_cells",
    "no_row_switches_off_settled_law",
    "parse_manifest",
    "plan_files",
    "settled_documents",
    "superseded_pairs",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
DEFAULT_PLAN_ROOT: Final = REPO_ROOT / "_plan"
DEFAULT_MANIFEST: Final = REPO_ROOT / "tools" / "plan.sha256"

MANIFEST_VERSION: Final = 1
"""Bumped only if the row grammar changes. A manifest of another version is `EXIT_NOT_RUN`: a
digest read under the wrong grammar is worse than no digest at all."""

RULE_CHARTER: Final = "charter-frozen"
RULE_DOCUMENTS: Final = "documents-frozen"
RULE_ERRATA: Final = "errata-phrases"
RULE_CODES: Final = "codes-unique"

RULES: Final = (RULE_CHARTER, RULE_DOCUMENTS, RULE_ERRATA, RULE_CODES)
"""Every rule is NAMED in the output, so a failure says which rule failed."""

CHARTER_REL: Final = "_notes/charter.md"
TERMINOLOGY_REL: Final = "_notes/terminology.md"
SNAPSHOTS_PREFIX: Final = "_notes/.snapshots/"

SECTION_9_HEADING: Final = re.compile(r"^## 9\.")
"""The frozen boundary's anchor. `charter.md:8687` is the only line matching it today, and
"exactly one match" is an assertion of `charter-frozen` rather than an assumption made here."""

ERRATA_TABLE_OPEN: Final = "### 9.2 "
ERRATA_TABLE_CLOSE: Final = "### 9.3 "
ERRATA_ROW: Final = re.compile(r'^\|\s*<a id="(e\d+)"></a>')
CODE_SPAN: Final = re.compile(r"``(?P<double>.+?)``|`(?P<single>.+?)`")
LOCUS_INTERVAL: Final = re.compile(r":(\d+)(?:-(\d+))?")
HEADING_CLAIM: Final = re.compile(r"the ([a-z]+(?:-[a-z]+)?) statements above")
PHRASE_MISS: Final = "resolves nowhere in sections 1-8"

ERRATA_ROW_CELLS: Final = 6
"""Charter section 9.2's table is six columns wide (`charter.md:8713`), and the third is the
quoted phrase. A row narrower than that is a row this parser has mis-read, which is
`EXIT_NOT_RUN` and never a silent skip."""

SHA256_HEX: Final = 64
VERSION_ROW_FIELDS: Final = 2
CHARTER_ROW_FIELDS: Final = 5
DOCUMENT_ROW_FIELDS: Final = 3
"""The manifest's row grammar, as field counts. See `MANIFEST_HEADER`."""

#: `errata-phrases` reads a count written in words -- the charter spells its counts out -- so the
#: parser is a table and not a guess, and an unparseable word is a failure rather than a skip.
NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}

# ---------------------------------------------------------------------------------------------
# THE ALLOW-LIST, and the reason each row is not settled law.
#
# These are the files under `_plan/_notes/` that THIS PROJECT WRITES, wave by wave. Pinning them
# would make the gate cry wolf on every commit, which is how a gate gets disabled. Every row names
# the writer and what it writes, and `test_plan_lint.py` proves no row is a placeholder: the path
# exists, the reason is a real sentence, the path is not one the plan's own settled corpus names,
# and the file was written after the plan documents were.
#
# Adding a row here switches the gate off for one path, so it is a deliberate act with a reason
# attached and never a way past a red run. The other direction is `NEVER_WRITABLE_NOTES`.
# ---------------------------------------------------------------------------------------------
WRITABLE_NOTES: Final[dict[str, str]] = {
    "_notes/build-defects.md": (
        "the build-defect ledger. Every wave appends verified rows to it, and C55 (:5935) -- the "
        "row that ordered this gate -- was written into it by the wave before this one."
    ),
    "_notes/m0-was-skipped.md": (
        "a scope decision recorded during a build wave: ':3, Recorded 2026-09-09, during P2 stage "
        "B. Nothing here has been applied to `_plan/`'. A wave note, not plan law."
    ),
    "_notes/p2-stage-b1-findings.md": (
        "P2 stage B wave 1's findings dump -- ':1, every finding the six build agents reported, "
        "verbatim ... dumped from the workflow journal so they survive the session'."
    ),
    "_notes/p2-stage-b2a-findings.md": (
        "P2 stage B wave 2a's findings dump, written by that wave's recorder on the b1 terms."
    ),
    "_notes/p2-stage-b2b-findings.md": (
        "P2 stage B wave 2b's findings dump, written by that wave's recorder on the b1 terms."
    ),
    "_notes/p2-stage-b2c-findings.md": (
        "P2 stage B wave 2c's findings dump, written by that wave's recorder on the b1 terms."
    ),
    "_notes/p2-stage-c-findings.md": (
        "P2 stage C's findings dump, written by that wave's recorder on the b1 terms."
    ),
    "_notes/p2-stage-d-findings.md": (
        "P2 stage D's findings dump, written by that wave's recorder on the b1 terms."
    ),
    "_notes/p3-stage-a-findings.md": (
        "P3 stage A's findings dump, written by that wave's recorder on the b1 terms."
    ),
    "_notes/p3-stage-b-findings.md": (
        "P3 stage B's findings dump -- ':3, Eighth companion, on the same terms as the b1, b2a, "
        "b2b, b2c, c, d and P3-stage-A files'."
    ),
}

NEVER_WRITABLE_NOTES: Final[frozenset[str]] = frozenset({CHARTER_REL, TERMINOLOGY_REL})
"""The two `_notes/` files the plan itself names as law. `18-api-sketch.md:3238` prints the
`codes-unique` corpus as *"`_plan/*.md` plus `_plan/_notes/charter.md` and
`_plan/_notes/terminology.md`"*, so neither may ever reach `WRITABLE_NOTES`; nor may anything at
the plan root, under `adr/`, or under `_notes/.snapshots/`. `no_row_switches_off_settled_law()`
is that check, and it runs inside the gate as well as inside the tests."""

BINDING_SEPARATOR: Final = re.compile(r"[\s\x60()/·*|]{0,6}")
"""18-api-sketch.md:3240's separator class, character for character.

The plan prints it as `[\\s\\x60()/·*\\|]{0,6}`. The only difference here is the markdown escape on
the pipe, which a table cell needs and a regex does not; `\\x60` is left exactly as the plan spells
it, because `re` reads it as the backtick it names. That makes the transcription checkable against
the cell itself, which is what `test_plan_lint.py` does rather than pinning it against us."""

SCAN_NUMERIC: Final = re.compile(NUMERIC_RE.pattern.removeprefix("^").removesuffix("$"))
SCAN_SYMBOL: Final = re.compile(SYMBOL_RE.pattern.removeprefix("^").removesuffix("$"))
"""The two token shapes, unanchored for a line scan. They are NOT re-declared here:
`omniweave_core.errors.NUMERIC_RE`/`SYMBOL_RE` already transcribe 18-api-sketch.md section 9 item
7's shapes for the register half of the same rule (`errors.py:375-378`), and INV-21 gives one fact
one home. `test_plan_lint.py` pins the patterns against the plan's own printed cell rather than
against each other, because both sides of that equality would otherwise come from us."""


class GateNotRunError(Exception):
    """The gate could not look. Distinct from a rule that looked and failed -- see `main`."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule failure. `path` is plan-relative, or `""` when the rule failed about the tree."""

    rule: str
    path: str
    detail: str

    def render(self) -> str:
        where = f" {self.path}:" if self.path else ""
        return f"FAIL {self.rule}:{where} {self.detail}"


@dataclass(frozen=True, slots=True)
class Erratum:
    """One row of charter section 9.2, as `errata-phrases` reads it."""

    anchor: str
    code: str
    row_line: int
    locus: str
    phrase: str
    intervals: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class Binding:
    """One `codes-unique` binding site: a numeric adjacent to a symbol on one line."""

    numeric: str
    symbol: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class Manifest:
    """`tools/plan.sha256`, parsed."""

    version: int
    charter_digest: str
    region_last_line: int
    heading_line: int
    documents: dict[str, str]


# ---------------------------------------------------------------------------------------------
# Reading the tree
# ---------------------------------------------------------------------------------------------


def digest(data: bytes) -> str:
    """sha256, hex, over raw bytes -- so a line ending or a BOM is part of what is pinned."""
    return hashlib.sha256(data).hexdigest()


def read_bytes(path: Path, plan_root: Path) -> bytes:
    """A document that cannot be read is `EXIT_NOT_RUN`, never a passing rule."""
    try:
        return path.read_bytes()
    except OSError as exc:
        where = path.relative_to(plan_root).as_posix() if path.is_relative_to(plan_root) else path
        raise GateNotRunError(f"cannot read {where}: {exc}") from exc


def plan_files(plan_root: Path) -> tuple[str, ...]:
    """Every file under the plan root, plan-relative, posix, sorted.

    Dotted names included: `_notes/.snapshots/` is pinned rather than excluded, so the walk has to
    see it. An empty tree raises, because every rule below would then be an assertion over an
    empty collection.
    """
    if not plan_root.is_dir():
        raise GateNotRunError(f"plan root is not a directory: {plan_root}")
    found = sorted(
        item.relative_to(plan_root).as_posix() for item in plan_root.rglob("*") if item.is_file()
    )
    if not found:
        raise GateNotRunError(f"no files under {plan_root} -- every rule here would be vacuous")
    return tuple(found)


def settled_documents(paths: Sequence[str]) -> tuple[str, ...]:
    """The `documents-frozen` set, computed as a DIFFERENCE and never declared.

    Everything under the plan root, less the allow-list, less `charter.md` -- which
    `charter-frozen` covers by region, because its section 9 may grow.
    """
    return tuple(rel for rel in paths if rel not in WRITABLE_NOTES and rel != CHARTER_REL)


def no_row_switches_off_settled_law() -> tuple[str, ...]:
    """The allow-list's own guard, returned as messages so the gate and its tests share it.

    A row naming a plan-root document, anything under `adr/`, a snapshot, or either of the two
    `_notes/` files the plan's own corpus clause names would be an off switch for settled law.
    """
    bad: list[str] = []
    for rel in WRITABLE_NOTES:
        if not rel.startswith("_notes/"):
            bad.append(f"{rel} is not under _notes/ and can never be writable")
        elif rel in NEVER_WRITABLE_NOTES:
            bad.append(f"{rel} is named by 18-api-sketch.md:3238's corpus and is never writable")
        elif rel.startswith(SNAPSHOTS_PREFIX):
            bad.append(f"{rel} is a snapshot -- immutable by construction, so never writable")
    return tuple(bad)


# ---------------------------------------------------------------------------------------------
# Rule 1 -- charter-frozen
# ---------------------------------------------------------------------------------------------


def frozen_region(charter: bytes) -> tuple[bytes, tuple[int, ...]]:
    """Section 1-8's bytes, and every 1-based line number matching the section 9 heading.

    The region is every byte strictly above the heading. Returning ALL matches is the point: the
    caller asserts there is exactly one, which is what stops a second `## 9.` heading from
    silently moving the boundary. See the module docstring.
    """
    lines = charter.splitlines(keepends=True)
    matches = tuple(
        number
        for number, raw in enumerate(lines, 1)
        if SECTION_9_HEADING.match(raw.decode("utf-8", errors="replace"))
    )
    if len(matches) != 1:
        return b"", matches
    return b"".join(lines[: matches[0] - 1]), matches


def check_charter_frozen(plan_root: Path, manifest: Manifest) -> tuple[list[Finding], list[str]]:
    """Rule 1. Findings, plus report notes that print even when the rule passes."""
    charter = read_bytes(plan_root / CHARTER_REL, plan_root)
    region, matches = frozen_region(charter)
    if len(matches) != 1:
        found = ", ".join(f":{number}" for number in matches) or "none"
        detail = (
            f"{SECTION_9_HEADING.pattern} matches {len(matches)} lines ({found}); exactly one "
            "defines the frozen boundary, and a second one moves it"
        )
        return [Finding(RULE_CHARTER, CHARTER_REL, detail)], []

    heading = matches[0]
    findings: list[Finding] = []
    if heading != manifest.heading_line:
        findings.append(
            Finding(
                RULE_CHARTER,
                CHARTER_REL,
                f"the section 9 heading is at :{heading}, pinned at :{manifest.heading_line} -- "
                "sections 1-8 grew or shrank, which :8689 says they never do",
            )
        )
    got = digest(region)
    if got != manifest.charter_digest:
        findings.append(
            Finding(
                RULE_CHARTER,
                CHARTER_REL,
                f"sections 1-8 digest {got[:16]}..., pinned {manifest.charter_digest[:16]}... "
                f"({heading - 1} lines, {len(region)} bytes)",
            )
        )
    note = (
        f"region 1-{heading - 1} ({heading - 1} lines, {len(region)} bytes), sha256 "
        f"{got[:16]}..., section 9 heading at :{heading}"
    )
    return findings, [note]


# ---------------------------------------------------------------------------------------------
# Rule 2 -- documents-frozen
# ---------------------------------------------------------------------------------------------


def check_documents_frozen(
    plan_root: Path, manifest: Manifest, paths: Sequence[str]
) -> tuple[list[Finding], list[str]]:
    """Rule 2. Every settled file pinned, no pinned file missing, no unlisted file."""
    findings = [
        Finding(RULE_DOCUMENTS, "", message) for message in no_row_switches_off_settled_law()
    ]
    on_disk = set(paths)

    if CHARTER_REL in manifest.documents:
        findings.append(
            Finding(
                RULE_DOCUMENTS,
                CHARTER_REL,
                "pinned as a whole document, but its section 9 may grow; charter-frozen owns it",
            )
        )
    findings.extend(
        Finding(RULE_DOCUMENTS, rel, "is both pinned and on the writable allow-list")
        for rel in sorted(set(manifest.documents) & set(WRITABLE_NOTES))
    )
    findings.extend(
        Finding(RULE_DOCUMENTS, rel, "pinned in the manifest and not on disk")
        for rel in sorted(set(manifest.documents) - on_disk)
    )
    for rel in settled_documents(paths):
        if rel not in manifest.documents:
            findings.append(
                Finding(
                    RULE_DOCUMENTS,
                    rel,
                    "is in neither the manifest nor the writable allow-list. If it is settled "
                    "law, --bless it; if this project writes it, add a WRITABLE_NOTES row naming "
                    "the wave that writes it and why",
                )
            )
            continue
        got = digest(read_bytes(plan_root / rel, plan_root))
        if got != manifest.documents[rel]:
            findings.append(
                Finding(
                    RULE_DOCUMENTS,
                    rel,
                    f"digest {got[:16]}..., pinned {manifest.documents[rel][:16]}...",
                )
            )
    absent = sorted(set(WRITABLE_NOTES) - on_disk)
    findings.extend(
        Finding(RULE_DOCUMENTS, rel, "on the writable allow-list and not on disk") for rel in absent
    )
    note = (
        f"{len(manifest.documents)} documents pinned, {len(WRITABLE_NOTES) - len(absent)} writable "
        f"by allow-list, 1 covered by {RULE_CHARTER}, {len(paths)} files under the root"
    )
    return findings, [note]


# ---------------------------------------------------------------------------------------------
# Rule 3 -- errata-phrases
# ---------------------------------------------------------------------------------------------


def markdown_cells(row: str) -> tuple[str, ...]:
    """A markdown table row's cells, honouring `\\|` inside a cell.

    Charter `E22` prints ``Rung \\| None`` inside a code span, so a naive `split("|")` reads that
    row as seven cells and mis-indexes every column after the escape.
    """
    out: list[str] = []
    cur: list[str] = []
    index = 0
    while index < len(row):
        char = row[index]
        if char == "\\" and row[index + 1 : index + 2] == "|":
            cur.append("|")
            index += 2
            continue
        if char == "|":
            out.append("".join(cur))
            cur = []
            index += 1
            continue
        cur.append(char)
        index += 1
    out.append("".join(cur))
    return tuple(cell.strip() for cell in out[1:-1])


def first_code_span(cell: str) -> str | None:
    """The row's quoted phrase. Both `` `x` `` and ``` ``a `b` c`` ``` occur; E12 is the
    second."""
    match = CODE_SPAN.search(cell)
    if match is None:
        return None
    span = match.group("double") if match.group("double") is not None else match.group("single")
    return span.strip()


def locus_intervals(cell: str) -> tuple[tuple[int, int], ...]:
    """Every `:N` and `:N-M` in the locus cell, as closed intervals. ADVISORY only, per E-Q2."""
    return tuple((int(low), int(high or low)) for low, high in LOCUS_INTERVAL.findall(cell))


def errata_rows(charter_text: str) -> tuple[Erratum, ...]:
    """Charter section 9.2's table, row by row. The COUNT comes from here, never from a heading."""
    lines = charter_text.splitlines()
    opens = [n for n, line in enumerate(lines) if line.startswith(ERRATA_TABLE_OPEN)]
    closes = [n for n, line in enumerate(lines) if line.startswith(ERRATA_TABLE_CLOSE)]
    if len(opens) != 1 or len(closes) != 1 or closes[0] <= opens[0]:
        raise GateNotRunError(
            f"charter section 9.2 is not delimited by one {ERRATA_TABLE_OPEN!r} and one "
            f"{ERRATA_TABLE_CLOSE!r} heading (found {len(opens)} and {len(closes)})"
        )
    rows: list[Erratum] = []
    for offset in range(opens[0], closes[0]):
        line = lines[offset]
        anchor = ERRATA_ROW.match(line)
        if anchor is None:
            continue
        cells = markdown_cells(line)
        if len(cells) < ERRATA_ROW_CELLS:
            raise GateNotRunError(
                f"charter:{offset + 1} is a section 9.2 row with {len(cells)} cells, not "
                f"{ERRATA_ROW_CELLS}"
            )
        phrase = first_code_span(cells[2])
        if phrase is None:
            raise GateNotRunError(
                f"charter:{offset + 1} ({anchor.group(1)}) quotes no phrase in its third cell, so "
                "E-Q2's rule has nothing to resolve"
            )
        rows.append(
            Erratum(
                anchor=anchor.group(1),
                code=anchor.group(1).upper(),
                row_line=offset + 1,
                locus=cells[1],
                phrase=phrase,
                intervals=locus_intervals(cells[1]),
            )
        )
    return tuple(rows)


def heading_claim(charter_text: str) -> tuple[int | None, str]:
    """The count the section 9 heading claims in words, and the heading line itself."""
    for line in charter_text.splitlines():
        if not SECTION_9_HEADING.match(line):
            continue
        match = HEADING_CLAIM.search(line)
        if match is None:
            return None, line
        word = match.group(1)
        if "-" not in word:
            return NUMBER_WORDS.get(word), line
        tens, units = word.split("-", 1)
        if tens in NUMBER_WORDS and units in NUMBER_WORDS:
            return NUMBER_WORDS[tens] + NUMBER_WORDS[units], line
        return None, line
    return None, ""


def check_errata_phrases(plan_root: Path) -> tuple[list[Finding], list[str]]:
    """Rule 3. E-Q2's sentence: resolve the phrase, fail on a miss, line number advisory."""
    charter = read_bytes(plan_root / CHARTER_REL, plan_root)
    text = charter.decode("utf-8")
    region_bytes, matches = frozen_region(charter)
    if len(matches) != 1:
        detail = (
            "no unique section 9 heading, so sections 1-8 are not delimited -- and resolving a "
            "phrase against the whole file would find the row that quotes it"
        )
        return [Finding(RULE_ERRATA, CHARTER_REL, detail)], []

    region = region_bytes.decode("utf-8")
    rows = errata_rows(text)
    findings: list[Finding] = []
    claimed, heading = heading_claim(text)
    if claimed is None:
        findings.append(
            Finding(RULE_ERRATA, CHARTER_REL, f"no count reads out of the heading {heading!r}")
        )
    elif claimed != len(rows):
        findings.append(
            Finding(
                RULE_ERRATA,
                f"{CHARTER_REL}:{matches[0]}",
                f"the section 9 heading claims {claimed} statements and its own table holds "
                f"{len(rows)} rows",
            )
        )

    codes = [row.code for row in rows]
    repeated = sorted({code for code in codes if codes.count(code) > 1})
    if repeated:
        findings.append(
            Finding(RULE_ERRATA, CHARTER_REL, f"section 9.2 anchors repeat: {repeated}")
        )

    resolved = 0
    drifted: list[str] = []
    for row in rows:
        offset = region.find(row.phrase)
        if offset < 0:
            findings.append(
                Finding(
                    RULE_ERRATA,
                    f"{CHARTER_REL}:{row.row_line}",
                    f"{row.code} quotes {row.phrase!r}, which {PHRASE_MISS}. Its locus cell "
                    f"{row.locus!r} is ADVISORY and not the locus: E-Q2 makes the phrase the "
                    "locus, so a miss is a real miss",
                )
            )
            continue
        resolved += 1
        line = region.count("\n", 0, offset) + 1
        if row.intervals and not any(low <= line <= high for low, high in row.intervals):
            drifted.append(f"{row.code} phrase at :{line}, locus cell says {row.locus!r}")

    notes = [
        f"{len(rows)} rows, {resolved} phrases resolved in sections 1-8 (lines "
        f"1-{matches[0] - 1}); the heading claims {claimed}; {len(drifted)} advisory line(s) "
        "drifted"
    ]
    notes.extend(
        f"advisory drift (not a failure -- E-Q2 makes the line a hint): {drift}"
        for drift in drifted
    )
    return findings, notes


# ---------------------------------------------------------------------------------------------
# Rule 4 -- codes-unique
# ---------------------------------------------------------------------------------------------


def codes_corpus(plan_root: Path) -> tuple[str, ...]:
    """18-api-sketch.md:3238's corpus clause: `_plan/*.md` plus `charter.md` and
    `terminology.md`; snapshots excluded (they are pinned by `documents-frozen`, not read here)."""
    top = sorted(item.name for item in plan_root.glob("*.md") if item.is_file())
    return (*top, CHARTER_REL, TERMINOLOGY_REL)


def bindings(text: str, path: str) -> Iterator[Binding]:
    """18-api-sketch.md:3239-3241's token, binding and not-a-binding clauses, matched per line.

    Tokens are collected in positional order, so "no other token between them" is exactly
    "consecutive". Both orders bind, because the separator class admits no letters: ordinary prose
    ("`OW_FOO` and `OW-A-001`") cannot produce a pair, and a comma anywhere in the separator is
    the plan's own not-a-binding clause.
    """
    for number, line in enumerate(text.splitlines(), 1):
        tokens = sorted(
            [(m.start(), m.end(), True, m.group()) for m in SCAN_NUMERIC.finditer(line)]
            + [(m.start(), m.end(), False, m.group()) for m in SCAN_SYMBOL.finditer(line)]
        )
        for left, right in itertools.pairwise(tokens):
            if left[2] == right[2]:
                continue
            between = line[left[1] : right[0]]
            if "," in between or BINDING_SEPARATOR.fullmatch(between) is None:
                continue
            numeric, symbol = (left[3], right[3]) if left[2] else (right[3], left[3])
            yield Binding(numeric=numeric, symbol=symbol, path=path, line=number)


def superseded_pairs(rows: Sequence[Erratum]) -> frozenset[tuple[str, str]]:
    """The `(numeric, symbol)` pairs charter section 9.2 records as RETIRED spellings.

    Read out of the errata rather than transcribed, so 18-api-sketch.md:3359's "the documented
    exception list is **empty**" stays true and deleting the row turns this rule red. Today that
    is exactly `E18`'s `OW-A-021 OW_INSTRUCTION_SHAPED_TEXT`.
    """
    return frozenset(
        (site.numeric, site.symbol) for row in rows for site in bindings(row.phrase, row.anchor)
    )


def _render_sites(groups: dict[str, list[Binding]]) -> str:
    """Every binding site -- file, line, symbol -- because 18:3243 wants a `sed`, not a
    search."""
    return "; ".join(
        f"{other} at " + ", ".join(f"{site.path}:{site.line}" for site in sites)
        for other, sites in sorted(groups.items())
    )


def check_codes_unique(plan_root: Path) -> tuple[list[Finding], list[str]]:
    """Rule 4, the prose half. The register half is `omniweave_core.errors.check_register()`."""
    charter = read_bytes(plan_root / CHARTER_REL, plan_root)
    retired = superseded_pairs(errata_rows(charter.decode("utf-8")))

    corpus = codes_corpus(plan_root)
    sites: list[Binding] = []
    excluded: list[Binding] = []
    for rel in corpus:
        text = read_bytes(plan_root / rel, plan_root).decode("utf-8")
        for site in bindings(text, rel):
            (excluded if (site.numeric, site.symbol) in retired else sites).append(site)

    by_numeric: dict[str, dict[str, list[Binding]]] = {}
    by_symbol: dict[str, dict[str, list[Binding]]] = {}
    for site in sites:
        by_numeric.setdefault(site.numeric, {}).setdefault(site.symbol, []).append(site)
        by_symbol.setdefault(site.symbol, {}).setdefault(site.numeric, []).append(site)

    findings: list[Finding] = [
        Finding(
            RULE_CODES, "", f"{numeric} binds to {len(symbols)} symbols: {_render_sites(symbols)}"
        )
        for numeric, symbols in sorted(by_numeric.items())
        if len(symbols) > 1
    ]
    findings.extend(
        Finding(RULE_CODES, "", f"{symbol} binds to {len(nums)} numerics: {_render_sites(nums)}")
        for symbol, nums in sorted(by_symbol.items())
        if len(nums) > 1
    )

    notes = [
        f"{len(by_numeric)} numerics and {len(by_symbol)} symbols bound over {len(corpus)} "
        f"documents, {len(sites)} binding sites, {len(excluded)} superseded"
    ]
    notes.extend(
        "superseded by a charter section 9 row (not a hand-written exception list): "
        f"{site.numeric} {site.symbol} at {site.path}:{site.line}"
        for site in excluded
    )
    return findings, notes


# ---------------------------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------------------------


def build_manifest(plan_root: Path) -> Manifest:
    """Recompute every digest from the tree as it stands. `--bless` and nothing else calls this."""
    charter = read_bytes(plan_root / CHARTER_REL, plan_root)
    region, matches = frozen_region(charter)
    if len(matches) != 1:
        raise GateNotRunError(
            f"cannot bless: {SECTION_9_HEADING.pattern} matches {len(matches)} lines in "
            f"{CHARTER_REL}, so sections 1-8 have no boundary"
        )
    documents = {
        rel: digest(read_bytes(plan_root / rel, plan_root))
        for rel in settled_documents(plan_files(plan_root))
    }
    return Manifest(
        version=MANIFEST_VERSION,
        charter_digest=digest(region),
        region_last_line=matches[0] - 1,
        heading_line=matches[0],
        documents=documents,
    )


MANIFEST_HEADER: Final = """\
# tools/plan.sha256 -- sha256 digests of settled law under `_plan/`, read by tools/plan_lint.py.
#
# WHY THIS FILE IS HERE AND NOT UNDER `_plan/`. `.gitignore:3` is `_plan/`, so the whole plan
# directory is untracked and `git diff HEAD -- _plan/` prints nothing whatever it contains
# (`_plan/_notes/build-defects.md` C55, :5935). A manifest inside `_plan/` -- C55's own
# `_plan/PLAN.sha256` -- would be gitignored too, and exactly as invisible as the thing it
# protects. `tools/` is tracked and already holds this repository's registers, so a digest change
# here shows up in an ordinary diff. Choosing the path was our call; the plan names the verb.
#
# GENERATED. Never hand-edit a digest. Amend the plan, then run
#   uv run python tools/plan_lint.py --bless --reason "<why, and what decided it>"
# and commit this file IN THE SAME COMMIT as the plan edit -- the plan side leaves no trace in
# history, so this diff is the only record that settled law changed, and why. The full procedure
# is in tools/plan_lint.py's module docstring.
#
# ROWS. `version <n>`, one `charter-frozen` row, and one `documents-frozen` row per settled file.
# `_notes/charter.md` has no `documents-frozen` row on purpose: its section 9 errata surface MAY
# grow (charter.md:8689, and :8762's E-Q1), so only sections 1-8 are digested, delimited by the
# unique `## 9.` heading whose line number is pinned beside the digest.
#
# Files this project WRITES every wave -- the build-defect ledger and the per-stage findings dumps
# -- are not pinned. They are named one by one, with a reason each, in tools/plan_lint.py's
# `WRITABLE_NOTES`. A file under `_plan/` in neither this manifest nor that allow-list FAILS.
"""


def format_manifest(manifest: Manifest, reason: str) -> str:
    """The manifest's bytes. Deterministic -- sorted rows, no timestamp -- so a diff is
    real."""
    parts = [
        MANIFEST_HEADER,
        f"#\n# blessed-because: {reason}\n\n",
        f"version  {manifest.version}\n",
        f"{RULE_CHARTER}  {manifest.charter_digest}  {CHARTER_REL}"
        f"  region=1-{manifest.region_last_line}  heading={manifest.heading_line}\n",
    ]
    parts.extend(
        f"{RULE_DOCUMENTS}  {hexdigest}  {rel}\n"
        for rel, hexdigest in sorted(manifest.documents.items())
    )
    return "".join(parts)


def _checked_digest(value: str, where: str) -> str:
    if len(value) != SHA256_HEX or any(char not in "0123456789abcdef" for char in value):
        raise GateNotRunError(f"{where}: {value!r} is not a lowercase hex sha256")
    return value


def _parse_charter_row(parts: Sequence[str], where: str) -> tuple[str, int, int]:
    if len(parts) != CHARTER_ROW_FIELDS or parts[2] != CHARTER_REL:
        raise GateNotRunError(
            f"{where}: a {RULE_CHARTER} row is `<digest> {CHARTER_REL} region=1-N heading=M`"
        )
    region = re.fullmatch(r"region=1-(\d+)", parts[3])
    heading = re.fullmatch(r"heading=(\d+)", parts[4])
    if region is None or heading is None:
        raise GateNotRunError(f"{where}: cannot read {parts[3]!r} and {parts[4]!r}")
    last, boundary = int(region.group(1)), int(heading.group(1))
    if last + 1 != boundary:
        raise GateNotRunError(
            f"{where}: region=1-{last} and heading={boundary} disagree. The region is every line "
            "strictly above the heading, so the two are adjacent by construction"
        )
    return _checked_digest(parts[1], where), last, boundary


def parse_manifest(text: str, source: Path | str) -> Manifest:
    """Parse, strictly. Anything unexpected is `EXIT_NOT_RUN`: a half-read manifest is a gate that
    reports success because it never looked."""
    version: int | None = None
    charter: tuple[str, int, int] | None = None
    documents: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        where = f"{source}:{number}"
        if parts[0] == "version" and len(parts) == VERSION_ROW_FIELDS:
            if not parts[1].isdigit():
                raise GateNotRunError(f"{where}: version {parts[1]!r} is not a number")
            version = int(parts[1])
        elif parts[0] == RULE_CHARTER:
            charter = _parse_charter_row(parts, where)
        elif parts[0] == RULE_DOCUMENTS and len(parts) == DOCUMENT_ROW_FIELDS:
            if parts[2] in documents:
                raise GateNotRunError(f"{where}: {parts[2]} is pinned twice")
            documents[parts[2]] = _checked_digest(parts[1], where)
        else:
            raise GateNotRunError(f"{where}: cannot read the row {line!r}")
    if version is None:
        raise GateNotRunError(f"{source}: no `version` row")
    if version != MANIFEST_VERSION:
        raise GateNotRunError(
            f"{source}: version {version}, and this gate reads {MANIFEST_VERSION}"
        )
    if charter is None:
        raise GateNotRunError(f"{source}: no `{RULE_CHARTER}` row")
    if not documents:
        raise GateNotRunError(f"{source}: no `{RULE_DOCUMENTS}` rows -- that rule would be vacuous")
    return Manifest(
        version=version,
        charter_digest=charter[0],
        region_last_line=charter[1],
        heading_line=charter[2],
        documents=documents,
    )


def _report_bless(old: Manifest | None, fresh: Manifest, out: TextIO) -> None:
    """Every digest `--bless` adds, changes or removes, printed BEFORE it writes."""
    if old is None:
        out.write(
            f"  FIRST BLESS: {len(fresh.documents)} documents, plus charter sections 1-8 "
            f"(1-{fresh.region_last_line}).\n"
        )
        return
    added = sorted(set(fresh.documents) - set(old.documents))
    removed = sorted(set(old.documents) - set(fresh.documents))
    changed = sorted(
        rel
        for rel in set(fresh.documents) & set(old.documents)
        if fresh.documents[rel] != old.documents[rel]
    )
    charter_moved = (
        old.charter_digest != fresh.charter_digest or old.heading_line != fresh.heading_line
    )
    if charter_moved:
        out.write(
            f"  CHARTER SECTIONS 1-8 CHANGED: {old.charter_digest[:16]}... -> "
            f"{fresh.charter_digest[:16]}..., boundary :{old.heading_line} -> "
            f":{fresh.heading_line}. charter.md:8689 says no line of 1-8 is ever edited.\n"
        )
    for rel in changed:
        out.write(
            f"  changed:  {rel}  {old.documents[rel][:16]}... -> {fresh.documents[rel][:16]}...\n"
        )
    for rel in added:
        out.write(f"  added:    {rel}\n")
    for rel in removed:
        out.write(f"  removed:  {rel}\n")
    if not (added or removed or changed or charter_moved):
        out.write("  NO DIGEST CHANGED. Only the reason line moves.\n")


def _bless(plan_root: Path, manifest_path: Path, reason: str, out: TextIO) -> int:
    """Rewrite the manifest, loudly. See the module docstring's five-step procedure."""
    if not reason.strip():
        raise GateNotRunError(
            "--bless needs --reason: an amendment to settled law without a stated reason is not "
            "an amendment, it is a gate being switched off. See the module docstring"
        )
    fresh = build_manifest(plan_root)
    old = (
        parse_manifest(manifest_path.read_text(encoding="utf-8"), manifest_path)
        if manifest_path.is_file()
        else None
    )

    out.write("=" * 94 + "\n")
    out.write("REWRITING THE PLAN MANIFEST. This is an amendment to settled law.\n")
    out.write(f"  reason:   {reason.strip()}\n")
    out.write(f"  plan:     {plan_root}\n")
    out.write(f"  manifest: {manifest_path}\n")
    _report_bless(old, fresh, out)
    out.write("Commit this manifest in the SAME COMMIT as the plan edit: the plan side is\n")
    out.write("gitignored (.gitignore:3), so this diff is the only trace the change leaves.\n")
    out.write("=" * 94 + "\n")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(format_manifest(fresh, reason.strip()), encoding="utf-8", newline="\n")
    out.write(f"wrote {manifest_path}\n")
    return EXIT_CLEAN


def _require_manifest(manifest_path: Path) -> None:
    """No manifest is `EXIT_NOT_RUN`. There is nothing to compare against, so a pass would be a
    gate reporting success because it never looked -- C55's own closing rule."""
    if not manifest_path.is_file():
        raise GateNotRunError(
            f"no manifest at {manifest_path}. There is nothing to compare against, so this gate "
            "cannot pass: bless one with --bless --reason '<...>'"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plan_lint.py",
        description=(
            "ow plan lint: charter-frozen, documents-frozen, errata-phrases and codes-unique over "
            "_plan/. Exit 0 clean, 1 a rule failed, 2 the gate did not run."
        ),
    )
    parser.add_argument(
        "--plan-root",
        default=DEFAULT_PLAN_ROOT,
        type=Path,
        help=(
            "the plan tree to check (default: %(default)s). A parameter so the tests build a "
            "fixture tree instead of mutating settled law."
        ),
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST,
        type=Path,
        help="the digest manifest (default: %(default)s).",
    )
    parser.add_argument(
        "--bless",
        action="store_true",
        help=(
            "REWRITE the manifest from the tree as it stands. Requires --reason. Read the "
            "five-step procedure in this module's docstring first."
        ),
    )
    parser.add_argument(
        "--reason",
        default="",
        help="why settled law was amended, and what decided it. Written into the manifest.",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """0 every rule passed, 1 a rule failed, 2 the gate did not run."""
    stream = sys.stdout if out is None else out
    args = _parser().parse_args(argv)
    plan_root: Path = args.plan_root
    manifest_path: Path = args.manifest

    try:
        if args.bless:
            return _bless(plan_root, manifest_path, args.reason, stream)
        _require_manifest(manifest_path)
        paths = plan_files(plan_root)
        manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"), manifest_path)
        results: dict[str, tuple[list[Finding], list[str]]] = {
            RULE_CHARTER: check_charter_frozen(plan_root, manifest),
            RULE_DOCUMENTS: check_documents_frozen(plan_root, manifest, paths),
            RULE_ERRATA: check_errata_phrases(plan_root),
            RULE_CODES: check_codes_unique(plan_root),
        }
    except GateNotRunError as exc:
        stream.write(f"plan lint DID NOT RUN: {exc}\n")
        return EXIT_NOT_RUN

    stream.write(f"plan lint: root={plan_root} manifest={manifest_path}\n")
    failed = 0
    for rule in RULES:
        findings, notes = results[rule]
        failed += len(findings)
        stream.write(f"  {'FAIL' if findings else 'ok  '} {rule:<18}{notes[0] if notes else ''}\n")
        for note in notes[1:]:
            stream.write(f"       {'':<18}{note}\n")
        for finding in findings:
            stream.write(f"  {finding.render()}\n")
    if failed:
        stream.write(f"plan lint: {failed} finding(s) -- settled law under {plan_root} moved.\n")
        return EXIT_FAIL
    stream.write(f"plan lint: {len(RULES)} rules, 0 findings.\n")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
