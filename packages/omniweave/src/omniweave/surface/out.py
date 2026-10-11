"""`ow out <verb>`: the OUT verbs this build dispatches: `targets` (D761), `constructs` (D762),
`scaffold` (D765) and `check` (D766).

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
5. **Only `targets`, `constructs`, `scaffold` and `check` are served.** The other eight `out`
   verbs are rostered without an Action, so the generated tree never parses them and this
   module never sees them.
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
8. **`scaffold` resolves what `out.job.scaffold()` takes, and writes nothing before the last
   refusal.** The order is `--brief` and `--slug` (both required), the corpus and its
   store (which must exist), the one card and its table, the Brief parsed against the
   table's baseline, the generation, and the slug's grammar. Only then is a byte written.
   - The generation is one past the store's newest seal for the slug, read through
     `connect_readonly()`. The seal still allocates the real one (09 section 5.4).
   - `<cache_root>` is `[roots] cache`, resolved as D527 resolves a corpus path: against
     the directory of the file that declared it, else `cwd`.
   - The run id, the trace context and `clock_ns` are minted here, at the runtime edge,
     as `new_run_id()`'s docstring and G8's `secrets` rule place them.
9. **`--corpus` is read by `scaffold` alone.** `targets` and `constructs` print nothing that
   depends on it and accept it, which is what an inert flag is. `check` refuses it by name,
   because the JobDir's `job.json` already names the corpus its cites resolve in.
10. **`check` is `out.compile.check()` over a JobDir** (`--job`, else `cwd`). The target, the
    corpus, the Brief and the commissioned roster come from its `job.json`. `--target`
    must match when given: 09 prints it in every fix. The compiler is the target's own
    class, built through `host.activate.construct()` with the card's `[config]` defaults,
    because the framework runs the target's `rules()` and the target has no `validate()`.
11. **The stages read what 09 section 4.3 lists.** `early`, `first-unit` and `unit` read
    the IL and the table. `final` adds the Brief, the Plan's roster (held to the bundle both
    ways) and a `CiteResolver` over the corpus's store, opened read-only.
12. **The exit is the stage's, and the report's `gate` block is the release's.** `final`
    exits as `gate_status()` decides (0, 6, 8 or 64). A non-final stage exits 8 on any error
    finding and 0 otherwise, as 09 section 4.3's table has it. Its report still says
    `non-final`, because no early report may release anything, and the text form says so
    under the trailer. `--render json` prints `validation/<stage>.json`'s document.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO, cast

from omniweave_core.errors import ConfigError, NotFoundError, OwError, TargetError, UsageError

from omniweave.sdk.reports import (
    ConstructBake,
    ConstructListing,
    ConstructsReport,
    OutCheckReport,
    ScaffoldReport,
    ScaffoldUnit,
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

__all__ = [
    "OUT_WORD",
    "Checked",
    "check_report",
    "constructs_report",
    "main",
    "scaffold_report",
    "targets_report",
]

OUT_WORD: Final[str] = "out"
_SCAFFOLD_FIX: Final[str] = "ow out scaffold <target> --brief brief.md --slug q3-board"
_CHECK_FIX: Final[str] = "ow out check --stage early|first-unit|unit|final [--unit U] [--job DIR]"
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


def _scaffold(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out scaffold", fix=_SCAFFOLD_FIX)
    missing = [f"--{name}" for name in ("brief", "slug") if getattr(parsed, name) is None]
    if missing:
        raise UsageError(f"ow out scaffold needs {' and '.join(missing)}", fix=_SCAFFOLD_FIX)
    built = scaffold_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        target=str(parsed.target),
        brief=Path(str(parsed.brief)),
        slug=str(parsed.slug),
        corpus=parsed.corpus,
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_scaffolded(built), ensure_ascii=False) + "\n")
    else:
        for line in _scaffold_lines(built):
            stdout.write(line + "\n")
    return 0


def _check(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    from omniweave_core.out.report import STAGES, render  # noqa: PLC0415 -- only this verb pays

    _refuse_unserved(parsed, verb="ow out check", fix=_CHECK_FIX)
    if parsed.corpus is not None:
        raise UsageError(
            "--corpus is not served by ow out check: the JobDir's job.json names its corpus",
            fix=_CHECK_FIX,
        )
    stage = parsed.stage
    if stage not in STAGES:
        raise UsageError(f"ow out check needs --stage, one of {', '.join(STAGES)}", fix=_CHECK_FIX)
    if (stage == "unit") != (parsed.unit is not None):
        raise UsageError(
            "--unit names the one unit --stage unit checks, and only it", fix=_CHECK_FIX
        )
    checked = check_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        job=None if parsed.job is None else Path(str(parsed.job)),
        target=parsed.target,
        stage=str(stage),
        unit=parsed.unit,
    )
    document = checked.document
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write(render(document))
        if stage != "final":
            stdout.write(
                f"stage {stage}: {checked.summary.errors} error(s), exit {checked.summary.exit}; "
                "only --stage final is a release gate\n"
            )
    return checked.summary.exit


_VERBS: Final[Mapping[str, Callable[..., int]]] = {
    "out.targets": _targets,
    "out.constructs": _constructs,
    "out.scaffold": _scaffold,
    "out.check": _check,
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
    driver, card = _one_card(_discover(resolved, env).cards, target)
    table = load_table(Path(driver.source), card)
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


def _one_card(cards: Sequence[DriverCard], target: str) -> tuple[DriverCard, CompileCard]:
    """Ruling 6: exactly one compile card declares `target`."""
    from omniweave_core.out.card import CompileCard  # noqa: PLC0415

    compiled = [
        (card, CompileCard.of(card)) for card in cards if str(card.identity.port) == "compile"
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


def scaffold_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    target: str,
    brief: Path,
    slug: str,
    corpus: str | None,
    entropy: Callable[[int], bytes] = os.urandom,
) -> ScaffoldReport:
    """Ruling 8: resolve, refuse, and only then write the JobDir."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.events import traceparent  # noqa: PLC0415
    from omniweave_core.operator import ULID_ENTROPY_BYTES, new_run_id  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.brief import baseline_rows, parse_brief  # noqa: PLC0415
    from omniweave_core.out.job import job_path, scaffold  # noqa: PLC0415
    from omniweave_core.store import artifact  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    from omniweave.surface.opening import corpus_for  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(resolved, [], corpus, verb="ow out scaffold")
    store = store_of(resolved, name, cwd=cwd)
    driver, card = _one_card(_discover(resolved, env).cards, target)
    table = load_table(Path(driver.source), card)
    text = _brief_text(brief if brief.is_absolute() else cwd / brief)
    parsed = parse_brief(text, baseline=baseline_rows(table))
    connection = store_sqlite.connect_readonly(store)
    try:
        gen = artifact.latest_generation(connection, slug) + 1
    finally:
        connection.close()
    clock = SystemClock()
    run_id = new_run_id(clock, entropy(ULID_ENTROPY_BYTES))
    where = job_path(_cache_root(resolved, cwd), run_id, slug, gen)
    job = scaffold(
        where,
        card=card,
        card_sha256=driver.card_sha256,
        table=table,
        brief_text=text,
        brief=parsed,
        slug=slug,
        artifact_gen=gen,
        corpus=name,
        traceparent=traceparent(entropy(16).hex(), entropy(8).hex()),
        clock_ns=clock.wall_ns(),
    )
    return ScaffoldReport(
        job_dir=str(where),
        run_id=run_id,
        target=card.target,
        slug=slug,
        artifact_gen=gen,
        corpus=name,
        traceparent=job.traceparent,
        units=tuple(
            ScaffoldUnit(id=u.id, ord=u.ord, il_path=u.il_path, anchor=u.anchor)
            for u in job.plan.units
        ),
    )


def _brief_text(path: Path) -> str:
    """The Brief's file, UTF-8. Missing is 2; unreadable is the Brief's own code."""
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise NotFoundError(f"no Brief at {path}", fix=_SCAFFOLD_FIX) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise TargetError(
            f"{path.name} does not read as UTF-8 text: {type(exc).__name__}",
            symbol="OW_TARGET_BRIEF_INVALID",
            fix=_SCAFFOLD_FIX,
        ) from None


def _cache_root(resolved: config.Config, cwd: Path) -> Path:
    """Ruling 8: `[roots] cache`, against its declaring file's directory, else `cwd` (D527)."""
    raw = Path(str(resolved.get("roots.cache")))
    declared = resolved.source_of("roots.cache").path
    base = declared.parent if declared is not None else cwd
    return raw if raw.is_absolute() else (base / raw).resolve()


def _scaffolded(built: ScaffoldReport) -> dict[str, Any]:
    return {
        "job_dir": built.job_dir,
        "run_id": built.run_id,
        "target": built.target,
        "slug": built.slug,
        "artifact_gen": built.artifact_gen,
        "corpus": built.corpus,
        "traceparent": built.traceparent,
        "units": [
            {"id": u.id, "ord": u.ord, "il_path": u.il_path, "anchor": u.anchor}
            for u in built.units
        ],
    }


def _scaffold_lines(built: ScaffoldReport) -> list[str]:
    return [
        f"scaffolded {built.target} {built.slug}@{built.artifact_gen} in corpus {built.corpus}",
        f"  job dir  {built.job_dir}",
        f"  run      {built.run_id}",
        *(f"  {u.id}  {u.il_path}  {u.anchor}".rstrip() for u in built.units),
        "next: write each unit's file under il/ and add its [[unit]] row to il/il.toml",
    ]


@dataclass(frozen=True, slots=True)
class Checked:
    """`check_report()`'s answer: the summary the registry returns and the document printed."""

    summary: OutCheckReport
    document: Mapping[str, Any]


def check_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    job: Path | None,
    target: str | None,
    stage: str,
    unit: str | None,
) -> Checked:
    """Rulings 10-12: one stage of the gate over one JobDir."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.host.activate import construct  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.compile import CompileV1, check  # noqa: PLC0415
    from omniweave_core.out.job import Job  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.cites import SqliteCiteResolver  # noqa: PLC0415

    from omniweave.surface.query import store_of  # noqa: PLC0415

    job_dir = cwd if job is None else (job if job.is_absolute() else cwd / job)
    plan = Job.load(job_dir).plan
    if target is not None and target != plan.target:
        raise UsageError(
            f"--target {target} is not this JobDir's target, {plan.target}",
            fix=f"ow out check --target {plan.target} --stage {stage}",
        )
    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    driver, card = _one_card(_discover(resolved, env).cards, plan.target)
    table = load_table(Path(driver.source), card)
    compiler = cast("CompileV1", construct(driver, driver.config.effective()))
    final = stage == "final"
    thread = None
    if final:
        store = store_of(resolved, plan.corpus, cwd=cwd)
        thread = store_sqlite.StoreThread(lambda: store_sqlite.connect_readonly(store)).start()
    try:
        result = check(
            job_dir,
            compiler,
            target=plan.target,
            constructs=table,
            stage=stage,
            unit=unit,
            plan_units=[u.id for u in plan.units] if final else None,
            brief=plan.brief if final else None,
            clock=SystemClock(),
            cites=None if thread is None else SqliteCiteResolver(thread, corpus=plan.corpus),
        )
    finally:
        if thread is not None:
            thread.close()
    counts = result.report.counts
    errors = counts.get("error", 0)
    code = result.exit if final else (8 if errors else 0)
    return Checked(
        summary=OutCheckReport(
            stage=stage,
            target=plan.target,
            status=result.status.value,
            exit=code,
            report_path=str(result.path),
            errors=errors,
            warnings=counts.get("warning", 0),
            infos=counts.get("info", 0),
        ),
        document=result.report.as_json(),
    )
