"""`gates.invariant_register` - the five semantic assertions over `tools/invariants.toml`.

Not a `G<n>`. ADR-2 decision 2 settles the home and the reason: `G27(d)` is
"the correct home for *identifier resolution* and the wrong home for *semantic assertions over a
register's rows*" -- `d2` resolves whether `INV-21` exists, this script asserts whether its row is
well-formed. Different questions, different failure messages, different owners. It is the
`[[job_assertion]]` `gates.invariant_register`, job `gates`, budget 2 s, and
11-repo-layout.md:1637 states its scope in one line: *"heading <-> row bidirectionally, ladder
rule 1, `independent == len(enforcers) + len(sites)`, ladder rule 2's two decidable cases, and
every spelled-out invariant count in any document against the row count."*

## The five, each independently falsifiable

**A1 - bidirectional coverage.** Every `### INV-<n>` heading in `01-principles.md` has exactly one
`[[inv]]` row and every `INV-<n>` row has exactly one heading. The shape the terminology lock
already uses, and the direction people forget is the second one: a row for a heading somebody
deleted is a register describing a document that no longer says it.

**A2 - ladder rule 1.** `independent >= min_enforcers` and `classes != ["R"]`, for every `[[inv]]`
row. Both numbers are read from the file rather than written here, which is what ADR-2 decision 2
asks for by putting `ladder` and `min_enforcers` in the register.

**A3 - the arithmetic.** `independent == len(enforcers) + len(sites)`. One line, and it is the
check that makes `independent` auditable instead of asserted: section 1e's INV-19 is 5 against
three `enforcers` entries precisely because `sites` holds the two that have no id.

**A4 - ladder rule 2's two decidable cases, and only those.** Case (a): two enforcers that resolve
to the same semgrep configuration count as one -- a `sites` entry naming a file under
`tools/semgrep/` and any `enforcers` id whose `tools/gates.toml` runner list contains
`tools/gate_semgrep.py` are one enforcer, because one bad edit to that bank disables both. Case
(b): a generated artefact and the artefact it was generated from count as one unless a parity gate
is named. The general case is undecidable and stays `R` (01#3's own pre-committed scope). After
collapsing, rule 1 is re-asserted on the collapsed count -- which is the point of the clause, since
a row reaching two only by double-counting one bank has one enforcer.

Case (b) matches no row in the register as committed, and that is a hazard this file takes
seriously rather than a reason to skip it: a detector that silently matches nothing is clause d0's
own failure mode. `collapse_generated` is therefore exercised against a synthetic row in
`packages/omniweave-core/tests/unit/test_gate_invariants.py`, so the detector is known to work
before the day a row needs it.

**A5 - the count.** Every spelled-out invariant count in the plan equals the number of `[[inv]]`
rows whose id matches `^INV-\\d+$` and whose `force` is `invariant`. Modelled on `G27(d)` clause
d2's distribution-count check: "a pull request that adds `INV-26` and forgets a paragraph fails
here". The scan, its scope and the seven phrases it does not count are declared in the register's
own header, because an exemption nobody can read is an exemption nobody reviews.

## And six structural checks, because a register with the right arithmetic over the wrong rows is
## still wrong

**S1 families.** Nine `[[family]]` rows, prefixes unique, each `assigns` document present, each
`assigned` count equal to the rows that family actually has, and `M-INV` ahead of `INV` so the
longest match wins -- 11-repo-layout.md section 8.6's own warning, that a scan without it
"resolves `M-INV-3` against the framework register, finds a row, and reports a pass for an
identifier it never looked up".

**S2 members.** Every id matches exactly one family's pattern and no id appears twice across the
two arrays. Each `[[member]]`'s `source` line exists, and for a row read from a table the folded
cells equal `title` and `enforced_by` -- the register is checked against the document rather than
trusted, which is the only thing that keeps a transcription honest.

**S3 enforcers resolve.** `G<n>` against `tools/gates.toml`, `Q-G<n>` against 13-quality.md
section 14's table, and an invariant-family id against this register. An enforcer that resolves
nowhere is a row claiming a gate nobody wrote.

**S4 sites resolve, or are scheduled.** A `sites` entry is a dotted `omniweave*` symbol that
imports or a repo-relative path that exists -- or it has an `[[unbuilt_site]]` row naming the
16-roadmap.md phase that builds it. Both directions: a site that resolves may not also claim a
phase, so the list shrinks as the phases land and cannot quietly grow.

**S5 `[[absent]]`.** The two identifiers a document cites in order to say they do not exist. Each
`cites` line still contains the identifier, and no row claims it. Minting `RT15` for real means
deleting its row, and deleting the sentence does too.

**S6 `[[count_exempt]]`.** Each exempted phrase still occurs in its file. A stale exemption is a
hole in A5 that nothing else would report.

Exit 0 clean, 1 with one `gates.invariant_register FAIL` block per finding.
Specified in 01-principles.md section 1e, ADR-2 decision 2, 11-repo-layout.md:1637 and
17-risks.md:578 (`01#3`).
"""

from __future__ import annotations

import importlib
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
REGISTER: Final[Path] = REPO / "tools" / "invariants.toml"
GATES: Final[Path] = REPO / "tools" / "gates.toml"
PRINCIPLES: Final[Path] = REPO / "docs" / "plan" / "01-principles.md"
QUALITY: Final[Path] = REPO / "docs" / "plan" / "13-quality.md"
ROADMAP: Final[Path] = REPO / "docs" / "plan" / "16-roadmap.md"

PREFIX: Final = "gates.invariant_register"
FAIL_INDENT: Final = "    "

FOLD: Final[tuple[tuple[str, str], ...]] = (
    (chr(0x2014), " -- "),  # EM DASH
    (chr(0x21D2), "=>"),  # RIGHTWARDS DOUBLE ARROW
    (chr(0x00D7), "x"),  # MULTIPLICATION SIGN
    (chr(0x2192), "->"),  # RIGHTWARDS ARROW
    (chr(0x2227), "and"),  # LOGICAL AND
    (chr(0x2264), "<="),  # LESS-THAN OR EQUAL TO
    (chr(0x2265), ">="),  # GREATER-THAN OR EQUAL TO
    (chr(0x00A7), "section "),  # SECTION SIGN
    (chr(0x2016), "||"),  # DOUBLE VERTICAL LINE
    (chr(0x2026), "..."),  # HORIZONTAL ELLIPSIS
    (chr(0x2208), " in "),  # ELEMENT OF
    (chr(0x03A3), "sum"),  # GREEK CAPITAL LETTER SIGMA
    (chr(0x00B1), "+/-"),  # PLUS-MINUS SIGN
    (chr(0x00B7), "."),  # MIDDLE DOT
    (chr(0x2286), "subset-of"),  # SUBSET OF OR EQUAL TO
    (chr(0x2229), "intersect"),  # INTERSECTION
)
"""The register's declared substitution table, in its declared order. Applied nowhere else.

Named by codepoint for `calibration.py`'s reason -- `ruff`'s RUF001 reads several of these glyphs
in a string literal as ambiguous, and a reader who cannot see which arrow or dash a row folds
cannot check a register row against the cell it was read from."""

SEMGREP_RUNNER: Final = "tools/gate_semgrep.py"
SEMGREP_DIR: Final = "tools/semgrep/"

NUMBER_WORDS: Final[tuple[str, ...]] = (
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "twenty-one",
    "twenty-two",
    "twenty-three",
    "twenty-four",
    "twenty-five",
    "twenty-six",
    "twenty-seven",
    "twenty-eight",
    "twenty-nine",
    "thirty",
)
WORD_VALUE: Final[dict[str, int]] = {
    #  `two`..`twenty` are consecutive, so the first nineteen come off the tuple's own order; the
    #  rest are written out because `twenty-one`..`thirty` are not.
    **{word: index + 2 for index, word in enumerate(NUMBER_WORDS[:19])},
    "twenty-one": 21,
    "twenty-two": 22,
    "twenty-three": 23,
    "twenty-four": 24,
    "twenty-five": 25,
    "twenty-six": 26,
    "twenty-seven": 27,
    "twenty-eight": 28,
    "twenty-nine": 29,
    "thirty": 30,
}

FAMILIES: Final = 9
"""11-repo-layout.md section 8.6 and glossary.md's prefix map: nine invariant prefixes."""

SOURCE_CELLS: Final = 3
"""Every table a `[[member]]` row is read from is `| id | invariant | enforced by |`."""

_HEADING = re.compile(r"^### (INV-\d+) — (.+)$", re.MULTILINE)
_CELL = re.compile(r"(?<!\\)\|")
_INV_ID = re.compile(r"^INV-\d+$")
_SYMBOL = re.compile(r"^omniweave(?:_[a-z]+)*(?:\.[A-Za-z_]\w*)+$")
_PHASE = re.compile(r"^\|\s*\*\*?(M0|P\d+)\*?\*?\s*\|", re.MULTILINE)
_QG_ROW = re.compile(r"^\|\s*`?(Q-G\d+)`?", re.MULTILINE)
_COUNT = re.compile(
    r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\s+invariants?\b",
    re.IGNORECASE,
)

__all__ = [
    "Finding",
    "check_absent",
    "check_arithmetic",
    "check_bidirectional",
    "check_count",
    "check_count_exempt",
    "check_enforcers",
    "check_families",
    "check_ladder_rule_one",
    "check_ladder_rule_two",
    "check_members",
    "check_sites",
    "collapse_generated",
    "collapse_semgrep",
    "fold",
    "main",
    "plan_scope",
]


@dataclass(frozen=True, slots=True)
class Finding:
    """One failure, named by what has to be fixed rather than by which check found it."""

    headline: str
    detail: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join((f"{PREFIX} FAIL: {self.headline}", *self.detail))


def fold(text: str) -> str:
    """The register's fold, and the unescaping a markdown cell needs. See the register's header."""
    for before, after in FOLD:
        text = text.replace(before, after)
    return " ".join(text.replace("\\|", "|").split())


def plan_scope() -> tuple[Path, ...]:
    """A5's scope: the plan and the ADRs, never `_notes/`. The register's header says why."""
    plan = REPO / "docs" / "plan"
    return (
        *sorted(plan.glob("*.md")),
        *sorted((plan / "adr").glob("*.md")),
        REPO / "docs" / "ARCHITECTURE.md",
    )


def _register() -> dict[str, object]:
    return tomllib.loads(REGISTER.read_text(encoding="utf-8"))


def _table(register: dict[str, object], key: str) -> list[dict[str, object]]:
    """One table array, as rows. A missing or malformed key reads as no rows and the structural
    checks below report the absence, which is better than raising before any finding is printed."""
    rows = register.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _int(row: dict[str, object], key: str) -> int:
    """One integer out of a parsed TOML row. A non-integer is a malformed row and reads as 0, so
    the arithmetic and ladder checks report it as a number that does not hold rather than raise."""
    value = row.get(key)
    return value if isinstance(value, int) else 0


def _strs(row: dict[str, object], key: str) -> list[str]:
    """One list of strings out of a parsed TOML row, in file order. A missing key reads as empty."""
    value = row.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(one) for one in value]


def _invariant_rows(register: dict[str, object]) -> list[dict[str, object]]:
    return _table(register, "inv")


def _member_rows(register: dict[str, object]) -> list[dict[str, object]]:
    return _table(register, "member")


#  ---------------------------------------------------------------------------------------------
#  A1 - bidirectional coverage


def check_bidirectional(register: dict[str, object]) -> list[Finding]:
    headings = {
        found.group(1): found.group(2)
        for found in _HEADING.finditer(PRINCIPLES.read_text(encoding="utf-8"))
    }
    rows = [row for row in _invariant_rows(register) if _INV_ID.match(str(row["id"]))]
    counted: dict[str, int] = {}
    for row in rows:
        identifier = str(row["id"])
        counted[identifier] = counted.get(identifier, 0) + 1
    findings: list[Finding] = []
    for identifier, times in sorted(counted.items()):
        if times != 1:
            findings.append(Finding(f"{identifier} has {times} rows; a row is one per identifier."))
    missing = sorted(set(headings) - set(counted), key=_order)
    invented = sorted(set(counted) - set(headings), key=_order)
    if missing:
        findings.append(
            Finding(
                f"{len(missing)} heading(s) in 01-principles.md have no [[inv]] row: "
                + ", ".join(missing),
                (
                    FAIL_INDENT
                    + "fix: add the row, or the section is an invariant no register holds.",
                ),
            )
        )
    if invented:
        findings.append(
            Finding(
                f"{len(invented)} [[inv]] row(s) have no `### INV-<n>` heading: "
                + ", ".join(invented),
                (FAIL_INDENT + "fix: delete the row, or restore the section it describes.",),
            )
        )
    for identifier, title in sorted(headings.items(), key=lambda pair: _order(pair[0])):
        row = next((one for one in rows if str(one["id"]) == identifier), None)
        if row is not None and fold(title) != str(row["title"]):
            findings.append(
                Finding(
                    f"{identifier}: the row's title is not the heading's.",
                    (
                        FAIL_INDENT + f"heading: {fold(title)}",
                        FAIL_INDENT + f"row:     {row['title']}",
                    ),
                )
            )
    return findings


def _order(identifier: str) -> int:
    found = re.search(r"\d+", identifier)
    return int(found.group()) if found else 0


#  ---------------------------------------------------------------------------------------------
#  A2 and A3 - ladder rule 1 and the arithmetic


def check_ladder_rule_one(register: dict[str, object]) -> list[Finding]:
    ladder = _strs(register, "ladder")
    floor = _int(register, "min_enforcers")
    findings: list[Finding] = []
    for row in _invariant_rows(register):
        identifier = str(row["id"])
        classes = _strs(row, "classes")
        independent = _int(row, "independent")
        if independent < floor:
            findings.append(
                Finding(f"{identifier}: independent = {independent}, min_enforcers = {floor}.")
            )
        if classes == ["R"]:
            findings.append(
                Finding(f'{identifier}: classes = ["R"], which rule 1 forbids on its own.')
            )
        unknown = [one for one in classes if one not in ladder]
        if unknown:
            findings.append(Finding(f"{identifier}: class(es) not on the ladder: {unknown}."))
        #  Order is only a question once every letter is ON the ladder; `ladder.index` raises on a
        #  letter that is not, and a gate that raises prints no other finding.
        if not unknown and classes != sorted(classes, key=ladder.index):
            findings.append(
                Finding(
                    f"{identifier}: classes are not in ladder order.",
                    (FAIL_INDENT + f"ladder: {ladder}",),
                )
            )
        if len(set(classes)) != len(classes):
            findings.append(Finding(f"{identifier}: classes repeats a letter; it is a set."))
    return findings


def check_arithmetic(register: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    for row in _invariant_rows(register):
        enforcers = _strs(row, "enforcers")
        sites = _strs(row, "sites")
        independent = _int(row, "independent")
        if independent != len(enforcers) + len(sites):
            findings.append(
                Finding(
                    f"{row['id']}: independent = {independent}, "
                    f"len(enforcers) + len(sites) = {len(enforcers)} + {len(sites)}."
                )
            )
        for name, listed in (("enforcers", enforcers), ("sites", sites)):
            if len(set(listed)) != len(listed):
                findings.append(Finding(f"{row['id']}: {name} lists an entry twice."))
    return findings


#  ---------------------------------------------------------------------------------------------
#  A4 - rule 2's two decidable cases


def collapse_semgrep(enforcers: list[str], sites: list[str], semgrep_gates: frozenset[str]) -> int:
    """Case (a): everything that resolves to the semgrep bank is one enforcer, not several."""
    banked = [one for one in enforcers if one in semgrep_gates]
    banked += [one for one in sites if one.startswith(SEMGREP_DIR)]
    if len(banked) <= 1:
        return 0
    return len(banked) - 1


def collapse_generated(enforcers: list[str], sites: list[str], generated: dict[str, str]) -> int:
    """Case (b): a generated artefact and its source are one enforcer unless a parity gate is named.

    `generated` maps a listed entry to the entry it is generated from. A pair counts as two only
    when a third entry is the parity gate holding them equal, which is the "unless" in ADR-2
    decision 2 assertion 4.
    """
    listed = set(enforcers) | set(sites)
    collapsed = 0
    for artefact, source in sorted(generated.items()):
        if artefact in listed and source in listed:
            parity = generated.get(f"{artefact}:parity")
            if parity is None or parity not in listed:
                collapsed += 1
    return collapsed


def check_ladder_rule_two(register: dict[str, object]) -> list[Finding]:
    semgrep_gates = _semgrep_gates()
    generated = {
        str(row["artefact"]): str(row["from"]) for row in _table(register, "generated_pair")
    } | {
        f"{row['artefact']}:parity": str(row["parity"])
        for row in _table(register, "generated_pair")
        if row.get("parity")
    }
    floor = _int(register, "min_enforcers")
    findings: list[Finding] = []
    for row in _invariant_rows(register):
        enforcers = _strs(row, "enforcers")
        sites = _strs(row, "sites")
        effective = (
            _int(row, "independent")
            - collapse_semgrep(enforcers, sites, semgrep_gates)
            - collapse_generated(enforcers, sites, generated)
        )
        if effective < floor:
            findings.append(
                Finding(
                    f"{row['id']}: {effective} independent enforcer(s) after rule 2, "
                    f"min_enforcers = {floor}.",
                    (
                        FAIL_INDENT + f"listed: {row['independent']}",
                        FAIL_INDENT
                        + "rule 2 collapses enforcers that share the semgrep bank, and a "
                        + "generated artefact with its source when no parity gate is named.",
                    ),
                )
            )
    return findings


def _semgrep_gates() -> frozenset[str]:
    rows = _table(tomllib.loads(GATES.read_text(encoding="utf-8")), "gate")
    found = set()
    for row in rows:
        runners = _strs(row, "runner")
        if SEMGREP_RUNNER in runners:
            found.add(str(row["id"]))
    return frozenset(found)


#  ---------------------------------------------------------------------------------------------
#  A5 - the count


def check_count(register: dict[str, object]) -> list[Finding]:
    rows = [
        row
        for row in _invariant_rows(register)
        if _INV_ID.match(str(row["id"])) and str(row["force"]) == "invariant"
    ]
    expected = len(rows)
    exempt = {
        (str(row["file"]), str(row["phrase"]).lower()) for row in _table(register, "count_exempt")
    }
    findings: list[Finding] = []
    for path in plan_scope():
        if not path.is_file():
            findings.append(Finding(f"A5's scope names {_relative(path)} and it is not a file."))
            continue
        text = path.read_text(encoding="utf-8")
        for found in _COUNT.finditer(text):
            phrase = found.group(0).lower()
            if (_relative(path), phrase) in exempt:
                continue
            said = WORD_VALUE.get(found.group(1).lower())
            if said == expected:
                continue
            line = text[: found.start()].count("\n") + 1
            findings.append(
                Finding(
                    f'{_relative(path)}:{line} says "{found.group(0)}" and the register holds '
                    f"{expected}.",
                    (
                        FAIL_INDENT
                        + "fix: the prose, or -- if the phrase counts another series -- a "
                        + "[[count_exempt]] row saying which.",
                    ),
                )
            )
    return findings


def _relative(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


#  ---------------------------------------------------------------------------------------------
#  S1 - the families


def check_families(register: dict[str, object]) -> list[Finding]:
    families = _table(register, "family")
    findings: list[Finding] = []
    if len(families) != FAMILIES:
        findings.append(
            Finding(
                f"{len(families)} [[family]] row(s); 11-repo-layout.md section 8.6 "
                f"says {FAMILIES}.",
            )
        )
    prefixes = [str(row["prefix"]) for row in families]
    if len(set(prefixes)) != len(prefixes):
        findings.append(Finding("a prefix is registered twice; a prefix resolves to one series."))
    if {"M-INV", "INV"} <= set(prefixes) and prefixes.index("M-INV") > prefixes.index("INV"):
        findings.append(
            Finding(
                "INV is listed before M-INV, so the longest match does not win.",
                (
                    FAIL_INDENT
                    + "11-repo-layout.md section 8.6: a scan without that order resolves "
                    + "M-INV-3 against the framework register and reports a pass for an "
                    + "identifier it never looked up.",
                ),
            )
        )
    held: dict[str, int] = {}
    for row in _invariant_rows(register):
        prefix = str(row["id"]).rsplit("-", 1)[0]
        held[prefix] = held.get(prefix, 0) + 1
    for row in _member_rows(register):
        family = str(row["family"])
        held[family] = held.get(family, 0) + 1
    for row in families:
        prefix = str(row["prefix"])
        pattern = str(row["pattern"])
        try:
            re.compile(pattern)
        except re.error as why:
            findings.append(Finding(f"{prefix}: pattern does not compile: {why}"))
        assigns = REPO / str(row["assigns"])
        if not assigns.is_file():
            findings.append(Finding(f"{prefix}: assigns {row['assigns']}, which is not a file."))
        if _int(row, "assigned") != held.get(prefix, 0):
            findings.append(
                Finding(f"{prefix}: assigned = {row['assigned']}, rows = {held.get(prefix, 0)}.")
            )
        if str(row["rows"]) not in {"inv", "member"}:
            findings.append(Finding(f"{prefix}: rows = {row['rows']!r}, not 'inv' or 'member'."))
    return findings


#  ---------------------------------------------------------------------------------------------
#  S2 - the members


def check_members(register: dict[str, object]) -> list[Finding]:
    families = _table(register, "family")
    patterns = [(str(row["prefix"]), re.compile(str(row["pattern"]) + r"$")) for row in families]
    seen: dict[str, int] = {}
    findings: list[Finding] = []
    for row in (*_invariant_rows(register), *_member_rows(register)):
        identifier = str(row["id"])
        seen[identifier] = seen.get(identifier, 0) + 1
    for identifier, times in sorted(seen.items(), key=lambda pair: -pair[1]):
        if times != 1:
            findings.append(Finding(f"{identifier} appears in {times} rows across the arrays."))
    for row in _member_rows(register):
        identifier = str(row["id"])
        family = str(row["family"])
        matched = [prefix for prefix, pattern in patterns if pattern.match(identifier)]
        if not matched:
            findings.append(Finding(f"{identifier}: matches no [[family]] pattern."))
        elif matched[0] != family:
            findings.append(
                Finding(f"{identifier}: family = {family!r}, longest match is {matched[0]!r}.")
            )
        findings.extend(_check_source(row))
    return findings


def _check_source(row: dict[str, object]) -> list[Finding]:
    identifier = str(row["id"])
    relative, _, number = str(row["source"]).rpartition(":")
    path = REPO / relative
    if not path.is_file():
        return [Finding(f"{identifier}: source {row['source']} is not a file.")]
    lines = path.read_text(encoding="utf-8").splitlines()
    index = int(number) - 1
    if not 0 <= index < len(lines):
        return [Finding(f"{identifier}: source {row['source']} is past the end of the file.")]
    line = lines[index]
    if identifier not in line:
        return [
            Finding(
                f"{identifier}: source {row['source']} does not name it.",
                (FAIL_INDENT + f"line: {line.strip()[:100]}",),
            )
        ]
    if not line.lstrip().startswith("|"):
        #  M-INV is prose, not a table. Naming the identifier is all this line can be asked for.
        return []
    cells = [one.strip() for one in _CELL.split(line.strip().strip("|"))]
    if len(cells) != SOURCE_CELLS:
        return [
            Finding(f"{identifier}: source row has {len(cells)} cells, expected {SOURCE_CELLS}.")
        ]
    findings: list[Finding] = []
    for key, cell in (("title", cells[1]), ("enforced_by", cells[2])):
        if fold(cell) != str(row[key]):
            findings.append(
                Finding(
                    f"{identifier}: {key} is not the folded source cell.",
                    (
                        FAIL_INDENT + f"source: {fold(cell)[:120]}",
                        FAIL_INDENT + f"row:    {str(row[key])[:120]}",
                    ),
                )
            )
    return findings


#  ---------------------------------------------------------------------------------------------
#  S3 - the enforcers


def check_enforcers(register: dict[str, object]) -> list[Finding]:
    gates = {
        str(row["id"]) for row in _table(tomllib.loads(GATES.read_text(encoding="utf-8")), "gate")
    }
    quality = set(_QG_ROW.findall(QUALITY.read_text(encoding="utf-8")))
    held = {str(row["id"]) for row in (*_invariant_rows(register), *_member_rows(register))}
    findings: list[Finding] = []
    for row in _invariant_rows(register):
        for enforcer in _strs(row, "enforcers"):
            if enforcer.startswith("Q-G"):
                where, known = "13-quality.md section 14", quality
            elif re.match(r"^G\d+$", enforcer):
                where, known = "tools/gates.toml", gates
            else:
                where, known = "this register", held
            if enforcer not in known:
                findings.append(Finding(f"{row['id']}: enforcer {enforcer} is not in {where}."))
    return findings


#  ---------------------------------------------------------------------------------------------
#  S4 - the sites


def check_sites(register: dict[str, object]) -> list[Finding]:
    phases = set(_PHASE.findall(ROADMAP.read_text(encoding="utf-8")))
    scheduled = {str(row["site"]): row for row in _table(register, "unbuilt_site")}
    findings: list[Finding] = []
    listed: set[str] = set()
    for row in _invariant_rows(register):
        for site in _strs(row, "sites"):
            listed.add(site)
            resolves = _resolves(site)
            if resolves and site in scheduled:
                findings.append(
                    Finding(
                        f"{site} resolves and still has an [[unbuilt_site]] row.",
                        (
                            FAIL_INDENT
                            + "fix: delete the row; the phase that builds it has landed.",
                        ),
                    )
                )
            if not resolves and site not in scheduled:
                findings.append(
                    Finding(
                        f"{row['id']}: site {site} neither resolves nor is scheduled.",
                        (
                            FAIL_INDENT
                            + "fix: name a symbol that imports or a path that exists, or add an "
                            + "[[unbuilt_site]] row with the 16-roadmap.md phase that builds it.",
                        ),
                    )
                )
    for site, row in sorted(scheduled.items()):
        if site not in listed:
            findings.append(Finding(f"[[unbuilt_site]] {site} is no row's site."))
        if str(row["phase"]) not in phases:
            findings.append(
                Finding(f"[[unbuilt_site]] {site}: phase {row['phase']} is not in 16-roadmap.md.")
            )
    return findings


def _resolves(site: str) -> bool:
    if not _SYMBOL.match(site):
        return (REPO / site).exists()
    parts = site.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for attribute in parts[cut:]:
            if not hasattr(target, attribute):
                return False
            target = getattr(target, attribute)
        return True
    return False


#  ---------------------------------------------------------------------------------------------
#  S5 and S6 - the two declared exception tables


def check_absent(register: dict[str, object]) -> list[Finding]:
    held = {str(row["id"]) for row in (*_invariant_rows(register), *_member_rows(register))}
    findings: list[Finding] = []
    for row in _table(register, "absent"):
        identifier = str(row["id"])
        if identifier in held:
            findings.append(
                Finding(
                    f"{identifier} is listed as absent and has a row.",
                    (FAIL_INDENT + "fix: delete the [[absent]] row; it exists now.",),
                )
            )
        relative, _, number = str(row["cites"]).rpartition(":")
        path = REPO / relative
        if not path.is_file():
            findings.append(Finding(f"{identifier}: cites {row['cites']}, which is not a file."))
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        index = int(number) - 1
        if not 0 <= index < len(lines) or identifier not in lines[index]:
            findings.append(
                Finding(
                    f"{identifier}: {row['cites']} no longer names it.",
                    (
                        FAIL_INDENT
                        + "fix: delete the [[absent]] row -- nothing cites the identifier any "
                        + "more, so it needs no exception.",
                    ),
                )
            )
    return findings


def check_count_exempt(register: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    for row in _table(register, "count_exempt"):
        path = REPO / str(row["file"])
        phrase = str(row["phrase"])
        if not path.is_file():
            findings.append(Finding(f"[[count_exempt]] {row['file']} is not a file."))
            continue
        if phrase.lower() not in path.read_text(encoding="utf-8").lower():
            findings.append(
                Finding(
                    f"[[count_exempt]] {row['file']} no longer says {phrase!r}.",
                    (FAIL_INDENT + "fix: delete the row; A5 does not need the exception.",),
                )
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stdout.write("usage: tools/gate_invariants.py\n")
        return 2
    if not REGISTER.is_file():
        sys.stdout.write(
            f"{PREFIX} FAIL: tools/invariants.toml is not committed.\n"
            f"{FAIL_INDENT}01-principles.md section 1e specifies it; G27 clause d2 cannot resolve "
            "an invariant identifier without it.\n"
        )
        return 1
    register = _register()
    findings = [
        *check_bidirectional(register),
        *check_ladder_rule_one(register),
        *check_arithmetic(register),
        *check_ladder_rule_two(register),
        *check_count(register),
        *check_families(register),
        *check_members(register),
        *check_enforcers(register),
        *check_sites(register),
        *check_absent(register),
        *check_count_exempt(register),
    ]
    if findings:
        for finding in findings:
            sys.stdout.write(finding.render() + "\n")
        sys.stdout.write(f"{PREFIX} FAILED: {len(findings)} finding(s)\n")
        return 1
    invariants = len(_invariant_rows(register))
    members = len(_member_rows(register))
    families = len(_table(register, "family"))
    sys.stdout.write(
        f"{PREFIX} ok: {invariants} [[inv]] rows bidirectional against 01-principles.md, "
        f"{members} [[member]] rows over {families} families, ladder rules 1 and 2 hold, "
        f"every count says {invariants}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
