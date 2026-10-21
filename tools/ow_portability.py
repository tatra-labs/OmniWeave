"""The portability suite's part half: each target's committed part digests, checked or written.

D903. `ow eval run --suite portability` holds this cell's compiled parts to
`eval/portability.toml` (`omniweave_conform.portability`, ruling 3), and this script is the file's
one writer. It compiles each register `[[target]]`'s golden once, as the suite does, and either
compares the members with the committed table or, under `--write`, writes the table.

D914: the register's `pptx` row also yields `pptx@golden40`, the 40-unit golden V10-10 names
(`fixtures/gen/gen_golden40.py`, generated into a scratch directory and compiled with the `pptx`
row's card and config), so each CI cell holds V10-10's deck to the committed table too.

Write it on the cell that blessed the goldens, `win32` (D886), and only when a target's output
moved on purpose: the diff is the review, and a table rewritten to match a drifted cell makes the
suite agree with the drift.

## Exit codes

`0` every member matches, or the table was written. `1` a member differs, is missing or is extra.
`2` the check did not run: no target in the register, an unreadable table or a compile that
failed.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.portability import (  # noqa: E402
    PARTS,
    differences,
    parts,
    read_parts,
    render_parts,
)
from omniweave_conform.roundtrip import Target, targets  # noqa: E402
from omniweave_core.errors import QualityError  # noqa: E402

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "main"]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2
GOLDEN40: Final = "pptx@golden40"
"""D914: V10-10's 40-unit golden, compiled with the register's `pptx` row."""


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """0 the parts match or were written, 1 they differ, 2 the check did not run."""
    parser = argparse.ArgumentParser(
        prog="ow_portability.py", description="Each target's part digests: check, or --write."
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="PATH")
    parser.add_argument("--write", action="store_true", help=f"write {PARTS} from this cell")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    root: Path = args.root
    register = tomllib.loads((root / "eval" / "gates.toml").read_text(encoding="utf-8"))
    rows = targets(register, root)
    if not rows:
        _say("portability DID NOT RUN  the register names no [[target]]")
        return EXIT_NOT_RUN
    try:
        with tempfile.TemporaryDirectory(prefix="ow-portability-golden40-") as scratch:
            found = {row.target: parts(row)[3] for row in (*rows, *_golden40(root, rows, scratch))}
    except (QualityError, RuntimeError, OSError, TypeError) as error:
        _say(f"portability DID NOT RUN  a compile failed: {type(error).__name__}: {error}")
        return EXIT_NOT_RUN
    if args.write:
        cell = f"{sys.platform}, Python {sys.version_info.major}.{sys.version_info.minor}"
        (root / PARTS).write_bytes(render_parts(found, cell=cell).encode("utf-8"))
        _say(f"portability  wrote {PARTS}: {len(found)} target(s), {cell}")
        return EXIT_CLEAN
    return _check(root, found)


def _golden40(root: Path, rows: tuple[Target, ...], scratch: str) -> tuple[Target, ...]:
    """D914: the 40-unit golden written under `scratch`, as a target of the `pptx` row's card."""
    pptx = next((row for row in rows if row.target == "pptx"), None)
    generator = root / "fixtures" / "gen" / "gen_golden40.py"
    if pptx is None or not generator.is_file():
        return ()
    spec = importlib.util.spec_from_file_location("_ow_portability_golden40", generator)
    if spec is None or spec.loader is None:
        return ()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.write(Path(scratch) / "pptx")
    return (replace(pptx, target=GOLDEN40, golden=Path(scratch) / "pptx"),)


def _check(root: Path, found: dict[str, dict[str, str]]) -> int:
    """Each target's members against the committed table."""
    try:
        frozen = read_parts(root)
    except QualityError as error:
        _say(f"portability DID NOT RUN  {error}")
        return EXIT_NOT_RUN
    failed = 0
    for target, members in found.items():
        held = differences(frozen.get(target, {}), members)
        _say(f"portability  {target}: {held.matched} of {held.compared} part(s) match")
        for line in held.differences:
            _say(f"  FAIL  {target}: {line}")
        failed += len(held.differences)
    if failed:
        _say(f"portability FAIL  {failed} difference(s)")
        return EXIT_FAIL
    _say("portability ok  every part matches")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
