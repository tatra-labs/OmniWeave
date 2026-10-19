"""`ow eval <verb>`: `publish` (D833), `release-check` (D840), `bless` (D846) and `run` (D868).

10-interfaces.md section 2.5: *"`omniweave-conform` implements the `eval` Action group"*. Every
`eval` row stays in `ACTIONS` here, and the work happens across an entry point,
`omniweave.surface.dispatch.eval_entry()`. This module parses, resolves paths against the
working directory, calls the verb with builtin values, and prints.

13-quality.md section 11.1: *"`ow eval publish` exports the `eval_scoreboard` view into the
committed JSON tree"*, which Q-G19 byte-diff gates. Section 13.3 prints the verb.

13-quality.md:1881: *"`ow eval release-check` # exit 0 iff zero `unknown`, zero hard-gate
failures"*. `omniweave_conform.release` holds what a finding is; this module prints them.

13-quality.md:1847 makes `ow eval bless --inventory --reason '<>'` OW-Q-013's fix: Q-G24 refuses
a fall in the test inventory with no `BLESS.log` row, and this verb writes the inventory and
the row together.

## Rulings

1. **Missing `.oweval` exits 2**, as `NotFoundError`, naming the path. It is never opened, because
   opening would create an empty store and publish nothing.
2. **`--check` compares and writes nothing.** A file that differs is printed, and the verb exits 1
   with `ow eval publish` as the fix, the way `ow surface emit --check` reports G25.
3. **A refused publication exits 1.** Export raises `QualityError` when a row fails Q-G19 or a
   metric ships without its Q-G21 partner. The error is reported as any refusal is, under
   `--render json` and `--json-errors` alike, and the exit is 1, the code the gate scripts give
   a failing row. `QualityError` itself carries no exit of its own, and its floor of 70 means
   "report a bug", which a run with no scope is not.
4. **`--render json` prints one object**: `files`, `rows`, `changed` and `written`.
   `--render jsonl|rows` has no writer here and is refused by name, as `ow out targets` refuses
   it. `--quiet` is not read, so `switches.check()` refuses it.
5. **Without `omniweave-conform` the verb is `OW-A-027`, exit 64**, from `eval_entry()`, naming
   `pip install omniweave-conform` (10:286).
6. **`release-check` exits 1 on any finding** and 0 on none, 13:1881's *"exit 0 iff"*. Each
   finding prints as a line, then its fix, then one verdict line. `--render json` prints one
   object: `ok`, `strict`, `runs`, `superseded`, `gates` and `findings`. A missing `.oweval`
   or register exits 2, as ruling 1. A register the check cannot read is a refusal, exit 1,
   as ruling 3.
7. **`bless --inventory` is OW-Q-013's fix (13:1847).** It needs `OMNIWEAVE_BLESS=1` in the
   environment, which is section 5.5's first requirement, and a `--reason`. `--counters` is
   refused by name, as nothing writes a counter baseline yet. The date is today's, UTC, read
   once here from `SystemClock` as the other surfaces read the wall clock. A refusal in the
   bless is `QualityError`, exit 1, as in ruling 3.
8. **`run` measures suites and writes them** (13:1873, D868, D869). `--suite` omitted is every
   suite this build measures, `parse`, `absence`, `retrieve` (D870) then `roundtrip` (D871),
   written in one transaction; another of the seven is refused by name, as is a name outside
   them. `--deterministic-half` names the only half of `absence` built, so it is refused beside
   any other suite, and `--subject`, a parse driver, beside any suite but `parse`, whose subjects
   are its own. The absence harness is handed
   `surface.admit.admit`, 13:1306's check of each fix against this registry. `--witness` and
   `--cassette` must be values their `eval_run` columns admit. `--validate-judge` and `--emit`
   are refused by name, and so is the global `--corpus`, which 13:1873 gives this verb as
   `--corpus C@V`: each suite's corpus is its own, so a corpus named here would be ignored. The
   `.oweval` is created when it does not exist, because a run is what writes one. Each subject
   prints as a line in its suite's terms, then one verdict line. `--render json` prints one
   object: `suites`, `oweval` and `runs`. A refusal from a suite, such as a register with no
   `[[subject]]`, is `QualityError`, exit 1, as in ruling 3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.errors import InternalError, NotFoundError, OwError, QualityError, UsageError

from omniweave.sdk.reports import (
    EvalBlessReport,
    EvalPublishReport,
    EvalReleaseCheckReport,
    EvalReleaseFinding,
    EvalRunReport,
    EvalRunRow,
)
from omniweave.surface.dispatch import eval_entry
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

__all__ = ["EVAL_WORD", "main"]

EVAL_WORD: Final[str] = "eval"
_PUBLISH_FIX: Final[str] = "ow eval publish [--oweval PATH] [--results DIR] [--check]"
_RELEASE_FIX: Final[str] = "ow eval release-check [--oweval PATH] [--gates PATH] [--strict]"
_BLESS_FIX: Final[str] = "OMNIWEAVE_BLESS=1 ow eval bless --inventory --reason '<why>'"
_RUN_FIX: Final[str] = "ow eval run --suite parse [--subject D] [--witness W] [--cassette MODE]"
SUITES: Final[tuple[str, ...]] = (
    "parse",
    "extract",
    "retrieve",
    "absence",
    "roundtrip",
    "portability",
    "perf",
)
"""13:237-242's seven suites, the `eval_run.suite` CHECK, in that order."""
RUN_SUITES: Final[tuple[str, ...]] = ("parse", "absence", "retrieve", "roundtrip")
"""Ruling 8: the suites `ow eval run` measures in this build."""
WITNESSES: Final[tuple[str, ...]] = ("ci", "self", "third_party")
CASSETTES: Final[tuple[str, ...]] = ("off", "allow", "required")
_STALE: Final[int] = 1
_REFUSED: Final[int] = 1


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow eval ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(EVAL_WORD, parsed)
        return _VERBS[parsed.ow_action](parsed, cwd=cwd, env=env, stdout=stdout)
    except QualityError as error:
        report(error, parsed, stdout=stdout, stderr=stderr)
        return _REFUSED
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _publish(
    parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO
) -> int:
    del env  # `publish` reads no environment.
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow eval publish",
            fix=_PUBLISH_FIX,
        )
    oweval = _oweval(parsed, cwd)
    results = cwd / parsed.results
    done = _report(
        eval_entry("publish")(oweval=str(oweval), results=str(results), check=parsed.check)
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_row(done), ensure_ascii=False) + "\n")
    else:
        for line in _lines(done, results=parsed.results, check=parsed.check):
            stdout.write(line + "\n")
    return _STALE if parsed.check and done.changed else 0


def _report(result: Mapping[str, object]) -> EvalPublishReport:
    """The entry point's builtins as this side's report. Anything else is a broken install."""
    files = result.get("files")
    changed = result.get("changed")
    rows = result.get("rows")
    written = result.get("written")
    if not (
        isinstance(files, list)
        and isinstance(changed, list)
        and isinstance(rows, int)
        and isinstance(written, bool)
    ):
        raise InternalError(
            "the [omniweave.eval] publish entry point returned no files, changed, rows and written",
            fix="pip install --force-reinstall omniweave-conform",
        )
    return EvalPublishReport(
        files=tuple(str(path) for path in files),
        rows=rows,
        changed=tuple(str(path) for path in changed),
        written=written,
    )


def _row(done: EvalPublishReport) -> dict[str, object]:
    return {
        "files": list(done.files),
        "rows": done.rows,
        "changed": list(done.changed),
        "written": done.written,
    }


def _lines(done: EvalPublishReport, *, results: str, check: bool) -> list[str]:
    """Ruling 2's text form: what differs, then one line of verdict."""
    size = f"{len(done.files)} file(s), {done.rows} row(s)"
    if not done.changed:
        return [f"{results} matches the .oweval: {size}"]
    verb = "differs" if check else "wrote"
    lines = [f"  {verb}  {path}" for path in done.changed]
    if check:
        lines.append(
            f"ow eval publish --check: {len(done.changed)} file(s) differ; run ow eval publish"
        )
    else:
        lines.append(f"published {results}: {size}, {len(done.changed)} file(s) changed")
    return lines


def _release_check(
    parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO
) -> int:
    """Ruling 6."""
    del env  # `release-check` reads no environment.
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow eval release-check",
            fix=_RELEASE_FIX,
        )
    oweval = _oweval(parsed, cwd)
    gates = cwd / parsed.gates
    if not gates.is_file():
        raise NotFoundError(
            f"no metric register at {gates}",
            fix="pass --gates PATH naming the eval/gates.toml register",
        )
    done = _release(
        eval_entry("release-check")(oweval=str(oweval), gates=str(gates), strict=parsed.strict),
        strict=parsed.strict,
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_release_row(done), ensure_ascii=False) + "\n")
    else:
        for line in _release_lines(done):
            stdout.write(line + "\n")
    return 0 if done.ok else _REFUSED


def _oweval(parsed: argparse.Namespace, cwd: Path) -> Path:
    """Ruling 1: the `.oweval`, resolved, or `NotFoundError` before anything opens it."""
    oweval = cwd / parsed.oweval
    if not oweval.is_file():
        raise NotFoundError(
            f"no .oweval at {oweval}",
            fix="run the eval suites to write one, or pass --oweval PATH",
        )
    return oweval


def _release(result: Mapping[str, object], *, strict: bool) -> EvalReleaseCheckReport:
    """The entry point's builtins as this side's report. Anything else is a broken install."""
    ok, runs, superseded, gates = (result.get(k) for k in ("ok", "runs", "superseded", "gates"))
    findings = result.get("findings")
    if not (
        isinstance(ok, bool)
        and isinstance(runs, int)
        and isinstance(superseded, int)
        and isinstance(gates, int)
        and isinstance(findings, list)
        and all(_finding(row) for row in findings)
    ):
        raise InternalError(
            "the [omniweave.eval] release-check entry point returned no ok, runs, superseded,"
            " gates and findings",
            fix="pip install --force-reinstall omniweave-conform",
        )
    return EvalReleaseCheckReport(
        ok=ok,
        strict=strict,
        runs=runs,
        superseded=superseded,
        gates=gates,
        findings=tuple(
            EvalReleaseFinding(kind=row["kind"], names=row["names"], why=row["why"], fix=row["fix"])
            for row in findings
        ),
    )


def _finding(row: object) -> bool:
    return isinstance(row, dict) and all(
        isinstance(row.get(key), str) for key in ("kind", "names", "why", "fix")
    )


def _release_row(done: EvalReleaseCheckReport) -> dict[str, object]:
    return {
        "ok": done.ok,
        "strict": done.strict,
        "runs": done.runs,
        "superseded": done.superseded,
        "gates": done.gates,
        "findings": [
            {"kind": f.kind, "names": f.names, "why": f.why, "fix": f.fix} for f in done.findings
        ],
    }


def _release_lines(done: EvalReleaseCheckReport) -> list[str]:
    """Ruling 6's text form: each finding and its fix, then one line of verdict."""
    lines = []
    for f in done.findings:
        lines.append(f"  {f.kind:<10}  {f.names}: {f.why}")
        lines.append(f"  {'':<10}  fix: {f.fix}")
    judged = (
        f"{done.runs} latest run(s), {done.superseded} superseded, {done.gates} hard gate(s)"
        + (", --strict" if done.strict else "")
    )
    if done.ok:
        lines.append(f"ow eval release-check: ok; {judged}")
    else:
        lines.append(f"ow eval release-check: refused, {len(done.findings)} finding(s); {judged}")
    return lines


def _bless(parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO) -> int:
    """Ruling 7."""
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow eval bless", fix=_BLESS_FIX
        )
    if parsed.counters:
        raise UsageError(
            "--counters is parsed and not served by ow eval bless: nothing writes a counter "
            "baseline yet",
            fix=_BLESS_FIX,
        )
    if not parsed.inventory:
        raise UsageError(
            "ow eval bless needs --inventory, the one thing it blesses", fix=_BLESS_FIX
        )
    if not parsed.reason:
        raise UsageError("ow eval bless needs --reason, the row's why", fix=_BLESS_FIX)
    done = _blessed(
        eval_entry("bless")(root=str(cwd), reason=parsed.reason, date=_today(), env=dict(env))
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_bless_row(done), ensure_ascii=False) + "\n")
        return 0
    for line in done.fell:
        stdout.write(f"  fell     {line}\n")
    stdout.write(f"  row      {done.row}\n")
    stdout.write(
        f"blessed {done.inventory}: {len(done.changed)} area(s) moved, {len(done.fell)} fell,"
        f" {done.tests} test(s); wrote {done.inventory} and a row in {done.log}\n"
    )
    return 0


def _today() -> str:
    """Ruling 7: the row's date, UTC, from the one wall-clock read."""
    import datetime as dt  # noqa: PLC0415 -- only `bless` pays

    from omniweave_core.clock import SystemClock  # noqa: PLC0415

    seconds = SystemClock().wall_ns() / 1e9
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).date().isoformat()


def _blessed(result: Mapping[str, object]) -> EvalBlessReport:
    """The entry point's builtins as this side's report. Anything else is a broken install."""
    inventory, log, row = (result.get(k) for k in ("inventory", "log", "row"))
    fell, changed, tests = result.get("fell"), result.get("changed"), result.get("tests")
    if not (
        isinstance(inventory, str)
        and isinstance(log, str)
        and isinstance(row, str)
        and isinstance(fell, list)
        and isinstance(changed, list)
        and isinstance(tests, int)
        and all(isinstance(x, str) for x in (*fell, *changed))
    ):
        raise InternalError(
            "the [omniweave.eval] bless entry point returned no inventory, log, row, fell, changed"
            " and tests",
            fix="pip install --force-reinstall omniweave-conform",
        )
    return EvalBlessReport(
        inventory=inventory,
        log=log,
        row=row,
        fell=tuple(str(x) for x in fell),
        changed=tuple(str(x) for x in changed),
        tests=tests,
    )


def _bless_row(done: EvalBlessReport) -> dict[str, object]:
    return {
        "inventory": done.inventory,
        "log": done.log,
        "row": done.row,
        "fell": list(done.fell),
        "changed": list(done.changed),
        "tests": done.tests,
    }


def _run(parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO) -> int:
    """Ruling 8."""
    del env  # `run` reads no environment.
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow eval run", fix=_RUN_FIX
        )
    named = [
        flag
        for flag, given in (
            ("--corpus", parsed.corpus is not None),
            ("--validate-judge", parsed.validate_judge),
            ("--emit", parsed.emit is not None),
        )
        if given
    ]
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow eval run in this build: each "
            "subject's corpus is its own fixture set, no judge runs, and no result file is written",
            fix=_RUN_FIX,
        )
    suite = parsed.suite
    if suite is not None and suite not in SUITES:
        raise UsageError(f"--suite {suite!r} is not one of {', '.join(SUITES)}", fix=_RUN_FIX)
    if suite is not None and suite not in RUN_SUITES:
        raise UsageError(
            f"--suite {suite} is not measured in this build; ow eval run measures "
            f"{', '.join(RUN_SUITES)}",
            fix=_RUN_FIX,
        )
    suites = RUN_SUITES if suite is None else (suite,)
    if parsed.deterministic_half and suites != ("absence",):
        raise UsageError(
            "--deterministic-half names the half of the absence suite this build runs, and is "
            "given only with --suite absence",
            fix="ow eval run --suite absence --deterministic-half",
        )
    product = [one for one in suites if one != "parse"]
    if parsed.subject is not None and product:
        raise UsageError(
            f"--subject names a parse driver, and the {product[0]} suite's subjects are its own",
            fix="ow eval run --suite parse --subject <driver id>",
        )
    for flag, value, allowed in (
        ("--witness", parsed.witness, WITNESSES),
        ("--cassette", parsed.cassette, CASSETTES),
    ):
        if value not in allowed:
            raise UsageError(f"{flag} {value!r} is not one of {', '.join(allowed)}", fix=_RUN_FIX)
    gates = cwd / parsed.gates
    if not gates.is_file():
        raise NotFoundError(
            f"no metric register at {gates}",
            fix="pass --gates PATH naming the eval/gates.toml register",
        )
    oweval = cwd / parsed.oweval
    from omniweave.surface.admit import admit  # noqa: PLC0415 -- only `run` pays

    done = _ran(
        eval_entry("run")(
            oweval=str(oweval),
            gates=str(gates),
            root=str(cwd),
            suites=list(suites),
            subject=parsed.subject,
            witness=parsed.witness,
            cassette=parsed.cassette,
            admit=admit,
        )
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_run_row(done), ensure_ascii=False) + "\n")
        return 0
    for row in done.runs:
        stdout.write(_run_line(row) + "\n")
    stdout.write(
        f"ow eval run --suite {','.join(done.suites)}: {len(done.runs)} run(s) written to "
        f"{parsed.oweval}\n"
    )
    return 0


def _run_line(row: EvalRunRow) -> str:
    """One subject's line: its rate, then what it read, in the suite's own terms."""
    rate = "vacuous" if row.value is None else f"{row.value:.4f} over {row.n}"
    if row.suite == "absence":
        tail = f"{row.parsed} of {row.n} pair(s) passed" + (
            f"; failed: {', '.join(row.refused)}" if row.refused else ""
        )
    elif row.suite == "roundtrip":
        tail = f"{row.parsed} of {row.n} element(s) survive" + (
            f"; failed: {', '.join(row.refused)}" if row.refused else ""
        )
    elif row.suite == "retrieve":
        cites = row.parsed + len(row.refused)
        rate = f"{int(row.value or 0)} over {row.n} answer(s)"
        tail = f"{row.parsed} of {cites} cite(s) resolve" + (
            f"; unresolved: {', '.join(row.refused)}" if row.refused else ""
        )
    else:
        tail = f"{row.parsed} parsed, {len(row.refused)} refused"
    return f"  {row.subject:<24} {row.slice:<20} {row.metric} {rate}; {tail}"


def _ran(result: Mapping[str, object]) -> EvalRunReport:
    """The entry point's builtins as this side's report. Anything else is a broken install."""
    suites, oweval, runs = (result.get(k) for k in ("suites", "oweval", "runs"))
    if not (
        isinstance(suites, list)
        and all(isinstance(one, str) for one in suites)
        and isinstance(oweval, str)
        and isinstance(runs, list)
        and all(_run_shape(row) for row in runs)
    ):
        raise InternalError(
            "the [omniweave.eval] run entry point returned no suites, oweval and runs",
            fix="pip install --force-reinstall omniweave-conform",
        )
    return EvalRunReport(
        suites=tuple(suites),
        oweval=oweval,
        runs=tuple(
            EvalRunRow(
                run_id=row["run_id"],
                suite=row["suite"],
                subject=row["subject"],
                slice=row["slice"],
                corpus=row["corpus"],
                metric=row["metric"],
                value=row["value"],
                n=row["n"],
                parsed=row["parsed"],
                refused=tuple(row["refused"]),
            )
            for row in runs
        ),
    )


def _run_shape(row: object) -> bool:
    return (
        isinstance(row, dict)
        and all(
            isinstance(row.get(k), str)
            for k in ("run_id", "suite", "subject", "slice", "corpus", "metric")
        )
        and (row.get("value") is None or isinstance(row.get("value"), float))
        and all(isinstance(row.get(k), int) for k in ("n", "parsed"))
        and isinstance(row.get("refused"), list)
        and all(isinstance(x, str) for x in row["refused"])
    )


def _run_row(done: EvalRunReport) -> dict[str, object]:
    return {
        "suites": list(done.suites),
        "oweval": done.oweval,
        "runs": [
            {
                "run_id": row.run_id,
                "suite": row.suite,
                "subject": row.subject,
                "slice": row.slice,
                "corpus": row.corpus,
                "metric": row.metric,
                "value": row.value,
                "n": row.n,
                "parsed": row.parsed,
                "refused": list(row.refused),
            }
            for row in done.runs
        ],
    }


_VERBS: Final[Mapping[str, Callable[..., int]]] = {
    "eval.run": _run,
    "eval.publish": _publish,
    "eval.release_check": _release_check,
    "eval.bless": _bless,
}
