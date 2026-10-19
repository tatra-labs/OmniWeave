"""OUT13 on this machine: each register target's golden, five compiles, one `part_digest`. D878.

13-quality.md:1568 gives OUT13 its runs (*"3 runs x `PYTHONHASHSEED ∈ {0, 1, random}`, two temp
dirs, different cwd and `TMPDIR`, `SOURCE_DATE_EPOCH=0`"*) and 09-generation.md:1597 its diff
(*"member by member"*). The decisions are `omniweave_conform.out_determinism`'s. This file reads
the metric register's `[[target]]` rows, runs each, prints every compile's digests and every
disagreement, and exits, following the standing pattern (ledger D25).

**One cell.** The nine OS/Python cells V10-10 names, and the two pdfium minors, are CI's matrix,
which is off. This runs the in-cell half wherever it is invoked, and says so on its last line.

**`--golden DIR` with one `--target`** compiles that directory instead of the register's golden
(D881): `fixtures/gen/gen_golden40.py`'s forty-slide deck is V10-10's *"40-unit golden"*, and it
is generated rather than committed, so the register cannot name it.

**A `check_` script, not a `gate_` one.** A `tools/gate_*.py` must have a register row whose
runner CI invokes (`test_gates_register.py`), and OUT13 is a law with no gate row. V10-10 runs it
as a slow instrument.

## Exit codes

`0` every target's five compiles agree on `part`, and on `byte` where the card declares it. `1` a
disagreement, naming the target, the compile and the members. `2` the check did not run: no
register, no target, or a compile that could not run.

Specified in 13-quality.md section 8.7 and 09-generation.md sections 5.4 and 11.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

REPO: Final = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.out_determinism import Judged, run  # noqa: E402
from omniweave_conform.roundtrip import targets  # noqa: E402
from omniweave_core.errors import QualityError  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["EXIT_DIFFER", "EXIT_HELD", "EXIT_NOT_RUN", "REGISTER", "main", "render"]

EXIT_HELD, EXIT_DIFFER, EXIT_NOT_RUN = 0, 1, 2
REGISTER: Final = Path("eval") / "gates.toml"


def render(judged: Judged) -> list[str]:
    """One target's lines: its declared classes, each compile, and every failure."""
    n = len(judged.compiles)
    lines = [
        f"{judged.target}  declares {', '.join(judged.declared) or 'nothing'}; "
        f"part {judged.agree('part_digest')} of {n} agree, byte {judged.agree('byte_digest')} "
        f"of {n}"
    ]
    lines += [
        f"  {c.label:<22} part sha256:{c.part_digest[:16]}  byte sha256:{c.byte_digest[:16]}  "
        f"{len(c.members)} member(s)"
        for c in judged.compiles
    ]
    lines += [f"  DIFFER {failure}" for failure in judged.failures]
    return lines


def main(argv: Sequence[str] | None = None, *, root: Path = REPO) -> int:
    parser = argparse.ArgumentParser(prog="check_out_determinism", description="OUT13, one cell.")
    parser.add_argument("--register", type=Path, default=None, help="the metric register")
    parser.add_argument("--target", action="append", default=None, help="only these targets")
    parser.add_argument(
        "--golden", type=Path, default=None, help="this golden instead, for one --target (D881)"
    )
    args = parser.parse_args(argv)
    register = args.register if args.register is not None else root / REGISTER
    try:
        rows = targets(tomllib.loads(register.read_text(encoding="utf-8")), root)
    except (OSError, tomllib.TOMLDecodeError) as error:
        sys.stdout.write(f"OUT13 did not run: {type(error).__name__}: {error}\n")
        return EXIT_NOT_RUN
    chosen = [t for t in rows if args.target is None or t.target in args.target]
    if args.golden is not None:
        if len(chosen) != 1:
            sys.stdout.write("OUT13 did not run: --golden names one fixture, so one --target\n")
            return EXIT_NOT_RUN
        chosen = [replace(chosen[0], golden=args.golden.resolve())]
    if not chosen:
        among = f" among {args.target}" if args.target else ""
        sys.stdout.write(f"OUT13 did not run: {register} names no [[target]]{among}\n")
        return EXIT_NOT_RUN
    try:
        judged = []
        with tempfile.TemporaryDirectory(prefix="ow-out-determinism-") as scratch:
            for target in chosen:
                judged.append(
                    run(target, root=root, register=register, workdir=Path(scratch) / target.target)
                )
    except (OSError, QualityError) as error:
        sys.stdout.write(f"OUT13 did not run: {type(error).__name__}: {error}\n")
        return EXIT_NOT_RUN
    for one in judged:
        sys.stdout.write("\n".join(render(one)) + "\n")
    held = all(one.held for one in judged)
    sys.stdout.write(
        f"OUT13 {'ok' if held else 'FAILED'}  {len(judged)} target(s), one cell; the nine-cell "
        "matrix is CI's\n"
    )
    return EXIT_HELD if held else EXIT_DIFFER


if __name__ == "__main__":
    sys.exit(main())
