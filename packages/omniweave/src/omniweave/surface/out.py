"""`ow out <verb>`: the OUT verbs this build dispatches. D761: `targets`.

09-generation.md section 1 (`omniweave.targets` exists "so `ow out targets` can list an artefact
kind without resolving a driver"), section 12.4 ("`ow out targets` prints the target, the flag and
**the reason**"), and 10-interfaces.md's `full` roster (`ow_targets` / `out.targets`: "which
artefact kinds this deployment can compile, and their determinism class").

## Rulings

1. **`targets` lists every compile card discovery finds.** That covers entry points,
   `OMNIWEAVE_DRIVER_PATH`, and the project's `.omniweave/drivers/`. Rows come through
   `omniweave_core.out.card.targets()`, plus whether `[targets] enabled` lists the kind. A kind
   can compile when it is both implemented and enabled. A row says which of the two is missing,
   so an unimplemented `video` is printed with its reason rather than left out.
2. **`--render json` prints the bare array of rows.** That is the shape 16-roadmap's P9 exit
   criterion reads, `.[] | select(.target=="video") | .implemented == false`. The text form is
   one line a row.
3. **A card discovery refuses is not a row.** Its count goes to stderr with `ow doctor` as the
   command that names each one, the way `doctor`'s D-08 reports the same faults.
4. **Refused by name, exit 1:** `--quiet`, because this verb declares no scalar, and
   `--render jsonl|rows`, which have no writer here (the `explain` precedent).
5. **Only `targets` is served.** The other eleven `out` verbs are rostered without an Action, so
   the generated tree never parses them and this module never sees them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.errors import OwError, UsageError

from omniweave.sdk.reports import TargetListing, TargetsReport
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core import config

__all__ = ["OUT_WORD", "main", "targets_report"]

OUT_WORD: Final[str] = "out"


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow out ...` from argv (starting at the root word). Exit 0, or 1 for usage."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(OUT_WORD, parsed)
        _refuse_unserved(parsed)
        explicit = Path(parsed.config) if parsed.config else None
        listing, faults = targets_report(cwd=cwd, env=env, explicit=explicit)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)
    if parsed.render == "json":
        stdout.write(json.dumps([_row(t) for t in listing.targets], ensure_ascii=False) + "\n")
    else:
        for line in _lines(listing):
            stdout.write(line + "\n")
    if faults:
        stderr.write(f"ow out targets: {faults} card(s) were refused; `ow doctor` names each\n")
    return 0


def targets_report(
    *, cwd: Path, env: Mapping[str, str], explicit: Path | None
) -> tuple[TargetsReport, int]:
    """Ruling 1: every discovered compile card as a row, and the count of refused cards."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.discovery import discover  # noqa: PLC0415
    from omniweave_core.out.card import targets  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    enabled = resolved.get("targets.enabled")
    allowed = {str(one) for one in enabled} if isinstance(enabled, tuple) else set()
    found = discover(env=env, project_root=_project_root(resolved))
    rows = tuple(
        TargetListing(
            target=row.target,
            driver=row.driver,
            implemented=row.implemented,
            reason=row.reason,
            enabled=row.target in allowed,
            determinism=row.determinism,
            carrier=row.carrier,
            il=row.il,
            fidelity=row.fidelity,
            laws=row.laws,
        )
        for row in targets(found.cards)
    )
    return TargetsReport(rows), len(found.faults)


def _project_root(resolved: config.Config) -> Path | None:
    """The directory of the `omniweave.toml` that supplied a value, as `doctor` resolves it."""
    from omniweave_core.config import ConfigLayer  # noqa: PLC0415

    for source in resolved.sources.values():
        if source.layer is ConfigLayer.PROJECT_FILE and source.path is not None:
            return source.path.parent
    return None


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow out targets",
            fix="ow out targets [--render json]",
        )


def _row(listing: TargetListing) -> dict[str, Any]:
    return {
        "target": listing.target,
        "driver": listing.driver,
        "implemented": listing.implemented,
        "enabled": listing.enabled,
        "reason": listing.reason,
        "determinism": list(listing.determinism),
        "carrier": listing.carrier,
        "il": listing.il,
        "fidelity": listing.fidelity,
        "laws": list(listing.laws),
    }


def _lines(listing: TargetsReport) -> list[str]:
    """Ruling 2's text form: the target, its driver, its IL, and what stops it compiling."""
    if not listing.targets:
        return ["no compile card was found; `ow doctor` lists what discovery saw"]
    lines = []
    for one in listing.targets:
        state = "ready" if one.implemented and one.enabled else "not ready"
        why = (
            f"implemented = false: {one.reason}"
            if not one.implemented
            else ("enabled" if one.enabled else "not in [targets] enabled")
        )
        lines.append(
            f"{one.target:<8} {state:<9} {one.driver:<24} {one.carrier}/{one.il}  "
            f"determinism {'+'.join(one.determinism)}  {why}"
        )
    return lines
