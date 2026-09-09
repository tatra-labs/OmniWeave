"""`schema/migrations/0001_init.sql` -- L2's DDL, asserted against the plan and against SQLite.

Specified by 03-document-model.md section 13.1 (the golden DDL) and 07-store-and-retrieval.md
section 3 (the per-file object assignment at :237, and the index register at section 3.13). The
file is P2 W2.2's (16-roadmap.md section 3.3).

Four obligations, and every test below serves one of them:

1. **It applies.** G27(b) asserts every migration "applies in numeric order to an empty file on
   the declared `MIN_SQLITE`" (charter.md:803). `tools/gate_migrations.py` is `runner_planned` in
   `tools/gates.toml` and does not exist yet, so until it lands this module is the only thing that
   runs the statements at all.
2. **It is a transcription.** Every `CREATE TABLE` here carries the charter's columns, column for
   column, with exactly one rename -- `block.title` -> `block.label`, ADR-1 decision 7 -- and the
   test asserts that the rename is the ONLY difference rather than assuming it.
3. **Its interpolated literals mean what the enums mean.** Three constants are baked into
   `block`'s CHECK constraints because SQLite refuses the general form: `OsKind.PIXELS` = 3 and
   `OsKind.BYTES` = 0 (03:1447-1451 -- "CI asserts each literal against ... in both directions")
   and the shard ordinal 0 (ST20, charter.md:1070-1076). They are DERIVED here, never retyped.
4. **`enum_val`'s seeded ordinals equal `omniweave_core.model.enums`'s.** charter.md:939:
   "Generated from the Python enums at migration time; CI asserts parity in both directions." One
   derivation (`enum_val_rows()`) against one table, which is the whole reason the derivation
   lives in one place.

`_plan/` is `.gitignore`d, so every test that reads a plan document calls `plan.require()` first
and skips when the design tree is absent from the checkout (see `tests/conftest.py`).
"""

from __future__ import annotations

# WHY `import sqlite3` IS HERE AT ALL. INV-17 bans it outside `omniweave_core/store/` and G27(b)
# requires that the migration be APPLIED to a real database -- both are true, and the second is
# what settles it. A test that asserted this DDL by reading it would catch none of
# `CREATE VIRTUAL TABLE`'s option arity, none of the eleven CHECK constraints, the forward foreign
# key, or a trigger body that does not compile; two of the findings this module reports were only
# visible from a live connection. The semgrep half of the ban
# (`tools/semgrep/omniweave.yaml`) scopes every rule to `packages/*/src/**` and so already exempts
# a test; ruff's half carries no `per-file-ignores` row for tests, and adding one belongs to
# `pyproject.toml`'s owner -- see this cluster's `needs_from_owner`. Until then the `noqa` is the
# narrowest form of the exemption: one line, in one file, with the reason attached.
import re
import sqlite3  # noqa: TID251
from typing import TYPE_CHECKING

import pytest
from conftest import MIGRATIONS_DIR
from omniweave_core.limits import MIN_SQLITE
from omniweave_core.model.enums import (
    ENUM_DOMAINS,
    Kind,
    Layer,
    Method,
    OsKind,
    PageKind,
    Quote,
    RelKind,
    TableKind,
    Trust,
    enum_val_rows,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from conftest import PlanDocs


MIGRATION = "0001_init.sql"
"""The file this module owns, by NAME. Its directory is `conftest.MIGRATIONS_DIR` -- one home for
the path, because `_plan/_notes/build-defects.md` D12 moved it and a name is what does not move."""

# 07-store-and-retrieval.md:237 -- the "Creates" cell for `0001_init.sql`, verbatim, minus
# `block_fts`, which is a CREATE VIRTUAL TABLE and is asserted separately.
TABLES_07_ASSIGNS = (
    "meta",
    "enum_val",
    "doc",
    "page",
    "producer",
    "block",
    "block_history",
    "rel",
    "mark",
    "table_meta",
    "cell",
    "grid_slot",
    "part",
    "asset",
    "block_asset",
    "page_render",
    "diag",
)

# 07 section 3.13's index register: the ten rows whose Owner column reads `0001`.
INDEXES_IN_THE_REGISTER = (
    "block_addr",
    "block_cite",
    "block_sib",
    "block_read",
    "block_parent",
    "block_kind",
    "block_cdig",
    "block_review",
    "block_restricted",
    "diag_code",
)

# The two ST10 identity indexes on 0001's tables (charter.md:1014, :1191). They are NOT rows of
# section 3.13's register, which this cluster reports as a defect rather than treating as a reason
# to omit them: ST10 says an identity containing an IFNULL sentinel is ALWAYS a separate UNIQUE
# INDEX, and without them `INSERT OR IGNORE` on `producer` and `asset` degenerates to a plain
# INSERT -- codegraph #1034, byte-identical duplicates that inflated counts and flowed to callers.
IDENTITY_INDEXES = ("producer_identity", "asset_identity")

# The three remaining charter indexes on 0001's tables, ALSO absent from section 3.13's register:
# `rel_dst` / `rel_src` (charter.md:1114-1115, "D5 supplies the half D2 omitted") and `mark_block`
# (charter.md:1125). Counted: the register carries 29 rows and names ten of 0001's fifteen
# indexes, so five are missing and ST17's "an index that appears in `sqlite_master` without a
# register row fails CI" cannot hold as written. Reported; the five ship, because the charter's
# DDL is settled law and the register is the derived artefact.
INDEXES_NOT_IN_THE_REGISTER = ("rel_dst", "rel_src", "mark_block")

# `WITHOUT ROWID` is a storage decision, not taste: each of these six has a composite natural key
# and no surrogate, so a hidden rowid would be dead weight on every row.
WITHOUT_ROWID = ("enum_val", "page", "grid_slot", "part", "block_asset", "page_render")

# charter.md:4834 -- 0002_graph.sql is where "enum_val gains the CLOSED domains: 'lane', 'akind',
# 'alias_kind', 'claim_status', 'taint', 'precision'". So 0001 seeds the other nine, and
# `test_the_fifteen_domains_partition_into_0001s_nine_and_0002s_six` proves the split is total.
DOMAINS_0002 = ("lane", "akind", "alias_kind", "claim_status", "taint", "precision")
DOMAINS_0001 = (
    "kind",
    "layer",
    "trust",
    "method",
    "quote",
    "page_kind",
    "table_kind",
    "rel_kind",
    "origin_span_kind",
)

# Each of 0001's nine domains against the (table, column) it types, so a seeded domain that reads
# no column in this file -- or a column here with no domain -- is a failure rather than a footnote.
# Sources: block.kind/.layer/.trust/.method/.quote/.os_kind (03:2327-2350); page.page_kind and
# page.method (charter.md:984, :991); table_meta.kind (charter.md:1135); rel.kind and rel.trust
# (charter.md:1106-1110).
DOMAIN_COLUMNS = {
    "kind": (("block", "kind"),),
    "layer": (("block", "layer"),),
    "trust": (("block", "trust"), ("rel", "trust")),
    "method": (("block", "method"), ("page", "method")),
    "quote": (("block", "quote"),),
    "page_kind": (("page", "page_kind"),),
    "table_kind": (("table_meta", "kind"),),
    "rel_kind": (("rel", "kind"),),
    "origin_span_kind": (("block", "os_kind"),),
}

# The classes behind those nine, so a per-domain member count is checked against the enum rather
# than against a number retyped here.
DOMAIN_CLASSES = {
    "kind": Kind,
    "layer": Layer,
    "trust": Trust,
    "method": Method,
    "quote": Quote,
    "page_kind": PageKind,
    "table_kind": TableKind,
    "rel_kind": RelKind,
    "origin_span_kind": OsKind,
}

# 77 = 35 + 5 + 3 + 10 + 5 + 5 + 2 + 7 + 5, the nine domains' member counts. Written out because a
# bare 77 in an assertion says nothing about which domain moved when it breaks.
EXPECTED_ROWS = sum(len(cls.__members__) for cls in DOMAIN_CLASSES.values())

_COMMENT = re.compile(r"--[^\n]*")
_CREATE_TABLE = re.compile(r"\bCREATE\s+TABLE\s+([a-z_]+)\s*\(", re.IGNORECASE)
_CONSTRAINT_LEAD = ("CHECK", "UNIQUE", "PRIMARY", "FOREIGN", "CONSTRAINT")


# ---------------------------------------------------------------------------
# Reading the file, and reading a `CREATE TABLE` out of any SQL text
# ---------------------------------------------------------------------------


def _strip_comments(sql: str) -> str:
    """Every `--` comment removed. Safe on this corpus: no string literal here holds `--`."""
    return _COMMENT.sub("", sql)


def _table_span(sql: str, table: str) -> tuple[str, str] | None:
    """`(body, tail)` for `CREATE TABLE <table> (<body>)<tail>;`, comments stripped.

    A regex cannot find the body on its own -- `block` alone nests eleven parenthesised CHECK
    bodies -- so the opening paren is found by pattern and the close by counting depth. The tail
    is what carries `WITHOUT ROWID` / `STRICT`, and reading it by depth rather than by a
    non-greedy `.*?` is what stops a rowid table matching the NEXT table's `WITHOUT ROWID`.
    """
    text = _strip_comments(sql)
    for match in _CREATE_TABLE.finditer(text):
        if match.group(1) != table:
            continue
        depth, start = 1, match.end()
        for offset in range(start, len(text)):
            if text[offset] == "(":
                depth += 1
            elif text[offset] == ")":
                depth -= 1
                if depth == 0:
                    end = text.index(";", offset)
                    return text[start:offset], text[offset + 1 : end]
    return None


def _table_body(sql: str, table: str) -> str | None:
    span = _table_span(sql, table)
    return None if span is None else span[0]


def _columns(body: str) -> tuple[str, ...]:
    """The declared column names in `body`, in order, table-level constraints excluded."""
    items: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))

    names: list[str] = []
    for item in items:
        tokens = item.split()
        if not tokens or tokens[0].upper() in _CONSTRAINT_LEAD:
            continue
        names.append(tokens[0])
    return tuple(names)


def _charter_ddl(plan: PlanDocs) -> str:
    """Every ```sql fence in `charter.md`, joined. The L2 block is one of them."""
    return "\n".join(plan.fences("_notes/charter.md", "sql"))


def _ord(domain: str, name: str) -> int:
    """The stored ordinal for one member, from the enums module. Never a retyped literal."""
    for row_domain, ordinal, row_name in enum_val_rows():
        if row_domain == domain and row_name == name:
            return ordinal
    message = f"no enum_val row for {domain}.{name}"
    raise LookupError(message)


def _apply(sql: str) -> sqlite3.Connection:
    """`sql` applied to an empty in-memory database with foreign keys ON.

    `PRAGMA foreign_keys = ON` is deliberate and is what makes
    `test_the_one_forward_foreign_key_survives_create_table` a real observation: the whole
    justification for leaving `route_decision` in 0004 is that SQLite performs no DDL-time parent
    lookup even when enforcement is on (07:264-273).
    """
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(sql)
    return connection


# FTS5 creates its own shadow tables beside a virtual table and they are not part of any DDL.
# Matched by exact suffix rather than by the `block_fts_` prefix, because the three sync TRIGGERS
# share that prefix and are very much part of the DDL.
_FTS5_SHADOWS = ("_data", "_idx", "_content", "_docsize", "_config")


def _objects(connection: sqlite3.Connection, kind: str) -> tuple[str, ...]:
    """Every `sqlite_master` name of one type, SQLite's and FTS5's own shadows excluded."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ? ORDER BY name", (kind,)
    ).fetchall()
    shadows = tuple(f"block_fts{suffix}" for suffix in _FTS5_SHADOWS)
    return tuple(name for (name,) in rows if not name.startswith("sqlite_") and name not in shadows)


@pytest.fixture(scope="module")
def migration_sql() -> str:
    return (MIGRATIONS_DIR / MIGRATION).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def migration_bytes() -> bytes:
    return (MIGRATIONS_DIR / MIGRATION).read_bytes()


@pytest.fixture(scope="module")
def applied(migration_sql: str) -> sqlite3.Connection:
    """The schema, once, for the read-only introspection tests."""
    return _apply(migration_sql)


# The minimum stand-in for 0004_runtime.sql's `route_decision` (charter.md:2811), whose
# `decision_id TEXT PRIMARY KEY` is the parent key `block.decision_id` names. It is a TEST FIXTURE
# and not shipped DDL: 0001 must not create it (07 section 3's whole layer-per-file
# correspondence), and no `block` row can be written on a `foreign_keys = ON` connection until
# 0004 has applied -- see `test_a_block_row_needs_0004s_route_decision_to_exist_at_all`, which
# measures that and records where 07 states the reason differently.
ROUTE_DECISION_STANDIN = "CREATE TABLE route_decision (decision_id TEXT PRIMARY KEY);"


@pytest.fixture
def store(migration_sql: str) -> sqlite3.Connection:
    """A FRESH database per test, for the tests that write rows.

    Function-scoped on purpose: a trigger test that left a `block` row behind would silently
    change what the next test's `SELECT count(*)` means, and a rollback is not enough because
    `executescript` commits.

    Carries the `route_decision` stand-in, because SQLite resolves a foreign key's parent when it
    PREPARES a DML statement on the child.
    """
    connection = _apply(migration_sql)
    connection.executescript(ROUTE_DECISION_STANDIN)
    return connection


# ---------------------------------------------------------------------------
# 1. It applies, on a SQLite at or above the declared floor
# ---------------------------------------------------------------------------


def test_the_migration_file_is_where_07_section_3_says_it_is() -> None:
    assert (MIGRATIONS_DIR / MIGRATION).is_file(), f"{MIGRATION} is missing"


def test_the_sqlite_under_test_is_at_or_above_the_min_sqlite_floor() -> None:
    """If the DDL needs a feature above this floor that is a defect in the DDL, not in the floor.

    `MIN_SQLITE` is `omniweave_core.limits`'s one floor and is three features deep: STRICT tables
    need 3.37.0, `unixepoch()` 3.38.0 and `unixepoch('subsec')` 3.42.0 (07 section 2.1). 0001
    declares no STRICT table and calls no date function, so it sits comfortably inside the floor
    -- but the assertion belongs here anyway, because a green run on a NEWER SQLite proves nothing
    about G27(b)'s, which runs at exactly `MIN_SQLITE`.
    """
    assert sqlite3.sqlite_version_info >= MIN_SQLITE, (
        f"this interpreter links SQLite {sqlite3.sqlite_version}, below "
        f"MIN_SQLITE {'.'.join(str(part) for part in MIN_SQLITE)}"
    )


def test_the_migration_applies_clean_to_an_empty_database(store: sqlite3.Connection) -> None:
    """G27(b) in miniature, and it is the assertion `tools/gate_migrations.py` will inherit."""
    assert store.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.execute("PRAGMA foreign_key_check").fetchall() == []


def test_every_statement_in_the_file_is_complete(migration_sql: str) -> None:
    """G27 clause (a)'s instrument: `sqlite3.complete_statement` over the text (charter.md:803).

    A trigger body is the trap this catches -- `END;` closes it and a naive `;` split does not, so
    an incrementally-fed statement that never completes is how a half-written trigger ships.
    """
    assert sqlite3.complete_statement(migration_sql)


def test_the_file_is_house_style(migration_bytes: bytes) -> None:
    """LF, ASCII in SQL, one trailing newline, 100 columns."""
    assert b"\r" not in migration_bytes, "CRLF in a byte-diff-gated file"
    text = migration_bytes.decode("ascii")  # raises on any non-ASCII byte
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    over = [n for n, line in enumerate(text.split("\n"), start=1) if len(line) > 100]
    assert over == [], f"lines over 100 columns: {over}"


# ---------------------------------------------------------------------------
# 2. It creates exactly the objects 07 section 3 assigns to 0001
# ---------------------------------------------------------------------------


def test_it_creates_exactly_the_tables_07_section_3_assigns(applied: sqlite3.Connection) -> None:
    """No more and no fewer. A table hoisted out of 0002 or 0004 breaks the layer-per-file
    correspondence 07 section 3's whole table expresses."""
    assert set(_objects(applied, "table")) == {*TABLES_07_ASSIGNS, "block_fts"}


def test_the_register_indexes_and_the_two_identity_indexes_are_present(
    applied: sqlite3.Connection,
) -> None:
    assert set(_objects(applied, "index")) == {
        *INDEXES_IN_THE_REGISTER,
        *IDENTITY_INDEXES,
        *INDEXES_NOT_IN_THE_REGISTER,
    }


def test_five_of_0001s_indexes_have_no_row_in_07_section_3_13s_register(plan: PlanDocs) -> None:
    """A REPORTED DEFECT, pinned so it cannot be silently "fixed" by dropping an index.

    ST17 (07 section 3.13) says "every shipped index is named in `tools/indexes.toml` with the
    statement it serves" and "an index that appears in `sqlite_master` without a register row
    fails CI". The register's own table names ten indexes at Owner `0001`; this file creates
    fifteen. The five without a row are `producer_identity`, `asset_identity`, `rel_dst`,
    `rel_src` and `mark_block` -- each printed in charter.md's L2 DDL, and the first two REQUIRED
    by ST10 (an IFNULL identity is always a separate UNIQUE INDEX). `tools/indexes.toml` does not
    exist yet, so the register cannot be repaired here; when it lands it needs five more rows.
    """
    plan.require()
    doc = ("07-store-and-retrieval.md",)
    for name in (*IDENTITY_INDEXES, *INDEXES_NOT_IN_THE_REGISTER):
        assert not plan.grep(rf"^\| `{name}` \|", documents=doc), (
            f"07 section 3.13 now carries a register row for {name}; delete it from "
            "INDEXES_NOT_IN_THE_REGISTER and from this test"
        )
    for name in INDEXES_IN_THE_REGISTER:
        assert plan.grep(rf"^\| `{name}` \|", documents=doc), f"{name} left the register"


def test_the_three_ifnull_identities_are_separate_indexes_not_inline_constraints(
    migration_sql: str,
) -> None:
    """ST10: an identity containing an `IFNULL` sentinel is ALWAYS a separate `UNIQUE INDEX`.

    SQLite prohibits an expression inside a table-level UNIQUE or PRIMARY KEY, so the inline form
    does not merely fail review -- it fails `CREATE TABLE` (charter.md:3789, 03:2471-2472).
    """
    text = _strip_comments(migration_sql)
    for name in ("producer_identity", "asset_identity", "block_sib"):
        assert f"CREATE UNIQUE INDEX {name}" in text
    for table in ("producer", "asset", "block"):
        body = _table_body(migration_sql, table)
        assert body is not None
        assert "IFNULL" not in body.upper(), f"{table} carries an IFNULL inside CREATE TABLE"


def test_ow_block_head_is_the_only_view_and_projects_block_unchanged(
    applied: sqlite3.Connection,
) -> None:
    """03:2376-2380. It is a FILTER, not a deduplication: retiring a generation sets `state = 1`
    in the same transaction that advances `doc.gen`, so the layer never holds two generations
    (07 section 3.3)."""
    assert _objects(applied, "view") == ("ow_block_head",)
    view = [row[1] for row in applied.execute("PRAGMA table_info(ow_block_head)")]
    block = [row[1] for row in applied.execute("PRAGMA table_info(block)")]
    assert view == block, "SELECT b.* must project block's columns unchanged"


def test_the_three_block_fts_triggers_are_the_only_triggers(applied: sqlite3.Connection) -> None:
    """A trigger name is global in `sqlite_master`, so 0003's `head_fts` and `block_tri` sets
    carry their own names; printing `block_fts_ai` twice aborts G27(b) (07 section 3.3)."""
    assert _objects(applied, "trigger") == ("block_fts_ad", "block_fts_ai", "block_fts_au")


def test_it_declares_no_pragma(migration_sql: str) -> None:
    """The pragma set has three lifetimes and one home, `store/sqlite.py` (07 section 2.1).

    Two of them could not be honoured from a migration in any case: `page_size` is a no-op once a
    page has been written, and `foreign_keys` is a documented no-op inside a transaction -- which
    03 section 15.3 says every migration runs in.
    """
    assert "PRAGMA" not in _strip_comments(migration_sql).upper()


def test_it_writes_no_meta_row(applied: sqlite3.Connection, migration_sql: str) -> None:
    """`meta` is created empty. ADR-9 decision 3 and ST24 (07:3263) put the only version stamp
    anyone checks in `index_state`, which 0003 creates, and the four release-1 constants 03:2708
    fixes have no code home in `omniweave_core.contract` to hold parity against."""
    assert "INSERT INTO meta" not in _strip_comments(migration_sql)
    assert applied.execute("SELECT count(*) FROM meta").fetchone() == (0,)


def test_meta_never_gains_a_schema_key(applied: sqlite3.Connection) -> None:
    """ST23 (07:3262), ADR-9. The store's single-homedness check reads exactly this."""
    assert applied.execute("SELECT count(*) FROM meta WHERE k = 'schema'").fetchone() == (0,)


def test_enum_val_is_the_only_seeded_table(applied: sqlite3.Connection) -> None:
    """`enum_val` is a registry generated from the Python enums (charter.md:939), not corpus data;
    every other table in an L2 migration is created with no ROWS (16-roadmap.md section 3.3)."""
    counts = {
        table: applied.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
        for table in TABLES_07_ASSIGNS
    }
    assert [table for table, rows in counts.items() if rows] == ["enum_val"]


def test_producer_precedes_page_so_the_shipped_order_has_one_forward_foreign_key(
    migration_sql: str,
) -> None:
    """07:264: "the one forward foreign key in the shipped order is
    `block.decision_id -> route_decision`". `page.producer_id -> producer` would be a second, so
    `producer` is hoisted above the charter's print position. This DEPARTS from charter.md's order
    and the reason is that sentence, which counts the exceptions at exactly one."""
    text = _strip_comments(migration_sql)
    page_at = re.search(r"CREATE TABLE page\s*\(", text)
    assert page_at is not None
    assert text.index("CREATE TABLE producer") < page_at.start()


def test_a_block_row_needs_0004s_route_decision_to_exist_at_all(
    migration_sql: str,
) -> None:
    """MEASURED, AND 07:266-268 STATES THE REASON DIFFERENTLY. A defect this cluster reports.

    07 section 3 writes the exception as: "Under `PRAGMA foreign_keys = ON` that `CREATE TABLE`
    still succeeds: the parent is consulted **when a non-NULL `decision_id` is written**, which
    cannot happen until every migration has applied."

    Measured on SQLite 3.43.1: the parent is resolved when SQLite PREPARES any DML on the child,
    NOT when a non-NULL value is bound. An `INSERT INTO block ... decision_id = NULL` raises
    `OperationalError: no such table: main.route_decision`. The ORDERING CONCLUSION IS UNHARMED --
    a migration writes no rows, so `0001` -> `0005` still applies -- but the consequence is
    stronger than the document states: on a `foreign_keys = ON` connection NO `block` row of any
    kind can be written until `0004_runtime.sql` has run, so the store's create path must apply
    every migration before it opens a `DocSink`. Stating it as a non-NULL condition would let
    someone conclude that a partially migrated store can be written to as long as routing is
    unused.
    """
    connection = _apply(migration_sql)
    _seed_one_page(connection)  # `doc`, `producer` and `page` all insert cleanly
    missing = re.escape("no such table: main.route_decision")
    with pytest.raises(sqlite3.OperationalError, match=missing):
        _insert_block(connection, block_id=1)  # decision_id is left NULL


def test_the_one_forward_foreign_key_survives_create_table(applied: sqlite3.Connection) -> None:
    """`block.decision_id -> route_decision`, whose parent `0004_runtime.sql` creates.

    The exception 07 section 3 takes is that SQLite resolves a parent at the first DML on the
    child row and never at `CREATE TABLE`. All three halves are asserted: the foreign key is
    declared, the parent table does not exist, and the migration applied anyway with enforcement
    on. `PRAGMA foreign_key_check` reports nothing because a migration writes no rows.
    """
    targets = {row[2] for row in applied.execute("PRAGMA foreign_key_list(block)")}
    assert "route_decision" in targets
    assert "route_decision" not in _objects(applied, "table")
    assert applied.execute("PRAGMA foreign_key_check").fetchall() == []


# ---------------------------------------------------------------------------
# 3. It is a transcription of the charter, with exactly one rename
# ---------------------------------------------------------------------------


def test_every_create_table_appears_in_the_charter_with_the_same_columns(
    plan: PlanDocs, migration_sql: str
) -> None:
    """The transcription assertion. One rename is expected and is CHECKED, not tolerated:
    `block.title` -> `block.label`, ADR-1 decision 7 (adr/0001:103), so that `Kind.TITLE` keeps
    the word. 07 section 3.3 makes it load-bearing -- `head_fts` is an external-content FTS5 table
    over this column, and a stale `title` raises `no such column: title` when 0003 applies, which
    by the forward-reference rule takes G27(b)'s whole run with it."""
    plan.require()
    charter = _charter_ddl(plan)
    renames = {"block": {"title": "label"}}
    for table in TABLES_07_ASSIGNS:
        mine = _table_body(migration_sql, table)
        theirs = _table_body(charter, table)
        assert mine is not None, f"0001 does not declare {table}"
        assert theirs is not None, f"charter.md declares no CREATE TABLE {table}"
        rename = renames.get(table, {})
        expected = tuple(rename.get(column, column) for column in _columns(theirs))
        assert _columns(mine) == expected, f"{table}'s columns diverge from charter.md"


def test_block_carries_label_and_not_title(applied: sqlite3.Connection, plan: PlanDocs) -> None:
    """The rename, asserted from the ADR rather than from memory."""
    plan.require()
    columns = {row[1] for row in applied.execute("PRAGMA table_info(block)")}
    assert "label" in columns
    assert "title" not in columns
    adr = ("adr/0001-terminology-lock-bulk-pass.md",)
    assert plan.grep(r"the column becomes \*\*`block\.label`\*\*", documents=adr), (
        "adr/0001 no longer carries decision 7's rename"
    )


def test_no_column_is_added_by_an_alter_table(
    applied: sqlite3.Connection, migration_sql: str
) -> None:
    """D3's three ownership columns and D4's `decision_id` are in the INITIAL DDL (03:2465-2469):
    `ALTER TABLE t ADD COLUMN x TEXT NOT NULL` succeeds only against an EMPTY table, so a store
    with rows could never gain them."""
    assert "ALTER TABLE" not in _strip_comments(migration_sql).upper()
    columns = {row[1] for row in applied.execute("PRAGMA table_info(block)")}
    assert {"origin_operator", "origin_driver", "driver_schema_v", "decision_id"} <= columns


def test_the_without_rowid_tables_are_the_charters(migration_sql: str) -> None:
    mine = {
        table
        for table in TABLES_07_ASSIGNS
        if "WITHOUT ROWID" in (_table_span(migration_sql, table) or ("", ""))[1].upper()
    }
    assert mine == set(WITHOUT_ROWID)


def test_it_declares_no_strict_table(migration_sql: str) -> None:
    """Eleven charter tables are STRICT (charter.md:4111) and none of them is L2's. Measured over
    charter.md:930-1235: zero `) STRICT;`.

    The word boundary is load-bearing: `restriction_bits` and `block_restricted` both contain the
    five letters, and a substring test passes on this file for the wrong reason.
    """
    tails = [(_table_span(migration_sql, table) or ("", ""))[1] for table in TABLES_07_ASSIGNS]
    assert not [tail for tail in tails if re.search(r"\bSTRICT\b", tail, re.IGNORECASE)]


def test_diag_block_id_is_deliberately_not_a_foreign_key(applied: sqlite3.Connection) -> None:
    """03:1813-1815: a diagnostic often concerns a block the parse then refused to write, and an
    FK would force a choice between losing the diagnostic and writing a block that was rejected."""
    columns = {row[1] for row in applied.execute("PRAGMA table_info(diag)")}
    assert "block_id" in columns
    keys = {(row[3], row[2]) for row in applied.execute("PRAGMA foreign_key_list(diag)")}
    assert ("block_id", "block") not in keys
    assert ("doc_ord", "doc") in keys  # the one FK diag DOES carry


def test_grid_slot_points_at_cell_and_not_at_block(applied: sqlite3.Connection) -> None:
    """`origin_id REFERENCES cell(block_id)` is narrower and deliberate: it makes "an origin that
    is not a cell of this table" unrepresentable rather than merely wrong (03:2062-2065)."""
    keys = {(row[3], row[2]) for row in applied.execute("PRAGMA foreign_key_list(grid_slot)")}
    assert ("origin_id", "cell") in keys
    assert ("origin_id", "block") not in keys


# ---------------------------------------------------------------------------
# 4. The interpolated literals, against the enums, in both directions
# ---------------------------------------------------------------------------


def test_the_os_kind_check_literals_equal_pixels_and_bytes(migration_sql: str) -> None:
    """03:1449-1451: "the generator emits `CHECK (os_kind <> 3 OR quad IS NOT NULL)` ... and CI
    asserts each literal against `OsKind.PIXELS`'s and `OsKind.BYTES`'s declaration index in both
    directions". A subquery inside a CHECK is prohibited, which is why the literal exists at all.

    BOTH DIRECTIONS: the ordinal the enum derives is in the file, and every `os_kind` literal in
    the file is one of those two and not some third member's.
    """
    pixels = _ord("origin_span_kind", "pixels")
    bytes_ = _ord("origin_span_kind", "bytes")
    assert (pixels, bytes_) == (
        list(OsKind).index(OsKind.PIXELS),
        list(OsKind).index(OsKind.BYTES),
    )
    body = _table_body(migration_sql, "block")
    assert body is not None
    assert f"CHECK (os_kind <> {pixels} OR quad IS NOT NULL)" in body
    assert f"CHECK (os_kind <> {bytes_} OR os_codec IS NOT NULL)" in body
    assert {int(found) for found in re.findall(r"os_kind <> (\d+)", body)} == {pixels, bytes_}


def test_the_pixels_check_refuses_a_polygonless_pixel_address(store: sqlite3.Connection) -> None:
    """`pixels` is the variant whose ADDRESS IS THE POLYGON (03 section 7.2), so a NULL `quad`
    leaves it with no address at all. A literal that matches the enum and guards nothing would
    still be a defect, which is why this reads the constraint functionally."""
    _seed_one_page(store)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_block(store, block_id=1, os_kind=_ord("origin_span_kind", "pixels"), quad=None)


def test_the_bytes_check_refuses_a_codecless_byte_range(store: sqlite3.Connection) -> None:
    """The `bytes` branch DECODES before it compares, so a NULL codec makes INV-10's predicate
    unevaluable rather than merely undocumented (03:1454-1457)."""
    _seed_one_page(store)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_block(store, block_id=1, os_kind=_ord("origin_span_kind", "bytes"), os_codec=None)


def test_the_shard_ordinal_check_is_interpolated_at_zero(migration_sql: str) -> None:
    """ST20, charter.md:1070-1076. SQLite prohibits a bind parameter in a CHECK body, so
    `:shard_ord` cannot appear; `0` is every single-store corpus's value and is re-asserted at
    each open against `index_state.shard_ord`."""
    body = _table_body(migration_sql, "block")
    assert body is not None
    assert "CHECK ((block_id >> 48) = 0)" in body
    assert ":shard_ord" not in body


def test_a_block_id_above_the_shard_ceiling_is_refused(store: sqlite3.Connection) -> None:
    _seed_one_page(store)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_block(store, block_id=1 << 48)


# ---------------------------------------------------------------------------
# 5. `enum_val` -- the domains, and parity in both directions
# ---------------------------------------------------------------------------


def test_the_fifteen_domains_partition_into_0001s_nine_and_0002s_six() -> None:
    """`enum_val` carries fifteen closed domains (03:2311, charter.md:942) and charter.md:4834
    assigns six of them to `0002_graph.sql`. The partition must be total and disjoint, or one file
    seeds a domain the other also seeds -- which `PRIMARY KEY (domain, ord)` would turn into an
    apply-time failure only if the two happened to choose colliding ordinals."""
    assert set(DOMAINS_0001).isdisjoint(DOMAINS_0002)
    assert set(DOMAINS_0001) | set(DOMAINS_0002) == set(ENUM_DOMAINS)
    assert len(ENUM_DOMAINS) == 15


def test_enum_val_holds_exactly_0001s_nine_domains(applied: sqlite3.Connection) -> None:
    rows = applied.execute("SELECT DISTINCT domain FROM enum_val").fetchall()
    assert {domain for (domain,) in rows} == set(DOMAINS_0001)


def test_enum_val_carries_no_format_domain(applied: sqlite3.Connection) -> None:
    """Ruled in `_notes/build-defects.md` D10, five loci against two: 03:2311-2312,
    charter.md:942, charter.md:7948, charter.md:8746 erratum D26 and adr/0012:197 all exclude
    `format`; 05-ingest-and-routing.md:633 and :2074 are the two defective sentences.

    The argument and not just the count: a format token is free text over a COMPUTED domain --
    core's forty-eight tokens union the ENABLED cards' `format_tokens` -- and `enum_val.ord` is an
    append-only STORED value, so enabling a driver would mint an ordinal and two installs would
    then disagree about `enum_val`. That is an INV-10 and a portability break.
    """
    counted = applied.execute("SELECT count(*) FROM enum_val WHERE domain = 'format'")
    assert counted.fetchone() == (0,)
    assert "format" not in ENUM_DOMAINS


def test_none_of_0002s_six_domains_is_seeded_here(applied: sqlite3.Connection) -> None:
    placeholders = ", ".join("?" for _ in DOMAINS_0002)
    statement = f"SELECT count(*) FROM enum_val WHERE domain IN ({placeholders})"  # noqa: S608
    assert applied.execute(statement, DOMAINS_0002).fetchone() == (0,)


def test_every_seeded_row_equals_enum_val_rows_exactly(applied: sqlite3.Connection) -> None:
    """PARITY, DIRECTION ONE: everything `enum_val_rows()` derives for 0001's nine domains is on
    disk. DIRECTION TWO: nothing on disk is absent from the derivation.

    `enum_val_rows()` is the single site that applies 03 section 2.1's ordinal rule, so this
    compares one derivation against one table rather than two derivations against each other
    (charter.md:939, "CI asserts parity in both directions").
    """
    derived = {row for row in enum_val_rows() if row[0] in DOMAINS_0001}
    stored = set(applied.execute("SELECT domain, ord, name FROM enum_val").fetchall())
    assert stored == derived
    assert len(stored) == len(derived) == EXPECTED_ROWS


def test_each_domains_ordinals_follow_section_2_1s_rule(applied: sqlite3.Connection) -> None:
    """The rule, per domain: an ordered IntEnum stores the MEMBER'S OWN INTEGER; a StrEnum stores
    DECLARATION ORDER. `trust` and `quote` are the two IntEnums here and their integers coincide
    with declaration order -- which is not a licence to conflate the two rules, because the
    coincidence is exactly what `MIN()` over a set depends on."""
    for domain, vocabulary in DOMAIN_CLASSES.items():
        stored = applied.execute(
            "SELECT ord, name FROM enum_val WHERE domain = ? ORDER BY ord", (domain,)
        ).fetchall()
        members = list(vocabulary.__members__.values())
        assert len(stored) == len(members), f"{domain} has {len(stored)} rows for {len(members)}"
        pairs = zip(stored, members, strict=True)
        for index, ((ordinal, name), member) in enumerate(pairs):
            assert name == member.name.lower()
            expected = int(member) if isinstance(member, int) else index
            assert ordinal == expected, f"{domain}.{name} stored {ordinal}, rule says {expected}"


def test_trust_and_quote_are_ordered_so_min_over_a_set_is_its_weakest_member(
    applied: sqlite3.Connection,
) -> None:
    """The reading that makes `segment.quote_min` a gate rather than a lie (charter.md:1253-1260).

    Under a declaration-ordered StrEnum with VERBATIM first, `MIN()` returned the BEST tier
    present, so one verbatim block in a segment made the whole segment pass the byte-exactness
    gate for its reflowed and synthetic members.
    """
    assert _ord("trust", "ambiguous") < _ord("trust", "extracted")
    assert _ord("quote", "synthetic") < _ord("quote", "verbatim")
    weakest = applied.execute(
        "SELECT min(ord) FROM enum_val WHERE domain = 'quote' AND name IN "
        "('verbatim', 'reflowed', 'synthetic')"
    ).fetchone()
    assert weakest == (int(Quote.SYNTHETIC),)


def test_every_seeded_domain_types_a_column_that_exists_in_this_file(
    applied: sqlite3.Connection,
) -> None:
    """A domain seeded here with no column here would belong to another migration; a column here
    with no domain would be an integer nobody can decode."""
    assert set(DOMAIN_COLUMNS) == set(DOMAINS_0001)
    for domain, sites in DOMAIN_COLUMNS.items():
        for table, column in sites:
            columns = {row[1] for row in applied.execute(f"PRAGMA table_info({table})")}
            assert column in columns, f"{domain} types {table}.{column}, which does not exist"


def test_one_domain_name_cannot_hold_two_vocabularies(store: sqlite3.Connection) -> None:
    """`PRIMARY KEY (domain, ord)` is the mechanism that struck `ref_kind` as a second spelling of
    `akind` (charter.md:945-947)."""
    with pytest.raises(sqlite3.IntegrityError):
        store.execute(
            "INSERT INTO enum_val (domain, ord, name) VALUES ('kind', 0, 'something_else')"
        )


# ---------------------------------------------------------------------------
# 6. `block_fts` -- the option set 07 section 3.3 owns, and the two guards
# ---------------------------------------------------------------------------


def test_the_block_fts_option_set_is_07_section_3_3s(plan: PlanDocs, migration_sql: str) -> None:
    """07 section 3.3 is normative for the options and 03 section 13.1 prints the statement; both
    documents carry it verbatim because this file is one golden DDL. Changing an option is a
    SCHEMA major bump and the change is made in 07 section 3.3, never here."""
    plan.require()
    text = _strip_comments(migration_sql)
    for option in (
        "content='block'",
        "content_rowid='block_id'",
        "tokenize='unicode61 remove_diacritics 2'",
        "detail='full'",
        "columnsize=1",
    ):
        assert option in text, f"block_fts lost {option}"
        assert plan.grep(re.escape(option), documents=("07-store-and-retrieval.md",)), (
            f"{option} is no longer in 07, which owns it"
        )
    assert "prefix=" not in text, "prefix is DELIBERATELY absent (07 section 3.3)"
    assert "rank=" not in text, "a persistent rank would put the scorer outside SCORER_VERSION"


def test_block_fts_holds_no_second_copy_of_the_text(store: sqlite3.Connection) -> None:
    """INV-1, by construction: `content='block'` makes it external-content, so only the inverted
    index is stored and the column values are read back out of `block`."""
    _seed_one_page(store)
    _insert_block(store, block_id=1, text="the quick brown fox")
    hits = store.execute("SELECT rowid FROM block_fts WHERE block_fts MATCH 'brown'").fetchall()
    assert hits == [(1,)]
    stored = store.execute("SELECT text FROM block_fts WHERE rowid = 1").fetchone()
    assert stored == ("the quick brown fox",)  # read back THROUGH `block`, not from a copy


def test_the_insert_trigger_carries_both_guards(store: sqlite3.Connection) -> None:
    """Skip rows where `state <> 0`; skip rows where `text IS NULL` (03:2429-2431)."""
    _seed_one_page(store)
    _insert_block(store, block_id=10, text="indexed")
    _insert_block(store, block_id=11, text="tombstoned", state=1)
    _insert_block(store, block_id=12, text=None)
    indexed = store.execute("SELECT rowid FROM block_fts WHERE block_fts MATCH 'indexed'")
    assert indexed.fetchall() == [(10,)]
    hidden = store.execute("SELECT count(*) FROM block_fts WHERE block_fts MATCH 'tombstoned'")
    assert hidden.fetchone() == (0,)
    assert store.execute("INSERT INTO block_fts(block_fts) VALUES('integrity-check')")


def test_tombstoning_removes_the_row_from_the_index_and_re_adds_nothing(
    store: sqlite3.Connection,
) -> None:
    """03:2458-2460, verbatim: "Tombstoning is an `UPDATE state 0 -> 1`, so `block_fts_au`
    removes the row from the index and does not re-add it -- there is no separate tombstone
    trigger."
    """
    _seed_one_page(store)
    _insert_block(store, block_id=20, text="ephemeral")
    before = store.execute("SELECT count(*) FROM block_fts WHERE block_fts MATCH 'ephemeral'")
    assert before.fetchone() == (1,)
    store.execute("UPDATE block SET state = 1 WHERE block_id = 20")
    after = store.execute("SELECT count(*) FROM block_fts WHERE block_fts MATCH 'ephemeral'")
    assert after.fetchone() == (0,)
    assert store.execute("INSERT INTO block_fts(block_fts) VALUES('integrity-check')")


def test_the_delete_command_row_carries_the_old_values_exactly_as_indexed(
    store: sqlite3.Connection,
) -> None:
    """An external-content table stores no text of its own, so a `'delete'` whose text differs
    from what was indexed corrupts the index SILENTLY. The `_au` trigger's first statement is what
    makes an edit safe: it deletes OLD.text before inserting NEW.text (07 section 3.3)."""
    _seed_one_page(store)
    _insert_block(store, block_id=30, text="before")
    store.execute("UPDATE block SET text = 'after' WHERE block_id = 30")
    gone = store.execute("SELECT count(*) FROM block_fts WHERE block_fts MATCH 'before'")
    assert gone.fetchone() == (0,)
    kept = store.execute("SELECT rowid FROM block_fts WHERE block_fts MATCH 'after'").fetchall()
    assert kept == [(30,)]
    assert store.execute("INSERT INTO block_fts(block_fts) VALUES('integrity-check')")


def test_block_fts_indexes_every_generation_and_ow_block_head_is_what_filters(
    store: sqlite3.Connection,
) -> None:
    """03:2460-2462: `block_fts` indexes EVERY generation, including staged ones, so a lexical
    search joins `ow_block_head`. Both halves are asserted here, because the second is the reason
    the first is safe.
    """
    _seed_one_page(store)
    _seed_one_page(store, gen=2)
    _insert_block(store, block_id=40, gen=1, text="staged and head share a term")
    _insert_block(store, block_id=41, gen=2, text="staged and head share a term")
    matched = store.execute(
        "SELECT rowid FROM block_fts WHERE block_fts MATCH 'staged' ORDER BY rowid"
    ).fetchall()
    assert matched == [(40,), (41,)]  # BOTH generations are in the index
    visible = store.execute("SELECT block_id FROM ow_block_head ORDER BY block_id").fetchall()
    assert visible == [(40,)]  # doc.gen is 1, so gen 2 is durable and INVISIBLE


def test_the_cite_index_is_gen_free_and_the_addr_index_is_not(store: sqlite3.Connection) -> None:
    """`block_cite` is UNIQUE `(doc_ord, cite)` and `block_addr` UNIQUE `(doc_ord, gen, addr)`:
    `addr` legitimately repeats across generations because it is a POSITION, and `cite` must not,
    or `d7#412` would name a different row at gen 41 and gen 42 (charter.md:1081-1085)."""
    _seed_one_page(store)
    _seed_one_page(store, gen=2)
    _insert_block(store, block_id=50, gen=1, addr="p0/1", cite="d1#1")
    _insert_block(store, block_id=51, gen=2, addr="p0/1", cite="d1#2")  # same addr, new gen: legal
    with pytest.raises(sqlite3.IntegrityError):
        _insert_block(store, block_id=52, gen=2, addr="p0/2", cite="d1#1")


# ---------------------------------------------------------------------------
# Row-chain helpers -- the minimum a `block` row needs in order to exist
# ---------------------------------------------------------------------------


def _seed_one_page(connection: sqlite3.Connection, *, gen: int = 1) -> None:
    """One `doc`, one `producer` and one `page`, so a `block` row has parents to point at.

    `doc.gen` stays 1 whatever `gen` is asked for: a generation above the head is exactly the
    staged-and-invisible state `ow_block_head` exists to hide (03 section 1.1).
    """
    connection.execute(
        "INSERT OR IGNORE INTO doc (doc_ord, doc_key, source_sha256, uri, media_type, format,"
        " format_evidence, source_bytes, gen, status, model_version, declared, achieved)"
        " VALUES (1, X'00', X'00', 'file:///a.pdf', 'application/pdf', 'pdf', '{}', 1, 1, 'ok',"
        " '1.1', '{}', '{}')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO producer (producer_id, operator, op_version, code_fingerprint,"
        " options_digest) VALUES (1, 'parse.pdf', 1, 'abc', X'00')"
    )
    connection.execute(
        "INSERT OR IGNORE INTO page (doc_ord, gen, page, page_kind, method, producer_id)"
        " VALUES (1, ?, 0, ?, ?, 1)",
        (gen, _ord("page_kind", "page"), _ord("method", "text_layer")),
    )


def _insert_block(
    connection: sqlite3.Connection,
    *,
    block_id: int,
    gen: int = 1,
    addr: str | None = None,
    cite: str | None = None,
    text: str | None = "text",
    state: int = 0,
    os_kind: int | None = None,
    os_codec: str | None = "utf-8/strict",
    quad: bytes | None = b"\x00" * 32,
) -> None:
    """One `block` row with every NOT NULL column stated and no default relied on.

    `os_kind` defaults to `bytes`, whose CHECK requires `os_codec`; `quad` is supplied by default
    so that a caller testing the `pixels` branch can withhold it and see the constraint fire.
    """
    connection.execute(
        "INSERT INTO block (block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text,"
        " content_digest, quad, os_kind, os_codec, producer_id, method, trust, quote,"
        " origin_operator, origin_driver, driver_schema_v, state)"
        " VALUES (?, 1, ?, 0, ?, ?, ?, ?, ?, ?, X'00', ?, ?, ?, 1, ?, ?, ?, 'parse.pdf',"
        " 'parse.pdf.pdfium', 1, ?)",
        (
            block_id,
            gen,
            f"p0/{block_id}" if addr is None else addr,
            f"d1#{block_id}" if cite is None else cite,
            block_id,
            _ord("kind", "paragraph"),
            _ord("layer", "body"),
            text,
            quad,
            _ord("origin_span_kind", "bytes") if os_kind is None else os_kind,
            os_codec,
            _ord("method", "text_layer"),
            _ord("trust", "extracted"),
            _ord("quote", "verbatim"),
            state,
        ),
    )
