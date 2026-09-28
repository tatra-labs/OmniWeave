"""`ow explain <CODE>`: what an `OW-*` code or an exit status means. 10:1438; 18:1197-1208.

`omniweave_core.errors.explain()` has resolved either spelling of a register row -- `OW-A-013` or
`OW_PARSE_GAP_IN_SCOPE` -- since W1.3, and raises `OW-A-026` naming the nearest three by edit
distance. The CLI verb was refused as a root *"not dispatched by this build"*. This module prints
that row. It reads no corpus and no configuration, so it answers on a machine with no store at all
(`ExplainIn`'s docstring), including while a store is locked.

**An exit status resolves too.** 10:1520-1523 puts the exit table in `codes.toml` *"so `ow explain`
can print it"*, and 10:2769 closes on *"`ow explain 8` resolves"*. So a bare integer is looked up
in the register's `[[exit]]` rows.

**What is printed**, as 18:1197-1203 prints it: the numeric and the symbol, the meaning, `fix:`
and `see:`. 18's `exit:` line is not printed: no register row carries the exit a code produces,
and the row's `raised_by` class is not on `CodeRow` (D618). A row whose `meaning` or `fix` the
register leaves empty says so rather than printing a blank.

**What is refused by name**, each exit 1:
- `--quiet`: 10:1542-1545 has each Action declare its one scalar, and `explain` declares none;
- `--render jsonl` and `--render rows`, which have no writer.
- `--verbose`, and any other global flag `switches.READS` does not give this verb (D631).
  `--json-errors` is served: 18:898's object on stderr, through `switches.report()`.

Exits are 10:1438's `0/2`, plus 1 for usage. 2 is a code or a status the register does not hold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.errors import NotFoundError, OwError, UsageError

from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

__all__ = ["EXPLAIN_WORD", "main"]

EXPLAIN_WORD: Final[str] = "explain"

_SCHEMA: Final[int] = 1
_ABSENT: Final[str] = "(not recorded in codes.toml)"


def main(argv: Sequence[str], *, stdout: TextIO, stderr: TextIO) -> int:
    """`ow explain ...` from argv (starting at the root word). The exit is 10:1438's."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(EXPLAIN_WORD, parsed)
        return _explain(parsed, stdout=stdout)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _explain(parsed: argparse.Namespace, *, stdout: TextIO) -> int:
    _refuse_unserved(parsed)
    wanted = str(parsed.code).strip()
    document = _status(int(wanted)) if wanted.isdigit() else _code(wanted)
    if parsed.render == "json":
        stdout.write(json.dumps({"schema": _SCHEMA, **document}, ensure_ascii=False) + "\n")
    else:
        for line in _text(document):
            stdout.write(line + "\n")
    return 0


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow explain",
            fix="ow explain <CODE> [--render json]",
        )


def _code(wanted: str) -> dict[str, Any]:
    """One `[[code]]` row, by either spelling: `CodeRow`'s five fields (18:751)."""
    from omniweave_core.errors import explain  # noqa: PLC0415

    row = explain(wanted)
    return {
        "numeric": row.numeric,
        "symbol": row.symbol,
        "meaning": row.meaning,
        "fix": row.fix,
        "owner_doc": row.owner_doc,
    }


def _status(code: int) -> dict[str, Any]:
    """One `[[exit]]` row: the status, its slug, its meaning, and the classes that exit with it."""
    from omniweave_core.errors import load_register  # noqa: PLC0415

    register = load_register()
    for row in register.exits:
        if row.code == code:
            return {
                "exit": row.code,
                "slug": row.slug,
                "meaning": row.meaning,
                "classes": list(row.classes),
                "note": row.note,
            }
    known = " ".join(str(row.code) for row in register.exits)
    raise NotFoundError(
        f"exit status {code} is not in codes.toml's exit table; it holds {known}",
        symbol="OW_UNKNOWN_CODE",
        fix="ow explain <status>   # one of the statuses above",
    )


def _text(document: dict[str, Any]) -> list[str]:
    """18:1197-1203's block: the two spellings, then the meaning, the fix and the owning doc."""
    if "exit" in document:
        classes = ", ".join(document["classes"])
        lines = [f"exit {document['exit']}  {document['slug']}", f"  {document['meaning']}"]
        if classes:
            lines.append(f"  raised by: {classes}")
        if document["note"]:
            lines.append(f"  note: {document['note']}")
        return lines
    return [
        f"{document['numeric']}  {document['symbol']}",
        f"  {document['meaning'] or _ABSENT}",
        f"  fix: {document['fix'] or _ABSENT}",
        f"  see: {document['owner_doc'] or _ABSENT}",
    ]
