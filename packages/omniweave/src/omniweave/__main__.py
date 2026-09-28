"""`ow` and `python -m omniweave`: the roots this build can run, `--version` and `--help`.

This file did not exist before W7.4i, and its absence was a defect in a cell that claimed otherwise.
`posttool.command()` falls back to `python -m omniweave ingest` and its docstring called that
fallback one that *"always works"* -- but `python -m omniweave` exited 1 at import with *"No module
named omniweave.__main__"*, into the `DEVNULL` 10:2072 requires. D433.

**It dispatches the roots whose runtime exists.** `ow hook <event>` is W7.4's (16:718); `ow install`
and `ow uninstall` are W7.5's (16:719), and `ow hooks check` runs W7.4j's engine over what they
installed; all three are parsed by the generated tree now that their `ACTIONS` rows exist (W7.5h,
W7.5i, D467) and run by `omniweave.install.run`, as `ow skills install | remove` are since W7.6b --
the verb the router skill's section 4 tells an agent to run. `ow serve --mcp` is W7.3p's: startup
step 5 here, then the server through the `omniweave.serve` entry point (`omniweave.surface.serve`),
which is the command 10:1675's MCP entry runs (D460). `ow ingest` is W7.3w's: the drain, run as far
as this build can take it (hops 1-4 of 02 section 4.1), parsed by its own module as `hook` is,
because 18:928 hides it as 18:923 hides `hook` (D565). `ow surface emit` is W7.1e's: G25's step,
and the command every generated header names (D334). `ow doctor` is W7.8c's: the checks this
build can run, and the list of those it cannot (D610). `ow query` is W7.8g's: the same core calls
`ow_query` makes, rendered to stdout (D614). `ow add` is W7.8h's: `ow_add`'s roster step, then
the drain `ow ingest` runs, in one process (D615). `ow open` is W7.8i's: the calls `ow_open`
makes, rendered to stdout (D616). `ow corpora` is W7.8j's: the documents `ow_corpora`
returns, built by core for both (D617). `ow explain` is W7.8k's: a register row or an exit
status, read from `codes.toml` and nothing else (D618). `ow doc` is W7.8n's: `grid` reads one
table's `Grid` back from the store, and `diff` is refused by name (D621). Every root in
`cli.COMMANDS` now dispatches. A word that is not a root is refused, on stderr, with
`InternalError`'s exit -- 10:2185's *"anything else"*, the only row in the taxonomy that does not
assert something about a store or an argument that would be false here. The
refusal is spelled out rather than silent, because the one thing worse than a command that does not
work is one that exits 0 having done nothing.

**`hook` is routed first and imports nothing else.** A hook runs on every prompt and has a deadline
(G26); the install verbs import the generated parser, the registry and the engine, and are imported
only when their root is asked for. The hook engine itself is imported only for `hook`, so `ow
--version` does not pay for it either (W7.8l).

**`ow` and `omniweave` are the console script 18:874 names** (W7.8l, D619). It waited for twelve of
the thirteen roots to dispatch, because an `ow` on every PATH that refused most of `ow --help`
would have been worse than none. The thirteenth, `ow doc`, dispatched in W7.8n.

**Three words before a root are handled here, and they are what V01-3 times:**
- `ow --version` prints `RELEASE`, `CONTRACT` and `SCHEMA` on one line (11:704), importing
  `omniweave_core.contract` and nothing else, against 11:680's 150 ms.
- `ow --help` (and `-h`) prints the generated tree's help, importing the tree and nothing else,
  against 250 ms.
- `ow` alone is a usage error, exit 1, naming `ow --help`: a command line with no command did
  nothing, and a script that ran it should not read 0.

Any other flag before the root is refused as usage, because the roots parse their own global
flags and this build does not re-order a command line (D619).
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["DISPATCHED", "HOOK_WORD", "main"]

HOOK_WORD: Final[str] = "hook"
"""`omniweave.hooks.main.HOOK_WORD`, restated so that importing this module does not import the
hook engine: `ow --version` would otherwise pay ~43 ms for a word. `test_hooks_main.py` asserts
the two are equal."""

_VERSION_WORDS: Final[frozenset[str]] = frozenset({"--version"})

_HELP_WORDS: Final[frozenset[str]] = frozenset({"--help", "-h"})

_INSTALL_ROOTS: Final[frozenset[str]] = frozenset({"install", "uninstall", "hooks", "skills"})

_SERVE_ROOT: Final[str] = "serve"

_INGEST_ROOT: Final[str] = "ingest"

_SURFACE_ROOT: Final[str] = "surface"

_DOCTOR_ROOT: Final[str] = "doctor"

_QUERY_ROOT: Final[str] = "query"

_ADD_ROOT: Final[str] = "add"

_OPEN_ROOT: Final[str] = "open"

_CORPORA_ROOT: Final[str] = "corpora"

_EXPLAIN_ROOT: Final[str] = "explain"

_DOC_ROOT: Final[str] = "doc"

DISPATCHED: Final[frozenset[str]] = frozenset(
    {
        HOOK_WORD,
        *_INSTALL_ROOTS,
        _SERVE_ROOT,
        _INGEST_ROOT,
        _SURFACE_ROOT,
        _DOCTOR_ROOT,
        _QUERY_ROOT,
        _ADD_ROOT,
        _OPEN_ROOT,
        _CORPORA_ROOT,
        _EXPLAIN_ROOT,
        _DOC_ROOT,
    }
)
"""The roots this build can run. `ingest` joined in W7.3w; nothing spawns it yet (D433, D554).
`surface` joined in W7.1e (D334), `doctor` in W7.8c (D610), `query` in W7.8g (D614), `add` in
W7.8h (D615), `open` in W7.8i (D616), `corpora` in W7.8j (D617), `explain` in W7.8k
(D618), and `doc` in W7.8n (D621)."""


def main(argv: Sequence[str] | None = None) -> int:  # noqa: PLR0911, PLR0912 -- one per root
    """Route each dispatched root to its entry point; refuse everything else with exit 70."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == HOOK_WORD:
        from omniweave.hooks.main import entry  # noqa: PLC0415 -- only the hook pays for it

        #  A read of the working directory, which the cwd ban exempts this file for (D435): a
        #  hook's `<sessions>/` is found by walking up from it (10:1893).
        return entry(args[1:], cwd=Path.cwd())
    if args and args[0] in _VERSION_WORDS:
        return _version()
    if not args or args[0].startswith("-"):
        return _tree(args)
    if args and args[0] in _INSTALL_ROOTS:
        return _install(args)
    if args and args[0] == _SERVE_ROOT:
        return _serve(args)
    if args and args[0] == _INGEST_ROOT:
        return _ingest(args[1:])
    if args and args[0] == _SURFACE_ROOT:
        return _surface(args)
    if args and args[0] == _DOCTOR_ROOT:
        return _doctor(args)
    if args and args[0] == _QUERY_ROOT:
        return _query(args)
    if args and args[0] == _ADD_ROOT:
        return _add(args)
    if args and args[0] == _OPEN_ROOT:
        return _open(args)
    if args and args[0] == _CORPORA_ROOT:
        return _corpora(args)
    if args and args[0] == _EXPLAIN_ROOT:
        return _explain(args)
    if args and args[0] == _DOC_ROOT:
        return _doc(args)

    from omniweave_core.errors import InternalError  # noqa: PLC0415 -- only the refusal pays

    #  `ascii()`, because stderr is cp1252 in a piped child on Windows (D431) and `root` is argv.
    root = ascii(args[0]) if args else "nothing"
    known = ", ".join(f"`ow {one}`" for one in sorted(DISPATCHED))
    sys.stderr.write(f"ow: {root} is not dispatched by this build; only {known} are.\n")
    return InternalError.EXIT


def _version() -> int:
    """11:704's one line: `RELEASE`, `CONTRACT`, and `SCHEMA` as `<major>.<minor>`."""
    from omniweave_core.contract import CONTRACT, RELEASE, SCHEMA_STRING  # noqa: PLC0415

    sys.stdout.write(f"omniweave {RELEASE}  contract {CONTRACT}  schema {SCHEMA_STRING}\n")
    return 0


def _tree(args: list[str]) -> int:
    """`ow --help`, `ow` alone, and a flag before the root: the generated tree answers the first.

    argparse's help exits 0 and its parse error exits 2, which is 10:1484's 1 here.
    """
    from omniweave.cli import build_parser  # noqa: PLC0415 -- `--version` never pays for it

    if args and args[0] in _HELP_WORDS:
        try:
            build_parser().parse_args(args)
        except SystemExit as stop:
            return stop.code if isinstance(stop.code, int) else 0
        return 0
    usage = build_parser().format_usage()
    if not args:
        sys.stderr.write(usage + "ow: no command given; `ow --help` lists them\n")
    else:
        #  `!a`, as the refusal below uses `ascii()`: a piped child's stderr is cp1252 (D431).
        sys.stderr.write(
            usage + f"ow: {args[0]!a} comes before the command, and this build reads a "
            "global flag only after it: ow <command> [flags]\n"
        )
    return 1


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


def _ingest(args: list[str]) -> int:
    from omniweave.surface.ingest import main as run  # noqa: PLC0415 -- the hook path never pays

    #  The fourth read of the working directory under D435's exemption: `./omniweave.toml` and
    #  every relative path argument resolve against it.
    return run(args, env=os.environ, cwd=Path.cwd(), stdout=sys.stdout, stderr=sys.stderr)


def _surface(args: list[str]) -> int:
    from omniweave.gen.verb import main as run  # noqa: PLC0415 -- the hook path never pays

    return run(args, stdout=sys.stdout, stderr=sys.stderr)


def _doctor(args: list[str]) -> int:
    from omniweave.doctor import main as run  # noqa: PLC0415 -- the hook path never pays

    #  The fifth read of the working directory under D435's exemption: D-02 asks about the git
    #  work tree the operator is standing in, and `./omniweave.toml` is found by walking up.
    return run(args, cwd=Path.cwd(), env=os.environ, stdout=sys.stdout, stderr=sys.stderr)


def _query(args: list[str]) -> int:
    from omniweave.surface.query import main as run  # noqa: PLC0415 -- the hook path never pays

    #  10:1553-1561: stdout and stderr are UTF-8 with `errors="replace"` on every platform, before
    #  anything is written: an Answer prints document text, which a cp1252 pipe cannot carry.
    _utf8()
    #  The sixth read of the working directory under D435's exemption: `./omniweave.toml`.
    return run(args, env=os.environ, cwd=Path.cwd(), stdout=sys.stdout, stderr=sys.stderr)


def _add(args: list[str]) -> int:
    from omniweave.surface.add import main as run  # noqa: PLC0415 -- the hook path never pays

    #  The same rule as `query`'s: the report prints each pending unit's path, which is the user's.
    _utf8()
    #  The seventh read of the working directory under D435's exemption: `./omniweave.toml` and
    #  every relative source resolve against it.
    return run(args, env=os.environ, cwd=Path.cwd(), stdout=sys.stdout, stderr=sys.stderr)


def _open(args: list[str]) -> int:
    from omniweave.surface.opening import main as run  # noqa: PLC0415 -- the hook path never pays

    #  An opened block is document text, `query`'s reason for the reconfigure.
    _utf8()
    #  The eighth read of the working directory under D435's exemption: `./omniweave.toml`.
    return run(args, env=os.environ, cwd=Path.cwd(), stdout=sys.stdout, stderr=sys.stderr)


def _corpora(args: list[str]) -> int:
    from omniweave.surface.corpora import main as run  # noqa: PLC0415 -- the hook path never pays

    #  A corpus's name, outline and abstract are the user's text, `query`'s reason.
    _utf8()
    #  The ninth read of the working directory under D435's exemption: `./omniweave.toml`.
    return run(args, env=os.environ, cwd=Path.cwd(), stdout=sys.stdout, stderr=sys.stderr)


def _explain(args: list[str]) -> int:
    from omniweave.surface.explain import main as run  # noqa: PLC0415 -- the hook path never pays

    #  A register row's meaning is not all ASCII (`OW-A-017`'s `add(schema=…)`). No read of the
    #  working directory: `codes.toml` is found from the package, not from where `ow` runs.
    _utf8()
    return run(args, stdout=sys.stdout, stderr=sys.stderr)


def _doc(args: list[str]) -> int:
    from omniweave.surface.doc import main as run  # noqa: PLC0415 -- the hook path never pays

    #  A cell's text is document text, `query`'s reason for the reconfigure.
    _utf8()
    #  The tenth read of the working directory under D435's exemption: `./omniweave.toml`.
    return run(args, env=os.environ, cwd=Path.cwd(), stdout=sys.stdout, stderr=sys.stderr)


def _utf8() -> None:
    """10:1553-1561's reconfigure, for the roots that print a document's text or a user's path."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
