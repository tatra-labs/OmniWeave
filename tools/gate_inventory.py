"""Q-G24, test inventory: the inventory against the collection, and no silent decrease. **D845.**

13-quality.md:1829: *"`eval/inventory.toml` -- per-area unit and property counts -- byte-matches
`pytest --collect-only -q` on the ubuntu/3.11 cell, and a net decrease in any area fails without a
`BLESS.log` row (`OW-Q-013`)"*. What it stops: *"a `skipif`, a broken marker expression or a
deleted `conftest.py` silently removing 300 tests. Nothing else in the framework measures test
*count*"*. :78 adds that the count in the plan and the count in the repository *"cannot drift"*.
This file collects, renders the inventory, byte-diffs it, and holds any decrease to a bless,
following the standing pattern (ledger D25). D846 moved the counting into
`omniweave_conform.inventory`, which `ow eval bless --inventory` shares, and the judging stayed
here.

## Rulings

1. **An area is a distribution and the test directory under its `tests/`**, such as
   `omniweave-core/unit`. A test file directly in `tests/` is in the area `<dist>/tests`. The plan
   writes *"per-area"* and names no area, and this is the coarsest grain at which a deleted
   `conftest.py` still shows. A `conftest.py` governs a directory, so a directory is what loses its
   tests.
2. **A unit is a collected test item, and a property is one that hypothesis drives.** The latter
   is read off the item's function with `hypothesis.is_hypothesis_test`. Collection is everything
   `pytest --collect-only` collects from `testpaths`, every tier included: collecting runs no test,
   and a tier left out is a tier that could shrink unseen.
3. **Collection runs in a fresh interpreter**, with a plugin written into a scratch directory that
   records each item. The gate's own process never imports a test module. A collection that does
   not exit 0 is a finding, with its tail: a broken import is the decrease this gate exists for.
4. **`eval/inventory.toml` is one `[[area]]` per area, sorted by name, holding `tests` and
   `properties`.** It is LF with no timestamps and no total: a total is the sum of the rows, and
   a second copy of a sum is a number that drifts. The gate byte-diffs it, and `--write` writes it.
5. **A decrease is judged against the merge base with `--base`.** Merges are squash-only, so the
   change that lands is the diff from that base to `--head`, as `tools/gate_bless.py` rules (D841).
   Any area whose `tests` or `properties` fell, or that vanished, fails, unless the landed change
   adds a `BLESS.log` row whose glob matches `eval/inventory.toml`. On the base branch itself the
   last commit is judged against its parent.
6. **What the plan pins and this gate measures differ by machine.** The plan pins the inventory to
   the ubuntu/3.11 cell. No test module skips at module level, since each `importorskip` sits
   inside a test, so collection should not vary by platform. It is measured here, though, not
   proven: the gate counts on the machine it runs on.

## Exit codes

`0` the inventory matches the collection and nothing decreased unblessed. `1` a finding, named
with its area and the fix. `2` the gate did not run: no git for the decrease clause, or an argument
it cannot read.

Specified in 13-quality.md sections 2.1, 13.1 and 14, and 16-roadmap.md W10.11.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform import inventory  # noqa: E402
from omniweave_conform.bless import append_only, covers  # noqa: E402
from omniweave_conform.inventory import (  # noqa: E402
    HEADER,
    INVENTORY,
    PLUGIN,
    Count,
    area_of,
    areas,
    decreases,
    parse,
    render,
)
from omniweave_core.errors import QualityError  # noqa: E402

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "HEADER",
    "INVENTORY",
    "PLUGIN",
    "Count",
    "area_of",
    "areas",
    "collect",
    "decreases",
    "main",
    "parse",
    "render",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2
_BLESS_FIX: Final = "OMNIWEAVE_BLESS=1 ow eval bless --inventory --reason '<why the tests went>'"


def collect(root: Path) -> tuple[int, list[tuple[str, bool]], list[str]]:
    """Ruling 3, through `omniweave_conform.inventory.collect()`, under this process's environment.

    A child that never reported a status, because it timed out or never started, is exit `-1`,
    which is not 0 and so a finding.
    """
    done = inventory.collect(root, os.environ)
    return (-1 if done.code is None else done.code), list(done.rows), list(done.tail)


def _bless_module() -> ModuleType:
    """`tools/gate_bless.py`, by path, for ruling 5's landed change (D841's ruling 1)."""
    path = Path(__file__).resolve().parent / "gate_bless.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_bless_inventory", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- the file is in this tree
        message = f"cannot load {path}"
        raise OSError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def landed_inventory(root: Path, base: str, head: str) -> tuple[str, str, str]:
    """Ruling 5: `(inventory at the base end, BLESS.log at the base end, BLESS.log at head)`."""
    bless = _bless_module()
    try:
        old, new = bless.landed(root, base, head)
        return (
            bless.file_at(root, old, INVENTORY),
            bless.file_at(root, old, bless.LOG),
            bless.file_at(root, new, bless.LOG),
        )
    except bless.GitError as exc:
        raise OSError(str(exc)) from exc


def _unblessed(fell: Sequence[str], old_log: str, new_log: str) -> list[str]:
    """Ruling 5: each decrease, unless the landed change adds a row blessing the inventory."""
    if not fell:
        return []
    try:
        added = append_only(old_log, new_log)
    except QualityError as exc:
        return [f"BLESS.log: {exc}"]
    if not covers([INVENTORY], added).unblessed:
        return []
    return [f"OW-Q-013 decrease {line}; {_BLESS_FIX}" for line in fell]


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(
    argv: list[str] | None = None,
    *,
    collector: Callable[[Path], tuple[int, list[tuple[str, bool]], list[str]]] = collect,
    history: Callable[[Path, str, str], tuple[str, str, str]] = landed_inventory,
) -> int:
    """0 clean, 1 a finding, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_inventory.py",
        description="Q-G24: the inventory matches the collection, and nothing fell unblessed.",
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="PATH")
    parser.add_argument("--base", default="origin/master", metavar="REF")
    parser.add_argument("--head", default="HEAD", metavar="REF")
    parser.add_argument("--write", action="store_true", help=f"regenerate {INVENTORY}")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    root: Path = args.root
    code, rows, tail = collector(root)
    counted = areas(rows)
    findings: list[str] = []
    if code != 0:
        findings.append(f"collection exited {code}; a module that fails to import loses its tests")
    text = render(counted)
    target = root / INVENTORY
    if args.write and code == 0:
        target.write_bytes(text.encode("utf-8"))
    elif not target.is_file() or target.read_bytes() != text.encode("utf-8"):
        state = "differs from the collection" if target.is_file() else "is missing"
        findings.append(f"{INVENTORY} {state}; run `uv run tools/gate_inventory.py --write`")
    try:
        before_text, old_log, new_log = history(root, args.base, args.head)
        before = parse(before_text) if before_text else {}
    except (OSError, ValueError) as exc:
        _say(f"Q-G24 DID NOT RUN  the decrease clause: {exc}")
        return EXIT_NOT_RUN
    fell = decreases(before, counted)
    findings += _unblessed(fell, old_log, new_log)
    total = sum(count.tests for count in counted.values())
    properties = sum(count.properties for count in counted.values())
    _say(f"Q-G24  {total} test(s), {properties} propert(ies), {len(counted)} area(s)")
    for line in fell:
        _say(f"  fell  {line}")
    for finding in findings:
        _say(f"  FAIL  {finding}")
    if code != 0:
        for line in tail:
            _say(f"  | {line}")
    if args.write and code == 0:
        _say(f"  wrote {INVENTORY}")
    _say(f"Q-G24 {'FAIL' if findings else 'ok'}  {len(findings)} finding(s)")
    return EXIT_FAIL if findings else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
