"""`json-hook-rules`: the hook command, whose rule is ours, and converging a settings file's rules.

10:1683-1698 is the specification, in three parts. **The command** is `shutil.which("ow")`
resolved absolute at install time, forward-slashed on Windows, and quoted when it contains a space.
**Ownership** of an existing rule is decided by the `ow` subcommand embedded in the command string,
parsed across four spellings. **Convergence** is rule-level and conditional: a rule that is entirely
omniweave's converges its command and its matcher, and a shared rule converges the command only.
10:1654 adds the fifth primitive: prior-version artefacts are pruned *"at the individual-command
level, **only if something matched**"*. This module is all of it, over a parsed document; the
reading and writing is `modes.py`'s.

## THE COMMAND THE PLAN SPECIFIES CANNOT BE BUILT HERE

`shutil.which("ow")` is `None` on this machine, measured: `packages/omniweave/pyproject.toml`
declares no console script, so there is no `ow` anywhere to resolve (W7.4i shipped `python -m
omniweave` and no entry point). An install that followed 10:1683 would have no command to write.
The launcher is `which("ow")` when that is absolute and otherwise the interpreter that is running,
`<sys.executable> -m omniweave` -- the form `posttool.command()` already falls back to (D425), and
the one form that works today. **So there are five spellings, not four**: the interpreter form
must be recognised as ours, or the first upgrade after a console script ships would append a
second set of hooks beside the first instead of converging them. D456.

## "QUOTED WHEN IT CONTAINS A SPACE" IS NOT THE WHOLE CONDITION

This machine's interpreter is `E:/AI/_Project/Project (tatra-labs)/omniweave/.venv/Scripts/
python.exe`, which has a space -- and parentheses. Under `/bin/sh` an unquoted `(` is a syntax
error even with no space beside it, so `C:/tools(x86)/ow.exe` breaks exactly as a space would. The
head is double-quoted when it contains anything outside a plain-path alphabet. Double quotes and not
single, because they mean the same to `cmd.exe` and to a POSIX shell, and a host whose shell is not
recorded (D439) may be either. A head containing `"`, `$` or a backtick cannot be quoted safely in
both at once, and is refused. D457.

## WHAT CONVERGENCE DOES WITH WHAT IT FINDS

Per event, the first hook of ours is converged to the desired command, and any further hook of ours
under that event -- a duplicate, an old spelling -- is pruned. So is every hook of ours under an
event this install does not want (a `--hooks steer` install followed by `--hooks context` drops
the `PreToolUse` hook). A rule left with no hooks is removed, and an event left with no rules is
removed, but only where omniweave's pruning emptied them. Nothing is touched in a rule that holds
no hook of ours, which is 10:1654's *"only if something matched"* taken literally: a file with
nothing of ours in it comes back from `converge()` equal, and `write_json`'s deep-equality test
then leaves its bytes alone.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave.hooks.envelope import EVENTS
from omniweave.hooks.main import HOOK_WORD, event_of, kebab

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "HOOKS_KEY",
    "Converged",
    "Desired",
    "converge",
    "desired",
    "hook_command",
    "launcher",
    "owned_event",
    "owned_pairs",
    "strip",
    "tokens",
]

# The settings key Claude Code reads hook rules from (10:1670's row names only the file).
HOOKS_KEY: Final = "hooks"
_TYPE: Final = "command"
_MODULE: Final = "omniweave"
_PLAIN: Final = re.compile(r"[A-Za-z0-9_./:@%+=,~-]+")
_UNQUOTABLE: Final = frozenset('"$`')
_PYTHON: Final = re.compile(r"(python|pythonw)(\d+(\.\d+)*)?|py")
_WINDOWS: Final = sys.platform == "win32"


# ---------------------------------------------------------------------------------------------
# The command. 10:1683-1689, D456, D457.
# ---------------------------------------------------------------------------------------------


def launcher(
    *,
    which: Callable[[str], str | None] = shutil.which,
    executable: str = sys.executable,
) -> tuple[str, ...] | str:
    """The argv prefix a hook command starts with, or why there is none. D456."""
    found = which("ow")
    if found and Path(found).is_absolute():
        return (found,)
    if executable and Path(executable).is_absolute():
        return (executable, "-m", _MODULE)
    return "no absolute `ow` on PATH and no absolute interpreter to fall back to"


def _head(path: str, *, windows: bool) -> str:
    spelled = path.replace("\\", "/") if windows else path
    if _PLAIN.fullmatch(spelled):
        return spelled
    return f'"{spelled}"'


def hook_command(launch: Sequence[str], event: str, *, windows: bool = _WINDOWS) -> str:
    """`<launcher> hook <word>` for one event; `ValueError` for a head no quoting can protect."""
    if not launch:
        raise ValueError("an empty launcher")
    if _UNQUOTABLE & set(launch[0]):
        raise ValueError(
            f"{launch[0]!r} holds a character no shell quoting protects in both shells"
        )
    return " ".join((_head(launch[0], windows=windows), *launch[1:], HOOK_WORD, kebab(event)))


# ---------------------------------------------------------------------------------------------
# Ownership. 10:1690-1693, five spellings.
# ---------------------------------------------------------------------------------------------


def tokens(command: str) -> tuple[str, ...]:
    """Whitespace-separated words, a quoted run being one word -- with **no** escape processing.

    Not `shlex`: a backslash is a path separator in the third spelling (`C:\\Python\\Scripts\\ow.exe
    hook ...` after a JSON round-trip), and a POSIX split would eat it, which is the very bug the
    command is written to avoid. An unterminated quote runs to the end of the string.
    """
    words: list[str] = []
    index, size = 0, len(command)
    while index < size:
        if command[index].isspace():
            index += 1
            continue
        quote = command[index] if command[index] in {'"', "'"} else ""
        if quote:
            end = command.find(quote, index + 1)
            end = size if end < 0 else end
            words.append(command[index + 1 : end])
            index = end + 1
            continue
        end = index
        while end < size and not command[end].isspace():
            end += 1
        words.append(command[index:end])
        index = end
    return tuple(words)


def _base(word: str) -> str:
    name = re.split(r"[\\/]", word)[-1].lower()
    return name.removesuffix(".exe")


def owned_event(command: object) -> str | None:
    """The event an omniweave hook command runs; `""` if ours with an unknown word; else `None`.

    Ours means `ow hook <word>` in any of 10:1690's four spellings -- bare, absolute with `/`,
    absolute with `\\`, quoted -- or `<python> -m omniweave hook <word>` (D456).
    """
    if not isinstance(command, str):
        return None
    words = tokens(command)
    if not words:
        return None
    base = _base(words[0])
    if base == "ow":
        rest = words[1:]
    elif _PYTHON.fullmatch(base) and words[1:3] == ("-m", _MODULE):
        rest = words[3:]
    else:
        return None
    if not rest or rest[0] != HOOK_WORD:
        return None
    return event_of(rest[1]) if len(rest) > 1 else ""


# ---------------------------------------------------------------------------------------------
# Convergence. 10:1654, 10:1695-1698.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Desired:
    """One event's rule as omniweave wants it: the matcher (`""` for none) and the command."""

    event: str
    matcher: str
    command: str


def desired(
    events: Sequence[str], launch: Sequence[str], *, windows: bool = _WINDOWS
) -> tuple[Desired, ...]:
    """The rules for `events`, in 10:1849's table order, matchers from `EVENTS`."""
    wanted = set(events)
    return tuple(
        Desired(name, spec.matcher, hook_command(launch, name, windows=windows))
        for name, spec in EVENTS.items()
        if name in wanted
    )


@dataclass(slots=True)
class Converged:
    """What `converge` did to a document's `hooks` object."""

    placed: list[str] = field(default_factory=list)
    appended: list[str] = field(default_factory=list)
    converged: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    matchers: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    refusal: str = ""

    def matched(self) -> bool:
        return bool(self.converged or self.pruned)


def converge(document: dict[str, Any], wanted: Sequence[Desired]) -> Converged:
    """Bring `document["hooks"]` to `wanted`, in place. Nothing of anyone else's is touched."""
    result = Converged()
    hooks = document.get(HOOKS_KEY)
    if hooks is None:
        if not wanted:
            return result
        hooks = document[HOOKS_KEY] = {}
        result.created.append(HOOKS_KEY)
    if not isinstance(hooks, dict):
        result.refusal = (
            f"{HOOKS_KEY} is {type(hooks).__name__}, not an object; not writing into it"
        )
        return result
    by_event = {one.event: one for one in wanted}
    for event, rules in list(hooks.items()):
        if isinstance(rules, list):
            _converge_event(hooks, event, rules, by_event.get(event), result)
    for one in wanted:
        if one.event in result.placed:
            continue
        rules = hooks.get(one.event)
        if rules is None:
            rules = hooks[one.event] = []
            result.created.append(f"{HOOKS_KEY}.{one.event}")
        if not isinstance(rules, list):
            result.refusal = f"{HOOKS_KEY}.{one.event} is not an array; not writing into it"
            return result
        rules.append(_rule(one))
        result.placed.append(one.event)
        result.appended.append(one.event)
    return result


def _is_ours(entry: object) -> bool:
    return isinstance(entry, dict) and owned_event(entry.get("command")) is not None


def _rule(one: Desired) -> dict[str, Any]:
    rule: dict[str, Any] = {"matcher": one.matcher} if one.matcher else {}
    rule["hooks"] = [{"type": _TYPE, "command": one.command}]
    return rule


def _converge_event(
    hooks: dict[str, Any],
    event: str,
    rules: list[Any],
    want: Desired | None,
    result: Converged,
    *,
    drop_emptied: bool = True,
) -> None:
    emptied = False
    for rule in list(rules):
        entries = rule.get("hooks") if isinstance(rule, dict) else None
        if not isinstance(entries, list):
            continue
        mine = {id(entry) for entry in entries if _is_ours(entry)}
        if not mine:
            continue
        entirely = len(mine) == len(entries)
        kept: list[Any] = []
        placed_here = False
        for entry in entries:
            if id(entry) not in mine:
                kept.append(entry)
            elif want is not None and event not in result.placed:
                if entry.get("command") != want.command or entry.get("type") != _TYPE:
                    result.converged.append(event)
                kept.append({**entry, "type": _TYPE, "command": want.command})
                result.placed.append(event)
                placed_here = True
            else:
                result.pruned.append(event)
        rule["hooks"] = kept
        if placed_here and entirely and want is not None:
            _converge_matcher(rule, want, event, result)
        if not kept:
            rules.remove(rule)
            emptied = True
    if emptied and not rules and drop_emptied:
        del hooks[event]


def _converge_matcher(rule: dict[str, Any], want: Desired, event: str, result: Converged) -> None:
    """10:1695: only a rule that is entirely omniweave's has its matcher converged."""
    current = rule.get("matcher", "")
    if current == want.matcher:
        return
    if want.matcher:
        rule["matcher"] = want.matcher
    else:
        rule.pop("matcher", None)
    result.matchers.append(event)


def strip(document: dict[str, Any], *, drop_emptied: bool) -> list[str]:
    """Remove every hook of ours from `document["hooks"]`; the events touched. Uninstall's half.

    `drop_emptied` removes an event list the removal left empty. An uninstall with a row passes
    `False` and prunes only the lists the row says install created: a user's own `"SessionStart":
    []` was there before and must be there after.
    """
    hooks = document.get(HOOKS_KEY)
    if not isinstance(hooks, dict):
        return []
    result = Converged()
    for event, rules in list(hooks.items()):
        if isinstance(rules, list):
            _converge_event(hooks, event, rules, None, result, drop_emptied=drop_emptied)
    return result.pruned


def owned_pairs(document: Mapping[str, Any]) -> list[list[str]]:
    """`[event, command]` for every hook of ours, in file order: the row's owned digest input."""
    hooks = document.get(HOOKS_KEY)
    pairs: list[list[str]] = []
    if not isinstance(hooks, dict):
        return pairs
    for event, rules in hooks.items():
        for rule in rules if isinstance(rules, list) else ():
            entries = rule.get("hooks") if isinstance(rule, dict) else None
            for entry in entries if isinstance(entries, list) else ():
                if _is_ours(entry):
                    pairs.append([event, entry["command"]])
    return pairs
