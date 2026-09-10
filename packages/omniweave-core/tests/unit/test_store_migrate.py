"""`omniweave_core.store.migrate` -- the forward-only loader that reads the DDL out of the wheel.

Specified by 11-repo-layout.md section 5.1 (:1184-1230: package data, `importlib.resources`,
forward-only, numeric order, one transaction each, and the three declared facts every `migration`
row carries) and 07-store-and-retrieval.md section 3.8 (:684-786: the `migration` table's columns
and its resumption semantics). `tools/gate_migrations.py` is G27(b), which asserts the same set from
the repository side; this module asserts the RUNNER, which the gate deliberately is not -- the gate
*"writes no `migration` row"* (gate_migrations.py:64) because no static reader can supply the three
declarations, and supplying them is exactly this loader's problem.

Three of these tests are shaped against a specific way of passing while broken:

1. **The `importlib.resources` claim is tested by REPLACING `files`.** Swapping the resource
   anchor's `files()` for a synthetic `joinpath`/`iterdir` tree changes what `migrations()` returns,
   which can only be true if the read goes through it. The `__file__` ban is a second instrument
   over the module's AST, not a grep: this module's docstrings quote the ban repeatedly, so a text
   search would either fire on the prose or be weakened until it fired on nothing.
2. **"Re-opening applies nothing a second time" is asserted on the RETURN VALUE and on the ledger**,
   because a loader that re-ran every file would also raise on the second `CREATE TABLE`, and a test
   that only caught the absence of an exception would not distinguish "skipped" from "crashed
   differently".
3. **The transaction boundary is asserted through a deliberate failure.** One transaction per file
   is invisible on a successful run; it is only observable when a later file aborts and the earlier
   ones are still there, and when a file aborts and NONE of its own objects are.

`import sqlite3` under a `noqa`: the subject is DDL applied to a real file, which is
`test_migration_0001.py:31-41`'s reason and `tools/gate_migrations.py:123`'s. A loader test that
read the SQL instead of applying it would catch no `CREATE INDEX` forward reference, no rollback
boundary and no `INTEGER PRIMARY KEY` collision, which are three of the things this module exists
to get right.
"""

from __future__ import annotations

import ast
import re
import sqlite3  # noqa: TID251 -- see the module docstring's last paragraph.
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from omniweave_core.contract import SCHEMA_STRING
from omniweave_core.errors import StoreError
from omniweave_core.store import migrate
from omniweave_core.store.migrate import (
    COST_CLASSES,
    MIGRATIONS_ANCHOR,
    MIGRATIONS_PARTS,
    NAME,
    UNDECLARED,
    Declaration,
    MigrationSource,
    applied_versions,
    apply_pending,
    conditions_from_config,
    migrations,
    select_statements,
)
from omniweave_core.store.sqlite import connect

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

NOW_NS = 1_700_000_000_000_000_000
SHIPPED = ("0001_init.sql", "0002_graph.sql", "0003_index.sql", "0004_runtime.sql")
"""The four files P2 ships (07-store-and-retrieval.md section 3's table). `0005_out.sql` is
[generation](09-generation.md)'s and is P9's, so a five-member set here would be a claim about
unwritten work."""


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def source(version: int, name: str, text: str) -> MigrationSource:
    """A synthetic `MigrationSource` with its declaration parsed out of its own text.

    Built through the module's own parser rather than by handing a `Declaration` in, so a test of a
    directive is a test of the parser and not of the dataclass.
    """
    return MigrationSource(
        version=version,
        name=name,
        text=text,
        declaration=migrate._parse_declaration(name, text),
    )


@dataclass
class FakeEntry:
    """One member of a synthetic resource tree: `name` and `read_text`, all `files()` needs."""

    name: str
    text: str

    def read_text(self, encoding: str = "utf-8") -> str:
        del encoding
        return self.text


@dataclass
class FakeRoot:
    """A `Traversable`-shaped stand-in: `joinpath` then `iterdir`, and nothing else.

    The two methods are exactly the two `migrations()` calls, which is the point: if the loader
    reached for a `Path`, a `__file__` or an `os.listdir`, this object could not satisfy it and the
    test that swaps it in would fail rather than pass quietly.
    """

    entries: Sequence[FakeEntry]
    joined: tuple[str, ...] = ()

    def joinpath(self, *parts: str) -> FakeRoot:
        return FakeRoot(entries=self.entries, joined=(*self.joined, *parts))

    def iterdir(self) -> Sequence[FakeEntry]:
        return list(self.entries)


def migrated(tmp_path: Path, *, corpus_id: str = "corpus-under-test") -> sqlite3.Connection:
    """An open, fully migrated store. The caller closes it."""
    connection = connect(tmp_path / "index.owstore")
    apply_pending(connection, now_ns=NOW_NS, corpus_id=corpus_id)
    return connection


# --------------------------------------------------------------------------------------------
# 1. Reading the set through `importlib.resources`
# --------------------------------------------------------------------------------------------


def test_the_loader_reads_the_set_through_importlib_resources_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swap `files()` and the whole set changes -- which is only possible if it is the only reader.

    11-repo-layout.md:1186 requires the DDL to be *"read through `importlib.resources` at use
    time"*, and `_plan/_notes/build-defects.md` D12 is why the directory is package data at all: the
    same bytes must be reachable from a wheel, a zipimport and a source checkout, and only a
    `Traversable` is all three. `FakeRoot` implements exactly `joinpath` and `iterdir`, so a loader
    that reached for a filesystem path could not be satisfied by it.

    The anchor and the sub-path are asserted too, because a loader reading the RIGHT way from the
    WRONG directory would otherwise pass.
    """
    captured: list[str] = []

    def fake_files(anchor: str) -> FakeRoot:
        captured.append(anchor)
        return FakeRoot(
            entries=[
                FakeEntry("0002_two.sql", "CREATE TABLE two(x);"),
                FakeEntry("0001_one.sql", "CREATE TABLE one(x);"),
                FakeEntry("notes.md", "not a migration"),
            ]
        )

    monkeypatch.setattr(migrate, "files", fake_files)
    found = migrations()
    assert captured == [MIGRATIONS_ANCHOR]
    assert [item.name for item in found] == ["0001_one.sql", "0002_two.sql"]
    assert [item.version for item in found] == [1, 2]
    assert MIGRATIONS_PARTS == ("schema", "migrations")


def test_the_loader_never_evaluates_dunder_file_or_dunder_path(repo_root: Path) -> None:
    """The literal form of the ban, over the module's own AST rather than over its text.

    `__file__` and `__path__` are banned under `packages/*/src/` because a package read as a
    resource has neither. `ast` and not a grep, because this module's docstrings quote the ban
    repeatedly and a grep would either fire on the prose or be weakened until it fired on nothing.
    The AST sees only what the interpreter would evaluate, which is the ban's actual subject.
    """
    text = (repo_root / "packages/omniweave-core/src/omniweave_core/store/migrate.py").read_text(
        encoding="utf-8"
    )
    banned = {"__file__", "__path__"}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Name):
            assert node.id not in banned, f"line {node.lineno} evaluates {node.id}"
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned, f"line {node.lineno} evaluates .{node.attr}"
    assert "from importlib.resources import files" in text


def test_the_shipped_set_is_the_four_p2_files_dense_from_one() -> None:
    """11-repo-layout.md section 5.2: unique and dense, and the prefix IS the apply order."""
    found = migrations()
    assert [item.name for item in found] == list(SHIPPED)
    assert [item.version for item in found] == [1, 2, 3, 4]
    assert all(NAME.match(item.name) for item in found)


def test_a_duplicate_migration_number_refuses_before_anything_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 5.2's failure: two PRs each adding `0004`, both green in isolation.

    *"`migration.version` is an INTEGER PRIMARY KEY, so applying both inserts version 4 twice and
    the second raises a constraint violation -- on every store in the fleet, at ingest time, after
    the first one has already committed its DDL."* The refusal is at READ time, before a
    transaction opens, which is the only place it costs nothing.
    """
    monkeypatch.setattr(
        migrate,
        "files",
        lambda _a: FakeRoot(
            entries=[FakeEntry("0001_a.sql", "SELECT 1;"), FakeEntry("0001_b.sql", "SELECT 1;")]
        ),
    )
    with pytest.raises(StoreError) as caught:
        migrations()
    assert "INTEGER PRIMARY KEY" in str(caught.value)


def test_a_gap_in_the_migration_numbers_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """*"A gap raises nothing at all"* on a fresh store, which is why density is asserted."""
    monkeypatch.setattr(
        migrate,
        "files",
        lambda _a: FakeRoot(
            entries=[FakeEntry("0001_a.sql", "SELECT 1;"), FakeEntry("0003_c.sql", "SELECT 1;")]
        ),
    )
    with pytest.raises(StoreError) as caught:
        migrations()
    assert "dense from 1" in str(caught.value)


def test_an_empty_migration_set_is_a_broken_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DDL ships inside the wheel, so an empty directory is not an empty schema."""
    monkeypatch.setattr(migrate, "files", lambda _a: FakeRoot(entries=[]))
    with pytest.raises(StoreError) as caught:
        migrations()
    assert "package data" in str(caught.value)


# --------------------------------------------------------------------------------------------
# 2. Applying to a real store
# --------------------------------------------------------------------------------------------


def test_the_shipped_set_applies_to_a_fresh_store_and_the_result_is_clean(tmp_path: Path) -> None:
    """The G27(b) assertion, taken through the RUNNER rather than through the gate.

    `PRAGMA foreign_key_check` is what makes the one forward foreign key in the shipped order --
    `block.decision_id -> route_decision`, `0001` naming a table `0004` creates -- a CHECKED
    exception rather than an assumed one (07:257-268). `integrity_check` is the other half.
    """
    connection = migrated(tmp_path)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert applied_versions(connection) == frozenset({1, 2, 3, 4})
    finally:
        connection.close()


def test_re_opening_applies_nothing_a_second_time(tmp_path: Path) -> None:
    """Forward-only means the second run is a no-op, and the ledger is what proves it.

    Both halves are asserted: `apply_pending` returns an EMPTY tuple, and the `migration` table
    still holds exactly four rows with their original `applied_at_ns`. A loader that re-applied
    would also raise, and an assertion that only caught the absence of a raise could not tell
    "skipped" from "failed in some other way".
    """
    path = tmp_path / "index.owstore"
    first = connect(path)
    try:
        assert len(apply_pending(first, now_ns=NOW_NS, corpus_id="c")) == 4
    finally:
        first.close()
    second = connect(path)
    try:
        assert apply_pending(second, now_ns=NOW_NS + 999, corpus_id="c") == ()
        stamps = second.execute("SELECT DISTINCT applied_at_ns FROM migration").fetchall()
        assert stamps == [(NOW_NS,)]
        assert second.execute("SELECT count(*) FROM migration").fetchone()[0] == 4
    finally:
        second.close()


def test_every_applied_file_gets_a_migration_row_carrying_its_three_declared_facts(
    tmp_path: Path,
) -> None:
    """11-repo-layout.md:1215-1221. `ow doctor` prints `unbackfilled_means` verbatim.

    All four shipped files are UNDECLARED today (see `migrate.UNDECLARED`), so the prose says so
    rather than guessing "nothing to backfill". The assertion is on that honesty: the string names
    the file and says the declaration is missing, which is the fact an operator can act on.
    """
    connection = migrated(tmp_path)
    try:
        rows = connection.execute(
            "SELECT version, name, cost_class, resumable, backfill_done, backfill_total, "
            "unbackfilled_means FROM migration ORDER BY version"
        ).fetchall()
        assert [row[1] for row in rows] == list(SHIPPED)
        for version, name, cost_class, resumable, done, total, means in rows:
            assert cost_class in COST_CLASSES
            assert resumable in (0, 1)
            assert done == 0
            assert total is None
            assert means, "unbackfilled_means is required prose and may not be empty"
            assert name in means
            assert means.startswith("undeclared: ")
            assert version in (1, 2, 3, 4)
    finally:
        connection.close()


def test_index_state_is_seeded_with_the_keys_a_store_open_reads(tmp_path: Path) -> None:
    """`0003_index.sql:37-38`: the tables are created empty and *"the runner writes"* these.

    `schema` is compared against `contract.SCHEMA_STRING`, which is the one site in the framework
    that formats the pair (ADR-9) -- so this asserts the single home rather than the literal `1.0`.
    """
    connection = migrated(tmp_path, corpus_id="seeded")
    try:
        state = dict(connection.execute("SELECT k, v FROM index_state").fetchall())
        assert state["schema"] == SCHEMA_STRING
        assert state["generation"] == "0"
        assert state["shard_ord"] == "0"
        assert state["fts_state"] == "ok"
        assert state["corpus_id"] == "seeded"
        assert connection.execute("SELECT count(*) FROM index_state").fetchone()[0] == 5
    finally:
        connection.close()


def test_a_migrated_store_reports_schema_major_one_and_that_is_the_frozen_value(
    tmp_path: Path,
) -> None:
    """16-roadmap.md:428 freezes `SCHEMA = 1`; :433-434 obliges v1.0 to ship the same value.

    **This is the literal, and the test above it deliberately is not.** That one compares
    `index_state.schema` against `contract.SCHEMA_STRING`, which is the correct instrument for
    ADR-9's single-homedness -- it proves the seed comes from the one formatting site -- and the
    wrong one for the freeze, because both sides of the equality are this build's own number.
    Renumbering `contract.SCHEMA` to `2` moves the constant, moves the seed, and leaves that
    assertion green while breaking the one promise 16-roadmap.md:433 calls an obligation
    "nothing else in the plan does" carry: *"v0.1 ships a store at `SCHEMA = 1`, and v1.0 ships
    the same `SCHEMA`."*

    So the value appears here once, on the DISK side, read back out of a store the shipped
    migrations built. That is not a second home for it -- `omniweave_core.contract` is still the
    sole code home and `index_state.schema` the sole disk home (ADR-9 decisions 1 and 3) -- it is
    an expectation a wrong constant cannot satisfy by agreeing with itself.

    The stamp is parsed rather than compared whole because 03:2700 fixes its spelling as
    `<major>.<minor>` and it is the MAJOR the freeze is about: a `SCHEMA` minor is the sanctioned
    additive-DDL move (:436-437), so pinning `"1.0"` here would fail the first legal minor bump
    and teach the next reader to delete the test. What may never move without breaking the
    published read contract is the `1`.
    """
    connection = migrated(tmp_path)
    try:
        row = connection.execute("SELECT v FROM index_state WHERE k = 'schema'").fetchone()
    finally:
        connection.close()
    assert row is not None, "a fully migrated store holds an `index_state.schema` row"
    stamp = str(row[0])
    major, dot, minor = stamp.partition(".")
    assert dot == ".", f"index_state.schema is {stamp!r}; 03:2700 spells it `<major>.<minor>`"
    assert minor.isdigit(), f"index_state.schema is {stamp!r}; the minor is an int"
    assert major == "1", (
        f"a store built from the shipped migrations stamps schema {stamp!r}; 16-roadmap.md:428 "
        f"freezes SCHEMA = 1 and :434 obliges v1.0 to ship the same major. A major bump is a "
        f"published read-contract break with a two-release deprecation window (02:211), not a "
        f"migration -- see the freeze paragraph at 16-roadmap.md:433-438 before editing this."
    )


def test_meta_never_gains_a_schema_key(tmp_path: Path) -> None:
    """ADR-9's other half: `index_state.schema` is the only place on disk that holds the pair."""
    connection = migrated(tmp_path)
    try:
        assert connection.execute("SELECT count(*) FROM meta WHERE k = 'schema'").fetchone() == (0,)
    finally:
        connection.close()


def test_a_later_migration_never_resets_the_generation_counter(tmp_path: Path) -> None:
    """`INSERT OR IGNORE`, not `OR REPLACE`: a seed must not rewind gate 3's comparison.

    **The fixture is a PARTIALLY migrated store, and that is the whole test.** Re-running the loader
    against an already-current store seeds nothing at all -- `apply_pending` only reaches
    `_seed_index_state` when it applied something -- so a version written with `OR REPLACE` would
    pass a test built that way. The reachable path is a store that received `0001`..`0003` from one
    release and `0004` from the next: the seed runs again, and `generation` and `corpus_id` are by
    then real values a re-seed would destroy.
    """
    path = tmp_path / "index.owstore"
    partial = connect(path)
    try:
        apply_pending(partial, now_ns=NOW_NS, sources=list(migrations())[:3], corpus_id="original")
        partial.execute("UPDATE index_state SET v = '17' WHERE k = 'generation'")
    finally:
        partial.close()
    rest = connect(path)
    try:
        assert [item.version for item in apply_pending(rest, now_ns=NOW_NS, corpus_id="other")] == [
            4
        ]
        state = dict(rest.execute("SELECT k, v FROM index_state").fetchall())
        assert state["generation"] == "17"
        assert state["corpus_id"] == "original"
    finally:
        rest.close()


# --------------------------------------------------------------------------------------------
# 3. The transaction boundary
# --------------------------------------------------------------------------------------------


def test_a_file_that_aborts_is_rolled_back_whole(tmp_path: Path) -> None:
    """11:1190-1191's recorded defect, reproduced: *"NEITHER FILE APPLIES."*

    The synthetic file creates a table and then an index on a table nobody has created, which is
    exactly the shape that made the pre-`0002`/`0003` ordering fail. The assertion is that the
    table it DID create is gone -- one transaction per file, rolled back whole.
    """
    connection = connect(tmp_path / "index.owstore")
    broken = source(
        1,
        "0001_broken.sql",
        "CREATE TABLE lands_first(x);\nCREATE INDEX bad ON not_yet_created(x);\n",
    )
    try:
        with pytest.raises(StoreError) as caught:
            apply_pending(connection, now_ns=NOW_NS, sources=[broken])
        assert "0001_broken.sql" in str(caught.value)
        assert not connection.in_transaction
        objects = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        assert objects == 0
    finally:
        connection.close()


def test_the_rows_for_the_files_before_0003_land_no_later_than_0003s_commit(
    tmp_path: Path,
) -> None:
    """`migration` ships in `0003_index.sql`, so `0001` and `0002` have nowhere to write.

    `0004_runtime.sql:32-36` draws the conclusion -- *"The row is therefore the applier's, for every
    file uniformly"* -- and the loader writes the two held-back rows inside `0003`'s transaction,
    the earliest transaction that can hold them. The test proves it by failing `0004`: the three
    earlier rows must be committed and the fourth must not exist.
    """
    connection = connect(tmp_path / "index.owstore")
    shipped = list(migrations())
    broken = source(4, "0004_broken.sql", "CREATE INDEX bad ON not_yet_created(x);\n")
    try:
        with pytest.raises(StoreError):
            apply_pending(connection, now_ns=NOW_NS, sources=[*shipped[:3], broken])
        rows = connection.execute("SELECT version FROM migration ORDER BY version").fetchall()
        assert rows == [(1,), (2,), (3,)]
    finally:
        connection.close()


def test_a_store_with_objects_and_no_ledger_refuses_and_names_the_remedy(tmp_path: Path) -> None:
    """The one window one-transaction-per-file cannot close, refused rather than guessed at.

    A crash after `0001` commits and before `0003` creates the ledger leaves objects with no record
    of which files produced them, and re-applying `0001` would abort on `table meta already exists`.
    The remedy is 07:158-160's documented one -- *"`rm -rf .omniweave` is a supported, documented,
    lossless operation"* -- and it is affordable because the window is a brand-new store's first
    open: `SCHEMA` 1 ships all four files, so `0001` never meets a store that holds data.
    """
    connection = connect(tmp_path / "index.owstore")
    try:
        apply_pending(connection, now_ns=NOW_NS, sources=list(migrations())[:2])
        assert not connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'migration'"
        ).fetchone()[0]
        with pytest.raises(StoreError) as caught:
            apply_pending(connection, now_ns=NOW_NS)
        assert "rm -rf .omniweave" in caught.value.fix
    finally:
        connection.close()


def test_a_pending_migration_numbered_below_an_applied_one_refuses(tmp_path: Path) -> None:
    """11:1237-1239's gap case, as it reaches a STORE rather than as it reaches an empty file.

    *"PRs adding `0004` and `0006` with `0005` never landing produce a set that applies fine to an
    empty file and applies out of intended order on a store that received `0006` in an earlier
    release and `0004` in a later one."* The fixture is that store: the four shipped files plus a
    `0006`, and then a `0005` offered afterwards.
    """
    connection = connect(tmp_path / "index.owstore")
    six = source(6, "0006_early.sql", "CREATE TABLE arrived_early(x);\n")
    five = source(5, "0005_late.sql", "CREATE TABLE arrived_late(x);\n")
    try:
        apply_pending(connection, now_ns=NOW_NS, sources=[*migrations(), six])
        assert applied_versions(connection) == frozenset({1, 2, 3, 4, 6})
        with pytest.raises(StoreError) as caught:
            apply_pending(connection, now_ns=NOW_NS, sources=[*migrations(), five, six])
        assert "forward-only" in str(caught.value)
        assert "0005_late.sql" in str(caught.value)
    finally:
        connection.close()


# --------------------------------------------------------------------------------------------
# 4. Declarations
# --------------------------------------------------------------------------------------------


def test_an_undeclared_migration_says_so_rather_than_guessing_nothing_to_backfill() -> None:
    """The prose an operator reads says the true thing, not the plausible one.

    Guessing *"nothing to backfill"* on a file that might have backfilled something is precisely the
    failure `unbackfilled_means` exists to prevent, so the fallback names the missing declaration.
    """
    bare = source(1, "0001_bare.sql", "CREATE TABLE t(x);\n")
    assert bare.declaration.source == UNDECLARED
    assert bare.declaration.cost_class == "ddl"
    assert bare.declaration.resumable == 0
    assert bare.declaration.unbackfilled_means.startswith("undeclared: 0001_bare.sql")
    assert "nothing to backfill" not in bare.declaration.unbackfilled_means


def test_a_declared_migration_carries_the_authors_three_facts() -> None:
    """The `@ow:migration` directive, in the `@ow:` namespace `0003_index.sql:56` establishes."""
    text = (
        "-- @ow:migration cost_class = backfill, resumable = 1\n"
        "-- @ow:unbackfilled_means rows without os_a resolve to the whole page, not a span\n"
        "UPDATE block SET os_a = 0;\n"
    )
    declared = source(9, "0009_backfill.sql", text)
    assert declared.declaration == Declaration(
        cost_class="backfill",
        resumable=1,
        unbackfilled_means="rows without os_a resolve to the whole page, not a span",
        source="0009_backfill.sql",
    )


def test_a_declaration_without_its_prose_refuses_rather_than_filling_it_in() -> None:
    """An author who declared two of three facts stopped halfway, and that must be visible."""
    with pytest.raises(StoreError) as caught:
        source(
            9, "0009_half.sql", "-- @ow:migration cost_class = backfill, resumable = 1\nSELECT 1;\n"
        )
    assert "unbackfilled_means" in str(caught.value)


def test_a_cost_class_outside_the_shipped_check_refuses() -> None:
    """`migration.cost_class` is `CHECK (cost_class IN ('ddl','backfill','rebuild'))`."""
    assert set(COST_CLASSES) == {"ddl", "backfill", "rebuild"}
    with pytest.raises(StoreError):
        Declaration(cost_class="cheap", resumable=0, unbackfilled_means="x", source="s")


def test_empty_prose_is_the_one_value_unbackfilled_means_may_not_take() -> None:
    """`ow doctor` prints it verbatim, and printing nothing is not printing the answer."""
    with pytest.raises(StoreError):
        Declaration(cost_class="ddl", resumable=0, unbackfilled_means="", source="s")


# --------------------------------------------------------------------------------------------
# 5. Optional regions
# --------------------------------------------------------------------------------------------


def test_the_trigram_region_is_applied_only_when_its_condition_holds() -> None:
    """`0003_index.sql:53-58`'s contract, over the shipped file rather than over a fixture.

    Section 3.4's trigram set is *"created ONLY when [retrieval] trigram = true, which a static SQL
    file cannot decide"*. The region markers themselves never reach SQLite either way.
    """
    third = next(item for item in migrations() if item.version == 3)
    off = select_statements(third, {"trigram": False})
    on = select_statements(third, {"trigram": True})
    assert len(on) > len(off)
    assert on.count("CREATE") > off.count("CREATE")
    for text in (on, off):
        assert not [line for line in text.splitlines() if migrate.OPTIONAL_BEGIN.match(line)]
        assert not [line for line in text.splitlines() if migrate.OPTIONAL_END.match(line)]
    # The header comment at 0003_index.sql:56 DOCUMENTS the marker syntax behind a second `--`,
    # so the two-dash-anchored regexes do not match it and the prose survives into both variants.
    # That is the desired reading -- a file may describe its own grammar -- and it is asserted here
    # rather than assumed, because a looser regex would silently delete the whole trigram region's
    # neighbourhood from every store.
    assert "@ow:optional-begin <name>" in off


def test_the_trigram_region_actually_creates_objects_when_it_is_on(tmp_path: Path) -> None:
    """The region is DDL, so the observable difference is the object count in `sqlite_master`."""
    off_store = connect(tmp_path / "off.owstore")
    on_store = connect(tmp_path / "on.owstore")
    try:
        apply_pending(off_store, now_ns=NOW_NS, conditions={"trigram": False})
        apply_pending(on_store, now_ns=NOW_NS, conditions={"trigram": True})
        off = off_store.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        on = on_store.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        assert on > off
    finally:
        off_store.close()
        on_store.close()


def test_the_default_conditions_come_from_the_declared_config_default() -> None:
    """`[retrieval] trigram` has one home, and it is `config.KEYS`, not a literal here."""
    assert conditions_from_config() == {"trigram": False}
    assert conditions_from_config({"retrieval.trigram": True}) == {"trigram": True}


def test_an_unknown_optional_region_refuses_rather_than_guessing() -> None:
    """Defaulting an unknown region either way silently changes which DDL a store receives."""
    text = "-- @ow:optional-begin mystery\nCREATE TABLE t(x);\n-- @ow:optional-end mystery\n"
    with pytest.raises(StoreError) as caught:
        select_statements(source(1, "0001_x.sql", text), {"trigram": False})
    assert "mystery" in str(caught.value)


def test_an_unclosed_optional_region_refuses() -> None:
    """A region that runs to end-of-file would swallow every statement after it."""
    text = "-- @ow:optional-begin trigram\nCREATE TABLE t(x);\n"
    with pytest.raises(StoreError) as caught:
        select_statements(source(1, "0001_x.sql", text), {"trigram": True})
    assert "never closed" in str(caught.value)


def test_a_mismatched_region_end_refuses() -> None:
    """`-end a` closing `-begin b` means the file's regions are not what its author thought."""
    text = "-- @ow:optional-begin trigram\nSELECT 1;\n-- @ow:optional-end other\n"
    with pytest.raises(StoreError):
        select_statements(source(1, "0001_x.sql", text), {"trigram": True, "other": True})


def test_a_nested_optional_region_refuses() -> None:
    """Regions do not nest; a second `-begin` inside one is a file nobody reads twice alike."""
    text = "-- @ow:optional-begin trigram\n-- @ow:optional-begin other\nSELECT 1;\n"
    with pytest.raises(StoreError):
        select_statements(source(1, "0001_x.sql", text), {"trigram": True, "other": True})


def test_the_region_markers_are_spelled_as_the_shipped_file_spells_them() -> None:
    """A transcription check: the loader's regexes against `0003_index.sql`'s own comment."""
    third = next(item for item in migrations() if item.version == 3)
    begins = [line for line in third.text.splitlines() if migrate.OPTIONAL_BEGIN.match(line)]
    ends = [line for line in third.text.splitlines() if migrate.OPTIONAL_END.match(line)]
    assert len(begins) == len(ends) == 1
    assert re.search(r"@ow:optional-begin\s+trigram", begins[0])
