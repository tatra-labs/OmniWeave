"""G27(b) — the migration set: dense, unique, ordered, appliable, single-homed, append-only.

`uv run tools/gate_migrations.py --min-sqlite 3.42` is 16-roadmap.md's P2 exit-criteria line
(16-roadmap.md:441, spelled there "G27(b): numeric order onto an empty file"), and
`tools/gates.toml`'s `G27` clause `b` states the assertion in one sentence: *"migrations are dense
and unique from 0001, apply in numeric order to an empty file on MIN_SQLITE, and no migration
present in the previous tag was renamed or edited"*.

Six checks, and each has a specifying site and a distinct failure it is the only witness for:

1. **Naming** is `NNNN_<slug>.sql`, four digits (11-repo-layout.md:1188). The numeric prefix IS
   the apply order, so a name that does not carry one has no place in it.
2. **Uniqueness.** Section 5.2 is the whole reason this file exists: two PRs branch from one
   commit, each adds `0004_*.sql`, each passes in isolation because on an empty file a single
   `0004` applies cleanly, and after both merge `migration.version` — an `INTEGER PRIMARY KEY` —
   is asked to hold version 4 twice, on every store in the fleet, at ingest time, after the first
   has already committed its DDL (11-repo-layout.md:1232-1239).
3. **Density.** The prefixes are exactly `1..N`. This is the half that cannot be delegated:
   *"Duplicates would also surface from the `migration` primary key during that apply — which is a
   pleasing redundancy and not a substitute, because a gap raises nothing"* (11:1246-1247). A set
   holding `0004` and `0006` applies cleanly to an empty file and applies **out of intended
   order** on a store that received `0006` in an earlier release and `0004` in a later one.
4. **Applicability**, in numeric order, one transaction each (11:1186-1188), onto an **empty
   file**. A real temporary file and not `:memory:`, for two reasons that are the same reason:
   `journal_mode = WAL` and its `-wal`/`-shm` sidecars exist only for a file-backed database
   (07-store-and-retrieval.md:168-176), and the migrations are what a real store receives. Then
   `PRAGMA foreign_key_check` and `PRAGMA integrity_check` against the completed schema, which is
   what makes the one forward foreign key `block.decision_id → route_decision` a checked
   exception rather than an assumed one (07:257-268). The failure this catches and nothing else
   does: an index resolves its table at `CREATE INDEX`, so an index on a table a later file
   creates **aborts the migration and neither file applies** (11:1190-1191, 07:250-256).
5. **The end-of-run single-home assertion** (11:1196-1202, adr/0009-schema-single-home.md).
   `index_state` holds exactly one `schema` row whose value equals `f"{SCHEMA}.{SCHEMA_MINOR}"`
   read from `omniweave_core.contract`, and `meta` holds no `schema` key at all. The anchor is the
   END of the run and not `0001_init.sql`, because `index_state` is created by `0003_index.sql`
   (`0003_index.sql:406`) and an assertion written against `0001` is unrunnable.
6. **Append-only against the previous tag** (11:1261-1268). *"The boundary that decides whether
   renumbering is legal is the tag, not the merge."* A migration that has only ever existed on a
   branch is renumbered freely, because no store has applied it; one that has appeared in a
   published release is never renumbered and never edited, because some stores have applied it and
   `migration.version` cannot tell which. With no tag in the repository there is nothing to diff
   against, and this check then reports `SKIP (no previous tag)` **on its own line** and the gate
   still exits 0 — 16-roadmap.md's own rule is that a workflow which bounds its coverage says what
   it dropped, so a silent pass is not available.

WHO WRITES `index_state.schema`
-------------------------------
`0003_index.sql:37-38` is explicit: *"`index_state`'s and `migration`'s ROWS. The tables are
created empty here; the runner writes `index_state.schema` and one `migration` row per applied
file."* So the shipped DDL seeds no `schema` row, by design and with the design recorded, and this
gate stands in for the runner: after every migration has applied it writes the single row, exactly
once, and only if the migration set left the key unset. Two halves of check 5 therefore have teeth
against the DDL and one is true by construction, and saying which is which is the point:

* `meta` holding no `schema` key is a **property of the migrations** and is the assertion ADR-9
  exists for (`0001_init.sql:64-66`, *"`meta` NEVER gains a `schema` key"*).
* `index_state` holding **exactly one** `schema` row is a property of the migrations too: a
  migration that seeded a second home is caught here whether it collides with this gate's own
  insert or arrives as two rows in a table declared without the primary key.
* The row's **value** is compared against `contract.SCHEMA_STRING` only when the migration set
  seeded it. When this gate wrote it, the comparison would be with itself, and the report says
  which of the two happened rather than leaving the reader to assume.

No `migration` row is written. `migration.cost_class`, `resumable` and `unbackfilled_means` are
required prose a migration's author declares (11:1215-1221) and no static reader can re-derive
them; fabricating three columns to obtain a duplicate-version `IntegrityError` that check 3
already reports by name would be a second, weaker answer to a question that has an exact one.

WHY THIS GATE IMPORTS `sqlite3` AT ALL
--------------------------------------
INV-17 restricts `import sqlite3` to `omniweave_core/store/` and `pyproject.toml` carries no
`per-file-ignores` row for `tools/`, so the `noqa` below is the exemption in its narrowest form:
one line, in one file, with the reason attached. The ban's subject is production code reaching for
a second connection to a store — a second connection is a second snapshot, and INV-17 exists so
that every read of a store goes through the one boundary that can hand out a `Snapshot`. A gate
whose entire job is applying DDL to a scratch file that is deleted before it returns is the
instrument of that rule, not a violation of it: it opens no store, it holds no `Snapshot`, and the
only alternative — reading the `.sql` text — is precisely the check `tools/gate_schema_lint.py`
already is, and it catches none of `CREATE VIRTUAL TABLE`'s option arity, no `CHECK` constraint, no
trigger body that does not compile, and above all not the forward reference that is this gate's
first purpose. `tests/unit/test_migration_0001.py:31-41` takes the same exemption in the same
shape and for the same reason.

`subprocess` carries the same shape for check 6: `git` is the only reader of git history, there is
no library form of it in a zero-dependency tree, and the plan specifies the mechanism as a diff
against a tag (11:1265-1266). This gate's row in `tools/gates.toml` sets `fetch_depth = 0` for
exactly that call.

WHY THIS GATE IMPORTS FIRST-PARTY, WHICH FOUR OTHER GATES MAY NOT
-----------------------------------------------------------------
`tools/gate_layers.py`, `tools/gate_core_pure.py`, `tools/gate_importtime.py` and
`tools/gate_lazy_core.py` are asserted stdlib-only and first-party-free by
`tests/unit/test_gates_structural.py`, for the reason 02-architecture.md section 3.3 gives: they
build a graph by *"walking source rather than importing it — which also means the gate runs on a
package whose dependencies are not installed"*, and a gate that imported the tree to inspect it
would fail on exactly the broken tree it exists to diagnose. That argument does not reach here and
the opposite one does. This gate asserts nothing about an import graph; it asserts a property of
`.sql` files against two numbers that are single-homed on purpose — `MIN_SQLITE` in
`omniweave_core.limits` (07:196, "the one declared floor") and `SCHEMA`/`SCHEMA_MINOR` in
`omniweave_core.contract` (11:1198, `0003_index.sql:409-412`, *"formatted at exactly one site, in
`contract` itself"*). A transcribed copy of either would be the second home the assertion is
about. Both modules are eager, both are third-party-free (INV-2), and neither is one of G17's nine
lazy names, so importing them loads no driver, no store and no model.

Exit codes
----------
`0` the six checks hold, check 6 possibly skipped and saying so. `1` a check is false. `2` the gate
did not run — an unusable argument, a missing or empty `schema/migrations/`, or an interpreter
whose SQLite is below the floor. `1` and `2` are distinguished because CI treats both as failure
and a human needs to know which.

Specified in 11-repo-layout.md sections 5.1 and 5.2, 07-store-and-retrieval.md sections 2.1 and 3,
16-roadmap.md's P2 exit criteria (:441), adr/0009-schema-single-home.md, and `tools/gates.toml`'s
`G27` clause `b`. The FAIL output shape is 11-repo-layout.md:1270-1279 and is matched, not
approximated.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3  # noqa: TID251 — G27b's subject is DDL applied to a real file; see the docstring.
import subprocess  # noqa: TID251 — check 6 diffs against a tag and `git` is its only reader.
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave_core.contract import SCHEMA_STRING
from omniweave_core.limits import MIN_SQLITE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import TextIO

REPO = Path(__file__).resolve().parent.parent
# The DDL is `omniweave-core` PACKAGE DATA and not a repo-root directory. 11-repo-layout.md:1186
# has it "packaged with `omniweave-core` as package data, read through `importlib.resources` at use
# time", :205's tree draws it under `omniweave_core/store/` and :793 spells the path in full;
# :2304's CODEOWNERS line is the only site that anchors it at the root, and
# `_plan/_notes/build-defects.md` D12 rules for the package with the sdist evidence. Same constant,
# same reasoning and same location as `tools/gate_schema_lint.py:120`, which is the other half of
# this gate.
MIGRATIONS = (
    REPO
    / "packages"
    / "omniweave-core"
    / "src"
    / "omniweave_core"
    / "store"
    / "schema"
    / "migrations"
)

# The pathspec check 6 hands to `git`, derived from MIGRATIONS rather than written out a second
# time: a hard-coded `schema/migrations` would have kept diffing a directory that no longer exists
# after the D12 move, and would have reported SKIP-shaped silence rather than a wrong answer, which
# is worse. The move itself can never straddle a tag boundary -- it landed before this repository
# had any tag -- so the current home is the only home a diff against a tag can need.
MIGRATIONS_PATHSPEC = MIGRATIONS.relative_to(REPO).as_posix()

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

# The FAIL block's two columns, from the specified output at 11-repo-layout.md:1272-1278: the
# headline sits after an eleven-character prefix, its prose continues at that column, and a named
# file is indented two further. Written as arithmetic over the prefix so the two cannot drift.
FAIL_PREFIX = "G27b FAIL  "
FAIL_INDENT = " " * len(FAIL_PREFIX)
FILE_INDENT = FAIL_INDENT + "  "

# 11-repo-layout.md:1188, "Naming is `NNNN_<slug>.sql`, four digits". The slug is lower-case
# `[a-z0-9]` words joined by single underscores, which is what the four shipped files are: without
# pinning the slug's alphabet a name like `0004_A.SQL` would parse and the prefix would stop being
# the only thing before the first underscore.
NAME = re.compile(r"^(?P<number>[0-9]{4})_(?P<slug>[a-z0-9]+(?:_[a-z0-9]+)*)\.sql\Z")

# 07-store-and-retrieval.md:168-174, transcribed in the order that document declares load-bearing.
# `busy_timeout` is FIRST because `journal_mode = WAL` itself touches the file and can raise
# SQLITE_BUSY before the timeout is in effect (07:178-180, codegraph #238).
CONN_PRAGMAS = (
    "busy_timeout = 5000",
    "foreign_keys = ON",
    "journal_mode = WAL",
    "synchronous = NORMAL",
    "cache_size = -64000",
    "temp_store = MEMORY",
    "mmap_size = 268435456",
)
INIT_PRAGMAS = ("journal_size_limit = 67108864",)
CREATE_PRAGMAS = ("page_size = 8192", "auto_vacuum = INCREMENTAL")

# Three counts that would otherwise read as magic numbers. Each is a shape rather than a
# threshold, which is why it is named rather than tuned:
COLLISION = 2
"""Two files sharing a prefix is section 5.2's collision; more is the same defect, counted."""
STATUS_AND_PATH = 2
"""`git diff --name-status` emits at least a status and one path per line."""
VERSION_PARTS = 3
"""`major.minor.patch` -- the widest SQLite version a `--min-sqlite` value may spell."""


@dataclass(frozen=True, slots=True)
class MigrationFile:
    """One `schema/migrations/*.sql`, with its prefix parsed if the name carries one."""

    path: Path
    number: int | None
    slug: str | None

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class Failure:
    """A red check: one headline at the FAIL column plus detail already indented under it."""

    headline: str
    detail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TagView:
    """What the previous tag holds, or why there is no previous tag to hold anything.

    `files` is empty when `tag is None`, and the two are always read together: an empty set with a
    tag means that tag shipped no migrations, which is a different fact from no tag at all, and
    check 6's SKIP line is only legal for the second.
    """

    tag: str | None
    files: frozenset[str]
    reason: str | None = None


# ---------------------------------------------------------------------------
# Reading the set
# ---------------------------------------------------------------------------


def migration_files(root: Path) -> list[MigrationFile]:
    """Every `*.sql` in `root`, sorted by name, with `NNNN_<slug>.sql` parsed where it parses.

    Sorted by NAME rather than by number, because the unparsed and the duplicated both have to
    appear in a stable order in a failure message and neither has a usable number to sort on.
    """
    found: list[MigrationFile] = []
    for path in sorted(root.glob("*.sql"), key=lambda item: item.name):
        match = NAME.match(path.name)
        if match is None:
            found.append(MigrationFile(path=path, number=None, slug=None))
            continue
        found.append(
            MigrationFile(path=path, number=int(match.group("number")), slug=match.group("slug"))
        )
    return found


def label(root: Path) -> str:
    """The directory as a failure message names it: its own last two components.

    The specified FAIL output writes it `schema/migrations/` (11-repo-layout.md:1272) and the
    directory is `.../omniweave_core/store/schema/migrations`, so the last two components ARE the
    specified spelling. Rendering them rather than transcribing the literal is what keeps the
    message true when the gate is pointed at a synthetic set with `--migrations`; the header line
    prints the absolute path, so nothing is lost.
    """
    return "/".join(root.parts[-2:]) + "/"


def in_apply_order(files: Iterable[MigrationFile]) -> list[MigrationFile]:
    """The parsed files in numeric order — the order in which a store receives them."""
    return sorted(
        (item for item in files if item.number is not None),
        key=lambda item: (item.number or 0, item.name),
    )


# ---------------------------------------------------------------------------
# Checks 1 to 3: naming, uniqueness, density
# ---------------------------------------------------------------------------


def check_naming(files: Sequence[MigrationFile], root: Path) -> list[Failure]:
    """Check 1. `NNNN_<slug>.sql`, four digits (11-repo-layout.md:1188)."""
    return [
        Failure(
            headline=f"{label(root)}{item.name} is not NNNN_<slug>.sql.",
            detail=(
                FAIL_INDENT + "Naming is `NNNN_<slug>.sql`, four digits, and the numeric prefix",
                FAIL_INDENT + "IS the apply order (11-repo-layout.md:1188). A name that does not",
                FAIL_INDENT + "carry one has no place in that order, so this file is neither",
                FAIL_INDENT + "applied nor counted towards density.",
            ),
        )
        for item in files
        if item.number is None
    ]


def _duplicate_detail(
    group: Sequence[MigrationFile], next_free: int, published: Mapping[str, str]
) -> tuple[str, ...]:
    """The specified detail block for one duplicated number (11-repo-layout.md:1273-1278).

    The name column is `max(len(name)) + 2` wide, which is what makes the specimen output's two
    annotations line up; it is arithmetic rather than a literal so a third colliding file does not
    silently break the column.
    """
    width = max(len(item.name) for item in group) + 2
    lines: list[str] = []
    for item in group:
        tag = published.get(item.name)
        if tag is not None:
            note = f"(in {tag}, PUBLISHED — never renumber)"
        elif published:
            note = "(new on this branch)"
        else:
            note = "(no previous tag — publication unknown)"
        lines.append(f"{FILE_INDENT}{item.name:<{width}}{note}")
    version = group[0].number or 0
    lines.append(
        FAIL_INDENT + "migration.version is an INTEGER PRIMARY KEY, so both would insert version "
        f"{version} and the"
    )
    lines.append(FAIL_INDENT + "second would abort on every store that applied the first.")
    shipped = [item for item in group if item.name in published]
    fresh = [item for item in group if item.name not in published]
    if len(shipped) == 1 and len(fresh) == 1:
        lines.append(
            FAIL_INDENT + "fix: rebase on the default branch and rename the NEW file to "
            f"{next_free:04d}_{fresh[0].slug}.sql."
        )
        lines.append(
            FAIL_INDENT
            + f"Do not touch {shipped[0].name}: {published[shipped[0].name]} shipped it."
        )
    else:
        lines.append(
            FAIL_INDENT + "fix: rebase on the default branch and renumber the file that is new on "
            f"this branch to {next_free:04d}_<its slug>.sql."
        )
        lines.append(
            FAIL_INDENT + "A file the previous tag contains is never renumbered "
            "(11-repo-layout.md:1261-1268)."
        )
    return tuple(lines)


def check_uniqueness(files: Sequence[MigrationFile], view: TagView, root: Path) -> list[Failure]:
    """Check 2, section 5.2's collision, reported in section 5.2's own output shape."""
    numbered = in_apply_order(files)
    if not numbered:
        return []
    next_free = max(item.number or 0 for item in numbered) + 1
    published = {name: view.tag for name in view.files if view.tag is not None}
    failures: list[Failure] = []
    for number in sorted({item.number or 0 for item in numbered}):
        group = [item for item in numbered if item.number == number]
        if len(group) < COLLISION:
            continue
        count = "two" if len(group) == COLLISION else str(len(group))
        failures.append(
            Failure(
                headline=f"{label(root)} has {count} files numbered {number:04d}:",
                detail=_duplicate_detail(group, next_free, published),
            )
        )
    return failures


def check_density(files: Sequence[MigrationFile], root: Path) -> list[Failure]:
    """Check 3. The prefixes are exactly `1..N` (11-repo-layout.md:1243-1247).

    A missing `0001` is reported by this check and not by a separate "starts at one" check: the
    expected set is `range(1, max + 1)`, so a set numbered `0002..0004` reports `0001 is missing`,
    which is both true and the fix.
    """
    numbered = in_apply_order(files)
    if not numbered:
        return []
    present = {item.number or 0 for item in numbered}
    missing = sorted(set(range(1, max(present) + 1)) - present)
    if not missing:
        return []
    names = ", ".join(f"{number:04d}" for number in missing)
    verb = "is" if len(missing) == 1 else "are"
    return [
        Failure(
            headline=f"{label(root)} is not dense: {names} {verb} missing.",
            detail=(
                FAIL_INDENT + "present  " + ", ".join(f"{n:04d}" for n in sorted(present)),
                FAIL_INDENT + "A gap raises nothing at apply time: the set applies cleanly to an",
                FAIL_INDENT + "empty file and applies OUT OF INTENDED ORDER on a store that",
                FAIL_INDENT + "received the higher number in an earlier release and the lower one",
                FAIL_INDENT + "in a later one (11-repo-layout.md:1235-1239). The `migration`",
                FAIL_INDENT + "primary key cannot catch it, which is why this check is not",
                FAIL_INDENT + "delegated to it (11-repo-layout.md:1246-1247).",
                FAIL_INDENT
                + "fix: renumber down to close the gap, unless a tag contains the file.",
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Check 4: applicability, onto an empty FILE
# ---------------------------------------------------------------------------


def open_scratch(path: Path) -> sqlite3.Connection:
    """A fresh file-backed store carrying 07 section 2.1's pragmas, in 07 section 2.1's order.

    `CREATE_PRAGMAS` are interleaved right after `busy_timeout` rather than appended, and that is
    a constraint rather than a preference: `page_size` is refused once the database's journal mode
    is `wal`, so a create-time pragma applied after `journal_mode = WAL` is silently a no-op and
    the scratch file would then not be the file a store receives.

    `isolation_level = None` hands the transaction to this module, which is what lets each
    migration run in one transaction of its own (11-repo-layout.md:1186-1188) — and what
    `0001_init.sql:44-45` assumes when it says the file "opens no BEGIN".
    """
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute(f"PRAGMA {CONN_PRAGMAS[0]}")
    for pragma in CREATE_PRAGMAS:
        connection.execute(f"PRAGMA {pragma}")
    for pragma in CONN_PRAGMAS[1:]:
        connection.execute(f"PRAGMA {pragma}")
    for pragma in INIT_PRAGMAS:
        connection.execute(f"PRAGMA {pragma}")
    return connection


def _object_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return int(row[0])


def _scalar(connection: sqlite3.Connection, statement: str) -> object:
    row = connection.execute(statement).fetchone()
    return None if row is None else row[0]


def apply_one(connection: sqlite3.Connection, item: MigrationFile) -> None:
    """One migration, in one transaction, rolled back if any statement in it raises.

    The rollback is what makes the report honest about the recorded defect: an index resolving a
    table a later file creates aborts, and neither the index nor anything else in its file lands
    (11-repo-layout.md:1190-1191).
    """
    text = item.path.read_text(encoding="utf-8")
    try:
        connection.executescript(f"BEGIN;\n{text}\nCOMMIT;")
    except sqlite3.Error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def _abort_failure(
    files: Sequence[MigrationFile], item: MigrationFile, error: sqlite3.Error
) -> Failure:
    """The forward-reference report: what applied before the abort, and the rule it broke."""
    applied = [
        other.name for other in in_apply_order(files) if (other.number or 0) < (item.number or 0)
    ]
    return Failure(
        headline=f"{item.name} did not apply: {error}",
        detail=(
            FAIL_INDENT + "applied before it  " + (", ".join(applied) if applied else "(none)"),
            FAIL_INDENT + "An index resolves its table at CREATE INDEX, so an index on a table a",
            FAIL_INDENT + "later file creates aborts the migration and NEITHER FILE APPLIES",
            FAIL_INDENT + "(11-repo-layout.md:1188-1194, 07-store-and-retrieval.md:250-256). A",
            FAIL_INDENT + "view survives a forward reference lazily; an index and a foreign key",
            FAIL_INDENT + "do not.",
            FAIL_INDENT + "fix: order the files by dependency, not by date (16-roadmap.md:291).",
        ),
    )


def _not_wal_failure(mode: object) -> Failure:
    return Failure(
        headline=f"the scratch database reports journal_mode = {mode!r}, not 'wal'.",
        detail=(
            FAIL_INDENT + "07-store-and-retrieval.md:168-176 puts every store in WAL, and WAL",
            FAIL_INDENT + "with its -wal and -shm sidecars exists only for a file-backed",
            FAIL_INDENT + "database. A run reporting anything else is not applying these files",
            FAIL_INDENT + "the way a store receives them, which is the whole premise of check 4.",
        ),
    )


def apply_all(
    files: Sequence[MigrationFile], path: Path
) -> tuple[sqlite3.Connection | None, list[str], list[Failure]]:
    """Check 4. Every parsed migration, in numeric order, onto the empty file at `path`.

    Returns the live connection on success so check 5 can run against the completed schema at the
    END of the run — the anchor 11-repo-layout.md:1196 fixes, and the only anchor at which
    `index_state` exists at all.
    """
    report: list[str] = []
    connection = open_scratch(path)
    mode = _scalar(connection, "PRAGMA journal_mode")
    page = _scalar(connection, "PRAGMA page_size")
    if str(mode).lower() != "wal":
        connection.close()
        return None, report, [_not_wal_failure(mode)]
    report.append(f"  file        a real file, journal_mode = {mode}, page_size = {page}")
    before = _object_count(connection)
    for item in in_apply_order(files):
        try:
            apply_one(connection, item)
        except sqlite3.Error as error:
            connection.close()
            return None, report, [_abort_failure(files, item, error)]
        after = _object_count(connection)
        report.append(f"  {item.name:<22} applied  {after - before:>4} object(s)")
        before = after
    return connection, report, []


def check_pragmas(connection: sqlite3.Connection) -> tuple[list[str], list[Failure]]:
    """`PRAGMA foreign_key_check` and `PRAGMA integrity_check` against the completed schema.

    Against the COMPLETED schema, because that is what makes the one forward foreign key in the
    shipped order — `block.decision_id → route_decision`, `0001` naming a table `0004` creates —
    a checked exception rather than an assumed one (07-store-and-retrieval.md:257-268).
    """
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
    failures: list[Failure] = []
    if violations:
        failures.append(
            Failure(
                headline=(
                    f"PRAGMA foreign_key_check reported {len(violations)} violation(s) after the "
                    "last migration."
                ),
                detail=(
                    *(
                        FAIL_INDENT + f"{row[0]} rowid {row[1]} -> {row[2]} (fk #{row[3]})"
                        for row in violations
                    ),
                    FAIL_INDENT + "07-store-and-retrieval.md:266-268 makes this the check that",
                    FAIL_INDENT + "keeps the one forward foreign key an exception and not a hope.",
                ),
            )
        )
    if integrity != ["ok"]:
        failures.append(
            Failure(
                headline="PRAGMA integrity_check did not return ok after the last migration.",
                detail=tuple(FAIL_INDENT + line for line in integrity),
            )
        )
    verdict = "ok" if integrity == ["ok"] else "FAILED"
    clean = "clean" if not violations else f"{len(violations)} violation(s)"
    return [f"  checks      foreign_key_check {clean}, integrity_check {verdict}"], failures


# ---------------------------------------------------------------------------
# Check 5: the end-of-run single-home assertion
# ---------------------------------------------------------------------------


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _missing_home_failure(name: str) -> Failure:
    return Failure(
        headline=f"{name} does not exist after the last migration.",
        detail=(
            FAIL_INDENT + "`meta` is `0001_init.sql:61`'s and `index_state` is",
            FAIL_INDENT + "`0003_index.sql:406`'s. Section 4.1 states the two homes and ADR-9",
            FAIL_INDENT + "rules them; a set that creates neither cannot carry a SCHEMA at all.",
        ),
    )


def _meta_key_failure(values: Sequence[str]) -> Failure:
    return Failure(
        headline=f"meta holds a `schema` key ({', '.join(repr(value) for value in values)}).",
        detail=(
            FAIL_INDENT + "`meta` NEVER gains a `schema` key: the sole disk home for SCHEMA is",
            FAIL_INDENT + "`index_state.schema` (`0001_init.sql:64-66`, ADR-9 decision 3, ST23 at",
            FAIL_INDENT + "07-store-and-retrieval.md:3262). Two copies of a version cannot be",
            FAIL_INDENT + "kept equal by a reader; the second is what a store disagrees with",
            FAIL_INDENT + "itself about.",
        ),
    )


def _two_homes_failure(values: Sequence[str]) -> Failure:
    return Failure(
        headline=f"index_state holds {len(values)} rows keyed `schema`.",
        detail=(
            *(FAIL_INDENT + f"v = {value!r}" for value in values),
            FAIL_INDENT + "11-repo-layout.md:1197-1199 requires exactly one, and ADR-9 makes",
            FAIL_INDENT + "`index_state.schema` the single home. A second row is a second answer",
            FAIL_INDENT + "to `<major>.<minor>` and a reader has no way to pick.",
        ),
    )


def _wrong_value_failure(found: str) -> Failure:
    return Failure(
        headline=f"index_state.schema is {found!r}, not {SCHEMA_STRING!r}.",
        detail=(
            FAIL_INDENT + 'The value equals f"{SCHEMA}.{SCHEMA_MINOR}" read from',
            FAIL_INDENT + "`omniweave_core.contract` (11-repo-layout.md:1198), which formats it",
            FAIL_INDENT + "at exactly one site as `SCHEMA_STRING` (`0003_index.sql:409-412`).",
        ),
    )


def check_single_home(connection: sqlite3.Connection) -> tuple[list[str], list[Failure]]:
    """Check 5, at the END of the run (11-repo-layout.md:1196-1202, ADR-9).

    Which half has teeth against the DDL and which is true by construction is settled in the
    module docstring and is not re-argued here. What this function does add is the order: the two
    tables must exist before either is queried, and the cardinality must hold before the value is
    read, because "the value of the schema row" is not a question a two-row table answers.
    """
    failures = [
        _missing_home_failure(name)
        for name in ("meta", "index_state")
        if not _has_table(connection, name)
    ]
    if failures:
        return [], failures

    meta_rows = [str(row[0]) for row in connection.execute("SELECT v FROM meta WHERE k = 'schema'")]
    if meta_rows:
        failures.append(_meta_key_failure(meta_rows))

    seeded = [
        str(row[0]) for row in connection.execute("SELECT v FROM index_state WHERE k = 'schema'")
    ]
    if len(seeded) > 1:
        return [], [*failures, _two_homes_failure(seeded)]
    if failures:
        return [], failures

    if seeded:
        if seeded[0] != SCHEMA_STRING:
            return [], [_wrong_value_failure(seeded[0])]
        origin = "seeded by the migration set"
    else:
        # `0003_index.sql:37-38`: the tables are created empty and THE RUNNER writes this row. This
        # gate stands in for the runner, so it performs the runner's one write here, at the end of
        # the run, and reports that it did rather than letting a reader assume the DDL seeded it.
        connection.execute("INSERT INTO index_state (k, v) VALUES ('schema', ?)", (SCHEMA_STRING,))
        origin = "written here, as the runner does"
    return (
        [
            f'  single home index_state.schema = "{SCHEMA_STRING}" ({origin}), '
            "meta holds no schema key"
        ],
        [],
    )


# ---------------------------------------------------------------------------
# Check 6: append-only against the previous tag
# ---------------------------------------------------------------------------


def _git(*arguments: str) -> tuple[int, str]:
    """`git <arguments>` in the repository, or `(-1, reason)` when git cannot be run at all."""
    executable = shutil.which("git")
    if executable is None:
        return -1, "git is not on PATH"
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, argv[0] from `shutil.which`.
        [executable, *arguments],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode, completed.stderr.strip() or completed.stdout.strip()
    return 0, completed.stdout


def previous_tag() -> TagView:
    """The most recent tag reachable from HEAD, and what `MIGRATIONS_PATHSPEC` held at it.

    `git describe --tags --abbrev=0` rather than the newest tag in the repository: the boundary is
    the last release this history actually descends from, and a tag on an unrelated branch has
    published nothing to this line of work. `fetch_depth = 0` on G27's row in `tools/gates.toml`
    is what makes the tag reachable in CI at all.
    """
    code, output = _git("describe", "--tags", "--abbrev=0")
    if code != 0:
        return TagView(tag=None, files=frozenset(), reason="no previous tag")
    tag = output.strip()
    if not tag:
        return TagView(tag=None, files=frozenset(), reason="no previous tag")
    code, listing = _git("ls-tree", "-r", "--name-only", tag, "--", MIGRATIONS_PATHSPEC)
    if code != 0:
        return TagView(tag=None, files=frozenset(), reason=f"cannot read {tag}: {listing}")
    names = {
        Path(line.strip()).name for line in listing.splitlines() if line.strip().endswith(".sql")
    }
    return TagView(tag=tag, files=frozenset(names))


def _rename_failure(subject: str, target: str, tag: str) -> Failure:
    return Failure(
        headline=f"{subject} was renamed to {target}, and {tag} published it.",
        detail=(
            FAIL_INDENT + "The boundary that decides whether renumbering is legal is the tag, not",
            FAIL_INDENT + "the merge (11-repo-layout.md:1261-1268). Some stores have applied this",
            FAIL_INDENT + "file and `migration.version` cannot tell which.",
            FAIL_INDENT + f"fix: restore {subject} and append the new work as a new number.",
        ),
    )


def _delete_failure(subject: str, tag: str) -> Failure:
    return Failure(
        headline=f"{subject} was deleted, and {tag} published it.",
        detail=(
            FAIL_INDENT + "The migration set is append-only against the previous tag",
            FAIL_INDENT + "(11-repo-layout.md:1253-1256). Deleting a shipped migration leaves the",
            FAIL_INDENT + "stores that applied it describable by no later set.",
        ),
    )


def _edit_failure(subject: str, tag: str) -> Failure:
    return Failure(
        headline=f"{subject} was edited in place, and {tag} published it.",
        detail=(
            FAIL_INDENT + "Editing a shipped migration in place is unfixable: some stores have",
            FAIL_INDENT + "applied it and some have not, and `migration.version` cannot",
            FAIL_INDENT + "distinguish them (11-repo-layout.md:1253-1256).",
            FAIL_INDENT + "fix: append a new migration; never revise a published one.",
        ),
    )


def check_append_only(view: TagView) -> tuple[list[str], list[Failure]]:
    """Check 6. Nothing the previous tag published was renamed, edited or deleted (11:1261-1268).

    The SKIP line is not a courtesy. A check that bounds its own coverage has to say what it
    dropped, so a repository with no tag reports `SKIP (no previous tag)` on its own line and the
    gate still exits 0 — which is exactly this repository's state at P2 and would otherwise read
    as an assertion that held.
    """
    if view.tag is None:
        return [f"  append-only SKIP ({view.reason})"], []
    code, diff = _git(
        "diff", "--name-status", "--find-renames", view.tag, "--", MIGRATIONS_PATHSPEC
    )
    if code != 0:
        return [f"  append-only SKIP (cannot diff {view.tag}: {diff})"], []
    failures: list[Failure] = []
    added = 0
    for line in diff.splitlines():
        fields = [field for field in line.split("\t") if field]
        if len(fields) < STATUS_AND_PATH:
            continue
        status, paths = fields[0], fields[1:]
        if status.startswith("A"):
            added += 1
            continue
        subject = Path(paths[0]).name
        if subject not in view.files:
            continue
        if status.startswith("R"):
            failures.append(_rename_failure(subject, Path(paths[-1]).name, view.tag))
        elif status.startswith("D"):
            failures.append(_delete_failure(subject, view.tag))
        else:
            failures.append(_edit_failure(subject, view.tag))
    return [f"  append-only {view.tag}: {added} appended, {len(view.files)} published"], failures


# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, int, int]:
    """`3.42` or `3.42.0` as a three-tuple. Anything else is an argument error, not a floor.

    The roadmap's own invocation is `--min-sqlite 3.42` (16-roadmap.md:441), two components, so a
    two-component form is not a leniency here — it is the specified spelling.
    """
    parts = text.strip().split(".")
    if not 1 <= len(parts) <= VERSION_PARTS or not all(part.isdigit() for part in parts):
        message = f"not a SQLite version: {text!r} (expected N.N or N.N.N)"
        raise ValueError(message)
    padded = [*(int(part) for part in parts), 0, 0]
    return (padded[0], padded[1], padded[2])


def _floor_refusal(floor: tuple[int, int, int]) -> tuple[str, ...]:
    """The refusal, which names the extra and the three features it buys (07:196-200)."""
    return (
        f"G27b DID NOT RUN  this interpreter links SQLite {sqlite3.sqlite_version}, below the "
        f"declared floor {'.'.join(str(part) for part in floor)}.",
        "                  MIN_SQLITE is three features deep: STRICT tables need 3.37.0,",
        "                  unixepoch() needs 3.38.0 and unixepoch('subsec') needs 3.42.0",
        "                  (07-store-and-retrieval.md:196-200). The migrations use all three, so",
        "                  a run under the floor reports a syntax error rather than a defect in",
        "                  the set.",
        "                  fix: pip install omniweave-core[sqlite]",
    )


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def _emit(out: TextIO, message: str = "") -> None:
    """The only write. T20 is enabled repo-wide, so a gate reports through an injected `TextIO`."""
    out.write(message + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate_migrations.py",
        description="G27(b): the migration set is dense, unique, ordered and appliable.",
    )
    parser.add_argument(
        "--min-sqlite",
        default=None,
        help=(
            "the SQLite floor as N.N or N.N.N. Defaults to omniweave_core.limits.MIN_SQLITE "
            f"({'.'.join(str(part) for part in MIN_SQLITE)}), the one declared floor; this flag "
            "overrides it and never becomes a second copy of it."
        ),
    )
    parser.add_argument(
        "--migrations",
        default=None,
        type=Path,
        help="the directory to read (default schema/migrations/).",
    )
    return parser


def audit(root: Path, view: TagView) -> tuple[list[str], list[Failure]]:
    """The six checks over `root`, returning the report lines and every failure.

    Checks 1 to 3 gate check 4 and check 4 gates check 5, because an undefined apply order makes
    an apply report meaningless — 11-repo-layout.md:1245, *"and **only then** applies them in
    order to an empty file"*. Check 6 reads git and never the database, so it runs either way and
    its line always appears; a structural failure must not silently drop the tag boundary too.
    """
    files = migration_files(root)
    report: list[str] = [
        f"G27b  {len(files)} migration(s) in {root}",
        f"  sqlite      {sqlite3.sqlite_version} (floor "
        f"{'.'.join(str(part) for part in MIN_SQLITE)} from omniweave_core.limits.MIN_SQLITE)",
    ]
    structural = [
        *check_naming(files, root),
        *check_uniqueness(files, view, root),
        *check_density(files, root),
    ]
    if structural:
        report.append("  order       NOT ESTABLISHED, so the apply and the single-home check ran")
        report.append("              on nothing (11-repo-layout.md:1245, 'and only then applies')")
        tag_report, tag_failures = check_append_only(view)
        return [*report, *tag_report], [*structural, *tag_failures]

    numbered = in_apply_order(files)
    lowest = numbered[0].number or 0
    highest = numbered[-1].number or 0
    pragma_failures: list[Failure] = []
    home_failures: list[Failure] = []
    with tempfile.TemporaryDirectory(prefix="ow-g27b-") as scratch:
        connection, applied, failures = apply_all(files, Path(scratch) / "index.owstore")
        report.extend(applied)
        if connection is None:
            tag_report, tag_failures = check_append_only(view)
            return [*report, *tag_report], [*failures, *tag_failures]
        try:
            report.append(f"  density     {lowest:04d}..{highest:04d}, no duplicate and no gap")
            pragma_report, pragma_failures = check_pragmas(connection)
            report.extend(pragma_report)
            home_report, home_failures = check_single_home(connection)
            report.extend(home_report)
        finally:
            connection.close()
    tag_report, tag_failures = check_append_only(view)
    return [*report, *tag_report], [*pragma_failures, *home_failures, *tag_failures]


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    view: TagView | None = None,
) -> int:
    """Run the six checks and report. `view` is injectable so a test can pin the tag boundary."""
    writer = sys.stdout if out is None else out
    namespace = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))

    floor = MIN_SQLITE
    if namespace.min_sqlite is not None:
        try:
            floor = parse_version(namespace.min_sqlite)
        except ValueError as error:
            _emit(writer, f"G27b DID NOT RUN  {error}")
            return EXIT_NOT_RUN
    if sqlite3.sqlite_version_info < floor:
        for line in _floor_refusal(floor):
            _emit(writer, line)
        return EXIT_NOT_RUN

    root = MIGRATIONS if namespace.migrations is None else namespace.migrations
    if not root.is_dir():
        _emit(writer, f"G27b DID NOT RUN  no such directory: {root}")
        return EXIT_NOT_RUN
    if not sorted(root.glob("*.sql")):
        _emit(writer, f"G27b DID NOT RUN  no *.sql in {root}")
        return EXIT_NOT_RUN

    report, failures = audit(root, previous_tag() if view is None else view)
    for line in report:
        _emit(writer, line)
    _emit(writer)
    if failures:
        for failure in failures:
            _emit(writer, FAIL_PREFIX + failure.headline)
            for line in failure.detail:
                _emit(writer, line)
        _emit(writer, f"\nG27b FAIL  {len(failures)} finding(s) over {root}.")
        return EXIT_FAIL
    count = len(in_apply_order(migration_files(root)))
    _emit(
        writer,
        f"G27b ok  {count} migration(s) dense from 0001, applied in numeric order to an empty "
        f"file on SQLite {sqlite3.sqlite_version}, index_state and meta each in one home.",
    )
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
