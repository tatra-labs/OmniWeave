"""`ow install`, `ow uninstall`, `ow hooks check` and the `ow skills` verbs, from argv.

`__main__` routes the four roots here now that their `ACTIONS` rows exist (W7.5h, W7.5i, W7.6b). The
argv is parsed by the generated tree (`omniweave.cli.build_parser`, artefact 3, byte-gated by G25),
so a flag this file reads is a flag the registry published -- and one it does not publish cannot be
typed.

## WHAT THE ENVIRONMENT IS READ FOR, AND NOTHING ELSE

The environment is handed in, never read ambiently. It gives `$OMNIWEAVE_HOME` -- or
`<home>/.omniweave`, `omniweave_core.config`'s own default (`_home_config`) -- and the user's home,
`HOME` then `USERPROFILE`, the same two names in the same order. The project root a `local`
install writes under is the working directory `__main__` was started in, resolved (10:1734). The
launcher is `hookrules.launcher()` (D456). The skill bundles are the repository's `skills/`, found
from this file's own location; the wheel does not ship them yet, and when it is absent the skill
step is refused by name (W7.5f).

## THE FLAGS THE PLAN GIVES NO DEFAULT, AND THE ONE IT ASKS FOR

`--hooks` and `--skills` have no default anywhere in the plan (D447), so an install that names
neither is refused with both named, before anything is planned. That includes 10:2453's own
example, `ow install --target auto` (D471). `--location` is asked for when stdin is a terminal --
10:1754 makes it the first question `ow uninstall` asks, and `ow install` is the other verb allowed
to ask (10:1620) -- and refused when it is not. `--check` and `--print-config` write nothing and
default to `global`, the column 18:2986 prints.

The generated parser publishes these as free strings, because a human-only row has no MCP input
schema for the generator to take `enum`s from, so the choices are checked here and a wrong one is
a usage error naming the right ones.

## EXIT 2 IS NOT A USAGE ERROR HERE

argparse exits 2 on a flag it does not know. 10:1484 makes a usage error exit 1, and 2 is *"not
found"* (10:1485). A parse failure is mapped to 1; `--help` stays 0.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.clock import SystemClock
from omniweave_core.host.subproc import Captured, run_captured

from omniweave.cli import ACTION_DEST, build_parser
from omniweave.install import skillcheck, skillset, verbs
from omniweave.install.engine import HostEnv
from omniweave.install.hookrules import launcher
from omniweave.install.types import HOOK_SETS, LOCATIONS, SKILL_SETS, InstallOptions

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from omniweave.install.types import HookSet, Location, SkillSet

__all__ = ["ROOTS", "host_env", "main"]

ROOTS: Final = frozenset({"install", "uninstall", "hooks", "skills"})
"""The roots this module dispatches; `__main__.DISPATCHED` includes them."""

_ARGPARSE_USAGE: Final = 2
_YES: Final = frozenset({"y", "yes"})


def _skills_root() -> Path | None:
    """`<repo>/skills`, beside the source tree this module is running from, or `None`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "skills"
        if (candidate / "omniweave").is_dir() and (parent / "packages").is_dir():
            return candidate
    return None


def host_env(env: Mapping[str, str], cwd: Path) -> HostEnv | str:
    """The `HostEnv` a run from `cwd` under `env` installs with, or why there is none."""
    user = env.get("HOME") or env.get("USERPROFILE")
    if not user:
        return "neither HOME nor USERPROFILE is set, so there is no home to install into"
    user_home = Path(user)
    home = Path(env["OMNIWEAVE_HOME"]) if env.get("OMNIWEAVE_HOME") else user_home / ".omniweave"
    return HostEnv(
        omniweave_home=home,
        user_home=user_home,
        clock=SystemClock(),
        pid=os.getpid(),
        launch=launcher(),
        project_root=cwd.resolve(),
        skills_root=_skills_root(),
        environ=dict(env),
    )


def _is_terminal(stream: TextIO) -> bool:
    """Whether `stream` is a terminal a person can answer on. D472.

    Measured on Windows: `isatty()` is `True` for the null device -- a child started with
    `stdin=DEVNULL`, or `< NUL` -- because `NUL` is a character device, which is all `isatty` asks.
    A detached `ow uninstall` then printed its location question and read an empty answer.
    `GetConsoleMode` succeeds only on a console handle, and returned false for `NUL` and for a pipe.
    """
    try:
        if not stream.isatty():
            return False
        fileno = stream.fileno()
    except (OSError, ValueError):
        return False
    if sys.platform != "win32":
        return True
    import ctypes  # noqa: PLC0415 -- Windows only, and only when a question may be asked
    import msvcrt  # noqa: PLC0415

    mode = ctypes.c_uint32()
    handle = ctypes.c_void_p(msvcrt.get_osfhandle(fileno))
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


class _Terminal:
    """The one place these verbs read a terminal: a yes/no, and step 1's location."""

    def __init__(self, stdin: TextIO, stdout: TextIO) -> None:
        self._in = stdin
        self._out = stdout

    @property
    def present(self) -> bool:
        return _is_terminal(self._in)

    def ask(self, question: str) -> str:
        self._out.write(f"{question} ")
        self._out.flush()
        return self._in.readline().strip().lower()

    def confirm(self, question: str) -> bool:
        return self.ask(f"{question} [y/N]") in _YES


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse `argv` (starting at the root word), run the verb, print its lines, return its exit."""
    out, err = stdout or sys.stdout, stderr or sys.stderr
    parsed = _parse(argv, out, err)
    if isinstance(parsed, int):
        return parsed
    built = host_env(env, cwd)
    if isinstance(built, str):
        err.write(f"ow: {built}\n")
        return verbs.USAGE
    terminal = _Terminal(stdin or sys.stdin, out)
    action = getattr(parsed, ACTION_DEST)
    if action == "hooks.check":
        outcome = _hooks_check(built, env)
    elif action == "install":
        outcome = _install(parsed, built, terminal)
    elif action.startswith("skills."):
        outcome = _skills(action, parsed, built, terminal)
    else:
        outcome = _uninstall(parsed, built, terminal)
    out.write(outcome.text())
    return outcome.exit_code


def _parse(argv: Sequence[str], out: TextIO, err: TextIO) -> argparse.Namespace | int:
    """The namespace, or the exit: argparse prints `--help` and its errors to the streams given."""
    parser = build_parser()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return parser.parse_args(list(argv))
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else verbs.USAGE
        return verbs.USAGE if code == _ARGPARSE_USAGE else code


def _refused(message: str) -> verbs.Outcome:
    return verbs.Outcome(verbs.USAGE, (f"ow: {message}",))


def _choice(value: str | None, flag: str, allowed: Sequence[str]) -> str | None:
    if value is None or value in allowed:
        return None
    return f"{flag} must be one of {', '.join(allowed)}; got {value!r}"


def _location(
    value: str | None, terminal: _Terminal, hint: Callable[[], str]
) -> Location | verbs.Outcome:
    if value is None and terminal.present:
        value = terminal.ask(f"{hint()}\n[global/local]") or None
    if value is None:
        return _refused("--location is required: global or local (there is no terminal to ask on)")
    wrong = _choice(value, "--location", LOCATIONS)
    if wrong:
        return _refused(wrong)
    return "global" if value == "global" else "local"


def _install(ns: argparse.Namespace, env: HostEnv, terminal: _Terminal) -> verbs.Outcome:
    early = _unwritten(ns, env, terminal)
    if early is not None:
        return early
    loc = _location(ns.location, terminal, lambda: verbs.location_hint(ns.target, env))
    if isinstance(loc, verbs.Outcome):
        return loc
    hooks: HookSet = ns.hooks
    skills: SkillSet = ns.skills
    opts = InstallOptions(hooks, skills, allow_cli=ns.allow_cli, dry_run=ns.dry_run)
    confirm = terminal.confirm if terminal.present else None
    return verbs.install(ns.target, loc, opts, env, yes=ns.yes, confirm=confirm)


def _unwritten(ns: argparse.Namespace, env: HostEnv, terminal: _Terminal) -> verbs.Outcome | None:
    """A wrong choice, `--check`, `--print-config`, or a missing `--hooks`/`--skills`; else None."""
    for value, flag, allowed in (
        (ns.hooks, "--hooks", tuple(HOOK_SETS)),
        (ns.skills, "--skills", SKILL_SETS),
    ):
        wrong = _choice(value, flag, allowed)
        if wrong:
            return _refused(wrong)
    if ns.check or ns.print_config:
        loc = _location(ns.location or "global", terminal, lambda: "")
        if isinstance(loc, verbs.Outcome):
            return loc
        if ns.print_config:
            return verbs.print_config(ns.print_config, loc, env)
        return verbs.check(ns.target, loc, env)
    missing = [
        flag for flag, value in (("--hooks", ns.hooks), ("--skills", ns.skills)) if not value
    ]
    if not missing:
        return None
    return _refused(
        f"{' and '.join(missing)} {'has' if len(missing) == 1 else 'have'} no default "
        "(the plan gives none, D447): name what to install, e.g. --hooks context --skills core"
    )


def _uninstall(ns: argparse.Namespace, env: HostEnv, terminal: _Terminal) -> verbs.Outcome:
    loc = _location(ns.location, terminal, lambda: verbs.location_hint(ns.target, env))
    if isinstance(loc, verbs.Outcome):
        return loc
    confirm = terminal.confirm if terminal.present else None
    return verbs.uninstall(ns.target, loc, env, yes=ns.yes, confirm=confirm, keep_cli=ns.keep_cli)


def _skills(
    action: str, ns: argparse.Namespace, env: HostEnv, terminal: _Terminal
) -> verbs.Outcome:
    """`ow skills install <name>...` writes without asking; `remove` asks, as uninstall does.

    `ls`, `verify`, `check` and `hash` read only (`omniweave.install.skillcheck`)."""
    readers = {
        "skills.ls": lambda: skillcheck.ls(env),
        "skills.verify": lambda: skillcheck.verify(env, every=ns.all),
        "skills.check": lambda: skillcheck.check(env, byte_diff=ns.check),
        "skills.hash": lambda: skillcheck.digests(env),
    }
    if action in readers:
        return readers[action]()
    names = [ns.name] if isinstance(ns.name, str) else list(ns.name)
    if action == "skills.install":
        return skillset.install(names, env)
    confirm = terminal.confirm if terminal.present else None
    return skillset.remove(names, env, yes=ns.yes, confirm=confirm)


def _runner(
    argv: Sequence[str], stdin: bytes, cwd: Path, env: Mapping[str, str], timeout: float
) -> Captured:
    return run_captured(argv, stdin=stdin, cwd=str(cwd), env=env, timeout_s=timeout)


def _hooks_check(env: HostEnv, environ: Mapping[str, str]) -> verbs.Outcome:
    """`ow hooks check`: the receipt's hooks, each run in a scratch project that is then removed."""
    with tempfile.TemporaryDirectory(prefix="ow-hooks-check-") as scratch:
        return verbs.hooks_check(env, environ=environ, runner=_runner, scratch=Path(scratch))
