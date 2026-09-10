"""Q-G15's static half: a LINTER over `eval/perf.toml`. It measures nothing, ever.

12-performance.md:231 names this file and states its job in one sentence: *"`tools/gate_budgets.py`
asserts presence and vocabulary membership under `Q-G15` alongside its `value + tol_abs <= tier
ceiling` clause ([13](13-quality.md) section 2.9)"*. 13-quality.md:1999 renders the same row of the
Q-G table: *"`eval/perf.toml` on `ow-bench-1`; Pacer ratios, absolute memory, exact counters,
section 2.9's `value + tol_abs <= ceiling`, and `process` present and in vocabulary on every `rss.`
row"*.

## What this is NOT

It is not `ow eval perf`. That verb runs the Pacer, opens a store, times things on `ow-bench-1` and
compares a measured figure against a row here; it is W10.6 and it is P10. The names sit next to each
other in the plan and confusing the two would be very easy, so it is worth being blunt: **this
script never opens a store, never imports omniweave, never starts a timer and never reads a
measurement.** It reads one TOML file and asserts things about its rows. Every failure it can emit
is a defect in the register, and none is a performance regression.

The split follows the standing pattern for a P2-stage instrument whose CLI home is a later phase
(ruling D25, worked in `tools/gate_crash.py`'s docstring): the library-or-script half lands now and
a `ow eval perf` wrapper arrives with P10. Nothing here waits on that.

## The four clauses, and the defect each one is the only witness for

1. **The row schema** (12-performance.md:215-225, which declares itself the schema's *sole home*).
   `id` matches `[a-z0-9_.]{1,64}` and is unique; `value` is `int|float`; exactly one of `tol_pct`
   (`int`, 0-100) and `tol_abs` (`int|float`); `gate` is `pr` or `nightly`; **an unknown key is a
   hard error at load**. The defect: a row that reads plausibly and gates nothing, because the
   runner looked for `tolerance_pct` and found no key by that name.
2. **`process` presence and vocabulary on every `rss.` row, and its rejection everywhere else**
   (13-quality.md:368-375, ADR-11 D5, charter section 9.2 `E88`). The defect is stated at
   13-quality.md:371-374 and it is not a typo class: `rss.merged4mcell_peak_bytes = 4 GiB` bounds a
   **worker**, and a reader who takes it for a whole-host figure sets sixteen workers against it and
   gets an OOM kill at hour six instead of `ow doctor`'s refusal before the run.
3. **`value + tolerance <= the tier ceiling`** (13-quality.md:351-366). The pyramid states ceilings
   and this register states budgets with tolerances; *"Nothing in the charter connects them, and a
   budget whose `value + tol_abs` exceeds its tier ceiling is a budget that can pass while the tier
   is over"*. The check is **non-strict on purpose** -- 13-quality.md:365-366: two charter rows sit
   exactly on their ceilings and *"tightening it to `<` would fail the charter rather than a
   mistake"*.
4. **The file is not empty and the ceiling table is not vacuous.** Both counts are printed on every
   run, pass or fail, because a linter whose subject silently disappeared reports the same
   green as a linter that checked fifteen rows. `tools/gate_weights.py` prints its two numbers
   unconditionally for the same reason.

## The tolerance is generalised from `tol_abs` to `tol_pct`, and the plan does that itself

Section 2.9 writes the clause as `value + tol_abs <= ceiling`, and only three shipped rows carry
`tol_abs`. 12-performance.md:178-179 states the same property for the percentage rows in the
percentage form -- *"The `eval/perf.toml` budget for each is set so that **budget x (1 + tolerance)
lands just inside the ceiling**"* -- and 12-performance.md:184-188 tabulates the four results
(77.5 / 147.5 / 216 ms and the two `none` rows that 12-performance.md:195-198 then fills in). So the
worst case of a `tol_pct` row is `value * (1 + tol_pct/100)` and the two spellings are one clause.

The arithmetic runs in `fractions.Fraction`, not in `float`. `660 * (1 + 10 / 100)` is
`726.0000000000001` in binary floating point -- `store.bytes_per_block`, the row P2 exists to
measure -- and `16 * 1.2` is a double that prints as `19.2` while not being the decimal 19.2. A
gate that rejected a row for either would be reporting an artefact of the base rather than a defect
in the register, so `Fraction` over the decimal SPELLING of each number makes the comparison the one
the plan did on paper.

## Where the ceilings live, and why they are not in the register

They cannot be in `eval/perf.toml`: the row schema has no key for a ceiling and an unknown key is a
hard error. They are plan facts -- V01-3's four cold-start ceilings (00-vision.md:704, tabulated at
12-performance.md:182-188) and the test pyramid's per-tier seconds (13-quality.md:60-71) -- so they
are transcribed into `CEILINGS` below, one citation per row. A row the plan gives no tier is not
checked and is *named* in the output rather than counted as passing: 13-quality.md:357-358 scopes
the clause to *"every row carrying a tier"*.

## This script has no row in `tools/gates.toml`, and that is the register's own ruling

`tools/gates.toml` holds the `G` series only. Its header (tools/gates.toml:95-102) states the rule
and its source: `eval/gates.toml` holds the metric gates *"-- `structure_f1`, `hallucination_rate`,
the Q-G series -- with their own owners, review dates and guards"*, and *"neither file may name a
row the other owns"* (11-repo-layout.md section 1.7), and
`test_gates_register.py::test_no_q_g_row_lives_here` enforces it from the other side.
`eval/gates.toml` does not exist at P2. The consequence is real and is not papered over here:
`test_gates_register.py::test_every_gate_script_on_disk_is_registered`
requires every `tools/gate_*.py` to be named by a row, and until `eval/gates.toml` lands with a
`Q-G15` row -- or the plan rules that a Q-G runner may be named from `tools/gates.toml` -- this file
is the one script no register names. That is reported as a finding, not fixed by adding a row to a
register this file does not own.

## Exit codes

`0` the register is clean. `1` a budget row is bad -- the report names the row, the key and the
plan line it violates. `2` the gate did not run: a bad argument, a missing file, TOML that does
not parse. CI treats `1` and `2` alike and a human needs to know which, exactly as
`tools/gate_crash.py` says.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CEILINGS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "GATE_VALUES",
    "ID_PATTERN",
    "KNOWN_KEYS",
    "PERF_TOML",
    "PROCESS_VALUES",
    "REPO",
    "RSS_PREFIX",
    "Ceiling",
    "Finding",
    "GateNotRunError",
    "check",
    "load",
    "main",
    "worst_case",
]

REPO: Final = Path(__file__).resolve().parents[1]
"""The workspace root -- the directory holding `packages/`, `tools/` and `eval/`."""

PERF_TOML: Final = "eval/perf.toml"
"""The register, relative to `REPO`. 12-performance.md section 2.4 is its sole home."""

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

ID_PATTERN: Final = re.compile(r"\A[a-z0-9_.]{1,64}\Z")
r"""`id`'s grammar, 12-performance.md:219. The suffix carries the unit (`_ms`, `_s`, `_bytes`).

`\A` and `\Z`, not `^` and `$`. Python's `$` also matches immediately BEFORE a trailing
newline, so `^[a-z0-9_.]{1,64}$` accepts `"store.bytes_per_block\n"`: an id that renders as the
id it is not, that `_check_uniqueness` scores as distinct from the real row, and that resolves
against no scoreboard row, risk indicator (17-risks.md:56) or bless entry. The class
12-performance.md:219 states holds no newline, so neither does this pattern.
"""

GATE_VALUES: Final[tuple[str, ...]] = ("pr", "nightly")
"""`gate`'s closed vocabulary, 12-performance.md:223 -- the CI job that fails on breach."""

PROCESS_VALUES: Final[tuple[str, ...]] = ("supervisor", "worker", "driver_subproc", "service")
"""`process`'s closed vocabulary, 12-performance.md:224 and 13-quality.md:369-370."""

RSS_PREFIX: Final = "rss."
"""The `id` prefix that makes `process` required. 12-performance.md:224 -- "iff `id` starts
`rss.`; rejected on any other row"."""

TOLERANCE_KEYS: Final[tuple[str, ...]] = ("tol_pct", "tol_abs")
"""Mutually exclusive, exactly one required (12-performance.md:214-222)."""

REQUIRED_KEYS: Final[tuple[str, ...]] = ("id", "value", "gate")

OPTIONAL_KEYS: Final[tuple[str, ...]] = ("tol_pct", "tol_abs", "process", "note", "ratchet")

KNOWN_KEYS: Final[frozenset[str]] = frozenset(REQUIRED_KEYS + OPTIONAL_KEYS)
"""Every key a `[[budget]]` row may carry. Anything else is a hard error (12-performance.md:214).

`ratchet` is here and it is NOT in section 2.4's key table, which declares itself the schema's sole
home. Two sites state it on `store.bytes_per_block` -- the charter's TOML (`charter:7622`) and
section 2.4's own rendering of that row's tolerance cell, *"+/-10%, **ratchet**"*
(12-performance.md:244) -- and 12-performance.md:209-210 fixes the file's shape as *"the charter's
plus exactly one key"*, which adds `process` without removing anything. Refusing the key here would
make the register the plan states fail the gate the plan states, so the key is known and the
contradiction is reported as a finding instead.
"""

TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"pacer", "budget"})
"""The whole of the file: the Pacer table and the budget array (charter:7565-7631)."""

PACER_KEYS: Final[frozenset[str]] = frozenset({"work", "instability_pct", "rule", "runner"})
"""`[pacer]`'s four keys, charter:7567-7571. The plan states no schema table for them, so they are
checked for presence and nothing more -- an absent `runner` is the one that matters, because
12-performance.md:1966 makes `ow-bench-1` the only machine a Budget may live on and this is the only
place in the file that can name it."""

TOL_PCT_MAX: Final = 100
"""`tol_pct` is an `int` in 0-100 (12-performance.md:221)."""


@dataclass(frozen=True, slots=True)
class Ceiling:
    """A tier ceiling and the plan line that fixes it.

    The `why` is not decoration. A gate that rejects a row has to be answerable with a citation,
    because the reader's first question is always whether the ceiling or the budget is wrong.
    """

    limit: int | float
    unit: str
    why: str


CEILINGS: Final[Mapping[str, Ceiling]] = {
    # V01-3's four cold-start ceilings, 00-vision.md:704, tabulated with their budgets and the
    # headroom each leaves at 12-performance.md:182-188.
    "import.omniweave_core_ms": Ceiling(
        80, "ms", "V01-3, 00-vision.md:704 / 12-performance.md:184"
    ),
    "cold.ow_version_ms": Ceiling(150, "ms", "V01-3, 00-vision.md:704 / 12-performance.md:185"),
    "cold.ow_help_ms": Ceiling(250, "ms", "V01-3, 00-vision.md:704 / 12-performance.md:186"),
    "discovery.20dists_ms": Ceiling(20, "ms", "V01-3, 00-vision.md:704 / 12-performance.md:187"),
    # G10's warm-query ceiling, which is also `[retrieval.budget] query_ms`.
    "query.warm_p50_ms": Ceiling(
        250, "ms", "G10 / [retrieval.budget] query_ms, 12-performance.md:188"
    ),
    # The test pyramid's per-tier budgets, 13-quality.md:60-71, restated with this arithmetic at
    # 13-quality.md:362-366 and 13-quality.md:1924-1939.
    "conform.mandatory_tier_s": Ceiling(300, "s", "T3 <= 5 min, 13-quality.md:71 / :363"),
    "contributor_parity_s": Ceiling(600, "s", "parity hard ceiling, 13-quality.md:71 / :363"),
    "t0.gates_job_s": Ceiling(180, "s", "T0 <= 3 min, 13-quality.md:71 / :1924"),
    "test.cell_ubuntu_311_s": Ceiling(240, "s", "T1 <= 4 min per cell, 13-quality.md:71 / :1931"),
    "golden.job_s": Ceiling(240, "s", "T2 <= 4 min, 13-quality.md:71 / :1939"),
}
"""Every row the plan gives a tier ceiling, and only those.

The five rows that are absent -- `parse.office.p50_ms`, `store.bytes_per_block`, the two `rss.` rows
and `wal.bulk_index_peak_bytes` -- are absent because no ceiling is stated for them anywhere in the
plan, not because the arithmetic was inconvenient. 13-quality.md:357-358 scopes the clause to
*"every row carrying a tier"*, and inventing a ceiling for a row the plan leaves open would be a
number this gate made up. They are listed by name in the report so the gap is visible rather
than assumed.
"""


class GateNotRunError(Exception):
    """The gate could not run: the register is missing, unreadable, or not TOML. Exit code 2."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One defect in one place, with the plan line that makes it a defect."""

    where: str
    what: str
    why: str

    def block(self) -> str:
        return f"  FAIL {self.where}\n       {self.what}\n       {self.why}"


def load(path: Path) -> Mapping[str, Any]:
    """Parse the register. Raises `GateNotRunError` when there is nothing to lint.

    A missing or malformed file is deliberately NOT a finding. A finding says "row 7 is wrong",
    which is a claim this function is in no position to make when it could not read row 7 at all;
    conflating the two is how a gate reports a clean register on a checkout where somebody deleted
    it.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GateNotRunError(f"cannot read {path}: {exc}") from exc
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise GateNotRunError(f"{path} is not parseable TOML: {exc}") from exc


def _is_number(value: object) -> bool:
    """`int | float`, and `bool` is neither.

    `bool` is a subclass of `int` in Python, so `value = true` satisfies `isinstance(v, int)` and
    would be budgeted at one millisecond. The unit suffix in the `id` is the only thing that says
    what the number means, and `true` has no unit.
    """
    return isinstance(value, int | float) and not isinstance(value, bool)


def _decimal(value: int | float) -> Fraction:
    """The exact value of the number as it is SPELLED, not as it is stored.

    `Fraction(0.1)` is 3602879701896397/36028797018963968; `Fraction("0.1")` is one tenth. Every
    number in this register is a decimal a human typed, so the string form is the true one and the
    comparison against a ceiling is the arithmetic the plan did on paper.
    """
    return Fraction(str(value))


def worst_case(row: Mapping[str, Any]) -> Fraction | None:
    """`value + tol_abs`, or `value * (1 + tol_pct/100)`. `None` when the row is too broken to say.

    Both spellings are one clause -- see the module docstring. The percentage form is
    12-performance.md:178-179's own arithmetic ("budget x (1 + tolerance)").
    """
    value = row.get("value")
    if not _is_number(value):
        return None
    exact = _decimal(value)
    if _is_number(row.get("tol_abs")):
        return exact + _decimal(row["tol_abs"])
    tol_pct = row.get("tol_pct")
    if isinstance(tol_pct, int) and not isinstance(tol_pct, bool):
        return exact * (1 + Fraction(tol_pct, 100))
    return None


def _label(position: int, row: Mapping[str, Any]) -> str:
    """How a row is named in the report: its position, and its `id` when it has a usable one.

    An id that does not match `ID_PATTERN` is quoted with `!r` rather than interpolated raw. The
    id comes out of the file under test, so it can hold a newline or a control character, and a
    finding whose first line is split in two is a finding a CI log annotation truncates at the
    break -- the gate would be reporting the defect in a form the defect chose.
    """
    identifier = row.get("id")
    if isinstance(identifier, str) and identifier:
        shown = identifier if ID_PATTERN.match(identifier) else repr(identifier)
        return f"[[budget]] #{position} ({shown})"
    return f"[[budget]] #{position}"


def _check_keys(where: str, row: Mapping[str, Any]) -> list[Finding]:
    """Unknown keys, and the three that are always required."""
    findings: list[Finding] = []
    for key in sorted(set(row) - KNOWN_KEYS):
        findings.append(
            Finding(
                where,
                f"unknown key {key!r}",
                "12-performance.md:214 -- an unknown key is a hard error at load. The key table at "
                "12-performance.md:215-225 is the schema's sole home.",
            )
        )
    for key in REQUIRED_KEYS:
        if key not in row:
            findings.append(
                Finding(where, f"missing required key {key!r}", "12-performance.md:219-223.")
            )
    return findings


def _check_id(where: str, row: Mapping[str, Any]) -> list[Finding]:
    identifier = row.get("id")
    if identifier is None:
        return []
    if not isinstance(identifier, str) or not ID_PATTERN.match(identifier):
        return [
            Finding(
                where,
                f"id {identifier!r} is not `[a-z0-9_.]{{1,64}}`",
                "12-performance.md:219. The id IS the `budget_id` a scoreboard row, a risk "
                "indicator (17-risks.md:56) and a bless entry all resolve against.",
            )
        ]
    return []


def _check_value(where: str, row: Mapping[str, Any]) -> list[Finding]:
    if "value" not in row:
        return []
    if not _is_number(row["value"]):
        return [
            Finding(
                where,
                f"value {row['value']!r} is not `int | float`",
                "12-performance.md:220 -- the budgeted figure, in the unit the id's suffix names.",
            )
        ]
    return []


def _check_tolerance(where: str, row: Mapping[str, Any]) -> list[Finding]:
    """Exactly one of `tol_pct` / `tol_abs`, and each in its own type and range."""
    findings: list[Finding] = []
    present = [key for key in TOLERANCE_KEYS if key in row]
    if len(present) != 1:
        findings.append(
            Finding(
                where,
                f"tolerance keys present: {present or 'none'}",
                "12-performance.md:214 -- `tol_pct` and `tol_abs` are mutually exclusive and "
                "exactly one is required.",
            )
        )
    if "tol_pct" in row:
        tol_pct = row["tol_pct"]
        if not isinstance(tol_pct, int) or isinstance(tol_pct, bool):
            findings.append(
                Finding(where, f"tol_pct {tol_pct!r} is not an `int`", "12-performance.md:221.")
            )
        elif not 0 <= tol_pct <= TOL_PCT_MAX:
            findings.append(
                Finding(
                    where,
                    f"tol_pct {tol_pct} is outside 0-100",
                    "12-performance.md:221 -- a percentage of the value, not a multiplier.",
                )
            )
    if "tol_abs" in row and not _is_number(row["tol_abs"]):
        findings.append(
            Finding(
                where,
                f"tol_abs {row['tol_abs']!r} is not `int | float`",
                "12-performance.md:222 -- an absolute, in the same unit as `value`.",
            )
        )
    return findings


def _check_gate(where: str, row: Mapping[str, Any]) -> list[Finding]:
    if "gate" not in row:
        return []
    if row["gate"] not in GATE_VALUES:
        return [
            Finding(
                where,
                f"gate {row['gate']!r} is not one of {list(GATE_VALUES)}",
                "12-performance.md:223 -- the CI job that fails on breach.",
            )
        ]
    return []


def _check_process(where: str, row: Mapping[str, Any]) -> list[Finding]:
    """Clause 2: `process` iff `rss.`, over a closed vocabulary.

    Both halves fail. A missing `process` on an `rss.` row is the OOM at hour six; a `process` on a
    row that is not `rss.` is a scope claim about a figure that has no scope, and the schema
    rejects it in as many words (12-performance.md:224).
    """
    identifier = row.get("id")
    is_rss = isinstance(identifier, str) and identifier.startswith(RSS_PREFIX)
    process = row.get("process")
    if is_rss and process is None:
        return [
            Finding(
                where,
                "an `rss.` row with no `process`",
                "13-quality.md:368-374 / ADR-11 D5 / charter section 9.2 E88. A memory budget "
                "read at the wrong scope is an OOM kill at hour six instead of a refusal before "
                "the run.",
            )
        ]
    if not is_rss and process is not None:
        return [
            Finding(
                where,
                f"`process` = {process!r} on a row whose id does not start {RSS_PREFIX!r}",
                "12-performance.md:224 -- required iff the id starts `rss.`, rejected on any other "
                "row.",
            )
        ]
    if process is not None and process not in PROCESS_VALUES:
        return [
            Finding(
                where,
                f"process {process!r} is not one of {list(PROCESS_VALUES)}",
                "12-performance.md:224 / 13-quality.md:369-370 -- a closed vocabulary.",
            )
        ]
    return []


def _check_ratchet(where: str, row: Mapping[str, Any]) -> list[Finding]:
    """`ratchet`, where present, is a boolean. See `KNOWN_KEYS` for why the key is known at all."""
    if "ratchet" in row and not isinstance(row["ratchet"], bool):
        return [
            Finding(
                where,
                f"ratchet {row['ratchet']!r} is not a boolean",
                "charter:7622 -- 'it may fall and never rise' (12-performance.md:244) is a yes/no.",
            )
        ]
    return []


def _check_note(where: str, row: Mapping[str, Any]) -> list[Finding]:
    if "note" in row and not isinstance(row["note"], str):
        return [
            Finding(
                where,
                f"note {row['note']!r} is not a string",
                "12-performance.md:225 -- provenance, free text.",
            )
        ]
    return []


def _check_ceiling(where: str, row: Mapping[str, Any]) -> list[Finding]:
    """Clause 3, non-strict, over the rows the plan gives a tier (13-quality.md:351-366)."""
    identifier = row.get("id")
    if not isinstance(identifier, str):
        return []
    ceiling = CEILINGS.get(identifier)
    if ceiling is None:
        return []
    worst = worst_case(row)
    if worst is None:
        return []
    if worst > _decimal(ceiling.limit):
        return [
            Finding(
                where,
                f"value + tolerance = {float(worst):g} {ceiling.unit} exceeds the "
                f"{ceiling.limit} {ceiling.unit} ceiling",
                "13-quality.md:351-366 -- a budget whose worst case is over its tier ceiling is a "
                f"budget that can pass while the tier is over. Ceiling: {ceiling.why}.",
            )
        ]
    return []


def _check_row(position: int, row: Mapping[str, Any]) -> list[Finding]:
    """Every clause that is a statement about one row, in schema-then-arithmetic order."""
    where = _label(position, row)
    findings: list[Finding] = []
    findings.extend(_check_keys(where, row))
    findings.extend(_check_id(where, row))
    findings.extend(_check_value(where, row))
    findings.extend(_check_tolerance(where, row))
    findings.extend(_check_gate(where, row))
    findings.extend(_check_process(where, row))
    findings.extend(_check_ratchet(where, row))
    findings.extend(_check_note(where, row))
    findings.extend(_check_ceiling(where, row))
    return findings


def _check_uniqueness(rows: Sequence[Mapping[str, Any]]) -> list[Finding]:
    """`id` is unique across the file (12-performance.md:219).

    TOML is happy to hold two rows with the same `id`; the last one wins in every dict a reader
    builds from them, and the first becomes a budget that is committed, rendered and never checked.
    """
    seen: dict[str, int] = {}
    findings: list[Finding] = []
    for position, row in enumerate(rows, start=1):
        identifier = row.get("id")
        if not isinstance(identifier, str):
            continue
        if identifier in seen:
            findings.append(
                Finding(
                    _label(position, row),
                    f"duplicate id -- already declared by [[budget]] #{seen[identifier]}",
                    "12-performance.md:219 -- unique across the file.",
                )
            )
        else:
            seen[identifier] = position
    return findings


def _check_shape(doc: Mapping[str, Any]) -> list[Finding]:
    """The file's own shape: the two top-level tables, and a `[pacer]` that names its runner."""
    findings: list[Finding] = []
    for key in sorted(set(doc) - TOP_LEVEL_KEYS):
        findings.append(
            Finding(
                PERF_TOML,
                f"unknown top-level key {key!r}",
                "charter:7565-7631 -- the file is `[pacer]` plus the `[[budget]]` array.",
            )
        )
    rows = doc.get("budget")
    if rows is not None and not isinstance(rows, list):
        findings.append(
            Finding(
                PERF_TOML,
                f"`budget` is {type(rows).__name__} and not an array of tables",
                "12-performance.md:207-225 -- the register is an array of `[[budget]]` tables. "
                "`budget = 5` is not an empty register, it is a file nothing can be read out of.",
            )
        )
    elif not rows:
        findings.append(
            Finding(
                PERF_TOML,
                "no `[[budget]]` rows at all",
                "12-performance.md:207 -- this file IS the gated subset. An empty register makes "
                "every downstream check vacuously green.",
            )
        )
    pacer = doc.get("pacer")
    if not isinstance(pacer, dict):
        findings.append(
            Finding(PERF_TOML, "no `[pacer]` table", "charter:7567-7571 -- time is a Pacer ratio.")
        )
        return findings
    for key in sorted(PACER_KEYS - set(pacer)):
        findings.append(
            Finding(
                f"{PERF_TOML} [pacer]",
                f"missing key {key!r}",
                "charter:7567-7571. `runner` in particular: 12-performance.md:1966 makes "
                "`ow-bench-1` the only machine a Budget may live on, and this is the only key in "
                "the file that can name it.",
            )
        )
    return findings


def check(doc: Mapping[str, Any]) -> list[Finding]:
    """Every clause over a parsed register. An empty list is the register being clean."""
    findings = _check_shape(doc)
    rows = doc.get("budget")
    if not isinstance(rows, list):
        return findings
    typed: list[Mapping[str, Any]] = [row for row in rows if isinstance(row, dict)]
    findings.extend(
        Finding(f"[[budget]] #{position}", f"not a table: {row!r}", "12-performance.md:215-225.")
        for position, row in enumerate(rows, start=1)
        if not isinstance(row, dict)
    )
    for position, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            findings.extend(_check_row(position, row))
    findings.extend(_check_uniqueness(typed))
    return findings


def _say(text: str = "") -> None:
    """Write one line to stdout.

    `print` is banned repo-wide by ruff's `T20` -- *"a library that prints has no way to be quiet
    inside a hook with a 400 ms deadline"* (11-repo-layout.md section 8.1). A gate script is not a
    library and stdout is the whole of its output contract, but the repository declares no
    `tools/*.py` per-file-ignore, so the writer is explicit rather than suppressed. The same helper,
    for the same reason, is in `tools/gate_weights.py` and `tools/gate_layers.py`.
    """
    sys.stdout.write(f"{text}\n")


def _report(path: Path, doc: Mapping[str, Any], findings: Sequence[Finding]) -> None:
    """The two counts, then the findings. Both counts print on every run, pass or fail."""
    raw = doc.get("budget")
    rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    identifiers = {row["id"] for row in rows if isinstance(row.get("id"), str)}
    with_ceiling = sorted(identifiers & set(CEILINGS))
    without_ceiling = sorted(identifiers - set(CEILINGS))
    missing_rows = sorted(set(CEILINGS) - identifiers)

    _say(f"Q-G15 gate_budgets: {path} (12-performance.md section 2.4, 13-quality.md section 2.9)")
    _say("  a LINTER over the register. It opens no store, times nothing and measures nothing.")
    _say(f"  {len(rows)} [[budget]] row(s), {len(identifiers)} distinct id(s)")
    _say(f"  {len(with_ceiling)} row(s) checked against a tier ceiling: {', '.join(with_ceiling)}")
    _say(
        f"  {len(without_ceiling)} row(s) the plan gives no tier ceiling, so clause 3 is silent on "
        f"them: {', '.join(without_ceiling) or 'none'}"
    )
    if missing_rows:
        _say(
            "  NOTE a ceiling is stated for these ids and the register has no such row: "
            f"{', '.join(missing_rows)}"
        )
    ratchets = sorted(
        row["id"] for row in rows if row.get("ratchet") and isinstance(row.get("id"), str)
    )
    _say(f"  ratchet rows (may fall, never rise): {', '.join(ratchets) or 'none'}")
    for finding in findings:
        _say(finding.block())
    _say(f"Q-G15 {'FAIL' if findings else 'ok'}  {len(findings)} finding(s)")


def main(argv: list[str] | None = None) -> int:
    """0 the register is clean, 1 a budget row is bad, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_budgets.py",
        description=(
            "Q-G15: lint eval/perf.toml's [[budget]] rows against 12-performance.md section 2.4's "
            "schema and 13-quality.md section 2.9's ceiling arithmetic. Measures nothing."
        ),
    )
    parser.add_argument(
        "--perf",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"the register to lint (default: <repo>/{PERF_TOML})",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN

    path: Path = args.perf if args.perf is not None else REPO / PERF_TOML
    try:
        doc = load(path)
    except GateNotRunError as exc:
        _say(f"Q-G15 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    findings = check(doc)
    _report(path, doc, findings)
    return EXIT_FAIL if findings else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
