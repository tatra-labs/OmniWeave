"""`gates.risk_register` - the five rules over `tools/risks.toml`, plus what reads its own data.

Not a `G<n>`, and 17-risks.md section 1.1 settles why in its own words: 11-repo-layout.md section
8.6 "spends `G27(d)` on `gate_docs.py` ... That is the correct home for *identifier resolution* and
the wrong home for *semantic assertions over a register's rows*." So this is the `[[job_assertion]]`
`gates.risk_register`, job `gates`, budget **2 s** -- "one `tomllib.load`, five set-membership
passes over 60 rows and ~200 question keys, and one byte-diff of section 1.2's table". There is no
clause `e`.

`Q-G17`'s rot clock deliberately does not read this file: "the register's rot clock is rule 4 of
`gates.risk_register`, and one clock per register is the point of not having two homes for one key."
Rule 4 is therefore the clock, and it will fail the build after `review_by` exactly as Q-G17 fails a
gate row past its date. That is the design and not an accident -- section 1 says so: "There is no
non-blocking mode and no bypass flag."

## The five rules, in section 1's own numbering

**1. Every row's `indicator` resolves to a real instrument.** A `[[counter]]` id in
`eval/counters.toml`, a `[[budget]]` id in `eval/perf.toml`, a `[[gate]]`'s metric in
`eval/gates.toml`, a `G<n>` or `Q-G<n>` or a `[[job_assertion]]` name in `tools/gates.toml`, or a
code in `codes.toml`. "A row whose indicator is a sentence is a row nobody will ever notice
materialising, and it fails."

Measured over section 3's own sixty rows, **twenty-one resolve**. The other thirty-nine name a
real, leading, specific instrument that is not a row in one of those six registers, and
`tools/risks.toml`'s header says why for each. So rule 1 runs as a hard check over the
twenty-one and a RATCHET over the thirty-nine: a row that leaves the declared set without
resolving fails, a declared row that resolves and keeps its declaration fails, and the count may
fall and never rise. Widening rule 1's six registers until the sentence came true would be the
checker rewriting the rule it exists to obey.

**2. Every row with `likelihood * impact >= 12` carries a non-empty `contingency`.** Twenty rows
clear that score and all twenty carry one. "Above that score, 'we will think about it then' is not
a plan."

**3. Every `questions` key resolves** to a row in section 7.2, 7.3 or 7.4 -- 162 keys, "so closing
an open question mechanically lists the risks it retires". One row of the sixty cites a key, and
that is faithful: section 3's table has no questions column, so a `questions` array populated by
guessing which of 162 keys each row relates to would be invention rather than transcription.

**4. Every row carries an `owner` from the ten roles, a `reviewed_at` and a `review_by`**, with
`review_by - reviewed_at <= review_every_days`. Plus section 1.2's **derived** risks column:
"The register check regenerates it from `tools/risks.toml`'s `owner` fields and byte-diffs it
against this table, exactly as `ow surface emit --check` treats a generated agent-facing
artefact. A hand-edited cell fails `gates.risk_register`."

The sets and the counts match for all ten roles. The ORDER matches for nine: section 1.2's
`licence` row lists its `R-L*` rows before its `R-E*` ones, where the other nine roles and
section 3's own table order put Ecosystem before Legal. That is one hand-ordered cell in a frozen
document, it is declared in `ORDER_EXCEPTION`, and a second divergence fails.

**5. Every `kill` value resolves to a criterion in section 5, and every criterion in section 5 is
reached by at least one row.** Thirteen criteria, all defined and all reached. "A kill criterion
nothing can reach is decoration; a risk whose worst case is a stop with no criterion is an unpriced
exit."

## And three structural checks, because five rules over the wrong rows are five wrong rules

**S1 the register is section 3's register** -- sixty rows, ids unique, every row's `source` line
present and holding its id, and every `title`, `trigger`, `mitigation` and `contingency` equal to
the folded source cell. Sixty rows transcribed by hand would rot; none of them is trusted.

**S2 section 4's paths** -- every `P<n>` the register names has at least two member rows, which is
section 4's own sentence, and every path section 4 defines is named by the register.

**S3 the floor** -- sixty rows, asserted before any rule reports. A loader that returned nothing
would make every rule above pass over an empty set, which is the C55 shape this repository keeps
paying for.

Exit 0 clean, 1 with one `gates.risk_register FAIL` block per finding, 2 on a usage error.
Specified in 17-risks.md sections 1, 1.1, 1.2, 3, 4, 5 and 7, and ADR-2 decision 2 (`RK-Q1`).
"""

from __future__ import annotations

import collections
import datetime as dt
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
REGISTER: Final[Path] = REPO / "tools" / "risks.toml"
DOC: Final[Path] = REPO / "docs" / "plan" / "17-risks.md"
QUALITY: Final[Path] = REPO / "docs" / "plan" / "13-quality.md"

PREFIX: Final = "gates.risk_register"
FAIL_INDENT: Final = "    "
ROWS: Final = 60
HIGH_SCORE: Final = 12
"""Rule 2's threshold, in section 1's own words: `likelihood * impact >= 12`."""

PATH_MEMBERS: Final = 2
"""Section 4: `gates.risk_register` asserts every `P<n>` has at least two member rows."""

SCALE: Final = range(1, 6)
"""Section 2's scales: both `likelihood` and `impact` are 1..5."""

FOLD: Final[tuple[tuple[str, str], ...]] = (
    (chr(0x2014), " -- "),
    (chr(0x2192), " -> "),
    (chr(0x2265), ">="),
    (chr(0x2264), "<="),
    (chr(0x00D7), "x"),
    (chr(0x2020), "(unbuilt)"),
    (chr(0x00A7), "section "),
    (chr(0x2026), "..."),
    (chr(0x2248), "~"),
    (chr(0x00B1), "+/-"),
    (chr(0x2212), "-"),
    (chr(0x03BA), "kappa"),
    (chr(0x2019), "'"),
    (chr(0x201C), '"'),
    (chr(0x201D), '"'),
    (chr(0x00A0), " "),
    (chr(0x21D2), "=>"),
    (chr(0x00B5), "u"),
)
"""The register's declared substitution table, in its declared order. Applied nowhere else."""

KIND_REASON: Final[dict[str, str]] = {
    "counter_owed": (
        "the document marks the id with a dagger, which section 3 defines as an id that does not "
        "yet exist and is added to eval/counters.toml or eval/perf.toml by 13-quality.md and "
        "15-observability.md IN THE SAME CHANGE THAT MERGES THIS DOCUMENT. That change did not "
        "happen, so the instrument is owed by two other documents"
    ),
    "target_state": (
        "a Target's GateStatus, a per-run verdict in an OUT receipt rather than a register row"
    ),
    "store_column": (
        "a column of a store or graph table -- a real instrument, and a better one than a counter "
        "for this row, and not one of rule 1's six registers"
    ),
    "conformance_suite": (
        "a conformance suite's pass or fail, which omniweave_conform owns and no register "
        "enumerates by assertion"
    ),
    "property_test": (
        "a named property test in 13-quality.md section 6, which carries no register row"
    ),
    "benchmark_harness": (
        "a bench/serve/ harness number. The harness is specified and not built, so there is "
        "nothing for an id to point at yet"
    ),
    "acceptance_path": (
        "a measurement on an acceptance criterion's own path, which tools/acceptance_v10.py runs "
        "and eval/published_numbers.toml publishes rather than any of rule 1's registers"
    ),
    "register_field": (
        "a FIELD of a register rather than a row id. Rule 1 resolves row ids, and a field of a "
        "row is a different kind of name"
    ),
    "receipt_field": (
        "a field of an OUT receipt or a driver attestation, which is per-run output rather than a "
        "register row"
    ),
    "cli_exit": (
        "a CLI verb's exit code or output. The verb resolves against ACTIONS under G27 clause d2; "
        "its EXIT is an observation, and rule 1's registers hold no exit codes except "
        "codes.toml's, which this row's trigger does not name"
    ),
    "project_observation": (
        "an observation about the project rather than about a run -- an advisory's age, one "
        "author's share of commits, what adoption feedback says. Real, leading, and nothing a "
        "register can hold"
    ),
}
"""Why each `kind` of `[[unmetered]]` row cannot resolve under rule 1 as written.

Here rather than in the register, beside the check that reads it: one home, not two. A `kind` in
the register with no row here is a finding."""

ORDER_EXCEPTION: Final[dict[str, str]] = {
    "licence": (
        "section 1.2's cell lists this role's `R-L*` rows before its `R-E*` ones, where the other "
        "nine roles and section 3's own table order put Ecosystem before Legal. One hand-ordered "
        "cell in a frozen document; the set and the count match, and a second divergence fails"
    )
}
"""Rule 4's byte-diff, and the one cell it does not hold to section 3's order."""

_CELL: Final = re.compile(r"(?<!\\)\|")
_ROW: Final = re.compile(r"^\|\s*\*\*(R-[A-Z]+\d+)\*\*\s*\|")
_ROLE_ROW: Final = re.compile(r"^\| `([a-z]+)` \|")
_KILL_ROW: Final = re.compile(r"^\|\s*\*\*(K-\d+)\*\*", re.MULTILINE)
_QUESTION_ROW: Final = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)
_PATH_HEAD: Final = re.compile(r"\*\*(P\d) " + chr(0x2014) + " ")
_RISK_ID: Final = re.compile(r"(?<![\w-])R-[A-Z]+\d+")
_QG: Final = re.compile(r"^\|\s*`?(Q-G\d+)", re.MULTILINE)

__all__ = [
    "FOLD",
    "KIND_REASON",
    "ORDER_EXCEPTION",
    "Finding",
    "check_floor",
    "check_indicators",
    "check_kills",
    "check_owners",
    "check_paths",
    "check_questions",
    "check_scores",
    "check_sources",
    "fold",
    "instruments",
    "main",
]


@dataclass(frozen=True, slots=True)
class Finding:
    headline: str
    detail: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join((f"{PREFIX} FAIL: {self.headline}", *self.detail))


def fold(text: str) -> str:
    """The register's fold, and the unescaping a markdown cell needs."""
    for before, after in FOLD:
        text = text.replace(before, after)
    return " ".join(text.replace("\\|", "|").split())


def _table(parsed: dict[str, object], key: str) -> list[dict[str, object]]:
    rows = parsed.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _str(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _strs(row: dict[str, object], key: str) -> list[str]:
    value = row.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(one) for one in value]


def _int(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    return value if isinstance(value, int) else 0


def instruments() -> dict[str, frozenset[str]]:
    """Rule 1's six registers, each as the set of row ids it holds."""
    counters = tomllib.loads((REPO / "eval" / "counters.toml").read_text(encoding="utf-8"))
    perf = tomllib.loads((REPO / "eval" / "perf.toml").read_text(encoding="utf-8"))
    metric = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
    gates = tomllib.loads((REPO / "tools" / "gates.toml").read_text(encoding="utf-8"))
    codes = tomllib.loads((REPO / "codes.toml").read_text(encoding="utf-8"))
    return {
        "counter": frozenset(_str(one, "id") for one in _table(counters, "counter")),
        "budget": frozenset(_str(one, "id") for one in _table(perf, "budget")),
        "metric": frozenset(_str(one, "metric") for one in _table(metric, "gate")),
        "gate": frozenset(_str(one, "id") for one in _table(gates, "gate")),
        "job_assertion": frozenset(_str(one, "name") for one in _table(gates, "job_assertion")),
        "code": frozenset(
            {_str(one, "numeric") for one in _table(codes, "code")}
            | {_str(one, "symbol") for one in _table(codes, "code")}
        ),
        "quality_gate": frozenset(_QG.findall(QUALITY.read_text(encoding="utf-8"))),
    }


#  ---------------------------------------------------------------------------------------------
#  S3, then the five rules


def check_floor(rows: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    findings: list[Finding] = []
    if len(rows) != ROWS:
        findings.append(
            Finding(
                f"the register holds {len(rows)} `[[risk]]` row(s); section 3 holds {ROWS}.",
                (
                    FAIL_INDENT
                    + "every rule below passes over an empty set, so this is asserted first.",
                ),
            )
        )
    counted = collections.Counter(_str(one, "id") for one in rows)
    for identifier, times in sorted(counted.items()):
        if times != 1:
            findings.append(Finding(f"{identifier} appears in {times} rows."))
    return [f"  rows        {len(rows)} of {ROWS}, ids unique"], findings


def check_indicators(
    rows: list[dict[str, object]], unmetered: list[dict[str, object]]
) -> tuple[list[str], list[Finding]]:
    """Rule 1: hard over the rows that resolve, ratcheted over the declared ones."""
    known = instruments()
    declared = {_str(one, "risk"): one for one in unmetered}
    findings: list[Finding] = []
    resolved = 0
    for row in rows:
        identifier = _str(row, "id")
        indicator = _str(row, "indicator")
        where = next((name for name, members in known.items() if indicator in members), "")
        if indicator and where:
            resolved += 1
            if identifier in declared:
                findings.append(
                    Finding(
                        f"{identifier}: indicator {indicator!r} resolves in {where} and the row "
                        "still has an [[unmetered]] declaration.",
                        (FAIL_INDENT + "fix: delete the declaration. The list may only shrink.",),
                    )
                )
            stated = _str(row, "resolves_in")
            if stated and stated != where:
                findings.append(
                    Finding(f"{identifier}: resolves_in says {stated!r}, found in {where!r}.")
                )
            continue
        if identifier not in declared:
            findings.append(
                Finding(
                    f"{identifier}: indicator {indicator!r} resolves in none of rule 1's "
                    "registers and the row is not declared.",
                    (
                        FAIL_INDENT + f"trigger: {_str(row, 'trigger')[:100]}",
                        FAIL_INDENT
                        + "fix: an indicator that resolves, or an [[unmetered]] row saying what "
                        + "the cell names and which kind of instrument it is.",
                    ),
                )
            )
            continue
        kind = _str(declared[identifier], "kind")
        if kind not in KIND_REASON:
            findings.append(
                Finding(
                    f"{identifier}: [[unmetered]] kind {kind!r} has no row in KIND_REASON.",
                    (FAIL_INDENT + f"known kinds: {sorted(KIND_REASON)}",),
                )
            )
        if not _str(declared[identifier], "names").strip():
            findings.append(Finding(f"{identifier}: [[unmetered]] names nothing."))
    held = {_str(one, "id") for one in rows}
    for one in unmetered:
        if _str(one, "risk") not in held:
            findings.append(
                Finding(f"[[unmetered]] {_str(one, 'risk')} is not a row of this register.")
            )
    if len(unmetered) > len(rows) - resolved:
        findings.append(
            Finding(
                f"{len(unmetered)} declaration(s) for {len(rows) - resolved} unresolved row(s).",
            )
        )
    kinds = collections.Counter(_str(one, "kind") for one in unmetered)
    report = [
        f"  rule 1      {resolved} indicator(s) resolve, {len(unmetered)} declared unmetered",
        "              " + ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items())),
    ]
    return report, findings


def check_scores(rows: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    """Rule 2: `likelihood * impact >= 12` carries a contingency."""
    findings: list[Finding] = []
    high = 0
    for row in rows:
        likelihood, impact = _int(row, "likelihood"), _int(row, "impact")
        if likelihood not in SCALE or impact not in SCALE:
            findings.append(
                Finding(
                    f"{_str(row, 'id')}: likelihood {likelihood} and impact {impact}; "
                    f"section 2's scales are {SCALE.start}..{SCALE.stop - 1}."
                )
            )
        if likelihood * impact < HIGH_SCORE:
            continue
        high += 1
        contingency = _str(row, "contingency").strip()
        if not contingency or contingency == "--":
            findings.append(
                Finding(
                    f"{_str(row, 'id')}: scores {likelihood}x{impact} and carries no contingency.",
                    (
                        FAIL_INDENT
                        + 'section 1 rule 2: above that score, "we will think about it then" is '
                        + "not a plan.",
                    ),
                )
            )
    line = f"  rule 2      {high} row(s) at or above {HIGH_SCORE}, each with a contingency"
    return [line], findings


def check_questions(rows: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    """Rule 3: every `questions` key is a row of section 7.2, 7.3 or 7.4."""
    text = DOC.read_text(encoding="utf-8")
    defined: set[str] = set()
    for part in ("7.2", "7.3", "7.4"):
        start = text.index(f"### {part} ")
        following = [
            text.index(f"### 7.{one} ")
            for one in range(int(part[-1]) + 1, 8)
            if f"### 7.{one} " in text
        ]
        defined.update(_QUESTION_ROW.findall(text[start : min(following, default=len(text))]))
    findings: list[Finding] = []
    cited = 0
    for row in rows:
        for key in _strs(row, "questions"):
            cited += 1
            if key not in defined:
                findings.append(
                    Finding(
                        f"{_str(row, 'id')}: question key {key!r} is in no section 7.2-7.4 row."
                    )
                )
    return [
        f"  rule 3      {cited} question key(s) cited, {len(defined)} defined in sections 7.2-7.4"
    ], findings


def check_owners(
    register: dict[str, object], rows: list[dict[str, object]]
) -> tuple[list[str], list[Finding]]:
    """Rule 4: the owner, the two dates, the rot clock, and section 1.2's derived column."""
    header = register.get("register")
    header = header if isinstance(header, dict) else {}
    roles = _strs(header, "owner_roles")
    window = _int(header, "review_every_days")
    text = DOC.read_text(encoding="utf-8")
    start, end = text.index("### 1.2 "), text.index("## 2. The scales")
    cells: dict[str, str] = {}
    for line in text[start:end].splitlines():
        matched = _ROLE_ROW.match(line)
        if matched:
            parts = [one.strip() for one in _CELL.split(line.strip().strip("|"))]
            cells[matched.group(1)] = parts[-1]
    findings: list[Finding] = []
    if sorted(roles) != sorted(cells):
        findings.append(
            Finding(
                "[register] owner_roles is not section 1.2's ten roles.",
                (
                    FAIL_INDENT + f"register: {sorted(roles)}",
                    FAIL_INDENT + f"document: {sorted(cells)}",
                ),
            )
        )
    today = dt.date.today()  # noqa: DTZ011 -- a date, and the rot clock is a date comparison.
    by_owner: dict[str, list[str]] = collections.defaultdict(list)
    for row in rows:
        identifier, owner = _str(row, "id"), _str(row, "owner")
        if owner not in roles:
            findings.append(Finding(f"{identifier}: owner {owner!r} is not one of the ten roles."))
        else:
            by_owner[owner].append(identifier)
        try:
            reviewed = dt.date.fromisoformat(_str(row, "reviewed_at"))
            review_by = dt.date.fromisoformat(_str(row, "review_by"))
        except ValueError:
            findings.append(Finding(f"{identifier}: reviewed_at or review_by is not an ISO date."))
            continue
        if (review_by - reviewed).days > window:
            findings.append(
                Finding(
                    f"{identifier}: review_by is {(review_by - reviewed).days} days after "
                    f"reviewed_at; review_every_days is {window}."
                )
            )
        if review_by < today:
            findings.append(
                Finding(
                    f"{identifier}: review_by {review_by} has passed.",
                    (
                        FAIL_INDENT
                        + "section 1 rule 4: a row past review_by fails the build, exactly as "
                        + "Q-G17 fails a gate row past its date. There is no bypass flag.",
                    ),
                )
            )
    findings.extend(_derived_column(cells, by_owner, rows))
    return [
        f"  rule 4      {len(roles)} role(s), {len(rows)} row(s) dated, window {window} days, "
        f"next due {min((_str(one, 'review_by') for one in rows), default='-')}",
        f"              section 1.2's derived column regenerated, "
        f"{len(ORDER_EXCEPTION)} declared order exception(s)",
    ], findings


def _derived_column(
    cells: dict[str, str], by_owner: dict[str, list[str]], rows: list[dict[str, object]]
) -> list[Finding]:
    """Rule 4's second half: section 1.2's risks column, regenerated and compared.

    "The register check regenerates it from `tools/risks.toml`'s `owner` fields and byte-diffs it
    against this table, exactly as `ow surface emit --check` treats a generated agent-facing
    artefact. A hand-edited cell fails `gates.risk_register`."
    """
    findings: list[Finding] = []
    order = {_str(row, "id"): index for index, row in enumerate(rows)}
    for role, cell in sorted(cells.items()):
        documented = _RISK_ID.findall(cell)
        mine = sorted(by_owner.get(role, []), key=lambda one: order.get(one, 0))
        if set(documented) != set(mine):
            findings.append(
                Finding(
                    f"section 1.2's {role} cell is not the register's rows for that owner.",
                    (
                        FAIL_INDENT + f"document: {documented}",
                        FAIL_INDENT + f"register: {mine}",
                    ),
                )
            )
            continue
        stated = re.search(r"\((\d+)\)", cell)
        if stated and int(stated.group(1)) != len(mine):
            findings.append(
                Finding(
                    f"section 1.2's {role} cell says ({stated.group(1)}), "
                    f"the register has {len(mine)}."
                )
            )
        if documented != mine and role not in ORDER_EXCEPTION:
            findings.append(
                Finding(
                    f"section 1.2's {role} cell is in a different order from section 3's table.",
                    (
                        FAIL_INDENT + f"document: {documented}",
                        FAIL_INDENT + f"register: {mine}",
                        FAIL_INDENT
                        + "fix: the cell, or an ORDER_EXCEPTION row if the document's order is "
                        + "deliberate and frozen.",
                    ),
                )
            )
        if documented == mine and role in ORDER_EXCEPTION:
            findings.append(
                Finding(
                    f"ORDER_EXCEPTION holds {role} and its cell is in table order now.",
                    (FAIL_INDENT + "fix: delete the row.",),
                )
            )
    return findings


def check_kills(rows: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    """Rule 5, both directions."""
    text = DOC.read_text(encoding="utf-8")
    body = text[text.index("## 5. Kill criteria") : text.index("## 6. Assumptions")]
    defined = set(_KILL_ROW.findall(body))
    reached: set[str] = set()
    findings: list[Finding] = []
    for row in rows:
        for criterion in _strs(row, "kill"):
            reached.add(criterion)
            if criterion not in defined:
                findings.append(
                    Finding(f"{_str(row, 'id')}: kill {criterion!r} is in no section 5 row.")
                )
    unreached = sorted(defined - reached, key=lambda one: int(one.split("-")[1]))
    if unreached:
        findings.append(
            Finding(
                f"{len(unreached)} kill criterion/criteria no row can reach: "
                + ", ".join(unreached),
                (
                    FAIL_INDENT
                    + "section 1 rule 5: a kill criterion nothing can reach is decoration.",
                ),
            )
        )
    return [
        f"  rule 5      {len(defined)} criterion/criteria in section 5, all reached by "
        f"{sum(1 for one in rows if _strs(one, 'kill'))} row(s)"
    ], findings


def check_paths(rows: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    """S2: section 4's own sentence -- every `P<n>` has at least two member rows."""
    text = DOC.read_text(encoding="utf-8")
    body = text[text.index("## 4. Compound paths") : text.index("## 5. Kill criteria")]
    defined = set(_PATH_HEAD.findall(body))
    membership: dict[str, int] = collections.Counter()
    findings: list[Finding] = []
    for row in rows:
        for path in _strs(row, "paths"):
            membership[path] += 1
            if path not in defined:
                findings.append(
                    Finding(f"{_str(row, 'id')}: path {path!r} is in no section 4 heading.")
                )
    for path in sorted(defined):
        if membership[path] < PATH_MEMBERS:
            findings.append(
                Finding(
                    f"{path} has {membership[path]} member row(s); section 4 asserts "
                    f"at least {PATH_MEMBERS}.",
                )
            )
    return [
        f"  paths       {len(defined)} path(s), "
        + ", ".join(f"{path} {membership[path]}" for path in sorted(defined))
    ], findings


def check_sources(rows: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    """S1: every row checked against the line it was read from, not trusted."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    findings: list[Finding] = []
    for row in rows:
        identifier = _str(row, "id")
        relative, _, number = _str(row, "source").rpartition(":")
        if relative != "docs/plan/17-risks.md" or not number.isdigit():
            findings.append(Finding(f"{identifier}: source {_str(row, 'source')!r} is not a line."))
            continue
        index = int(number) - 1
        if not 0 <= index < len(lines):
            findings.append(Finding(f"{identifier}: source line {number} is past the end."))
            continue
        line = lines[index]
        matched = _ROW.match(line)
        if matched is None or matched.group(1) != identifier:
            findings.append(
                Finding(
                    f"{identifier}: source line {number} does not open that row.",
                    (FAIL_INDENT + f"line: {line.strip()[:90]}",),
                )
            )
            continue
        cells = [one.strip() for one in _CELL.split(line.strip().strip("|"))]
        for key, index_in_row in (
            ("title", 1),
            ("trigger", 4),
            ("mitigation", 5),
            ("contingency", 6),
        ):
            if fold(cells[index_in_row]) != _str(row, key):
                findings.append(
                    Finding(
                        f"{identifier}: {key} is not the folded source cell.",
                        (
                            FAIL_INDENT + f"source: {fold(cells[index_in_row])[:110]}",
                            FAIL_INDENT + f"row:    {_str(row, key)[:110]}",
                        ),
                    )
                )
    return [f"  sources     {len(rows)} row(s) checked against their own line"], findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stdout.write("usage: tools/risk_register.py\n")
        return 2
    if not REGISTER.is_file():
        sys.stdout.write(
            f"{PREFIX} FAIL: tools/risks.toml is not committed.\n"
            f"{FAIL_INDENT}17-risks.md section 1 specifies it: the register is data, not prose.\n"
        )
        return 1
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    rows = _table(register, "risk")
    unmetered = _table(register, "unmetered")
    report: list[str] = []
    findings: list[Finding] = []
    for lines, found in (
        check_floor(rows),
        check_indicators(rows, unmetered),
        check_scores(rows),
        check_questions(rows),
        check_owners(register, rows),
        check_kills(rows),
        check_paths(rows),
        check_sources(rows),
    ):
        report.extend(lines)
        findings.extend(found)
    for line in report:
        sys.stdout.write(line + "\n")
    if findings:
        for finding in findings:
            sys.stdout.write(finding.render() + "\n")
        sys.stdout.write(f"{PREFIX} FAILED: {len(findings)} finding(s)\n")
        return 1
    sys.stdout.write(
        f"{PREFIX} ok  {len(rows)} risk(s) over 10 owners, five rules hold, "
        f"{len(unmetered)} indicator(s) declared unmetered\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
