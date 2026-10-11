"""`ow out <verb>`: the OUT verbs this build dispatches. D761: `targets`. D762: `constructs`.

09-generation.md section 1 (`omniweave.targets` exists "so `ow out targets` can list an artefact
kind without resolving a driver"), section 12.4 ("`ow out targets` prints the target, the flag and
**the reason**"), and 10-interfaces.md's `full` roster (`ow_targets` / `out.targets`: "which
artefact kinds this deployment can compile, and their determinism class"). Section 3.3 for
`constructs`: "`ow out constructs pptx --format md` renders the ConstructTable as agent
documentation", with `--group` and `--construct` selecting from it.

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
4. **Refused by name, exit 1:** `--quiet`, because neither verb declares a scalar, and
   `--render jsonl|rows`, which have no writer here (the `explain` precedent).
5. **Only `targets` and `constructs` are served.** The other ten `out` verbs are rostered without
   an Action, so the generated tree never parses them and this module never sees them.
6. **`constructs` documents the one card that declares the target**, found as `targets` finds
   cards, whether or not `[targets] enabled` lists it: documentation is how an agent learns a
   target before anyone enables it. No card is `OW_TARGET_UNKNOWN` (exit 2), naming the kinds
   `ow out targets` lists. Two cards for one target is `OW_TARGET_AMBIGUOUS`, a configuration
   error (exit 1) naming both drivers, because which one compiles is the registry's choice and the
   documentation must describe that one.
7. **`--format text|md`, and one document a run.** `text` is a header and one line a row, or every
   key of the one row `--construct` names. `md` is `agentdoc.agent_doc()`. `--render json` is the
   report object, and it refuses `--format md`, since that would be two documents. `--group` and
   `--construct` are two selections, so passing both is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.errors import ConfigError, NotFoundError, OwError, UsageError

from omniweave.sdk.reports import (
    ConstructBake,
    ConstructListing,
    ConstructsReport,
    TargetListing,
    TargetsReport,
)
from omniweave.surface.inputs import CONSTRUCT_FORMATS
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core import config
    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.out.card import CompileCard
    from omniweave_core.out.constructs import Construct, ConstructTable

__all__ = ["OUT_WORD", "constructs_report", "main", "targets_report"]

OUT_WORD: Final[str] = "out"
_CONSTRUCTS_FIX: Final[str] = (
    "ow out constructs <target> [--format md] [--group G | --construct ID]"
)


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow out ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(OUT_WORD, parsed)
        verb = _VERBS[parsed.ow_action]
        return verb(parsed, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _targets(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    _refuse_unserved(parsed, verb="ow out targets", fix="ow out targets [--render json]")
    listing, faults = targets_report(cwd=cwd, env=env, explicit=_explicit(parsed))
    if parsed.render == "json":
        stdout.write(json.dumps([_row(t) for t in listing.targets], ensure_ascii=False) + "\n")
    else:
        for line in _lines(listing):
            stdout.write(line + "\n")
    if faults:
        stderr.write(f"ow out targets: {faults} card(s) were refused; `ow doctor` names each\n")
    return 0


def _constructs(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out constructs", fix=_CONSTRUCTS_FIX)
    fmt = str(parsed.format)
    if fmt not in CONSTRUCT_FORMATS:
        raise UsageError(
            f"--format {fmt} is not one of {', '.join(CONSTRUCT_FORMATS)}", fix=_CONSTRUCTS_FIX
        )
    if fmt == "md" and parsed.render == "json":
        raise UsageError(
            "--format md and --render json ask for two documents; pass one", fix=_CONSTRUCTS_FIX
        )
    if parsed.group is not None and parsed.construct is not None:
        raise UsageError(
            "--group and --construct are two selections; pass one", fix=_CONSTRUCTS_FIX
        )
    built = constructs_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        target=str(parsed.target),
        group=parsed.group,
        construct=parsed.construct,
    )
    listing, card, table, rows = built
    if parsed.render == "json":
        stdout.write(json.dumps(_report(listing), ensure_ascii=False) + "\n")
    elif fmt == "md":
        from omniweave_core.out.agentdoc import agent_doc  # noqa: PLC0415 -- only this verb pays

        stdout.write(agent_doc(card, table, rows))
    else:
        lines = _row_block(listing.rows[0]) if parsed.construct else _construct_lines(listing)
        for line in lines:
            stdout.write(line + "\n")
    return 0


_VERBS: Final[Mapping[str, Callable[..., int]]] = {
    "out.targets": _targets,
    "out.constructs": _constructs,
}


def targets_report(
    *, cwd: Path, env: Mapping[str, str], explicit: Path | None
) -> tuple[TargetsReport, int]:
    """Ruling 1: every discovered compile card as a row, and the count of refused cards."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.out.card import targets  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    enabled = resolved.get("targets.enabled")
    allowed = {str(one) for one in enabled} if isinstance(enabled, tuple) else set()
    found = _discover(resolved, env)
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


def constructs_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    target: str,
    group: str | None = None,
    construct: str | None = None,
) -> tuple[ConstructsReport, CompileCard, ConstructTable, tuple[Construct, ...]]:
    """Ruling 6: the one card declaring `target`, its table, and the rows selected from it."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.errors import load_register  # noqa: PLC0415
    from omniweave_core.out.agentdoc import group_of, load_table, select  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    path, card = _one_card(_discover(resolved, env).cards, target)
    table = load_table(path, card)
    rows = select(table, target, group=group, construct=construct)
    by_symbol = load_register().by_symbol
    listing = ConstructsReport(
        target=card.target,
        driver=card.driver,
        il=table.il,
        carrier=table.carrier,
        version=table.version,
        digest=table.digest(),
        agent_doc_tokens_max=card.agent_doc_tokens_max,
        ignore=table.ignore,
        rows=tuple(
            ConstructListing(
                id=row.id,
                group=group_of(row.id),
                disposition=row.disposition.value,
                round_trip=row.round_trip.value,
                code=row.code,
                numeric=(by_symbol[row.code].numeric if row.code in by_symbol else ""),
                since=row.since,
                selector=row.selector,
                canonical=row.canonical,
                maps_to=row.maps_to,
                normalizes_to=row.normalizes_to,
                normalizer=row.normalizer,
                bake=None
                if row.bake is None
                else ConstructBake(row.bake.renderer, row.bake.dpi, row.bake.role),
                forbidden_when=row.forbidden_when,
                msg=row.msg,
                severity=row.severity,
                visible=row.visible,
            )
            for row in rows
        ),
    )
    return listing, card, table, rows


def _one_card(cards: Sequence[DriverCard], target: str) -> tuple[Path, CompileCard]:
    """Ruling 6: exactly one compile card declares `target`."""
    from omniweave_core.out.card import CompileCard  # noqa: PLC0415

    compiled = [
        (Path(card.source), CompileCard.of(card))
        for card in cards
        if str(card.identity.port) == "compile"
    ]
    claiming = [(path, one) for path, one in compiled if one.target == target]
    if not claiming:
        kinds = ", ".join(sorted({one.target for _, one in compiled})) or "none"
        raise NotFoundError(
            f"no compile card declares target {target!r}; the cards found declare {kinds}",
            symbol="OW_TARGET_UNKNOWN",
            fix="ow out targets",
        )
    if len(claiming) > 1:
        drivers = ", ".join(sorted(one.driver for _, one in claiming))
        raise ConfigError(
            f"{len(claiming)} compile cards declare target {target!r}: {drivers}",
            symbol="OW_TARGET_AMBIGUOUS",
            fix="keep one of them on OMNIWEAVE_DRIVER_PATH or in .omniweave/drivers/",
        )
    [one] = claiming
    return one


def _discover(resolved: config.Config, env: Mapping[str, str]) -> Any:
    from omniweave_core.discovery import discover  # noqa: PLC0415

    return discover(env=env, project_root=_project_root(resolved))


def _explicit(parsed: argparse.Namespace) -> Path | None:
    return Path(parsed.config) if parsed.config else None


def _project_root(resolved: config.Config) -> Path | None:
    """The directory of the `omniweave.toml` that supplied a value, as `doctor` resolves it."""
    from omniweave_core.config import ConfigLayer  # noqa: PLC0415

    for source in resolved.sources.values():
        if source.layer is ConfigLayer.PROJECT_FILE and source.path is not None:
            return source.path.parent
    return None


def _refuse_unserved(parsed: argparse.Namespace, *, verb: str, fix: str) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(f"{', '.join(named)} is parsed and not served by {verb}", fix=fix)


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


def _report(listing: ConstructsReport) -> dict[str, Any]:
    return {
        "target": listing.target,
        "driver": listing.driver,
        "il": listing.il,
        "carrier": listing.carrier,
        "version": listing.version,
        "digest": listing.digest,
        "agent_doc_tokens_max": listing.agent_doc_tokens_max,
        "ignore": list(listing.ignore),
        "rows": [_construct(row) for row in listing.rows],
    }


def _construct(row: ConstructListing) -> dict[str, Any]:
    bake = row.bake
    return {
        "id": row.id,
        "group": row.group,
        "disposition": row.disposition,
        "round_trip": row.round_trip,
        "code": row.code,
        "numeric": row.numeric,
        "since": row.since,
        "selector": row.selector,
        "canonical": row.canonical,
        "maps_to": row.maps_to,
        "normalizes_to": row.normalizes_to,
        "normalizer": row.normalizer,
        "bake": None
        if bake is None
        else {"renderer": bake.renderer, "dpi": bake.dpi, "role": bake.role},
        "forbidden_when": row.forbidden_when,
        "msg": row.msg,
        "severity": row.severity,
        "visible": row.visible,
    }


def _construct_lines(listing: ConstructsReport) -> list[str]:
    """Ruling 7's text form: a header, then the id, disposition, round trip, selector, code."""
    lines = [
        f"{listing.target} {listing.driver} {listing.carrier}/{listing.il} table v{listing.version}"
        f"  {len(listing.rows)} row(s)  agent doc budget {listing.agent_doc_tokens_max} tokens"
    ]
    for row in listing.rows:
        lines.append(
            f"  {row.id:<22} {row.disposition:<9} {row.round_trip:<10} {row.selector:<24} "
            f"{row.numeric or row.code}"
        )
    return lines


def _row_block(row: ConstructListing) -> list[str]:
    """`--construct`: every key the row carries, one a line, as `OW-T-009`'s fix promises."""
    lines = []
    for key, value in _construct(row).items():
        if value is None:
            continue
        shown = (
            ", ".join(f"{k} {v}" for k, v in value.items()) if isinstance(value, dict) else value
        )
        lines.append(f"{key:<15} {shown}")
    return lines
