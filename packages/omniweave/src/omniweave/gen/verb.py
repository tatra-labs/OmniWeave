"""`ow surface emit [--check | --bless]`: the generated artefacts, written or gated. G25.

`gen.emit` has held both halves since W7.2 -- `emit()` writes every `LIVE` artefact and `check()`
returns G25's findings -- and `test_gen_emit.py` has been what actually ran G25. What was missing
was the verb: six generated headers told their reader to run `ow surface emit`, `tools/gates.toml`
names it as G25's step, and no `ActionSpec` declared it, so the generated tree parsed it as nothing
(D334). This module is the runner the `surface.emit` row dispatches to, and nothing more.

It is in `gen/` and not beside the other verb runners in `surface/`, by 02:254's forbidden
column: `surface/` declares and `gen/` emits, and `surface/` is imported by every CLI and server
entry point, so nothing there may be able to write (`test_this_package_can_write_no_file_at_all`).

Exit 0 or 1, 10:1430's two: 0 when `--check` finds nothing or the write completed, 1 when
`--check` finds drift. A usage error is argparse's, through the generated tree, like every other
root. Everything printed is a repo-relative path or a finding, ASCII, for `__main__`'s reason.
"""

from __future__ import annotations

import argparse
import contextlib
from typing import TYPE_CHECKING, Final, TextIO

from omniweave.sdk.reports import SurfaceReport

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["DRIFT", "OK", "main", "run"]

OK: Final[int] = 0
DRIFT: Final[int] = 1
"""10:1430's `0/1`: the gate passed or the write completed; the gate found drift."""

_ARGPARSE_USAGE: Final[int] = 2


def run(*, check: bool, bless: bool) -> SurfaceReport:
    """The Action: `check()` and report, or `emit()` and report what changed. Flags, not argv."""
    from omniweave.gen import emit  # noqa: PLC0415 -- every generator; only this verb pays

    if check and bless:
        return SurfaceReport(
            exit_code=_ARGPARSE_USAGE,
            lines=("ow: surface emit takes --check or --bless, not both: a check never writes",),
        )
    if check:
        findings = emit.check()
        if not findings:
            return SurfaceReport(
                OK, ("surface emit --check: every generated artefact matches ACTIONS",)
            )
        return SurfaceReport(
            DRIFT,
            (*findings, f"surface emit --check: {len(findings)} finding(s); run ow surface emit"),
        )
    changed = emit.emit()
    written = tuple(f"wrote {path}" for path in changed)
    return SurfaceReport(OK, (*written, f"surface emit: {len(changed)} artefact(s) changed"))


def main(argv: Sequence[str], *, stdout: TextIO, stderr: TextIO) -> int:
    """`ow surface emit ...` from argv (starting at the root word), through the generated tree."""
    from omniweave.cli import build_parser  # noqa: PLC0415 -- only a CLI verb pays for the tree

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            parsed: argparse.Namespace = build_parser().parse_args(list(argv))
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else _ARGPARSE_USAGE
    report = run(
        check=bool(getattr(parsed, "check", False)), bless=bool(getattr(parsed, "bless", False))
    )
    stream = stderr if report.exit_code == _ARGPARSE_USAGE else stdout
    for line in report.lines:
        stream.write(line.encode("ascii", "backslashreplace").decode("ascii") + "\n")
    return report.exit_code
