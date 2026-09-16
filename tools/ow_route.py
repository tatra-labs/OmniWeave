"""`ow route lint | explain | propose | promote | scoreboard`, driven from `tools/`.

**Why a `tools/` script and not a CLI in the package.** `omniweave.cli` is P7's and the argparse
tree is GENERATED from `ACTIONS` (11-repo-layout.md:246); 16-roadmap.md:34's FE5 is explicit about
what shipping a hand-written one first would cost -- *"Ship a hand-written CLI first and the
registry's arrival is a reconciliation between two surfaces that already disagree."* So this is the
sixth application of the standing pattern (ledger D25): `ow schema emit` shipped as
`tools/schemagen.py`, `ow store verify` as `store/verify.py` plus `tools/gate_crash.py`,
`ow test crash-matrix`, `ow eval perf`, `ow ingest --scope` and `ow bench` the same way. The
LIBRARY FUNCTIONS are `omniweave.route.lint.lint()` and `omniweave.route.explain.explain_rule()`;
everything here is argument parsing, an `Installation` assembled from the machine, and a printer.

## What `--strict` does, and what it cannot do

`ow route lint --strict --estimates` is 16-roadmap.md:632's P5 exit-criteria line. `--strict`
promotes check 6's warning to an error, which is the only warning the fourteen produce: 05:1001
makes `expect_unavailable = true` a warning *"rather than an error"* and 05:1002 makes check 14 its
expiry, so `--strict` is "treat the exemption as spent" and nothing else.

`--estimates` is **not implemented and says so** rather than being accepted and ignored. No line in
the plan says what it asserts; the nearest candidate is check 13's reservation comparison, which
runs unconditionally here when a `PriceBook` is present. An unrecognised flag that exits 0 is a CI
line that tests nothing, so this one exits 2.

## The `Installation` this assembles, and the three things it cannot find

`[drivers] enabled` comes from the resolved configuration; the cards come from the installed
distributions' `driver.toml` files; `[retrieval.budget]` comes from the same configuration. The
`PriceBook` does not: `.omniweave/pricebook.toml` is operator-owned (05:2390) and this repository
ships none, so check 13 reports as not-run unless `--pricebook` names one. The format domain for
check 10 is `route/detect.py`'s and 05 section 2.2 has not shipped it, so check 10 is not-run unless
`--format-domain` names a file of tokens.

Neither absence is silent: both land in `Report.not_run`, which prints on a clean run too.

## The three store-reading commands, and the number none of them may invent

`scoreboard` prints `route_scoreboard` and refuses when `route_threshold` is short a row, because
that is precisely when the view's `state` column stops meaning anything -- 15:1525, `ow doctor`
check D-12: *"a missing row makes `route_scoreboard.state` fall through to `OK`"*. A report whose
every line reads `OK` because its inputs are absent is the one output worse than no report.

`propose` requires `--divergence-micros` and has **no default**. D209: section 6.2's `PriceBook`
prices seven physical units and none of them is a unit of divergence, so the exchange rate the
objective needs has no row to read and no number nobody chose may stand in for it. Without the flag
the command exits 2 and says so.

`promote` reads a diff from `--diff` and prints what it would apply; `--apply` writes. The default
is the dry run because 05:2996 is *"Neither writes without a commit"*, and a command that writes on
the way to being read is one the reviewer meets after the fact.

Exit codes: `0` clean, `1` at least one error, `2` the command could not run.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave.route import agree as rag
from omniweave.route import demand as rd
from omniweave.route import evidence as ev
from omniweave.route import explain as rx
from omniweave.route import ledger as rlg
from omniweave.route import lint as rl
from omniweave.route import policy as rp
from omniweave.route import propose as rpz
from omniweave.route.checks import Installation
from omniweave.route.fit import render_diff
from omniweave.route.spend import PriceBook
from omniweave_core.config import SHIPPED_DRIVERS
from omniweave_core.contract import RELEASE
from omniweave_core.drivers.card import MeasuredOn, load_card
from omniweave_core.errors import OwError
from omniweave_core.store.sqlite import connect_readonly

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TextIO

    from omniweave_core.drivers.card import DriverCard

REPO = Path(__file__).resolve().parents[1]
PACKAGES = REPO / "packages"

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

COMMANDS = ("lint", "propose", "promote", "scoreboard")
"""16-roadmap.md:607's four, plus `scoreboard` -- which 05:2969 ships at release 1 beside
`route_scoreboard` and `route_threshold` and which the roadmap row's command list omits. `explain`
stays the flag it has been since W5.5a: it is `lint`'s renderer over one rule, not a second pass."""

STORE = Path(".omniweave/index.owstore")
"""`store.path`'s shipped default (`config.py:712`), relative to the working directory."""

_BUDGET_PREFIX = "retrieval.budget."
_CARD = "driver.toml"
_SIGNALS = "signals.toml"
_NA = "n/a"


def signal_specs() -> list[ev.SignalSpec]:
    """Core's registrations plus every installed provider's, by walking the workspace.

    `importlib.metadata` is the real mechanism (`evidence.installed_specs`) and is not used here,
    because `omniweave` may not import `omniweave_pdf` (tools/layers.toml) and a `tools/` script
    reading a file is not an import. The entry-point walk needs the distributions installed into
    this interpreter's environment; the workspace walk needs only a checkout, which is what a
    linter run from a repository has.
    """
    specs = list(ev.builtin_specs())
    for path in sorted(PACKAGES.glob(f"*/src/*/{_SIGNALS}")):
        provider = _provider_of(path)
        specs.extend(
            ev.load_signals(
                path.read_bytes(), provider=provider, origin=str(path.relative_to(REPO))
            )
        )
    return specs


def _provider_of(path: Path) -> str:
    """`packages/omniweave-pdf/src/omniweave_pdf/signals.toml` -> `pdfium`.

    The provider NAME is the ENTRY POINT's, not the distribution's and not the package directory's:
    `omniweave-pdf`'s `pyproject.toml` declares `[project.entry-points."omniweave.signals"]` with
    `"pdfium" = "omniweave_pdf"`, and `officexml` sits the same way under `omniweave-office`. Two
    names differ from their directory and both of them are in the day-one registry, so deriving the
    provider from the path would put `pdf` and `office` into every `read_set` triple -- and
    `route_signal` is keyed on `(key, signal_version)` with the provider's version, so the wrong
    name is a wrong cache namespace rather than a cosmetic slip.

    `importlib.metadata` would answer this too and is what `evidence.installed_specs()` uses; this
    reads the source `pyproject.toml` for `signal_specs()`'s reason -- a checkout is enough.
    """
    project = path.parents[2] / "pyproject.toml"
    body = tomllib.loads(project.read_text("utf-8"))
    points = body.get("project", {}).get("entry-points", {}).get("omniweave.signals", {})
    for name, target in points.items():
        if isinstance(name, str) and str(target).replace("-", "_") == path.parent.name:
            return name
    return path.parent.name.removeprefix("omniweave_")


def installed_cards() -> dict[str, DriverCard]:
    """Every first-party `driver.toml` in the workspace, keyed by `identity.id`.

    A `Tombstone` is skipped rather than reported: a tombstoned driver is one the framework refuses
    to load at all (04 section 7.5), so it is not "installed" for check 6's purposes and pretending
    otherwise would turn a refusal into a lint pass.
    """
    cards: dict[str, DriverCard] = {}
    for path in sorted(PACKAGES.glob(f"*/src/*/{_CARD}")):
        if "conform" in path.parts:  # the conformance kit's template, not a driver
            continue
        loaded = load_card(path.read_bytes(), origin="entry_point", source=str(path))
        identity = getattr(loaded, "identity", None)
        if identity is not None:
            cards[identity.id] = loaded  # type: ignore[assignment] -- narrowed by `identity`
    return cards


def retrieval_budget() -> dict[str, object]:
    """`[retrieval.budget]`'s three keys at their declared defaults.

    Defaults and not a resolved `Config`, because check 3's subject is the shipped arrangement: an
    operator who has overridden `query_ms` gets their own number from `ow doctor`, and a linter run
    in a repository has no `.omniweave/` to resolve against.
    """
    from omniweave_core.config import _DECLARATIONS  # noqa: PLC0415 -- a private roster, read once

    return {key.name: key.default for key in _DECLARATIONS if key.name.startswith(_BUDGET_PREFIX)}


def installation(*, pricebook: Path | None) -> Installation:
    book = None
    if pricebook is not None:
        book = _read_book(pricebook)
    return Installation(
        enabled=frozenset(SHIPPED_DRIVERS),
        cards=installed_cards(),
        book=book,
        retrieval=retrieval_budget(),
    )


def _read_book(path: Path) -> PriceBook:
    """`.omniweave/pricebook.toml` -> a `PriceBook`. One `tomllib.load` and a `Decimal` per rate."""
    body = tomllib.loads(path.read_text("utf-8"))
    rates = {
        table: {dim: Decimal(str(value)) for dim, value in entries.items()}
        for table, entries in body.items()
        if isinstance(entries, dict)
    }
    return PriceBook(
        version=int(body.get("version", 1)),
        currency=str(body.get("currency", "USD")),
        effective_from=str(body.get("effective_from", "")),
        rates=rates,  # type: ignore[arg-type]
    )


def _policy(paths: Sequence[Path], registry: ev.SignalRegistry) -> rp.RoutePolicy:
    """The builtin layer, plus any `--layer` the caller named, compiled against the registry.

    The builtin layer is always first and always present: 05:936 makes merge a concatenation with
    the higher layer prepended, so a site or project layer supplied here overrides rather than
    replaces -- which is what an operator linting their own overlay wants to see.
    """
    layers = [rp.builtin_layer()]
    for path in paths:
        layers.append(rp.load_layer(path.read_bytes(), layer="project", origin=str(path)))
    return rp.compile_policy(layers, registry=registry)


def _emit(out: TextIO, message: str = "") -> None:
    print(message, file=out)


# --------------------------------------------------------------------------------------------
# The three store-reading commands.
# --------------------------------------------------------------------------------------------


def _measured_on(conn: rlg.Connection, store: Path) -> MeasuredOn:
    """INV-19's ten-field provenance for a fit over an operator's own decision log.

    Seven fields are `"n/a"` and that is the type's own instruction. 04:781: *"A pure-code path
    writes the literal `"n/a"` where a field does not apply -- a None-equivalent that is still a
    value."* There are no weights, no runtime and no prompt in a PAVA fit over stored
    rows; what there IS is a corpus, and `meta.corpus_id` is its identity, so `corpus_digest` reads
    the store rather than being a second `"n/a"` beside a corpus that exists.
    """
    row = conn.execute("SELECT v FROM meta WHERE k = 'corpus_id'").fetchall()
    corpus_id = str(row[0][0]) if row and isinstance(row[0], tuple | list) else _NA  # type: ignore[index]
    return MeasuredOn(
        weights=_NA,
        weights_revision=_NA,
        runtime=_NA,
        runtime_version=_NA,
        sampling=_NA,
        prompt_version=_NA,
        hardware=_NA,
        corpus=str(store),
        corpus_digest=corpus_id,
        harness_version=RELEASE,
    )


def _scoreboard(conn: rlg.Connection, out: TextIO, *, slice_key: str) -> int:
    """`route_scoreboard`, read and printed. Refuses on a short `route_threshold`.

    D-12's condition (15:1525) checked before the rows are printed rather than after: every `state`
    the view produces with a threshold row missing is `'OK'`, so printing first and warning second
    would put a wall of green in front of an operator and the reason for it underneath.
    """
    missing = rlg.missing_thresholds(conn)
    if missing:
        _emit(out, f"ow route scoreboard: route_threshold is missing {', '.join(missing)}.")
        _emit(out, "  A missing row makes the view's comparison NULL, and NULL falls through to")
        _emit(out, "  'OK' -- so every slice would read OK for the reason it should not. D-12.")
        return EXIT_NOT_RUN
    rows = rlg.scoreboard(conn, slice_key=slice_key)
    for line in rag.scoreboard_legend():
        _emit(out, line)
    _emit(out)
    for row in rows:
        _emit(out, row.render())
    counts = {state: sum(row.state == state for row in rows) for state in rlg.STATES}
    _emit(out)
    _emit(
        out,
        f"ow route scoreboard: {len(rows)} slice/rule/driver rollup(s), "
        + ", ".join(f"{count} {state}" for state, count in counts.items()),
    )
    return EXIT_CLEAN


def _propose(
    conn: rlg.Connection,
    out: TextIO,
    policy: rp.RoutePolicy,
    *,
    store: Path,
    slice_key: str,
    divergence_micros: float,
    diff_path: str,
) -> int:
    """Fit every fittable threshold against every slice, and emit the diff a human commits.

    The unfittable thresholds are printed first and not dropped. A threshold `ow route propose`
    never mentions reads, to an operator holding the `[thresholds]` block, as one the fitter
    considered and had nothing to say about -- which is a different fact from one it structurally
    cannot move.
    """
    for name, why in rpz.unfittable(policy):
        _emit(out, f"unfittable  {name:<26} {why}")
    outcomes = rpz.propose(
        policy,
        rlg.scoreboard(conn, slice_key=slice_key),
        observe=lambda key, signal: rlg.observations(conn, slice_key=key, signal=signal),
        measured_on=_measured_on(conn, store),
        divergence_micros=divergence_micros,
    )
    for outcome in outcomes:
        _emit(out, outcome.render())
    proposals = [one.proposal for one in outcomes if one.proposal is not None]
    diff = render_diff(proposals, path=diff_path, current=policy.thresholds)
    if diff:
        _emit(out)
        for line in diff:
            _emit(out, line)
    _emit(out)
    _emit(
        out,
        f"ow route propose: {len(outcomes)} pass(es), {len(proposals)} proposal(s) over "
        f"{len({one.slice_key for one in outcomes})} slice(s)",
    )
    return EXIT_CLEAN


def _promote(out: TextIO, *, diff: Path | None, target: Path | None, apply: bool) -> int:
    """Apply a reviewed diff to the file it names. Dry by default; `--apply` writes.

    The file rewritten is the one the diff's own `--- a/<path>` line names, resolved against the
    working directory, unless `--target` overrides it. The override exists because a diff emitted
    against `.omniweave/policy.d/route.toml` in one checkout is reviewed in another, and refusing
    to apply it there would make the review a thing that can only happen in one directory.
    """
    if diff is None:
        _emit(out, "ow route promote: --diff names the reviewed diff to apply.")
        return EXIT_NOT_RUN
    try:
        patch = rpz.parse_diff(diff.read_text("utf-8").splitlines())
    except OwError as exc:
        _emit(out, f"ow route promote: {exc}")
        _emit(out, f"  fix: {exc.fix}")
        return EXIT_NOT_RUN
    path = target if target is not None else Path(patch.path)
    if not path.is_file():
        _emit(out, f"ow route promote: the diff names {patch.path}, which is not a file here.")
        _emit(out, "  --target names the file to rewrite when the review happens elsewhere.")
        return EXIT_NOT_RUN
    for comment in patch.comments:
        _emit(out, f"#  {comment}")
    before = path.read_text("utf-8")
    try:
        after = rpz.apply_patch(before, patch)
    except OwError as exc:
        _emit(out, f"ow route promote: {exc}")
        _emit(out, f"  fix: {exc.fix}")
        return EXIT_FAIL
    for change in patch.changes:
        _emit(out, f"{'apply' if apply else 'would apply'}  {change.render()}  in {path}")
    if apply:
        path.write_text(after, encoding="utf-8", newline="")
    _emit(out)
    _emit(
        out,
        f"ow route promote: {len(patch.changes)} change(s) "
        + (f"written to {path}; commit it" if apply else "not written; re-run with --apply"),
    )
    return EXIT_CLEAN


def _lint(
    args: argparse.Namespace, out: TextIO, policy: rp.RoutePolicy, registry: ev.SignalRegistry
) -> int:
    """The fourteen checks over the compiled policy and the assembled `Installation`."""
    domain = None
    if args.format_domain is not None:
        domain = tuple(
            token
            for token in args.format_domain.read_text("utf-8").split()
            if token and not token.startswith("#")
        )
    report = rl.lint(
        policy,
        registry=registry,
        format_domain=domain,
        installation=installation(pricebook=args.pricebook),
    )
    for line in report.render():
        _emit(out, line)
    _emit(out)
    errors = [f for f in report.findings if f.severity == "error"]
    warnings = [f for f in report.findings if f.severity == "warning"]
    _emit(
        out,
        f"ow route lint: {len(policy.rules)} rule(s), {len(errors)} error(s), "
        f"{len(warnings)} warning(s), {len(report.undecided)} undecidable, "
        f"{len(report.not_run)} check(s) not run",
    )
    if errors or (args.strict and warnings):
        return EXIT_FAIL
    return EXIT_CLEAN


def _explain(
    args: argparse.Namespace, out: TextIO, policy: rp.RoutePolicy, registry: ev.SignalRegistry
) -> int:
    """`--explain <rule-id>`: five derived facts, or the rule id that is not one."""
    demand = rd.compile_demand(policy, registry=registry)
    try:
        explanation = rx.explain_rule(
            policy, args.explain, registry=registry, demand=demand, formats=args.formats
        )
    except KeyError as exc:
        _emit(out, f"ow_route: {exc.args[0]}")
        return EXIT_NOT_RUN
    for line in explanation.render():
        _emit(out, line)
    return EXIT_CLEAN


def _over_store(args: argparse.Namespace, out: TextIO, policy: rp.RoutePolicy) -> int:
    """`propose` and `scoreboard`: the two commands that open the store. One connection each.

    Read-only, because neither writes: 05:2988 says `ow route propose` *"emits a **TOML diff a
    human commits**"* and the scoreboard is a view. `connect_readonly` refuses a path that does
    not exist rather than creating one, which is why the `is_file()` check below reads as a
    friendlier message and not as the guard -- the guard is the store module's.
    """
    if args.command == "propose" and args.divergence_micros is None:
        _emit(out, "ow route propose: --divergence-micros has no default and needs one.")
        _emit(out, "  Section 6.2's PriceBook prices seven physical units and none of them is a")
        _emit(out, "  unit of divergence, so the objective's exchange rate has no row to read.")
        _emit(out, "  A default here would put a number nobody chose in every proposal. D209.")
        return EXIT_NOT_RUN
    if not args.store.is_file():
        _emit(out, f"ow route {args.command}: no store at {args.store}; --store names another.")
        return EXIT_NOT_RUN
    conn = connect_readonly(args.store)
    try:
        if args.command == "scoreboard":
            return _scoreboard(conn, out, slice_key=args.slice_key)
        return _propose(
            conn,
            out,
            policy,
            store=args.store,
            slice_key=args.slice_key,
            divergence_micros=args.divergence_micros,
            diff_path=args.diff_path,
        )
    finally:
        conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow_route",
        description="ow route lint -- the fourteen checks of 05-ingest-and-routing.md section 4.5.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="lint",
        choices=COMMANDS,
        help="lint (the default), propose, promote or scoreboard",
    )
    parser.add_argument("--store", type=Path, default=STORE, help="the .owstore to read")
    parser.add_argument("--slice", dest="slice_key", default="", help="one slice_key")
    parser.add_argument(
        "--divergence-micros",
        type=float,
        help="what one whole unit of avoided divergence is worth. NO DEFAULT (D209)",
    )
    parser.add_argument("--diff", type=Path, help="promote: the reviewed diff to apply")
    parser.add_argument("--target", type=Path, help="promote: rewrite this file, not the diff's")
    parser.add_argument("--apply", action="store_true", help="promote: write the file")
    parser.add_argument(
        "--diff-path",
        default=".omniweave/policy.d/route.toml",
        help="propose: the path the emitted diff names",
    )
    parser.add_argument("--layer", type=Path, action="append", default=[], help="an overlay TOML")
    parser.add_argument(
        "--pricebook", type=Path, help="a pricebook TOML; without it check 13 is skipped"
    )
    parser.add_argument(
        "--format-domain",
        type=Path,
        help="one format token per line; without it check 10 is skipped",
    )
    parser.add_argument("--strict", action="store_true", help="a warning fails the run")
    parser.add_argument("--explain", metavar="RULE_ID", help="print one rule's five derived facts")
    parser.add_argument(
        "--formats",
        metavar="TOKEN",
        action="append",
        default=[],
        help="resolve providers for these format tokens too; 05:2224's block.type-on-pdf view",
    )
    parser.add_argument("--estimates", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None, *, writer: TextIO | None = None) -> int:
    """`0` clean, `1` an error, `2` the command could not run."""
    args = _parser().parse_args(argv)
    out = writer if writer is not None else sys.stdout
    if args.estimates:
        _emit(out, "ow_route: --estimates is not implemented; no line in the plan says what it")
        _emit(out, "          asserts. Check 13's reservation comparison runs with --pricebook.")
        return EXIT_NOT_RUN

    if args.command == "promote":
        return _promote(out, diff=args.diff, target=args.target, apply=args.apply)

    registry = ev.build_registry(signal_specs())
    policy = _policy(args.layer, registry)

    if args.command in ("propose", "scoreboard"):
        return _over_store(args, out, policy)

    if args.explain:
        return _explain(args, out, policy, registry)
    return _lint(args, out, policy, registry)


if __name__ == "__main__":
    raise SystemExit(main())
