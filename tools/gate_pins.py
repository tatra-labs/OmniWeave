"""G7: a version constraint tighter than `>=` carries a comment. Text and TOML, reconciled.

`tools/gates.toml`'s G7 row states the assertion in one line -- *"a constraint tighter than `>=`
carries a comment"* -- and its `step` states the scope: *"a `gates` job step over every
packages/*/pyproject.toml: a `==`, `~=` or `<` bound carries a justification comment (section
8.5)"*. The same assertion is rendered at 11-repo-layout.md:1550, stated from the vision side at
00-vision.md:585 (*"gate G7 (a constraint tighter than `>=` carries a comment)"*), from the security
side at 14-security.md:1275-1276 (*"**G7** enforces the rule that makes the policy auditable"*) and
from the risk side at 17-risks.md:227 (*"G7 fails a constraint tighter than `>=` with no comment"*).
It is W1.7, 16-roadmap.md:363 -- a P1 deliverable that was never built.

## The path of this file is our engineering call, and the plan says as much

11-repo-layout.md section 8.5 is the POLICY and it names no script; 16-roadmap.md:363 schedules the
gate in a list of seven and names no filename either. `tools/gates.toml`'s G7 row records that
silence in its own comment -- *"The plan names no script. Section 8.5 is the policy and
16-roadmap.md:363 (W1.7) schedules the gate without a filename, so this row says 'job step' rather
than inventing `gate_pins.py`"*. So the NAME below is ours, chosen to match the row's own guess,
and choosing it is the same engineering call `tools/gate_budgets.py` and `tools/measure_store.py`
make in their docstrings for the same situation. What is NOT ours is the assertion, the operator
list or the scope: all three are transcribed above, with citations, and none is widened here.

There is precedent for a runner the plan does not name: G29's runner is a test file
(`tests/test_no_content_in_artefacts.py`) and G6's is `tools/schemagen.py`. Both shapes already sit
in the register.

## Why this cannot be done from a parsed TOML document, and what the reconciliation is

`tomllib` discards comments. There is no API, and no plausible one, by which a parsed document can
answer "is there a `#` next to this bound". So the gate reads the file TWICE and reconciles:

* **as TOML**, to learn which strings are version constraints and which of those are tightened.
  Deciding that from text alone would mean re-implementing TOML: a requirement can sit in
  `[project] dependencies`, in an extra, in `[dependency-groups]`, in `[build-system] requires` or
  in a `[tool.uv]` array, and a string that merely LOOKS like a requirement (a `description`, a
  `classifiers` row) is not one.
* **as text**, to learn where each of those strings physically sits and what comment lines are
  adjacent to it. A physical line is the only unit a comment can attach to.

The two passes are reconciled by requiring that every tightened constraint the TOML pass found is
locatable as a string literal in the text pass. When one is not -- it was written inside a
multi-line basic string, or the line splitter is wrong about where a `#` begins -- the gate exits
**2**, not 0. That is the whole reason the reconciliation exists rather than being implied: a
one-pass text gate that cannot see a bound reports the same green as a gate that checked it.

There is no "one key per physical line" rule to lean on here, and it was worth checking, because
one exists nearby and is easy to mistake for this. 11-repo-layout.md:1570 and :48 scope G27 clause
(a2) to ` ```toml ` FENCES IN THE PLAN DOCUMENTS -- *"one key per physical line"*, with the brace
depth rule spelled at :1581 -- and 05-ingest-and-routing.md:1259 states the same clause the same
way. Nothing extends it to `pyproject.toml`, and `packages/omniweave-pdf/pyproject.toml` is printed
in the plan itself at 11-repo-layout.md:274 as a single physical line holding three requirements.
So the text pass checks **each string literal on a line separately** and a line may carry several.

## What counts as carrying a comment: presence and adjacency, never content

A bound is justified when a comment is ADJACENT to it, in any of three forms:

1. a trailing `#` comment on the bound's own physical line;
2. the contiguous run of comment-only lines immediately ABOVE it;
3. the contiguous run of comment-only lines immediately BELOW it.

A blank line breaks a run, and so does a table header: the comment block above
`[project.optional-dependencies]` is separated from the first key by the header line itself, which
is code and not a comment, so it reaches no key in the table. That is the shape a block comment
introducing a whole extras table has, and it is why such a block justifies nothing under it: one
comment would otherwise justify an unbounded number of bounds, which is the difference between an
auditable pin and a decorated table. The rule is pinned in `test_gate_pins.py` on a fixture rather
than on the tree, deliberately: which bounds the fourteen files carry, and which of them carry a
comment, is a fact about the tree that any `pyproject.toml` edit changes, and a gate's own
docstring must not go stale the moment one lands.

Form 3 is not a convenience -- it is forced by the plan's own worked example.
11-repo-layout.md:2337-2339 says
*"`firecrawl-anydoc == 0.2.4` is an exact pin under the second role and carries its justification
in the `pyproject.toml` comment"*, and in `packages/omniweave-office/pyproject.toml` that
justification sits on the two lines BELOW the bound. A gate accepting only forms 1 and 2 would fail
the one file section 8.5 holds up as compliant, which would be a defect in the gate. Both
conventions are in the tree: that same file puts a comment above `firecrawl-anydoc` which annotates
the bound before it, so neither direction can be the only one.

The consequence is a stated false-negative direction. A comment block sitting between two bounds is
credited to BOTH, because the gate cannot tell which one it is about; and a comment saying nothing
useful counts, because a gate that judged whether prose justifies a pin would be a gate that
guesses. The content requirement has a different enforcer, and the plan puts it on a human:
11-repo-layout.md:2283-2284 makes *"the reason a looser constraint will not do"* a required PR
field, and section 8.5's role table is what a reviewer reads it against. This gate is the
auditability floor under that -- 14-security.md:1275 calls it exactly that -- and not the audit.

## Which operators are tightening

The row's step names three: `==`, `~=`, `<`. This gate reads them as FAMILIES and treats five
spellings as tightening -- `===`, `==`, `~=`, `<=`, `<` -- because `<=1.9` and `<2.0` are the same
ceiling and a gate that failed the second while passing the first would be reporting the spelling
rather than the bound. That is the boundary-value reading, and it is stated here rather than left
implicit because it is two spellings wider than the register's literal list.

Three operators are NOT tightening, each for a stated reason:

* `>=` -- the policy's own default. Section 8.5's first role is *"floor with a CVE comment, no
  ceiling"*, and `>=` alone is the shape that role prescribes.
* `>` -- still a floor with no ceiling. It excludes one release below, which is the floor's
  business; the register's step does not name it.
* `!=` -- section 8.5 SANCTIONS it: *"a specific bad release is excluded with `!=`, never by
  raising the floor"*, holding up docling's `pypdfium2 (>=4.30.0,!=4.30.1,<6.0.0)` as *"the habit
  worth copying"* because *"raising a floor to skip one bad release also forbids the good releases
  below it"*. Failing `!=` would fail the habit the policy prescribes.

An environment marker is stripped before any of this runs. `semgrep; sys_platform != 'win32'`
carries a `!=` and `pkg; python_version < "3.12"` carries a `<`, and neither is a version bound on
the distribution -- a marker decides WHETHER the requirement applies, not which versions satisfy
it. A direct URL reference (`pkg @ https://...`) has no specifier set at all (PEP 508) and is
likewise not a bound; it is a different defect, and G12's business.

## Every place a version constraint can appear, and which are covered

`COVERED_SITES` is the list, and it is complete over the fourteen files as they stand. Because
"complete today" rots, the gate also SWEEPS the parsed document for any key named like a constraint
site at a path it does not cover (`tool.poetry.dependencies`, say) and prints it as a `NOTE`. A
gate that silently checked one table would be worse than no gate, so the uncovered surface is named
on every run rather than assumed empty.

The workspace root's own `pyproject.toml` is deliberately NOT in the default glob: the register's
step scopes G7 to *"every packages/*/pyproject.toml"* and widening a gate past its registered scope
is the same act as inventing a register row. It is reachable with `--glob pyproject.toml`, and it
matters -- the root's `[dependency-groups] dev` carries `pytest~=9.1` with no adjacent comment.
That is reported as a finding of this wave, not fixed by quietly enlarging the gate.

## Exit codes

`0` every tightened bound carries a comment. `1` a tightened bound does not -- the report names the
file, the physical line, the bound and the operator. `2` the gate did not run: a bad argument, no
file matched the glob, a file that is not readable or not parseable TOML, or a tightened bound the
text pass could not locate. CI treats `1` and `2` alike and a human needs to know which, exactly as
`tools/gate_crash.py` and `tools/gate_budgets.py` say.

The gate installs nothing, imports nothing outside the standard library, opens no socket and reads
no file it was not pointed at. `budget_s = 2` in the register is the reason that is a requirement
and not a preference.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CONSTRAINT_KEY_NAMES",
    "COVERED_SITES",
    "DEFAULT_GLOBS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "OPERATORS",
    "REPO",
    "TIGHTENING_OPERATORS",
    "UV_ARRAY_KEYS",
    "Constraint",
    "FileReport",
    "Finding",
    "GateNotRunError",
    "Line",
    "Occurrence",
    "check_file",
    "collect",
    "justifying_lines",
    "main",
    "operators_in",
    "scan",
    "specifier_of",
    "uncovered_sites",
]

REPO: Final = Path(__file__).resolve().parents[1]
"""The workspace root -- the directory holding `packages/`, `tools/` and `eval/`."""

DEFAULT_GLOBS: Final[tuple[str, ...]] = ("packages/*/pyproject.toml",)
"""G7's scope, transcribed from `tools/gates.toml`'s G7 `step`. The root `pyproject.toml` is not in
it; see the module docstring for why, and for the finding that scope hides."""

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

OPERATORS: Final[tuple[str, ...]] = ("===", "==", "~=", "!=", "<=", ">=", "<", ">")
"""Every PEP 440 comparison operator, LONGEST FIRST.

The order is load-bearing and not cosmetic: `operators_in` reads the leading operator of a clause
by first match, so a shorter operator listed before a longer spelling of the same text would
misclassify it. `<=1.9` read as `<` is harmless here (both are tightening) but `>=1` read as `>`
would be a floor reported as a different floor, and `===1.0` read as `==` loses the
arbitrary-equality spelling from the report. Sorting by length once is cheaper than being careful
twice.
"""

TIGHTENING_OPERATORS: Final[frozenset[str]] = frozenset({"===", "==", "~=", "<=", "<"})
"""The five spellings this gate calls tighter than `>=`. The module docstring's "Which operators
are tightening" states the three the register names and the widening to families."""

UV_ARRAY_KEYS: Final[tuple[str, ...]] = (
    "constraint-dependencies",
    "override-dependencies",
    "dev-dependencies",
    "build-constraint-dependencies",
)
"""`[tool.uv]`'s requirement arrays. None is used in the fourteen files today, and all four are
covered anyway: a `constraint-dependencies` row is a version bound on the resolution of the whole
workspace, which is the most consequential place a silent `<` could hide."""

COVERED_SITES: Final[tuple[str, ...]] = (
    "project.requires-python",
    "project.dependencies",
    "project.optional-dependencies.<extra>",
    "build-system.requires",
    "dependency-groups.<group>",
    *(f"tool.uv.{key}" for key in UV_ARRAY_KEYS),
)
"""Every place a version constraint can appear in the fourteen files, and every place this gate
looks. Printed on every run, so the scope of a green result is never a matter of trust.

`project.requires-python` is a bare specifier rather than a requirement and is checked all the
same: the fourteen files all carry `>=3.11` with `# NO upper bound. charter.md D1.` beside it, and
charter D1's no-upper-bound rule is exactly the rule a `,<3.14` appended one afternoon would break.
`[project.optional-dependencies]` is where 00-vision.md:585 records DataFlow's *"four incompatible
vLLM pins"*, so an extra is not a lesser site. `[build-system] requires` is where `hatchling>=1.27`
lives.
"""

CONSTRAINT_KEY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "dependencies",
        "requires",
        "requires-python",
        "optional-dependencies",
        *UV_ARRAY_KEYS,
    }
)
"""Key names that hold version constraints ANYWHERE they appear. `uncovered_sites` sweeps the
parsed document for one of these at a path `COVERED_SITES` does not name --
`tool.poetry.dependencies` is the shape that would otherwise pass unexamined -- and the gate prints
each as a `NOTE`."""

_MULTILINE_DELIMITERS: Final[tuple[str, ...]] = ('"""', "'''")

_NAME_FIRST: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_NAME_REST: Final = _NAME_FIRST | frozenset("._-")


class GateNotRunError(Exception):
    """The gate could not run: an unreadable file, TOML that does not parse, a bound the text pass
    could not locate, or a glob that matched nothing. Exit code 2."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One unjustified bound in one place, with the plan line that makes it a defect."""

    where: str
    what: str
    why: str

    def block(self) -> str:
        return f"  FAIL {self.where}\n       {self.what}\n       {self.why}"


@dataclass(frozen=True, slots=True)
class Line:
    """One physical line, split into the part TOML reads and the part it discards.

    `comment` is `None` when the line carries no `#` outside a string, and the empty string when it
    carries a bare `#`. The distinction is kept because a bare `#` is a comment that says nothing,
    and `justifying_lines` declines to credit it.
    """

    number: int
    code: str
    comment: str | None

    @property
    def is_comment_only(self) -> bool:
        return not self.code.strip() and self.comment is not None


@dataclass(frozen=True, slots=True)
class Constraint:
    """One version constraint as the TOML pass sees it: where it lives and what it says."""

    site: str
    raw: str
    specifier: str
    operators: tuple[str, ...]

    @property
    def tightening(self) -> tuple[str, ...]:
        return tuple(op for op in self.operators if op in TIGHTENING_OPERATORS)


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One tightened bound as the TEXT pass sees it: a physical line, and its adjacent comments.

    `sites` is every site in the parsed document holding this exact requirement string, not the
    one site this particular literal came from, and the plural is not sloppiness: the same string
    genuinely appears at several sites in `packages/omniweave/pyproject.toml`
    (`omniweave-serve ~= 0.1.0` is both the `serve` extra and a member of `recommended`) and the
    text pass has no way to tell which literal `tomllib` read into which. Naming them all is the
    honest report; naming one would be a guess dressed as a location.
    """

    line: int
    raw: str
    sites: tuple[str, ...]
    operators: tuple[str, ...]
    justified_by: tuple[int, ...]

    @property
    def justified(self) -> bool:
        return bool(self.justified_by)


@dataclass(frozen=True, slots=True)
class FileReport:
    """Everything the gate learned about one `pyproject.toml`. The counts print either way."""

    path: Path
    constraints: tuple[Constraint, ...]
    occurrences: tuple[Occurrence, ...]
    uncovered: tuple[str, ...]
    findings: tuple[Finding, ...]


# ---------------------------------------------------------------------------
# The TOML pass: which strings are constraints, and which are tightened
# ---------------------------------------------------------------------------


def specifier_of(raw: str) -> str | None:
    """The specifier set of a PEP 508 requirement, or `None` when it has none.

    Three things are stripped before the specifier is read, and each strip prevents a false
    positive the module docstring argues for at length: the environment marker after `;` (a marker
    is not a version bound), the optional `[extras]` bracket, and the parentheses PEP 508 allows
    around the specifier set -- section 8.5's own docling example is written
    `pypdfium2 (>=4.30.0,!=4.30.1,<6.0.0)`. A direct URL reference yields `None` because PEP 508
    forbids it a specifier set at all.
    """
    head = raw.split(";", 1)[0].strip()
    if not head or head[0] not in _NAME_FIRST:
        return None
    index = 0
    while index < len(head) and head[index] in _NAME_REST:
        index += 1
    rest = head[index:].strip()
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            return None
        rest = rest[close + 1 :].strip()
    if rest.startswith("@"):
        return None
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1].strip()
    return rest


def operators_in(specifier: str) -> tuple[str, ...]:
    """The leading operator of every comma-separated clause, in order.

    A clause with no leading operator contributes nothing: `"pkg 1.2"` is not valid PEP 440 and
    this gate is not the validator for that. `OPERATORS` is longest-first, which is what makes the
    first match the right one.
    """
    found: list[str] = []
    for clause in specifier.split(","):
        text = clause.strip()
        for operator in OPERATORS:
            if text.startswith(operator):
                found.append(operator)
                break
    return tuple(found)


def _requirement(site: str, raw: str) -> Constraint | None:
    specifier = specifier_of(raw)
    if not specifier:
        return None
    return Constraint(site, raw, specifier, operators_in(specifier))


def _from_array(site: str, value: object) -> Iterator[Constraint]:
    """Requirements out of one array. A non-string entry is skipped, not guessed at.

    `[dependency-groups]` may hold `{ include-group = "x" }` tables beside its strings (PEP 735),
    and an include carries no version.
    """
    if not isinstance(value, list):
        return
    for position, entry in enumerate(value):
        if not isinstance(entry, str):
            continue
        constraint = _requirement(f"{site}[{position}]", entry)
        if constraint is not None:
            yield constraint


def _from_table_of_arrays(site: str, value: object) -> Iterator[Constraint]:
    if not isinstance(value, dict):
        return
    for key, array in value.items():
        yield from _from_array(f"{site}.{key}", array)


def collect(doc: Mapping[str, Any]) -> tuple[Constraint, ...]:
    """Every version constraint at a site `COVERED_SITES` names, in that fixed order."""
    out: list[Constraint] = []
    project = doc.get("project")
    if isinstance(project, dict):
        requires_python = project.get("requires-python")
        if isinstance(requires_python, str) and requires_python.strip():
            out.append(
                Constraint(
                    "project.requires-python",
                    requires_python,
                    requires_python.strip(),
                    operators_in(requires_python),
                )
            )
        out.extend(_from_array("project.dependencies", project.get("dependencies")))
        out.extend(
            _from_table_of_arrays(
                "project.optional-dependencies", project.get("optional-dependencies")
            )
        )
    build_system = doc.get("build-system")
    if isinstance(build_system, dict):
        out.extend(_from_array("build-system.requires", build_system.get("requires")))
    out.extend(_from_table_of_arrays("dependency-groups", doc.get("dependency-groups")))
    tool = doc.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    if isinstance(uv, dict):
        for key in UV_ARRAY_KEYS:
            out.extend(_from_array(f"tool.uv.{key}", uv.get(key)))
    return tuple(out)


def uncovered_sites(doc: Mapping[str, Any]) -> tuple[str, ...]:
    """Constraint-shaped keys at paths this gate does not read. The anti-rot half of the scope."""
    covered = {site.split(".<")[0] for site in COVERED_SITES}
    found: list[str] = []

    def walk(node: Mapping[str, Any], prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in CONSTRAINT_KEY_NAMES and path not in covered:
                found.append(path)
            if isinstance(value, dict):
                walk(value, path)

    walk(doc, "")
    return tuple(sorted(found))


# ---------------------------------------------------------------------------
# The text pass: where each bound sits, and what comment is next to it
# ---------------------------------------------------------------------------


def _split_line(text: str, opened: str | None) -> tuple[str, str | None, str | None]:
    """Split one physical line into `(code, comment, still_open)`.

    A `#` inside a TOML string is not a comment, so the split has to know string state, and a
    multi-line string carries that state across lines -- hence `opened` in and `still_open` out.
    Basic strings (`"`) honour backslash escapes; literal strings (`'`) do not, which is why the
    delimiter's first character is tested before an escape is consumed.
    """
    delimiter = opened
    index = 0
    while index < len(text):
        if delimiter is None:
            if text[index] == "#":
                return text[:index], text[index + 1 :], None
            if text.startswith(_MULTILINE_DELIMITERS, index):
                delimiter = text[index : index + 3]
                index += 3
                continue
            if text[index] in "\"'":
                delimiter = text[index]
                index += 1
                continue
            index += 1
            continue
        if delimiter[0] == '"' and text[index] == "\\":
            index += 2
            continue
        if text.startswith(delimiter, index):
            index += len(delimiter)
            delimiter = None
            continue
        index += 1
    return text, None, delimiter if delimiter in _MULTILINE_DELIMITERS else None


def scan(source: str) -> tuple[Line, ...]:
    """Every physical line of the file, split into code and comment."""
    lines: list[Line] = []
    opened: str | None = None
    for number, text in enumerate(source.splitlines(), start=1):
        code, comment, opened = _split_line(text, opened)
        lines.append(Line(number, code, comment))
    return tuple(lines)


def _literals(code: str) -> Iterator[str]:
    """Every single-line TOML string literal in the code part of a line, unquoted.

    Escapes inside a basic string are left as written. A requirement string holding a backslash
    would therefore not match its parsed form, the reconciliation in `check_file` would notice, and
    the gate would exit 2 rather than pass it silently. No requirement in the fourteen files holds
    one, and the honest failure is cheaper than a decoder nobody exercises.
    """
    index = 0
    while index < len(code):
        quote = code[index]
        if quote not in "\"'":
            index += 1
            continue
        end = index + 1
        while end < len(code):
            if quote == '"' and code[end] == "\\":
                end += 2
                continue
            if code[end] == quote:
                break
            end += 1
        if end >= len(code):
            return
        yield code[index + 1 : end]
        index = end + 1


def justifying_lines(lines: Sequence[Line], index: int) -> tuple[int, ...]:
    """The line numbers of every comment adjacent to `lines[index]`, in the three accepted forms.

    Own-line trailing comment, then the contiguous comment-only run above, then the one below. A
    comment whose text is blank is not credited: a bare `#` carries no justification, and crediting
    it would make the gate satisfiable by a keystroke.
    """
    found: list[int] = []
    here = lines[index]
    if here.comment is not None and here.comment.strip():
        found.append(here.number)
    for step in (-1, 1):
        cursor = index + step
        while 0 <= cursor < len(lines) and lines[cursor].is_comment_only:
            comment = lines[cursor].comment
            if comment is not None and comment.strip():
                found.append(lines[cursor].number)
            cursor += step
    return tuple(sorted(found))


# ---------------------------------------------------------------------------
# The two passes, reconciled
# ---------------------------------------------------------------------------


def _load(path: Path) -> tuple[str, Mapping[str, Any]]:
    """The file as text and as TOML. Raises `GateNotRunError` when there is nothing to check.

    A missing or malformed file is deliberately NOT a finding, for the reason `gate_budgets.load`
    gives: a finding says "this bound is unjustified", which is a claim nothing can make about a
    file it could not read.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GateNotRunError(f"cannot read {path}: {exc}") from exc
    try:
        return source, tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise GateNotRunError(f"{path} is not parseable TOML: {exc}") from exc


_WHY: Final = (
    "11-repo-layout.md section 8.5: a constraint tighter than `>=` carries a comment "
    "(tools/gates.toml G7). Put the reason on the bound's own line, or on the line above or below "
    "it: the role from section 8.5's table, and for an exact pin the owner, the refresh procedure, "
    "the review date and the issue link."
)


def check_file(path: Path, label: str | None = None) -> FileReport:
    """One file, both passes, reconciled. Raises `GateNotRunError` when the two do not meet."""
    shown = label or path.as_posix()
    source, doc = _load(path)
    constraints = collect(doc)
    lines = scan(source)

    sites: dict[str, list[str]] = {}
    operators: dict[str, tuple[str, ...]] = {}
    for constraint in constraints:
        if not constraint.tightening:
            continue
        sites.setdefault(constraint.raw, []).append(constraint.site)
        operators[constraint.raw] = constraint.tightening

    occurrences: list[Occurrence] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        for literal in _literals(line.code):
            if literal not in sites:
                continue
            seen.add(literal)
            occurrences.append(
                Occurrence(
                    line.number,
                    literal,
                    tuple(sites[literal]),
                    operators[literal],
                    justifying_lines(lines, index),
                )
            )

    missing = sorted(set(sites) - seen)
    if missing:
        raise GateNotRunError(
            f"{shown}: the TOML pass found {len(missing)} tightened bound(s) the text pass could "
            f"not locate as a string literal, so no comment can be attributed to them: "
            f"{', '.join(repr(raw) for raw in missing)}"
        )

    findings = tuple(
        Finding(
            f"{shown}:{occurrence.line}",
            f"{occurrence.raw!r} carries {', '.join(occurrence.operators)} and no adjacent "
            f"comment (a bound at {', '.join(occurrence.sites)})",
            _WHY,
        )
        for occurrence in occurrences
        if not occurrence.justified
    )
    return FileReport(path, constraints, tuple(occurrences), uncovered_sites(doc), findings)


def _targets(root: Path, globs: Sequence[str]) -> list[Path]:
    """Every file the globs name, de-duplicated, in a stable order."""
    unique: list[Path] = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in unique:
                unique.append(path)
    return unique


def _say(text: str = "") -> None:
    """Write one line to stdout.

    `print` is banned repo-wide by ruff's `T20` (11-repo-layout.md section 8.1) and no
    `tools/*.py` per-file-ignore is declared, so the writer is explicit rather than suppressed --
    the same helper, for the same reason, as `tools/gate_budgets.py` and `tools/gate_weights.py`.
    """
    sys.stdout.write(f"{text}\n")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _report(root: Path, globs: Sequence[str], reports: Sequence[FileReport]) -> None:
    """The counts first, then the findings. The counts print on every run, pass or fail.

    A linter whose subject silently disappeared reports the same green as a linter that checked
    fourteen files, so the number of files, constraints and tightened bounds is part of the output
    contract and not a verbosity flag. `tools/gate_budgets.py` prints its two numbers
    unconditionally for the same reason.
    """
    constraints = sum(len(report.constraints) for report in reports)
    occurrences = [occurrence for report in reports for occurrence in report.occurrences]
    justified = [occurrence for occurrence in occurrences if occurrence.justified]
    findings = [finding for report in reports for finding in report.findings]

    _say(f"G7 gate_pins: {root} (11-repo-layout.md section 8.5, tools/gates.toml G7)")
    _say("  a PRESENCE check: the file is read as TEXT for the comment and as TOML for the bound.")
    _say(f"  glob(s): {', '.join(globs)}")
    _say(f"  {len(reports)} pyproject.toml file(s), {constraints} version constraint(s) parsed")
    _say(
        f"  {len(occurrences)} tightened bound(s), {len(justified)} carrying an adjacent comment, "
        f"{len(occurrences) - len(justified)} not"
    )
    # Ordered off OPERATORS, not off the frozenset: set iteration order is not a promise, and a
    # gate whose report line reshuffles between runs is a gate whose log diffs are noise.
    tightening = tuple(op for op in OPERATORS if op in TIGHTENING_OPERATORS)
    _say(f"  tightening: {' '.join(tightening)}")
    _say("  not tightening: >= > != (a floor, and section 8.5's sanctioned `!=` exclusion)")
    _say(f"  sites covered: {', '.join(COVERED_SITES)}")
    for report in reports:
        for site in report.uncovered:
            _say(
                f"  NOTE {_relative(report.path, root)} carries {site}, a constraint-shaped key "
                f"at a path this gate does not read"
            )
    for finding in findings:
        _say(finding.block())
    _say(f"G7 {'FAIL' if findings else 'ok'}  {len(findings)} finding(s)")


def main(argv: list[str] | None = None) -> int:
    """0 every tightened bound carries a comment, 1 one does not, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_pins.py",
        description=(
            "G7: over every packages/*/pyproject.toml, a version constraint tighter than `>=` "
            "(a `==`, `~=` or `<` bound) carries a justification comment on its own line, or on "
            "the line above or below it. 11-repo-layout.md section 8.5."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"the workspace root the glob is relative to (default: {REPO})",
    )
    parser.add_argument(
        "--glob",
        action="append",
        default=None,
        metavar="PATTERN",
        help=(
            "a glob of files to check, relative to --root; repeatable "
            f"(default: {' '.join(DEFAULT_GLOBS)})"
        ),
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN

    root: Path = (args.root if args.root is not None else REPO).resolve()
    globs: tuple[str, ...] = tuple(args.glob) if args.glob else DEFAULT_GLOBS

    targets = _targets(root, globs)
    if not targets:
        _say(f"G7 DID NOT RUN  no file under {root} matched {', '.join(globs)}")
        return EXIT_NOT_RUN

    reports: list[FileReport] = []
    try:
        for path in targets:
            reports.append(check_file(path, _relative(path, root)))
    except GateNotRunError as exc:
        _say(f"G7 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    _report(root, globs, reports)
    return EXIT_FAIL if any(report.findings for report in reports) else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
