"""`python -m omniweave`: dispatches `hook`, `install`, `uninstall`, `hooks`, `skills`, `serve`.

This file did not exist before W7.4i, and its absence was a defect in a cell that claimed otherwise.
`posttool.command()` falls back to `python -m omniweave ingest` and its docstring called that
fallback one that *"always works"* -- but `python -m omniweave` exited 1 at import with *"No module
named omniweave.__main__"*, into the `DEVNULL` 10:2072 requires. D433.

**It dispatches the roots whose runtime exists.** `ow hook <event>` is W7.4's (16:718); `ow install`
and `ow uninstall` are W7.5's (16:719), and `ow hooks check` runs W7.4j's engine over what they
installed; all three are parsed by the generated tree now that their `ACTIONS` rows exist (W7.5h,
W7.5i, D467) and run by `omniweave.install.run`, as `ow skills install | remove` are since
W7.6b -- the verb the router skill's section 4 tells an agent to run. `ow serve --mcp` is
W7.3p's: startup step 5 here, then the server through the `omniweave.serve` entry point
(`omniweave.surface.serve`), which is the command 10:1675's MCP entry runs (D460). The other
roots in `cli.COMMANDS` are refused, on stderr, with `InternalError`'s exit -- 10:2185's *"anything
else"*, the only row in the taxonomy that does not assert something about a store or an argument
that would be false here. The refusal is spelled out rather than silent, because the one thing
worse than a command that does not work is one that exits 0 having done nothing.

**`hook` is routed first and imports nothing else.** A hook runs on every prompt and has a deadline
(G26); the install verbs import the generated parser, the registry and the engine, and are imported
only when their root is asked for.

**No console script is declared, and 18:874 says there is one.** *"`ow` and `omniweave` are the same
console script"* -- and no `pyproject.toml` in the workspace has a `[project.scripts]` table. A
console script would put an `ow` on every user's PATH that refuses most of `ow --help`, so it waits
for the dispatcher rather than arriving here.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave.hooks.main import HOOK_WORD, entry

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["DISPATCHED", "main"]

_INSTALL_ROOTS: Final[frozenset[str]] = frozenset({"install", "uninstall", "hooks", "skills"})

_SERVE_ROOT: Final[str] = "serve"

DISPATCHED: Final[frozenset[str]] = frozenset({HOOK_WORD, *_INSTALL_ROOTS, _SERVE_ROOT})
"""The roots this build can run. `ingest` joining it is the day the drain can be wired (D433)."""


def main(argv: Sequence[str] | None = None) -> int:
    """Route each dispatched root to its entry point; refuse everything else with exit 70."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == HOOK_WORD:
        #  A read of the working directory, which the cwd ban exempts this file for (D435): a
        #  hook's `<sessions>/` is found by walking up from it (10:1893).
        return entry(args[1:], cwd=Path.cwd())
    if args and args[0] in _INSTALL_ROOTS:
        return _install(args)
    if args and args[0] == _SERVE_ROOT:
        return _serve(args)

    from omniweave_core.errors import InternalError  # noqa: PLC0415 -- only the refusal pays

    #  `ascii()`, because stderr is cp1252 in a piped child on Windows (D431) and `root` is argv.
    root = ascii(args[0]) if args else "nothing"
    known = ", ".join(f"`ow {one}`" for one in sorted(DISPATCHED))
    sys.stderr.write(f"ow: {root} is not dispatched by this build; only {known} are.\n")
    return InternalError.EXIT


def _install(args: list[str]) -> int:
    from omniweave.install.run import main as run  # noqa: PLC0415 -- the hook path never pays

    #  Measured: into a pipe on Windows, Python writes cp1252 and the transcript's `·` and `…`
    #  reach a UTF-8 reader as U+FFFD. A terminal is left alone -- the console writes Unicode.
    if not sys.stdout.isatty() and isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    #  The second read of the working directory, under the same exemption (D435): a `local`
    #  install writes under the project it is run from (10:1734).
    return run(args, env=os.environ, cwd=Path.cwd())


def _serve(args: list[str]) -> int:
    from omniweave.surface.serve import main as run  # noqa: PLC0415 -- the hook path never pays

    #  Nothing here touches stdout: from the moment the server binds it, it is the protocol
    #  channel, and the refusals before that go to stderr. The third read of the working
    #  directory under D435's exemption: `./omniweave.toml` is found by walking up from it.
    return run(args, env=os.environ, cwd=Path.cwd(), stderr=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
