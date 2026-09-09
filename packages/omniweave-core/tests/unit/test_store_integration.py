"""The store seams no single module's tests can reach, plus the object-count reconciliation.

Every module in the store landed with its own suite, and each is necessarily blind in the same
place: `sqlite.py`'s tests are `sqlite.py`'s, `maintenance.py` and `walvalve.py` take a connection
they never open, `migrate.py` is tested against a scratch file, and `Doc` reads through a fake
reader. Nothing asserted that the pieces compose. This file does, over one real `.owstore` built
by the shipped migrations.

Two of the assertions here are the reason the file exists rather than being a nice-to-have.

**Snapshot isolation is checked in BOTH directions.** ST2 (07-store-and-retrieval.md:2758-2799)
says one query is one `BEGIN DEFERRED`, so a commit landing mid-query is invisible to it. A test
that only asserts "the two reads agree" passes just as well against a connection that never saw
the commit at all, or against a reader pointed at the wrong file. So the commit is also asserted to
become visible once the snapshot closes. The pair `0 == 0` then `0 -> 1` is the evidence; either
half alone is not.

**A raising transaction closure is checked for its EFFECT, not its exception.** That the exception
reaches the submitter is the easy half. The half that matters is that the row the closure wrote
before raising is gone, because a store thread that swallowed the rollback would still re-raise
and still look correct.

Specified in 07-store-and-retrieval.md sections 2, 2.1, 10.1-10.4 and 11, and
11-repo-layout.md section 5.1.

ON THE TEST TREE. 16-roadmap.md:445 states P2's exit criteria as
`uv run pytest tests/store tests/model tests/archive -q`, and no such tree exists -- everything in
this repository lives under `tests/unit/` and `tests/`. The split is a plan-ordered layout that
nobody has built; recorded in `_plan/_notes/build-defects.md` rather than invented here, because
moving forty test modules is not a decision a single test file should make.
"""

from __future__ import annotations

import re
import sqlite3  # noqa: TID251 -- see the module docstring: this file drives a REAL store.
from pathlib import Path

import pytest
from conftest import MIGRATIONS_DIR
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.maintenance import maintenance_window, planner_statistics

# A fixed timestamp. `time.time()` is banned in library code and injected everywhere in the store,
# so a test that reads the ambient clock would be asserting against a value the production path
# cannot produce. Any int works; this one is legible.
NOW_NS = 1_757_400_000_000_000_000


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A real `.owstore` with all four migrations applied, closed and ready to be re-opened."""
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
    finally:
        connection.close()
    return path


# ---------------------------------------------------------------------------------------------
# The pieces compose
# ---------------------------------------------------------------------------------------------


def test_a_fresh_store_opens_migrates_and_is_internally_consistent(store: Path) -> None:
    """`connect` then `apply_pending` produces a store SQLite itself calls sound."""
    connection = ow.connect(store)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        domains = connection.execute("SELECT count(DISTINCT domain) FROM enum_val").fetchone()[0]
        assert domains == 15, f"the fifteen closed domains are seeded; found {domains}"
    finally:
        connection.close()


def test_the_pragmas_are_in_force_on_a_reopened_store_and_not_merely_issued(store: Path) -> None:
    """Read back what SQLite reports, not what `CONN_PRAGMAS` says.

    `sqlite.py` asserts the issue ORDER by recording statements, which is the property
    07:181-183 makes load-bearing. This asserts the orthogonal thing: that the values actually
    took effect on a file that already existed, which is where `CREATE_PRAGMAS` versus
    `CONN_PRAGMAS` versus `INIT_PRAGMAS` could silently diverge.
    """
    connection = ow.connect(store)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA page_size").fetchone()[0] == 8192
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL
    finally:
        connection.close()


def test_re_applying_the_migration_set_does_nothing(store: Path) -> None:
    """Forward-only. 11-repo-layout.md:1186's "applied forward-only in numeric order"."""
    connection = ow.connect(store)
    try:
        assert migrate.apply_pending(connection, now_ns=NOW_NS) == ()
    finally:
        connection.close()


def test_the_store_thread_runs_a_unit_and_rolls_a_raising_one_back_whole(store: Path) -> None:
    """INV-17's thread half, asserted through its EFFECT on the database.

    07:2722-2723: the store thread is the only holder of a `Connection` in a process and every
    write reaches it as a transaction closure on a bounded queue. The rollback is the part a
    plausible-looking implementation gets wrong: re-raising is easy, and leaving the partial row
    behind is invisible to any test that only catches the exception.
    """
    with ow.StoreThread(lambda: ow.connect(store)) as thread:
        blocks = thread.run(
            ow.Unit(
                name="count", run=lambda c: c.execute("SELECT count(*) FROM block").fetchone()[0]
            )
        )
        assert blocks == 0

        def writes_then_raises(connection: sqlite3.Connection) -> object:
            connection.execute("INSERT INTO meta(k, v) VALUES ('integration', 'x')")
            message = "deliberate, to prove the rollback"
            raise RuntimeError(message)

        with pytest.raises(RuntimeError, match="deliberate"):
            thread.run(ow.Unit(name="boom", run=writes_then_raises))

        left = thread.run(
            ow.Unit(
                name="check",
                run=lambda c: c.execute(
                    "SELECT count(*) FROM meta WHERE k = 'integration'"
                ).fetchone()[0],
            )
        )
        assert left == 0, "the raising closure's row survived; the transaction did not roll back"


def test_a_commit_during_one_snapshot_is_invisible_to_it_and_visible_after_it(store: Path) -> None:
    """ST2, both directions. See the module docstring for why one direction is not enough.

    07:2786-2789: "WAL gives the reader a consistent view from that first read without blocking
    the writer, so a re-index commit during a query is **invisible to that query** -- not 'mostly
    invisible'."
    """
    writer = ow.connect(store)
    reader = ow.connect_readonly(store)
    try:
        with ow.snapshot(reader) as snap:
            before = reader.execute("SELECT count(*) FROM meta").fetchone()[0]
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO meta(k, v) VALUES ('mid_query', '1')")
            writer.commit()
            during = reader.execute("SELECT count(*) FROM meta").fetchone()[0]
            assert during == before, "a commit landed inside the snapshot; ST2 is broken"
            assert isinstance(snap.token, sqlite3.Connection), "the SQLite backend owns the token"
            assert isinstance(snap.generation, int)

        after = reader.execute("SELECT count(*) FROM meta").fetchone()[0]
        assert after == before + 1, (
            "the commit never became visible, so the assertion above proved nothing -- "
            "this reader may not be looking at the file the writer wrote"
        )
    finally:
        reader.close()
        writer.close()


def test_a_readonly_open_does_not_move_the_stores_mtime(store: Path) -> None:
    """07:2748-2751. A read that perturbs freshness makes absence gate 6 fire on its own
    observation, so the `connect_readonly` ladder exists to keep a read inert."""
    before = store.stat().st_mtime_ns
    connection = ow.connect_readonly(store)
    try:
        connection.execute("SELECT count(*) FROM block").fetchone()
    finally:
        connection.close()
    assert store.stat().st_mtime_ns == before


def test_the_maintenance_operations_run_against_a_real_store(store: Path) -> None:
    """They take a connection they never open, so this is the first time they see a real one."""
    connection = ow.connect(store)
    try:
        assert planner_statistics(connection) is not None
        assert maintenance_window(connection) is not None
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


# ---------------------------------------------------------------------------------------------
# The object-count reconciliation, so nobody re-panics about 74 against 91
# ---------------------------------------------------------------------------------------------

# `16-roadmap.md:415` prices W2.2 at **91** `CREATE TABLE`, and an applied P2 store holds far
# fewer. Every absence is phase-correct or belongs to a separate database FILE, and this is the
# arithmetic, kept as a test because the shortfall looks alarming and has already been
# mis-reported once (`_plan/_notes/build-defects.md` C1, where a scope regex read section 3 as
# everything up to `## 4.` and reported five sidecar tables as missing rows).
#
# The count that follows is over `CREATE TABLE` only, which is how `16:415` states it
# ("verified by `grep -oh 'CREATE TABLE [a-z_]*' charter.md | sort -u | wc -l`"). The three FTS5
# virtual tables are `CREATE VIRTUAL TABLE` and are therefore outside it in both places.
DEFERRED_TO_A_LATER_PHASE: dict[str, str] = {
    "artifact": "P9, 0005_out.sql (16-roadmap.md:428 -- 'one appended file')",
    "artifact_asset": "P9, 0005_out.sql",
    "artifact_cite": "P9, 0005_out.sql",
    "artifact_el": "P9, 0005_out.sql",
    "artifact_unit": "P9, 0005_out.sql",
    "corpus_card": "P6 W6.8 (16-roadmap.md:664)",
    "serve_emission": "P7, omniweave-serve",
}

LIVES_IN_A_SEPARATE_DATABASE_FILE: dict[str, str] = {
    "retrieval_event": "events.owstore -- the query ledger (07 section 3.10). DERIVED, deletable",
    "vec_manifest": "index.vec.owstore (07 section 3.9). DERIVED, deletable",
    "vseg": "index.vec.owstore (07 section 3.9)",
    "vfull": "index.vec.owstore (07 section 3.9)",
    "vpending": "index.vec.owstore (07 section 3.9)",
    "eval_corpus": ".oweval, 'a separate SQLite file' (16-roadmap.md:928, W10.1)",
    "eval_run": ".oweval (16-roadmap.md:928)",
    "eval_assertion": ".oweval (16-roadmap.md:928)",
    "eval_verdict": ".oweval (16-roadmap.md:928)",
    "eval_metric": ".oweval (16-roadmap.md:928)",
    "eval_counter": ".oweval (16-roadmap.md:928)",
    "eval_perf": ".oweval (16-roadmap.md:928)",
    "eval_calibration": ".oweval (16-roadmap.md:928)",
    "eval_flake": ".oweval (16-roadmap.md:928)",
}


CHARTER_TABLES = 90
"""How many tables the charter actually declares, and **it is not the 91 the plan says.**

`16-roadmap.md:415` prices W2.2 at "**91** `CREATE TABLE`" and prints its own verification:
`grep -oh 'CREATE TABLE [a-z_]*' charter.md | sort -u | wc -l`. That command over-counts by one.
`[a-z_]*` is zero-or-more, so at `charter.md:4115` -- a COMMENT reading "fails on the FIRST
`CREATE TABLE ... STRICT`" -- it matches `CREATE TABLE ` with an **empty** name, and `sort -u`
counts the empty string as a 91st distinct table. Change the `*` to a `+` and the same command
returns **90**, which is also what a comment-stripped parse returns.

The count is load-bearing in that row's arithmetic: "0.5 engineer-day per table ... => 45.5
engineer-days" is exactly 91 x 0.5. Recorded as `_plan/_notes/build-defects.md` D18.
"""


def _declared_tables(text: str) -> frozenset[str]:
    """`CREATE TABLE <name>` only, matching `16:415`'s own grep. Comments are stripped first.

    Stripping `--` comments is not fastidiousness. Running the naive grep over the shipped DDL
    yields a table called `still`, from the prose "this CREATE TABLE still succeeds under" in a
    comment at `0001_init.sql:300`. That phantom is the fourth naive-scan false positive on this
    project, and it is what this helper exists to prevent.
    """
    stripped = "\n".join(line.split("--", 1)[0] for line in text.splitlines())

    return frozenset(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)", stripped))


def test_a_comment_cannot_contribute_a_table_name() -> None:
    """The phantom, pinned. Without this the helper above is untested cleverness."""
    poisoned = "-- and this CREATE TABLE still succeeds under\nCREATE TABLE real (a INT);\n"
    assert _declared_tables(poisoned) == {"real"}


def test_every_charter_table_is_either_built_deferred_or_in_another_file(plan: object) -> None:
    """The reconciliation. 91 = built + deferred + separate-file, with no remainder either way."""
    plan.require()  # type: ignore[attr-defined]
    charter = _declared_tables(plan.text("_notes/charter.md"))  # type: ignore[attr-defined]
    assert len(charter) == CHARTER_TABLES, (
        f"the charter declares {len(charter)} tables, not {CHARTER_TABLES}. "
        f"See CHARTER_TABLES above: 16-roadmap.md:415's own count of 91 is off by one."
    )

    built: set[str] = set()
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        built |= _declared_tables(path.read_text(encoding="utf-8"))

    accounted = built | set(DEFERRED_TO_A_LATER_PHASE) | set(LIVES_IN_A_SEPARATE_DATABASE_FILE)
    unaccounted = sorted(charter - accounted)
    assert unaccounted == [], (
        f"charter tables in no category: {unaccounted}. Either the migration that creates them is "
        f"missing, or they belong in one of the two dictionaries above with the plan line that "
        f"says so."
    )

    invented = sorted(built - charter)
    assert invented == [], f"the migrations create tables the charter does not declare: {invented}"

    overlap = sorted(set(DEFERRED_TO_A_LATER_PHASE) & built)
    assert overlap == [], f"listed as deferred but actually built: {overlap}"
    sidecar_overlap = sorted(set(LIVES_IN_A_SEPARATE_DATABASE_FILE) & built)
    assert sidecar_overlap == [], (
        f"a sidecar table was welded into the main store's migration: {sidecar_overlap}. "
        f"`rm index.vec.owstore` must cost CPU, not correctness (07:951)."
    )


def test_neither_absence_dictionary_names_a_table_the_charter_does_not_declare(
    plan: object,
) -> None:
    """A stale row here would exempt a name that no longer exists, which is how an allow-list
    stops being a record and starts being a hole."""
    plan.require()  # type: ignore[attr-defined]
    charter = _declared_tables(plan.text("_notes/charter.md"))  # type: ignore[attr-defined]
    for name in (*DEFERRED_TO_A_LATER_PHASE, *LIVES_IN_A_SEPARATE_DATABASE_FILE):
        assert name in charter, f"{name} is excused but the charter does not declare it"
