"""Q-G26, split and corpus leakage, as a program. **D875.**

13-quality.md:2010 makes Q-G26 a `G` gate over three things: *"recomputed split,
fixture-versus-corpus digest intersection, assertion provenance"*. The decisions are
`omniweave_conform.leakage`'s. This file reads the inputs, prints every leak and every clause it
could not run, and exits, following the standing pattern (ledger D25).

**Three inputs, two of them absent until something writes them.**
- **The splits.** Nothing in this build records a split: every use recomputes
  `stats.split_of()`, so there is no split file to hold to it, and the clause is reported as not
  run, by name, rather than as clean.
- **`omniweave-golden`'s manifest** comes with `ow eval fetch`, which is not built. `--golden PATH`
  names one; every 64-hex value in it is a digest the corpus holds. Without it the clause is not
  run.
- **The `.oweval`'s assertions**, `eval/omniweave.oweval` by default. Each one's
  `derived_from_sha256` is held against Tier A, every committed byte under `fixtures/` or a
  `packages/<dist>/fixtures/` tree (`gate_fixtures.tier_a()`, D844, loaded by path). Without an
  `.oweval` the clause is not run; an `--oweval` named and missing is an input the gate cannot
  read, and exits 2.

**Registration.** A `Q-G` script, so `test_gates_register.py`'s `QG_SERIES_SCRIPTS` names it.

## Exit codes

`0` no leak. `1` a leak, named with `OW-Q-015`. `2` the gate did not run: no git, or an input it
cannot read.

Specified in 13-quality.md sections 9.1 and 15, and 16-roadmap.md W10.11.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

REPO: Final = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.leakage import Leak, assertion_leaks, golden_leaks  # noqa: E402
from omniweave_core.store.oweval import open_oweval  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import ModuleType

__all__ = ["EXIT_CLEAN", "EXIT_LEAK", "EXIT_NOT_RUN", "OWEVAL", "digests_of", "main"]

EXIT_CLEAN, EXIT_LEAK, EXIT_NOT_RUN = 0, 1, 2
OWEVAL: Final = Path("eval") / "omniweave.oweval"
_HEX64: Final = re.compile(r"\b[0-9a-f]{64}\b")


def _fixtures_gate() -> ModuleType:
    path = REPO / "tools" / "gate_fixtures.py"
    spec = importlib.util.spec_from_file_location("_owgate_fixtures_for_leakage", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- the file is in this repo
        msg = f"cannot load {path}"
        raise RuntimeError(msg)
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


def digests_of(root: Path, paths: Sequence[str]) -> dict[str, str]:
    """Each Tier-A path's sha256, as `{sha256: path}`. Two identical files keep the first path."""
    out: dict[str, str] = {}
    for path in sorted(paths):
        file = root / path
        if file.is_file():
            out.setdefault(hashlib.sha256(file.read_bytes()).hexdigest(), path)
    return out


def _manifest_digests(path: Path) -> set[str]:
    """Every 64-hex value in the golden's manifest, at any depth."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.update(_HEX64.findall(value.lower()))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(tomllib.loads(path.read_text(encoding="utf-8")))
    return found


def _assertions(path: Path) -> list[tuple[str, str, str]]:
    connection = open_oweval(path)
    try:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT assertion_id, corpus_id, derived_from_sha256 FROM eval_assertion "
                "ORDER BY assertion_id"
            )
        ]
    finally:
        connection.close()


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    committed: Sequence[str] | None = None,
    root: Path = REPO,
) -> int:
    parser = argparse.ArgumentParser(prog="gate_leakage", description="Q-G26: no leakage.")
    parser.add_argument("--oweval", type=Path, default=None, help="the .oweval to read")
    parser.add_argument("--golden", type=Path, default=None, help="omniweave-golden's manifest")
    args = parser.parse_args(argv)
    gate = _fixtures_gate()
    try:
        tracked = list(committed) if committed is not None else gate._committed(root)
        fixtures: Mapping[str, str] = digests_of(root, gate.tier_a(tracked))
        golden = _manifest_digests(args.golden) if args.golden is not None else None
        if args.oweval is not None and not args.oweval.is_file():
            raise FileNotFoundError(f"--oweval {args.oweval} is not a file")
        oweval = args.oweval if args.oweval is not None else root / OWEVAL
        assertions = _assertions(oweval) if oweval.is_file() else None
    except (OSError, tomllib.TOMLDecodeError, RuntimeError) as error:
        _say(f"Q-G26 did not run: {type(error).__name__}: {error}")
        return EXIT_NOT_RUN
    leaks: list[Leak] = []
    _say(f"Q-G26  Tier A: {len(fixtures)} distinct fixture digest(s)")
    _say("  split      not run: nothing records a split; every use recomputes stats.split_of()")
    if golden is None:
        _say("  golden     not run: no omniweave-golden manifest (ow eval fetch is not built)")
    else:
        leaks += golden_leaks(fixtures, golden)
        _say(f"  golden     {len(golden)} manifest digest(s) checked")
    if assertions is None:
        _say(f"  assertion  not run: no .oweval at {oweval}")
    else:
        leaks += assertion_leaks(assertions, fixtures)
        _say(f"  assertion  {len(assertions)} assertion(s) checked")
    for leak in leaks:
        _say(f"  LEAK {leak.clause:<9}  {leak.names}: {leak.why}")
    _say(f"Q-G26 {'ok' if not leaks else 'FAILED'}  {len(leaks)} leak(s)")
    return EXIT_LEAK if leaks else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
