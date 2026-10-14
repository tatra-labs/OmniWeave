"""Q-G25's marker check: every test lives in the directory its tier marker permits. **D834.**

13-quality.md section 13.1 (:1830): *"**tier placement.** Every test resides in the directory its
markers permit; the `tests/unit/` autouse fixture patches `socket.socket`, `subprocess.Popen`,
`time.time` and non-`tmp_path` `open()` to raise; a `@pytest.mark.golden` outside
`tests/golden/` fails (`OW-Q-014`)"*. Section 2.7 (:259-268) gives the table: `golden` is T2 in
`tests/golden/`, `conform` is T3 in `tests/conform/`, *"directory placement plus the marker
check"*. Section 15 (:2009) splits the gate: *"`A` + `G` | an autouse fixture makes the
violation raise; the marker check gates the rest"*. This file is the `G` half.

It reads every test file's AST and imports nothing from `omniweave`, as `tools/gate_budgets.py`
and `tools/gate_gate_rot.py` do not: a placement check has no library half to share.

## Rulings

1. **The test tree is every `test_*.py` and `conftest.py` under a `tests/` directory in
   `packages/`, and under `bench/`.** `bench/` is a tree of its own, not a tier directory, so a
   tier marker there is misplaced like anywhere else.
2. **A tier is a marker of `pyproject.toml`'s `markers` list with a directory of the same name:
   `golden` and `conform`.** A file using `pytest.mark.<tier>` anywhere, on the module, a class,
   a function or a `pytest.param`, must live under `tests/<tier>/` (`OW-Q-014`).
3. **A `test_*.py` under `tests/<tier>/` must mark its whole module**, as `pytestmark` at module
   level. Otherwise its unmarked tests run under `-m "not conform"`, in T1's job. That is a test
   in a directory its markers do not permit, the same finding seen from the other side.
4. **Two tiers on one file is a finding,** because no directory permits both.
5. **What this half cannot see is named, not passed.** A test that spawns or opens a socket
   with no marker is the autouse fixture's to catch, and that fixture is not built (D834). A
   marker applied by a conftest hook (`item.add_marker`) or imported as `from pytest import mark`
   is invisible to the AST, and the shipped tree uses neither.

## Exit codes

`0` every test is placed. `1` one is not, named with `OW-Q-014`, its file, the marker and the
directory. `2` the gate did not run: a test file that does not parse, or a bad argument.

Specified in 13-quality.md sections 2.7, 13.1, 13.2 and 15.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "TIERS",
    "Misplaced",
    "audit",
    "main",
    "marks",
    "tier_of",
]

REPO = Path(__file__).resolve().parent.parent

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

TIERS: Final = ("conform", "golden")
"""Ruling 2: each a marker and the directory it permits, 13-quality.md:264-267."""

CODE: Final = "OW-Q-014"
FIX: Final = "move the test, do not move the marker"


@dataclass(frozen=True, slots=True)
class Misplaced:
    """One test file in a directory its markers do not permit."""

    path: str
    marker: str
    reason: str

    def line(self) -> str:
        return f"  {CODE} {self.path}: {self.reason}"


def tier_of(path: str) -> str | None:
    """The tier directory a test file sits in: the part after its last `tests/`, if a tier."""
    parts = path.split("/")
    if "tests" not in parts:
        return None
    at = len(parts) - 1 - parts[::-1].index("tests")
    below = parts[at + 1 : -1]
    return below[0] if below and below[0] in TIERS else None


def _tier(node: ast.AST) -> str | None:
    """`pytest.mark.<tier>`, the attribute chain, or nothing."""
    if (
        isinstance(node, ast.Attribute)
        and node.attr in TIERS
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    ):
        return node.attr
    return None


def marks(source: str, path: str = "<test>") -> tuple[frozenset[str], frozenset[str]]:
    """`(module, anywhere)`: the tiers `pytestmark` sets at module level, and every tier used."""
    tree = ast.parse(source, filename=path)
    anywhere = frozenset(t for node in ast.walk(tree) if (t := _tier(node)) is not None)
    module: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            module.update(t for sub in ast.walk(value) if (t := _tier(sub)) is not None)
    return frozenset(module), anywhere


def audit(files: dict[str, str]) -> list[Misplaced]:
    """Rulings 2-4 over `relative path -> source`."""
    out = []
    for path, source in sorted(files.items()):
        module, anywhere = marks(source, path)
        here = tier_of(path)
        if len(anywhere) > 1:
            out.append(
                Misplaced(
                    path,
                    "+".join(sorted(anywhere)),
                    f"marked {' and '.join(sorted(anywhere))}; no directory permits both",
                )
            )
            continue
        for tier in sorted(anywhere - {here} if here else anywhere):
            out.append(Misplaced(path, tier, f"marked '{tier}' outside tests/{tier}/"))
        name = path.rsplit("/", 1)[-1]
        if here and name.startswith("test_") and here not in module:
            out.append(
                Misplaced(
                    path,
                    here,
                    f"in tests/{here}/ without a module-level pytestmark = pytest.mark.{here}",
                )
            )
    return out


def _tree(root: Path) -> dict[str, str]:
    """Ruling 1: the test tree, `relative path -> source`."""
    found = [
        *root.glob("packages/*/tests/**/*.py"),
        *root.glob("bench/**/*.py"),
    ]
    return {
        path.relative_to(root).as_posix(): path.read_bytes().decode("utf-8")
        for path in sorted(found)
        if path.name.startswith("test_") or path.name == "conftest.py"
    }


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """0 every test placed, 1 one is not, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_placement.py",
        description="Q-G25: every test lives in the directory its tier marker permits.",
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="DIR")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    try:
        files = _tree(args.root)
        found = audit(files)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        _say(f"Q-G25 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    placed = {tier: sum(1 for path in files if tier_of(path) == tier) for tier in TIERS}
    _say(
        f"Q-G25  {len(files)} file(s); "
        + ", ".join(f"tests/{tier}/ {placed[tier]}" for tier in TIERS)
    )
    _say("  not checked: a spawning or socket-opening test with no marker (the autouse fixture)")
    for one in found:
        _say(one.line())
    if found:
        _say(f"  fix: {FIX}")
    _say(f"Q-G25 {'FAIL' if found else 'ok'}  {len(found)} misplaced file(s)")
    return EXIT_FAIL if found else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
