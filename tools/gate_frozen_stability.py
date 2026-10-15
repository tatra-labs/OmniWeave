"""Q-G4, frozen stability: `shape` byte-identical across pdfium builds and cells. **D849.**

16-roadmap.md:980: `uv run tools/gate_frozen_stability.py --pdfium-minors 2 --cells 9`.
13-quality.md:671: *"`Q-G4` asserts that `shape` is byte-identical across **two pdfium minors x
nine OS/Python cells**. That converts the open question about whole-point geometry quantization
from an assumption into a measurement, and it must close (`F31`) **before** the golden suite
freezes."* :1988 places it at *"the `golden` job x two pdfium minors, plus the nine-cell `test`
matrix"*. D848 committed the goldens this compares against.

One machine is one cell at one pdfium build, so the gate has two halves:
- `--emit DIR` writes this cell's `shape` Reductions, from a real ingest (`tools/ow_golden.py`),
  into `DIR/<cell>/` with a `cell.toml` naming it. Each CI cell runs this and uploads the
  directory.
- The comparison reads every `<cell>/` under `--artifacts` and holds each to the committed
  `fixtures/goldens/` shapes.

## Rulings

1. **A cell is `(os, python, pdfium)`.**
   - The OS is `sys.platform`, and Python is `major.minor`.
   - pdfium is `pypdfium2.version.PDFIUM_INFO` as printed, e.g. `153.0.7999.0`. Two different
     builds are two "minors": pdfium's version is a Chromium build number, and the plan's
     *"two pdfium minors"* means two builds the driver can run against.
2. **Each cell's shapes must equal the committed shapes, file for file and byte for byte.** The
   frozen value is the committed one. A cell that agrees with the others and not with the golden
   has drifted, and the golden is what a reviewer blessed. A missing or extra `shape` is a
   difference. `pages` and `outline` are tracked, not frozen, and are not read.
3. **Coverage is counted, and too little means the gate did not run.**
   - It needs at least `--pdfium-minors` distinct pdfium builds and `--cells` distinct
     `(os, python)` pairs.
   - With fewer, every cell can match and stability is still not measured, so the exit is 2,
     naming what is missing.
   - The plan's fallback (13-quality.md:673-677), *"nine cells at one pinned pdfium"*, is
     `--pdfium-minors 1`. Its other half, the pdfium axis as a `tracked` comparison, is not
     built.
4. **A `cell.toml` names `os`, `python` and `pdfium`, all non-empty.** A cell whose metadata does
   not read is refused, because an anonymous cell counts towards nothing.

## Exit codes

`0` enough cells, and every one matches. `1` a cell's shapes differ from the goldens. `2` the gate
did not run: too few cells or builds, an unreadable cell, or an ingest that failed under `--emit`.

Specified in 13-quality.md sections 5.1 and 14, and 16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.golden import read_tree  # noqa: E402

__all__ = [
    "ARTIFACTS",
    "CELL_FILE",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "Cell",
    "compare",
    "emit",
    "here",
    "main",
    "shapes",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2
CELL_FILE: Final = "cell.toml"
ARTIFACTS: Final = Path("artifacts") / "frozen-stability"
"""Where a CI job puts the cells it downloaded. Ignored by git; a local run has none."""


@dataclass(frozen=True, slots=True)
class Cell:
    """Ruling 1: one machine's `(os, python, pdfium)`, and the directory its shapes are in."""

    os: str
    python: str
    pdfium: str

    @property
    def name(self) -> str:
        return f"{self.os}-py{self.python}-pdfium{self.pdfium}"


def here() -> Cell:
    """This process's cell."""
    from pypdfium2.version import PDFIUM_INFO  # noqa: PLC0415 -- only a cell that emits pays

    return Cell(
        sys.platform, f"{sys.version_info.major}.{sys.version_info.minor}", str(PDFIUM_INFO)
    )


def shapes(tree: Mapping[str, str]) -> dict[str, str]:
    """Ruling 2: only the frozen kind."""
    return {path: text for path, text in tree.items() if path.endswith(".shape")}


def emit(target: Path, cell: Cell, tree: Mapping[str, str]) -> Path:
    """`--emit`: this cell's shapes and its `cell.toml` under `target/<cell>/`."""
    folder = target / cell.name
    folder.mkdir(parents=True, exist_ok=True)
    meta = "".join(
        f"{key} = {json.dumps(value)}\n"
        for key, value in (("os", cell.os), ("python", cell.python), ("pdfium", cell.pdfium))
    )
    (folder / CELL_FILE).write_bytes(meta.encode("utf-8"))
    for path, text in shapes(tree).items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(text.encode("utf-8"))
    return folder


def _read_cell(folder: Path) -> tuple[Cell, dict[str, str]]:
    """Ruling 4: a cell's metadata and its shapes, or `ValueError`."""
    try:
        meta = tomllib.loads((folder / CELL_FILE).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        message = f"{folder.name}: no readable {CELL_FILE} ({exc})"
        raise ValueError(message) from exc
    values = [meta.get(key) for key in ("os", "python", "pdfium")]
    if not all(isinstance(value, str) and value for value in values):
        message = f"{folder.name}: {CELL_FILE} needs a non-empty os, python and pdfium"
        raise ValueError(message)
    found = {
        path.relative_to(folder).as_posix(): path.read_bytes().decode("utf-8")
        for path in sorted(folder.rglob("*.shape"))
    }
    return Cell(*values), found  # type: ignore[arg-type]


def compare(golden: Mapping[str, str], cells: Mapping[Cell, Mapping[str, str]]) -> list[str]:
    """Ruling 2: each difference between a cell's shapes and the golden ones, as a line."""
    out = []
    for cell in sorted(cells, key=lambda c: c.name):
        found = cells[cell]
        for path in sorted(set(golden) | set(found)):
            if path not in found:
                out.append(f"{cell.name}: {path} is missing")
            elif path not in golden:
                out.append(f"{cell.name}: {path} is not a golden")
            elif found[path] != golden[path]:
                out.append(
                    f"{cell.name}: {path} differs at {_first_difference(golden[path], found[path])}"
                )
    return out


def _first_difference(want: str, got: str) -> str:
    for number, (a, b) in enumerate(zip(want.splitlines(), got.splitlines(), strict=False), 1):
        if a != b:
            return f"line {number}: {a!r} -> {b!r}"
    return "its length"


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _golden_tool() -> ModuleType:
    path = Path(__file__).resolve().parent / "ow_golden.py"
    spec = importlib.util.spec_from_file_location("_owgate_frozen_ow_golden", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- the file is in this tree
        message = f"cannot load {path}"
        raise OSError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(
    argv: list[str] | None = None,
    *,
    ingest: Callable[[Path], dict[str, str]] | None = None,
    cell: Callable[[], Cell] = here,
) -> int:
    """0 enough cells and all match, 1 a cell differs, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_frozen_stability.py",
        description="Q-G4: shape is byte-identical across pdfium builds and OS/Python cells.",
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="PATH")
    parser.add_argument("--artifacts", type=Path, default=None, metavar="DIR")
    parser.add_argument("--pdfium-minors", type=int, default=2, metavar="N")
    parser.add_argument("--cells", type=int, default=9, metavar="N")
    parser.add_argument("--emit", type=Path, default=None, metavar="DIR")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    root: Path = args.root
    if args.emit is not None:
        return _emit(root, args.emit, ingest, cell)
    return _compare(root, args)


def _emit(
    root: Path,
    target: Path,
    ingest: Callable[[Path], dict[str, str]] | None,
    cell: Callable[[], Cell],
) -> int:
    """`--emit`: one real ingest, this cell's shapes written, and nothing compared."""
    try:
        tree = (ingest or _golden_tool().ingest)(root)
    except (OSError, ValueError) as exc:
        _say(f"Q-G4 DID NOT RUN  the ingest: {exc}")
        return EXIT_NOT_RUN
    folder = emit(target, cell(), tree)
    _say(f"Q-G4  emitted {len(shapes(tree))} shape(s) to {folder}")
    return EXIT_CLEAN


def _compare(root: Path, args: argparse.Namespace) -> int:
    artifacts = args.artifacts if args.artifacts is not None else root / ARTIFACTS
    try:
        cells = dict(
            _read_cell(folder)
            for folder in (
                sorted(p for p in artifacts.iterdir() if p.is_dir()) if artifacts.is_dir() else []
            )
        )
    except ValueError as exc:
        _say(f"Q-G4 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN
    golden = shapes(read_tree(root))
    builds = {c.pdfium for c in cells}
    pairs = {(c.os, c.python) for c in cells}
    _say(
        f"Q-G4  {len(golden)} golden shape(s); {len(cells)} cell(s): {len(builds)} pdfium build(s)"
        f" of {args.pdfium_minors}, {len(pairs)} OS/Python cell(s) of {args.cells}"
    )
    differences = compare(golden, cells)
    for line in differences:
        _say(f"  FAIL  {line}")
    if differences:
        _say(f"Q-G4 FAIL  {len(differences)} difference(s)")
        return EXIT_FAIL
    if len(builds) < args.pdfium_minors or len(pairs) < args.cells:
        _say(
            "Q-G4 DID NOT RUN  stability is not measured below "
            f"{args.pdfium_minors} pdfium build(s) x {args.cells} cell(s); "
            + (
                "every cell read matches"
                if cells
                else f"no cell under {artifacts}; run --emit in each"
            )
        )
        return EXIT_NOT_RUN
    _say("Q-G4 ok  every cell matches the goldens")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
