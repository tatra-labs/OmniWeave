"""`omniweave_core.store.sqlite` -- the pragmas, the ladder, the thread, the lock, the snapshot.

Specified by 07-store-and-retrieval.md section 2.1 (the four pragma tuples and their order, at
:165-200), section 3.1 (the schema-compatibility ladder, :273-295) and section 10 (the write model,
durability, the read ladder and snapshot isolation, :2714-2800).

Five of these tests exist because a WEAKER version of them would pass on broken code, and each one
says so at its own docstring:

1. **The pragma order is recorded off a real connection**, through a `sqlite3.Connection` subclass
   that logs `execute`. A test comparing `CONN_PRAGMAS` to a transcribed copy of itself asserts
   nothing at all: the claim is about the sequence a connection RECEIVES, and `busy_timeout` being
   first is the whole content of it (07:178-180, codegraph #238).
2. **The read-only ladder is asserted on the filesystem**, not on the URI. 07:2749-2752 says the
   ladder exists so that a read creates no sidecar and moves no mtime, so the test stats the file
   before and after; asserting only that the URI carries `immutable=1` would pass a version that
   perturbed the file anyway. `READONLY_PRAGMAS` gets a second test against a store that is NOT in
   WAL mode, because that is the only condition under which the dropped pragma actually raises.
3. **Snapshot isolation commits a writer BETWEEN two reads inside one snapshot**, which is the test
   07:2762-2763 names in as many words. A test that read twice with no interleaved commit would
   pass against no isolation whatsoever.
4. **Thread ownership is asserted twice**, once on the attribute read and once on a connection
   deliberately smuggled out of the store thread, because the two failures have different
   witnesses: `StoreThread.connection` refuses before a reference escapes, and `sqlite3`'s
   `check_same_thread` refuses after one has.
5. **ST14's `synchronous` is read AT COMMIT TIME**, from inside the transaction through the
   `on_commit` hook, because a pragma read after the commit would report whatever the next unit set.

`import sqlite3` under a `noqa`, and the reason is `test_migration_0001.py:31-41`'s reason. INV-17
restricts the import to `omniweave_core/store/`, `pyproject.toml`'s `per-file-ignores` carries
`store/*.py` and carries no row for tests, and the subject of this module is a live connection: the
recording factory IS a `sqlite3.Connection` subclass, the interrupt is matched on
`sqlite3.Error.sqlite_errorname`, and the cross-thread refusal is a `sqlite3.ProgrammingError`.
None of the three is reachable without the name. The semgrep half of the ban scopes every rule to
`packages/*/src/**` and so already exempts a test; adding the ruff row belongs to
`pyproject.toml`'s owner, and until then this `noqa` is the narrowest form of the exemption.
"""

from __future__ import annotations

import inspect
import sqlite3  # noqa: TID251 -- see the module docstring's last paragraph.
import threading
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.contract import SCHEMA, SCHEMA_MINOR, SCHEMA_STRING
from omniweave_core.errors import ConfigError, StoreError
from omniweave_core.limits import MAX_SNAPSHOT_MS, MIN_SQLITE
from omniweave_core.store import migrate
from omniweave_core.store.sqlite import (
    BATCH_WAIT_MS,
    CONN_PRAGMAS,
    CREATE_PRAGMAS,
    DURABLE_COST_CLASSES,
    EVENT_PRAGMAS,
    INIT_PRAGMAS,
    INTERACTIVE_WAIT_MS,
    READONLY_PRAGMAS,
    SYNCHRONOUS_FULL,
    SYNCHRONOUS_NORMAL,
    LockHolder,
    ReadonlyRung,
    SchemaAction,
    StoreThread,
    Unit,
    connect,
    connect_readonly,
    heal_wal,
    readonly_target,
    refuse_missing_fts5,
    refuse_old_sqlite,
    refuse_open_bulk_window,
    schema_action,
    snapshot,
    wal_bytes,
)

if TYPE_CHECKING:
    from pathlib import Path

NOW_NS = 1_700_000_000_000_000_000
"""One frozen wall clock for every test that needs one. `time.time` is banned in library code and a
test that read the real clock would make `applied_at_ns` and a lock age unassertable."""


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


class Recorder(sqlite3.Connection):
    """A `Connection` that logs every `execute` -- the seam `connect(factory=...)` exists for.

    `sqlite3.Connection` is a C type, so neither the class nor an instance accepts a monkeypatched
    method; the DBAPI's own `factory` argument is the only way to observe what a connection was
    actually told to do. Subclassing is also what makes the observation total: nothing in
    `sqlite.py` reaches the driver except through `execute`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, *parameters: Any) -> sqlite3.Cursor:
        self.calls.append((sql, tuple(parameters)))
        return super().execute(sql, *parameters)

    @property
    def statements(self) -> list[str]:
        """Just the SQL, for the assertions that do not care about bindings.

        The BINDINGS matter for one assertion and only one: `index_state` is a key-value table, so
        every read of it is the same SQL string and only the parameter says which key was asked
        for. A first-statement test written on the SQL alone would pass against a `snapshot()` that
        read `corpus_id` first and never read the generation at all.
        """
        return [sql for sql, _ in self.calls]


class NoFts5(sqlite3.Connection):
    """A `Connection` whose FTS5 module is missing, for the refusal that has no other witness."""

    def execute(self, sql: str, *parameters: Any) -> sqlite3.Cursor:
        if "fts5" in sql:
            raise sqlite3.OperationalError("no such module: fts5")
        return super().execute(sql, *parameters)


def pragmas_of(connection: Recorder) -> list[str]:
    """The recorded statements that are pragmas, with the `PRAGMA ` prefix stripped."""
    return [s.removeprefix("PRAGMA ") for s in connection.statements if s.startswith("PRAGMA ")]


def fresh_store(tmp_path: Path, *, name: str = "index.owstore") -> Path:
    """A migrated store at `tmp_path/name`, closed, with its `-wal` folded back."""
    path = tmp_path / name
    connection = connect(path)
    migrate.apply_pending(connection, now_ns=NOW_NS, corpus_id="corpus-under-test")
    connection.close()
    return path


class FakeLock:
    """A `ScopedLock` that records what it was asked and can be held shut on demand.

    `gate` is what makes "enqueue before attempting the lock" testable: `acquire` blocks on it, so a
    `submit()` that returned while the gate is closed returned before the lock was granted.
    """

    def __init__(self, *, gate: threading.Event | None = None) -> None:
        self.name = "store.write"
        self.waits: list[int] = []
        self.releases = 0
        self.gate = gate

    def acquire(self, *, wait_ms: int) -> None:
        self.waits.append(wait_ms)
        if self.gate is not None:
            self.gate.wait(5)

    def release(self) -> None:
        self.releases += 1

    def holder(self) -> LockHolder | None:
        return None


# --------------------------------------------------------------------------------------------
# 1. The four pragma tuples and the order
# --------------------------------------------------------------------------------------------


def test_the_pragmas_are_issued_in_the_order_the_plan_fixes(tmp_path: Path) -> None:
    """The sequence a NEW file's connection receives, recorded off the connection itself.

    07:165-180 prints four tuples and titles the section "in this order, because the order is
    load-bearing". The expected sequence below is `CONN_PRAGMAS[:1]`, then `CREATE_PRAGMAS`, then
    `CONN_PRAGMAS[1:]`, then `INIT_PRAGMAS` -- the interleaving `CREATE_PRAGMAS`' docstring argues,
    and it is spelled out here from the tuples rather than as a literal list so that a reordering
    of a tuple moves this assertion with it and a reordering of the CODE does not.
    """
    connection = connect(tmp_path / "index.owstore", factory=Recorder)
    assert isinstance(connection, Recorder)
    try:
        expected = [*CONN_PRAGMAS[:1], *CREATE_PRAGMAS, *CONN_PRAGMAS[1:], *INIT_PRAGMAS]
        assert pragmas_of(connection)[: len(expected)] == expected
    finally:
        connection.close()


def test_busy_timeout_is_issued_before_journal_mode_on_a_create_and_on_a_reopen(
    tmp_path: Path,
) -> None:
    """codegraph #238, both times a connection is opened.

    07:178-180: *"`journal_mode = WAL` itself touches the file and can raise `SQLITE_BUSY` before
    the timeout is in effect."* The re-open half matters because the create path and the re-open
    path are different branches of `connect()`, and only the create path issues `CREATE_PRAGMAS` in
    between.
    """
    path = tmp_path / "index.owstore"
    for _ in range(2):
        connection = connect(path, factory=Recorder)
        assert isinstance(connection, Recorder)
        try:
            issued = pragmas_of(connection)
            assert issued.index("busy_timeout = 5000") < issued.index("journal_mode = WAL")
        finally:
            connection.close()


def test_the_create_pragmas_are_issued_only_when_the_file_did_not_exist(tmp_path: Path) -> None:
    """`CREATE_PRAGMAS` is "CREATE time only" (07:176), and the create is OBSERVED, not asked."""
    path = tmp_path / "index.owstore"
    first = connect(path, factory=Recorder)
    assert isinstance(first, Recorder)
    first.close()
    second = connect(path, factory=Recorder)
    assert isinstance(second, Recorder)
    try:
        assert all(p in pragmas_of(first) for p in CREATE_PRAGMAS)
        assert not any(p in pragmas_of(second) for p in CREATE_PRAGMAS)
    finally:
        second.close()


def test_the_create_pragmas_are_what_the_file_reports_afterwards(tmp_path: Path) -> None:
    """`page_size` and `auto_vacuum` PERSIST, which is what makes them create-time-only.

    `auto_vacuum` reads back as `2` because SQLite spells `INCREMENTAL` that way. Both readings are
    taken from a second connection, because a value read off the connection that set it proves
    nothing about the file.
    """
    path = tmp_path / "index.owstore"
    connect(path).close()
    connection = connect(path)
    try:
        assert connection.execute("PRAGMA page_size").fetchone()[0] == 8192
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    finally:
        connection.close()


def test_the_journal_size_limit_is_re_issued_on_every_open(tmp_path: Path) -> None:
    """The reported defect: 07:175 calls `INIT_PRAGMAS` persistent per file, and it is not.

    The measurement is the first assertion -- a fresh connection that has NOT been given
    `INIT_PRAGMAS` reads `-1` -- and the behaviour is the second: `connect()` issues it every time,
    so the value a store actually runs with is 64 MiB whichever open it is on. Without the re-issue
    the `-wal` never shrinks below its high-water mark and codegraph #1431's 25.6 GB comes back.
    """
    path = tmp_path / "index.owstore"
    connect(path).close()
    bare = sqlite3.connect(path, isolation_level=None)
    try:
        assert bare.execute("PRAGMA journal_size_limit").fetchone()[0] == -1
    finally:
        bare.close()
    connection = connect(path, factory=Recorder)
    assert isinstance(connection, Recorder)
    try:
        assert INIT_PRAGMAS[0] in pragmas_of(connection)
        assert connection.execute("PRAGMA journal_size_limit").fetchone()[0] == 67108864
    finally:
        connection.close()


def test_the_readonly_pragmas_are_conn_pragmas_minus_journal_mode(tmp_path: Path) -> None:
    """DERIVED, so the two tuples cannot drift, and the derivation drops exactly one member."""
    assert len(READONLY_PRAGMAS) == len(CONN_PRAGMAS) - 1
    assert set(CONN_PRAGMAS) - set(READONLY_PRAGMAS) == {"journal_mode = WAL"}
    assert list(READONLY_PRAGMAS) == [p for p in CONN_PRAGMAS if p != "journal_mode = WAL"]
    del tmp_path


def test_the_event_pragmas_are_weaker_than_the_index_pragmas() -> None:
    """`events.owstore` only (07:177): a lost telemetry row is free and a blocked query is not."""
    assert EVENT_PRAGMAS == ("busy_timeout = 200", "journal_mode = WAL", "synchronous = OFF")
    assert "synchronous = OFF" not in CONN_PRAGMAS


# --------------------------------------------------------------------------------------------
# 2. The two refusals at open
# --------------------------------------------------------------------------------------------


def test_opening_below_min_sqlite_refuses_and_names_the_pip_extra(tmp_path: Path) -> None:
    """07:196-200. The version is faked, because a floor cannot be tested from above it.

    Asserted on three things, because each is separately load-bearing: the code
    (`OW_SQLITE_TOO_OLD`, which resolves to `OW-C-043` through `codes.toml`), the `fix` string
    (02:724 and 18:171 both name it verbatim), and the message naming the features -- 07:197-199
    makes the floor *"three features deep"* and an operator who is told only a number cannot tell
    which of them they lost.
    """
    path = tmp_path / "index.owstore"
    with pytest.raises(ConfigError) as caught:
        connect(path, version_info=(3, 41, 9))
    assert caught.value.code() == "OW_SQLITE_TOO_OLD"
    assert caught.value.numeric() == "OW-C-043"
    assert caught.value.fix == "pip install omniweave-core[sqlite]"
    assert "unixepoch('subsec')" in str(caught.value)
    assert not path.exists(), "the refusal must precede the open, or it has created the file"


def test_the_min_sqlite_floor_is_inclusive() -> None:
    """`>=`, not `>`: `MIN_SQLITE` is the floor a build is allowed to stand on."""
    refuse_old_sqlite(MIN_SQLITE)
    with pytest.raises(ConfigError):
        refuse_old_sqlite((MIN_SQLITE[0], MIN_SQLITE[1], MIN_SQLITE[2] - 1))


def test_a_readonly_open_below_min_sqlite_refuses_too(tmp_path: Path) -> None:
    """The floor is a property of the interpreter, so it gates the read ladder as well."""
    path = fresh_store(tmp_path)
    with pytest.raises(ConfigError):
        connect_readonly(path, version_info=(3, 41, 9))


def test_an_interpreter_without_fts5_refuses_and_names_the_pip_extra(tmp_path: Path) -> None:
    """11:577-580 makes the FTS5 refusal the same remedy as the version refusal.

    Probed rather than read off `PRAGMA compile_options`, so the test's fake fails the probe rather
    than the option list -- which is the failure a build that claims `ENABLE_FTS5` and cannot create
    the module actually has.
    """
    with pytest.raises(ConfigError) as caught:
        connect(tmp_path / "index.owstore", factory=NoFts5)
    assert caught.value.fix == "pip install omniweave-core[sqlite]"
    assert "block_fts" in str(caught.value)


def test_the_fts5_probe_leaves_nothing_behind(tmp_path: Path) -> None:
    """The probe runs in `temp` and drops itself, so an open is not a schema change."""
    connection = connect(tmp_path / "index.owstore")
    try:
        refuse_missing_fts5(connection)
        rows = connection.execute(
            "SELECT count(*) FROM sqlite_temp_master WHERE name LIKE 'ow_fts5_probe%'"
        ).fetchone()
        assert rows[0] == 0
        assert connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    finally:
        connection.close()


# --------------------------------------------------------------------------------------------
# 3. The `connect_readonly` ladder
# --------------------------------------------------------------------------------------------


def test_the_ladder_picks_mode_ro_when_a_wal_sidecar_exists(tmp_path: Path) -> None:
    """Rung 1 (07:2745). A live `-wal` must be consulted, so `immutable=1` is illegal here."""
    path = tmp_path / "index.owstore"
    writer = connect(path)
    try:
        writer.execute("CREATE TABLE probe(x)")
        assert (tmp_path / "index.owstore-wal").exists()
        uri, rung = readonly_target(path)
        assert rung == ReadonlyRung.RO
        assert uri.endswith("?mode=ro")
        reader = connect_readonly(path)
        try:
            assert reader.execute("SELECT count(*) FROM probe").fetchone()[0] == 0
        finally:
            reader.close()
    finally:
        writer.close()


def test_the_ladder_picks_immutable_when_there_is_no_wal_sidecar(tmp_path: Path) -> None:
    """Rung 2 (07:2746). A cleanly closed store has folded its WAL back and deleted the sidecar."""
    path = fresh_store(tmp_path)
    assert not (tmp_path / "index.owstore-wal").exists()
    uri, rung = readonly_target(path)
    assert rung == ReadonlyRung.RO_IMMUTABLE
    assert uri.endswith("?mode=ro&immutable=1")
    reader = connect_readonly(path)
    try:
        assert reader.execute("SELECT v FROM index_state WHERE k='schema'").fetchone()[0] == "1.0"
    finally:
        reader.close()


def test_a_readonly_open_creates_no_wal_sidecar_and_does_not_move_the_mtime(
    tmp_path: Path,
) -> None:
    """The property 07:2749-2752 exists for, asserted on the filesystem and not on the URI.

    *"A plain read-write open **creates** the WAL sidecars and moves the very mtime the freshness
    check reads. A read that perturbs freshness is a read that makes gate 6
    (`source_edited_unindexed`) fire on its own observation."* Both rungs are exercised: rung 2 on
    the closed store, then rung 1 with a writer holding a WAL open, because the pragma that broke
    this (`journal_mode = WAL`) is issued on either rung or neither.
    """
    path = fresh_store(tmp_path)
    before = path.stat().st_mtime_ns
    reader = connect_readonly(path)
    try:
        reader.execute("SELECT count(*) FROM index_state").fetchone()
    finally:
        reader.close()
    assert not (tmp_path / "index.owstore-wal").exists()
    assert not (tmp_path / "index.owstore-shm").exists()
    assert path.stat().st_mtime_ns == before

    writer = connect(path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT OR REPLACE INTO index_state(k, v) VALUES ('probe', '1')")
        writer.execute("COMMIT")
        after_write = path.stat().st_mtime_ns
        second = connect_readonly(path)
        try:
            second.execute("SELECT count(*) FROM index_state").fetchone()
        finally:
            second.close()
        assert path.stat().st_mtime_ns == after_write
    finally:
        writer.close()


def test_a_readonly_connection_is_issued_every_conn_pragma_except_journal_mode(
    tmp_path: Path,
) -> None:
    """The pragma set is the ladder's other half; `READONLY_PRAGMAS` records the measurement."""
    path = fresh_store(tmp_path)
    reader = connect_readonly(path, factory=Recorder)
    assert isinstance(reader, Recorder)
    try:
        assert pragmas_of(reader) == list(READONLY_PRAGMAS)
        assert "journal_mode = WAL" not in pragmas_of(reader)
    finally:
        reader.close()


def test_immutable_while_a_wal_exists_is_the_silent_stale_read_the_ladder_avoids(
    tmp_path: Path,
) -> None:
    """The wrong rung, taken deliberately, so the hazard 07:2754-2757 names has a witness here.

    *"Using it while a `-wal` exists returns pre-WAL data, which is a silent stale read rather than
    an error."* Measured: against a store whose `CREATE TABLE` is still in the WAL, the wrong rung
    reports `no such table` -- the extreme of the same failure. The test pins the shape of the
    hazard rather than the message, so it documents WHY `readonly_target` branches at all.
    """
    path = tmp_path / "index.owstore"
    writer = connect(path)
    try:
        writer.execute("CREATE TABLE probe(x)")
        wrong = sqlite3.connect(
            f"file:{path.as_posix()}?{ReadonlyRung.RO_IMMUTABLE}", uri=True, isolation_level=None
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                wrong.execute("SELECT count(*) FROM probe").fetchone()
        finally:
            wrong.close()
    finally:
        writer.close()


def test_a_readonly_open_of_a_store_that_is_not_in_wal_mode_succeeds(tmp_path: Path) -> None:
    """Why `journal_mode` is dropped from the read-only set, with the scope of the claim measured.

    `ow store backup` is `VACUUM INTO <path>` (07 section 2.2) and a `VACUUM INTO` output is a fresh
    file in SQLite's default `delete` journal mode, so a reader may meet a store that is not in WAL
    mode. Three things are asserted, and the third is what keeps the second honest:

    1. `connect_readonly` opens it and reads from it.
    2. On a hand-built rung-1 URI (`mode=ro`, which the ladder would NOT choose for this file),
       issuing the full `CONN_PRAGMAS` raises `attempt to write a readonly database` -- the
       measurement `READONLY_PRAGMAS` records.
    3. On the rung the ladder actually chooses for it (`immutable=1`), the same pragma is a harmless
       no-op. So the dropped pragma is a GUARD rather than a fix for a live failure, and this test
       says so rather than implying a bug that the ladder already prevents.
    """
    source_path = fresh_store(tmp_path)
    backup = tmp_path / "backup.owstore"
    writer = connect(source_path)
    try:
        writer.execute("VACUUM INTO ?", (str(backup),))
    finally:
        writer.close()
    plain = sqlite3.connect(backup, isolation_level=None)
    try:
        assert plain.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        plain.close()

    reader = connect_readonly(backup)
    try:
        assert reader.execute("SELECT v FROM index_state WHERE k='schema'").fetchone() is not None
    finally:
        reader.close()

    hazard = sqlite3.connect(
        f"file:{backup.as_posix()}?{ReadonlyRung.RO}", uri=True, isolation_level=None
    )
    try:
        with pytest.raises(sqlite3.OperationalError):
            hazard.execute("PRAGMA journal_mode = WAL")
    finally:
        hazard.close()

    chosen_uri, chosen_rung = readonly_target(backup)
    assert chosen_rung == ReadonlyRung.RO_IMMUTABLE
    benign = sqlite3.connect(chosen_uri, uri=True, isolation_level=None)
    try:
        assert benign.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "delete"
    finally:
        benign.close()


def test_a_readonly_open_of_a_missing_file_refuses_and_never_creates_it(tmp_path: Path) -> None:
    """A created file answers every freshness question with "empty", so absence is a refusal."""
    path = tmp_path / "absent.owstore"
    with pytest.raises(StoreError) as caught:
        connect_readonly(path)
    assert "no store at" in str(caught.value)
    assert not path.exists()


# --------------------------------------------------------------------------------------------
# 4. Heal-on-open and the bulk-window marker
# --------------------------------------------------------------------------------------------


def _grow_wal(path: Path, *, rows: int) -> tuple[sqlite3.Connection, int]:
    """Commit `rows` fat rows with autocheckpointing off; return the OPEN connection and the size.

    **The connection is returned open, and that is the whole fixture.** Closing the last connection
    to a WAL database checkpoints and DELETES the `-wal` sidecar, so a heal test written over a
    closed store would assert `wal_bytes(path) == 0` against a file SQLite had already cleaned up --
    and would pass with `heal_wal` deleted. An oversized WAL only exists while something holds the
    database open, which is also the real-world shape: 07's 25.6 GB was leaked by sessions that were
    SIGKILLed rather than closed.
    """
    connection = connect(path)
    connection.execute("PRAGMA wal_autocheckpoint = 0")
    connection.execute("CREATE TABLE IF NOT EXISTS fat(x TEXT)")
    connection.execute("BEGIN IMMEDIATE")
    connection.executemany("INSERT INTO fat VALUES (?)", [("x" * 400,)] * rows)
    connection.execute("COMMIT")
    return connection, wal_bytes(path)


def test_heal_on_open_truncates_an_oversized_wal(tmp_path: Path) -> None:
    """07:2807 and 15:1806: heal above `[store] wal_heal_mb`, or a killed session leaks 25.6 GB.

    The WAL is grown past a deliberately small threshold rather than past 64 MiB, because the
    threshold is the parameter and the 64 is `config.KEYS`' business; `wal_heal_mb` is passed
    explicitly so the test asserts the mechanism at a size a test may write.
    """
    path = tmp_path / "index.owstore"
    grower, grown = _grow_wal(path, rows=20_000)
    try:
        assert grown > 4 * (1 << 20), "the fixture did not actually grow a WAL"
        healed = connect(path, wal_heal_mb=1)
        try:
            assert wal_bytes(path) == 0
        finally:
            healed.close()
    finally:
        grower.close()


def test_heal_on_open_leaves_a_wal_below_the_threshold_alone(tmp_path: Path) -> None:
    """`>`, not `>=`, and a healthy WAL is not something an open touches."""
    path = tmp_path / "index.owstore"
    grower, grown = _grow_wal(path, rows=20_000)
    try:
        untouched = connect(path, wal_heal_mb=0)
        try:
            assert wal_bytes(path) == grown
            assert heal_wal(untouched, path, wal_heal_mb=1024) == 0
            assert wal_bytes(path) == grown
        finally:
            untouched.close()
    finally:
        grower.close()


def test_an_open_bulk_window_refuses_to_serve_and_names_ow_store_repair(tmp_path: Path) -> None:
    """ST13, 07:2858-2861. A dropped secondary index makes every query silently under-return.

    The marker's numeric is asserted in the message because `codes.toml` carries no symbol for
    `OW-S-031`; the module docstring on `refuse_open_bulk_window` reports the missing allocation.
    """
    path = fresh_store(tmp_path)
    connection = connect(path)
    try:
        refuse_open_bulk_window(connection)
        connection.execute(
            "INSERT OR REPLACE INTO index_state(k, v) VALUES ('bulk_window', '1700000000')"
        )
        with pytest.raises(StoreError) as caught:
            refuse_open_bulk_window(connection)
        assert "OW-S-031" in str(caught.value)
        assert caught.value.fix == "ow store repair"
    finally:
        connection.close()


def test_a_bulk_window_marker_of_zero_or_empty_is_closed(tmp_path: Path) -> None:
    """`0` and `''` are how the marker reads when it is cleared, and neither refuses."""
    path = fresh_store(tmp_path)
    connection = connect(path)
    try:
        for value in ("0", ""):
            connection.execute(
                "INSERT OR REPLACE INTO index_state(k, v) VALUES ('bulk_window', ?)", (value,)
            )
            refuse_open_bulk_window(connection)
    finally:
        connection.close()


def test_a_store_below_0003_has_no_bulk_window_to_refuse(tmp_path: Path) -> None:
    """`index_state` ships in `0003_index.sql`, so its absence must not be a refusal."""
    connection = connect(tmp_path / "index.owstore")
    try:
        refuse_open_bulk_window(connection)
    finally:
        connection.close()


# --------------------------------------------------------------------------------------------
# 5. The section 3.1 schema ladder
# --------------------------------------------------------------------------------------------


def test_a_file_major_above_the_reader_refuses_with_ow_s_030() -> None:
    """Row 1 of 07:285. *"Silent misreading is the failure an operator cannot detect."*"""
    with pytest.raises(StoreError) as caught:
        schema_action(SCHEMA + 1, 0, writable=True)
    assert caught.value.code() == "OW_SCHEMA_AHEAD"
    assert caught.value.numeric() == "OW-S-030"
    assert caught.value.fix == "pip install -U omniweave-core"
    assert f"{SCHEMA + 1}.0" in str(caught.value)
    assert SCHEMA_STRING in str(caught.value)


def test_an_older_major_migrates_on_a_write_open_and_refuses_on_a_read_open() -> None:
    """Row 2, both halves: *"a read must never mutate the file whose mtime the freshness check
    reads."*"""
    assert schema_action(SCHEMA - 1, 0, writable=True) == SchemaAction.MIGRATE
    with pytest.raises(StoreError) as caught:
        schema_action(SCHEMA - 1, 0, writable=False)
    assert caught.value.fix == "ow store migrate"


def test_a_newer_minor_serves_reads_and_refuses_writes() -> None:
    """Row 3. *"A writer that does not know a column cannot maintain its invariant."*"""
    assert schema_action(SCHEMA, SCHEMA_MINOR + 1, writable=True) == SchemaAction.SERVE_READS_ONLY
    assert schema_action(SCHEMA, SCHEMA_MINOR + 1, writable=False) == SchemaAction.SERVE_READS_ONLY


def test_an_older_minor_migrates_forward_and_an_equal_pair_serves() -> None:
    """Rows 4 and the identity case; a minor bump is additive DDL by definition."""
    assert schema_action(SCHEMA, SCHEMA_MINOR + 1, writable=True) != SchemaAction.MIGRATE
    assert schema_action(SCHEMA, SCHEMA_MINOR, writable=True) == SchemaAction.SERVE
    assert schema_action(SCHEMA, SCHEMA_MINOR, writable=False) == SchemaAction.SERVE


def test_the_ladder_can_report_a_refusal_without_raising_it() -> None:
    """`ow doctor` reports every check and exits once, so the refusals are also a return value."""
    assert schema_action(SCHEMA + 1, 0, writable=True, raise_on_refuse=False) == SchemaAction.REFUSE
    assert (
        schema_action(SCHEMA - 1, 0, writable=False, raise_on_refuse=False) == SchemaAction.REFUSE
    )


def test_there_is_no_force_in_the_ladder() -> None:
    """07:281-282: *"There is one table and no `--force`."* Asserted on the signature itself."""
    names = set(inspect.signature(schema_action).parameters)
    assert "force" not in names
    assert names == {"file_major", "file_minor", "writable", "raise_on_refuse"}


# --------------------------------------------------------------------------------------------
# 7. The store thread, the queue and the transaction primitive
# --------------------------------------------------------------------------------------------


def test_the_store_thread_is_the_only_thread_that_may_read_the_connection(tmp_path: Path) -> None:
    """INV-17 as an attribute refusal, before a reference can escape.

    07:2722-2723 makes the store thread *"the only holder of a `Connection` in a process"*. The
    refusal names the rule and the two threads, because a driver message about thread ids does not
    tell a caller what to do instead.
    """
    path = tmp_path / "index.owstore"
    with StoreThread(lambda: connect(path)) as store:
        with pytest.raises(StoreError) as caught:
            _ = store.connection
        assert "INV-17" in str(caught.value)
        assert caught.value.fix == "StoreThread.run(Unit(...))"
        assert not store.owns_current_thread
        assert store.run(Unit("owns", lambda _c: store.owns_current_thread)) is True


def test_a_connection_smuggled_off_the_store_thread_refuses_to_execute(tmp_path: Path) -> None:
    """The second witness: `sqlite3`'s own `check_same_thread`, after a reference HAS escaped.

    A closure can return the connection object, so the attribute refusal is not the whole guard.
    `check_same_thread=True` is left at its default precisely so this attempt raises rather than
    corrupting, and the test proves the default is in force rather than assuming it.
    """
    path = tmp_path / "index.owstore"
    with StoreThread(lambda: connect(path)) as store:
        smuggled = store.run(Unit("smuggle", lambda c: c))
        assert isinstance(smuggled, sqlite3.Connection)
        with pytest.raises(sqlite3.ProgrammingError):
            smuggled.execute("SELECT 1")


def test_a_unit_commits_and_its_return_value_reaches_the_submitter(tmp_path: Path) -> None:
    """One transaction per unit (07:2717), and the closure's value is the call's value."""
    path = tmp_path / "index.owstore"
    with StoreThread(lambda: connect(path)) as store:
        store.run(Unit("ddl", lambda c: c.execute("CREATE TABLE t(x INTEGER)")))
        rows = store.run(Unit("insert", lambda c: c.execute("INSERT INTO t VALUES (7)").rowcount))
        assert rows == 1
    reader = connect(path)
    try:
        assert reader.execute("SELECT x FROM t").fetchall() == [(7,)]
    finally:
        reader.close()


def test_a_closure_that_raises_rolls_back_and_the_exception_reaches_the_submitter(
    tmp_path: Path,
) -> None:
    """The two halves of one guarantee: no partial rows, and no swallowed exception.

    A `False` return would be wrong here for the reason 08:2489-2494 gives about the one boolean the
    store boundary does return -- *"a boolean that means both 'someone else won' and 'your driver is
    wrong' turns a bug into a no-op"*.
    """
    path = tmp_path / "index.owstore"
    sentinel = RuntimeError("the closure decided against it")

    def half_then_raise(connection: sqlite3.Connection) -> None:
        connection.execute("INSERT INTO t VALUES (1)")
        connection.execute("INSERT INTO t VALUES (2)")
        raise sentinel

    with StoreThread(lambda: connect(path)) as store:
        store.run(Unit("ddl", lambda c: c.execute("CREATE TABLE t(x INTEGER)")))
        with pytest.raises(RuntimeError) as caught:
            store.run(Unit("partial", half_then_raise))
        assert caught.value is sentinel
        assert store.run(
            Unit("count", lambda c: c.execute("SELECT count(*) FROM t").fetchone())
        ) == (0,)
        assert store.run(Unit("still-usable", lambda c: c.execute("SELECT 1").fetchone())) == (1,)


def test_a_unit_is_enqueued_before_the_lock_is_attempted(tmp_path: Path) -> None:
    """07:2730: *"Enqueue before attempting the lock."*

    The lock stub blocks inside `acquire`, so a `submit()` that returned while the gate is closed
    returned before the lock was granted -- which is the whole property: *"an interactive `ow add`
    writes its `work` row in a short transaction and returns; it does not sit for 60 s behind a
    batch writer."* The negative assertion (`done.wait(0.05)` is False) is what makes it a test of
    the ORDER rather than of the outcome.
    """
    path = tmp_path / "index.owstore"
    gate = threading.Event()
    lock = FakeLock(gate=gate)
    with StoreThread(lambda: connect(path), lock=lock) as store:
        ticket = store.submit(Unit("waits-for-the-lock", lambda c: c.execute("SELECT 1")))
        assert not ticket.done.wait(0.05)
        gate.set()
        ticket.result(5)
    assert lock.waits == [INTERACTIVE_WAIT_MS]
    assert lock.releases == 1


def test_the_wait_budget_is_passed_per_unit_and_never_configured(tmp_path: Path) -> None:
    """07:2726-2729. A watcher batch pays `BATCH_WAIT_MS`; an interactive write pays 2 s."""
    path = tmp_path / "index.owstore"
    lock = FakeLock()
    with StoreThread(lambda: connect(path), lock=lock) as store:
        store.run(Unit("interactive", lambda c: c.execute("SELECT 1")))
        store.run(Unit("batch", lambda c: c.execute("SELECT 1"), wait_ms=BATCH_WAIT_MS))
    assert lock.waits == [INTERACTIVE_WAIT_MS, BATCH_WAIT_MS]
    assert lock.releases == 2


def test_the_lock_is_released_even_when_the_unit_raises(tmp_path: Path) -> None:
    """A failed transaction that kept the cross-process lock would hang the next writer."""
    path = tmp_path / "index.owstore"
    lock = FakeLock()

    def boom(_connection: sqlite3.Connection) -> None:
        raise RuntimeError("no")

    with StoreThread(lambda: connect(path), lock=lock) as store, pytest.raises(RuntimeError):
        store.run(Unit("boom", boom))
    assert lock.releases == 1


def test_a_full_queue_refuses_rather_than_dropping_a_transaction(tmp_path: Path) -> None:
    """`STORE_QUEUE_BOUND`'s rule: back-pressure, then a refusal. Never a drop.

    A dropped transaction is lost work with no witness. The two drops the plan does allow are a
    telemetry batch and a watcher event, and both are free; a transaction closure is neither.
    """
    path = tmp_path / "index.owstore"
    release = threading.Event()
    with StoreThread(lambda: connect(path), bound=1) as store:
        store.submit(Unit("occupies-the-thread", lambda _c: release.wait(5)))
        store.submit(Unit("fills-the-queue", lambda c: c.execute("SELECT 1")))
        with pytest.raises(StoreError) as caught:
            store.submit(Unit("third", lambda c: c.execute("SELECT 1")), enqueue_timeout_s=0.05)
        assert "full" in str(caught.value)
        release.set()


def test_a_queue_that_can_hold_nothing_is_refused_at_construction(tmp_path: Path) -> None:
    """A bound of 0 is a deadlock dressed as a configuration value."""
    with pytest.raises(StoreError):
        StoreThread(lambda: connect(tmp_path / "index.owstore"), bound=0)


def test_an_opener_that_refuses_delivers_its_error_to_start(tmp_path: Path) -> None:
    """A `MIN_SQLITE` or FTS5 refusal must reach the caller, not die on a background thread."""
    path = tmp_path / "index.owstore"
    with pytest.raises(ConfigError):
        StoreThread(lambda: connect(path, version_info=(3, 41, 9))).start()


def test_submitting_after_close_is_refused(tmp_path: Path) -> None:
    """A submitter told "accepted" must get its transaction, so acceptance stops at close."""
    store = StoreThread(lambda: connect(tmp_path / "index.owstore")).start()
    store.close()
    with pytest.raises(StoreError):
        store.submit(Unit("late", lambda c: c.execute("SELECT 1")))


# --------------------------------------------------------------------------------------------
# 8. ST14 -- a BILLED_API commit is durable
# --------------------------------------------------------------------------------------------


def test_synchronous_is_full_at_commit_for_a_billed_unit_and_normal_for_a_free_one(
    tmp_path: Path,
) -> None:
    """ST14, 07:2735-2740, asserted AT COMMIT TIME through the `on_commit` hook.

    The pragma is read from inside the transaction, immediately before `COMMIT`, because a read
    taken afterwards would report whatever the NEXT unit set -- which is how a test of this property
    passes against code that sets the pragma in the wrong place. The billed operator is synthetic:
    no `BILLED_API` driver exists until P4, and 07:2740 asks for the hook and its test now.
    """
    path = tmp_path / "index.owstore"
    seen: list[int] = []

    def record(connection: sqlite3.Connection) -> None:
        seen.append(int(connection.execute("PRAGMA synchronous").fetchone()[0]))

    with StoreThread(lambda: connect(path)) as store:
        store.run(Unit("free", lambda c: c.execute("SELECT 1"), on_commit=record))
        store.run(
            Unit(
                "billed",
                lambda c: c.execute("SELECT 1"),
                cost_class="billed_api",
                on_commit=record,
            )
        )
        store.run(Unit("free-again", lambda c: c.execute("SELECT 1"), on_commit=record))
    assert seen == [SYNCHRONOUS_NORMAL, SYNCHRONOUS_FULL, SYNCHRONOUS_NORMAL]


def test_only_billed_api_is_durable_and_the_domain_is_the_shipped_check() -> None:
    """The three `cost_class` values are `0004_runtime.sql`'s `CHECK`, and one is durable."""
    assert set(DURABLE_COST_CLASSES) == {"billed_api"}
    assert Unit("u", lambda _c: None, cost_class="billed_api").durable
    assert not Unit("u", lambda _c: None, cost_class="free").durable
    assert not Unit("u", lambda _c: None, cost_class="local_compute").durable


def test_an_on_commit_hook_that_raises_aborts_the_unit(tmp_path: Path) -> None:
    """The hook runs inside the transaction, so a raise rolls the unit back. Deliberate coupling.

    07:2731-2733 requires one unit's derived rows, its `work` transition, its `dep` rows, its
    reservation commit and its spend row to commit *"together or not at all"*, and the reservation
    and spend writes are what this hook is for.
    """
    path = tmp_path / "index.owstore"

    def veto(_connection: sqlite3.Connection) -> None:
        raise RuntimeError("the reservation could not be committed")

    with StoreThread(lambda: connect(path)) as store:
        store.run(Unit("ddl", lambda c: c.execute("CREATE TABLE t(x)")))
        with pytest.raises(RuntimeError):
            store.run(
                Unit("vetoed", lambda c: c.execute("INSERT INTO t VALUES (1)"), on_commit=veto)
            )
        assert store.run(
            Unit("count", lambda c: c.execute("SELECT count(*) FROM t").fetchone())
        ) == (0,)


# --------------------------------------------------------------------------------------------
# 9. `snapshot()`
# --------------------------------------------------------------------------------------------


def test_the_snapshot_reads_the_generation_as_its_very_first_statement(tmp_path: Path) -> None:
    """07:2777-2782. The read is not a convenience: it is what makes the transaction real.

    *"A `BEGIN DEFERRED` does not actually acquire the read snapshot until the first statement ...
    Without that first read, two Channels could still straddle a commit."* So the assertion is on
    the ADJACENCY of the two statements, not on their presence.
    """
    path = fresh_store(tmp_path)
    reader = connect_readonly(path, factory=Recorder)
    assert isinstance(reader, Recorder)
    try:
        start = len(reader.calls)
        with snapshot(reader) as state:
            assert state.generation == 0
        issued = reader.calls[start:]
        assert issued[0] == ("BEGIN DEFERRED", ())
        assert issued[1] == ("SELECT v FROM index_state WHERE k = ?", (("generation",),))
        assert issued[-1] == ("ROLLBACK", ())
    finally:
        reader.close()


def test_the_snapshot_carries_the_generation_corpus_id_schema_and_vec_state(
    tmp_path: Path,
) -> None:
    """`Snapshot`'s six fields, and `token` holding the `Connection` nothing else unwraps.

    The generation is bumped off its seeded `0` before the snapshot is taken, because `0` is what a
    `Snapshot` built from no read at all would also report -- and gate 3 compares this number across
    the snapshot boundary, so a constant would be worse than an absent field.
    """
    path = fresh_store(tmp_path)
    bump = connect(path)
    try:
        bump.execute("UPDATE index_state SET v = '42' WHERE k = 'generation'")
    finally:
        bump.close()
    reader = connect_readonly(path)
    try:
        with snapshot(reader) as state:
            assert state.token is reader
            assert state.generation == 42
            assert state.corpus_id == "corpus-under-test"
            assert state.schema == SCHEMA
            assert state.vec_attached is False
            assert state.opened_ns > 0
    finally:
        reader.close()


def test_a_commit_between_two_reads_inside_one_snapshot_is_invisible(tmp_path: Path) -> None:
    """ST2's own test, stated at 07:2762-2763, and the reason `snapshot()` exists at all.

    *"A full re-index is committed between Channel 1 and Channel 5 and the results must be
    identical."* The interleaved commit is real -- a second connection, a real `BEGIN IMMEDIATE`,
    a real `COMMIT` -- and it is verified to have landed by reading it OUTSIDE the snapshot
    afterwards, because a commit that silently failed would make this test pass against no
    isolation at all.
    """
    path = tmp_path / "index.owstore"
    writer = connect(path)
    migrate.apply_pending(writer, now_ns=NOW_NS, corpus_id="isolation")
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO stat(k, v, computed_ns) VALUES ('live_blocks', 1, 1)")
    writer.execute("COMMIT")

    reader = connect_readonly(path)
    try:
        with snapshot(reader) as state:
            first = reader.execute("SELECT count(*) FROM stat").fetchone()[0]
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO stat(k, v, computed_ns) VALUES ('live_segments', 2, 2)")
            writer.execute("UPDATE index_state SET v = '1' WHERE k = 'generation'")
            writer.execute("COMMIT")
            second = reader.execute("SELECT count(*) FROM stat").fetchone()[0]
            assert first == second == 1
            assert state.generation == 0
        assert reader.execute("SELECT count(*) FROM stat").fetchone()[0] == 2
        assert reader.execute("SELECT v FROM index_state WHERE k='generation'").fetchone()[0] == "1"
    finally:
        reader.close()
        writer.close()


def test_max_snapshot_ms_aborts_with_ow_s_010(tmp_path: Path) -> None:
    """07:2789-2793 and 07:1820. The deadline is a WAL-valve parameter, not a UX parameter.

    The clock is injected so the budget is spent without spending the wall time: the second reading
    is 10 s past the first, which is past the ceiling as well as past the request. This is the half
    of the enforcement the `interrupt()` cannot see -- a body that spends its budget in Python
    between two cheap statements.
    """
    path = fresh_store(tmp_path)
    reader = connect_readonly(path)
    readings = iter([0, 10_000_000_000])
    try:
        with (
            pytest.raises(StoreError) as caught,
            snapshot(reader, snapshot_ms=50, monotonic_ns=lambda: next(readings)),
        ):
            pass
        assert caught.value.code() == "OW_SNAPSHOT_EXPIRED"
        assert caught.value.numeric() == "OW-S-010"
        assert "pins the WAL" in str(caught.value)
        assert not reader.in_transaction, "an expired snapshot must still have rolled back"
    finally:
        reader.close()


def test_max_snapshot_ms_interrupts_a_long_statement_inside_the_snapshot(tmp_path: Path) -> None:
    """The other half: `Connection.interrupt()` from a timer, against a statement that is running.

    A recursive CTE is the cheapest interruptible long statement there is, and it needs no fixture
    rows -- so the test exercises the interrupt path rather than a table-size accident. Measured on
    3.43.1 the interrupt surfaces as `sqlite3.OperationalError` with
    `sqlite_errorname == "SQLITE_INTERRUPT"`, which is what `snapshot()` translates.
    """
    path = fresh_store(tmp_path)
    reader = connect_readonly(path)
    grind = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 200000000) "
        "SELECT count(*) FROM c"
    )
    try:
        with pytest.raises(StoreError) as caught, snapshot(reader, snapshot_ms=20):
            reader.execute(grind).fetchone()
        assert caught.value.code() == "OW_SNAPSHOT_EXPIRED"
        assert not reader.in_transaction
    finally:
        reader.close()


def test_snapshot_ms_is_clamped_below_max_snapshot_ms(tmp_path: Path) -> None:
    """*"`[retrieval] snapshot_ms` clamps BELOW it"* (07:2790), so a request above it is clamped.

    The clamp is observable in the message, which names the budget the snapshot actually ran with.
    """
    path = fresh_store(tmp_path)
    reader = connect_readonly(path)
    readings = iter([0, 10 * MAX_SNAPSHOT_MS * 1_000_000])
    try:
        with (
            pytest.raises(StoreError) as caught,
            snapshot(reader, snapshot_ms=MAX_SNAPSHOT_MS * 10, monotonic_ns=lambda: next(readings)),
        ):
            pass
        assert f"{MAX_SNAPSHOT_MS} ms" in str(caught.value)
    finally:
        reader.close()


def test_a_snapshot_ms_that_is_not_a_positive_integer_is_refused(tmp_path: Path) -> None:
    """A deadline of 0 or -1 is a snapshot that has already expired, which is a usage error."""
    path = fresh_store(tmp_path)
    reader = connect_readonly(path)
    try:
        with pytest.raises(StoreError), snapshot(reader, snapshot_ms=0):
            pass
    finally:
        reader.close()


def test_a_store_with_no_generation_row_cannot_be_snapshotted(tmp_path: Path) -> None:
    """A missing `generation` is a store mid-migration, and `0` would be a fabricated answer."""
    connection = connect(tmp_path / "index.owstore")
    try:
        with pytest.raises(StoreError) as caught, snapshot(connection):
            pass
        assert caught.value.fix == "ow store migrate"
    finally:
        connection.close()


def test_the_snapshot_ends_in_rollback_and_leaves_no_transaction_open(tmp_path: Path) -> None:
    """A read transaction has nothing to commit, and a held one pins the WAL."""
    path = fresh_store(tmp_path)
    reader = connect_readonly(path)
    try:
        with snapshot(reader):
            assert reader.in_transaction
        assert not reader.in_transaction
        with pytest.raises(ZeroDivisionError), snapshot(reader):
            _ = 1 / 0
        assert not reader.in_transaction
    finally:
        reader.close()
