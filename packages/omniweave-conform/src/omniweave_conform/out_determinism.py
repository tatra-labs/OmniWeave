"""OUT13 determinism: each target's golden compiled five ways, diffed member by member. **D878.**

09-generation.md:1597: *"`omniweave-conform`'s `determinism` suite compiles the 40-unit golden
bundle twice in one process and once in a fresh process, and diffs `part_digest` **member by
member** — a whole-digest comparison tells you it broke, a member diff tells you which part."*
13-quality.md:1568 gives OUT13's obligation: *"3 runs x `PYTHONHASHSEED ∈ {0, 1, random}`, two temp
dirs, different cwd and `TMPDIR`, `SOURCE_DATE_EPOCH=0`; `part` is promised, `byte` is asserted
only under one pinned resolution"*. The target suite's R1 compiles twice in one process and
compares whole digests; this module is the rest.

## Rulings

1. **Five compiles, one golden.** Two in this process, in two scratch directories, and three in
   fresh processes, one per `PYTHONHASHSEED` in `0`, `1` and `random`. Each child runs with
   `SOURCE_DATE_EPOCH=0` and its own working directory and `TMPDIR` (`TMP` and `TEMP` too, which
   Windows reads), so no two compiles share a path. A child is `python -c` calling this module's
   `main()`, spawned through `host.subproc.run_captured()`, the one sanctioned spawn, and it
   prints one JSON object. There is no `__main__` block: library code may not call `sys.exit()`
   (G8), and an exception in the child is its non-zero exit.
2. **A target is a register `[[target]]` row** (`roundtrip.targets()`), its compiler built from
   the card with the row's `config`, as the roundtrip suite builds it. Each compile is
   `suites.target.suite.compile_golden()`, which is R1's compile, so the bytes are the ones R1
   compares.
3. **The members are the package's parts, each by sha256.** An OPC artefact is read by
   `opc.check_package()`, which also proves it is a well-formed package. Anything else is one
   member, `artefact`, its whole bytes. The comparison is always against the first in-process
   compile, and a disagreement names every member that differs, is missing or is extra.
4. **`part` is promised and always judged. `byte` is judged only when the card declares it.**
   Every compile here shares one resolution, so a card that declares `byte` must hold it across
   all five. For a card that does not, the byte agreement is printed, never judged.
5. **A compile that cannot run is not a disagreement.** A child that exits non-zero, prints no
   JSON, or a golden whose gate does not pass, raises `QualityError` with the cause, and the
   caller reports that the harness did not run.
6. **This is one machine, one cell.** The nine OS/Python cells of V10-10 and the two pdfium
   minors are CI's, which is off. What this proves is the in-cell half: hash seed, paths and the
   process boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import QualityError
from omniweave_core.host.activate import normalizers
from omniweave_core.host.subproc import run_captured
from omniweave_core.out.card import CompileCard
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.opc import check_package

from omniweave_conform.roundtrip import Target, targets
from omniweave_conform.subject import Subject
from omniweave_conform.suites.target.suite import compile_golden

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "SEEDS",
    "Compile",
    "Judged",
    "compile_fresh",
    "compile_here",
    "judge",
    "main",
    "member_diff",
    "members",
    "run",
]

SEEDS: Final = ("0", "1", "random")
"""Ruling 1: 13:1568's three `PYTHONHASHSEED` values, one fresh process each."""
WHOLE: Final = "artefact"
"""Ruling 3: the one member of an artefact that is not a package."""
CHILD_TIMEOUT_S: Final = 600.0
CHILD: Final = "import sys; from omniweave_conform.out_determinism import main; main(sys.argv[1:])"
"""Ruling 1: the child's program; its arguments follow it in `argv`."""
_FIX: Final = "ow conform --target <target>  # the target suite, every law"


@dataclass(frozen=True, slots=True)
class Compile:
    """One compile of a golden: where it ran, its digests, and each member's sha256."""

    label: str
    part_digest: str
    byte_digest: str
    members: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Judged:
    """Rulings 3 and 4 over one target's compiles."""

    target: str
    declared: tuple[str, ...]
    compiles: tuple[Compile, ...]
    failures: tuple[str, ...]

    @property
    def held(self) -> bool:
        return not self.failures

    def agree(self, field: str) -> int:
        """How many compiles share the first one's `part_digest` or `byte_digest`."""
        first = getattr(self.compiles[0], field)
        return sum(getattr(c, field) == first for c in self.compiles)


def members(body: bytes) -> dict[str, str]:
    """Ruling 3: each part's sha256, or the whole artefact as one member."""
    if not zipfile.is_zipfile(io.BytesIO(body)):
        return {WHOLE: hashlib.sha256(body).hexdigest()}
    return {name: hashlib.sha256(data).hexdigest() for name, data in check_package(body).items()}


def member_diff(first: Mapping[str, str], other: Mapping[str, str]) -> tuple[str, ...]:
    """Ruling 3: every member that differs, is missing from `other`, or is extra in it."""
    out = []
    for name in sorted(first.keys() | other.keys()):
        if name not in other:
            out.append(f"{name}: missing")
        elif name not in first:
            out.append(f"{name}: extra")
        elif first[name] != other[name]:
            out.append(f"{name}: {first[name][:12]} -> {other[name][:12]}")
    return tuple(out)


def compile_here(target: Target, workdir: Path, *, label: str) -> Compile:
    """Ruling 2: one compile of `target`'s golden in this process, under `workdir`."""
    card = _card(target.card)
    sibling = CompileCard.of(card)
    constructs = ConstructTable.load(
        Path(str(card.source)).parent / sibling.constructs, normalizers(card)
    )
    compiler: Any = Subject.of(target.card, workdir=workdir / "subject").instantiate(
        **target.config
    )
    compiled = compile_golden(compiler, card, constructs, target.golden, workdir=workdir / "suite")
    return Compile(
        label,
        compiled.part_digest,
        hashlib.sha256(compiled.body).hexdigest(),
        members(compiled.body),
    )


def compile_fresh(target: str, *, root: Path, register: Path, workdir: Path, seed: str) -> Compile:
    """Ruling 1: one compile in a child under `seed`, its own cwd and TMPDIR (ruling 5)."""
    cwd, tmp, work = workdir / "cwd", workdir / "tmp", workdir / "work"
    for path in (cwd, tmp, work):
        path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONHASHSEED": seed,
        "SOURCE_DATE_EPOCH": "0",
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
    }
    argv = (
        sys.executable,
        "-c",
        CHILD,
        "--target",
        target,
        "--root",
        str(root),
        "--register",
        str(register),
        "--workdir",
        str(work),
        "--label",
        f"PYTHONHASHSEED={seed}",
    )
    done = run_captured(argv, stdin=b"", cwd=str(cwd), env=env, timeout_s=CHILD_TIMEOUT_S)
    out = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not out:
        tail = done.stderr.decode("utf-8", "replace")[-800:]
        msg = f"the {target} compile under PYTHONHASHSEED={seed} exited {done.returncode}: {tail}"
        raise QualityError(msg, fix=_FIX)
    row = json.loads(out.splitlines()[-1])
    return Compile(row["label"], row["part_digest"], row["byte_digest"], row["members"])


def judge(target: str, declared: Sequence[str], compiles: Sequence[Compile]) -> Judged:
    """Rulings 3 and 4: every compile against the first, `part` always, `byte` if declared."""
    first, failures = compiles[0], []
    for other in compiles[1:]:
        if other.part_digest != first.part_digest:
            diff = "; ".join(member_diff(first.members, other.members)) or "no member differs"
            failures.append(
                f"part: {other.label} is sha256:{other.part_digest[:12]}, {first.label} "
                f"sha256:{first.part_digest[:12]} ({diff})"
            )
        if "byte" in declared and other.byte_digest != first.byte_digest:
            failures.append(
                f"byte: {other.label} is sha256:{other.byte_digest[:12]}, {first.label} "
                f"sha256:{first.byte_digest[:12]}, and the card declares byte"
            )
    return Judged(target, tuple(declared), tuple(compiles), tuple(failures))


def run(target: Target, *, root: Path, register: Path, workdir: Path) -> Judged:
    """Ruling 1: two compiles here and one per seed in a child, judged together."""
    capability = dict(_card(target.card).compile_capability)
    declared = tuple(str(c) for c in capability.get("determinism", ()))  # type: ignore[union-attr]
    compiles = [
        compile_here(target, workdir / "here-a", label="in-process a"),
        compile_here(target, workdir / "here-b", label="in-process b"),
    ]
    compiles += [
        compile_fresh(
            target.target, root=root, register=register, workdir=workdir / f"seed-{seed}", seed=seed
        )
        for seed in SEEDS
    ]
    return judge(target.target, declared, compiles)


def main(argv: Sequence[str] | None = None) -> int:
    """The child of ruling 1: one compile, printed as one JSON line."""
    parser = argparse.ArgumentParser(prog="out_determinism")
    parser.add_argument("--target", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args(argv)
    register = tomllib.loads(args.register.read_text(encoding="utf-8"))
    [target] = [t for t in targets(register, args.root) if t.target == args.target]
    done = compile_here(target, args.workdir, label=args.label)
    sys.stdout.write(
        json.dumps(
            {
                "label": done.label,
                "part_digest": done.part_digest,
                "byte_digest": done.byte_digest,
                "members": dict(done.members),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _card(path: Path) -> DriverCard:
    card = load_card(path.read_bytes(), origin="driver_path", source=str(path))
    if not isinstance(card, DriverCard):
        msg = f"{path} is not a driver card"
        raise QualityError(msg, fix=_FIX)
    return card
