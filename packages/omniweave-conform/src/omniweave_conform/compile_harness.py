"""The kit's `compile/1` harness: a compile card's golden, compiled for the twelve suites. D890.

04-driver-system.md section 8.2 holds every mandatory suite over a driver's runs, and a `compile/1`
driver had none: `idempotence`, `determinism`, `sandbox`, `cost` and `fuzz` each said *"no
compile/1 harness in this kit yet"*. This module is that harness. It is the `target` suite's
golden compile (`suites.target.suite.compile_golden`, D878's ruling 2), reached through a
`Subject`, so a suite compiles exactly what `ow conform --target` and OUT13's five-way run compile.

## Rulings

1. **`--fixtures` names a compile card's golden.** A parse card's fixtures are input files; a
   compile card's input is a golden fixture, a directory holding `il/` (and `cites.json`,
   `assets/`, `fonts/` as the target needs). `golden_of()` answers `None` for anything else, and a
   suite then says what it is missing rather than compiling nothing.
2. **The construct table is the card's own**, loaded beside it from `[compile] constructs` with
   the card's normalizers, as `out_determinism.compile_here()` loads it. A kit that passed its own
   table would test a different target.
3. **`part_digest` is what a compile run is compared by.** Every compile card declares
   `determinism = ["part", ...]`, and 09 section 6 makes `part` the floor every target promises
   and `byte` recorded, never promised. The byte digest is carried so a suite can report it.
4. **A separate module, not `harness.py`.** The target suite imports `harness`, so the compile
   half of the harness importing the target suite would be a cycle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.host.activate import normalizers
from omniweave_core.out.card import CompileCard
from omniweave_core.out.constructs import ConstructTable

from omniweave_conform.suites.target.suite import compile_golden

if TYPE_CHECKING:
    from omniweave_core.drivers.card import DriverCard

    from omniweave_conform.subject import Subject

__all__ = ["GOLDEN_IL", "CompileRun", "constructs_of", "golden_of", "run_compile"]

GOLDEN_IL: Final = "il"
"""Ruling 1: the directory a golden fixture keeps its IL in, and so what makes one."""


@dataclass(frozen=True, slots=True)
class CompileRun:
    """One compile of a golden: the artefact's bytes and its two digests (ruling 3)."""

    body: bytes
    part_digest: str

    @property
    def byte_digest(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def golden_of(subject: Subject) -> Path | None:
    """Ruling 1: the golden fixture `--fixtures` names, or `None` when it names none."""
    directory = subject.fixtures_dir
    if directory is None or not (directory / GOLDEN_IL).is_dir():
        return None
    return directory


def constructs_of(card: DriverCard) -> ConstructTable:
    """Ruling 2: the card's own construct table."""
    sibling = CompileCard.of(card)
    return ConstructTable.load(
        Path(str(card.source)).parent / sibling.constructs, normalizers(card)
    )


def run_compile(compiler: Any, card: DriverCard, golden: Path, workdir: Path) -> CompileRun:
    """The golden compiled once by `compiler`, in `workdir`, which must not exist yet."""
    compiled = compile_golden(compiler, card, constructs_of(card), golden, workdir=workdir)
    return CompileRun(compiled.body, compiled.part_digest)
