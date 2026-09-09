"""The migration loader: `schema/migrations/*.sql` read as package data, applied forward-only.

11-repo-layout.md:1184-1194 is the specification in one sentence: *"`schema/migrations/*.sql` is
packaged with `omniweave-core` as package data, read through `importlib.resources` at use time
(section 2.6), applied forward-only in numeric order, one transaction each. Naming is
`NNNN_<slug>.sql`, four digits, and the order is load-bearing."* 07 section 3.8 owns the `migration`
table this writes into, and 11:1215-1221 owns the three facts every row must declare.

**Why this is a sibling of `store/sqlite.py` and not a section inside it.** Two dependency
directions, and each one alone would be enough. `sqlite.connect()` must work on a file that has no
schema at all -- that is what `tools/gate_migrations.py` does and what a first `ow add` does -- so
the connection layer may not import the migration set. And this module takes a `sqlite3.Connection`
and nothing else: no thread, no lock, no snapshot, no `Store`. Folding the two together would put 07
section 3.8's ledger beside 07 section 10's concurrency model with no shared vocabulary. The seam is
one argument, and `sqlite.py`'s docstring records the same split from the other side.

**`importlib.resources`, never `__file__`.** `__file__` and `__path__` are banned under
`packages/*/src/` outright, and the ban is not stylistic: the same DDL has to be readable out of a
wheel, out of a zipimport, and out of a source checkout, and only a `Traversable` is all three.
`_plan/_notes/build-defects.md` D12 is why the directory moved under `omniweave_core/store/` in the
first place. `importlib.resources.files` is also not `importlib.import_module`, which is banned
outside `host/`: `files()` resolves an already-imported package's anchor and imports nothing.

**Three things this module does that the shipped `.sql` files cannot do for themselves**, each
recorded because a reader will look for it in the SQL and not find it:

1. **The `migration` row.** `migration` is created by `0003_index.sql` (07 section 3.8), so
   `0001_init.sql` and `0002_graph.sql` *cannot* insert their own -- the table does not exist when
   they run. `0004_runtime.sql:32-36` states the conclusion: *"The row is therefore the applier's,
   for every file uniformly."* `_write_ledger_row` below is that applier, and
   `apply_pending`'s docstring records the one transaction-boundary consequence.
2. **`index_state`'s seed rows.** `0003_index.sql:37-38`: *"The tables are created empty here; the
   runner writes `index_state.schema` and one `migration` row per applied file."*
3. **The optional regions.** `0003_index.sql:53-58` defines the contract in the file itself: *"the
   runner applies every statement outside an optional region always, and the statements inside one
   only when that region's named condition holds."* Section 3.4's trigram index set is the only
   region that ships, gated on `[retrieval] trigram`.

Stdlib only (INV-2 / G1). Tier T-SCHEMA: 02-architecture.md section 2 row 26.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Final

from omniweave_core.config import KEYS
from omniweave_core.contract import SCHEMA_STRING
from omniweave_core.errors import StoreError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "COST_CLASSES",
    "MIGRATIONS_ANCHOR",
    "MIGRATIONS_PARTS",
    "NAME",
    "OPTIONAL_BEGIN",
    "OPTIONAL_END",
    "UNDECLARED",
    "Applied",
    "Declaration",
    "MigrationSource",
    "applied_versions",
    "apply_pending",
    "conditions_from_config",
    "migrations",
    "select_statements",
]


MIGRATIONS_ANCHOR: Final = "omniweave_core.store"
MIGRATIONS_PARTS: Final = ("schema", "migrations")
"""The anchor package and the path under it. `files(ANCHOR).joinpath(*PARTS)` and nothing else.

The anchor is the PACKAGE, not this module, because `importlib.resources.files` takes a package and
`schema/` sits beside `sqlite.py` rather than beside a `migrate/` subpackage.
`tools/gate_migrations.py:145-157` and `tools/gate_schema_lint.py:120` reach the same directory the
other way -- from the repository root -- because a gate is not shipped in the wheel and has a
repository to walk; a runtime reader has neither.
"""

NAME: Final = re.compile(r"^(?P<number>[0-9]{4})_(?P<slug>[a-z0-9]+(?:_[a-z0-9]+)*)\.sql\Z")
"""`NNNN_<slug>.sql`, four digits (11-repo-layout.md:1188). The same pattern the gate compiles.

Two homes for one regex is a defect, and the defect is real but it is the lesser one:
`tools/gate_migrations.py:181` cannot import this module without making a gate depend on the code it
gates, and `tools/` is not in the wheel. Named here so a future consolidation has a starting point.
"""

OPTIONAL_BEGIN: Final = re.compile(r"^--\s*@ow:optional-begin\s+(?P<name>[a-z0-9_]+)")
OPTIONAL_END: Final = re.compile(r"^--\s*@ow:optional-end\s+(?P<name>[a-z0-9_]+)")
"""The optional-region markers, spelled exactly as `0003_index.sql:56` prints them.

The region is line-delimited and the markers are comments, so a file with a region applies
unchanged under a SQL parser that knows nothing about them -- which is what lets G27(b) apply the
whole file, *"conditional region included, which is the desired reading -- it proves the conditional
DDL is valid without deciding whether a given store wants it"* (0003_index.sql:60-62).
"""

_DECLARATION: Final = re.compile(
    r"^--\s*@ow:migration\s+cost_class\s*=\s*(?P<cost_class>[a-z]+)\s*,"
    r"\s*resumable\s*=\s*(?P<resumable>[01])\s*$"
)
_UNBACKFILLED: Final = re.compile(r"^--\s*@ow:unbackfilled_means\s+(?P<prose>.+?)\s*$")

COST_CLASSES: Final = frozenset({"ddl", "backfill", "rebuild"})
"""`migration.cost_class`'s closed domain, from the shipped `CHECK` (0003_index.sql:437)."""

UNDECLARED: Final = "undeclared"
"""What `Declaration.source` reads when a migration carried no `@ow:migration` directive.

**The declaration cannot be re-derived and this module does not pretend otherwise.**
11-repo-layout.md:1215-1221 says a migration row declares *"three things a later operator needs and
cannot re-derive: its `cost_class` ..., whether it is `resumable`, and `unbackfilled_means` --
required prose that `ow doctor` prints **verbatim**"*, and `tools/gate_migrations.py:64-67` reached
the same conclusion from the gate's side: *"no static reader can re-derive"* them, which is why that
gate writes no `migration` row at all.

**None of the four shipped files carries a machine-readable declaration.** `0004_runtime.sql:34-36`
declares all three in PROSE -- *"cost_class = 'ddl', resumable = 0, and unbackfilled_means = 'not
applicable: 0004 is pure DDL and writes no rows, so there is nothing to backfill'"* -- and 0001,
0002 and 0003 declare nothing. So the loader offers the `@ow:migration` directive, in the same
`@ow:` namespace `0003_index.sql:56` already establishes for optional regions, and falls back to
this: `cost_class = 'ddl'`, `resumable = 0`, and an `unbackfilled_means` that says the
declaration is missing. That string is the one an operator reads, so it says the true thing --
*"the file declared nothing"* -- rather than the plausible thing. Guessing *"nothing to backfill"*
on a file that might have backfilled something is exactly the failure `unbackfilled_means` exists
to prevent.

The owed edit is a `@ow:migration` line in each of the four files; it is reported rather than made,
because those files are byte-diff-gated and are not this work item's.
"""

_FIX_MIGRATE: Final = "ow store migrate"


@dataclass(frozen=True, slots=True)
class Declaration:
    """`migration`'s three declared columns, plus where they came from.

    `cost_class`, `resumable` and `unbackfilled_means` are the three of 11-repo-layout.md:1215-1221.
    `source` is either the migration's own file name (a real `@ow:migration` directive) or
    `UNDECLARED`, and it exists so `ow doctor` can distinguish *"the author said this"* from
    *"nobody said anything"* without parsing the prose.
    """

    cost_class: str
    resumable: int
    unbackfilled_means: str
    source: str

    def __post_init__(self) -> None:
        if self.cost_class not in COST_CLASSES:
            raise StoreError(
                f"migration cost_class {self.cost_class!r} is not one of "
                f"{sorted(COST_CLASSES)}, which is the shipped CHECK's domain",
                fix=_FIX_MIGRATE,
            )
        if not self.unbackfilled_means:
            raise StoreError(
                "unbackfilled_means is required prose that `ow doctor` prints verbatim; an empty "
                "string is the one value it may not take",
                fix=_FIX_MIGRATE,
            )


def _undeclared(name: str) -> Declaration:
    """The fallback `Declaration` for a file with no `@ow:migration` directive. See `UNDECLARED`."""
    return Declaration(
        cost_class="ddl",
        resumable=0,
        unbackfilled_means=(
            f"undeclared: {name} carries no @ow:migration directive, so what a partially applied "
            f"copy of it would mean is not recorded. It applied inside one transaction, so on this "
            f"store it either applied whole or not at all."
        ),
        source=UNDECLARED,
    )


@dataclass(frozen=True, slots=True)
class MigrationSource:
    """One `NNNN_<slug>.sql` as read out of the wheel: its number, its name, its text.

    `text` is the file VERBATIM, optional regions included. `select_statements` is what decides
    which of it applies to a given store, and it is a separate function so that the text a
    `migration` row describes and the text a store received are both inspectable.
    """

    version: int
    name: str
    text: str
    declaration: Declaration


def _parse_declaration(name: str, text: str) -> Declaration:
    """Read a `@ow:migration` / `@ow:unbackfilled_means` pair out of a migration's comments.

    Both directives are searched over the whole file rather than only its header, because a
    migration that grows a second backfill section will want its declaration beside it. A file
    carrying `@ow:migration` and no `@ow:unbackfilled_means` is a refusal and not a fallback: an
    author who declared two of the three facts stopped halfway, and silently supplying the third
    would hide that.
    """
    declared: re.Match[str] | None = None
    prose: str | None = None
    for line in text.splitlines():
        if declared is None:
            declared = _DECLARATION.match(line)
        if prose is None:
            found = _UNBACKFILLED.match(line)
            if found is not None:
                prose = found.group("prose")
    if declared is None:
        return _undeclared(name)
    if prose is None:
        raise StoreError(
            f"{name} declares @ow:migration but no @ow:unbackfilled_means; the prose is required "
            f"because `ow doctor` prints it verbatim (11-repo-layout.md:1215-1221)",
            fix=_FIX_MIGRATE,
        )
    return Declaration(
        cost_class=declared.group("cost_class"),
        resumable=int(declared.group("resumable")),
        unbackfilled_means=prose,
        source=name,
    )


def migrations() -> tuple[MigrationSource, ...]:
    """Every shipped migration, in numeric order, read through `importlib.resources`.

    The whole read is `files(MIGRATIONS_ANCHOR).joinpath(*MIGRATIONS_PARTS).iterdir()`, and every
    member is a `Traversable`, so this works identically against a directory, a wheel and a zip
    import. There is no `__file__` and no `Path` anywhere on the path.

    **The set's shape is checked before anything is applied**, and both checks are
    11-repo-layout.md section 5.2's: the prefixes must be UNIQUE and DENSE from 1. G27(b) asserts
    the same two in CI (`tools/gate_migrations.py` checks 2 and 3), and the reason to repeat them
    here is that CI checks the repository while this checks the wheel the operator installed --
    *"two branches each adding a 0004 would both insert version 4, and the second raises on every
    store in the fleet after the first has already committed its DDL"* (0003_index.sql:443-447). A
    GAP raises nothing at all on a fresh store and applies out of intended order on an older one,
    which is why density is asserted separately.

    A file whose name does not parse is ignored rather than refused, matching the gate: *"a name
    that does not carry [a numeric prefix] has no place in that order"* (gate_migrations.py). What
    would refuse it is G27(b), in CI, where a stray file is a defect someone can fix.
    """
    root = files(MIGRATIONS_ANCHOR).joinpath(*MIGRATIONS_PARTS)
    found: list[MigrationSource] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        match = NAME.match(entry.name)
        if match is None:
            continue
        text = entry.read_text(encoding="utf-8")
        found.append(
            MigrationSource(
                version=int(match.group("number")),
                name=entry.name,
                text=text,
                declaration=_parse_declaration(entry.name, text),
            )
        )
    _refuse_bad_set(found)
    return tuple(sorted(found, key=lambda item: item.version))


def _refuse_bad_set(found: Sequence[MigrationSource]) -> None:
    """Refuse a migration set that is not unique and dense from 1 (11-repo-layout.md section
    5.2)."""
    if not found:
        raise StoreError(
            "the installed omniweave-core carries no schema/migrations/*.sql; the DDL ships as "
            "package data inside the wheel, so an empty set means a broken install",
            fix="pip install --force-reinstall omniweave-core",
        )
    numbers = [item.version for item in found]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        raise StoreError(
            f"the installed migration set numbers {duplicates} more than once, and "
            f"migration.version is an INTEGER PRIMARY KEY, so applying both would raise after the "
            f"first had already committed its DDL",
            fix="pip install --force-reinstall omniweave-core",
        )
    expected = list(range(1, len(numbers) + 1))
    if sorted(numbers) != expected:
        raise StoreError(
            f"the installed migration set is {sorted(numbers)} and must be dense from 1: a gap "
            f"applies cleanly to an empty file and applies out of intended order on a store that "
            f"received the later number first",
            fix="pip install --force-reinstall omniweave-core",
        )


def conditions_from_config(values: Mapping[str, object] | None = None) -> Mapping[str, bool]:
    """The optional-region conditions, from resolved config or from the declared defaults.

    One region ships and it is `trigram`, gated on `[retrieval] trigram` (0003_index.sql:139,
    07 section 3.4). The default is read from `config.KEYS` rather than written as `False` here,
    because `[retrieval] trigram`'s default has exactly one home.
    """
    default = KEYS["retrieval.trigram"].default
    source = values or {}
    return {"trigram": bool(source.get("retrieval.trigram", default))}


def select_statements(source: MigrationSource, conditions: Mapping[str, bool]) -> str:
    """`source.text` with every optional region whose condition is false removed.

    `0003_index.sql:53-58` states the contract: *"the runner applies every statement outside an
    optional region always, and the statements inside one only when that region's named condition
    holds."*

    Three failures are refusals rather than best-effort reads, because each one would silently
    change which DDL a store received: an unclosed region, a `-end` naming a different region than
    the open one, and a region whose name is not a key of `conditions`. The last is the important
    one -- an unknown region name defaulting to false would drop DDL nobody asked to drop, and
    defaulting to true would apply DDL nobody asked to apply.
    """
    out: list[str] = []
    region: str | None = None
    for number, line in enumerate(source.text.splitlines(keepends=True), start=1):
        begin = OPTIONAL_BEGIN.match(line)
        end = OPTIONAL_END.match(line)
        if begin is not None:
            if region is not None:
                raise _region_error(source, number, f"{begin['name']!r} opens inside {region!r}")
            region = begin["name"]
            if region not in conditions:
                raise _region_error(source, number, f"no condition named {region!r} was supplied")
            continue
        if end is not None:
            if region != end["name"]:
                raise _region_error(source, number, f"{end['name']!r} closes {region!r}")
            region = None
            continue
        if region is None or conditions[region]:
            out.append(line)
    if region is not None:
        raise _region_error(source, len(source.text.splitlines()), f"{region!r} is never closed")
    return "".join(out)


def _region_error(source: MigrationSource, line: int, detail: str) -> StoreError:
    return StoreError(
        f"{source.name}:{line}: malformed @ow:optional region -- {detail}. A region that cannot "
        f"be read cannot be applied, because guessing changes which DDL this store receives",
        fix=_FIX_MIGRATE,
    )


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def applied_versions(connection: sqlite3.Connection) -> frozenset[int]:
    """Which migrations this store already carries, from the `migration` ledger.

    An empty set when the ledger table does not exist, which is every store below
    `0003_index.sql` -- including a brand-new file. `_refuse_orphan_schema` is what stops that
    reading from being ambiguous.
    """
    if not _has_table(connection, "migration"):
        return frozenset()
    return frozenset(int(row[0]) for row in connection.execute("SELECT version FROM migration"))


@dataclass(frozen=True, slots=True)
class Applied:
    """One migration this run applied: its version, its name and the objects it added."""

    version: int
    name: str
    objects_added: int


def apply_pending(
    connection: sqlite3.Connection,
    *,
    now_ns: int,
    conditions: Mapping[str, bool] | None = None,
    sources: Sequence[MigrationSource] | None = None,
    corpus_id: str | None = None,
) -> tuple[Applied, ...]:
    """Apply every migration this store lacks, forward-only, in numeric order, one transaction each.

    Returns what it applied; an empty tuple when the store was already current, which is the
    property `test_re_opening_applies_nothing_a_second_time` asserts.

    `now_ns` is a WALL clock the caller reads, because `migration.applied_at_ns` is a wall-clock
    column and `time.time` is banned in library code (02-architecture.md:392). One value is used for
    every row of one run: the run is one event and a per-row clock read would imply otherwise.

    **The transaction boundary, and the one place it cannot be what 11:1187 says.** Each file
    applies
    inside its own `BEGIN` / `COMMIT`, and its `migration` row is written inside that same
    transaction -- except for the files that precede the one creating the `migration` table.
    `migration` ships in `0003_index.sql` (07 section 3.8), so `0001` and `0002` have no table to
    write into when they run, and `0004_runtime.sql:32-36` draws the only available conclusion:
    *"The row is therefore the applier's, for every file uniformly."* Their rows are written inside
    `0003`'s transaction, which is the earliest transaction that can hold them.

    **The window that leaves, and why refusing is the whole remedy.** A crash between `0001`'s
    commit
    and `0003`'s leaves objects on disk and no ledger, and a second run cannot tell a
    partially-migrated store from a store whose ledger it simply has not reached -- so
    `_refuse_orphan_schema` refuses, naming `rm` of the store. That refusal is affordable because
    the
    window is exactly *"a brand-new store's first open"*: `SCHEMA` 1 ships all four files, so
    nothing
    ever applies `0001` to a store that holds data. 07:158-160 makes the remedy a documented one --
    *"`rm -rf .omniweave` is a supported, documented, lossless operation, and every rule in this
    document is subordinate to keeping that sentence true."*

    `BEGIN IMMEDIATE`, not `BEGIN`: a migration is a writer, and taking the RESERVED lock up front
    is what makes a contended migration fail before it has done half its DDL rather than after.
    `executescript` is what runs the file -- it is the only DBAPI call that accepts many statements,
    and it is what `tools/gate_migrations.py:449-462` uses, so the two agree.

    **The `BEGIN` is INSIDE the script, and that is a correctness requirement rather than a style.**
    `Connection.executescript` *"executes an implicit COMMIT first if there is a pending
    transaction"*, so a `BEGIN IMMEDIATE` issued before the call is committed by the call and every
    statement in the file then runs in autocommit -- measured on CPython 3.12.0 / SQLite 3.43.1: a
    two-statement script whose second statement fails leaves the first COMMITTED. That is the exact
    opposite of *"NEITHER FILE APPLIES"* (11-repo-layout.md:1190-1191). With the `BEGIN` inside the
    script there is no pending transaction at entry, nothing is implicitly committed, and the
    transaction is still open when the script returns -- which is also what lets the ledger rows be
    written into it. `tools/gate_migrations.py:458` puts both `BEGIN` and `COMMIT` in the script for
    the same reason; this one keeps the `COMMIT` outside because the ledger `INSERT` needs bind
    parameters and `executescript` takes none.
    """
    picked = tuple(sources) if sources is not None else migrations()
    active = conditions_from_config() if conditions is None else conditions
    applied = applied_versions(connection)
    _refuse_orphan_schema(connection, applied)
    pending = [item for item in picked if item.version not in applied]
    _refuse_backwards(pending, applied)
    done: list[Applied] = []
    unrecorded: list[MigrationSource] = []
    for item in pending:
        before = _object_count(connection)
        _apply_one(connection, item, active, now_ns=now_ns, unrecorded=unrecorded)
        done.append(
            Applied(
                version=item.version,
                name=item.name,
                objects_added=_object_count(connection) - before,
            )
        )
    if done:
        _seed_index_state(connection, corpus_id=corpus_id)
    return tuple(done)


def _refuse_orphan_schema(connection: sqlite3.Connection, applied: frozenset[int]) -> None:
    """Refuse a store that holds schema objects and no `migration` ledger. See `apply_pending`."""
    if applied or not _object_count(connection):
        return
    raise StoreError(
        "this store holds schema objects but no `migration` ledger, so which migrations it has "
        "received cannot be established: the ledger table ships in 0003_index.sql and a crash "
        "before it committed leaves exactly this state. Delete the store and re-create it",
        fix="rm -rf .omniweave && ow index build",
    )


def _refuse_backwards(pending: Sequence[MigrationSource], applied: frozenset[int]) -> None:
    """Refuse a pending migration numbered below one already applied. Forward-only means forward.

    11-repo-layout.md:1237-1239's gap case: *"PRs adding `0004` and `0006` with `0005` never landing
    produce a set that applies fine to an empty file and applies out of intended order on a store
    that received `0006` in an earlier release and `0004` in a later one."* `migrations()` refuses
    the gap in the SET; this refuses the same hazard as it reaches a STORE, which is where the DDL
    would actually land in the wrong order.
    """
    if not applied:
        return
    highest = max(applied)
    behind = [item.name for item in pending if item.version < highest]
    if behind:
        raise StoreError(
            f"{behind} would apply below migration {highest}, which this store already carries: "
            f"forward-only means a migration never lands after a higher-numbered one",
            fix="pip install -U omniweave-core",
        )


def _object_count(connection: sqlite3.Connection) -> int:
    """`sqlite_master` rows -- tables, indexes, views and triggers together."""
    row = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return int(row[0])


def _apply_one(
    connection: sqlite3.Connection,
    item: MigrationSource,
    conditions: Mapping[str, bool],
    *,
    now_ns: int,
    unrecorded: list[MigrationSource],
) -> None:
    """One migration in one transaction, with its ledger row when there is a ledger to hold it.

    `unrecorded` accumulates the files whose row could not be written yet and is drained into the
    first transaction that has the `migration` table; `apply_pending`'s docstring is the argument.
    A raise rolls the whole file back, which is what makes 11:1190-1191's recorded defect honest --
    *"an index resolves its table at CREATE INDEX, so an index on a table a later file creates
    aborts the migration and NEITHER FILE APPLIES."*
    """
    statements = select_statements(item, conditions)
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + statements)
        if _has_table(connection, "migration"):
            for pending in (*unrecorded, item):
                _write_ledger_row(connection, pending, now_ns=now_ns)
            unrecorded.clear()
        else:
            unrecorded.append(item)
    except BaseException as error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        if isinstance(error, sqlite3.Error):
            raise StoreError(
                f"{item.name} did not apply and was rolled back whole: {error}. An index resolves "
                f"its table at CREATE INDEX, so an index on a table a later file creates aborts "
                f"the migration and NEITHER the index nor anything else in its file lands",
                fix=_FIX_MIGRATE,
            ) from error
        raise
    if connection.in_transaction:
        connection.execute("COMMIT")


def _write_ledger_row(
    connection: sqlite3.Connection, item: MigrationSource, *, now_ns: int
) -> None:
    """One `migration` row: version, name, applied_at_ns and the three declared facts.

    `backfill_done` and `backfill_total` are left to their DDL default and to NULL: 0 rows of a
    backfill are done and the total is unknown, and a `backfill_total` of 0 would claim the
    migration measured itself. 07 section 3.8's `resumable` semantics read both.
    """
    declaration = item.declaration
    connection.execute(
        "INSERT INTO migration (version, name, applied_at_ns, cost_class, resumable, "
        "unbackfilled_means) VALUES (?, ?, ?, ?, ?, ?)",
        (
            item.version,
            item.name,
            now_ns,
            declaration.cost_class,
            declaration.resumable,
            declaration.unbackfilled_means,
        ),
    )


def _seed_index_state(connection: sqlite3.Connection, *, corpus_id: str | None) -> None:
    """The `index_state` rows the runner owns, written once and never overwritten.

    `0003_index.sql:37-38`: *"The tables are created empty here; the runner writes
    `index_state.schema` and one `migration` row per applied file."* Four keys are seeded and each
    one is a key a store OPEN reads, which is the rule that bounds the list:

    * **`schema`** = `contract.SCHEMA_STRING`. The only place on disk that holds the pair
      (07:275-281, ADR-9), and what G27(b) asserts at the end of a run
      (11-repo-layout.md:1196-1200). Formatted nowhere here: `SCHEMA_STRING` is the one site that
      formats it.
    * **`generation`** = `0`. The per-store monotonic RUN counter (07:2915), which `snapshot()`
      reads as its very first statement and which gate 3 compares across the snapshot boundary. A
      store with no `generation` row has no snapshot, so 0 is the value a store starts at rather
      than a value anyone chose.
    * **`shard_ord`** = `0`. 07:2999: *"single store: `shard_ord = 0`, so ids are literally 1, 2,
      3"*, and 07:3003-3006 says the ordinal is *"re-asserted at open against
      `index_state.shard_ord`"*, so the row has to exist for that assertion to have a subject.
    * **`fts_state`** = `ok`. The three-state machine the lexical Channel reads
      (0003_index.sql:413-418). A freshly created FTS index over zero blocks is complete, so `ok` is
      a measurement; the pessimistic values are written by whatever invalidates it, *"in the same
      transaction as the DDL that invalidates it"*.

    `corpus_id` is written only when the caller supplies one, because it is per-store and this
    module has no way to mint it -- `0001_init.sql:26-28` says the same of `meta`'s copy,
    *"per-store
    and per-build and cannot be literals in a byte-diff-gated file at all"*. The remaining
    `index_state` keys of 07:696-697 -- `scorer_version`, `wal_baseline_bytes`,
    `last_full_index_ns`, `default_space_id`, `unicode_version` -- belong to the WAL valve, the
    scorer and the identity layer, and are their owners' to seed.

    `INSERT OR IGNORE` and not `INSERT OR REPLACE`: re-running a migration must never reset a
    generation counter or a corpus id.
    """
    if not _has_table(connection, "index_state"):
        return
    rows = [
        ("schema", SCHEMA_STRING),
        ("generation", "0"),
        ("shard_ord", "0"),
        ("fts_state", "ok"),
    ]
    if corpus_id is not None:
        rows.append(("corpus_id", corpus_id))
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.executemany("INSERT OR IGNORE INTO index_state (k, v) VALUES (?, ?)", rows)
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")
