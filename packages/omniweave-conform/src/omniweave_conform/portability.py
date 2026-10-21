"""The portability suite: the same inputs give identical results on every cell. **D903.**

13-quality.md:238 names `portability` among the seven suites, and :2056 says what its failing
means, *"`portability`/`perf` failing means the runner changed rather than the model"*, but
nothing says what it measures, so D872 reported it `unknown`. A user ruling of 2026-10-19 (#7.4)
defines it: **the same inputs give identical results across the OS/Python cells.** One machine is
one cell, so a run holds this cell's results to committed frozen values, and a cell that matches
them matches every other cell that does.

## Rulings

1. **Two halves, each a committed input and a frozen value.**
   - `shape`: the Tier-A fixtures ingested by a real `ow add` and reduced (`golden.ingest()`), each
     `.shape` Reduction held to `fixtures/goldens/` byte for byte. That is Q-G4's frozen kind
     (13:671). `pages` and `outline` are tracked, not frozen, and are not read: CI's first Linux
     run moved their digests and nothing else (D886).
   - `part`: each register `[[target]]`'s golden compiled once in this process
     (`out_determinism.compile_here()`), each member's sha256 held to `eval/portability.toml`.
     `part` is the determinism every target promises (13:1568). `byte` is promised only under
     one pinned resolution, so it is not read.
2. **The value is the matched share.** The denominator is the union of the committed and the
   produced names, so a missing or extra file or member is a difference, as Q-G4's ruling 2 has
   it, and each difference is named.
3. **`eval/portability.toml` is written by `tools/ow_portability.py --write`**, on the cell that
   blessed the goldens (`win32`, D886), and only read here. A target with no row in it is refused
   rather than measured: an empty table agrees with nothing.
4. **The cells are CI's.** Every cell of the matrix running this suite against the same committed
   values is the cross-cell comparison. Before the matrix runs it, two cells were measured by
   hand (win32 with Python 3.12, linux with 3.13, one pdfium build): every shape and every part
   matched (D903).

Specified in 13-quality.md sections 2.5, 5.1 and 13.3.
"""

from __future__ import annotations

import json
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import QualityError
from omniweave_core.host.activate import code_fingerprint

from omniweave_conform import golden
from omniweave_conform.out_determinism import compile_here
from omniweave_conform.subject import Subject

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_conform.roundtrip import Target

__all__ = [
    "METRIC",
    "PARTS",
    "SHAPE",
    "Held",
    "differences",
    "parts",
    "read_parts",
    "render_parts",
    "shapes",
]

METRIC: Final = "cell_identity"
"""The register's hard row for this suite."""
PARTS: Final = "eval/portability.toml"
"""Ruling 3: each target's committed part digests, relative to the checkout's root."""
SHAPE: Final = "shape"
"""Ruling 1: the shape half's slice. Each part half's slice is its target's name."""
_WRITE: Final = "uv run tools/ow_portability.py --write  # on the cell that blessed the goldens"


@dataclass(frozen=True, slots=True)
class Held:
    """One half held to its frozen values: what was compared, and what differed (ruling 2)."""

    compared: int
    differences: tuple[str, ...]

    @property
    def matched(self) -> int:
        return self.compared - len(self.differences)


def differences(frozen: Mapping[str, str], found: Mapping[str, str]) -> Held:
    """Ruling 2: every name in either side, and each one missing, extra or different."""
    names = sorted(frozen.keys() | found.keys())
    out = []
    for name in names:
        if name not in found:
            out.append(f"{name}: missing")
        elif name not in frozen:
            out.append(f"{name}: not frozen")
        elif found[name] != frozen[name]:
            out.append(f"{name}: differs")
    return Held(len(names), tuple(out))


def shapes(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Ruling 1's shape half: the committed `.shape` Reductions, then this cell's, by path."""
    frozen = _shape_only(golden.read_tree(root))
    return frozen, _shape_only(golden.ingest(root))


def parts(target: Target) -> tuple[str, str, str, dict[str, str]]:
    """Ruling 1's part half: the compile driver, its version, its fingerprint, each member's sha."""
    with tempfile.TemporaryDirectory(prefix="ow-eval-portability-") as scratch:
        work = Path(scratch)
        subject = Subject.of(target.card, workdir=work / "subject")
        fingerprint = code_fingerprint(subject.source_files())
        done = compile_here(target, work / "compile", label="portability")
        card = subject.card
    return card.identity.id, card.identity.version, fingerprint, dict(done.members)


def read_parts(root: Path) -> dict[str, dict[str, str]]:
    """Ruling 3: `eval/portability.toml`'s table, `{target: {member: sha256}}`, or a refusal."""
    path = root / PARTS
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise QualityError(f"no readable {PARTS} ({error})", fix=_WRITE) from error
    out: dict[str, dict[str, str]] = {}
    for row in table.get("target", []):
        members: Any = row.get("parts")
        if not isinstance(row.get("target"), str) or not isinstance(members, dict) or not members:
            raise QualityError(f"{PARTS}: a [[target]] needs a target and its parts", fix=_WRITE)
        out[row["target"]] = {str(k): str(v) for k, v in members.items()}
    return out


def render_parts(table: Mapping[str, Mapping[str, str]], *, cell: str) -> str:
    """Ruling 3: the file `tools/ow_portability.py --write` commits, one row per target."""
    lines = [
        "# eval/portability.toml -- written by tools/ow_portability.py --write. Do not edit.",
        "#",
        "# The portability suite's part half (D903): each register [[target]]'s golden compiled",
        "# once, each member's sha256. Every cell must reproduce them; `byte` is not read.",
        f"# Written on {cell}.",
    ]
    for target in sorted(table):
        lines += ["", "[[target]]", f"target = {json.dumps(target)}", "", "[target.parts]"]
        lines += [
            f"{json.dumps(name)} = {json.dumps(sha)}" for name, sha in sorted(table[target].items())
        ]
    return "\n".join(lines) + "\n"


def _shape_only(tree: Mapping[str, str]) -> dict[str, str]:
    return {path: text for path, text in tree.items() if path.endswith(".shape")}
