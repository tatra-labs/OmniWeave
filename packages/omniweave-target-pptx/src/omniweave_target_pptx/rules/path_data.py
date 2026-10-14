"""`pptx.path@1`: path data is complete under SVG's command grammar, on a `<path>`. D790.

ppt-master's commands are `MmLlHhVvCcSsQqTtAaZz`. Data starts with M or m, each command takes
its arguments in whole segments, an arc's flags are 0 or 1 (and may be written without a
separator), and an arc's radii are never negative (`drawingml/paths.py:35-246`). Numbers may use
SVG's full grammar here: ppt-master only advises on their spelling in path data.

D796: `segments()` reads data `problem()` passes into its commands and their numbers, for
`lower.paths`. Both walk the data with `_segment()`, so the lowering reads exactly the grammar
the gate admits.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import said, values

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx

__all__ = ["SPEC", "path_data", "problem", "segments"]

RULE: Final = "pptx.path@1"
CODE: Final = "OW_TARGET_PATH_INVALID"
ARGUMENTS: Final = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}
_ARC_FLAGS: Final = (3, 4)
_ARC_RADII: Final = (0, 1)
_NUMBER: Final = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_SEPARATOR: Final = re.compile(r"[\s,]*")


def problem(d: str) -> str | None:
    """What makes `d` incomplete or ungrammatical, or `None`."""
    pos = _skip(d, 0)
    if pos == len(d):
        return "the path data is empty"
    if d[pos] not in "Mm":
        return "path data starts with M or m"
    while pos < len(d):
        command = d[pos]
        count = ARGUMENTS.get(command.lower())
        if count is None:
            return f"{d[pos : pos + 8]!r} at offset {pos} is no path command"
        pos = _skip(d, pos + 1)
        segments = 0
        while count and pos < len(d) and not d[pos].isalpha():
            pos, why, _ = _segment(d, pos, command, count)
            if why is not None:
                return why
            segments += 1
        if count and not segments:
            return f"{command} at offset {pos} has no numbers"
    return None


def segments(d: str) -> Iterator[tuple[str, Sequence[tuple[float, ...]]]]:
    """Each command in `d` with its segments' numbers, an arc's flags as 0.0 or 1.0. `d` is data
    `problem()` passes; `Z` has no segments."""
    pos = _skip(d, 0)
    while pos < len(d):
        command = d[pos]
        count = ARGUMENTS[command.lower()]
        pos = _skip(d, pos + 1)
        runs: list[tuple[float, ...]] = []
        while count and pos < len(d) and not d[pos].isalpha():
            pos, _, numbers = _segment(d, pos, command, count)
            runs.append(numbers)
        yield command, runs


def _segment(
    d: str, pos: int, command: str, count: int
) -> tuple[int, str | None, tuple[float, ...]]:
    """One segment of `command`'s arguments from `pos`: where it ends, why it cannot, and its
    numbers."""
    arc = command in "Aa"
    numbers: list[float] = []
    for k in range(count):
        if arc and k in _ARC_FLAGS:
            if d[pos : pos + 1] not in ("0", "1"):
                return pos, f"an arc flag is 0 or 1, at offset {pos}", ()
            numbers.append(float(d[pos]))
            pos = _skip(d, pos + 1)
            continue
        m = _NUMBER.match(d, pos)
        if m is None:
            return pos, f"{command} takes {count} numbers a segment; offset {pos} has none", ()
        if arc and k in _ARC_RADII and m[0].startswith("-"):
            return pos, f"an arc radius is never negative, {m[0]} at offset {pos}", ()
        numbers.append(float(m[0]))
        pos = _skip(d, m.end())
    return pos, None, tuple(numbers)


def path_data(ctx: RuleCtx) -> Iterator[Finding]:
    """Each `d` grammatical, and only on a `<path>`."""
    if ctx.doc is None or ctx.unit is None:
        return
    for v in values(ctx, ("d",)):
        if v.node.tag != "svg|path":
            yield said(ctx, v, rule=RULE, code=CODE, why="d belongs to <path>")
            continue
        why = problem(v.settled)
        if why is not None:
            yield said(ctx, v, rule=RULE, code=CODE, why=why)


def _skip(d: str, pos: int) -> int:
    m = _SEPARATOR.match(d, pos)
    return pos if m is None else m.end()


SPEC: Final = RuleSpec(RULE, 44, "unit", frozenset({CODE}), path_data)
