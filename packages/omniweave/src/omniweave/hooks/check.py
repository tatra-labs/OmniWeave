"""`ow hooks check`: resolve each installed command string, execute it as a host would, judge it.

10:2078 is the whole premise in one sentence: *"Verifying a hook by reading `settings.json` proves
nothing."* So this module resolves the command string, runs it as a real child with a synthetic
payload on stdin, and applies 10:2079's five assertions to what comes back -- exit 0, JSON where
the event has a channel, the right channel key, the self-deadline, no store sidecar created. A
command that cannot be spawned is `OW-A-030 OW_HOOK_NOT_RESOLVABLE`, reported with the command
string and the PATH it was resolved against (10:2082).

This is the engine. The verb, `ow hooks check`, is `omniweave.install.verbs.hooks_check` (W7.5i):
it reads the command strings *as installed* from the files the install receipt's `json-hook-rules`
rows name (10 section 7.3) and hands them to `check()` as the mapping it takes.

## THE PROBE RUNS IN A SCRATCH PROJECT, BECAUSE A SCRATCH HOME PROTECTS NOTHING THE PROBE TOUCHES

10:2088 promises *"the probe runs against a scratch `$OMNIWEAVE_HOME` … so `ow hooks check` can
never mutate the deployment it is checking."* But a hook writes only under `<sessions>/`, and
10:1893 puts that *"beside the resolved `omniweave.toml`"* -- in the project, not under
`$OMNIWEAVE_HOME`. A probe run from the user's project with only the home swapped would append a
synthetic edit to a real `.pending` queue (which a drain would later try to ingest), write a
`.compacted` marker, and run 10:1918's 24-hour sweep over the real `<sessions>/` twice. D437.

So every probe runs with its **cwd in a scratch project** -- an `omniweave.toml` under a `.git`, so
the upward walk stops there -- and `OMNIWEAVE_HOME` pointed at scratch as well. That costs one
thing, stated rather than hidden: the probe cannot see the user's corpora, so it checks the hook
*process* and not the user's data. Running from another directory also tests something real: a
hook command that only works from one cwd is a hook that fails when the host starts elsewhere.

## THE DEADLINE IS NOT VISIBLE FROM OUTSIDE THE PROCESS

The self-deadline is measured inside `run()` and a checker sees only the child's wall time, which
includes interpreter start-up and every import. Measured warm on this machine: `python -c pass` is
37 ms at p50 and `ow hook prompt` 106 ms. 18:2992-2996 prints `41 ms`, `8 ms`, `3 ms`, `11 ms` and
`6 ms` for five hooks, and four of those are below what it costs to start the interpreter at all --
so they cannot be what a checker measures, and nothing gives a hook a channel to report its own
elapsed time to one. D438.

So the check is one-sided and says so: a wall time at or under `SELF_DEADLINE_MS` **proves** the
deadline was met, because the in-process time is a part of it. Anything over is `unproven` -- shown
with the number, and not a failure, because a checker that failed every cold start would be ignored
by the second week.

## "RESOLVE" DEPENDS ON THE HOST'S SHELL AND THE HOST'S PATH, AND THE CHECK KNOWS NEITHER

10:2083 says this verb *"catches the Windows backslash-eating bug, the minimal-PATH bug and a stale
absolute path after a `pipx reinstall`"*. The third needs nothing but a stat. The other two depend
on facts about the host the plan never records:

- **The backslash bug exists only if the host runs the string through a POSIX shell**, which
  consumes each backslash in an unquoted `C:\\Users\\u\\ow.exe`. The split here is POSIX (`shlex`,
  `posix=True`), the parse that exhibits the bug, so an unquoted Windows path comes back as
  `C:Usersuow.exe` and is reported unresolvable -- the bug, caught. A host that uses `cmd.exe`
  would not have it, and the report names the parse used so a reader can tell.
- **The minimal-PATH bug needs the host's PATH**, and the checker has the user's -- exactly the
  environment in which a bare `ow` resolves and the bug hides. So a bare name that resolves is
  still flagged `host-path`: it worked here, and whether it works for the host is not knowable from
  here. D439.

A relative path with a separator (`./ow`, `bin/ow`) is refused without resolving it, for 10:2069's
reason: it would resolve against the cwd, and `posttool.command()` refuses the same shape.
"""

from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave.hooks.envelope import (
    CHANNEL,
    DECISION_CHANNEL,
    DECISION_REASON,
    EVENTS,
    KILL_SWITCH,
    KILL_VALUE,
    SELF_DEADLINE_MS,
)
from omniweave.hooks.main import WORDS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_core.clock import Clock
    from omniweave_core.host.subproc import Captured

__all__ = [
    "FAIL",
    "NOT_RESOLVABLE",
    "OK",
    "UNPROVEN",
    "Judged",
    "Probe",
    "Report",
    "Resolution",
    "check",
    "fixture",
    "judge",
    "probe",
    "render",
    "resolve",
    "scratch_project",
    "sidecars",
    "split",
    "unchecked",
]

OK: Final[str] = "ok"
FAIL: Final[str] = "fail"
UNPROVEN: Final[str] = "unproven"

NOT_RESOLVABLE: Final[str] = "OW_HOOK_NOT_RESOLVABLE"
"""10:2082's symbol. `OW-A-030` in `codes.toml`, and a test asserts the pairing."""

PROBE_TIMEOUT_S: Final[float] = 10.0

# D458: what `/bin/sh` reads as syntax when it is not quoted.
_OPERATORS: Final = frozenset("();<>|&")
"""How long one probe may run before it is killed and failed.

Not the self-deadline, which is the hook's own and invisible from here (D438). Twenty-five times
it, so a cold start on a slow disk is never mistaken for a hang, and a real hang still ends.
"""

_SIDECAR_SUFFIXES: Final[tuple[str, ...]] = ("-wal", "-shm")
_TIMED_OUT: Final[str] = "TimeoutExpired"
_WORD_OF: Final[Mapping[str, str]] = {event: word for word, event in WORDS.items()}
_ALLOWED_KEYS: Final[Mapping[str, frozenset[str]]] = {
    "PreToolUse": frozenset({"hookEventName", CHANNEL, DECISION_CHANNEL, DECISION_REASON}),
}
_SPEAKING_KEYS: Final[frozenset[str]] = frozenset({"hookEventName", CHANNEL})


# ---------------------------------------------------------------------------------------------
# Fixtures. 10:2086, with the one change that lets a shipped verb read them. D436.
# ---------------------------------------------------------------------------------------------


def fixture(word: str) -> bytes:
    """The synthetic payload for `ow hook <word>`, as the bytes a host would write to stdin.

    **Package data, not `tests/fixtures/hooks/`.** 10:2086 puts them in the test tree *"so a payload
    shape that changed in a host release is updated once"* -- and this package's wheel ships
    `src/omniweave` and its sdist `src`, so a file under `tests/` is in neither artefact a user
    installs, and a shipped `ow hooks check` could not read its own payloads. The files live here
    and the unit tests read them from here, which keeps 10:2086's actual requirement: one copy.
    """
    return resources.files(__package__).joinpath("fixtures", f"{word}.json").read_bytes()


# ---------------------------------------------------------------------------------------------
# Resolving a command string. D439.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a command string becomes: the argv, the executable it names, and why it is not one."""

    command: str
    argv: tuple[str, ...] = ()
    executable: str = ""
    reason: str = ""
    host_path: bool = False

    def ok(self) -> bool:
        return bool(self.executable)


def split(command: str, *, posix: bool = True) -> tuple[str, ...]:
    """The argv a shell would produce, or `()` when the string will not parse.

    POSIX by default because that is the parse in which the backslash bug exists; see the module
    docstring. An unbalanced quote is `()` rather than an exception, and `resolve()` reports it.
    """
    try:
        return tuple(shlex.split(command, posix=posix))
    except ValueError:
        return ()


def resolve(
    command: str,
    *,
    path: str,
    posix: bool = True,
    which: Callable[[str, str], str | None] | None = None,
    exists: Callable[[Path], bool] | None = None,
) -> Resolution:
    """Resolve the first word of `command` the way a host would, without ever consulting the cwd.

    Three shapes and three rules. An absolute path must exist -- the stale-`pipx` case. A path with
    a separator but no root is refused unresolved, because it would resolve against the cwd
    (10:2069). A bare name is searched on `path` and, if found, marked `host_path`, because the
    host's PATH is not this one (D439).
    """
    argv = split(command, posix=posix)
    if not argv:
        return Resolution(command, reason="empty or unparseable command string")
    head = argv[0]
    eaten = _eaten(command, head, posix=posix) or _syntax(command, posix=posix)
    if eaten:
        return Resolution(command, argv, reason=eaten)
    if Path(head).is_absolute() or "/" in head or "\\" in head:
        return _by_path(command, argv, exists=exists or _is_file)
    found = (which or _which)(head, path)
    if found is None:
        return Resolution(command, argv, reason=f"{head} is not on PATH", host_path=True)
    return Resolution(command, (found, *argv[1:]), executable=found, host_path=True)


def _by_path(command: str, argv: tuple[str, ...], *, exists: Callable[[Path], bool]) -> Resolution:
    """A head with a separator: absolute must exist; relative is refused without looking."""
    head = argv[0]
    if not Path(head).is_absolute():
        return Resolution(command, argv, reason=f"{head} is relative and would resolve in the cwd")
    if exists(Path(head)):
        return Resolution(command, argv, executable=head)
    return Resolution(command, argv, reason=f"{head} does not exist")


def _eaten(command: str, head: str, *, posix: bool) -> str:
    """The backslash bug, named as itself -- or `""` when this command does not have it.

    Measured on this machine: an unquoted `E:\\AI\\_Project\\Project (tatra-labs)\\...\\python.exe`
    splits to `E:AI_ProjectProject`, and *"not on PATH"* would send the reader looking at PATH. The
    fix is in the command string, so the message says what happened to it and what to write.
    """
    if not posix or "\\" not in command:
        return ""
    literal = split(command, posix=False)
    if not literal or literal[0] == head or "\\" not in literal[0]:
        return ""
    return (
        f"a POSIX shell consumed the backslashes: {literal[0]} became {head}; "
        "quote the path and write it with forward slashes"
    )


def _syntax(command: str, *, posix: bool) -> str:
    """An unquoted shell operator, named as itself -- or `""` when the string is one plain command.

    `shlex.split` is a word splitter, not a shell grammar, and the probe runs the argv it returns.
    Measured under this machine's `/bin/sh` (GNU bash 5.2): `C:/tools(x86)/ow.exe hook session-end`
    is *"syntax error near unexpected token `x86'"*, exit 2, while `shlex` splits it into a
    runnable argv -- so the check would pass a hook its host cannot even parse. An unquoted `;`,
    `|`, `&` or redirect is the same gap from the other side: the host runs a pipeline the probe
    never ran. `punctuation_chars` makes the operators separate words, and a quoted one stays
    inside its word. D458.
    """
    if not posix:
        return ""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:
        return ""
    found = next((word for word in words if word and set(word) <= _OPERATORS), "")
    if not found:
        return ""
    return (
        f"a POSIX shell reads the unquoted {found!r} as syntax, so the host would not run this as "
        "one program; quote any path that contains it"
    )


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _which(name: str, path: str) -> str | None:
    return shutil.which(name, path=path)


# ---------------------------------------------------------------------------------------------
# Judging one run. 10:2079's five assertions.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Judged:
    """One assertion's name, status and a detail a reader can act on."""

    name: str
    status: str
    detail: str = ""


def judge(
    event: str,
    *,
    returncode: int | None,
    stdout: bytes,
    wall_ms: int,
    created: Iterable[str] = (),
) -> tuple[Judged, ...]:
    """10:2079 in order: exit 0, JSON where there is a channel, the right key, deadline, sidecars.

    **An empty stdout is a pass on a channel event**, because a silent tier is a correct answer --
    18:2994 prints `(silent)` against `UserPromptSubmit` for exactly this. What fails is stdout on
    an event with no channel, which is text written into a field nobody reads (10:1926's jcodemunch
    bug), and JSON whose keys are not the ones that event may use.
    """
    spec = EVENTS[event]
    results = [
        Judged("exit", OK if returncode == 0 else FAIL, f"exit {returncode}"),
        *_channel(event, stdout, speaks=spec.speaks()),
        _deadline(wall_ms),
    ]
    made = sorted(created)
    results.append(Judged("sidecars", FAIL if made else OK, ", ".join(made)))
    return tuple(results)


def _channel(event: str, stdout: bytes, *, speaks: bool) -> tuple[Judged, Judged]:
    if not stdout.strip():
        return Judged("json", OK, "silent"), Judged("channel", OK, "silent")
    if not speaks:
        detail = "this event has no channel and printed anyway"
        return Judged("json", FAIL, detail), Judged("channel", FAIL, detail)
    try:
        parsed: Any = json.loads(stdout)
    except ValueError:
        return Judged("json", FAIL, "stdout is not JSON"), Judged("channel", FAIL, "")
    return Judged("json", OK), _keys(event, parsed)


def _keys(event: str, parsed: Any) -> Judged:
    """The channel half: one `hookSpecificOutput` object, this event's name, this event's keys."""
    body = parsed.get("hookSpecificOutput") if isinstance(parsed, dict) else None
    if not isinstance(body, dict):
        return Judged("channel", FAIL, "no hookSpecificOutput object")
    if body.get("hookEventName") != event:
        return Judged("channel", FAIL, f"hookEventName is not {event}")
    extra = frozenset(str(key) for key in body) - _ALLOWED_KEYS.get(event, _SPEAKING_KEYS)
    return Judged("channel", FAIL, ", ".join(sorted(extra))) if extra else Judged("channel", OK)


def _deadline(wall_ms: int) -> Judged:
    """One-sided: at or under the self-deadline proves it; over it proves nothing. D438."""
    if wall_ms <= SELF_DEADLINE_MS:
        return Judged("deadline", OK, f"{wall_ms} ms")
    return Judged("deadline", UNPROVEN, f"{wall_ms} ms spawn-inclusive; in-process time unseen")


def sidecars(watch: Iterable[Path]) -> frozenset[str]:
    """Every `-wal`/`-shm` file beside each watched store path. Never raises.

    10:2081's *"no store WAL sidecar was created by the call"* is a before/after difference, so this
    is taken twice. `-shm` is included because it is created with the `-wal` by the same read-write
    open I10 is about, and a probe that made one made the other.
    """
    found: set[str] = set()
    for store in watch:
        for suffix in _SIDECAR_SUFFIXES:
            sidecar = store.with_name(store.name + suffix)
            if _is_file(sidecar):
                found.add(str(sidecar))
    return frozenset(found)


# ---------------------------------------------------------------------------------------------
# Probing, and the report.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Probe:
    """One event's resolution, what the child did, and the five judgements."""

    event: str
    resolution: Resolution
    returncode: int | None = None
    stdout: bytes = b""
    wall_ms: int = 0
    failed: str = ""
    judged: tuple[Judged, ...] = ()

    def status(self) -> str:
        if not self.resolution.ok() or self.failed:
            return FAIL
        statuses = {item.status for item in self.judged}
        if FAIL in statuses:
            return FAIL
        return UNPROVEN if UNPROVEN in statuses else OK


@dataclass(frozen=True, slots=True)
class Report:
    """Every probe, plus what the environment itself says about the result."""

    probes: tuple[Probe, ...] = ()
    path: str = ""
    posix: bool = True
    notes: tuple[str, ...] = ()

    def exit_code(self) -> int:
        """10:1432 gives `ow hooks check` `0/1`: 1 when any probe fails; `unproven` is not one."""
        return 1 if any(item.status() == FAIL for item in self.probes) else 0


def scratch_project(root: Path) -> tuple[Path, Path]:
    """`(cwd, home)` under `root`: a project whose `<sessions>/` is scratch, and a home. D437.

    `.git` stops the upward walk for `omniweave.toml` (10:1893), so no probe can resolve the user's
    project even if `root` is inside it.
    """
    project, home = root / "project", root / "home"
    (project / ".git").mkdir(parents=True, exist_ok=True)
    (project / "omniweave.toml").write_text("", encoding="utf-8")
    home.mkdir(parents=True, exist_ok=True)
    return project, home


def probe(
    event: str,
    command: str,
    *,
    runner: Callable[[Sequence[str], bytes, Path, Mapping[str, str], float], Captured],
    clock: Clock,
    path: str,
    cwd: Path,
    env: Mapping[str, str],
    watch: Iterable[Path] = (),
    posix: bool = True,
) -> Probe:
    """Resolve, run with this event's fixture, judge. An unresolvable command is never executed."""
    resolution = resolve(command, path=path, posix=posix)
    if not resolution.ok():
        return Probe(event, resolution)
    stores = tuple(watch)
    before = sidecars(stores)
    started = clock.monotonic_ns()
    ran = runner(resolution.argv, fixture(_WORD_OF[event]), cwd, env, PROBE_TIMEOUT_S)
    wall_ms = -(-(clock.monotonic_ns() - started) // 1_000_000)
    judged = judge(
        event,
        returncode=ran.returncode,
        stdout=ran.stdout,
        wall_ms=wall_ms,
        created=sidecars(stores) - before,
    )
    return Probe(event, resolution, ran.returncode, ran.stdout, wall_ms, ran.failed, judged)


def check(
    commands: Mapping[str, str],
    *,
    runner: Callable[[Sequence[str], bytes, Path, Mapping[str, str], float], Captured],
    clock: Clock,
    path: str,
    scratch: Path,
    env: Mapping[str, str],
    watch: Iterable[Path] = (),
    posix: bool = True,
) -> Report:
    """Probe every installed event, in 10:1849's table order, inside one scratch project.

    The child's environment is the caller's with three changes: `PATH` is the one resolved against,
    `OMNIWEAVE_HOME` is scratch (10:2088), and **`OMNIWEAVE_HOOK` is removed**. With the kill switch
    inherited, every probe would exit 0 silently and the check would pass on hooks that are off --
    so it is stripped, and its presence in the caller's environment is reported as a note instead.
    """
    cwd, home = scratch_project(scratch)
    child = {key: value for key, value in env.items() if key != KILL_SWITCH}
    child["PATH"] = path
    child["OMNIWEAVE_HOME"] = str(home)
    notes: list[str] = []
    if env.get(KILL_SWITCH) == KILL_VALUE:
        notes.append(f"{KILL_SWITCH} is set here, so these hooks may be off for the host too")
    stores = tuple(watch)
    if not stores:
        notes.append("no store watched: the sidecar assertion is vacuous for this run")
    probes = tuple(
        probe(
            event,
            commands[event],
            runner=runner,
            clock=clock,
            path=path,
            cwd=cwd,
            env=child,
            watch=stores,
            posix=posix,
        )
        for event in EVENTS
        if event in commands
    )
    return Report(probes, path=path, posix=posix, notes=tuple(notes))


def render(report: Report) -> str:
    """18:2991-2997's table: event, command, `resolved · exit 0 · N ms`, then one summary line."""
    lines: list[str] = []
    for item in report.probes:
        lines.append(f"{item.event:<17} {item.resolution.command:<42} {_verdict(item)}")
    lines.extend(_summary(report))
    return "\n".join(lines)


def _verdict(item: Probe) -> str:
    if not item.resolution.ok():
        return f"{NOT_RESOLVABLE} · {item.resolution.reason}"
    if item.failed == _TIMED_OUT:
        return f"resolved · killed after {PROBE_TIMEOUT_S:g} s"
    if item.failed:
        #  10:2082: OW-A-030 is reported "when the spawn fails" -- a path that resolved and then
        #  would not execute (no permission, not a binary) is the same finding as one that did not.
        return f"{NOT_RESOLVABLE} · resolved but the spawn failed: {item.failed}"
    silent = " (silent)" if EVENTS[item.event].speaks() and not item.stdout.strip() else ""
    parts = [f"resolved · exit {item.returncode} · {item.wall_ms:>3} ms{silent}"]
    parts.extend(f"{j.name} {j.status}: {j.detail}" for j in item.judged if j.status != OK)
    if item.resolution.host_path:
        parts.append("host-path")
    return " · ".join(parts)


def _summary(report: Report) -> list[str]:
    total = len(report.probes)
    unresolved = [
        item
        for item in report.probes
        if not item.resolution.ok() or (item.failed and item.failed != _TIMED_OUT)
    ]
    ran = sum(1 for item in report.probes if item.judged)
    proven = sum(
        1
        for item in report.probes
        if any(j.name == "deadline" and j.status == OK for j in item.judged)
    )
    lines: list[str] = []
    #  A deadline is only proven for a probe that ran; "0 of 6 proven" over six unresolvable
    #  commands would read as six slow hooks, which is the wrong thing to go and fix.
    if ran and proven == ran == total:
        lines.append(f"all {total} under the {SELF_DEADLINE_MS} ms self-deadline")
    elif ran:
        lines.append(f"{proven} of {ran} run proven under the {SELF_DEADLINE_MS} ms self-deadline")
    if total - ran:
        lines.append(f"{total - ran} of {total} did not run")
    if unresolved:
        lines.append(f"PATH searched: {report.path}")
    parse = "POSIX shell" if report.posix else "Windows"
    lines.append(f"parsed as a {parse} would split it")
    lines.extend(report.notes)
    return lines


def unchecked() -> tuple[str, ...]:
    """What this check runs against a reading rather than against a statement."""
    return (
        "where the payload fixtures live. 10:2086 puts them in tests/, which neither this "
        "package's wheel nor its sdist ships, so a shipped verb could not read them. They are "
        "package data here and the tests read the same files (D436)",
        "what a scratch $OMNIWEAVE_HOME protects. <sessions>/ is beside omniweave.toml (10:1893), "
        "so a probe run from the user's project writes a fake queued edit and a marker into the "
        "real deployment and sweeps it. Probes run in a scratch project (D437)",
        "whether the self-deadline was met. It is measured inside the process and a checker sees "
        "spawn-inclusive time; 18:2992-2996 prints numbers below interpreter start-up. At or under "
        "400 ms proves it; over is unproven, not failed (D438)",
        "the host's shell and PATH. The backslash bug exists only under a POSIX shell and the "
        "minimal-PATH bug only on the host's PATH; the plan records neither. POSIX split, and a "
        "bare name that resolves is still flagged host-path (D439)",
        "the verb itself. The command strings are the install receipt's (10 section 7.3), which is "
        "W7.5; check() takes them as a mapping until then",
        "which stores to watch. 10:2088's 'a copy of the store's path with immutable=1' does not "
        "say which store or copy what; the hooks open no store yet, so the watch list is the "
        "caller's and an empty one is reported as vacuous (D440)",
    )
