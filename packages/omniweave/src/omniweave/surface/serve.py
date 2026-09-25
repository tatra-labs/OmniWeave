"""`ow serve --mcp`: parse, dispatch, config, step 5, hand over. The launcher D460 was waiting for.

02:712's startup sequence, run in order by the one process that can run all of it, up to the
point this distribution stops and `omniweave_serve` starts:

| step | here | decides |
|---|---|---|
| 1 dispatch | the generated parser, `dispatch.serve_entry()` | the verb; the server is installed |
| 2 config | `omniweave_core.config.load()` | the `Config`, `--config` included |
| 5 surface | `startup.servable(profile=--profile)` | SV1, the corpus, `compact` |
| -- | `entry(profile=, compact=, corpus_resolves=)` | serving, until the host closes stdin |

Steps 3, 4 and 6-9 are not here. 3 and 4 (limits, digests) have no runtime yet (D382's
measurement: *"steps 1 through 4 as a ladder"* are four mechanisms nothing runs in order), 6 and
7 open a store and a catalog the listed tools do not call yet (D511), 8 is a write lock `serve`
never takes, and 9 is the Supervisor loop `serve` may never run (02:264 row 40).

## WHY THE CAPABILITY IS CHECKED FIRST

10:286 makes an absent distribution a **dispatch** fact, and dispatch is step 1. So a machine
without `omniweave-serve` hears `pip install omniweave-serve` whatever its configuration says,
rather than a configuration error it would fix only to meet the install one next.

## WHAT IS REFUSED, AND WHY EACH IS NOT SILENT

- **Neither or both transports.** 10:1426 gives `--mcp` and `--http` and no default. Exit 1.
- **An `--http`-only flag under `--mcp`.** `--host`, `--port`, `--path`, `--api-key`,
  `--stateless` and `--session-timeout` configure a listener; beside `--mcp` they are ignored,
  and a flag that is accepted and ignored is how a user comes to believe a key protects a pipe.
  Exit 1.
- **`--http`.** `http.Listener` is an ASGI application and no ASGI server is a dependency of any
  distribution, so there is nothing to host it. Exit 70, `__main__`'s "not dispatched" exit.
- **A listed set the listing cannot send (D510).** When `[serve] listed` or
  `OMNIWEAVE_MCP_LISTED` resolves to a set other than the profile's, the server would send the
  profile's and say nothing -- 10:788's *"a server that quietly narrowed its own listing"*. Exit 1,
  naming the key that won.

Every refusal is one line on stderr: the symbol, the exit, the message and the command that clears
it, 10:294's *"on one line, with no traceback"*. Stdout is not touched before the server takes it:
the MCP stdio transport reserves it for protocol messages.
"""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import InternalError, OwError, UsageError

from omniweave.surface.dispatch import serve_entry
from omniweave.surface.registry import ACTIONS, PROFILES, listed
from omniweave.surface.startup import servable

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.config import Config

    from omniweave.surface.authority import Resolution
    from omniweave.surface.dispatch import Entry

__all__ = ["HTTP_ONLY", "main", "stores"]

HTTP_ONLY: Final[tuple[str, ...]] = (
    "host",
    "port",
    "path",
    "api_key",
    "stateless",
    "session_timeout",
)
"""10:1426's flags that configure a listener, in its order. None means anything to a pipe."""

_USAGE: Final[int] = UsageError.EXIT
_ARGPARSE_USAGE: Final[int] = 2


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stderr: TextIO,
    entries: Iterable[Entry] | None = None,
) -> int:
    """Run `ow serve` from argv (starting at `serve`). The exit is the server's, when it ran."""
    try:
        return _serve(argv, env=env, cwd=cwd, stderr=stderr, entries=entries)
    except OwError as error:
        stderr.write(_line(error))
        return type(error).EXIT


def _serve(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stderr: TextIO,
    entries: Iterable[Entry] | None,
) -> int:
    parsed = _parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    _transport(parsed)
    profile = parsed.profile
    if profile is not None and profile not in PROFILES:
        raise UsageError(
            f"--profile must be one of {', '.join(PROFILES)}; got {profile!r}",
            fix=f"ow serve --mcp --profile {PROFILES[0]}",
        )
    entry = serve_entry(entries)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    decided = servable(config, env=env, profile=profile)
    _unexpressible(decided.resolution)
    return entry(
        profile=decided.resolution.profile,
        compact=decided.compact,
        corpus_resolves=decided.resolves,
        corpus=decided.corpus,
        corpora=stores(config, decided.corpora, cwd=cwd),
        sources=stores(config, decided.corpora, cwd=cwd, field="source"),
        sessions=_sessions(cwd),
    )


def _sessions(cwd: Path) -> str | None:
    """`<sessions>`, where the hooks write the compaction marker the server's ledger reads.

    `hooks.session.sessions_dir(cwd)` and not a path beside `--config`: the marker's writer is the
    `PreCompact` hook, which resolves from the host's `cwd` and is never told about `--config`, and
    a reader that resolved a different directory from its writer would never see a marker. That
    is 10:1877's out-of-process split, and 10:1893 puts both halves beside *the resolved*
    `omniweave.toml` for this reason.
    """
    from omniweave.hooks.session import sessions_dir  # noqa: PLC0415 -- the serve path only

    found = sessions_dir(cwd)
    return None if found is None else str(found)


def stores(
    config: Config, names: Iterable[str], *, cwd: Path, field: str = "path"
) -> dict[str, str]:
    """Each declared corpus's `.owstore` -- or, with `field="source"`, its source root -- absolute.

    D527's rule for both, because both are `path` keys and neither is relative to anything the plan
    names. `corpora.*.source` inherits `[roots] source` (18's config table), and an inherited or
    built-in value resolves against `cwd`.

    `corpora.*.path` is a `path` key, and `config._as_path` normalises its separator and nothing
    else: no document says what a relative one is relative to. It is resolved against the
    directory of the file that declared it -- a project's `omniweave.toml` naming
    `.omniweave/index.owstore` means the one beside it, wherever `ow serve` was started -- and
    against `cwd` when the value came from the environment or a built-in.
    """
    out: dict[str, str] = {}
    for name in names:
        key = f"corpora.{name}.{field}"
        raw = Path(str(config.get(key)))
        declared = config.source_of(key).path
        base = declared.parent if declared is not None else cwd
        out[name] = str(raw if raw.is_absolute() else (base / raw).resolve())
    return out


def _parse(argv: Sequence[str], stderr: TextIO) -> argparse.Namespace | int:
    """The generated tree's namespace, or its exit. `--help` is 0; a parse error is 1 (10:1484).

    Both of argparse's streams go to stderr, `--help` included: stdout is the protocol channel
    the moment the server starts, and nothing on this path is allowed to learn to write there.
    """
    from omniweave.cli import build_parser  # noqa: PLC0415 -- only `ow serve` pays for the tree

    try:
        with contextlib.redirect_stdout(stderr), contextlib.redirect_stderr(stderr):
            return build_parser().parse_args(list(argv))
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else _USAGE
        return _USAGE if code == _ARGPARSE_USAGE else code


def _transport(parsed: argparse.Namespace) -> None:
    """Exactly one transport, and no listener flag beside a pipe. Raises; returns nothing."""
    if parsed.mcp == parsed.http:
        raise UsageError(
            "ow serve needs exactly one of --mcp (stdio) or --http",
            fix="ow serve --mcp",
        )
    if parsed.http:
        raise InternalError(
            "ow serve --http is not dispatched by this build: http.Listener is an ASGI "
            "application and no ASGI server is a dependency to host it",
            fix="ow serve --mcp",
        )
    given = [name for name in HTTP_ONLY if getattr(parsed, name) not in (None, False)]
    if given:
        flags = ", ".join("--" + "-".join(name.split("_")) for name in given)
        raise UsageError(
            f"--mcp takes no HTTP listener flag, and was given {flags}",
            fix="ow serve --mcp",
        )


def _unexpressible(resolution: Resolution) -> None:
    """D510: refuse a listed set the listing cannot send, rather than send the profile's."""
    shown = {ACTIONS[name].mcp_name for name in resolution.listed}
    promised = {ACTIONS[name].mcp_name for name in listed(resolution.profile)}
    if shown == promised:
        return
    raise UsageError(
        f"{resolution.listed_from} lists a set other than profile {resolution.profile}'s, and "
        f"the server can send a profile's list only; serving it would narrow the listing "
        f"without saying so",
        fix="remove the override, or set [serve] profile to the profile you want",
    )


def _line(error: OwError) -> str:
    """10:294's shape: code, exit, message and fix on one line. ASCII, because a piped child's
    stderr on Windows is cp1252 and a message can carry argv (D431)."""
    code = f"{error.code()} " if error.code() else ""
    text = f"ow: {code}(exit {type(error).EXIT}): {error}; fix: {error.fix}\n"
    return text.encode("ascii", "backslashreplace").decode("ascii")
