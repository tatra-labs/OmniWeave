"""`ow add <src>...`: roster the sources, drain them in-process, and report. 10 section 6, row 4.

10:1113-1117 gives `ow_add` three steps: *"(a) writes `unit` rows plus one `ingest_scope` row in a
single transaction, enqueue-before-lock; (b) spawns a detached `ow ingest --scope <scope_id>`
child ...; (c) polls the roster to its deadline and reports what completed, what remains"*. The
server can do only (a) (D554): it may not import the router and it has no detached spawn. The CLI
verb has neither obstacle, because it is in `omniweave`. So this module runs all three, in one
process:
- **(a)** is `acquire.add_sources()`, the call `ow_add` makes;
- **(b)** is `run.ingest.ingest()` over the same resolved paths, the drain `ow ingest <path>`
  runs, called rather than spawned;
- **(c)** is a read of each queued unit's state after the drain, which is the roster the poll
  would have read. There is no deadline to reach: the drain returns when it is done.

(a) still comes first and commits on its own, which is 07:2730's *"enqueue before attempting the
lock"*: a drain that dies leaves the roster behind, and the next `ow ingest` finds it.

**What is served**, by flag:
- `--corpus N`: one declared corpus, or `[serve] default_corpus`, as `ow query` resolves it.
- `--dry-run`: (a) walks and writes nothing, and nothing is drained. Exit 0 (18:1169).
- `--render text` (the default) and `--render json`: the `add-out-v1` object, `ow_add`'s wire
  form, with `schema` first (10:1530).
- `--quiet`: the count queued, 10:1543's scalar.
- `--offline`: routing's `ProbeEnv.offline`, so a card with `[hardware] needs_network = true`
  does not resolve (04:150, D631). No `acquire` connector fetches anything anyway.
- `--json-errors`: 18:898's object on stderr, through `switches.report()`.
- `[ingest] password_file`, read from the config, not a flag (ADR-15 D15.3): a unit it maps gets
  its password, and a failed `encrypted` one whose file did not change is queued again, which is
  what makes gate 9's `ow add <path>` fix for it a fix.
- `[ingest] max_parts`, likewise the config's (D644): a failed unit `gate.too-many-parts` refused
  is queued again, unchanged, once the cap admits the count its decision recorded.

**What is refused by name**, each exit 1, because a flag parsed and ignored answers a different
question than the one asked (`ow query`'s rule, D614):
- `--allow-cost`: nothing in this build is priced (D562), so there is no deferral to approve;
- `--schema`: nothing reads `unit.schema_requested`;
- `--allow-egress`: no `acquire` connector fetches anything (02:329), and a URL source is refused
  for the same reason;
- `--wait`: the drain is synchronous, so there is no deadline to wait to;
- `--render jsonl` and `--render rows`, which have no writer, and `--quiet` with `--render`.
- `--verbose`, and any other global flag `switches.READS` does not give `add` (D631).

Exits are 10:1425's `0/5/6/7`, plus 1 for usage and 2 for a corpus that is not declared. 5 is
never reached, because nothing is deferred for budget. 6 is a source outside the corpus's source
root (`OW-A-007`), and 7 is the store's write lock held past its wait.

**64 is a driver that is not installed** (D887, 11-repo-layout.md section 2.4's minimum profile:
*"the 'no driver for `.pdf`' refusal **naming `pip install omniweave-pdf`**"*). A `no_driver` unit
whose media type a first-party distribution reads (`INSTALLS`), and whose distribution is not
installed, is pending with `approve = "pip install <distribution>"`. When nothing completed and
EVERY pending unit is such a unit, the add is refused with `CapabilityMissing` (`OW-D-009`,
`OW_DRIVER_FORMAT_UNSUPPORTED`, exit 64) naming the install, then the `ow ingest` that reads the
units it left at `identified` -- a second `ow add` would count them `unchanged`. A driver that IS
installed and still routes nothing (not enabled, or a licence tier not allowed) stays 02 section
7.4's exit 0: that cause is configuration, which `ow doctor` names, and no install fixes it.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, TextIO
from urllib.parse import unquote, urlsplit

from omniweave_core.config import load
from omniweave_core.errors import CapabilityMissing, NotFoundError, OwError, UsageError

from omniweave.surface.ingest import contained, passwords_of, root_of
from omniweave.surface.query import parse
from omniweave.surface.serve import stores
from omniweave.surface.startup import corpora, declared_corpus
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.acquire import Added
    from omniweave_core.config import Config

    from omniweave.run.manifest import Trigger
    from omniweave.run.passwords import Passwords

__all__ = [
    "ADD_WORD",
    "INSTALLS",
    "REASONS",
    "SCHEMA_VERSION",
    "TEXT_PENDING_MAX",
    "add_report",
    "main",
]

ADD_WORD: Final[str] = "add"

SCHEMA_VERSION: Final[int] = 1

TEXT_PENDING_MAX: Final[int] = 32
"""How many `pending` rows the text render lists; the rest are counted. `--render json` lists all
of them: D557's cap is for an MCP text block, and stdout is not one."""

REASONS: Final[dict[str, str]] = {
    "identified": "no_driver",
    "planned": "not_parsed",
    "failed": "failed",
}
"""`pending[].reason` by the unit's state after the drain. `identified` is where a unit no enabled
driver reads stops (run.ingest's `UNROUTED`), and `planned` is a routed unit the parse did not
reach. Any other state is one the drain did not take the unit past, which is `not_drained`."""

NOT_DRAINED: Final[str] = "not_drained"
DRY_RUN: Final[str] = "dry_run"

NO_DRIVER: Final[str] = "no_driver"

_PDF: Final = ("application/pdf",)
_OFFICE: Final = (
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/rtf",
    "application/epub+zip",
    "text/csv",
)
_TEXT: Final = (
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/markdown",
    "text/plain",
    "application/json",
    "application/jsonl",
    "application/x-ipynb+json",
    "text/tab-separated-values",
    "image/svg+xml",
)
_IMAGES: Final = ("image/png", "image/jpeg", "image/webp", "image/tiff", "image/bmp", "image/gif")

INSTALLS: Final[Mapping[str, str]] = MappingProxyType(
    {
        **dict.fromkeys(_PDF, "omniweave-pdf"),
        **dict.fromkeys(_OFFICE, "omniweave-office"),
        **dict.fromkeys(_TEXT, "omniweave-office"),
        **dict.fromkeys(_IMAGES, "omniweave-vision"),
    }
)
"""D887: media type -> the first-party distribution whose parse driver reads it, for the remedy a
`no_driver` unit names. Static, because the distribution is the one that is NOT installed, so its
card cannot be read here; `test_add_verb.py` holds it equal to the shipped cards' `[capability]
formats` in both directions. A type two distributions read names the one meant for it:
`application/pdf` is `omniweave-pdf`'s, and `omniweave-vision`'s OCR is its fallback, not its
remedy. The target packages' `read`/`back` cards are the OUT loop's read-back, never a remedy."""

_SETTLED: Final[str] = "settled"
_PIP: Final[str] = "pip install"
_COST_CLASS: Final[str] = "free"
_REFUSED_FIX: Final[str] = "omit it; this build ingests local files at no cost and waits for them"


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
    sweep_ms: int | None = None,
) -> int:
    """`ow add ...` from argv (starting at the root word). The exit is 10 section 6.2's.

    `sweep_ms` is `ow ingest`'s: the drain's quiet-poll interval, which a test shortens (D564).
    """
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(ADD_WORD, parsed)
        return _add(parsed, argv=argv, env=env, cwd=cwd, out=(stdout, stderr), sweep_ms=sweep_ms)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _add(
    parsed: argparse.Namespace,
    *,
    argv: Sequence[str],
    env: Mapping[str, str],
    cwd: Path,
    out: tuple[TextIO, TextIO],
    sweep_ms: int | None,
) -> int:
    stdout, stderr = out
    _refuse_unserved(parsed)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = _corpus(config, parsed.corpus)
    report, drain = add_report(
        config,
        name,
        parsed.source,
        cwd=cwd,
        env=env,
        dry_run=parsed.dry_run,
        offline=parsed.offline,
        argv=argv,
        sweep_ms=sweep_ms,
        trigger="cli",
        rerun=_rerun(parsed),
        verb="ow add",
    )
    if not parsed.quiet:
        #  10:1565: a long verb's progress is stderr's, so stdout stays the report alone.
        for line in drain:
            stderr.write(line + "\n")
    _refuse_uninstalled(report)
    if parsed.quiet:
        stdout.write(f"{report['queued']}\n")
    elif parsed.render == "json":
        stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    else:
        for line in _text(report, dry_run=parsed.dry_run):
            stdout.write(line + "\n")
    return 0


def add_report(
    config: Config,
    name: str,
    sources: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    dry_run: bool,
    offline: bool,
    argv: Sequence[str],
    sweep_ms: int | None,
    trigger: Trigger,
    rerun: str,
    verb: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Steps (a)-(c) for one declared corpus: the `add-out-v1` report, and the drain's progress.

    `ow add` and the SDK's `Corpus.add()` both call this (D862), so they roster, drain and report
    one way. `trigger` is the run's `run.trigger`, `rerun` the command a dry run names, and `verb`
    the name a source outside the corpus's root is refused under.
    """
    from omniweave_core.acquire import add_sources  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.modelserver import services_root  # noqa: PLC0415

    from omniweave.run import discover  # noqa: PLC0415
    from omniweave.run.ingest import parse_keys_moved  # noqa: PLC0415
    from omniweave.run.routing import max_parts_of  # noqa: PLC0415

    store = Path(stores(config, [name], cwd=cwd)[name])
    source = Path(stores(config, [name], cwd=cwd, field="source")[name])
    paths = tuple(contained(Path(raw), source=source, cwd=cwd, verb=verb) for raw in sources)
    #  ADR-15 D15.3: `[ingest] password_file`, and an encrypted unit it maps is queued again.
    #  D644: so is one `gate.too-many-parts` refused, once `[ingest] max_parts` admits its count.
    passwords = passwords_of(config, override=None, source=source, env=env, cwd=cwd)
    added = add_sources(
        store,
        paths,
        now_ns=SystemClock().wall_ns(),
        dry_run=dry_run,
        reopens=discover.reopens_of(
            None if passwords is None else passwords.reopens,
            _raised(store, max_parts=max_parts_of(config)),
        ),
    )
    states: dict[str, str] = {}
    completed: list[dict[str, Any]] = []
    drain: tuple[str, ...] = ()
    installs: dict[str, str]
    #  D930: a driver that moved its key re-parses settled units (D679), and only a run does
    #  that, so an `ow add` over unchanged files still opens one when a key moved.
    if not dry_run and (added.queued or parse_keys_moved(store, config, offline=offline)):
        drain = _drain(
            store,
            config,
            roots=(source, cwd),
            paths=paths,
            argv=argv,
            sweep_ms=sweep_ms,
            offline=offline,
            passwords=passwords,
            services_root=services_root(env),
            trigger=trigger,
        )
        states = _states(store, added.queued)
        completed = _completed(store, [uri for uri in added.queued if states.get(uri) == _SETTLED])
        installs = _installs(store, added.queued)
    else:
        installs = {}
    built = _report(name, added, states, completed, dry_run=dry_run, rerun=rerun, installs=installs)
    return built, drain


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    """Every flag this build parses and cannot honour, refused by name, before anything is read."""
    named = [
        flag
        for flag, value in (
            ("--allow-cost", parsed.allow_cost),
            ("--schema", parsed.schema),
            ("--allow-egress", parsed.allow_egress),
            ("--wait", parsed.wait),
        )
        if value is not None
    ]
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by this build; adding without it "
            "would do something other than what was asked",
            fix=_REFUSED_FIX,
        )
    if parsed.quiet and parsed.render != "text":
        raise UsageError(
            "--quiet and --render are exclusive (10:1546)", fix="pass one of them, not both"
        )
    for raw in parsed.source:
        if "://" in raw:
            raise UsageError(
                f"{raw} is a URL, and this build has no acquire connector for URLs",
                fix="download it under the corpus source root and add that path",
            )


def _corpus(config: Config, wanted: str | None) -> str:
    """`--corpus`, else `[serve] default_corpus`. An undeclared one is 2, as it is for `ow query`.

    10:1469 says `ow add` *"creates a corpus"*. Creating one is writing `[corpora.<name>]` into an
    `omniweave.toml`, and no verb in this build writes a project's configuration (D615).
    """
    declared = corpora(config)
    if wanted is not None:
        if wanted not in declared:
            raise NotFoundError(
                f"--corpus {wanted!r} names no declared corpus; [corpora] declares "
                f"{', '.join(declared) or 'nothing'}",
                symbol="OW_CORPUS_NOT_FOUND",
                fix=f'declare [corpora.{wanted}] with path = ".omniweave/{wanted}.owstore" in '
                "omniweave.toml",
            )
        return wanted
    name, why = declared_corpus(config)
    if name is None:
        raise NotFoundError(
            f"ow add needs a corpus and none resolves: {why}",
            symbol="OW_CORPUS_NOT_FOUND",
            fix="ow add --corpus <name> ..., or set [serve] default_corpus",
        )
    return name


def _drain(
    store: Path,
    config: Config,
    *,
    roots: tuple[Path, Path],
    paths: Sequence[Path],
    argv: Sequence[str],
    sweep_ms: int | None,
    offline: bool = False,
    passwords: Passwords | None = None,
    services_root: Path | None = None,
    trigger: Trigger = "cli",
) -> tuple[str, ...]:
    """Step (b): the drain `ow ingest <path>...` runs, over the paths (a) just rostered.

    `roots` is the corpus's source root and the working directory `[roots] output` and `cache`
    resolve against when no file declared them, as `ow ingest` resolves them.
    """
    from omniweave.run.ingest import ingest  # noqa: PLC0415 -- a dry run never pays for it

    source, cwd = roots
    report = ingest(
        store,
        config=config,
        source_root=source,
        output_root=root_of(config, "roots.output", cwd),
        cache_root=root_of(config, "roots.cache", cwd),
        argv=list(argv),
        paths=paths,
        sweep_ms=sweep_ms,
        offline=offline,
        passwords=passwords,
        services_root=services_root,
        trigger=trigger,
    )
    return report.lines()


def _raised(store: Path, *, max_parts: int) -> frozenset[str]:
    """`discover.raised_parts` over a read-only connection, before anything is written (D644).

    A store that does not exist yet has refused nothing."""
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.reader import parts_refused  # noqa: PLC0415

    from omniweave.run import discover  # noqa: PLC0415

    if not store.exists():
        return frozenset()
    connection = store_sqlite.connect_readonly(store)
    try:
        return discover.raised_parts(parts_refused(connection), max_parts=max_parts)
    finally:
        connection.close()


def _states(store: Path, uris: Sequence[str]) -> dict[str, str]:
    """Step (c): where each queued unit stopped, read after the drain returned."""
    from omniweave_core.acquire import unit_states  # noqa: PLC0415

    return unit_states(store, uris)


def _installed(distribution: str) -> bool:
    """Whether `distribution` is installed in this environment. A test replaces it (D887)."""
    from importlib import metadata  # noqa: PLC0415 -- only a no_driver unit pays for it

    try:
        metadata.distribution(distribution)
    except metadata.PackageNotFoundError:
        return False
    return True


def _installs(store: Path, uris: Sequence[str]) -> dict[str, str]:
    """`uri -> distribution` for each unit an install would read (D887).

    A unit whose media type no first-party distribution reads, or whose distribution is already
    installed, has no entry: an install is not what it is waiting for. `_report` names the install
    only for a `no_driver` unit, so a settled or failed unit's entry is never read.
    """
    from omniweave_core.acquire import unit_media_types  # noqa: PLC0415

    wanted = {
        uri: INSTALLS[media]
        for uri, media in unit_media_types(store, uris).items()
        if media in INSTALLS
    }
    absent = {dist for dist in set(wanted.values()) if not _installed(dist)}
    return {uri: dist for uri, dist in wanted.items() if dist in absent}


def _refuse_uninstalled(report: Mapping[str, Any]) -> None:
    """D887: nothing completed and every pending unit waits for an install -> exit 64, named.

    A report with anything completed, or any unit pending for another reason, is answered with
    exit 0 and its `pending[].approve` rows, because the add did something or something else is
    owed. The message names the extensions, as section 2.4's *"no driver for `.pdf`"* does.
    """
    pending: list[Mapping[str, Any]] = report["pending"]
    if report["completed"] or not pending:
        return
    if not all(
        row["reason"] == NO_DRIVER and str(row["approve"]).startswith(f"{_PIP} ") for row in pending
    ):
        return
    dists = tuple(sorted({str(row["approve"]).removeprefix(f"{_PIP} ") for row in pending}))
    kinds = ", ".join(sorted({_kind(str(row["uri"])) for row in pending}))
    first = str(pending[0]["uri"])
    raise CapabilityMissing(
        f"no driver for {kinds} is installed, so {len(pending)} unit(s) stopped at identify "
        f"(first: {first}); {', '.join(dists)} reads them",
        missing=dists,
        symbol="OW_DRIVER_FORMAT_UNSUPPORTED",
        fix=f"{_PIP} {' '.join(dists)}   # then: ow ingest --corpus {report['corpus']}",
    )


def _kind(uri: str) -> str:
    """A unit's extension as the refusal names it (`.pdf`), or its file name when it has none."""
    name = PurePosixPath(unquote(urlsplit(uri).path)).name
    suffix = PurePosixPath(name).suffix.lower()
    return suffix or name


def _completed(store: Path, uris: Sequence[str]) -> list[dict[str, Any]]:
    """`add-out-v1`'s `AddCompleted` rows: each settled unit's head document, by `doc.uri`."""
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.doc import head_documents  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        return [dict(row) for row in head_documents(connection, uris)]
    finally:
        connection.close()


def _report(
    corpus: str,
    added: Added,
    states: Mapping[str, str],
    completed: Sequence[Mapping[str, Any]],
    *,
    dry_run: bool,
    rerun: str,
    installs: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """`add-out-v1`, as `ow_add` writes it, `schema` first (10:1530).

    `scope_id` is D555's text prefix, or `null` for anything but one directory, which is the
    one field that does not validate against the schema file -- and it is `ow_add`'s own.

    `installs` is `uri -> distribution` for the `no_driver` units an install would read (D887):
    their `approve` is that `pip install`, which is the command that fixes them.
    """
    to_install = installs or {}
    pending: list[dict[str, Any]] = []
    for uri in added.queued:
        if dry_run:
            reason, approve = DRY_RUN, rerun
        elif states.get(uri) == _SETTLED:
            continue
        else:
            reason = REASONS.get(states.get(uri, ""), NOT_DRAINED)
            approve = f"ow ingest --corpus {corpus}"
            if reason == NO_DRIVER and uri in to_install:
                approve = f"{_PIP} {to_install[uri]}"
        pending.append(
            {
                "uri": uri,
                "reason": reason,
                "cost_class": _COST_CLASS,
                "est_micros": 0,
                "approve": approve,
            }
        )
    return {
        "schema": SCHEMA_VERSION,
        "scope_id": added.scopes[0] if len(added.scopes) == 1 else None,
        "corpus": corpus,
        "discovered": added.discovered,
        "unchanged": added.unchanged,
        "queued": 0 if dry_run else len(added.queued),
        "skipped": added.skipped,
        "completed": list(completed),
        "pending": pending,
        "degradations": [],
        "deadline_reached": False,
    }


def _rerun(parsed: argparse.Namespace) -> str:
    """The command a dry run was pricing, without `--dry-run`: 18:1158's approving line."""
    corpus = [] if parsed.corpus is None else ["--corpus", parsed.corpus]
    return shlex.join(["ow", "add", *parsed.source, *corpus])


def _text(report: Mapping[str, Any], *, dry_run: bool) -> list[str]:
    """18:1152-1164's two-line receipt, then what is pending and the command that would run it."""
    scope = report["scope_id"] or "none"
    lines = [
        f"scope {scope}  ·  discovered {report['discovered']}  ·  unchanged {report['unchanged']}"
        f"  ·  queued {report['queued']}  ·  skipped {report['skipped']}"
    ]
    pending: list[dict[str, Any]] = report["pending"]
    if dry_run:
        lines.append(f"NOT RUN (dry run). {len(pending)} units would be queued.")
    else:
        why: dict[str, int] = {}
        for row in pending:
            why[row["reason"]] = why.get(row["reason"], 0) + 1
        shown = ", ".join(f"{count} {reason}" for reason, count in why.items())
        lines.append(
            f"completed {len(report['completed'])}   pending {len(pending)}"
            f"{f' ({shown})' if shown else ''}   deadline_reached false"
        )
    lines.extend(f"  {row['uri']}  {row['reason']}" for row in pending[:TEXT_PENDING_MAX])
    if len(pending) > TEXT_PENDING_MAX:
        lines.append(f"  ... and {len(pending) - TEXT_PENDING_MAX} more")
    for approve in dict.fromkeys(row["approve"] for row in pending):
        lines.append(f"  {approve}")
    return lines
