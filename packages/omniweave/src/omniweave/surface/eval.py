"""`ow eval <verb>`: the eval verbs this build dispatches. D833: `publish`.

10-interfaces.md section 2.5: *"`omniweave-conform` implements the `eval` Action group"*. Every
`eval` row stays in `ACTIONS` here, and the work happens across an entry point,
`omniweave.surface.dispatch.eval_entry()`. This module parses, resolves paths against the
working directory, calls the verb with builtin values, and prints.

13-quality.md section 11.1: *"`ow eval publish` exports the `eval_scoreboard` view into the
committed JSON tree"*, which Q-G19 byte-diff gates. Section 13.3 prints the verb.

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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.errors import InternalError, NotFoundError, OwError, QualityError, UsageError

from omniweave.sdk.reports import EvalPublishReport
from omniweave.surface.dispatch import eval_entry
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

__all__ = ["EVAL_WORD", "main"]

EVAL_WORD: Final[str] = "eval"
_PUBLISH_FIX: Final[str] = "ow eval publish [--oweval PATH] [--results DIR] [--check]"
_STALE: Final[int] = 1
_REFUSED: Final[int] = 1


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow eval ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    del env  # Nothing `ow eval publish` does depends on the environment.
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(EVAL_WORD, parsed)
        return _publish(parsed, cwd=cwd, stdout=stdout)
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
    oweval = cwd / parsed.oweval
    if not oweval.is_file():
        raise NotFoundError(
            f"no .oweval at {oweval}",
            fix="run the eval suites to write one, or pass --oweval PATH",
        )
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
