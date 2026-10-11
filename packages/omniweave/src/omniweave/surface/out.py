"""`ow out <verb>`: the OUT verbs this build dispatches: `targets` (D761), `constructs` (D762),
`scaffold` (D765), `check` (D766), `stamp` (D767), `normalize` (D768), `list` (D769), `compile`
(D773), `verify` (D774), `back` (D777) and `assets` (D778).

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
5. **Every `out` verb but `project` is served**: `targets`, `constructs`, `scaffold`,
   `check`, `stamp`, `normalize`, `list`, `compile`, `verify`, `back` and `assets`. `project` is
   rostered without an Action, so the generated tree never parses it and this module never sees
   it.
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
13. **`stamp` is `out.stamp.stamp()` over a JobDir** (`--job`, else `cwd`), with the target's
    own carrier, so the stamped text is reparsed by the parser the check uses. It exits 0
    whether or not it minted anything (09 section 15). Its text form ends with the re-check
    command, because a stamp moves `il_digest` and leaves any standing report `stale`.
14. **`normalize` is `out.normalize.normalize()` over a JobDir** with the target's carrier
    and its own normalizers, loaded by `host.activate.normalizers()`. `--unit` and
    `--construct` narrow it; 09's positional IL path is the `--unit` option, because a
    positional cannot be optional in the generated grammar. It exits 0 whether or not it
    changed anything, and ends with the re-check command.
15. **`list` reads one corpus's sealed `artifact` rows**, by slug then generation, through
    `connect_readonly()`. `--render json` is the bare array of rows, as for `targets`. An
    empty corpus is an empty list and exit 0. 14's `ow out list --erased` needs a
    `contains_erased` mark that `0005_out.sql` does not carry, so it is not built.
16. **`compile` is `run.out_compile.compile_artifact()` over a JobDir** (`--job`, else `cwd`),
    lowered by a `CompileWorker`: the target's `lower()` and `postflight()` run in an S4 worker,
    because every compile card asks for `subproc`. The host still builds the target in this
    process for its `carrier()`, as `check` does (D771's finding).
17. **The Plan is `job.json`'s with what the compile computes put in.** A scaffolded Plan carries
    the scaffold's `il_digest` and an empty ledger's digest (`out.job` ruling 26). `compile`
    recomputes `il_digest`, `constructs_digest` and `ledger_digest`, and the gate comes from
    `validation/final.json`, held to the bundle's `il_digest`, so a report that describes other
    bytes is `stale`. `job.json` is not rewritten: it is the scaffold's record, and the job
    record the worker is sent is the Plan compiled.
18. **`--accept-manual` is the draft.** It asks for a `manual-required` gate's draft (09
    section 9); against a gate that passed it is a usage error, because the answer is a
    release.
19. **One corpus store, written per unit under its write lock.** The ledger, the cite resolver,
    the restriction aggregate and the seal share one `StoreThread`, whose lock is taken per unit
    (`StoreThread`'s 07:2730 rule), so a worker's run does not hold the store. The CAS is the
    store's sibling `cas/` (`store_cas()`), the producer is `ensure_producer()`'s row for the card's
    identity, the output root is `[roots] output`, and the worker's scratch is
    `<cache_root>/tmp/compile`. D779: the restriction aggregate's barred mask is
    `[licence] deny_restrictions`, each named `Restriction`'s bit ORed.
20. **The exit is the compile's.** 0 for a seal or a lookup hit, otherwise the closed gate's
    exit from 09 section 15, with nothing lowered: 6 `restricted`, naming each barred asset and
    cite, and the gate's own code for the rest. A worker's refusal is raised under the target's
    symbol and any other failure is `OW_TARGET_COMPILE_FAILED`.
21. **`verify` is `run.out_verify.verify_artifact()` over a JobDir's sealed generation**
    (`--job`, else `cwd`): the row its `job.json` names, read through `connect_readonly()`,
    recompiled from its retained IL by a `CompileWorker`, and compared at each declared class.
    The API sketch prints `ow out verify <artefact>`; R1 also needs the Brief, the clock and the
    frozen assets, and only the IL is retained, so the JobDir that compiled the artefact supplies
    them, each held to the row's digest. A failing law exits 8, and `--corpus` is refused, as
    `check` refuses it.
22. **`back` restores a sealed generation into a new JobDir for the next one**
    (`out.retain.restore`, D776). The corpus is `--corpus`, else the default, and the
    generation is `--gen`, else the newest. The Brief is the retained one (D775): a row sealed
    before D775 has none in CAS, and that is `StoreError` naming the JobDir that compiled it.
    The run id, the trace context and the clock are minted here, as `scaffold` mints them, and
    the next generation is one past the store's newest. The text form prints the contract line
    first, as 09 section 3.6 rule 5 asks. That line says only whether the table's digest moved,
    because no recorded table version exists to list the rows that moved (D776).
23. **`assets` reads one store, through `connect_readonly()`, in one of two forms.**
    `--slug` (with `--gen`, else the newest) lists that generation's frozen assets: slot,
    role, units, bytes and owning document, and with `--explain` each asset's licence and
    the names of its restriction bits, which is where 09 section 15 sends a `restricted`
    gate. `--slot` is 09 section 7.2's reuse query: every artefact generation that slots
    those bytes and every corpus document that owns them. It takes `asset-slot:<sha256>` or
    the bare digest. Exactly one form is given, `--gen` and `--explain` belong to `--slug`,
    and the query is this corpus's: a store holds one corpus, so "every corpus" is one
    `--corpus` at a time.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO, cast

from omniweave_core.errors import ConfigError, NotFoundError, OwError, TargetError, UsageError

from omniweave.sdk.reports import (
    ArtifactListing,
    ArtifactsReport,
    AssetListing,
    AssetsReport,
    BackReport,
    CompileReport,
    ConstructBake,
    ConstructListing,
    ConstructsReport,
    NormalizedRow,
    NormalizeReport,
    OutCheckReport,
    RestrictedItem,
    ScaffoldReport,
    ScaffoldUnit,
    SlotOwner,
    SlotUser,
    StampedUnit,
    StampReport,
    TargetListing,
    TargetsReport,
    VerifiedClass,
    VerifyReport,
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
    from omniweave_core.out.plan import Plan

    from omniweave.run.out_compile import Compiled

__all__ = [
    "OUT_WORD",
    "Checked",
    "artifacts_report",
    "assets_report",
    "back_report",
    "check_report",
    "compile_report",
    "constructs_report",
    "main",
    "normalize_report",
    "scaffold_report",
    "stamp_report",
    "targets_report",
    "verify_report",
]

OUT_WORD: Final[str] = "out"
_SCAFFOLD_FIX: Final[str] = "ow out scaffold <target> --brief brief.md --slug q3-board"
_STAMP_FIX: Final[str] = "ow out stamp [--job DIR]"
_LIST_FIX: Final[str] = "ow out list [--slug S] [--corpus N] [--render json]"
_NORMALIZE_FIX: Final[str] = "ow out normalize [--stage S] [--unit U] [--construct ID] [--job DIR]"
_CHECK_FIX: Final[str] = "ow out check --stage early|first-unit|unit|final [--unit U] [--job DIR]"
_COMPILE_FIX: Final[str] = "ow out compile [--accept-manual] [--job DIR]"
_VERIFY_FIX: Final[str] = "ow out verify [--job DIR]"
_BACK_FIX: Final[str] = "ow out back <slug> [--gen N] [--corpus C]"
_ASSETS_FIX: Final[str] = "ow out assets --slug S [--gen N] [--explain] | --slot SHA256"
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
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


def _compile(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out compile", fix=_COMPILE_FIX)
    if parsed.corpus is not None:
        raise UsageError(
            "--corpus is not served by ow out compile: the JobDir's job.json names its corpus",
            fix=_COMPILE_FIX,
        )
    built = compile_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        job=None if parsed.job is None else Path(str(parsed.job)),
        accept_manual=bool(parsed.accept_manual),
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_compiled(built), ensure_ascii=False) + "\n")
    else:
        for line in _compile_lines(built):
            stdout.write(line + "\n")
    return built.exit


def _assets(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out assets", fix=_ASSETS_FIX)
    if (parsed.slug is None) == (parsed.slot is None):
        raise UsageError("ow out assets takes --slug or --slot, exactly one", fix=_ASSETS_FIX)
    if parsed.slot is not None and (parsed.gen is not None or parsed.explain):
        raise UsageError(
            "--gen and --explain read an artefact: they go with --slug", fix=_ASSETS_FIX
        )
    slot = None if parsed.slot is None else str(parsed.slot).removeprefix("asset-slot:")
    if slot is not None and _SHA256.fullmatch(slot) is None:
        raise UsageError(
            f"--slot {parsed.slot!r} is not asset-slot:<sha256> or 64 lower-case hex",
            fix=_ASSETS_FIX,
        )
    built = assets_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        slug=parsed.slug,
        gen=None if parsed.gen is None else int(parsed.gen),
        slot=slot,
        corpus=parsed.corpus,
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_assets_document(built), ensure_ascii=False) + "\n")
    else:
        for line in _assets_lines(built, explain=bool(parsed.explain)):
            stdout.write(line + "\n")
    return 0


def _back(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out back", fix=_BACK_FIX)
    built = back_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        slug=str(parsed.slug),
        gen=None if parsed.gen is None else int(parsed.gen),
        corpus=parsed.corpus,
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_backed(built), ensure_ascii=False) + "\n")
    else:
        for line in _back_lines(built):
            stdout.write(line + "\n")
    return 0


def _verify(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out verify", fix=_VERIFY_FIX)
    if parsed.corpus is not None:
        raise UsageError(
            "--corpus is not served by ow out verify: the JobDir's job.json names its corpus",
            fix=_VERIFY_FIX,
        )
    built = verify_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        job=None if parsed.job is None else Path(str(parsed.job)),
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_verified(built), ensure_ascii=False) + "\n")
    else:
        for line in _verify_lines(built):
            stdout.write(line + "\n")
    return built.exit


def _stamp(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out stamp", fix=_STAMP_FIX)
    if parsed.corpus is not None:
        raise UsageError(
            "--corpus is not served by ow out stamp: a stamp reads only the JobDir", fix=_STAMP_FIX
        )
    built = stamp_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        job=None if parsed.job is None else Path(str(parsed.job)),
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_stamped(built), ensure_ascii=False) + "\n")
    else:
        for line in _stamp_lines(built):
            stdout.write(line + "\n")
    return 0


def _normalize(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    from omniweave_core.out.report import STAGES  # noqa: PLC0415 -- only this verb pays

    _refuse_unserved(parsed, verb="ow out normalize", fix=_NORMALIZE_FIX)
    if parsed.corpus is not None:
        raise UsageError(
            "--corpus is not served by ow out normalize: it reads only the JobDir",
            fix=_NORMALIZE_FIX,
        )
    if parsed.stage is not None and parsed.stage not in STAGES:
        raise UsageError(f"--stage is one of {', '.join(STAGES)}", fix=_NORMALIZE_FIX)
    built = normalize_report(
        cwd=cwd,
        env=env,
        explicit=_explicit(parsed),
        job=None if parsed.job is None else Path(str(parsed.job)),
        stage=parsed.stage,
        unit=parsed.unit,
        construct=parsed.construct,
    )
    if parsed.render == "json":
        stdout.write(json.dumps(_normalized(built), ensure_ascii=False) + "\n")
    else:
        for line in _normalize_lines(built, parsed.stage):
            stdout.write(line + "\n")
    return 0


def _list(
    parsed: argparse.Namespace,
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    del stderr
    _refuse_unserved(parsed, verb="ow out list", fix=_LIST_FIX)
    listing = artifacts_report(
        cwd=cwd, env=env, explicit=_explicit(parsed), slug=parsed.slug, corpus=parsed.corpus
    )
    if parsed.render == "json":
        rows = [_artifact(one) for one in listing.artifacts]
        stdout.write(json.dumps(rows, ensure_ascii=False) + "\n")
    else:
        for line in _artifact_lines(listing, parsed.slug):
            stdout.write(line + "\n")
    return 0


_VERBS: Final[Mapping[str, Callable[..., int]]] = {
    "out.targets": _targets,
    "out.constructs": _constructs,
    "out.scaffold": _scaffold,
    "out.check": _check,
    "out.compile": _compile,
    "out.verify": _verify,
    "out.back": _back,
    "out.assets": _assets,
    "out.stamp": _stamp,
    "out.normalize": _normalize,
    "out.list": _list,
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


def compile_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    job: Path | None,
    accept_manual: bool,
) -> CompileReport:
    """Rulings 16-20: one compile over one JobDir, lowered in an S4 worker."""
    import sys  # noqa: PLC0415 -- only this verb pays

    from omniweave_core import config  # noqa: PLC0415
    from omniweave_core.canonical import sha256_canonical  # noqa: PLC0415
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.drivers.licence import restriction_mask  # noqa: PLC0415
    from omniweave_core.host import subproc  # noqa: PLC0415
    from omniweave_core.host.activate import construct  # noqa: PLC0415
    from omniweave_core.locks import store_write_lock  # noqa: PLC0415
    from omniweave_core.model.records import Producer  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.compile import CompileV1  # noqa: PLC0415
    from omniweave_core.out.job import ILBundle, Job  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.artifact import (  # noqa: PLC0415
        SqliteArtifactStore,
        ensure_producer,
    )
    from omniweave_core.store.cites import SqliteCiteResolver  # noqa: PLC0415
    from omniweave_core.store.ledger import SqliteAssetLedger  # noqa: PLC0415

    from omniweave.run.operators.parse import worker_env  # noqa: PLC0415
    from omniweave.run.out_compile import (  # noqa: PLC0415
        CompileHost,
        CompileWorker,
        compile_artifact,
        plan_of,
        store_cas,
    )
    from omniweave.surface.ingest import root_of  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    job_dir = cwd if job is None else (job if job.is_absolute() else cwd / job)
    scaffolded = Job.load(job_dir).plan
    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    driver, card = _one_card(_discover(resolved, env).cards, scaffolded.target)
    table = load_table(Path(driver.source), card)
    effective = driver.config.effective()
    compiler = cast("CompileV1", construct(driver, effective))
    store = store_of(resolved, scaffolded.corpus, cwd=cwd)
    blobs = store_cas(store)
    clock = SystemClock()
    lowering = CompileWorker(
        card=driver,
        effective_config=effective,
        blobs=blobs,
        tmp=_cache_root(resolved, cwd) / "tmp" / "compile",
        settings=subproc.HostSettings.from_config(resolved),
        executable=sys.executable,
        env=worker_env(),
        address=subproc.local_address(
            f"ow-{os.getpid()}-compile-{scaffolded.slug}-{scaffolded.artifact_gen}"
        ),
        now_ms=lambda: clock.monotonic_ns() // 1_000_000,
    )
    producer = Producer(
        operator=driver.identity.id,
        op_version=driver.identity.schema_version,
        code_fingerprint="",
        options_digest=bytes.fromhex(sha256_canonical(dict(effective))),
    )
    lock = store_write_lock(store, now_ns=clock.wall_ns)
    with store_sqlite.StoreThread(lambda: store_sqlite.connect(store), lock=lock) as thread:
        ledger = SqliteAssetLedger(thread, blobs, job_dir=job_dir)
        bundle = ILBundle.load(job_dir / "il", carrier=compiler.carrier, constructs=table)
        plan = plan_of(
            scaffolded, bundle=bundle, constructs=table, ledger=ledger, draft=accept_manual
        )
        producer_id = cast(
            "int",
            thread.run(
                store_sqlite.Unit(
                    name="out.compile.producer",
                    run=lambda connection: ensure_producer(connection, producer),
                    cost_class="free",
                )
            ),
        )
        compiled = compile_artifact(
            job_dir,
            compiler,
            plan,
            host=CompileHost.of(
                driver,
                card,
                producer_id=producer_id,
                barred_mask=restriction_mask(
                    cast("tuple[str, ...]", resolved.get("licence.deny_restrictions"))
                ),
            ),
            constructs=table,
            ledger=ledger,
            cites=SqliteCiteResolver(thread, corpus=plan.corpus),
            artifacts=SqliteArtifactStore(thread, clock=clock),
            blobs=blobs,
            lowering=lowering,
            output_root=root_of(resolved, "roots.output", cwd),
        )
    return _compile_summary(job_dir, plan, compiled)


def _compile_summary(job_dir: Path, plan: Plan, compiled: Compiled) -> CompileReport:
    """Ruling 20: the compile's status and exit, and the sealed row when there is one."""
    from omniweave_core.out.receipt import console_line  # noqa: PLC0415
    from omniweave_core.out.report import OutReport, report_path  # noqa: PLC0415

    sealed = compiled.sealed
    row = None if sealed is None else sealed.row
    postflight = None
    if compiled.receipt is not None:
        final = OutReport.load(report_path(job_dir, "final"))
        introduced = 0 if final is None else final.gate()[1]
        postflight = console_line(compiled.receipt, introduced)
    return CompileReport(
        target=plan.target,
        slug=plan.slug,
        delivery=plan.delivery,
        status=compiled.status.value,
        exit=compiled.exit,
        artifact_gen=None if row is None else row.artifact_gen,
        path=None if compiled.path is None else str(compiled.path),
        sha256=None if row is None else row.sha256,
        hit=sealed is not None and sealed.hit,
        postflight=postflight,
        restricted=tuple(
            RestrictedItem(what=one.what, id=one.id, bits=one.bits, cite=one.cite)
            for one in compiled.restricted
        ),
    )


def _compiled(built: CompileReport) -> dict[str, Any]:
    return {
        "target": built.target,
        "slug": built.slug,
        "delivery": built.delivery,
        "status": built.status,
        "exit": built.exit,
        "artifact_gen": built.artifact_gen,
        "path": built.path,
        "sha256": built.sha256,
        "hit": built.hit,
        "postflight": built.postflight,
        "restricted": [
            {"what": one.what, "id": one.id, "bits": one.bits, "cite": one.cite}
            for one in built.restricted
        ],
    }


def _compile_lines(built: CompileReport) -> list[str]:
    if built.path is None:
        lines = [f"gate {built.status}: nothing was lowered (exit {built.exit})"]
        lines += [
            f"  barred {one.what} {one.cite or one.id}: restriction bits {one.bits}"
            for one in built.restricted
        ]
        if built.status == "manual-required":
            return [*lines, "a draft: ow out compile --accept-manual"]
        return [*lines, "re-check: ow out check --stage final"]
    lines = [] if built.postflight is None else built.postflight.splitlines()
    named = f"{built.slug}@{built.artifact_gen}"
    if built.hit:
        return [*lines, f"lookup hit: {named} is an earlier compile's bytes, placed again"]
    return [*lines, f"sealed {named} ({built.delivery}) at {built.path}"]


def assets_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    slug: str | None,
    gen: int | None,
    slot: str | None,
    corpus: str | None,
) -> AssetsReport:
    """Ruling 23: one artefact's ledger, or one slot's users and owners, from one store."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.artifact import SqliteArtifactStore  # noqa: PLC0415

    from omniweave.surface.opening import corpus_for  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(resolved, [], corpus, verb="ow out assets")
    store = store_of(resolved, name, cwd=cwd)
    with store_sqlite.StoreThread(lambda: store_sqlite.connect_readonly(store)) as thread:
        artifacts = SqliteArtifactStore(thread, clock=SystemClock())
        if slot is not None:
            users, owners = artifacts.slot_use(slot)
            return AssetsReport(
                slug=None,
                artifact_gen=None,
                slot="asset-slot:" + slot,
                users=tuple(SlotUser(u.slug, u.artifact_gen, u.role, u.units) for u in users),
                owners=tuple(SlotOwner(o.doc_ord, o.uri, o.asset_id) for o in owners),
            )
        assert slug is not None  # noqa: S101 -- `_assets` gives exactly one of the two
        newest = artifacts.latest(slug)
        if newest == 0:
            raise NotFoundError(
                f"no artefact {slug!r} is sealed in corpus {name!r}",
                fix=f"ow out list --corpus {name}",
            )
        row = artifacts.get(slug, newest if gen is None else gen)
        frozen = artifacts.assets(row.artifact_id)
    return AssetsReport(
        slug=slug,
        artifact_gen=row.artifact_gen,
        slot=None,
        assets=tuple(
            AssetListing(
                asset_id=a.asset_id,
                sha256=a.sha256,
                slot=a.slot,
                role=a.role,
                units=a.units,
                media_type=a.media_type,
                byte_len=a.byte_len,
                doc_ord=a.doc_ord,
                licence=a.licence,
                spdx=a.spdx,
                restriction_bits=a.restriction_bits,
                restrictions=_restrictions(a.restriction_bits),
            )
            for a in frozen
        ),
    )


def _restrictions(bits: int) -> tuple[str, ...]:
    """Ruling 23: each set bit by its `Restriction` name, an unallocated one as `bit_<n>`."""
    from omniweave_ports import Restriction  # noqa: PLC0415

    names = {r.value: r.name.lower() for r in Restriction}
    return tuple(names.get(n, f"bit_{n}") for n in range(bits.bit_length()) if bits >> n & 1)


def _assets_document(built: AssetsReport) -> dict[str, Any]:
    return {
        "slug": built.slug,
        "artifact_gen": built.artifact_gen,
        "slot": built.slot,
        "assets": [
            {
                "asset_id": a.asset_id,
                "sha256": a.sha256,
                "slot": a.slot,
                "role": a.role,
                "units": list(a.units),
                "media_type": a.media_type,
                "byte_len": a.byte_len,
                "doc_ord": a.doc_ord,
                "licence": a.licence,
                "spdx": a.spdx,
                "restriction_bits": a.restriction_bits,
                "restrictions": list(a.restrictions),
            }
            for a in built.assets
        ],
        "users": [
            {"slug": u.slug, "artifact_gen": u.artifact_gen, "role": u.role, "units": list(u.units)}
            for u in built.users
        ],
        "owners": [
            {"doc_ord": o.doc_ord, "uri": o.uri, "asset_id": o.asset_id} for o in built.owners
        ],
    }


def _assets_lines(built: AssetsReport, *, explain: bool) -> list[str]:
    if built.slot is not None:
        return [
            f"{built.slot}: {len(built.users)} artefact generation(s), "
            f"{len(built.owners)} corpus document(s)",
            *(
                f"  artefact {u.slug}@{u.artifact_gen}  {u.role}  {','.join(u.units)}"
                for u in built.users
            ),
            *(f"  document d{o.doc_ord}  {o.uri}  (asset {o.asset_id})" for o in built.owners),
        ]
    named = f"{built.slug}@{built.artifact_gen}"
    if not built.assets:
        return [f"{named}: no frozen asset"]
    lines = [f"{named}: {len(built.assets)} frozen asset(s)"]
    for a in built.assets:
        lines.append(
            f"  {a.slot}  {a.role}  {','.join(a.units)}  {a.media_type}  {a.byte_len} bytes  "
            f"d{a.doc_ord}"
        )
        if explain:
            licence = a.spdx or a.licence or "no licence recorded"
            restricted = ", ".join(a.restrictions) or "none"
            lines.append(f"    licence: {licence}; restrictions: {restricted}")
    return lines


def back_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    slug: str,
    gen: int | None,
    corpus: str | None,
    entropy: Callable[[int], bytes] = os.urandom,
) -> BackReport:
    """Ruling 22: one sealed generation restored into the next one's JobDir."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.events import traceparent  # noqa: PLC0415
    from omniweave_core.operator import ULID_ENTROPY_BYTES, new_run_id  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.job import job_path  # noqa: PLC0415
    from omniweave_core.out.retain import fetch_brief, restore  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.artifact import SqliteArtifactStore  # noqa: PLC0415

    from omniweave.run.out_compile import store_cas  # noqa: PLC0415
    from omniweave.surface.opening import corpus_for  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(resolved, [], corpus, verb="ow out back")
    store = store_of(resolved, name, cwd=cwd)
    clock = SystemClock()
    with store_sqlite.StoreThread(lambda: store_sqlite.connect_readonly(store)) as thread:
        artifacts = SqliteArtifactStore(thread, clock=clock)
        newest = artifacts.latest(slug)
        if newest == 0:
            raise NotFoundError(
                f"no artefact {slug!r} is sealed in corpus {name!r}",
                fix=f"ow out list --corpus {name}",
            )
        row = artifacts.get(slug, newest if gen is None else gen)
        sealed = artifacts.units(row.artifact_id)
        assets = artifacts.ledger(row.artifact_id)
    driver, card = _one_card(_discover(resolved, env).cards, row.target)
    table = load_table(Path(driver.source), card)
    blobs = store_cas(store)
    if row.brief_digest is None:
        raise NotFoundError(
            f"{slug}@{row.artifact_gen} names no Brief, so its edit has no contract to restore",
            fix=f"ow out scaffold {row.target} --brief brief.md --slug {slug}",
        )
    brief = fetch_brief(row.brief_digest, blobs)
    run_id = new_run_id(clock, entropy(ULID_ENTROPY_BYTES))
    where = job_path(_cache_root(resolved, cwd), run_id, slug, newest + 1)
    job = restore(
        where,
        il_store_ref=row.il_store_ref,
        blobs=blobs,
        brief=brief,
        sealed=sealed,
        assets=assets,
        card=card,
        card_sha256=driver.card_sha256,
        table=table,
        slug=slug,
        artifact_gen=newest + 1,
        corpus=name,
        traceparent=traceparent(entropy(16).hex(), entropy(8).hex()),
        clock_ns=clock.wall_ns(),
    )
    return BackReport(
        slug=slug,
        from_gen=row.artifact_gen,
        artifact_gen=job.plan.artifact_gen,
        job_dir=str(where),
        run_id=run_id,
        contract_unchanged=row.constructs_digest == table.digest(),
        recorded_digest=row.constructs_digest,
        installed_digest=table.digest(),
        units=tuple(u.id for u in job.plan.units),
    )


def _backed(built: BackReport) -> dict[str, Any]:
    return {
        "slug": built.slug,
        "from_gen": built.from_gen,
        "artifact_gen": built.artifact_gen,
        "job_dir": built.job_dir,
        "run_id": built.run_id,
        "contract_unchanged": built.contract_unchanged,
        "recorded_digest": built.recorded_digest,
        "installed_digest": built.installed_digest,
        "units": list(built.units),
    }


def _back_lines(built: BackReport) -> list[str]:
    """Ruling 22: the contract line first, then what was restored and the next command."""
    if built.contract_unchanged:
        contract = (
            f"contract: unchanged since {built.slug}@{built.from_gen} ({built.installed_digest})"
        )
    else:
        contract = (
            f"contract: CHANGED: {built.slug}@{built.from_gen} was compiled against "
            f"{built.recorded_digest}, and the installed table digests to "
            f"{built.installed_digest}. No recorded table version names the rows that moved; "
            "ow out check reports what the installed table finds"
        )
    return [
        contract,
        f"restored {built.slug}@{built.from_gen} into {built.job_dir} as "
        f"{built.slug}@{built.artifact_gen} ({len(built.units)} unit(s))",
        f"edit il/, then: ow out check --stage final --job {built.job_dir}",
    ]


def verify_report(
    *, cwd: Path, env: Mapping[str, str], explicit: Path | None, job: Path | None
) -> VerifyReport:
    """Ruling 21: R1 and R7 over the sealed generation a JobDir names."""
    import sys  # noqa: PLC0415 -- only this verb pays

    from omniweave_core import config  # noqa: PLC0415
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.host import subproc  # noqa: PLC0415
    from omniweave_core.host.activate import construct  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.compile import CompileV1  # noqa: PLC0415
    from omniweave_core.out.job import Job  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.artifact import SqliteArtifactStore  # noqa: PLC0415

    from omniweave.run.operators.parse import worker_env  # noqa: PLC0415
    from omniweave.run.out_compile import CompileWorker, store_cas  # noqa: PLC0415
    from omniweave.run.out_verify import verify_artifact  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    job_dir = cwd if job is None else (job if job.is_absolute() else cwd / job)
    plan = Job.load(job_dir).plan
    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    driver, card = _one_card(_discover(resolved, env).cards, plan.target)
    table = load_table(Path(driver.source), card)
    effective = driver.config.effective()
    compiler = cast("CompileV1", construct(driver, effective))
    store = store_of(resolved, plan.corpus, cwd=cwd)
    clock = SystemClock()
    with store_sqlite.StoreThread(lambda: store_sqlite.connect_readonly(store)) as thread:
        artifacts = SqliteArtifactStore(thread, clock=clock)
        row = artifacts.get(plan.slug, plan.artifact_gen)
        units = artifacts.units(row.artifact_id)
    blobs = store_cas(store)
    named = f"{plan.slug}@{plan.artifact_gen}"
    verified = verify_artifact(
        job_dir,
        row=row,
        units=units,
        card_sha256=driver.card_sha256,
        constructs=table,
        carrier=compiler.carrier,
        blobs=blobs,
        lowering=CompileWorker(
            card=driver,
            effective_config=effective,
            blobs=blobs,
            tmp=_cache_root(resolved, cwd) / "tmp" / "compile",
            settings=subproc.HostSettings.from_config(resolved),
            executable=sys.executable,
            env=worker_env(),
            address=subproc.local_address(
                f"ow-{os.getpid()}-verify-{plan.slug}-{plan.artifact_gen}"
            ),
            now_ms=lambda: clock.monotonic_ns() // 1_000_000,
        ),
        scratch=_cache_root(resolved, cwd) / "tmp" / "verify" / named,
    )
    return VerifyReport(
        slug=plan.slug,
        artifact_gen=plan.artifact_gen,
        exit=0 if verified.passed else 8,
        r1=verified.r1,
        classes=tuple(VerifiedClass(name, held) for name, held in verified.classes.items()),
        r7=verified.r7,
        units_sealed=verified.units_sealed,
        unit_count=verified.unit_count,
    )


def _verified(built: VerifyReport) -> dict[str, Any]:
    return {
        "slug": built.slug,
        "artifact_gen": built.artifact_gen,
        "exit": built.exit,
        "r1": built.r1,
        "classes": {one.name: one.held for one in built.classes},
        "r7": built.r7,
        "units_sealed": built.units_sealed,
        "unit_count": built.unit_count,
    }


def _verify_lines(built: VerifyReport) -> list[str]:
    named = f"{built.slug}@{built.artifact_gen}"
    classes = ", ".join(f"{one.name} {one.held}" for one in built.classes)
    return [
        f"R1 retained-IL identity   {'PASS' if built.r1 else 'FAIL'}   "
        f"{named} recompiled from its retained IL: {classes}",
        f"R7 total classification   {'PASS' if built.r7 else 'FAIL'}   "
        f"{built.units_sealed} unit row(s) sealed, {built.unit_count} commissioned",
    ]


def stamp_report(
    *, cwd: Path, env: Mapping[str, str], explicit: Path | None, job: Path | None
) -> StampReport:
    """Ruling 13: one stamp over one JobDir, with the target's own carrier."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.host.activate import construct  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.compile import CompileV1  # noqa: PLC0415
    from omniweave_core.out.job import Job  # noqa: PLC0415
    from omniweave_core.out.stamp import stamp  # noqa: PLC0415

    job_dir = cwd if job is None else (job if job.is_absolute() else cwd / job)
    plan = Job.load(job_dir).plan
    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    driver, card = _one_card(_discover(resolved, env).cards, plan.target)
    table = load_table(Path(driver.source), card)
    compiler = cast("CompileV1", construct(driver, driver.config.effective()))
    stamped = stamp(job_dir, carrier=compiler.carrier, constructs=table, clock=SystemClock())
    return StampReport(
        written=stamped.written,
        units=tuple(
            StampedUnit(unit=unit, addresses=addresses)
            for unit, addresses in stamped.minted.items()
        ),
        stale_lock=stamped.stale_lock,
    )


def _stamped(built: StampReport) -> dict[str, Any]:
    return {
        "written": list(built.written),
        "units": [{"unit": u.unit, "addresses": list(u.addresses)} for u in built.units],
        "stale_lock": built.stale_lock,
    }


def _stamp_lines(built: StampReport) -> list[str]:
    lines = ["replaced a stale il/.stamp.lock"] if built.stale_lock else []
    if not built.units:
        return [
            *lines,
            "every citable, text-bearing element already has an address; nothing was written",
        ]
    minted = sum(len(u.addresses) for u in built.units)
    return [
        *lines,
        f"stamped {minted} address(es) in {len(built.written)} file(s)",
        *(f"  {u.unit}  {' '.join(u.addresses)}" for u in built.units),
        "re-check: ow out check --stage early",
    ]


def normalize_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    job: Path | None,
    stage: str | None,
    unit: str | None,
    construct: str | None,
) -> NormalizeReport:
    """Ruling 14: one normalize over one JobDir, with the target's carrier and normalizers."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.host.activate import construct as build  # noqa: PLC0415
    from omniweave_core.host.activate import normalizers  # noqa: PLC0415
    from omniweave_core.out.agentdoc import load_table  # noqa: PLC0415
    from omniweave_core.out.compile import CompileV1  # noqa: PLC0415
    from omniweave_core.out.job import Job  # noqa: PLC0415
    from omniweave_core.out.normalize import normalize  # noqa: PLC0415

    job_dir = cwd if job is None else (job if job.is_absolute() else cwd / job)
    plan = Job.load(job_dir).plan
    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    driver, card = _one_card(_discover(resolved, env).cards, plan.target)
    table = load_table(Path(driver.source), card)
    compiler = cast("CompileV1", build(driver, driver.config.effective()))
    done = normalize(
        job_dir,
        carrier=compiler.carrier,
        constructs=table,
        normalizers=normalizers(driver),
        stage=stage,
        construct=construct,
        unit=unit,
    )
    return NormalizeReport(
        written=done.written,
        changed=tuple(
            NormalizedRow(unit=one, construct=row, count=count)
            for one, rows in done.changed.items()
            for row, count in rows.items()
        ),
    )


def _normalized(built: NormalizeReport) -> dict[str, Any]:
    return {
        "written": list(built.written),
        "changed": [
            {"unit": r.unit, "construct": r.construct, "count": r.count} for r in built.changed
        ],
    }


def _normalize_lines(built: NormalizeReport, stage: str | None) -> list[str]:
    if not built.changed:
        return ["no value needed normalizing; nothing was written"]
    total = sum(r.count for r in built.changed)
    return [
        f"normalized {total} value(s) in {len(built.written)} file(s)",
        *(f"  {r.unit}  {r.construct}  x{r.count}" for r in built.changed),
        f"re-check: ow out check --stage {stage or 'early'}",
    ]


def artifacts_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    slug: str | None,
    corpus: str | None,
) -> ArtifactsReport:
    """Ruling 15: one corpus's sealed rows, read-only."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.artifact import artifact_rows  # noqa: PLC0415

    from omniweave.surface.opening import corpus_for  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(resolved, [], corpus, verb="ow out list")
    connection = store_sqlite.connect_readonly(store_of(resolved, name, cwd=cwd))
    try:
        rows = artifact_rows(connection, slug)
    finally:
        connection.close()
    return ArtifactsReport(
        corpus=name,
        artifacts=tuple(
            ArtifactListing(
                slug=row.slug,
                artifact_gen=row.artifact_gen,
                parent_artifact_gen=row.parent_artifact_gen,
                origin=row.origin,
                target=row.target,
                compile_driver=row.compile_driver,
                delivery=row.delivery,
                gate_status=row.gate_status.value,
                media_type=row.media_type,
                path=row.path,
                byte_len=row.byte_len,
                restriction_bits=row.restriction_bits,
                read_back_doc_ord=row.read_back_doc_ord,
                sealed_at_ns=row.sealed_at_ns,
            )
            for row in rows
        ),
    )


def _artifact(one: ArtifactListing) -> dict[str, Any]:
    return {
        "slug": one.slug,
        "artifact_gen": one.artifact_gen,
        "parent_artifact_gen": one.parent_artifact_gen,
        "origin": one.origin,
        "target": one.target,
        "compile_driver": one.compile_driver,
        "delivery": one.delivery,
        "gate_status": one.gate_status,
        "media_type": one.media_type,
        "path": one.path,
        "byte_len": one.byte_len,
        "restriction_bits": one.restriction_bits,
        "read_back_doc_ord": one.read_back_doc_ord,
        "sealed_at_ns": one.sealed_at_ns,
    }


def _artifact_lines(listing: ArtifactsReport, slug: str | None) -> list[str]:
    if not listing.artifacts:
        what = f"artefact {slug!r}" if slug is not None else "artefact"
        return [f"no {what} has been sealed in corpus {listing.corpus}"]
    return [
        f"{one.slug}@{one.artifact_gen}  {one.target:<8} {one.delivery:<7} {one.gate_status:<15} "
        f"{one.path}  read_back "
        + ("-" if one.read_back_doc_ord is None else f"d{one.read_back_doc_ord}")
        for one in listing.artifacts
    ]
