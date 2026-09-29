"""18:887's eight global flags on every root the generated tree parses: served, or refused by name.

18:887 accepts the eight *"before or after the verb, on every command"*, and the generated tree
does: every node carries them (W7.8q). Until W7.8x each root read the ones it had a use for and
parsed the rest into nothing, so `ow doctor --config other.toml` checked the configuration the
upward walk found, and `ow query --json-errors` printed prose. D615 item 8 recorded the four
switches; the audit behind this module found the other four ignored on seven roots as well (D631).

**Every (root, flag) pair is in exactly one of three places:**
- `READS`: the root's own code reads the value, and serves it or refuses a value in its own words.
  `ow query --render jsonl` is refused by `ow query`, which says why.
- `INERT`: nothing the root can print depends on the value, so honouring it and ignoring it are
  the same run. Each entry below says why.
- neither: `check()` refuses it by name, exit 1, before the root reads anything. A flag parsed and
  ignored answers a different question than the one asked (`ow query`'s rule, D614).

A flag left at its default is never refused, so a root pays for this only when a flag was given.

**`--json-errors` is 18:898's object**, `code`, `numeric`, `message`, `fix` and `exit`, one line on
stderr. `code` is `OwError.code()`, the symbol, which is the stored and wire form (charter section
5 C9), and `numeric` is `OW-A-002`. `--render json`'s error object uses the same two keys: D631
found 10:1539 spelling the numeric `code`, and ADR-13 D13.5 ruled for C9.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.errors import OwError, UsageError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping

__all__ = [
    "DEFAULTS",
    "INERT",
    "READS",
    "SPELLING",
    "check",
    "error_object",
    "json_error",
    "prose",
    "report",
    "unserved",
]

DEFAULTS: Final[Mapping[str, object]] = {
    "config": None,
    "corpus": None,
    "render": "text",
    "quiet": False,
    "verbose": 0,
    "no_color": False,
    "offline": False,
    "json_errors": False,
}
"""The eight, by namespace key, in 18:889's order, with the value the tree parses when none is
given. `test_switches.py` asserts these are `cli.GLOBAL_FLAGS`' own."""

SPELLING: Final[Mapping[str, str]] = {name: "--" + "-".join(name.split("_")) for name in DEFAULTS}
"""Each flag as typed. `split` and `join`, not `str.replace`, which this package's no-write scan
cannot tell from `Path.replace` (`test_this_package_can_write_no_file_at_all`)."""

_ROOTS: Final[tuple[str, ...]] = (
    "add",
    "corpora",
    "doc",
    "doctor",
    "explain",
    "hooks",
    "install",
    "open",
    "query",
    "serve",
    "skills",
    "surface",
    "uninstall",
)

_NO_ANSI: Final[str] = "no root writes an ANSI sequence, so there is no colour to turn off"
_NO_FETCH: Final[str] = "no root but `add` routes a unit or fetches anything"
_READS_ALL: Final[frozenset[str]] = frozenset({"json_errors"})
"""Every root writes its refusals through `report()`, which reads `--json-errors`."""

_READER: Final[frozenset[str]] = frozenset({"config", "corpus", "render", "quiet", "json_errors"})
"""What the six read-and-print verbs read: they resolve a corpus from a configuration, and each
refuses the `--render` modes and the `--quiet` it has no writer for, naming them."""

READS: Final[Mapping[str, frozenset[str]]] = {
    "query": _READER,
    "add": _READER | {"offline"},
    "open": _READER,
    "corpora": _READER,
    "doc": _READER,
    "explain": _READS_ALL | {"render", "quiet"},
    "doctor": _READS_ALL | {"config", "quiet"},
    "serve": _READS_ALL | {"config"},
    "install": _READS_ALL,
    "uninstall": _READS_ALL,
    "hooks": _READS_ALL,
    "skills": _READS_ALL,
    "surface": _READS_ALL,
}
"""The flags each root reads. `add` carries `--offline` into routing's `ProbeEnv`, so a card with
`[hardware] needs_network = true` resolves out (04:150). `doctor` loads `--config` and prints
nothing under `--quiet` (10:1543). `serve` loads `--config`."""

INERT: Final[Mapping[str, Mapping[str, str]]] = {
    root: {
        "no_color": _NO_ANSI,
        **({} if root == "add" else {"offline": _NO_FETCH}),
        **(
            {
                "config": f"`ow {root}` reads no configuration",
                "corpus": f"`ow {root}` resolves no corpus",
            }
            if root in ("explain", "surface")
            else {}
        ),
    }
    for root in _ROOTS
}
"""The flags each root accepts because nothing it prints can depend on them, with the reason.

- `--no-color`: 10:1529 allows ANSI only on a TTY, and nothing in this build writes any
  (`test_switches.py` scans every distribution a root imports).
- `--offline`: 18:897 *"refuses every fetch, a toolchain install included"*. No root but `add`
  routes, and nothing fetches: `ow add` refuses a URL, no toolchain installer exists, and the
  server does step (a) of `ow_add` only (D554).
- `--config` and `--corpus` on `explain` (`codes.toml`, found from the package) and `surface`
  (`ACTIONS`)."""


def unserved(root: str, parsed: argparse.Namespace) -> tuple[str, ...]:
    """Each global flag given away from its default that `root` neither reads nor is inert to.

    Spelled as a user reads it: `--render json`, not `render`. A value is not repeated, because a
    `--corpus` or `--config` value is the user's text and a refusal is printed to a cp1252 pipe.
    """
    served = READS[root] | frozenset(INERT[root])
    named: list[str] = []
    for name, default in DEFAULTS.items():
        if name in served or getattr(parsed, name, default) == default:
            continue
        spelled = SPELLING[name]
        named.append(f"{spelled} {parsed.render}" if name == "render" else spelled)
    return tuple(named)


def check(root: str, parsed: argparse.Namespace) -> None:
    """Refuse every global flag `root` does not serve, by name, as one `UsageError` (exit 1)."""
    named = unserved(root, parsed)
    if not named:
        return
    raise UsageError(
        f"{', '.join(named)} is parsed and not served by ow {root} in this build; running without "
        "it would answer a different question than the one asked",
        fix=f"omit {'it' if len(named) == 1 else 'them'}",
    )


def error_object(error: OwError) -> dict[str, Any]:
    """10:1539-1540's error object: `{"schema":1,"error":{code, numeric, message, fix}}`.

    `code` is the SYMBOL, as charter section 5 C9 fixes it on the wire, and `numeric` is the
    human form: the same two keys as 18:898's `--json-errors` object. 10:1539's printed example put
    the numeric under `code` and the symbol under `symbol`, which C9 forbids (ADR-13 D13.5).
    """
    return {
        "schema": 1,
        "error": {
            "code": error.code(),
            "numeric": error.numeric(),
            "message": str(error),
            "fix": error.fix,
        },
    }


def json_error(error: OwError) -> dict[str, Any]:
    """18:898's `--json-errors` object: `code`, `numeric`, `message`, `fix`, `exit`."""
    return {
        "code": error.code(),
        "numeric": error.numeric(),
        "message": str(error),
        "fix": error.fix,
        "exit": type(error).EXIT,
    }


def prose(error: OwError) -> str:
    """The read-and-print verbs' two lines: the code, the message, and the fix."""
    return f"ow: {error.numeric() or error.code()}: {error}\n  fix: {error.fix}\n"


def report(
    error: OwError,
    parsed: argparse.Namespace,
    *,
    stdout: TextIO | None,
    stderr: TextIO,
    line: Callable[[OwError], str] = prose,
) -> int:
    """Print `error` as the flags given ask, and return its exit.

    - `--render json`: 10:1539's object on stdout, since a `--render json` stdout that does not
      `json.loads` is a bug on the error paths too. `stdout=None` is `ow serve`'s, whose stdout
      is the protocol channel and is never written from here.
    - `--json-errors`: 18:898's object on stderr, in place of the prose. ASCII, because a piped
      child's stderr on Windows is cp1252 (D431).
    - otherwise `line(error)` on stderr, unless `--render json` already carried it.
    """
    as_json = getattr(parsed, "render", "text") == "json" and stdout is not None
    if as_json and stdout is not None:
        stdout.write(json.dumps(error_object(error), ensure_ascii=False) + "\n")
    if getattr(parsed, "json_errors", False):
        stderr.write(json.dumps(json_error(error)) + "\n")
    elif not as_json:
        stderr.write(line(error))
    return type(error).EXIT
