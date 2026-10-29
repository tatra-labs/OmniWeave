"""`pyright` strict over `packages` and `tools`, held at a per-rule ceiling that can only fall.

11-repo-layout.md section 8.1's table names `pyright` strict and section 8.2 says where it may run.
Neither says what it checks, so there was no `[tool.pyright]` and ci.yml's step printed
`NOT ENFORCED` -- a bare run would have type-checked under pyright's own defaults, asserting
something section 8.1 did not ask for. D997 wrote the table, under a user ruling of 2026-10-27
scoping it to `packages/*/src` and `tools` with tests excluded.

**Writing the table does not make the tree clean, and this script is the honest shape of that.**
Measured when the table landed, with the five unknown-type rules off and the four
invariant-contradicting rules off (pyproject.toml says why for each): **157 errors**. Running
`pyright` bare in CI would be a red build on every PR until all 157 are gone, which means the step
stays off and the number stays unmeasured -- which is how it got to 1,722 under full strict without
anyone noticing. So the step runs THIS, which fails on a RISE and equally on a FALL.

## Why the ceiling is per rule and not one total

A single total hides a trade. Fix twelve `reportArgumentType` errors, introduce twelve
`reportOptionalMemberAccess` ones, and a total-only ratchet reports no change -- while the tree has
acquired a new defect class and lost a fixed one. Each rule's count is pinned separately, so the
failure message names the rule that moved, and a new rule appearing at all is a finding whatever
the total says.

## Why a FALL fails too

A ratchet nobody tightens is a number nobody is watching -- the argument `tools/gates.toml` makes
for G27 clause d2's two ceilings, in the same words. Fixing an error is supposed to cost one line
in `CEILING`, and that line is the record of the fix.

## The one class that is pinned to its reason rather than merely counted

45 of the 157 are `reportUndefinedVariable`, and every one is a forward reference to a type no
module has built yet -- `DocRecord`, `Frame`, `Rel`, `AssetRef`, `QuoteVerdict` and the rest, each
already carrying `# noqa: F821` and a plan citation, under `model/doc.py`'s own sentence: *"Five
names in the signatures below have no module yet."* They cannot be fixed without building W2.1's
modules, so `check_forward_references` asserts the undefined names are drawn from `FORWARD` and
nothing else. A new undefined name fails even while the count holds, which a count alone would
miss.

## Why it is not named `gate_pyright.py`

`test_gates_register.py` fails on any `tools/gate_*.py` that `tools/gates.toml` does not name, and
there is no row to add. No `G<n>` covers pyright -- the series is append-by-ADR (section 1.7) and
inventing a number here would be the renumbering that forbids -- and the `[[job_assertion]]` count
is **nine at release 1** by ADR-2 decision 2 (`RK-Q1`), so a tenth row would contradict the
document that fixed the count. `tools/plan_lint.py` set the precedent for exactly this and
`test_plan_lint.py` records it: the script is named outside the glob, and if a row is ever added
the file is renamed in the same change.

Exit 0 clean, 1 with one `pyright-ceiling FAIL` block per finding, 2 on a usage error or when
`pyright` cannot run.
Specified in 11-repo-layout.md sections 8.1 and 8.2, and a user ruling of 2026-10-27.
"""

from __future__ import annotations

import collections
import json
import shutil
import subprocess  # noqa: TID251 -- running `pyright` IS this gate's subject.
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
PREFIX: Final = "pyright-ceiling"
FAIL_INDENT: Final = "    "
EXIT_NOT_RUN: Final = 2

CEILING: Final[dict[str, int]] = {
    #  Deliberate forward references to unbuilt types. See `FORWARD` and the module docstring;
    #  these fall when W2.1 lands `model/block.py`'s cluster, not before.
    "reportUndefinedVariable": 45,
    #  Real findings, every one. Grouped so a fix names its rule in the diff.
    "reportArgumentType": 37,
    #  FIXED, D1006: all 22 were a `@contextmanager` or `@asynccontextmanager` annotated
    #  `-> Iterator[T]` / `-> AsyncIterator[T]`, which typeshed marks deprecated in favour of
    #  `-> Generator[T]` and `-> AsyncGenerator[T]`. Each return type was changed at the site
    #  pyright named -- the DECORATOR line, with the annotation on the signature below it -- and
    #  the imports followed. The row stays at 0 rather than leaving the table, because a rule
    #  absent here and present in a run is a defect class nobody has looked at, and 0 is the
    #  claim that this one is clean rather than unexamined. The `os.stat_result.st_ctime` note
    #  this comment used to carry does not fire: nothing in the measured run reports it.
    "reportDeprecated": 0,
    #  A name imported from a module that re-exports it without `__all__`. The fix is to import
    #  from the module that declares it, which D997 did for two of the sixteen.
    "reportPrivateImportUsage": 14,
    #  `object` arithmetic on values read out of a TOML document before they are narrowed.
    "reportOperatorIssue": 9,
    #  Third-party packages that ship no stubs. pypdfium2 is the whole of it; this project's own
    #  fifteen distributions ship `py.typed` since D996, which removed 824 of these.
    "reportMissingTypeStubs": 9,
    "reportGeneralTypeIssues": 5,
    "reportAttributeAccessIssue": 4,
    "reportUnnecessaryComparison": 3,
    "reportReturnType": 2,
    "reportUnnecessaryCast": 2,
    "reportAssignmentType": 1,
    "reportIncompatibleMethodOverride": 1,
    "reportOptionalMemberAccess": 1,
    "reportOptionalOperand": 1,
    "reportUnusedImport": 1,
}
"""Every rule that errors today, with the count it errors at. Measured, not chosen.

A rule missing from this table and present in the run is a finding on its own terms: it means a
defect class appeared that nobody has looked at. A rule here at a lower count is also a finding,
because the fix is supposed to cost this line."""

FORWARD: Final[frozenset[str]] = frozenset(
    {
        "AliasDraft",
        "AnchorDraft",
        "AssetDraft",
        "AssetRef",
        "CellDraft",
        "ChannelResult",
        "ClaimDraft",
        "ClaimId",
        "DegradeCause",
        "Diag",
        "DocRecord",
        "EdgeDraft",
        "EdgeId",
        "EntityDraft",
        "EntityId",
        "Frame",
        "Grid",
        "Hit",
        "Limits",
        "MentionDraft",
        "MentionId",
        "PageRecord",
        "PassIdentity",
        "QuoteVerdict",
        "Rel",
        "RunId",
        "RunReport",
        "RunStatus",
        "SegmentRef",
        "Spend",
        "WorkSpec",
        "XrefDraft",
    }
)
"""The names `reportUndefinedVariable` is allowed to name, and no others.

Each is a type the plan specifies and no module has built, cited at its use site with
`# noqa: F821` and a plan line -- `DocRecord` at 03:404, `Rel` at 03:439, `Grid` at 03:1880,
`Diag` at 03:1800. The set is the point: a typo in an annotation produces an undefined name too,
and a count that only counted would let it through at the cost of one real forward reference being
fixed somewhere else."""

__all__ = [
    "CEILING",
    "FORWARD",
    "Finding",
    "check_ceiling",
    "check_forward_references",
    "main",
    "run_pyright",
]


@dataclass(frozen=True, slots=True)
class Finding:
    headline: str
    detail: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join((f"{PREFIX} FAIL: {self.headline}", *self.detail))


def run_pyright() -> list[dict[str, object]] | None:
    """Every error diagnostic, or `None` when `pyright` could not run at all.

    `None` is not zero errors and the two must never collapse: a shim that failed to fetch its Node
    runtime would otherwise read as a clean tree, which is the C55 shape this repository keeps
    paying for.
    """
    if shutil.which("pyright") is None and not (REPO / ".venv").exists():
        return None
    try:
        #  A fixed argv, no shell, and cwd pinned to the repository.
        done = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson"],
            capture_output=True,
            text=True,
            cwd=REPO,
            check=False,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = done.stdout
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    diagnostics = parsed.get("generalDiagnostics")
    if not isinstance(diagnostics, list):
        return None
    return [
        one for one in diagnostics if isinstance(one, dict) and str(one.get("severity")) == "error"
    ]


def check_ceiling(diagnostics: list[dict[str, object]]) -> tuple[list[str], list[Finding]]:
    """Every rule's count against `CEILING`, in both directions."""
    counted = collections.Counter(str(one.get("rule", "(no rule)")) for one in diagnostics)
    findings: list[Finding] = []
    for rule in sorted(set(counted) | set(CEILING)):
        found = counted.get(rule, 0)
        allowed = CEILING.get(rule)
        if allowed is None:
            findings.append(
                Finding(
                    f"{rule}: {found} error(s), and the rule is not in CEILING at all.",
                    (
                        FAIL_INDENT + _locus(diagnostics, rule),
                        FAIL_INDENT
                        + "a rule appearing for the first time is a defect class nobody has "
                        + "looked at. Fix it, or add the row and say what it is.",
                    ),
                )
            )
        elif found > allowed:
            findings.append(
                Finding(
                    f"{rule}: {found} error(s) against a ceiling of {allowed}.",
                    (FAIL_INDENT + _locus(diagnostics, rule),),
                )
            )
        elif found < allowed:
            findings.append(
                Finding(
                    f"{rule}: {found} error(s) and the ceiling is still {allowed}.",
                    (
                        FAIL_INDENT
                        + f"fix: lower it to {found}. A ratchet nobody tightens is a number "
                        + "nobody is watching.",
                    ),
                )
            )
    report = [
        f"  {len(diagnostics)} error(s) over {len(counted)} rule(s), ceiling "
        f"{sum(CEILING.values())} over {len(CEILING)}"
    ]
    report.extend(
        f"    {rule:38} {counted.get(rule, 0):4} / {CEILING[rule]}" for rule in sorted(CEILING)
    )
    return report, findings


def _locus(diagnostics: list[dict[str, object]], rule: str) -> str:
    """One file:line for a rule, so a failure starts somewhere rather than nowhere."""
    for one in diagnostics:
        if str(one.get("rule")) != rule:
            continue
        where = Path(str(one.get("file", "?")))
        span = one.get("range")
        line = 0
        if isinstance(span, dict):
            start = span.get("start")
            if isinstance(start, dict) and isinstance(start.get("line"), int):
                line = int(start["line"]) + 1
        try:
            shown = where.relative_to(REPO).as_posix()
        except ValueError:
            shown = where.name
        return f"first at {shown}:{line}"
    return "no locus"


def check_forward_references(
    diagnostics: list[dict[str, object]],
) -> tuple[list[str], list[Finding]]:
    """Every undefined name is one of `FORWARD`'s, and every one of `FORWARD`'s is still used."""
    found: set[str] = set()
    for one in diagnostics:
        if str(one.get("rule")) != "reportUndefinedVariable":
            continue
        message = str(one.get("message", ""))
        opened = message.find('"')
        closed = message.find('"', opened + 1)
        if opened >= 0 and closed > opened:
            found.add(message[opened + 1 : closed])
    findings: list[Finding] = []
    invented = sorted(found - FORWARD)
    if invented:
        findings.append(
            Finding(
                f"{len(invented)} undefined name(s) that are not declared forward references: "
                + ", ".join(invented),
                (
                    FAIL_INDENT
                    + "a typo in an annotation is an undefined name too. Fix it, or add it to "
                    + "FORWARD with the plan line that specifies the type.",
                ),
            )
        )
    stale = sorted(FORWARD - found)
    if stale:
        findings.append(
            Finding(
                f"{len(stale)} FORWARD name(s) nothing names any more: " + ", ".join(stale),
                (FAIL_INDENT + "fix: delete the row -- the module that defines it has landed.",),
            )
        )
    return [f"  forward references: {len(found)} name(s), all declared"], findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stdout.write("usage: tools/pyright_ceiling.py\n")
        return EXIT_NOT_RUN
    diagnostics = run_pyright()
    if diagnostics is None:
        sys.stdout.write(
            f"{PREFIX} DID NOT RUN: pyright produced no readable diagnostics.\n"
            f"{FAIL_INDENT}section 8.2: the shim fetches a Node runtime unless "
            "PYRIGHT_PYTHON_GLOBAL_NODE=1 finds one on PATH.\n"
        )
        return EXIT_NOT_RUN
    report: list[str] = []
    findings: list[Finding] = []
    for lines, found in (check_ceiling(diagnostics), check_forward_references(diagnostics)):
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
        f"{PREFIX} ok  {len(diagnostics)} error(s), every rule at its ceiling, "
        f"every undefined name a declared forward reference\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
