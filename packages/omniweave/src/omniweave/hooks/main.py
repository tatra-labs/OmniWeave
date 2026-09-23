"""`ow hook <event>`: the process around the six handlers -- bytes in, bytes out, always exit 0.

16:718 gives W7.4 its first clause as *"`hooks/`: `ow hook <event>`"*, and every cell before this
one built what that command runs without building the command. Six handlers existed and nothing
could invoke one as a process, which is also the thing `ow hooks check` (10 section 8.7) exists to
execute. So this comes first.

## THE OBVIOUS HOOK CRASHES ON WINDOWS, AND IT CRASHES ON ITS OWN OUTPUT

Measured on this machine, in a child whose stdio are pipes -- which is how every host runs a hook:

| | what the child gets | what happens |
|---|---|---|
| `sys.stdout.encoding` / `sys.stdin.encoding` | `cp1252` / `cp1252` | UTF-8 mode is off |
| `print()` of a briefing containing `->` as U+2192 | `UnicodeEncodeError` | **exit 1** |
| `sys.stdin.read()` of a UTF-8 prompt | U+2192 arrives as three characters | **no error at all** |

The first breaks 10:1842's *"every failure path is a silent exit 0"* on exactly the output a hook
exists to produce: `emission()` writes `ensure_ascii=False`, `precompact`'s restoration heading is
plain ASCII but the cites, corpus names and file names inside a briefing are the user's, and one
non-cp1252 character anywhere is an exit 1 the host shows the user. The second is worse because it
is silent: the front-load's cite, filename and phrase detectors run over mojibake, so a prompt that
quotes `"Kündigungsfrist"` or names `契約.pdf` is misread and the gate simply
stays quiet -- which is also what a correct miss looks like. D431.

**The plan says nothing about stdio encoding anywhere.** Not in section 8, not in 02 row 34, not in
the MCP stdio transport's section. So this module never touches text-mode stdio: it reads
`sys.stdin.buffer`, hands the bytes to `json.loads` (which detects UTF-8, UTF-16 and a UTF-8 BOM on
its own), and writes `emission()`'s string to `sys.stdout.buffer` encoded as UTF-8. Neither
direction depends on the console code page, `PYTHONUTF8` or `PYTHONIOENCODING`, all three of which
belong to the user's machine and not to this package.

## G26 TIMES A VERB THAT MAY NOT EXIST

`ow hook prompt` is the command G26 gates -- 13 occurrences across 01, 02, 04, 10, 11, 12 and 15.
The only transcript that spells every event (18:2992-2996) writes `ow hook user-prompt-submit`, and
no document spells `prompt` for any other event or `user-prompt-submit` anywhere else.

**The failure is not a naming inconsistency, it is a gate that passes by measuring the wrong
path.** An event word the CLI does not know is 10:1849's *"an exit 0 and a counter and never an
error"*, and it is the cheapest silent exit there is: no handler, no file, no store. A G26 harness
timing `ow hook prompt` against a build that only accepts `user-prompt-submit` would report the
fastest numbers in the framework for a command that did nothing. D432.

So both are accepted and land on one handler, and the alias set is closed at the one other spelling
the plan uses. `WORDS` is derived from `EVENTS` rather than retyped, so a seventh event cannot be
added to the table without acquiring a word.

## THE DRAIN IS NOT WIRED, BECAUSE THE THING IT WOULD SPAWN CANNOT RUN

`posttool.command()` produces `(argv0, "ingest")` or `(sys.executable, "-m", "omniweave",
"ingest")`, and **neither runs today**: there was no `omniweave/__main__.py` until this cell, there
is no `ow` console script in any `pyproject.toml`, and `ingest` is not a verb anything dispatches.
A real spawn would start a child that exits 1 at import into `DEVNULL`, holding a lease for 30 s per
burst that it never releases -- and the counter would read `drained`. W7.4g's docstring and D425
said the interpreter fallback *"always works"*; it could not have worked when that was written.
D433.

So `PostToolUse` and `SessionEnd` are wired with `spawn=None`, which releases the lease and counts
`noop-spawn-failed` -- a counter that tells the truth about a drain that did not happen, instead of
one that claims a drain that died. The queue still fills, so nothing is lost that a later drain
cannot take. `test_the_drain_stays_unwired_until_something_dispatches_ingest` ties this to
`__main__.DISPATCHED`, so the day `ingest` becomes dispatchable the suite says so.

## WHAT THE STORE-BACKED SEAMS ARE, TODAY

`Verify`, `Probes` and `Lookup` are the three seams that read a store, and each handler already has
a documented quiet path for `None`. This module passes `None` for all three: `SessionStart` briefs
without cites and says they were withheld, `UserPromptSubmit` stays silent, and `PreToolUse` fails
its first gate because resolving `[roots] source` is `config`'s job and D401 measured what importing
`config` costs here. Wiring them is the `connect_readonly` ladder's cell, not this one's.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, BinaryIO, Final

from omniweave.hooks import posttool, precompact, pretool, prompt, sessionend, sessionstart
from omniweave.hooks.envelope import EVENTS, EXIT_OK, Advice, Outcome, run, session_key
from omniweave.hooks.session import sessions_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core.clock import Clock

__all__ = [
    "ALIASES",
    "HOOK_WORD",
    "WORDS",
    "entry",
    "event_of",
    "handler_for",
    "kebab",
    "main",
    "read_payload",
    "unwired",
    "write_stdout",
]

HOOK_WORD: Final[str] = "hook"
"""10:1434's `ow hook <event>`: *"hidden from `--help`; reads stdin JSON"*, exit **always 0**."""

_CAMEL_BOUNDARY: Final = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def kebab(name: str) -> str:
    """`UserPromptSubmit` -> `user-prompt-submit`, which is 18:2992-2996's spelling of all six."""
    return _CAMEL_BOUNDARY.sub("-", name).lower()


WORDS: Final[Mapping[str, str]] = MappingProxyType({kebab(name): name for name in EVENTS})
"""The CLI word for each of 10:1849's six events, derived from `EVENTS` and never retyped.

18:2992-2996 prints five of the six (`pre-tool-use` is absent under `--hooks context`) and the
sixth follows by the same rule. A test asserts the five printed words are exactly what this derives.
"""

ALIASES: Final[Mapping[str, str]] = MappingProxyType({"prompt": "UserPromptSubmit"})
"""G26's spelling, closed at one entry: it is the only other spelling the plan uses. D432."""

_NO_TARGET: Final = pretool.Target()


def event_of(word: str) -> str:
    """The event a CLI word names, or `""`. An unknown word is counted by `run()`, never raised."""
    return WORDS.get(word) or ALIASES.get(word, "")


def read_payload(stream: BinaryIO | None) -> Mapping[str, Any]:
    """The host's JSON object from **bytes**, or `{}`. Never raises; never decodes via a code page.

    `json.loads` on `bytes` detects UTF-8, UTF-16 and UTF-32 itself and accepts a UTF-8 BOM --
    which, measured on this machine, is what PowerShell prepends (with a trailing CRLF) when a user
    pipes a fixture into `ow hook` by hand. Anything that is not a JSON object is `{}`: every
    handler's missing-field path is a quiet exit, and a payload this module cannot read is a
    payload no handler could have used.
    """
    if stream is None:
        return {}
    try:
        raw = stream.read()
        parsed = json.loads(raw)
    #  `RecursionError` is not a `ValueError`: measured, 100 KB of `[` escapes `json.loads` as one,
    #  and this read runs BEFORE `run()`, so an escape here would bypass the envelope's counter.
    except (OSError, ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def write_stdout(stream: BinaryIO | None, text: str) -> bool:
    """Write `text` as UTF-8 and flush. `True` only when every byte is gone. Never raises.

    The return is what makes `Outcome.settle()` safe to call: 10:2004 puts the ledger write
    *"after the hook's stdout is flushed"*, so a write that failed -- a host that closed the pipe,
    a lone surrogate from an undecodable file name that strict UTF-8 refuses -- must not be
    followed by a ledger claiming an emission the model never received.
    """
    if not text:
        return False
    if stream is None:
        return False
    try:
        stream.write(text.encode("utf-8"))
        stream.flush()
    except (OSError, ValueError):  # UnicodeEncodeError is a ValueError.
        return False
    return True


def handler_for(
    event: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    clock: Clock,
    pid: int,
    argv0: str,
) -> Callable[[Mapping[str, Any]], Advice]:
    """The handler for `event`, with every seam this build can supply and `None` for the rest.

    `<sessions>/` is resolved **inside** the returned callable, not here, so the upward walk for
    `omniweave.toml` runs inside `run()`'s `try` and under its clock. A walk that raised out here
    would be a failure path that is not a silent exit 0, and a walk timed nowhere is a cost G26
    pays that the self-deadline cannot see.
    """
    builders: Mapping[str, Callable[[Path | None], Callable[[Mapping[str, Any]], Advice]]] = {
        "SessionStart": lambda root: sessionstart.handler(root, clock.wall_ns, verify=None),
        "PreCompact": lambda root: precompact.handler(root, clock.wall_ns),
        "UserPromptSubmit": lambda _root: prompt.handler(None),
        "PreToolUse": lambda root: pretool.handler(
            target_of=_no_target, lookup=None, env=env, root=root, key_of=session_key
        ),
        "PostToolUse": lambda root: posttool.handler(
            root, key_of=session_key, now_ns=clock.wall_ns, pid=pid, spawn=None, argv0=argv0
        ),
        "SessionEnd": lambda root: sessionend.handler(
            root, key_of=session_key, now_ns=clock.wall_ns, pid=pid, spawn=None, argv0=argv0
        ),
    }
    build = builders.get(event)

    def bound(payload: Mapping[str, Any]) -> Advice:
        if build is None:
            return Advice()
        return build(sessions_dir(cwd))(payload)

    return bound


def _no_target(payload: Mapping[str, Any]) -> pretool.Target:  # noqa: ARG001 -- the seam's shape
    """No `[roots] source` without `config`, so gate 1 fails and `PreToolUse` says nothing. D401."""
    return _NO_TARGET


def main(
    argv: Sequence[str],
    *,
    stdin: BinaryIO | None,
    stdout: BinaryIO | None,
    env: Mapping[str, str],
    clock: Clock,
    cwd: Path,
    tty: bool,
    pid: int,
    argv0: str = "",
) -> Outcome:
    """One invocation: word, payload, handler, envelope, bytes out, flush, settle.

    **A TTY is checked before stdin is read, and that is the only order that works.** `run()` takes
    the payload as an argument, so by the time it can apply 10:1996's *"immediate return when stdin
    is a TTY"* the read has already happened -- and a read on a terminal blocks until a human types
    something. So the payload is not read at all on a TTY, and `run()` is still called with
    `tty=True` so the silence is counted like every other.

    **`settle()` runs only after `write_stdout()` returns `True`**, which is 10:2004's ordering with
    the one condition that makes it mean something: the bytes are flushed, not merely produced.
    """
    word = argv[0] if argv else ""
    #  Never `event_of(word) or word`: that makes every raw event name (`UserPromptSubmit`) a CLI
    #  word, which is an alias set nobody declared. An unknown word is `""`, which `run()` counts.
    event = event_of(word)
    payload: Mapping[str, Any] = {} if tty else read_payload(stdin)
    bound = handler_for(event, cwd=cwd, env=env, clock=clock, pid=pid, argv0=argv0)
    outcome = run(event, payload, bound, clock=clock, env=env, tty=tty)
    if write_stdout(stdout, outcome.stdout):
        outcome.settle()
    return outcome


def entry(argv: Sequence[str], *, cwd: Path) -> int:
    """`python -m omniweave hook <event>`. Always `EXIT_OK`, including when `main` itself fails.

    `cwd` is an argument because this is library code and the working directory is an ambient
    input 02:392 bans here: `__main__.py` reads it, once, and hands it down (D435).

    The `except` is the last line of 10:1842 and it is wide on purpose. Everything below it already
    returns rather than raises, so this catches only what nobody predicted -- and an unpredicted
    failure in a hook is precisely the case the rule exists for.
    """
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- G17: two modules, 0 deps

    try:
        stdin = sys.stdin.buffer if sys.stdin is not None else None
        stdout = sys.stdout.buffer if sys.stdout is not None else None
        main(
            argv,
            stdin=stdin,
            stdout=stdout,
            env=os.environ,
            clock=SystemClock(),
            cwd=cwd,
            tty=_isatty(sys.stdin),
            pid=os.getpid(),
            argv0=sys.argv[0] if sys.argv else "",
        )
    except Exception:  # noqa: S110 -- 10:1842, "every failure path is a silent exit 0"
        pass
    return EXIT_OK


def _isatty(stream: Any) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (OSError, ValueError):
        return False


def unwired() -> tuple[str, ...]:
    """What this entry point runs against a reading rather than against a statement."""
    return (
        "hook stdio encoding. On Windows a piped child gets cp1252: print() of a non-cp1252 "
        "briefing raises and exits 1, and text-mode stdin turns a UTF-8 prompt into mojibake "
        "with no error. The plan says nothing; this reads and writes bytes (D431)",
        "which word G26 times. `ow hook prompt` is the gated command in seven documents and "
        "18:2994 spells it `ow hook user-prompt-submit`; an unknown word is the cheapest silent "
        "exit there is, so a gate on the wrong one passes by measuring nothing. Both are "
        "accepted (D432)",
        "the drain. Neither form `posttool.command()` produces can run -- no console script, and "
        "`ingest` is not dispatched -- so PostToolUse and SessionEnd are wired with spawn=None "
        "and count `noop-spawn-failed` rather than `drained` (D433)",
        "the three store-backed seams. Verify, Probes and Lookup are None: SessionStart withholds "
        "cites, UserPromptSubmit is silent and PreToolUse fails gate 1, each by its documented "
        "quiet path. They belong to the connect_readonly cell",
        "the counters. Every Outcome carries its counter and none is persisted, because the "
        "counters file is D397's decision",
    )
