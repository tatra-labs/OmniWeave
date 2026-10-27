"""G27 clauses (a), (a2) and (a3) - the fenced blocks of the design record, machine-checked.

`tools/gates.toml` states G27 as *"documents machine-checked: fences parse (a), one key per
physical line (a2), `[[rule]]` fences linted (a3), migrations dense-unique-ordered (b), terminology
(c), symbols and registers (d)"*. Clause (b) is `tools/gate_migrations.py` and has been for some
time. This script is clauses (a), (a2) and (a3), plus clause (c)'s registered-off line. **Clause
(d) is not in this script yet**: 11-repo-layout.md section 8.6 gives it five checks d0-d4 over a
walk of `docs/ARCHITECTURE.md` and `docs/plan/*.md`, its ARCHITECTURE.md half already runs at the
test tier (`packages/omniweave-core/tests/unit/test_architecture_doc.py`, D986), and the walk is
the next cell. The gate prints that on its own line rather than leaving a reader to infer it: a
check that bounds its own coverage says what it dropped.

## Clause (a) - every fenced block parses under the parser its fence names

Three parsers, all stdlib: `tomllib` for ` ```toml `, `json` for ` ```json `, `ast` for
` ```python `. A fence naming anything else is COUNTED AND NOT CHECKED, and the count is printed
per language, because the honest statement of this clause's coverage is a number a reader can
compare against the corpus. ` ```jsonc ` is the one that looks checkable and is not: JSONC has no
stdlib parser, the fences carry `...` elisions, and a hand-rolled comment stripper would be a
second implementation of a parser the repository does not own -- INV-23's rejection criterion, the
same argument ADR-4 makes for deleting the standalone check 4 at the P5 exit.

`FENCE_FLOOR` is clause d0's lesson applied here. A fence scanner whose regex stopped matching
would report zero findings over zero fences and exit 0, which is exactly the C55 shape this
repository has paid for three times. The floor is asserted before any finding is reported.

## Clause (a2) - lexical, and that is the whole point

11-repo-layout.md:1576: *"After `tomllib.loads` succeeds on a ` ```toml ` fence in `charter.md` or
a plan document, `tools/gate_docs.py` walks the source text and requires the running count of `{`
minus `}`, outside comments and strings, to be zero at the end of every physical line."* A semantic
checker cannot see this: it reads a loaded `dict`, and TOML 1.0.0 permits a newline inside braces
where it falls inside a value. The charter's own D4 block is exactly that shape -- legal TOML, so
`tomllib` accepts it and always would have.

**The one expected finding is declared, not tolerated.** ADR-4 decision 1 measured this corpus:
*"One inline table spans a newline, not two, and it is a `when` rather than a `then`"*, in the
charter's section D4 fence, which the same decision **retires in whole** in favour of
05-ingest-and-routing.md section 4.4 under charter section 9 erratum `E42`. The charter's sections
1-8 are frozen -- *"No line of 1-8 was edited ... and none will be"* -- so the finding cannot be
fixed and is not a defect to fix: it is retired law, and `A2_EXPECTED` is the register of that.
The check runs both ways. A finding anywhere else fails, and an `A2_EXPECTED` row that stops being
a finding fails too, so the list can only shrink.

## Clause (a3) - the P1 interim standalone check 4

ADR-4 decision 2 and 05-ingest-and-routing.md:1797: `a3` runs `ow route lint` checks 1, 2, 4, 5, 7,
9, 10 and 12 over every ` ```toml ` fence that parses to a table containing a `[[rule]]` array, and
`ow route lint` ships at P5. *"From P1 the gate harness carries a standalone check 4 instead,
reading nullability from section 5.1's `null` column parsed out of the markdown table rather than
by importing `omniweave.route`; that column is therefore load-bearing for a gate as well as for the
linter."* At the P5 exit this standalone check is **deleted** in the same commit that lands `a3` --
pre-committed, because two implementations of one check is charter section 8 rejection criterion 19.

Check 4 is `OW-P-004`: *"every rule reading a nullable key declares `on_unknown`; a rule whose
`when` is `exists`-only does not need one"*. The seven expected findings are ADR-4 decision 1's own
measurement -- *"(a) seven rules there fail lint check 4 (`OW-P-004`), not nine, against zero in
section 4.4 -- and one of the seven is dangerous rather than merely non-compliant,
`repair.never-escalate-furniture` reading `block.type`"* -- so this clause does not merely check the
corpus, it reproduces the number the ADR was decided on. Both directions again: a rule that starts
failing fails the gate, and a declared row that stops failing fails it too.

## Clause (c) - registered and off

ADR-1 decision 6 requires the terminology lock's clause to sit in `tools/gates.toml` with
`enabled = false` and a `blocked_by` note *"so its absence is visible rather than assumed"*, until
four conditions hold. This script reads that row rather than restating it, and prints the state it
finds. It never runs the clause, because a `--warn-only` is what section 6.8 says there is none of.

Exit 0 clean, 1 with one `G27 FAIL` block per finding, 2 on a usage error.
Specified in 11-repo-layout.md section 6.4 and :1575-1600, ADR-4 decisions 1 and 2,
05-ingest-and-routing.md sections 4.5 and 5.1, and 16-roadmap.md:159 (P1 W1.12).
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
PLAN: Final[Path] = REPO / "docs" / "plan"
CHARTER: Final[Path] = PLAN / "_notes" / "charter.md"
ROUTING: Final[Path] = PLAN / "05-ingest-and-routing.md"
GATES: Final[Path] = REPO / "tools" / "gates.toml"

PREFIX: Final = "G27"
FAIL_INDENT: Final = "    "

FENCE_FLOOR: Final = 450
"""Clause d0's lesson: a scanner that matched nothing would report no finding and exit 0.

Measured at 637 fences over the scope below, of which 264 name one of the three parsers. Set well
under the total so an ordinary edit does not fail the gate, and far enough above zero that a broken
fence regex cannot satisfy it."""

TOML_FENCE_FLOOR: Final = 60
"""The same guard for clause a2 and a3's narrower scope, measured at 74.

ADR-4 decision 1 counted **73** *"` ```toml ` fences in the charter and in `00`-`18`"*. The extra
one is 01-principles.md section 1e's `tools/invariants.toml` example, which ADR-2 wrote after ADR-4
took its count. Recorded rather than corrected: the ADR's number was true when it was measured, and
the gate reports what it finds."""

_FENCE_OPEN: Final = re.compile(r"^(`{3,})([A-Za-z0-9_+-]*)\s*$")
_FENCE_CLOSE: Final = re.compile(r"^`{3,}\s*$")
_SIGNAL_ROW: Final = re.compile(r"^\|\s*`([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`\s*\|")
_CELL: Final = re.compile(r"(?<!\\)\|")
_NUMBERED: Final = re.compile(r"^\d\d-")

SIGNAL_COLUMNS: Final = 10
"""05-ingest-and-routing.md section 5.1's header: key, scope, kind, dtype, domain, cost, est, null,
req, provider(s). `null` is index 7 and is the column check 4 reads."""
NULL_COLUMN: Final = 7

COMBINATORS: Final = frozenset({"all", "any", "not", "all_of", "any_of", "none_of"})
"""A `when` key that holds other clauses rather than naming a signal. The charter's section D4
fence spells them `all_of` / `any_of`; section 4.4's spells them the same way. A walk that missed
them would find six check-4 failures where ADR-4 measured seven -- which is how this set was
found."""

UNCHECKED_FENCES: Final[dict[str, str]] = {
    "jsonc": (
        "JSONC has no stdlib parser; the fences carry `...` elisions, and a hand-rolled comment "
        "stripper would be a second implementation of a parser this repository does not own"
    ),
    "sql": (
        "a dialect check needs a connection and a schema; applying DDL out of a document is a "
        "side effect a document gate has no standing to take"
    ),
    "yaml": "no yaml parser in any dependency group, and core may not grow one (INV-2)",
    "text": "not a language",
    "console": "a transcript of a session, not a program",
    "bash": "no stdlib parser; `bash -n` would need bash on every runner, including Windows",
    "markdown": "the document's own language, quoted",
    "abnf": "a grammar, quoted from its own RFC",
    "typescript": "the second language is TypeScript and its parser lives in `toolchains/`",
    "ts": "as `typescript`",
    "js": "as `typescript`",
    "rust": "quoted from a mined repository, not a language this project builds",
    "xml": "a fragment, not a document, so `ElementTree` would reject a correct quotation",
    "jsonl": "one JSON value per line; the fences elide lines, so the file is not the lines",
    "ebnf": "a grammar, quoted",
    "diff": "not a language",
    "": "an unlabelled fence names no parser, so clause (a) has nothing to apply",
}
"""Every fence language this script counts and does not check, each saying why.

The clause is *"every fenced block parses under the parser its fence names"*, so a fence naming no
language, or naming one no parser here implements, is outside it. Printed with its count on every
run: a reader comparing this list against the corpus is the only check on whether the clause's
coverage is what it claims, and a silently unchecked language would be the hole."""

PARSE_EXEMPT: Final[tuple[tuple[str, int, int, str], ...]] = (
    #  (document, the fence's opening line, the offending line, why)
    #  ---- the aligned one-line class body. A `class X(StrEnum): A="a"; B="b"` whose members
    #  continue on the next line at the column of the first member is a column layout, not python.
    ("docs/plan/_notes/charter.md", 1230, 1247, "`class Layer(StrEnum):`, members aligned"),
    ("docs/plan/03-document-model.md", 96, 110, "the same block, in its sole home"),
    ("docs/plan/_notes/charter.md", 5974, 5977, "`class Provenance(StrEnum):`, members aligned"),
    ("docs/plan/09-generation.md", 779, 782, "the same block, in its sole home"),
    #  ---- a member or a docstring at a column inside an aligned block
    ("docs/plan/_notes/charter.md", 2399, 2463, "`def read_set_digest` under a comment column"),
    ("docs/plan/_notes/charter.md", 7275, 7351, "a docstring at an aligned field block's column"),
    ("docs/plan/18-api-sketch.md", 260, 461, "a docstring at an aligned field block's column"),
    ("docs/plan/18-api-sketch.md", 675, 718, "a docstring at an aligned field block's column"),
    #  ---- the rest, one cause each
    ("docs/plan/_notes/charter.md", 4257, 4326, "a box-drawing tree diagram in a python fence"),
    ("docs/plan/03-document-model.md", 1873, 1889, "four `def`s split by `;`, not python"),
    ("docs/plan/15-observability.md", 1344, 1346, "a quoted fragment of another project's code"),
)
"""The eleven python fences that do not parse, every one in a frozen document.

The shape of this list is the one `plan_lint.py`'s docstring argues for and the one
`test_core_eager_surface.py`'s `FILLED_HOMES` and `test_p2_freeze.py`'s `FROZEN_SURFACES` already
use twice: an explicit list, one row per locus, each naming WHY, and the check run in both
directions so a row that stops being a finding fails the gate. The alternative -- widening the
clause until these pass -- would be a clause that no longer says what it says.

Ten of the eleven are typography: a design record aligns a one-line class body or a field block
into columns a reader can scan, and python's grammar does not allow it. The eleventh is a verbatim
quotation of another project's source, which cannot be made to parse without falsifying the quote.
Fixing any of them means editing `charter.md` sections 1-8 (*"No line of 1-8 was edited ... and
none will be"*) or a document `tools/plan.sha256` pins -- a `--bless` whose recorded reason would
be "to satisfy a formatter"."""

A2_EXPECTED: Final[tuple[tuple[str, int, str], ...]] = (
    (
        "docs/plan/_notes/charter.md",
        2739,
        "the `when` clause of `repair.never-escalate-furniture`, in the section D4 fence ADR-4 "
        "decision 1 retires IN WHOLE under charter erratum E42",
    ),
)
"""ADR-4 decision 1's measurement, as a register: *"One inline table spans a newline, not two, and
it is a `when` rather than a `then`."* Retired law in a frozen region, so the finding stands and
the gate reports it as expected rather than as a defect."""

CHARTER_D4: Final = "docs/plan/_notes/charter.md"
"""The one document every A3_EXPECTED row names, spelled once so the rows fit a reader's eye."""

A3_EXPECTED: Final[tuple[tuple[str, int, str, str], ...]] = (
    #  (document, the fence's opening line, the rule id, the nullable key it reads)
    (CHARTER_D4, 2576, "gate.form-is-a-signal-not-an-exclusion", "corpus.is_form"),
    (CHARTER_D4, 2576, "decode.pdf-text-layer", "decode.char_count"),
    (CHARTER_D4, 2576, "decode.blank-part-escape", "ink.tiles"),
    (CHARTER_D4, 2576, "repair.never-escalate-furniture", "block.type"),
    (CHARTER_D4, 2576, "repair.promote-to-part", "block.flagged_frac"),
    (CHARTER_D4, 2576, "regen.output-invalid", "verify.finish_reason"),
    (CHARTER_D4, 2576, "degrade.marked-fallback", "verify.attempts_exhausted"),
)
"""The seven ADR-4 decision 1 counted, every one in the retired section D4 fence and none in
05-ingest-and-routing.md section 4.4's forty.

*"(a) seven rules there fail lint check 4 (`OW-P-004`), not nine, against zero in section 4.4 --
and one of the seven is dangerous rather than merely non-compliant,
`repair.never-escalate-furniture` reading `block.type`, which has no PDF provider, so without
`on_unknown = "match"` the furniture guard is silently off on the PDF path and one flagged footer
spawns the inference server for a clean document."* The row for that rule is why this list is
`(id, key)` pairs and not a count: the dangerous one has to be identifiable in the register, not
merely included in a total.

A rule reading several nullable keys is one row, naming the first in sorted order, because the
finding is about the rule."""

__all__ = [
    "A2_EXPECTED",
    "A3_EXPECTED",
    "PARSE_EXEMPT",
    "UNCHECKED_FENCES",
    "Fence",
    "Finding",
    "brace_depth_findings",
    "check_clause_a",
    "check_clause_a2",
    "check_clause_a3",
    "clause_c_state",
    "documents",
    "fences",
    "main",
    "nullability",
    "policy_documents",
    "rule_fences",
    "signal_keys_read",
]


@dataclass(frozen=True, slots=True)
class Fence:
    """One fenced block: where it opens, what language it names, and its body."""

    document: Path
    language: str
    line: int
    body: str

    @property
    def where(self) -> str:
        return f"{self.document.relative_to(REPO).as_posix()}:{self.line}"


@dataclass(frozen=True, slots=True)
class Finding:
    headline: str
    detail: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join((f"{PREFIX} FAIL: {self.headline}", *self.detail))


#  ---------------------------------------------------------------------------------------------
#  The corpus


def documents() -> tuple[Path, ...]:
    """Clause (a)'s scope: the committed design record, and not the deliberation behind it.

    The charter and the nineteen because a2 and a3 are worded over exactly those ("a ` ```toml `
    fence in `charter.md` or a plan document"); `README.md`, `glossary.md`, the ADRs and
    `docs/ARCHITECTURE.md` because they are the same record and carry fences on the same terms.

    NOT `_notes/panels/`, `_notes/rulings/` or the rest of `_notes/`. Those record a deliberation
    and quote other people's code: 93 of their fences do not parse, and every one of them is a
    faithful quotation of a partial snippet. A gate over them would be an instruction to falsify
    the record, which is the same reason `gate_invariants.py`'s A5 stops at the same boundary.
    """
    return (
        CHARTER,
        *sorted(path for path in PLAN.glob("*.md") if _NUMBERED.match(path.name)),
        PLAN / "README.md",
        PLAN / "glossary.md",
        *sorted((PLAN / "adr").glob("*.md")),
        REPO / "docs" / "ARCHITECTURE.md",
    )


def policy_documents() -> tuple[Path, ...]:
    """a2's and a3's scope, in the plan's own words: `charter.md` or a plan document."""
    return (
        CHARTER,
        *sorted(path for path in PLAN.glob("*.md") if _NUMBERED.match(path.name)),
    )


def fences(document: Path) -> list[Fence]:
    """Every fenced block, by its opening line.

    The closing run is matched on its own line and the opening run's length is remembered, because
    a nested four-backtick fence holding a three-backtick one is a shape the plan uses and a naive
    scanner closes the outer fence on the inner one's opener.
    """
    found: list[Fence] = []
    opener: str | None = None
    language, start, body = "", 0, []
    for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if opener is None:
            matched = _FENCE_OPEN.match(stripped)
            if matched is not None:
                opener, language, start, body = matched.group(1), matched.group(2), number, []
            continue
        if _FENCE_CLOSE.match(stripped) and len(stripped) >= len(opener):
            found.append(Fence(document, language, start, "\n".join(body)))
            opener = None
            continue
        body.append(line)
    return found


#  ---------------------------------------------------------------------------------------------
#  Clause (a)


def check_clause_a() -> tuple[list[str], list[Finding]]:
    parsers = {"toml": tomllib.loads, "json": json.loads, "python": ast.parse}
    exempt = {(path, line): why for path, line, _offending, why in PARSE_EXEMPT}
    counted: dict[str, int] = {}
    checked = 0
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for document in documents():
        if not document.is_file():
            findings.append(Finding(f"clause (a)'s scope names {document} and it is not a file."))
            continue
        for fence in fences(document):
            counted[fence.language] = counted.get(fence.language, 0) + 1
            parser = parsers.get(fence.language)
            if parser is None:
                if fence.language not in UNCHECKED_FENCES:
                    findings.append(
                        Finding(
                            f"{fence.where} names fence language {fence.language!r}, which has "
                            "neither a parser nor a row in UNCHECKED_FENCES.",
                            (
                                FAIL_INDENT
                                + "fix: add a parser, or a row saying why the clause does not "
                                + "reach it. An unlisted language is an unchecked one.",
                            ),
                        )
                    )
                continue
            checked += 1
            key = (fence.document.relative_to(REPO).as_posix(), fence.line)
            try:
                parser(fence.body)
            except (tomllib.TOMLDecodeError, json.JSONDecodeError, SyntaxError, ValueError) as why:
                seen.add(key)
                if key in exempt:
                    continue
                findings.append(
                    Finding(
                        f"{fence.where} is a ` ```{fence.language} ` fence that does not parse: "
                        f"{type(why).__name__}: {str(why).splitlines()[0][:90]}",
                        (
                            FAIL_INDENT
                            + "fix: the fence, or -- if the document is frozen and the block is "
                            + "quoted or typographic -- a PARSE_EXEMPT row saying which.",
                        ),
                    )
                )
    total = sum(counted.values())
    if total < FENCE_FLOOR:
        findings.insert(
            0,
            Finding(
                f"the fence scanner matched {total} fence(s), floor is {FENCE_FLOOR}.",
                (
                    FAIL_INDENT
                    + "every finding below is vacuous until this holds: a scanner that matches "
                    + "nothing reports nothing and exits 0.",
                ),
            ),
        )
    for path, line, _offending, why in PARSE_EXEMPT:
        if (path, line) not in seen:
            findings.append(
                Finding(
                    f"PARSE_EXEMPT {path}:{line} parses now ({why}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    report = [
        f"  clause (a)  {checked} fence(s) parsed under their own parser, "
        f"{len(PARSE_EXEMPT)} declared exception(s)",
        "  not checked "
        + ", ".join(
            f"{language or '(unlabelled)'} {count}"
            for language, count in sorted(counted.items())
            if language not in {"toml", "json", "python"}
        ),
    ]
    return report, findings


#  ---------------------------------------------------------------------------------------------
#  Clause (a2)


def _skip_string(line: str, index: int, quote: str) -> int:
    """Past the closing quote of a single-line string, or to the end of the line.

    A backslash escapes the next character inside a BASIC string only: TOML's literal strings,
    `'...'`, have no escapes at all, so treating one uniformly would read `'c:\\path\\'` as
    unterminated and swallow the rest of the line.
    """
    while index < len(line):
        if quote == '"' and line[index] == "\\":
            index += 2
            continue
        if line[index] == quote:
            return index + 1
        index += 1
    return index


def _walk_line(line: str, depth: int, multiline: str | None) -> tuple[int, str | None]:
    """One physical line of a toml fence, returning the brace depth and string state it leaves."""
    index = 0
    while index < len(line):
        rest = line[index:]
        if multiline is not None:
            if rest.startswith(multiline):
                multiline = None
                index += 3
            else:
                index += 1
            continue
        if rest.startswith(('"""', "'" * 3)):
            multiline = rest[:3]
            index += 3
            continue
        character = rest[0]
        if character in "\"'":
            index = _skip_string(line, index + 1, character)
            continue
        if character == "#":
            break
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
        index += 1
    return depth, multiline


def brace_depth_findings(body: str, first_line: int) -> list[tuple[int, int]]:
    """Every physical line that ends at brace depth >= 1, as `(line number, depth)`.

    A lexical walk, which is the clause. Outside a string, `#` opens a comment to end of line; a
    run of three quote characters opens a multi-line string and a single one opens a single-line
    string; and a backslash escapes the next character inside a basic string only, because TOML's
    literal strings have no escapes.
    """
    findings: list[tuple[int, int]] = []
    depth = 0
    multiline: str | None = None
    for offset, line in enumerate(body.splitlines()):
        depth, multiline = _walk_line(line, depth, multiline)
        if multiline is None and depth >= 1:
            findings.append((first_line + 1 + offset, depth))
    return findings


def check_clause_a2() -> tuple[list[str], list[Finding]]:
    expected = {(path, line): why for path, line, why in A2_EXPECTED}
    seen: set[tuple[str, int]] = set()
    scanned = 0
    findings: list[Finding] = []
    for document in policy_documents():
        for fence in fences(document):
            if fence.language != "toml":
                continue
            scanned += 1
            relative = fence.document.relative_to(REPO).as_posix()
            for line, depth in brace_depth_findings(fence.body, fence.line):
                seen.add((relative, line))
                if (relative, line) in expected:
                    continue
                findings.append(
                    Finding(
                        f"{relative}:{line} ends at brace depth {depth}, inside the ` ```toml ` "
                        f"fence at {fence.where}.",
                        (
                            FAIL_INDENT
                            + "the charter's four-times-stated style rule is \"a sub-table, NOT a "
                            + 'multi-line inline table". `tomllib` accepts this and always would; '
                            + "that is why the clause is lexical.",
                            FAIL_INDENT + "fix: a sub-table, or one line.",
                        ),
                    )
                )
    if scanned < TOML_FENCE_FLOOR:
        findings.insert(
            0, Finding(f"clause (a2) scanned {scanned} toml fence(s), floor is {TOML_FENCE_FLOOR}.")
        )
    for path, line, why in A2_EXPECTED:
        if (path, line) not in seen:
            findings.append(
                Finding(
                    f"A2_EXPECTED {path}:{line} no longer ends at depth >= 1 ({why}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    return [
        f"  clause (a2) {scanned} toml fence(s) walked, {len(A2_EXPECTED)} expected finding(s) "
        "(ADR-4 decision 1, charter erratum E42)"
    ], findings


#  ---------------------------------------------------------------------------------------------
#  Clause (a3) - the P1 interim standalone check 4


def nullability() -> dict[str, bool]:
    """05-ingest-and-routing.md section 5.1's `null` column, by signal key.

    Parsed out of the markdown table and not imported: ADR-4 decision 2's interim form is explicit
    that the standalone check reads the column *"rather than by importing `omniweave.route`"*, and
    `omniweave.route` does not exist until P5.
    """
    found: dict[str, bool] = {}
    for line in ROUTING.read_text(encoding="utf-8").splitlines():
        matched = _SIGNAL_ROW.match(line)
        if matched is None:
            continue
        cells = [one.strip() for one in _CELL.split(line.strip().strip("|"))]
        if len(cells) != SIGNAL_COLUMNS:
            continue
        null = cells[NULL_COLUMN].replace("*", "").strip().lower()
        if null in {"yes", "no"}:
            found[matched.group(1)] = null == "yes"
    return found


def signal_keys_read(when: object) -> list[tuple[str, object]]:
    """Every `(signal key, clause)` a `when` reads, descending through the combinators."""
    if not isinstance(when, dict):
        return []
    found: list[tuple[str, object]] = []
    for key, clause in when.items():
        if key in COMBINATORS:
            nested = clause if isinstance(clause, list) else [clause]
            for one in nested:
                found.extend(signal_keys_read(one))
            continue
        found.append((key, clause))
    return found


def rule_fences() -> list[tuple[Fence, list[dict[str, object]]]]:
    """Every toml fence in a3's scope that parses to a table containing a `[[rule]]` array."""
    found: list[tuple[Fence, list[dict[str, object]]]] = []
    for document in policy_documents():
        for fence in fences(document):
            if fence.language != "toml":
                continue
            try:
                parsed = tomllib.loads(fence.body)
            except tomllib.TOMLDecodeError:
                #  Clause (a) owns the parse failure; this clause reads what parses.
                continue
            rules = parsed.get("rule")
            if isinstance(rules, list):
                found.append((fence, [one for one in rules if isinstance(one, dict)]))
    return found


def check_clause_a3() -> tuple[list[str], list[Finding]]:
    null = nullability()
    expected = {(path, line, rule) for path, line, rule, _key in A3_EXPECTED}
    seen: set[tuple[str, int, str]] = set()
    findings: list[Finding] = []
    fence_count = 0
    rule_count = 0
    if not null:
        findings.append(
            Finding(
                "section 5.1's `null` column parsed to nothing, so check 4 is vacuous.",
                (
                    FAIL_INDENT
                    + "the column is load-bearing for this gate as well as for `ow route "
                    + "lint` (ADR-4 decision 2).",
                ),
            )
        )
    for fence, rules in rule_fences():
        fence_count += 1
        rule_count += len(rules)
        relative = fence.document.relative_to(REPO).as_posix()
        for rule in rules:
            identifier = str(rule.get("id", "<no id>"))
            read = signal_keys_read(rule.get("when"))
            if not read:
                continue
            if all(isinstance(one, dict) and set(one) == {"exists"} for _key, one in read):
                #  Check 4's own exception: an `exists`-only `when` cannot read UNKNOWN.
                continue
            nullable = sorted({key for key, _one in read if null.get(key, False)})
            if not nullable or "on_unknown" in rule:
                continue
            key = (relative, fence.line, identifier)
            seen.add(key)
            if key in expected:
                continue
            findings.append(
                Finding(
                    f"{relative}:{fence.line} rule {identifier!r} reads nullable "
                    f"{', '.join(nullable)} and declares no `on_unknown` (OW-P-004).",
                    (
                        FAIL_INDENT
                        + "check 4: every rule reading a nullable key declares `on_unknown`; a "
                        + "rule whose `when` is `exists`-only does not need one.",
                    ),
                )
            )
    for path, line, rule, key in A3_EXPECTED:
        if (path, line, rule) not in seen:
            findings.append(
                Finding(
                    f"A3_EXPECTED {path}:{line} {rule!r} passes check 4 now (it read {key}).",
                    (FAIL_INDENT + "fix: delete the row. The list may shrink and never grow.",),
                )
            )
    return [
        f"  clause (a3) standalone check 4 over {fence_count} `[[rule]]` fence(s), {rule_count} "
        f"rule(s), {len(null)} registry row(s) ({sum(null.values())} nullable), "
        f"{len(A3_EXPECTED)} expected finding(s)"
    ], findings


#  ---------------------------------------------------------------------------------------------
#  Clause (c), read from the register rather than restated


def clause_c_state() -> tuple[list[str], list[Finding]]:
    register = tomllib.loads(GATES.read_text(encoding="utf-8"))
    rows = register.get("gate", [])
    row = next(
        (one for one in rows if isinstance(one, dict) and str(one.get("id")) == "G27"),
        None,
    )
    if row is None:
        return [], [Finding("tools/gates.toml holds no G27 row.")]
    clauses = row.get("clause", [])
    clause = next(
        (one for one in clauses if isinstance(one, dict) and str(one.get("id")) == "c"),
        None,
    )
    if clause is None:
        return [], [Finding("G27's row holds no clause (c); ADR-1 decision 6 requires it.")]
    if clause.get("enabled"):
        return [], [
            Finding(
                "clause (c) is enabled in the register and this script does not run it.",
                (
                    FAIL_INDENT
                    + "ADR-1 decision 6's four turn-on conditions have to hold and the clause has "
                    + "to be implemented in the same change that enables it.",
                ),
            )
        ]
    return [
        f"  clause (c)  registered and OFF, blocked_by {clause.get('blocked_by', '?')}: "
        f"{clause.get('asserts')}"
    ], []


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stdout.write("usage: tools/gate_docs.py\n")
        return 2
    report: list[str] = []
    findings: list[Finding] = []
    for check in (check_clause_a, check_clause_a2, check_clause_a3, clause_c_state):
        lines, found = check()
        report.extend(lines)
        findings.extend(found)
    report.append(
        "  clause (d)  NOT IN THIS SCRIPT: section 8.6's d0-d4 walk of docs/ARCHITECTURE.md and "
        "docs/plan/*.md is the next cell; d's ARCHITECTURE.md half runs at the test tier "
        "(test_architecture_doc.py, D986)"
    )
    report.append(
        "  clause (b)  NOT IN THIS SCRIPT: tools/gate_migrations.py carries it (16-roadmap.md:453)"
    )
    for line in report:
        sys.stdout.write(line + "\n")
    if findings:
        for finding in findings:
            sys.stdout.write(finding.render() + "\n")
        sys.stdout.write(f"{PREFIX} FAILED: {len(findings)} finding(s)\n")
        return 1
    sys.stdout.write(
        f"{PREFIX} ok  clauses (a), (a2) and (a3) hold over "
        f"{len(documents())} document(s); (c) registered and off\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
