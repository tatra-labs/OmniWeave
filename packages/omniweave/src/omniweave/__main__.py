"""`python -m omniweave`: dispatches `hook` and nothing else, and says so for everything else.

This file did not exist before W7.4i, and its absence was a defect in a cell that claimed otherwise.
`posttool.command()` falls back to `python -m omniweave ingest` and its docstring called that
fallback one that *"always works"* -- but `python -m omniweave` exited 1 at import with *"No module
named omniweave.__main__"*, into the `DEVNULL` 10:2072 requires. D433.

**It dispatches one root.** `ow hook <event>` is W7.4's (16:718) and is the only verb whose runtime
exists; the other roots in `cli.COMMANDS` are parsed by a generated tree whose own docstring says it
*"parses and does not dispatch"*, because 02:719's steps 2-9 belong to a runtime not yet built. So
every other argv is refused, on stderr, with `InternalError`'s exit -- 10:2185's *"anything else"*,
the only row in the taxonomy that does not assert something about a store or an argument that would
be false here. The refusal is spelled out rather than silent, because the one thing worse than a
command that does not work is one that exits 0 having done nothing.

**No console script is declared, and 18:874 says there is one.** *"`ow` and `omniweave` are the same
console script"* -- and no `pyproject.toml` in the workspace has a `[project.scripts]` table. A
console script that dispatched only `hook` would put an `ow` on every user's PATH that refuses every
command in `ow --help`, so it waits for the dispatcher rather than arriving here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave.hooks.main import HOOK_WORD, entry

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["DISPATCHED", "main"]

DISPATCHED: Final[frozenset[str]] = frozenset({HOOK_WORD})
"""The roots this build can run. `ingest` joining it is the day the drain can be wired (D433)."""


def main(argv: Sequence[str] | None = None) -> int:
    """Route `hook` to the hook entry point; refuse everything else with `InternalError.EXIT`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == HOOK_WORD:
        #  The one read of the working directory in this distribution, which the cwd ban exempts
        #  this file for (D435): a hook's `<sessions>/` is found by walking up from it (10:1893).
        return entry(args[1:], cwd=Path.cwd())

    from omniweave_core.errors import InternalError  # noqa: PLC0415 -- only the refusal pays

    #  `ascii()`, because stderr is cp1252 in a piped child on Windows (D431) and `root` is argv.
    root = ascii(args[0]) if args else "nothing"
    sys.stderr.write(f"ow: {root} is not dispatched by this build; only `ow hook <event>` is.\n")
    return InternalError.EXIT


if __name__ == "__main__":
    raise SystemExit(main())
