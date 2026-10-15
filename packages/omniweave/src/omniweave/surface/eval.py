"""`ow eval <verb>`: the eval verbs this build dispatches. D833: `publish`; D840: `release-check`.

10-interfaces.md section 2.5: *"`omniweave-conform` implements the `eval` Action group"*. Every
`eval` row stays in `ACTIONS` here, and the work happens across an entry point,
`omniweave.surface.dispatch.eval_entry()`. This module parses, resolves paths against the
working directory, calls the verb with builtin values, and prints.

13-quality.md section 11.1: *"`ow eval publish` exports the `eval_scoreboard` view into the
committed JSON tree"*, which Q-G19 byte-diff gates. Section 13.3 prints the verb.

13-quality.md:1881: *"`ow eval release-check` # exit 0 iff zero `unknown`, zero hard-gate
failures"*. `omniweave_conform.release` holds what a finding is; this module prints them.

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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.errors import InternalError, NotFoundError, OwError, QualityError, UsageError

from omniweave.sdk.reports import EvalPublishReport, EvalReleaseCheckReport, EvalReleaseFinding
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
_STALE: Final[int] = 1
_REFUSED: Final[int] = 1


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow eval ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    del env  # Nothing an `ow eval` verb does depends on the environment.
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(EVAL_WORD, parsed)
        return _VERBS[parsed.ow_action](parsed, cwd=cwd, stdout=stdout)
    except QualityError as error:
        report(error, parsed, stdout=stdout, stderr=stderr)
        return _REFUSED
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _publish(parsed: argparse.Namespace, *, cwd: Path, stdout: TextIO) -> int:
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


def _release_check(parsed: argparse.Namespace, *, cwd: Path, stdout: TextIO) -> int:
    """Ruling 6."""
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


_VERBS: Final[Mapping[str, Callable[..., int]]] = {
    "eval.publish": _publish,
    "eval.release_check": _release_check,
}
