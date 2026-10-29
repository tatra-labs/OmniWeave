"""`ow eval release-check`: exit 0 iff zero `unknown` and zero hard-gate failures. **D840.**

13-quality.md:1881 prints the verb: *"exit 0 iff zero `unknown`, zero hard-gate failures"*, and
:1884 says it *"is the one command a release pipeline runs, and it refuses on `unknown` -- which is
why `SKIP` is not a state anywhere in this document"*. 16-roadmap.md:978 runs it as
`ow eval release-check --strict # zero unknown; skip is not a state`, and V10-1 needs it to exit 0
on the tagged commit. `check_release()` reads one `.oweval` and the metric register,
`eval/gates.toml`, and returns every finding. `omniweave_conform.entry.release_check` drives it.

## Rulings

1. **Each subject's latest run is what a release ships.** Runs are grouped by
   `(suite, subject, corpus_id)` and the one with the greatest `started_ns` is judged, `run_id`
   breaking a tie. An older run is superseded and counted, never judged: a failure that a later
   run fixed is history, and the `.oweval` keeps history until `ow eval prune`.
2. **A latest run whose `status` is `unknown` refuses** (12-performance.md:1560: a run interrupted
   mid-suite *"is `unknown`, not partial"*), naming its `not_measured`. `partial` does not:
   13:1342 publishes a run under 2% missing with its narrower population disclosed. The run is
   read from `eval_run` itself, because the scoreboard view leaves an `unknown` run out.
3. **A scoreboard row whose `standing` is `UNKNOWN` refuses** (13:1691: a metric that failed to
   compute *"appears as `UNKNOWN`, and `ow eval release-check` **refuses** the release on it"*).
   `WITHHELD` and `UNRANKED` are publication standings, not outcomes, and do not. The refusal
   carries what the run said about that metric, and a rate over labels nobody has verified names
   the verification as its fix (D913): running the suite again cannot compute it.
4. **An `eval_perf` row refuses unless its `status` is `pass`.** `unstable` is `unknown` (13:332)
   and `unknown` is `unknown`. `stale` and `fail` refuse too: 12-performance.md:78 says *"there is
   no sixth value that lets a warning survive without failing"*, and a release that shipped past
   a `fail` row would make `fail` exactly that warning.
5. **A hard gate is a `[[gate]]` row with `kind = "hard"` and `class = "blocking"`.** Floors and
   ceilings are regression bands, judged by `ow eval golden`. `informational` is the register's
   own word for a row that does not block (12:1661). A row the check cannot read -- not a
   table, or a hard row with no string `metric`, `suite` or `slice` or a `budget` that is not a
   number -- is refused as a whole, because a gate the check skipped would be a `SKIP`.
6. **A hard gate matches the latest runs' rows of its `suite` and `metric` whose `slice_key` its
   `slice` matches** as a case-sensitive glob, so `*` matches `__macro__` and every named slice.
   **It fails when a matching value is not exactly its `budget`**: `hard` is equality, and
   `eval/gates.toml` says so. An `UNKNOWN` row is ruling 3's and is not compared as well.
   **A hard gate no row matches refuses as unmeasured**: a gate that did not run is `unknown`, and
   `unknown` is not "passed".
7. **`--strict` also refuses a suite of the seven with no run at all** (13:1881's set, as
   `eval_run.suite`'s CHECK spells it). Without it, the check judges what the `.oweval` and the
   register name. With it, a suite nothing ran is the `skip` 16:978 says is not a state.

Not built: 17-risks.md:905's extension, *"any `tools/risks.toml` row past `review_by`"* and *"any
kill criterion's instrument has not run"*, because there is no `tools/risks.toml` yet; and
holding a run's `code_fingerprint` to the checkout, which needs the fingerprint's producer.

Specified in 13-quality.md sections 2.1, 8.3 and 13.3, 12-performance.md section 1.2, and
16-roadmap.md W10.6.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.drivers.card import MIN_SLICE_N
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import perf, run_statuses, scoreboard

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.store.oweval import RunStatus, Standing

__all__ = [
    "DECLARED_UNKNOWN",
    "NOT_APPLICABLE",
    "SUITES",
    "Finding",
    "Gate",
    "Release",
    "check_release",
    "hard_gates",
    "latest",
]

SUITES: Final = ("parse", "extract", "retrieve", "absence", "roundtrip", "portability", "perf")
"""The seven suites (13-quality.md:1881, 16-roadmap.md W10.6), as `eval_run.suite` spells them."""

NOT_APPLICABLE: Final = frozenset({"extract"})
"""The suites that are NOT APPLICABLE at this release, and therefore do not refuse one. **D987.**

A user ruling of 2026-10-26: *"a `not-applicable` suite state with a required reason and the ruling
that made it so -- the target suite already has this vocabulary -- applied to `extract` only. Keep
`perf` as `unknown` and amend P10's exit criterion to zero unknown outside perf."*

`extract` is not applicable because no field-extraction driver ships: `parse.fields.lift` is a
tombstone with no successor, so `field_acc`, `doc_acc` and `hallucination_rate` are defined over a
pass this release does not have (a user ruling of 2026-10-23, D971). That is a different claim from
`perf`'s, which stays a refusal: perf IS measurable and this machine is not the pinned runner, so
reporting it as not applicable would retire a number the project still owes.

**This set is the policy and `eval_run.NOT_APPLICABLE` is the reason**, one fact each, and
`test_conform_release.py` asserts the two agree. A suite named here still has to write its run --
`--strict` refuses a suite with no run at all, and 16:942's "skip is not a state" is exactly that
rule -- so the disclosure is a row in the `.oweval` and a line in the report, never an absence."""

DECLARED_UNKNOWN: Final[Mapping[str, str]] = MappingProxyType(
    {
        "false_confident_zero": (
            "nothing at v1.0: the metric is declared unknown and says why. Its population is the "
            "whole answerable set, 13 questions against min_slice_n = 30, so no signature and no "
            "rerun can compute it -- only 17 more answerable questions can, and that is deferred "
            "past v1.0. Removing this row means publishing the rate, not editing the register"
        )
    }
)
"""The metrics that read `UNKNOWN` and do NOT refuse a release, each with its reason. **D1017.**

A user ruling of 2026-10-29. `false_confident_zero` is measured over the adoption catalogue's
answerable questions and D933 found 0 of 13 answered absent -- a clean result, and an unpublishable
one, because 13 is under `min_slice_n = 30` (13:1088). Unlike every other `UNKNOWN` in this
register the fix is not a reviewer's signature: ruling 3's refusal names verification as the fix
and a rate over an under-powered population has no verification to name. 13 IS the whole
answerable population, so the only fix is a bigger catalogue.

This is the metric-level shape of `NOT_APPLICABLE`'s suite-level one, and it is deliberately NOT
the same mechanism: the `absence` suite IS applicable and DOES run, its other metric
(`degradation_detection`) scores, and the run is `ok`. Only this one rate is withheld. Reporting
the suite not-applicable would retire `degradation_detection` with it.

**A declared unknown is still printed**, as `disclosed`, with the standing the run computed and
the reason above -- `ok` does not read `disclosed`, and the report does. A number the project owes
and cannot yet publish is a thing a reader must see, which is the same rule D987 wrote for a
not-applicable suite. 16-roadmap.md:978's P10 exit criterion names it beside `perf`."""

_FIX: Final = {
    "run": "fix what stopped the run, then ow eval run --suite {suite}{subject}",
    "metric": "fix what kept the metric from computing, then run its suite again",
    "labels": (
        'verify its labels: write checked = "verified" on each .assertions.toml row you confirm '
        "against its document, {n} or more a slice, then ow eval run --suite {suite}"
    ),
    "reference": (
        'verify its structure reference: write checked = "verified" on each .structure.jsonl row '
        "you confirm against its document -- every row of a document, since a part-signed "
        "reference has no precision denominator -- then ow eval run --suite {suite}"
    ),
    "population": (
        "measure {n} or more a slice: add questions to the suite's corpus, then ow eval run "
        "--suite {suite}"
    ),
    "perf": "fix the Runner or the regression the budget names, then run ow bench again",
    "gate": "fix the regression; a hard budget moves only by a reviewed eval/gates.toml diff",
    "not_applicable": (
        "nothing: the suite is not applicable at this release and says why. Removing this line "
        "means shipping the pass it is about, not editing the register"
    ),
    "unmeasured": "run the gate's suite: ow eval run --suite {suite}",
    "suite": "run the suite: ow eval run --suite {suite}",
}
_REGISTER_FIX: Final = "mend eval/gates.toml's [[gate]] row, then run ow eval release-check again"


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason the release is refused: what kind, what it names, why, and the fix."""

    kind: str
    names: str
    why: str
    fix: str

    @property
    def line(self) -> str:
        return f"{self.kind:<10}  {self.names}: {self.why}"


@dataclass(frozen=True, slots=True)
class Gate:
    """A hard, blocking `[[gate]]` row (ruling 5)."""

    metric: str
    suite: str
    slice: str
    budget: float


@dataclass(frozen=True, slots=True)
class Release:
    """What `check_release()` judged, and every finding. `ok` iff there are none."""

    runs: int
    superseded: int
    gates: int
    findings: tuple[Finding, ...]
    disclosed: tuple[Finding, ...] = ()
    """D987: the not-applicable suites, reported and not refused. `ok` does not read them, and the
    report prints them, because a gap that is a decision is still a thing a reader must see."""

    @property
    def ok(self) -> bool:
        return not self.findings


def latest(runs: Iterable[RunStatus]) -> tuple[RunStatus, ...]:
    """Ruling 1: each `(suite, subject, corpus_id)`'s latest run, in `run_id` order."""
    best: dict[tuple[str, str, str], RunStatus] = {}
    for run in runs:
        key = (run.suite, run.subject, run.corpus_id)
        held = best.get(key)
        if held is None or (run.started_ns, run.run_id) > (held.started_ns, held.run_id):
            best[key] = run
    return tuple(sorted(best.values(), key=lambda run: run.run_id))


def _unknown(row: Standing, notes: Sequence[str]) -> Finding:
    """Ruling 3's refusal, saying why when the run said (D913): a rate over labels nobody has
    verified names the verification as its fix, since no rerun can compute it, and a rate over
    fewer questions than `min_slice_n` names more questions as its fix (D933)."""
    named = f"{row.metric}@{row.slice_key} in {row.suite}/{row.subject} run {row.run_id}"
    why = [note for note in notes if note.startswith(f"{row.metric}: ")]
    if not why:
        return Finding("metric", named, "UNKNOWN", _FIX["metric"])
    detail = "UNKNOWN; " + "; ".join(note.removeprefix(f"{row.metric}: ") for note in why)
    if any("unverified assertion" in note for note in why):
        return Finding(
            "metric", named, detail, _FIX["labels"].format(n=MIN_SLICE_N, suite=row.suite)
        )
    #  D982: a structure reference is signed per document and in its own file, so the labels fix
    #  would name the wrong file and the wrong unit.
    if any("reference row(s) unsigned" in note for note in why):
        return Finding("metric", named, detail, _FIX["reference"].format(suite=row.suite))
    if any("under min_slice_n" in note for note in why):
        return Finding(
            "metric", named, detail, _FIX["population"].format(n=MIN_SLICE_N, suite=row.suite)
        )
    return Finding("metric", named, detail, _FIX["metric"])


def hard_gates(register: Mapping[str, Any]) -> tuple[Gate, ...]:
    """Ruling 5: the register's hard blocking gates, or `QualityError` naming the first bad row."""
    rows = register.get("gate", [])
    if not isinstance(rows, list):
        raise _error("eval/gates.toml: `gate` is not an array of tables")
    gates = []
    for at, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise _error(f"eval/gates.toml: [[gate]] #{at} is not a table")
        if row.get("kind") != "hard" or row.get("class") != "blocking":
            continue
        named = [key for key in ("metric", "suite", "slice") if not _text(row.get(key))]
        if named:
            raise _error(f"eval/gates.toml: hard [[gate]] #{at} has no string {named[0]}")
        budget = row.get("budget")
        if isinstance(budget, bool) or not isinstance(budget, int | float):
            raise _error(f"eval/gates.toml: hard [[gate]] #{at} has no numeric budget")
        gates.append(Gate(row["metric"], row["suite"], row["slice"], float(budget)))
    return tuple(gates)


def _subject_flag(suite: str, subject: str) -> str:
    """A run finding's `--subject`, only where `ow eval run` takes one: a parse driver (D872)."""
    return f" --subject {subject}" if suite == "parse" else ""


def check_release(connection: Any, register: Mapping[str, Any], *, strict: bool) -> Release:
    """Rulings 1-7 over one `.oweval` and the metric register."""
    gates = hard_gates(register)
    every = run_statuses(connection)
    runs = latest(every)
    judged = {run.run_id for run in runs}
    unknown_runs = [run for run in runs if run.status == "unknown"]
    findings = [
        Finding(
            "run",
            f"{run.suite}/{run.subject} run {run.run_id}",
            "status unknown; not measured: " + (", ".join(run.not_measured) or "(none named)"),
            _FIX["run"].format(suite=run.suite, subject=_subject_flag(run.suite, run.subject)),
        )
        for run in unknown_runs
        if run.suite not in NOT_APPLICABLE
    ]
    #  D987: a not-applicable suite's run is a disclosure, not a gap. It is printed with its
    #  reason and the ruling, and it does not refuse the release.
    disclosed = tuple(
        Finding(
            "not-applicable",
            f"{run.suite}/{run.subject} run {run.run_id}",
            ", ".join(run.not_measured) or "(no reason named)",
            _FIX["not_applicable"],
        )
        for run in unknown_runs
        if run.suite in NOT_APPLICABLE
    )
    board = [row for row in scoreboard(connection) if row.run_id in judged]
    said = {run.run_id: run.not_measured for run in runs}
    unknown_rows = [row for row in board if row.standing == "UNKNOWN"]
    findings += [
        _unknown(row, said.get(row.run_id, ()))
        for row in unknown_rows
        if row.metric not in DECLARED_UNKNOWN
    ]
    #  D1017: a declared metric's UNKNOWN is a disclosure and not a gap. It keeps the detail the
    #  run computed -- the population and why it is short -- so the report says 0 of 13 rather
    #  than only that something was withheld, and carries the ruling as its fix.
    disclosed += tuple(
        Finding(
            "declared-unknown",
            f"{row.metric}@{row.slice_key} in {row.suite}/{row.subject} run {row.run_id}",
            _unknown(row, said.get(row.run_id, ())).why,
            DECLARED_UNKNOWN[row.metric],
        )
        for row in unknown_rows
        if row.metric in DECLARED_UNKNOWN
    )
    findings += [
        Finding(
            "perf", f"{row.budget_id} in run {row.run_id}", f"status {row.status}", _FIX["perf"]
        )
        for row in perf(connection)
        if row.run_id in judged and row.status != "pass"
    ]
    for gate in gates:
        matched = [
            row
            for row in board
            if row.suite == gate.suite
            and row.metric == gate.metric
            and fnmatchcase(row.slice_key, gate.slice)
        ]
        if not matched:
            findings.append(
                Finding(
                    "unmeasured",
                    f"hard gate {gate.metric}@{gate.slice}",
                    f"no {gate.suite} run measured it",
                    _FIX["unmeasured"].format(suite=gate.suite),
                )
            )
        findings += [
            Finding(
                "gate",
                f"{gate.metric}@{row.slice_key} in {row.suite}/{row.subject} run {row.run_id}",
                f"{row.value} is not the hard budget {gate.budget}",
                _FIX["gate"],
            )
            for row in matched
            if row.standing != "UNKNOWN" and row.value != gate.budget
        ]
    if strict:
        ran = {run.suite for run in runs}
        findings += [
            Finding("suite", suite, "no run at all", _FIX["suite"].format(suite=suite))
            for suite in SUITES
            if suite not in ran
        ]
    return Release(len(runs), len(every) - len(runs), len(gates), tuple(findings), disclosed)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _error(message: str) -> QualityError:
    return QualityError(message, fix=_REGISTER_FIX)
