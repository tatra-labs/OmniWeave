"""`store/reader.py` against a REAL `.owstore`, because every claim it makes is about SQLite.

Six methods, and the tests are grouped by which of them they hold. Four of the groups exist
because the property they check is invisible to a mock:

* **the narrowing probe runs on a `mode=ro` connection.** That is what `temp_store = MEMORY` buys
  (07-store-and-retrieval.md:186-190) and it is the second job of a pragma that otherwise reads as
  a speed knob, so the test opens the store through `connect_readonly`, writes into a TEMP table
  inside a read transaction, and asserts that no temp FILE appeared in a temp directory this test
  controls.
* **hydration inside one snapshot is generation-consistent.** ST2's own test shape (07:2761-2763)
  is asserted in BOTH directions, following `test_store_integration.py`: the re-index committed
  mid-hydrate is invisible to the open snapshot AND visible to the next one. Either half alone
  passes against a reader pointed at the wrong file.
* **a `Snapshot` from another store is refused.** `Snapshot.token` is typed `object` (07:72-78) so
  nothing in the type system stops it, and the failure it prevents is a consistent-looking read of
  the wrong file rather than an exception.
* **the refusals are legible.** P6 inherits whatever `channel()` says when it will not run, so the
  reason strings are asserted rather than the statuses alone.

`import sqlite3` here is TID251's test exception and it is taken deliberately: these tests seed
`doc`, `page`, `block`, `ref_site` and `anchor` rows through the same connection the `Reader`
reads, and a fixture that could not write SQL could only test the `Reader` against itself. The
seeding is direct DDL-shaped SQL rather than `DocSink`, because `DocSink` has no implementation
yet and 16-roadmap.md schedules it separately -- so the rows are built from the shipped DDL, which
is *"the authority on columns, types, CHECKs, UNIQUEs and foreign keys"*.

`PREFILTER_MAX` is 200,000 (limits.py:626) and `Narrowing.kind == "all"` is what happens above it.
Inserting 200,001 blocks to reach one branch would make this suite minutes long, so the two tests
that need the cap monkeypatch `reader.PREFILTER_MAX` instead. That is honest rather than a dodge:
the module reads the name at call time through `cap = PREFILTER_MAX + 1`, so the arithmetic, the
`LIMIT` and the `>=` comparison under test are the shipped ones, and only the number moves.

Specified in 07-store-and-retrieval.md sections 1.1, 3.8, 6.1, 7.2, 10.4 and 16, and
16-roadmap.md:1034 (W2.3).
"""

from __future__ import annotations

import inspect
import pathlib
import sqlite3  # noqa: TID251 -- see the module docstring: the fixtures seed a REAL store.
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
from omniweave_core.errors import StoreError, UsageError
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.store import Reader, migrate
from omniweave_core.store import reader as rd
from omniweave_core.store import sqlite as ow
from omniweave_core.store import vectors as vec
from omniweave_core.store.types import ChannelInput, ChannelSpec, Expand, Filters

NOW_NS = 1_757_400_000_000_000_000
"""A fixed clock. `time.time()` is banned in library code and `SqliteReader` takes `now_ns` from
its caller, so a test reading the ambient clock would assert against a value the production path
cannot produce."""

DIGEST = b"\x00" * 16


# ---------------------------------------------------------------------------------------------
# Fixtures: one store, one live writer, and seed helpers built from the shipped DDL
# ---------------------------------------------------------------------------------------------


class Built(NamedTuple):
    """A migrated store, its path, and a writer connection that STAYS OPEN.

    The writer is held open on purpose: `readonly_target()` picks `mode=ro` only while a `-wal`
    sidecar exists and `mode=ro&immutable=1` otherwise (07:2744-2757), and the narrowing test is
    about the `mode=ro` rung specifically. A live writer is what keeps the sidecar on disk.
    """

    path: Path
    writer: sqlite3.Connection


@pytest.fixture
def built(tmp_path: Path) -> Iterator[Built]:
    path = tmp_path / "index.owstore"
    writer = ow.connect(path)
    applied = migrate.apply_pending(writer, now_ns=NOW_NS)
    assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
    try:
        yield Built(path=path, writer=writer)
    finally:
        writer.close()


def _reader(built: Built, *, now_ns: int = NOW_NS) -> rd.SqliteReader:
    """A `Reader` on a fresh read-only connection to the built store."""
    return rd.SqliteReader(ow.connect_readonly(built.path), now_ns=now_ns)


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    assert row is not None, f"enum_val has no {domain}.{name}"
    return int(row[0])


def _producer(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    row = conn.execute("SELECT producer_id FROM producer").fetchone()
    return int(row[0])


def _doc(
    conn: sqlite3.Connection,
    doc_ord: int,
    *,
    uri: str,
    status: str = "ok",
    fmt: str = "pdf",
    gen: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "                format_evidence, source_bytes, gen, status, model_version, "
        "                declared, achieved) "
        "VALUES(?, ?, ?, ?, 'application/pdf', ?, '{}', 1, ?, ?, '1.1', '{}', '{}')",
        (doc_ord, bytes([doc_ord]) * 16, DIGEST, uri, fmt, gen, status),
    )


def _page(conn: sqlite3.Connection, doc_ord: int, gen: int, page: int, producer_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (
            doc_ord,
            gen,
            page,
            _code(conn, "page_kind", "page"),
            _code(conn, "method", "native"),
            producer_id,
        ),
    )


def _block(
    conn: sqlite3.Connection,
    *,
    block_id: int,
    doc_ord: int,
    producer_id: int,
    gen: int = 1,
    page: int = 0,
    ord_: int = 0,
    kind: str = "paragraph",
    layer: str = "body",
    method: str = "native",
    label: str | None = None,
    addr: str | None = None,
    text: str | None = "hello",
    trust: int = 2,
    quote: int = 4,
    restriction_bits: int = 0,
    state: int = 0,
) -> None:
    """One `block` row. `os_kind = none` so neither of the DDL's two os CHECKs applies.

    `label` defaults to `None` because most rows have none -- 0003_index.sql:97 calls `head_fts`
    *"tiny"* for exactly that reason -- and the identity ladder's three title tiers are the only
    thing that reads it. `addr` defaults to the `p{page}/{ord}` form; the document root block
    spells it `'doc'` (0001_init.sql:240) and has to say so.
    """
    _page(conn, doc_ord, gen, page, producer_id)
    conn.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, label, "
        "                  text, content_digest, os_kind, producer_id, method, trust, quote, "
        "                  origin_operator, origin_driver, driver_schema_v, restriction_bits, "
        "                  state) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'op.parse', 'drv', 1, ?, ?)",
        (
            block_id,
            doc_ord,
            gen,
            page,
            f"p{page}/{ord_}" if addr is None else addr,
            f"d{doc_ord}#{block_id}",
            ord_,
            _code(conn, "kind", kind),
            _code(conn, "layer", layer),
            label,
            text,
            DIGEST,
            _code(conn, "origin_span_kind", "none"),
            producer_id,
            _code(conn, "method", method),
            trust,
            quote,
            restriction_bits,
            state,
        ),
    )


def _seed_one_block(built: Built, *, text: str = "hello") -> None:
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf")
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id, text=text)
    conn.execute("COMMIT")


# ---------------------------------------------------------------------------------------------
# The Protocol
# ---------------------------------------------------------------------------------------------


def test_the_reader_protocol_still_has_exactly_six_methods_and_this_class_has_all_six() -> None:
    """07:63-68 prints six and 02-architecture.md:702 prices the surface at 4 + 6 + 11 + 12 = 33.

    A seventh here would mean the frozen boundary moved without an ADR (16-roadmap.md:428), and a
    sixth that `SqliteReader` lacked would mean the backend does not implement the boundary it
    claims to. Both directions are asserted, and so are the PARAMETER NAMES, because P6 may call
    `narrow(s=..., f=...)` by keyword and a rename would break it silently.
    """
    declared = sorted(name for name in vars(Reader) if not name.startswith("_"))
    assert declared == ["capabilities", "channel", "coverage", "hydrate", "narrow", "snapshot"]
    for name in declared:
        protocol_parameters = list(inspect.signature(getattr(Reader, name)).parameters)
        implementation = list(inspect.signature(getattr(rd.SqliteReader, name)).parameters)
        assert implementation == protocol_parameters, name


def test_the_reader_never_opens_a_connection_of_its_own() -> None:
    """ST1 (07:2721): *"`sqlite3.connect` appears in exactly one module"*, and it is `sqlite.py`."""
    source = Path(rd.__file__ if hasattr(rd, "__file__") else "").read_text(encoding="utf-8")
    assert "sqlite3.connect(" not in source


# ---------------------------------------------------------------------------------------------
# 1. snapshot
# ---------------------------------------------------------------------------------------------


def test_the_snapshot_is_the_one_sqlite_module_already_ships(built: Built) -> None:
    """07:2777-2782's mechanism is `sqlite.snapshot()`'s; this method delegates and books it.

    The observable of the delegation is that `Snapshot.token` is the Reader's own connection and
    that `generation` came from inside the transaction -- `index_state.generation` is seeded to 0
    by `migrate._seed_index_state`, so a Reader that never issued the first read would report the
    same 0 and the token check is what distinguishes them.
    """
    reader = _reader(built)
    with reader.snapshot() as state:
        assert state.token is reader._connection
        assert state.generation == 0
        assert state.schema == 1


def test_two_snapshots_from_one_reader_are_both_refused_after_they_close(built: Built) -> None:
    """A `Snapshot` outlives its transaction as a Python object; reading through it must not."""
    reader = _reader(built)
    with reader.snapshot() as first:
        pass
    with reader.snapshot() as second:
        assert reader.narrow(second, Filters()).kind == "empty"
    for stale in (first, second):
        with pytest.raises(StoreError, match="this Snapshot has closed"):
            reader.narrow(stale, Filters())


# ---------------------------------------------------------------------------------------------
# 2. capabilities -- read once, at open (07:3272)
# ---------------------------------------------------------------------------------------------


def test_capabilities_is_read_once_at_open_and_returns_the_same_object_every_time(
    built: Built,
) -> None:
    """07:3272. Two calls issue no statement and hand back one object.

    `caps_digest` *"memoises `plan()`"* (07:3280), so a digest that could change between two calls
    inside one process would make the memo key describe a store state the plan was not built
    against. The trace callback is the witness: it records every statement the connection runs,
    and after `__init__` there must be none.
    """
    reader = _reader(built)
    statements: list[str] = []
    reader._connection.set_trace_callback(statements.append)
    first = reader.capabilities()
    second = reader.capabilities()
    reader._connection.set_trace_callback(None)
    assert first is second
    assert statements == []


def test_a_change_after_open_does_not_reach_a_reader_that_already_read_its_capabilities(
    built: Built,
) -> None:
    """Read-once means a fresher answer needs a fresh `Reader`, and that is the point."""
    reader = _reader(built)
    assert reader.capabilities().fts_state == "ok"
    built.writer.execute("UPDATE index_state SET v = 'stale' WHERE k = 'fts_state'")
    built.writer.commit()
    assert reader.capabilities().fts_state == "ok"
    assert _reader(built).capabilities().fts_state == "stale"


@pytest.mark.parametrize(
    ("mutate", "field", "expected"),
    [
        pytest.param(
            "UPDATE index_state SET v = 'stale' WHERE k = 'fts_state'",
            "fts_state",
            "stale",
            id="fts_state",
        ),
        pytest.param(
            "UPDATE index_state SET v = '7' WHERE k = 'shard_ord'",
            "shard_ord",
            7,
            id="shard_ord",
        ),
        pytest.param(
            "INSERT INTO index_state(k, v) VALUES('scorer_version', '3')",
            "scorer_version",
            3,
            id="scorer_version",
        ),
        pytest.param(
            "INSERT INTO stat(k, v, computed_ns) VALUES('docs', 12, 1)",
            "docs",
            12,
            id="docs",
        ),
    ],
)
def test_the_caps_digest_moves_when_any_field_moves(
    built: Built, mutate: str, field: str, expected: object
) -> None:
    """07:3280: `caps_digest` is *"sha256_canonical of every field above"*, so ALL of them.

    Four different fields, drawn from three different sources (`index_state`, `stat` and, in
    `test_the_caps_digest_moves_when_the_channels_do`, `sqlite_master`), because a digest computed
    over a subset would still be stable across two calls and would still LOOK right -- it would
    only memoise `plan()` against a store state that had moved.
    """
    before = _reader(built).capabilities()
    built.writer.execute(mutate)
    built.writer.commit()
    after = _reader(built).capabilities()
    assert getattr(after, field) == expected
    assert getattr(before, field) != expected
    assert after.caps_digest != before.caps_digest


def test_the_caps_digest_moves_when_the_channels_do(built: Built) -> None:
    """`channels` is a store fact read off `sqlite_master`, and it is inside the digest."""
    before = _reader(built).capabilities()
    assert "lexical" in before.channels
    built.writer.execute("DROP TABLE block_fts")
    built.writer.commit()
    after = _reader(built).capabilities()
    assert "lexical" not in after.channels
    assert after.caps_digest != before.caps_digest


def test_the_caps_digest_moves_with_the_clock_because_stat_age_is_inside_it(built: Built) -> None:
    """`stat_age_ns` is a field of `IndexCaps`, so two opens a day apart are two capabilities."""
    early = rd.SqliteReader(ow.connect_readonly(built.path), now_ns=NOW_NS).capabilities()
    late = rd.SqliteReader(
        ow.connect_readonly(built.path), now_ns=NOW_NS + 86_400_000_000_000
    ).capabilities()
    assert late.stat_age_ns > early.stat_age_ns
    assert late.caps_digest != early.caps_digest


def test_a_missing_stat_key_reports_an_age_a_staleness_rule_must_call_stale(built: Built) -> None:
    """07:729-731: *"age > STAT_MAX_AGE_NS **or a key is missing**"* takes the maximum clamp.

    `stat_age_ns` is the only carrier `IndexCaps` gives that rule, so a never-computed key has to
    come back as an age above the 24 h threshold rather than as a comfortable zero -- which is the
    reading under which *"a wrong over-fetch factor is a silent recall loss"* (07:733) cannot
    happen by omission.
    """
    stat_max_age_ns = 86_400 * 1_000_000_000
    caps = _reader(built).capabilities()
    assert caps.docs == 0
    assert caps.stat_age_ns > stat_max_age_ns


def test_the_five_channel_names_are_reported_as_store_facts_not_as_build_facts(
    built: Built,
) -> None:
    """07:3275: *"which of the five CAN run at all in this store"*.

    `structural` is present although `channel()` refuses it, and that is the ruling: a Channel
    absent from `channels` reads as `OffReason.NOT_IN_PLAN` (an operator choice) while one present
    and refused reads as `NOT_BUILT` (a shipped limitation), and 16-roadmap.md:114 requires the
    second. `semantic` is absent because the `vec` sidecar is not attached, which is the one
    genuine store fact among the five here.
    """
    caps = _reader(built).capabilities()
    assert caps.channels == frozenset({"identity", "exact", "lexical", "structural"})
    assert "semantic" not in caps.channels
    assert caps.vec_ceiling == 0
    assert caps.vec_backend is None
    assert caps.federated is False


# ---------------------------------------------------------------------------------------------
# 3. narrow -- the three-way tag, and the mode=ro TEMP table
# ---------------------------------------------------------------------------------------------


def test_the_narrowing_probe_runs_on_a_read_only_connection_and_leaves_no_temp_file(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is what `temp_store = MEMORY` buys, and it is the pragma's SECOND job (07:186-190).

    *"An `INSERT` into a TEMP table is a write to the temp schema, and with an in-memory temp store
    there is no temp file to create, journal or leave behind on a read-only filesystem."* Three
    assertions, and each can fail on its own: the rung really is `mode=ro`, the pragma really is
    `MEMORY` (2), and the directory SQLite would spill a temp file into is still empty afterwards.

    The third is the weakest of the three and is stated honestly: a small temp table may live in
    the page cache even with a file-backed temp store, so an empty directory does not by itself
    prove the pragma. It is here because it is the only DIRECT observation of "no file", and the
    pragma assertion is what carries the mechanism.
    """
    sqlite_tmp = tmp_path / "sqlite-temp"
    sqlite_tmp.mkdir()
    for name in ("SQLITE_TMPDIR", "TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(sqlite_tmp))
    _seed_one_block(built)

    uri, rung = ow.readonly_target(built.path)
    assert rung == ow.ReadonlyRung.RO, f"expected the mode=ro rung, got {rung} for {uri}"

    reader = _reader(built)
    assert reader._connection.execute("PRAGMA temp_store").fetchone()[0] == 2
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        assert narrowing == ("set", "tmp_narrow", 1)
        temp_objects = {
            str(row[0]) for row in reader._connection.execute("SELECT name FROM temp.sqlite_master")
        }
        assert "tmp_narrow" in temp_objects
    assert list(sqlite_tmp.iterdir()) == []


def test_all_three_narrowing_kinds_are_reachable(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """07:1579-1582's tag is MEASURED: `empty` at zero rows, `set` at or below the cap, `all` above.

    `PREFILTER_MAX` is moved to 1 so the third branch is reachable without 200,001 blocks; the
    `LIMIT PREFILTER_MAX + 1` probe, the `>=` comparison and the `table` field are the shipped
    ones. `n` is EXACT in the `set` case (07:1581) and is the capped count in the `all` case, which
    is the difference the probe *"gives an exact candidate set or PROVES it is too big"* describes.
    """
    monkeypatch.setattr(rd, "PREFILTER_MAX", 1)
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()) == ("empty", None, 0)

    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()) == ("set", "tmp_narrow", 1)

    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
    _block(conn, block_id=2, doc_ord=1, producer_id=producer_id, ord_=1)
    conn.execute("COMMIT")
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()) == ("all", None, 2)


def test_an_empty_filter_set_short_circuits_before_any_statement_runs(built: Built) -> None:
    """`kind="empty"` from an empty `kinds` set is PROVEN, not measured, so nothing is scanned.

    ST5 (07:1637-1640) makes the asymmetry explicit for `deny_methods`: that field is
    `frozenset[Method]` and NOT `| None` *"because there is no third state to represent"*, which
    only says what it says if the `| None` fields DO have three -- `None` for no restriction and an
    empty set for restrict-to-nothing.

    The positive control is the second half: the same call with a real `Filters()` DOES issue
    statements, so an assertion of "no statements" cannot pass by the trace callback being broken.
    """
    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        statements: list[str] = []
        reader._connection.set_trace_callback(statements.append)
        assert reader.narrow(state, Filters(kinds=frozenset())) == ("empty", None, 0)
        assert statements == []
        assert reader.narrow(state, Filters()).kind == "set"
        reader._connection.set_trace_callback(None)
    assert any("tmp_narrow" in statement for statement in statements)


@pytest.mark.parametrize(
    "empty_filter",
    [
        pytest.param(Filters(doc_keys=frozenset()), id="doc_keys"),
        pytest.param(Filters(formats=frozenset()), id="formats"),
        pytest.param(Filters(kinds=frozenset()), id="kinds"),
        pytest.param(Filters(layers=frozenset()), id="layers"),
    ],
)
def test_every_positively_empty_set_filter_narrows_to_empty(
    built: Built, empty_filter: Filters
) -> None:
    """Four fields, one rule: an empty positive set restricts to nothing and matches nothing."""
    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, empty_filter) == ("empty", None, 0)


def test_the_filters_that_narrow_actually_narrow(built: Built) -> None:
    """Each `Filters` field that names a shipped column changes the candidate count.

    07:1564 is the rule this checks -- FILTERS NARROW -- and it is checked per field rather than in
    aggregate, because a predicate that was built but never bound (an `IN ()` with the wrong
    parameter order, a range with its bounds swapped) narrows to nothing and looks like a working
    filter until something asks for a row back.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf", fmt="pdf")
    _doc(conn, 2, uri="file:///other/b.md", fmt="markdown")
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id, page=0, kind="paragraph")
    _block(conn, block_id=2, doc_ord=1, producer_id=producer_id, page=3, ord_=1, kind="heading")
    _block(conn, block_id=3, doc_ord=1, producer_id=producer_id, page=0, ord_=2, layer="furniture")
    _block(conn, block_id=4, doc_ord=1, producer_id=producer_id, page=0, ord_=3, trust=1, quote=1)
    _block(conn, block_id=5, doc_ord=1, producer_id=producer_id, page=0, ord_=4, method="roundtrip")
    _block(conn, block_id=6, doc_ord=1, producer_id=producer_id, page=0, ord_=5, restriction_bits=2)
    _block(conn, block_id=7, doc_ord=2, producer_id=producer_id, page=0)
    conn.execute("COMMIT")

    reader = _reader(built)
    with reader.snapshot() as state:
        # layers defaults to {BODY}, so the furniture block is out from the start.
        assert reader.narrow(state, Filters()).n == 6
        assert reader.narrow(state, Filters(layers=frozenset({Layer.FURNITURE}))).n == 1
        assert reader.narrow(state, Filters(kinds=frozenset({Kind.HEADING}))).n == 1
        assert reader.narrow(state, Filters(pages=range(3, 4))).n == 1
        assert reader.narrow(state, Filters(min_trust=Trust.EXTRACTED)).n == 5
        assert reader.narrow(state, Filters(min_quote=Quote.VERBATIM)).n == 5
        assert reader.narrow(state, Filters(deny_methods=frozenset({Method.ROUNDTRIP}))).n == 5
        assert reader.narrow(state, Filters(deny_restriction_bits=2)).n == 5
        assert reader.narrow(state, Filters(uri_prefix="file:///corpus/")).n == 5
        assert reader.narrow(state, Filters(formats=frozenset({"markdown"}))).n == 1
        assert reader.narrow(state, Filters(doc_keys=frozenset({bytes([2]) * 16}))).n == 1
        assert reader.narrow(state, Filters(gen=2)) == ("empty", None, 0)


def test_a_uri_prefix_range_still_contains_a_supplementary_plane_character(
    built: Built,
) -> None:
    """The prefix upper bound is `prefix || U+10FFFF` and the last codepoint is load-bearing.

    A prefix filter is implemented as a half-open range so it can ride an index, and the bound has
    to be above every string that starts with the prefix. `U+FFFF` is the obvious-looking choice
    and it is WRONG: it encodes to `EF BF BF`, while any supplementary-plane character encodes to a
    four-byte sequence starting `F0`-`F4`, which sorts ABOVE it under SQLite's BINARY collation. So
    a document whose URI carries an emoji or a Gothic letter after the prefix would fall outside
    its own scope -- silently, as a smaller result set. This test is the only thing in the suite
    that can tell the two sentinels apart, and it exists because a mutation swapping them survived
    every other test here.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/plain.pdf")
    _doc(conn, 2, uri="file:///corpus/𐍈-gothic.pdf")
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id)
    _block(conn, block_id=2, doc_ord=2, producer_id=producer_id)
    conn.execute("COMMIT")
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters(uri_prefix="file:///corpus/")).n == 2
        assert reader.narrow(state, Filters(uri_prefix="file:///corpu")).n == 2
        assert reader.narrow(state, Filters(uri_prefix="file:///other/")).n == 0


def test_a_sec_path_prefix_is_a_range_scan_that_survives_the_four_digit_carry(
    built: Built,
) -> None:
    """`Filters.sec_path_prefix` joins `block_sec` and scans a range (0003_index.sql:283-291).

    The DDL prints the alternative upper bound -- *"the path with its last component
    incremented"* -- and that form loses rows at the carry it warns about two lines later:
    incrementing `/0001/9999` gives `/0001/10000`, which sorts BELOW `/0001/9999/0001` because
    `'1' < '9'`, so everything under the 9,999th sibling silently leaves the result. The sentinel
    bound has no carry, and the second half of this test is what tells the two apart.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf")
    paths = {
        1: "/0001/0002",
        2: "/0001/0002/0001",
        3: "/0001/0003",
        4: "/0001/9999",
        5: "/0001/9999/0001",
    }
    for block_id, sec_path in paths.items():
        _block(conn, block_id=block_id, doc_ord=1, producer_id=producer_id, ord_=block_id)
        conn.execute(
            "INSERT INTO block_sec(block_id, sec_id, sec_depth, sec_path) VALUES(?, ?, ?, ?)",
            (block_id, block_id, sec_path.count("/"), sec_path),
        )
    conn.execute("COMMIT")
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters(sec_path_prefix="/0001/0002")).n == 2
        assert reader.narrow(state, Filters(sec_path_prefix="/0001/0003")).n == 1
        assert reader.narrow(state, Filters(sec_path_prefix="/0001/9999")).n == 2
        assert reader.narrow(state, Filters(sec_path_prefix="/0002")).n == 0


def test_an_empty_deny_methods_is_no_restriction_and_not_a_restriction_to_nothing(
    built: Built,
) -> None:
    """ST5 in the SQL: 07:1590 says the `NOT IN (...)` clause is *"OMITTED ENTIRELY"* when empty.

    `Filters()` and `Filters(deny_methods=frozenset())` are *"the same query"* (07:1637-1640), and
    the failure the rule exists to prevent is the opposite reading, under which an unset deny list
    would exclude every method and return nothing.
    """
    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()) == reader.narrow(
            state, Filters(deny_methods=frozenset())
        )
        assert reader.narrow(state, Filters(deny_methods=frozenset())).n == 1


def test_a_tombstoned_or_superseded_block_is_not_a_candidate(built: Built) -> None:
    """`b.state = 0 AND b.gen = d.gen` is the head-generation projection (0001_init.sql:328-330)."""
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf", gen=2)
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id, gen=2)
    _block(conn, block_id=2, doc_ord=1, producer_id=producer_id, gen=1, ord_=1)
    _block(conn, block_id=3, doc_ord=1, producer_id=producer_id, gen=2, ord_=2, state=1)
    conn.execute("COMMIT")
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()) == ("set", "tmp_narrow", 1)
        assert reader.narrow(state, Filters(gen=1)).n == 1


def test_doc_keys_above_the_cap_become_a_second_temp_table_and_not_an_in_list(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """07:1608-1612: above `MAX_FILTER_DOC_KEYS` the keys go into `tmp_docs`, joined in.

    *"SQLite's parameter and expression-tree limits make a 100k-element `IN` list a parse-time
    failure rather than a slow query."* The ceiling changes the PLAN and never refuses the query,
    so the same filter must return the same rows on both sides of it -- which is what makes the
    cap safe to cross.
    """
    _seed_one_block(built)
    reader = _reader(built)
    keys = frozenset({bytes([1]) * 16, *(bytes([2, i // 256, i % 256]) * 5 for i in range(4))})
    with reader.snapshot() as state:
        below = reader.narrow(state, Filters(doc_keys=keys))
        assert below == ("set", "tmp_narrow", 1)
        temp_before = {
            str(row[0]) for row in reader._connection.execute("SELECT name FROM temp.sqlite_master")
        }
        assert "tmp_docs" not in temp_before

        monkeypatch.setattr(rd, "MAX_FILTER_DOC_KEYS", 2)
        above = reader.narrow(state, Filters(doc_keys=keys))
        temp_after = {
            str(row[0]) for row in reader._connection.execute("SELECT name FROM temp.sqlite_master")
        }
    assert above == below
    assert "tmp_docs" in temp_after


def test_the_narrowing_probe_runs_twice_on_one_connection(built: Built) -> None:
    """07:1601-1603: `IF NOT EXISTS` plus `DELETE FROM`, because a read connection is REUSED.

    *"A bare `CREATE TEMP TABLE` fails on the second query on that connection."* The second half is
    the `DELETE`: without it the second probe would union with the first, so the two narrowings
    below must not accumulate.
    """
    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()).n == 1
        assert reader.narrow(state, Filters()).n == 1
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()).n == 1


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        pytest.param(Filters(formats=frozenset({"owjob", "pdf"})), "owjob", id="owjob"),
        pytest.param(Filters(pages=range(0, 10, 2)), "step 2", id="strided_pages"),
        pytest.param(Filters(lang="en"), "Filters.lang", id="lang"),
    ],
)
def test_a_filter_that_cannot_be_honoured_is_a_usage_error_and_never_a_silent_drop(
    built: Built, bad: Filters, message: str
) -> None:
    """Three refusals, and each one refuses because the alternative returns a confident wrong set.

    `owjob` is 07:754's *"usage error naming `NO_JOB_DOCS`, not an empty result"*; a strided
    `pages` range *"would silently become a full scan"* (07:1613-1615); and `Filters.lang` names no
    shipped column at all (reader.py's DEFECT 1), so ignoring it would widen the query to the whole
    corpus. All three raise BEFORE any store read, which is what `UsageError` means (errors.py).
    """
    reader = _reader(built)
    with reader.snapshot() as state, pytest.raises(UsageError, match=message):
        reader.narrow(state, bad)


def test_the_enum_codes_come_from_this_store_and_not_from_this_builds_python_enum(
    built: Built,
) -> None:
    """07:1655-1657: the codes are *"resolved on the read connection"*, through `enum_val`.

    Reading `Kind.HEADING`'s ordinal off the Python enum instead would answer a query against an
    older store with this build's numbering. The test moves the store's own seed and asserts the
    narrowing follows the STORE: a block stored under the store's `heading` ord is still found by
    `kinds={Kind.HEADING}` after the ord changes, because both sides read the same table.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf")
    conn.execute("UPDATE enum_val SET ord = 99 WHERE domain = 'kind' AND name = 'heading'")
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id, kind="heading")
    conn.execute("COMMIT")
    assert int(conn.execute("SELECT kind FROM block WHERE block_id = 1").fetchone()[0]) == 99

    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters(kinds=frozenset({Kind.HEADING}))).n == 1
        assert reader.narrow(state, Filters(kinds=frozenset({Kind.PARAGRAPH}))).n == 0


def test_a_kind_this_store_never_seeded_is_refused_rather_than_matched_against_nothing(
    built: Built,
) -> None:
    """A member missing from `enum_val` means the seed predates this build, not that nothing
    matches."""
    built.writer.execute("DELETE FROM enum_val WHERE domain = 'kind' AND name = 'formula'")
    built.writer.commit()
    reader = _reader(built)
    with (
        reader.snapshot() as state,
        pytest.raises(StoreError, match="enum_val has no kind member"),
    ):
        reader.narrow(state, Filters(kinds=frozenset({Kind.FORMULA})))


# ---------------------------------------------------------------------------------------------
# 4. channel -- what P2 runs, and how legibly it refuses the rest
# ---------------------------------------------------------------------------------------------


def test_all_five_channels_are_implemented_by_this_build() -> None:
    """The end of the ladder P2 started: `_IMPLEMENTED_CHANNELS` is now `CHANNELS`.

    P2 shipped `{"exact"}`, W6.2b added `identity` and `lexical`, W6.2c `structural` and W6.2d
    `semantic`. Asserted against `CHANNELS` rather than against a written-out set, because the
    claim is *"all five"* and a written-out set would restate the code.
    """
    assert frozenset(rd.CHANNELS) == rd._IMPLEMENTED_CHANNELS


def test_a_channel_this_build_has_not_shipped_reports_off_not_built(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """16-roadmap.md:114's exact pair: `ChannelStatus.OFF` with `reason = "not_built"`.

    Every one of the five is implemented now, so the contract is asserted by emptying
    `_IMPLEMENTED_CHANNELS` rather than by naming a Channel that still refuses. That is not a
    weaker test: the frozenset is the module's one edit site for this branch, the branch is the
    shipped one, and a sixth Channel added to `CHANNELS` tomorrow reaches exactly this code.

    The reason string is asserted rather than the status alone, because P6 inherits this contract:
    `OffReason` is closed at four members *"because `ceiling()` branches on it"* (07:1214), so
    a free-form reason here would change a published `confidence` number with no error anywhere.
    `off` contributes nothing to the ceiling (07:1218-1222), which is why it is not `empty`.
    """
    monkeypatch.setattr(rd, "_IMPLEMENTED_CHANNELS", frozenset())
    _seed_one_block(built)
    reader = _reader(built)
    spec = ChannelSpec(name="lexical", budget_ms=50, limit=20, overfetch=1, weight=None, params={})
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        outcome = reader.channel(state, spec, narrowing)
    assert outcome.status == "off"
    assert outcome.reason == "not_built"
    assert outcome.ranked == ()


def test_a_sixth_channel_name_is_a_usage_error_and_not_a_silent_off(built: Built) -> None:
    """`ChannelSpec.name` is *"a member of `CHANNELS`"* (07:3295) and 07:1196 closes the five."""
    reader = _reader(built)
    spec = ChannelSpec(name="vibes", budget_ms=50, limit=20, overfetch=1, weight=None, params={})
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        with pytest.raises(UsageError, match="not one of the five Channels"):
            reader.channel(state, spec, narrowing)


def test_an_empty_narrowing_stops_every_channel_including_the_one_that_runs(built: Built) -> None:
    """The tagged type doing its job: an empty narrowed set has nothing inside it to rank.

    This is jcodemunch's failure in the other direction (07:1666-1680): there, an empty candidate
    set SKIPPED the filter and let the whole repository through, *"labelled 'Confident matches
    returned'"*. Here the empty set stops the Channel, and the reason says which.
    """
    _seed_one_block(built)
    reader = _reader(built)
    spec = ChannelSpec(
        name="exact",
        budget_ms=25,
        limit=20,
        overfetch=1,
        weight=None,
        params={},
        bind=ChannelInput(refs=(("fig-3", "figure"),)),
    )
    with reader.snapshot() as state:
        empty = reader.narrow(state, Filters(kinds=frozenset()))
        outcome = reader.channel(state, spec, empty)
    assert outcome.status == "empty"
    assert "narrowed set is empty" in outcome.reason


def _seed_refs(built: Built) -> None:
    """A corpus with one `anchor` definition and two `ref_site` occurrences of the same name.

    `anchor.run_id` is `NOT NULL REFERENCES derive_run(run_id)`, so the definition side needs a
    `derive_pass` and a `derive_run` row as well -- a corpus pass, which is what
    `derive_run.segment_id IS NULL` means (0002_graph.sql:174).
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf")
    _doc(conn, 2, uri="file:///corpus/b.pdf")
    # The ids INVERT reading order on purpose: block 9 is the definition and blocks 4 and 3 are
    # the two occurrences, so `ORDER BY tier, block_id` (07:1281 as printed) yields (9, 3, 4) and
    # 07:1271-1272's `(doc_ord, page, ord)` yields (9, 4, 3). Without the inversion the two
    # orderings agree and the assertion cannot tell them apart.
    _block(conn, block_id=9, doc_ord=1, producer_id=producer_id, page=9, ord_=1)
    _block(conn, block_id=4, doc_ord=1, producer_id=producer_id, page=0, ord_=0)
    _block(conn, block_id=3, doc_ord=2, producer_id=producer_id, page=0, ord_=0)
    conn.execute(
        "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, lanes, granularity, "
        "                        card_sha256, schema_version) "
        "VALUES('op.resolve', 'op', 'free', 0, '[\"anchor\"]', 'corpus', 'x', 1)"
    )
    conn.execute(
        "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
        "                       origin_operator, origin_driver, driver_schema_v, cost_class, "
        "                       input_digest, cache_key, status) "
        "VALUES(1, NULL, 'op.resolve', 1, ?, ?, 'op.resolve', 'core', 1, 'free', ?, 'k', 'ok')",
        (producer_id, _code(conn, "method", "heuristic"), DIGEST),
    )
    conn.execute(
        "INSERT INTO anchor(doc_ord, gen, name_norm, akind, surface, block_id, scope, run_id) "
        "VALUES(1, 1, 'fig3', 'figure', 'Figure 3', 9, 'corpus', 1)"
    )
    for block_id, doc_ord in ((4, 1), (3, 2)):
        conn.execute(
            "INSERT INTO ref_site(name_norm, akind, doc_ord, block_id, ts_a, ts_b, surface, "
            "                     scope, origin_operator) "
            "VALUES('fig3', 'figure', ?, ?, 4, 12, 'Figure 3', 'corpus', 'op.resolve')",
            (doc_ord, block_id),
        )
    conn.execute("COMMIT")


def _exact_spec(**bind: object) -> ChannelSpec:
    return ChannelSpec(
        name="exact",
        budget_ms=25,
        limit=20,
        overfetch=1,
        weight=None,
        params={},
        bind=ChannelInput(**bind),  # type: ignore[arg-type]
    )


def test_the_exact_channel_ranks_definitions_before_occurrences(built: Built) -> None:
    """07:1271-1272's order, which is why reader.py extends 07:1281's printed `ORDER BY`.

    The `anchor` row (block 9, the definition) must outrank both `ref_site` occurrences, and the
    two occurrences must then be in READING order `(doc_ord, page, ord)` -- block 4 in document 1
    before block 3 in document 2. The fixture inverts the ids against reading order for exactly
    this assertion: 07:1281's printed `ORDER BY tier, block_id` produces `(9, 3, 4)` here and
    07:1271-1272's prose produces `(9, 4, 3)`, so the two readings are distinguishable and DEFECT
    5's ruling is what the test pins.
    """
    _seed_refs(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        outcome = reader.channel(state, _exact_spec(refs=(("fig3", "figure"),)), narrowing)
    assert outcome.status == "ok"
    assert outcome.ranked == (9, 4, 3)


def test_the_exact_channel_carries_the_ref_site_span_and_invents_none_for_a_definition(
    built: Built,
) -> None:
    """07:2287-2290: a span comes from *"a `ref_site` `(ts_a, ts_b)` pair"*, and is never
    invented."""
    _seed_refs(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        outcome = reader.channel(state, _exact_spec(refs=(("fig3", "figure"),)), narrowing)
    assert set(outcome.spans) == {4, 3}
    assert outcome.spans[4].a == 4
    assert outcome.spans[4].b == 12
    assert 9 not in outcome.spans


def test_the_exact_channel_scores_only_within_the_narrowed_set(built: Built) -> None:
    """*"FILTERS NARROW. CHANNELS SCORE WITHIN THE NARROWED SET"* (07:1564).

    Narrowing to document 1 must drop the occurrence in document 2, and the assertion is on the
    RANKED IDS rather than on the count, because a Channel that ignored `tmp_narrow` would return
    the same three ids and only a per-id check can see it.
    """
    _seed_refs(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters(doc_keys=frozenset({bytes([1]) * 16})))
        outcome = reader.channel(state, _exact_spec(refs=(("fig3", "figure"),)), narrowing)
    assert outcome.ranked == (9, 4)


def test_the_exact_channel_honours_the_channel_local_limit(built: Built) -> None:
    """`ChannelSpec.limit` is *"channel-local top-N BEFORE fusion"* (07:3297).

    `truncated_at_limit` is what tells the Verdict the shortfall was the plan's and not the
    corpus's, which is gate 12's distinction (07:2192) applied one level down.
    """
    _seed_refs(built)
    reader = _reader(built)
    spec = ChannelSpec(
        name="exact",
        budget_ms=25,
        limit=2,
        overfetch=1,
        weight=None,
        params={},
        bind=ChannelInput(refs=(("fig3", "figure"),)),
    )
    with reader.snapshot() as state:
        outcome = reader.channel(state, spec, reader.narrow(state, Filters()))
    assert outcome.ranked == (9, 4)
    assert outcome.truncated_at_limit is True
    assert set(outcome.spans) == {4}


def test_a_document_scoped_anchor_never_resolves_another_documents_reference(
    built: Built,
) -> None:
    """0003_index.sql:250-252's second predicate, on the Channel path rather than in the view.

    *"A `scope='document'` anchor in document A resolves a `ref_site` in document B: 'Figure 3' in
    one contract binding 'Figure 3' in another. That is the single most common false merge in a
    document corpus."* With `scope_doc` unset, only a corpus-scoped anchor may be a definition.
    """
    _seed_refs(built)
    built.writer.execute("UPDATE anchor SET scope = 'document'")
    built.writer.commit()
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        unscoped = reader.channel(state, _exact_spec(refs=(("fig3", "figure"),)), narrowing)
        scoped = reader.channel(
            state, _exact_spec(refs=(("fig3", "figure"),), scope_doc=1), narrowing
        )
    assert unscoped.ranked == (4, 3)
    assert scoped.ranked == (9, 4, 3)


def test_the_exact_channel_is_empty_and_not_off_when_nothing_matches(built: Built) -> None:
    """`empty` means the statement RAN, which is a different fact from `off` and a different
    ceiling.

    07:1208: *"`ok`/`empty` contribute weight to the ceiling. `off` is an operator choice."*
    A Channel that looked and found nothing has done its job; reporting `off` would exempt it from
    the arithmetic it earned.
    """
    _seed_refs(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        no_refs = reader.channel(state, _exact_spec(), narrowing)
        no_match = reader.channel(state, _exact_spec(refs=(("nope", "figure"),)), narrowing)
    assert no_refs.status == "empty"
    assert "no reference-shaped tokens" in no_refs.reason
    assert no_match.status == "empty"
    assert "no anchor or ref_site row" in no_match.reason


def test_a_channel_outcome_that_is_not_ok_must_carry_a_reason(built: Built) -> None:
    """07:1232: `reason` is REQUIRED when status is not OK, and the shape enforces it."""
    del built
    with pytest.raises(ValueError, match="REQUIRED when status is not OK"):
        rd.ChannelOutcome(name="exact", status="off")
    with pytest.raises(ValueError, match="duplicate-free"):
        rd.ChannelOutcome(name="exact", status="ok", ranked=(1, 1))


# ---------------------------------------------------------------------------------------------
# 4a. channel -- identity: the ladder, and the tier ACTUALLY measured
# ---------------------------------------------------------------------------------------------


def _seed_identity(built: Built) -> None:
    """One document, its root block, and the three labels the 40 tier exists to keep apart.

    The pages INVERT the ladder on purpose. Block 45 carries the literal label and sits on the LAST
    page, block 30 carries the prefix label and sits on the first, so reading order yields
    `(30, 40, 45)` and the ladder yields `(45, 40, 30)`: the two orderings are distinguishable and
    a test that asserts the second is asserting the ladder and not the seed.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/handbook.pdf")
    _block(
        conn,
        block_id=1,
        doc_ord=1,
        producer_id=producer_id,
        page=0,
        ord_=0,
        addr="doc",
        text="the handbook",
    )
    _block(
        conn,
        block_id=30,
        doc_ord=1,
        producer_id=producer_id,
        page=1,
        ord_=1,
        label="Table 3.2 (revised)",
        text="the revised table",
    )
    _block(
        conn,
        block_id=40,
        doc_ord=1,
        producer_id=producer_id,
        page=2,
        ord_=2,
        label="Table 3-2",
        text="the punctuation-different table",
    )
    _block(
        conn,
        block_id=45,
        doc_ord=1,
        producer_id=producer_id,
        page=3,
        ord_=3,
        label="Table 3.2",
        text="the literal table",
    )
    conn.execute("COMMIT")


def _identity_spec(limit: int = 20, **bind: object) -> ChannelSpec:
    return ChannelSpec(
        name="identity",
        budget_ms=15,
        limit=limit,
        overfetch=1,
        weight=None,
        params={},
        bind=ChannelInput(**bind),  # type: ignore[arg-type]
    )


def test_a_cite_resolves_at_tier_fifty_and_the_grade_names_the_tier(built: Built) -> None:
    """07:1864's transcript: *"identity: OK, ranked=(block 412's block_id,),
    grades={...: "cite_exact"}"*."""
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _identity_spec(idents=("d1#40",)), reader.narrow(state, Filters())
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (40,)
    assert outcome.grades == {40: "cite_exact"}


def test_the_cite_lookup_supplies_both_columns_of_the_two_column_index(built: Built) -> None:
    """D240, measured. 07:1269-1270: *"Resolution is `block_cite` / `block_addr` / `doc(uri)`
    index lookups plus a `head_fts` title probe; cost is **sub-millisecond**"*.

    `CREATE UNIQUE INDEX block_cite ON block(doc_ord, cite)` (0001_init.sql:306) is COMPOSITE and
    a query string carries only the second column, so `WHERE cite = 'd1#40'` cannot use the index
    at all -- SQLite needs the left-most column -- and the ladder's cheapest tier becomes a full
    scan of `block`. The `doc_ord` is INSIDE the cite, which is what `cite_doc_ord()` recovers.

    The statement under test is the one the Channel actually ran, captured through the connection's
    trace callback (which expands the bound parameters, so it re-plans verbatim). The
    counterfactual is DERIVED from it by deleting the one predicate this cell exists to add, so the
    two plans differ by exactly the `doc_ord` and nothing else.

    Both `EXPLAIN QUERY PLAN`s run on the reader's own connection and INSIDE the snapshot, because
    `tmp_narrow` lives in that connection's TEMP schema and does not survive the snapshot's
    rollback.
    """
    _seed_identity(built)
    connection = ow.connect_readonly(built.path)
    reader = rd.SqliteReader(connection, now_ns=NOW_NS)
    executed: list[str] = []

    def plan_of(sql: str) -> list[str]:
        return [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql)]

    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        connection.set_trace_callback(executed.append)
        reader.channel(state, _identity_spec(idents=("d1#40",)), narrowing)
        connection.set_trace_callback(None)
        cite_sql = [sql for sql in executed if "b.cite = " in sql]
        assert len(cite_sql) == 1, f"expected one cite statement, got {cite_sql}"
        assert "b.doc_ord = 1 AND " in cite_sql[0]
        without = cite_sql[0].replace("b.doc_ord = 1 AND ", "")
        with_plan = plan_of(cite_sql[0])
        without_plan = plan_of(without)
    assert any("block_cite" in step for step in with_plan), with_plan
    assert not any("block_cite" in step for step in without_plan), without_plan


def test_the_forty_tier_survives_the_round_trip_through_the_store(built: Built) -> None:
    """16-roadmap.md:669's freeze item, asserted over real `head_fts` rows rather than in Python.

    `unicode61 remove_diacritics 2` folds case and diacritics and NOTHING else, so FTS5 returns all
    three labels as candidates and cannot itself tell them apart. `grade_title()` does, and 07:1265
    names the failure it prevents: *"The document analogue is 'Table 3.2 (revised)' tying with
    'Table 3.2'."* Here it does not tie -- it grades 30 against the literal match's 45, with the
    punctuation-different label at 40 between them.
    """
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _identity_spec(idents=("Table 3.2",)), reader.narrow(state, Filters())
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (45, 40, 30)
    assert outcome.grades == {
        45: "title_exact",
        40: "title_normalised",
        30: "title_prefix",
    }


def test_a_document_uri_resolves_to_one_block_and_not_to_the_whole_document(
    built: Built,
) -> None:
    """07:1254's ladder is over *"a block **or document**"* and `ranked` is block ids (07:1228).

    One block, and it is the document root (`addr = 'doc'`). Returning every block of the document
    at tier 50 would put a 41,822-block document above every other Channel's first hit and report
    `confidence = 1.000` for a URI match, which is the arithmetic ST8 exists to stop.
    """
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _identity_spec(idents=("file:///corpus/handbook.pdf",)),
            reader.narrow(state, Filters()),
        )
    assert outcome.ranked == (1,)
    assert outcome.grades == {1: "doc_uri_exact"}


def test_the_strongest_measured_tier_wins_when_two_idents_reach_one_block(built: Built) -> None:
    """07:1255: *"the one actually measured"* -- and the cite lookup DID measure 50.

    The title ident is listed FIRST, so a Channel that kept whichever grade it saw first would
    report `title_exact` and understate evidence it holds. `ranked` is duplicate-free (07:1228),
    so one of the two grades has to go and only the higher one is defensible.
    """
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _identity_spec(idents=("Table 3.2", "d1#45")),
            reader.narrow(state, Filters()),
        )
    assert outcome.ranked[0] == 45
    assert outcome.grades[45] == "cite_exact"


def test_an_addr_reaches_tier_fifty_only_under_a_document_scope(built: Built) -> None:
    """D241's first clause, and the half this cell can discharge.

    `block_addr` is `(doc_ord, gen, addr)` and `p2/0` is document-relative by construction: with no
    `ChannelInput.scope_doc` there is no left-most column to supply and no way to tell which
    document's `p2/0` was meant, so the rung does not run at all rather than calling one block per
    document a tier-50 hit.
    """
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        unscoped = reader.channel(state, _identity_spec(idents=("p2/2",)), narrowing)
        scoped = reader.channel(state, _identity_spec(idents=("p2/2",), scope_doc=1), narrowing)
    assert unscoped.status == "empty"
    assert scoped.ranked == (40,)
    assert scoped.grades == {40: "addr_exact"}


def test_the_identity_channel_scores_only_within_the_narrowed_set(built: Built) -> None:
    """`narrow()` bounds what is RETURNED (07:1585-1591), the ladder included."""
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters(pages=range(0, 2)))
        outcome = reader.channel(state, _identity_spec(idents=("Table 3.2",)), narrowing)
    assert narrowing.kind == "set"
    assert outcome.ranked == (30,)


def test_the_identity_channel_is_empty_and_not_off_when_nothing_matched(built: Built) -> None:
    """07:1843's own transcript line: *"identity: EMPTY -- no cite, addr, uri or title matched."*

    And `empty` rather than `off`, because `empty` means the lookups RAN: 07:1218-1219 keeps its
    weight in the ceiling for exactly that reason.
    """
    _seed_identity(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        nothing_bound = reader.channel(state, _identity_spec(), narrowing)
        no_match = reader.channel(state, _identity_spec(idents=("d9#1",)), narrowing)
    assert nothing_bound.status == "empty"
    assert "no cite, addr, uri or title candidate" in nothing_bound.reason
    assert no_match.status == "empty"
    assert no_match.reason == "no cite, addr, uri or title matched"


def test_a_grade_for_a_block_the_channel_did_not_rank_is_refused() -> None:
    """07:1231: `grades` is *"the tier ACTUALLY measured"*, and a block that was not returned had
    nothing measured about it."""
    with pytest.raises(ValueError, match="graded blocks it did not rank"):
        rd.ChannelOutcome(name="identity", status="ok", ranked=(1,), grades={2: "cite_exact"})


def test_a_tier_the_ladder_does_not_define_is_refused() -> None:
    """`Hit.identity_grade` is printed (07:2296) and an invented tier has no rank to be read
    against."""
    with pytest.raises(ValueError, match="IDENTITY_LADDER"):
        rd.ChannelOutcome(name="identity", status="ok", ranked=(1,), grades={1: "title_ish"})


# ---------------------------------------------------------------------------------------------
# 4b. channel -- lexical: W_BODY, W_HEAD and SPINE_DECAY, spent
# ---------------------------------------------------------------------------------------------


def _seed_lexical(built: Built) -> None:
    """A two-level section spine, and two bodies whose bm25 order is the OPPOSITE of their spine
    order.

    Block 11 sits one hop under the heading whose label matches and carries a LONG body; block 21
    sits two hops under it and carries the single word `notice`. So the body term alone ranks 21
    above 11 and the spine term alone ranks 11 above 21, and a test that asserts either ordering is
    asserting which term won rather than which block happened to be seeded first.

    `block_sec` is written by hand: it is 0003's DERIVED table (0003_index.sql:277-283) and nothing
    in the store writes it yet -- 16-roadmap.md:406 leaves the derived tables to their own phases.
    Block 10 has no `block_sec` row, which is what a top-level section looks like and is where the
    spine walk stops.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/handbook.pdf")
    _block(
        conn,
        block_id=10,
        doc_ord=1,
        producer_id=producer_id,
        page=1,
        ord_=0,
        kind="heading",
        label="Parental leave",
        text="Parental leave",
    )
    _block(
        conn,
        block_id=11,
        doc_ord=1,
        producer_id=producer_id,
        page=1,
        ord_=1,
        text="notice period runs four weeks and several extra words to dilute the body score",
    )
    _block(
        conn,
        block_id=20,
        doc_ord=1,
        producer_id=producer_id,
        page=2,
        ord_=2,
        kind="heading",
        label="Schedules",
        text="Schedules",
    )
    _block(conn, block_id=21, doc_ord=1, producer_id=producer_id, page=2, ord_=3, text="notice")
    _block(conn, block_id=30, doc_ord=1, producer_id=producer_id, page=3, ord_=4, text="notice")
    for block_id, sec_id, depth, path in (
        (11, 10, 1, "/0001"),
        (20, 10, 1, "/0001"),
        (21, 20, 2, "/0001/0001"),
    ):
        conn.execute(
            "INSERT INTO block_sec(block_id, sec_id, sec_depth, sec_path) VALUES(?, ?, ?, ?)",
            (block_id, sec_id, depth, path),
        )
    conn.execute("COMMIT")


def _lexical_spec(limit: int = 20, **bind: object) -> ChannelSpec:
    return ChannelSpec(
        name="lexical",
        budget_ms=50,
        limit=limit,
        overfetch=5,
        weight=None,
        params={},
        bind=ChannelInput(**bind),  # type: ignore[arg-type]
    )


def test_the_lexical_channel_ranks_by_the_body_term_when_no_heading_matches(
    built: Built,
) -> None:
    """`lex(b) = W_BODY x bm25n(block_fts, b) + W_HEAD x 0`, which is bm25 with a tie-break.

    No label carries `notice`, so `max over spine(b)` is zero for every candidate and the ranking
    is the body scorer's. The two one-word blocks tie exactly -- identical text, identical column
    size -- and reading order `(doc_ord, page, ord)` breaks the tie, never `block_id`, which is
    *"a DURABLE surrogate"* (0001_init.sql:236) and therefore ingest order.
    """
    _seed_lexical(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _lexical_spec(terms=("notice",)), reader.narrow(state, Filters())
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (21, 30, 11)


def test_the_spine_term_promotes_a_block_under_a_matching_heading_and_decays_with_depth(
    built: Built,
) -> None:
    """07:1294-1299's whole formula, including `b` as its own depth-0 ancestor.

    ```
    lex(10) = bm25n + 6.0 x 0.6**0 = bm25n + 6.00     the heading, its own spine
    lex(11) = bm25n + 6.0 x 0.6**1 = bm25n + 3.60     one hop under it
    lex(21) = bm25n + 6.0 x 0.6**2 = bm25n + 2.16     two hops under it
    lex(30) = bm25n + 6.0 x 0                         under no section at all
    ```

    `bm25n` is in `[0, 1]` by construction, so the four spine terms are separated by more than the
    body term can close and the ordering is the spine's. That is `W_HEAD = 6.0` doing what D5
    chose it for, and it is why block 21 -- which the body scorer ranks FIRST (the previous test)
    -- lands third here.
    """
    _seed_lexical(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _lexical_spec(terms=("parental", "notice")),
            reader.narrow(state, Filters()),
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (10, 11, 21, 30)


def test_the_head_probe_is_not_narrowed_although_the_body_probe_is(built: Built) -> None:
    """An ancestor heading is EVIDENCE about a candidate, not a candidate.

    `Filters(kinds={PARAGRAPH})` is the ordinary way to exclude headings from an answer, and it
    must not thereby delete a spine term worth six times the body weight. With the head probe
    narrowed the boost vanishes and the ranking reverts to the body scorer's `(21, 30, 11)`; with
    it unnarrowed the spine wins and block 11 leads. The two orders are different, which is what
    makes this assertion about the join and not about the seed.
    """
    _seed_lexical(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters(kinds=frozenset({Kind.PARAGRAPH})))
        outcome = reader.channel(state, _lexical_spec(terms=("parental", "notice")), narrowing)
    assert narrowing.kind == "set"
    assert outcome.ranked == (11, 21, 30)


def test_the_lexical_channel_matches_any_term_and_not_all_of_them(built: Built) -> None:
    """`OR`, not FTS5's implicit `AND`. `MAX_QUERY_TERMS` is 64 and a 64-term conjunction matches
    nothing, so an implicit-AND Channel reports `EMPTY` for every sentence-shaped query -- absence
    manufactured by a tokeniser, which is the one thing §6.8's gate ladder exists to prevent."""
    _seed_lexical(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _lexical_spec(terms=("parental", "zzzabsentword")),
            reader.narrow(state, Filters()),
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (10,)


def test_a_building_fts_index_is_unavailable_and_not_empty(built: Built) -> None:
    """0003_index.sql:413-418's three-state machine, read before the Channel runs.

    07:432-433: *"An FTS index of unknown completeness must degrade the Verdict, because a missing
    posting is indistinguishable from an absent phrase."* `empty` would be a claim about the corpus;
    `unavailable` is a claim about the index, and only the second is true.
    """
    _seed_lexical(built)
    built.writer.execute("UPDATE index_state SET v = 'building' WHERE k = 'fts_state'")
    built.writer.commit()
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _lexical_spec(terms=("notice",)), reader.narrow(state, Filters())
        )
    assert outcome.status == "unavailable"
    assert outcome.reason == "fts_building"
    assert outcome.ranked == ()


def test_the_lexical_channel_honours_the_channel_local_limit(built: Built) -> None:
    """`ChannelSpec.limit` already carries `LEX_OVERFETCH`: `plan()` sets `limit = k x overfetch`,
    so `k=20` arrives here as 100 and this method never multiplies again."""
    _seed_lexical(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _lexical_spec(limit=2, terms=("notice",)), reader.narrow(state, Filters())
        )
    assert outcome.ranked == (21, 30)
    assert outcome.truncated_at_limit is True


def test_the_lexical_channel_is_empty_and_not_off_when_nothing_matches(built: Built) -> None:
    """Two different empties, and each says which: nothing to match, or nothing matched."""
    _seed_lexical(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        no_terms = reader.channel(state, _lexical_spec(), narrowing)
        no_match = reader.channel(state, _lexical_spec(terms=("zzzabsentword",)), narrowing)
    assert no_terms.status == "empty"
    assert "no query term survived sanitisation" in no_terms.reason
    assert no_match.status == "empty"
    assert "carries any of the query terms" in no_match.reason


def test_a_channel_whose_tables_this_store_does_not_carry_is_unavailable(built: Built) -> None:
    """A store fact, not a build one, and therefore not `off`.

    `off` is 07:1204, *"the P-stage has not shipped it"*, and is ceiling-EXEMPT; a store built by
    an earlier migration set has a Channel this build DID ship and this file cannot answer, which
    is `unavailable` and forces `degraded`. The alternative is `no such table: block_fts` crossing
    the `Reader` boundary as an exception.
    """
    _seed_lexical(built)
    built.writer.execute("DROP TABLE block_fts")
    built.writer.commit()
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _lexical_spec(terms=("notice",)), reader.narrow(state, Filters())
        )
    assert outcome.status == "unavailable"
    assert outcome.reason == "this store carries no block_fts"


# ---------------------------------------------------------------------------------------------
# 4c. channel -- structural: a bounded frontier BFS, and each of its four ceilings
# ---------------------------------------------------------------------------------------------

REFERS_TO = "refers_to"
CITES = "cites"


def _seed_links(built: Built) -> None:
    """One document, nine blocks and a small link graph with a cycle in it.

    ```
      1 --refers_to(w=1.0)--> 2 --> 4 --> 5 --> 6 --> 7      the chain the hop cap stops
      1 --refers_to(w=0.5)--> 3 --refers_to--> 1             the cycle back to the seed
      1 --cites(w=2.0)------> 8                              excluded by the allowlist
      1 --refers_to(w=0.1, trust=AMBIGUOUS)--> 9             excluded by min_trust
    ```

    `relation_vocab` is seeded here because P2 creates it EMPTY -- 0002_graph.sql:34-35
    withholds `etype_vocab`'s fifteen builtin rows and `relation_vocab`'s thirteen alike -- and
    `block_link.relation` is a foreign key into it, so a link cannot exist without the row.

    Block 4 is on page 9 while every other block is on pages 0-7. That is what lets one test
    narrow it away without touching the rest of the graph, and it also makes reading order
    disagree with `block_id` order, so a tie-break asserted below is asserting the right one.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/graph.pdf")
    pages = {1: 0, 2: 1, 3: 2, 4: 9, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7}
    for index, (block_id, page) in enumerate(sorted(pages.items())):
        _block(
            conn,
            block_id=block_id,
            doc_ord=1,
            producer_id=producer_id,
            page=page,
            ord_=index,
            text=f"block {block_id}",
        )
    for relation in (REFERS_TO, CITES):
        conn.execute(
            "INSERT INTO relation_vocab(relation, symmetric, actor_rule, source) "
            "VALUES(?, 0, 'source refers to target', 'builtin')",
            (relation,),
        )
    links = (
        (1, 2, REFERS_TO, 1.0, 2),
        (1, 3, REFERS_TO, 0.5, 2),
        (2, 4, REFERS_TO, 1.0, 2),
        (4, 5, REFERS_TO, 1.0, 2),
        (5, 6, REFERS_TO, 1.0, 2),
        (6, 7, REFERS_TO, 1.0, 2),
        (3, 1, REFERS_TO, 1.0, 2),
        (1, 8, CITES, 2.0, 2),
        (1, 9, REFERS_TO, 0.1, 0),
    )
    for src, dst, relation, weight, trust in links:
        conn.execute(
            "INSERT INTO block_link(src_block, dst_block, relation, weight, producer_id, trust, "
            "                       origin_operator, origin_driver, driver_schema_v) "
            "VALUES(?, ?, ?, ?, ?, ?, 'op.link', 'drv', 1)",
            (src, dst, relation, weight, producer_id, trust),
        )
    conn.execute("COMMIT")


def _expand(**over: object) -> Expand:
    """`Expand` with the plan's defaults except `relations`, which has none (07:1360)."""
    fields: dict[str, object] = {"relations": frozenset({REFERS_TO})}
    fields.update(over)
    return Expand(**fields)  # type: ignore[arg-type]


def _structural_spec(limit: int = 20, budget_ms: int = 40, **bind: object) -> ChannelSpec:
    return ChannelSpec(
        name="structural",
        budget_ms=budget_ms,
        limit=limit,
        overfetch=1,
        weight=None,
        params={},
        bind=ChannelInput(**bind),  # type: ignore[arg-type]
    )


def test_the_structural_channel_ranks_by_weight_times_trust_over_log1p_degree(
    built: Built,
) -> None:
    """07:1894 and 18:2834's ordering, and it is NOT hop order.

    ```
      hop 1   1 -> 2   1.0 x 2 / log1p(2) = 1.8207     the seed has two eligible links
              1 -> 3   0.5 x 2 / log1p(2) = 0.9103
      hop 2   2 -> 4   1.0 x 2 / log1p(1) = 2.8854     one link, so a smaller denominator
              3 -> 1   1.0 x 2 / log1p(1) = 2.8854     the cycle back to the seed
    ```

    So a two-hop block outranks both one-hop blocks, which is what the formula says and what a
    hop-decay would have hidden: there is no `SPINE_DECAY` here, deliberately, because the decay
    that bounds this Channel is the hop CAP and not a weight. Blocks 1 and 4 tie exactly, and
    reading order breaks it -- block 1 is on page 0 and block 4 on page 9.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand()),
            reader.narrow(state, Filters()),
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (1, 4, 2, 3)
    assert outcome.truncated_at_limit is False
    assert outcome.degradations == ()


def test_a_seed_reached_from_another_block_is_a_result_and_is_still_never_re_expanded(
    built: Built,
) -> None:
    """`visited` bounds what is EXPANDED, not what is RANKED, and 07:1892-1896 needs both.

    That transcript seeds the traversal from `tmp_narrow` itself and reports 311 ranked blocks --
    every one of them already a seed -- so a set that excluded seeds from the result would report
    zero there. The other half is what stops a cyclic reference graph from running forever:
    block 1 is reached at hop 2 through `3 -> 1`, ranks, and is not expanded a second time.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(max_hops=4)),
            reader.narrow(state, Filters()),
        )
    assert 1 in outcome.ranked
    assert len(set(outcome.ranked)) == len(outcome.ranked)
    # 1 is expanded at hop 0 only, so 2 and 3 are never re-offered as fresh neighbours.
    assert outcome.ranked.count(2) == 1


def test_max_hops_is_hard_capped_at_four_however_many_are_asked_for(built: Built) -> None:
    """07:1345 and 18:2832's `HARD CAP 4`, clamped at the traversal.

    `store/types.py` prints the cap as a comment and enforces nothing: it is a clamp at the
    traversal and not a field constraint -- so `max_hops=99` is a legal `Expand` and an illegal
    traversal. The chain `1 -> 2 -> 4 -> 5 -> 6 -> 7` puts block 6 at hop 4 and block 7 at hop 5,
    which is the one link the cap has to cut.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(max_hops=99)),
            reader.narrow(state, Filters()),
        )
    assert 6 in outcome.ranked
    assert 7 not in outcome.ranked


def test_the_per_hop_beam_cuts_the_frontier_and_says_it_truncated(built: Built) -> None:
    """`beam: int = 64  # per hop, ordered by (weight x trust) / log1p(degree)` (07:1346).

    With `beam=1` the weaker of the seed's two neighbours is dropped before hop 2, so block 3 is
    never reached and the cycle through it never runs. `truncated_at_limit` is set because the
    shortfall is the plan's and not the corpus's -- the same distinction gate 12 draws one level
    up (07:2192).
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(beam=1)),
            reader.narrow(state, Filters()),
        )
    assert outcome.ranked == (4, 2)
    assert outcome.truncated_at_limit is True


def test_max_visited_stops_the_traversal_and_keeps_what_it_had_already_reached(
    built: Built,
) -> None:
    """`max_visited = 4096` (07:1349), here moved to 2 so one seed plus one hop exhausts it.

    Block 3 is REACHED at hop 1 and ranks, and is not EXPANDED because the visited budget is
    spent -- which is the same split the cycle test asserts from the other side.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(max_visited=2)),
            reader.narrow(state, Filters()),
        )
    assert outcome.ranked == (2, 3)
    assert outcome.truncated_at_limit is True


def test_a_hub_contributes_at_most_hub_cap_neighbours_and_sets_a_degradation(
    built: Built,
) -> None:
    """07:1349-1351, and row 19 of 15-observability.md's closed twenty-seven.

    *"a block with more links contributes at most `hub_cap` neighbours, sampled by weight, and
    sets `degradations += [Degradation(kind="hub_capped", ...)]`"*. Sampled by weight and
    DETERMINISTICALLY: the statement is ordered `weight DESC, dst_block`, so the kept subset is
    the top `hub_cap` and two runs over one store agree, which a weighted random sample would
    break and ST7 rests on.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(hub_cap=1, max_hops=1)),
            reader.narrow(state, Filters()),
        )
    assert outcome.ranked == (2,)
    assert outcome.degradations == ("hub_capped",)


def test_only_the_named_relations_are_traversed(built: Built) -> None:
    """07:1344 gives `Expand.relations` the comment *"REQUIRED, no default"*, and the
    allowlist is why.

    The same seed reaches block 8 under `{cites}` and never under `{refers_to}`: one link, one
    relation, two different answers.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        cites = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(relations=frozenset({CITES}))),
            narrowing,
        )
        refers = reader.channel(state, _structural_spec(seeds=(1,), expand=_expand()), narrowing)
    assert cites.ranked == (8,)
    assert 8 not in refers.ranked


def test_min_trust_filters_the_links_and_moves_the_degree_it_divides_by(built: Built) -> None:
    """`min_trust: Trust = Trust.INFERRED` (07:1348), and the degree is the ELIGIBLE degree.

    Block 9 hangs off an `AMBIGUOUS` link and the default floor excludes it. Lowering the floor
    admits it, and the seed's degree goes from 2 to 3 -- so every score at that hop falls, which
    is what "a block with more links" ought to mean and is why the count is taken after the
    filters rather than off `block_link` whole. The `AMBIGUOUS` link scores 0.0 and the block
    still ranks, which is 0001_init.sql:319's rule for an ambiguous link: kept, ranked down,
    never dropped.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        strict = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(max_hops=1)),
            narrowing,
        )
        loose = reader.channel(
            state,
            _structural_spec(seeds=(1,), expand=_expand(max_hops=1, min_trust=Trust.AMBIGUOUS)),
            narrowing,
        )
    assert strict.ranked == (2, 3)
    assert loose.ranked == (2, 3, 9)


def test_the_traversal_is_joined_to_the_narrowed_set_at_every_hop(built: Built) -> None:
    """18:2836: *"joined to `tmp_narrow` at every hop so it cannot leave the scope"*.

    Block 4 is on page 9 and the filter stops at page 5, so hop 2's `2 -> 4` link is not followed
    -- and the ranking that remains is the one the cycle produced, which proves the traversal ran
    rather than stopping at hop 1.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters(pages=range(0, 5)))
        outcome = reader.channel(state, _structural_spec(seeds=(1,), expand=_expand()), narrowing)
    assert narrowing.kind == "set"
    assert outcome.ranked == (1, 2, 3)


def test_with_no_seed_bound_the_traversal_starts_from_tmp_narrow_itself(built: Built) -> None:
    """07:1332's last rung: *"when no scoring Channel precedes it, from `tmp_narrow` itself"*.

    That is plan 3's shape (07:1892-1896) -- no `identity` seed, no `lexical` Channel in the plan,
    so the narrowed set seeds itself and every block it reaches is also inside it. Blocks 8 and 9
    are still absent, because the relation allowlist and `min_trust` do not care where the seed
    came from.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _structural_spec(expand=_expand()), reader.narrow(state, Filters())
        )
    assert outcome.status == "ok"
    assert outcome.ranked == (1, 5, 6, 7, 4, 2, 3)
    assert 8 not in outcome.ranked
    assert 9 not in outcome.ranked


def test_a_narrowing_that_proved_the_set_too_big_leaves_the_traversal_no_bounded_start(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`kind="all"` is a PROOF that the candidate set could not be enumerated (07:1585-1591).

    There is no `tmp_narrow` to seed from, and seeding from "the corpus" is the unbounded
    traversal `Expand` exists to make unrepresentable. `unavailable` and not `empty`, because the
    Channel did not look: `empty` would be a claim about the corpus's links.
    """
    monkeypatch.setattr(rd, "PREFILTER_MAX", 1)
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        outcome = reader.channel(state, _structural_spec(expand=_expand()), narrowing)
    assert narrowing.kind == "all"
    assert outcome.status == "unavailable"
    assert "no bounded" in outcome.reason


def test_a_structural_channel_with_no_expand_bound_is_unavailable(built: Built) -> None:
    """There is no default relation set to fall back to, and inventing one is the failure.

    07:1360-1362 forbids "all relations" by construction, and no part of section 5.2 says where an
    `Expand` comes from when `Query.expand` is `None` -- so the Channel reports that it could not
    look. D247.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _structural_spec(seeds=(1,)), reader.narrow(state, Filters())
        )
    assert outcome.status == "unavailable"
    assert "no Expand" in outcome.reason


def test_a_relation_this_store_does_not_carry_is_a_usage_error_naming_the_vocabulary(
    built: Built,
) -> None:
    """07:1361: *"silently traversing nothing is indistinguishable from a corpus with no links"*.

    A misspelled relation makes the `IN (...)` list match nothing, the Channel reports `EMPTY`,
    absence gate 2 does not fire because `EMPTY` is not `UNAVAILABLE`, and the Verdict says the
    corpus has no links. The empty set is refused for the same reason it has no default.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        with pytest.raises(UsageError, match="relation_vocab"):
            reader.channel(
                state,
                _structural_spec(seeds=(1,), expand=_expand(relations=frozenset({"refres_to"}))),
                narrowing,
            )
        with pytest.raises(UsageError, match="no default"):
            reader.channel(
                state,
                _structural_spec(seeds=(1,), expand=_expand(relations=frozenset())),
                narrowing,
            )


def test_a_channel_over_its_own_budget_is_unavailable_with_the_one_reason_gate_one_reads(
    built: Built,
) -> None:
    """07:1817's half of the two-deadline split, at 07:1805's cancellation point.

    07:1805 -- *"`structural` at the top of each hop"* -- is the first cancellation point any
    Channel in this module can have: the other three are single statements, and `interrupt()`
    aborts the whole
    transaction, so it is reserved for the snapshot deadline. A Channel over its OWN `budget_ms`
    returns `UNAVAILABLE(timeout)` and forces `degraded`; the QUERY deadline is the other case
    entirely and reports `OK`. Absence gate 1 reads `reason == "timeout"` and nothing else
    (07:1221), so the string is asserted rather than the status alone.

    `monotonic_ns` is injected, so the budget is spent without spending the wall time -- the same
    parameter and the same reason as `store/sqlite.py`'s `snapshot()`.
    """
    _seed_links(built)
    ticks = iter([0, 30_000_000])
    reader = rd.SqliteReader(
        ow.connect_readonly(built.path),
        now_ns=NOW_NS,
        monotonic_ns=lambda: next(ticks, 30_000_000),
    )
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _structural_spec(budget_ms=25, seeds=(1,), expand=_expand()),
            reader.narrow(state, Filters()),
        )
    assert outcome.status == "unavailable"
    assert outcome.reason == "timeout"
    assert outcome.ranked == ()


def test_the_structural_channel_is_empty_when_the_seed_reaches_nothing(built: Built) -> None:
    """Plan 1's transcript, 07:1846-1849: *"the frontier is empty at hop 1: ranked=0,
    status EMPTY, weight still counts in the ceiling"*."""
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state, _structural_spec(seeds=(7,), expand=_expand()), reader.narrow(state, Filters())
        )
    assert outcome.status == "empty"
    assert "no block_link row reaches" in outcome.reason


# ---------------------------------------------------------------------------------------------
# 4d. channel -- semantic: a backend call, one join back, and a capped lift
# ---------------------------------------------------------------------------------------------


class FakeVectors:
    """A `VectorBackend` that answers from a list, so what is tested is the CHANNEL.

    The seam is the Protocol (07:86-92), and `vector.brute` is a separate cell, so a Channel test
    that needed the real backend would be testing two things and pinning neither. This records
    every `search()` call, because half of what this Channel owes the plan is in the ARGUMENTS:
    contract obligation (1)'s `candidates` and the over-fetch clamp that replaces it.
    """

    def __init__(self, hits: list[tuple[bytes, float]], *, raises: Exception | None = None) -> None:
        self.hits = hits
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    def manifest(self) -> object:  # pragma: no cover -- not on the Channel's path
        raise NotImplementedError

    def upsert(self, model_key: str, rows: object) -> int:  # pragma: no cover
        raise NotImplementedError

    def sweep(self, live: object) -> int:  # pragma: no cover
        raise NotImplementedError

    def search(
        self,
        model_key: str,
        q_sig: bytes,
        q_full: bytes | None,
        *,
        k: int,
        candidates: frozenset[bytes] | None,
    ) -> list[tuple[bytes, float]]:
        self.calls.append(
            {
                "model_key": model_key,
                "q_sig": q_sig,
                "q_full": q_full,
                "k": k,
                "candidates": candidates,
            }
        )
        if self.raises is not None:
            raise self.raises
        found = self.hits
        if candidates is not None:
            found = [(digest, score) for digest, score in found if digest in candidates]
        return found[:k]


def _digest(n: int) -> bytes:
    """A 16-byte `segment.content_digest`, the only identifier that crosses the sidecar seam."""
    return bytes([n]) * 16


def _seed_segments(built: Built, *, members: dict[int, int] | None = None) -> None:
    """Two live segments over a document, plus one retired one, and their member blocks.

    `members` maps `segment_id` to a member count; the default gives segments 1 and 2 three blocks
    each and segment 3 -- the retired one -- one. Block ids are allocated in order, so
    `segment_block.ord` and reading order agree and a lift that ignored `ord` would still pass;
    the cap test below is where the order is made to matter.
    """
    counts = {1: 3, 2: 3, 3: 1} if members is None else members
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/segmented.pdf")
    conn.execute(
        "INSERT INTO segmenter(segmenter_id, driver_id, driver_schema_v, params_digest) "
        "VALUES(1, 'derive.segment.spine', 1, ?)",
        (DIGEST,),
    )
    block_id = 0
    for segment_id, count in counts.items():
        retired = segment_id == 3
        conn.execute(
            "INSERT INTO segment(segment_id, doc_ord, gen, ord, segmenter_id, layer, "
            "                    heading_path, n_blocks, n_tokens, n_chars, tokenizer_id, "
            "                    first_page, last_page, trust, quote_min, kind_mask, "
            "                    content_digest, origin_operator, origin_driver, "
            "                    driver_schema_v, state) "
            "VALUES(?, 1, 1, ?, 1, ?, '[]', ?, 1, 1, 'tok', 0, 0, 2, 4, 0, ?, "
            "       'op.segment', 'drv', 1, ?)",
            (
                segment_id,
                segment_id,
                _code(conn, "layer", "body"),
                count,
                _digest(segment_id),
                1 if retired else 0,
            ),
        )
        for ord_ in range(count):
            block_id += 1
            _block(
                conn,
                block_id=block_id,
                doc_ord=1,
                producer_id=producer_id,
                page=0,
                ord_=block_id,
                text=f"block {block_id}",
            )
            conn.execute(
                "INSERT INTO segment_block(block_id, segment_id, ord) VALUES(?, ?, ?)",
                (block_id, segment_id, ord_),
            )
    conn.execute("COMMIT")


def _seed_sidecar(
    built: Built,
    *,
    corpus_id: str | None = None,
    pushdown: bool = True,
    sig_bits: int = 768,
) -> pathlib.Path:
    """`index.vec.owstore` with a `vec_manifest`, and nothing else in it.

    The Channel reads the manifest and calls the backend; `vseg`, `vfull` and `vpending` are the
    backend's own tables and `vector.brute` is a separate cell, so the sidecar this fixture writes
    is exactly the part of 07 section 3.9 the `Reader` reads.

    `index_state.default_space_id` is written on the MAIN store at the same time, because
    `IndexCaps.channels` reports `semantic` only when the sidecar is attached AND there is a space
    to join through (07:3275) -- two halves of one fact, in two files, which is what makes the
    sidecar independently deletable.
    """
    built.writer.execute("INSERT OR REPLACE INTO index_state(k, v) VALUES('default_space_id', '1')")
    built.writer.commit()
    if corpus_id is None:
        row = built.writer.execute("SELECT v FROM index_state WHERE k = 'corpus_id'").fetchone()
        corpus_id = str(row[0]) if row is not None else ""
    path = built.path.with_name("index.vec.owstore")
    side = sqlite3.connect(path)
    side.execute("CREATE TABLE IF NOT EXISTS vec_manifest (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    side.executemany(
        "INSERT OR REPLACE INTO vec_manifest(k, v) VALUES(?, ?)",
        [
            ("corpus_id", corpus_id),
            ("schema", "1"),
            ("model_key", "bge-small/1"),
            ("backend", "vector.brute"),
            ("backend_version", "1"),
            ("storage", "sig_only"),
            ("sig_bits", str(sig_bits)),
            ("dim", "768"),
            ("built_at_ns", "1"),
            ("rows", "2"),
            ("pushdown", "1" if pushdown else "0"),
        ],
    )
    side.commit()
    side.close()
    return path


def _vec_reader(built: Built, path: pathlib.Path | None, backend: object | None) -> rd.SqliteReader:
    """A `Reader` whose connection already has the sidecar ATTACHed.

    The ATTACH happens BEFORE the `Reader` is constructed because the manifest is *"read once, at
    open"* (07:3272) and `caps_digest` memoises `plan()` -- a sidecar that appeared mid-`Reader`
    would make two `capabilities()` calls disagree about a store the plan was built against.
    """
    connection = ow.connect_readonly(built.path)
    if path is not None:
        connection.execute("ATTACH DATABASE ? AS vec", (str(path),))
    return rd.SqliteReader(connection, now_ns=NOW_NS, vectors=backend)  # type: ignore[arg-type]


def _semantic_spec(limit: int = 20, overfetch: int = 1, **bind: object) -> ChannelSpec:
    fields: dict[str, object] = {"q_sig": b"\x01" * 96}
    fields.update(bind)
    return ChannelSpec(
        name="semantic",
        budget_ms=80,
        limit=limit,
        overfetch=overfetch,
        weight=None,
        params={},
        bind=ChannelInput(**fields),  # type: ignore[arg-type]
    )


def test_a_segment_hit_yields_its_member_blocks_at_the_segments_own_rank(built: Built) -> None:
    """07:1511: *"A segment hit at rank *r* yields **its member blocks at rank *r***"*.

    That is what `rank_of` exists for (07:1243-1250): a positional rank would spread one segment's
    members over as many ranks as it has members and destroy the region-level signal the rule
    creates. Six blocks, two segments, two ranks.
    """
    _seed_segments(built)
    backend = FakeVectors([(_digest(1), 0.9), (_digest(2), 0.8)])
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        outcome = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    assert outcome.status == "ok"
    assert outcome.ranked == (1, 2, 3, 4, 5, 6)
    assert dict(outcome.rank_of) == {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2}
    assert outcome.degradations == ()


def test_the_lift_caps_at_sixty_four_members_and_records_that_it_did(built: Built) -> None:
    """07:1513-1517's cap, and the register row that stops it being silent.

    *"The cap is `SEM_BLOCKS_PER_SEGMENT = 64`, and because `MAX_SEGMENT_BLOCKS = 512`, the cap
    **can bite for up to 448 blocks of a large segment**."* The rule is *"the first 64 members in
    `segment_block.ord` order"*, so a 70-member segment yields members 0 to 63 and says so;
    without the record, *"up to 87% of a large table segment's citable cells are unreachable
    through it with nothing recording the fact"*.
    """
    _seed_segments(built, members={1: 70})
    backend = FakeVectors([(_digest(1), 0.9)])
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        outcome = reader.channel(state, _semantic_spec(limit=200), reader.narrow(state, Filters()))
    assert len(outcome.ranked) == 64
    assert outcome.ranked == tuple(range(1, 65))
    assert outcome.degradations == ("segment_lift_capped",)


def test_a_stale_digest_is_dropped_and_the_ranks_close_up_behind_it(built: Built) -> None:
    """07:1368-1372: the join back is *"the **only** exit from the `vec` sidecar (ST4), which is
    what makes a stale vector invisible rather than wrong"*.

    The sidecar is derived and the store is authoritative, so a digest the backend still holds and
    `segment` no longer does is the sidecar being out of date -- never the store being incomplete.
    Segment 3 is retired (`state = 1`) and segment 9 was never written at all; both are returned by
    the backend ahead of segment 2, and segment 2 still comes back at rank 1.
    """
    _seed_segments(built)
    backend = FakeVectors([(_digest(9), 1.0), (_digest(3), 0.95), (_digest(2), 0.8)])
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        outcome = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    assert outcome.ranked == (4, 5, 6)
    assert set(outcome.rank_of.values()) == {1}


def test_the_candidate_set_is_pushed_into_the_backend_before_ranking(built: Built) -> None:
    """Contract obligation (1) (07:104-107), from the caller's side.

    *"`candidates` narrows **before** ranking, tested at 0.01 selectivity. LEANN post-filters
    metadata after ANN retrieval with no over-fetch, which is silent recall loss that presents as
    absence."* The set is the live segment digests the narrowed set touches, and `k` is the
    Channel's plain limit: a backend that filters before ranking needs no over-fetch.
    """
    _seed_segments(built)
    backend = FakeVectors([(_digest(1), 0.9), (_digest(2), 0.8)])
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        reader.channel(state, _semantic_spec(limit=7), reader.narrow(state, Filters()))
    call = backend.calls[0]
    assert call["candidates"] == frozenset({_digest(1), _digest(2)})
    assert call["k"] == 7
    assert call["model_key"] == "bge-small/1"


def test_a_backend_that_cannot_push_down_gets_the_overfetch_clamp_and_says_so(
    built: Built,
) -> None:
    """`VecManifest.pushdown = False` is contract obligation (1) declined, and it is disclosed.

    07:3035 calls it *"not a failure; a disclosed mode change"*, and absence gate 11
    (`filter_starved`) reads the field by name (07:2191). So `candidates` goes as `None`, `k` is
    multiplied by the plan's over-fetch factor, and `pushdown_unavailable` -- row 18 of the closed
    twenty-seven -- rides back on the outcome.
    """
    _seed_segments(built)
    backend = FakeVectors([(_digest(1), 0.9)])
    reader = _vec_reader(built, _seed_sidecar(built, pushdown=False), backend)
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _semantic_spec(limit=5, overfetch=64),
            reader.narrow(state, Filters()),
        )
    call = backend.calls[0]
    assert call["candidates"] is None
    assert call["k"] == 5 * 64
    assert outcome.degradations == ("pushdown_unavailable",)
    assert reader.capabilities().vec_pushdown is False


def test_a_corrupt_sidecar_becomes_a_channel_status_and_never_an_exception(
    built: Built,
) -> None:
    """07:1373-1376: the ONE place a store-level exception becomes a Channel status.

    *"A `SQLITE_CORRUPT` or `SQLITE_NOTADB` raised while reading the sidecar is caught **at the
    Channel boundary only** and reported as `UNAVAILABLE(vec_unreadable)` ... and it is why the
    sidecar is deletable in the first place."* `unavailable` forces `degraded`; an
    `except: return []` would make a corrupt sidecar a confident zero, and 07:3189 gives the fix
    a caller can act on -- `rm index.vec.owstore`.
    """
    _seed_segments(built)
    backend = FakeVectors([], raises=sqlite3.DatabaseError("database disk image is malformed"))
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        outcome = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    assert outcome.status == "unavailable"
    assert outcome.reason == "vec_unreadable"


def test_a_sidecar_belonging_to_another_corpus_is_ignored_and_not_read(built: Built) -> None:
    """07:790 and 07:3190: a `corpus_id` mismatch means the sidecar is *"IGNORED, not read"*.

    Not an error, not a partial read, not a rebuild -- the vectors are derived and the store is
    authoritative. `IndexCaps` reports it the same way it reports a store with no sidecar at all,
    and absence gate 13 (`space_mismatch`) is what makes the difference visible to a caller; the
    Channel's reason names both corpus ids so the fix is obvious.
    """
    _seed_segments(built)
    backend = FakeVectors([(_digest(1), 0.9)])
    reader = _vec_reader(built, _seed_sidecar(built, corpus_id="another-corpus"), backend)
    caps = reader.capabilities()
    with reader.snapshot() as state:
        outcome = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    assert outcome.status == "unavailable"
    assert "ignored and not read" in outcome.reason
    assert caps.vec_backend is None
    assert "semantic" not in caps.channels
    assert backend.calls == []


def test_the_manifest_fills_the_two_index_caps_fields_it_owns(built: Built) -> None:
    """07:3339-3348's `VecManifest` read at attach, and 07:3272's *"read once, at open"*.

    P2 left `vec_backend` and `vec_pushdown` at `None` and `False` with the read owed to whatever
    ATTACHes the sidecar. This is that read, and `caps_digest` moves with it because the two
    fields are inside the digest that memoises `plan()`.
    """
    _seed_segments(built)
    bare = _reader(built).capabilities()
    reader = _vec_reader(built, _seed_sidecar(built), FakeVectors([]))
    caps = reader.capabilities()
    assert caps.vec_backend == "vector.brute"
    assert caps.vec_pushdown is True
    assert caps.vec_ceiling == 250_000
    assert "semantic" in caps.channels
    assert caps.caps_digest != bare.caps_digest


def test_the_semantic_channel_names_which_of_the_three_pieces_is_missing(built: Built) -> None:
    """Three refusals, three different fixes, and none of them is `empty`.

    `empty` would say the backend ran and matched nothing, which is a claim about the corpus.
    These three are claims about the configuration: no backend selected, no sidecar attached, and
    a query that never reached phase 2 -- which *"embeds before the snapshot"* (07:1364, ST22)
    precisely because a Driver call inside a held read transaction pins the WAL.
    """
    _seed_segments(built)
    reader = _vec_reader(built, None, None)
    with reader.snapshot() as state:
        no_backend = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    reader = _vec_reader(built, None, FakeVectors([]))
    with reader.snapshot() as state:
        no_sidecar = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    reader = _vec_reader(built, _seed_sidecar(built), FakeVectors([]))
    with reader.snapshot() as state:
        no_embedding = reader.channel(
            state,
            ChannelSpec(
                name="semantic",
                budget_ms=80,
                limit=20,
                overfetch=1,
                weight=None,
                params={},
                bind=ChannelInput(),
            ),
            reader.narrow(state, Filters()),
        )
    assert no_backend.status == "unavailable"
    assert "no VectorBackend was selected" in no_backend.reason
    assert no_sidecar.status == "unavailable"
    assert "no vec sidecar is attached" in no_sidecar.reason
    assert no_embedding.status == "unavailable"
    assert "phase 2" in no_embedding.reason


def test_a_synopsis_segment_lifts_its_own_blocks_and_never_the_ones_it_summarises(
    built: Built,
) -> None:
    """07:1523-1525, and the rule is honoured by NOT following an edge.

    *"a semantic hit whose segment is a table synopsis (`segment.synopsis_of IS NOT NULL`) lifts to
    the synopsis segment's own blocks and never to the 4M cells it summarises. The synopsis is what
    was embedded; pretending otherwise would make a cosine hit on eight sampled rows into a claim
    about the whole sheet."* The lift reads `segment_block` for the hit segment and follows no
    `synopsis_of`, so the way to break this is to add a helpful join -- which is why the test names
    the column it must not be joined through.
    """
    _seed_segments(built)
    built.writer.execute("UPDATE segment SET synopsis_of = 4 WHERE segment_id = 1")
    built.writer.commit()
    backend = FakeVectors([(_digest(1), 0.9)])
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        outcome = reader.channel(state, _semantic_spec(), reader.narrow(state, Filters()))
    assert outcome.ranked == (1, 2, 3)
    assert 4 not in outcome.ranked


def test_the_semantic_channel_scores_only_within_the_narrowed_set(built: Built) -> None:
    """07:1561: filters narrow, Channels score within the narrowed set -- the lift included.

    The cap is applied AFTER this join and not before, so a filter that happens to exclude a
        segment's first 64 members cannot turn a ranked segment into zero blocks while its rank
    still stands. Here the filter excludes two of segment 1's three members and the segment
    still ranks, with the one member that survived.
    """
    _seed_segments(built)
    built.writer.execute(
        "UPDATE block SET kind = ? WHERE block_id IN (1, 2)",
        (_code(built.writer, "kind", "heading"),),
    )
    built.writer.commit()
    backend = FakeVectors([(_digest(1), 0.9)])
    reader = _vec_reader(built, _seed_sidecar(built), backend)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters(kinds=frozenset({Kind.PARAGRAPH})))
        outcome = reader.channel(state, _semantic_spec(), narrowing)
    assert narrowing.kind == "set"
    assert outcome.ranked == (3,)
    assert dict(outcome.rank_of) == {3: 1}


def test_rank_of_is_empty_for_every_channel_but_semantic(built: Built) -> None:
    """07:1249: *"it is empty for every Channel but `semantic`"*, and `fuse()` depends on it.

    `fuse()` reads `c.rank_of.get(b) or (position of b in c.ranked) + 1` (07:1249-1250), so an
    empty mapping is the instruction to use the positional rank. A Channel that filled it with the
    positions would be saying the same thing twice and would break the moment one of them moved.
    """
    _seed_links(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, Filters())
        for spec in (
            _identity_spec(idents=("d1#1",)),
            _lexical_spec(terms=("block",)),
            _structural_spec(seeds=(1,), expand=_expand()),
        ):
            assert reader.channel(state, spec, narrowing).rank_of == {}


def test_a_rank_for_a_block_the_channel_did_not_rank_is_refused() -> None:
    """`rank_of` is the authoritative rank PER RANKED BLOCK (07:1248), not a second result set."""
    with pytest.raises(ValueError, match="gave ranks to blocks it did not rank"):
        rd.ChannelOutcome(name="semantic", status="ok", ranked=(1,), rank_of={2: 1})


def test_a_rank_below_one_is_refused_because_fuse_reads_it_as_absent() -> None:
    """07:1249-1250: `fuse()` reads `c.rank_of.get(b) or (position + 1)`, so 0 is a falsy sentinel
    AND an illegal 1-based rank -- a Channel reporting it would silently get the positional rank
    instead of the one it meant."""
    with pytest.raises(ValueError, match="rank below 1"):
        rd.ChannelOutcome(name="semantic", status="ok", ranked=(1,), rank_of={1: 0})


def test_attach_vec_answers_false_for_a_sidecar_that_is_not_there(built: Built) -> None:
    """The sidecar is *"[DER] Optional. Deletable."* (07:789), so its absence is the shipped
    default's ordinary state and not a condition anything should have to catch."""
    connection = ow.connect_readonly(built.path)
    assert ow.attach_vec(connection, vec.vec_path(built.path)) is False
    assert ow.attach_vec(connection, _seed_sidecar(built)) is True
    assert [row[1] for row in connection.execute("PRAGMA database_list")] == ["main", "vec"]


def test_the_stdlib_backend_drives_the_semantic_channel_end_to_end(built: Built) -> None:
    """W6.2's ten-ew row, closed: a real sidecar, a real signature scan, and the real lift.

    Every other semantic test above uses `FakeVectors`, because the seam is the Protocol and the
    two halves are separately testable. This one is the join: `vector.brute` scans `vseg` with
    07:812's XOR and `bit_count`, `SqliteReader` joins the digests it returns back to live segments
    inside the snapshot -- *"the **only** exit from the `vec` sidecar (ST4)"* (07:1372) -- and the
    lift gives each segment's members the segment's own rank.

    Signature `0xFF` for segment 1 and `0x0F` for segment 2 puts them four bits apart against a
    `0xFF` query, so the scan orders them and the six blocks arrive at two ranks.
    """
    _seed_segments(built)
    path = _seed_sidecar(built, sig_bits=8)
    writer = ow.connect(built.path)
    try:
        assert ow.attach_vec(writer, path, readonly=False) is True
        for statement in vec.SIDECAR_DDL:
            writer.execute(statement)
        vec.BruteVectors(writer).upsert(
            "bge-small/1",
            [(_digest(1), b"\xff", None), (_digest(2), b"\x0f", None)],
        )
        writer.commit()
    finally:
        writer.close()

    connection = ow.connect_readonly(built.path)
    assert ow.attach_vec(connection, path) is True
    reader = rd.SqliteReader(connection, now_ns=NOW_NS, vectors=vec.BruteVectors(connection))
    with reader.snapshot() as state:
        outcome = reader.channel(
            state,
            _semantic_spec(q_sig=b"\xff"),
            reader.narrow(state, Filters()),
        )
    assert reader.capabilities().vec_backend == "vector.brute"
    assert outcome.status == "ok"
    assert outcome.ranked == (1, 2, 3, 4, 5, 6)
    assert dict(outcome.rank_of) == {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2}


# ---------------------------------------------------------------------------------------------
# 5. hydrate
# ---------------------------------------------------------------------------------------------


def test_hydrate_returns_the_columns_the_plan_selects_with_the_enums_decoded(
    built: Built,
) -> None:
    """07:2312-2321, including the two columns that are not `Hit` fields.

    `method` and `chars` are *"selected EVEN WHEN `PackSpec.hydrate_text` is `False`"* (07:2329)
    because `Verdict.generated_share` and `RenderedBlock.method` read them, and `d.achieved` rides
    along so `byte_exact` is not an N+1 (07:2322).
    """
    _seed_one_block(built, text="hello world")
    reader = _reader(built)
    with reader.snapshot() as state:
        rows = reader.hydrate(state, [1])
    assert len(rows) == 1
    row = rows[0]
    assert row.block_id == 1
    assert row.cite == "d1#1"
    assert row.addr == "p0/0"
    assert row.text == "hello world"
    assert row.chars == 11
    assert row.kind is Kind.PARAGRAPH
    assert row.layer is Layer.BODY
    assert row.method is Method.NATIVE
    assert row.trust is Trust.EXTRACTED
    assert row.quote is Quote.VERBATIM
    assert row.uri == "file:///corpus/a.pdf"
    assert row.achieved == "{}"
    assert row.segment_id is None
    assert rows.dropped == 0


def test_hydrate_returns_rows_in_the_callers_order_and_counts_what_it_could_not_find(
    built: Built,
) -> None:
    """The ids are a fused RANKING, so `block_id` order would silently replace it.

    07:2323-2324: a row failing the `gen`/`state` predicate is *"dropped and counted"*, and the
    count is what gate 3 reads as corroboration that the store advanced mid-query. Here the drops
    are a tombstone and an id that never existed -- one fact from the caller's side.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf")
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id, ord_=0)
    _block(conn, block_id=2, doc_ord=1, producer_id=producer_id, ord_=1)
    _block(conn, block_id=3, doc_ord=1, producer_id=producer_id, ord_=2, state=1)
    conn.execute("COMMIT")
    reader = _reader(built)
    with reader.snapshot() as state:
        rows = reader.hydrate(state, [2, 1, 3, 999, 2])
    assert [row.block_id for row in rows] == [2, 1]
    assert rows.dropped == 2
    assert isinstance(rows, tuple)


def test_hydrate_batches_at_512_and_returns_every_row(built: Built) -> None:
    """07:2310: *"one statement per batch of up to 512 ids"*, and the batching must not lose rows.

    600 ids is two batches, and the second one is what a `range(0, n, 512)` off-by-one drops.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf")
    for block_id in range(1, 601):
        _block(conn, block_id=block_id, doc_ord=1, producer_id=producer_id, ord_=block_id)
    conn.execute("COMMIT")
    reader = _reader(built)
    wanted = list(range(600, 0, -1))
    with reader.snapshot() as state:
        rows = reader.hydrate(state, wanted)
    assert [row.block_id for row in rows] == wanted
    assert rows.dropped == 0


def test_hydration_inside_one_snapshot_is_generation_consistent(built: Built) -> None:
    """ST2 (07:2758-2763) asserted in BOTH directions, which is what makes either half evidence.

    A re-index committed between two hydrations of one snapshot must be invisible to that snapshot
    AND visible to the next one. Asserting only the first half passes just as well against a reader
    that never saw the commit at all, or one pointed at the wrong file --
    `test_store_integration.py`'s own rule, applied here.

    07:2334-2340 is why this matters for `text` specifically: reading it after the transaction
    closes would let *"a committed re-index hand it text from a different generation than the one
    that was ranked and scored"*, with gate 3 detecting the generation change only after the
    evidence was already wrong.
    """
    _seed_one_block(built, text="original")
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.hydrate(state, [1])[0].text == "original"
        built.writer.execute("BEGIN IMMEDIATE")
        built.writer.execute("UPDATE block SET text = 'reindexed' WHERE block_id = 1")
        built.writer.execute("UPDATE index_state SET v = '1' WHERE k = 'generation'")
        built.writer.execute("COMMIT")
        assert reader.hydrate(state, [1])[0].text == "original"
        assert state.generation == 0
    with reader.snapshot() as after:
        assert reader.hydrate(after, [1])[0].text == "reindexed"
        assert after.generation == 1


def test_a_generation_advance_mid_snapshot_is_invisible_to_the_narrowing_too(
    built: Built,
) -> None:
    """The same isolation, one method over: a Channel and its narrowing share one read view."""
    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        assert reader.narrow(state, Filters()).n == 1
        conn = built.writer
        conn.execute("BEGIN IMMEDIATE")
        producer_id = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
        _block(conn, block_id=2, doc_ord=1, producer_id=producer_id, ord_=1)
        conn.execute("COMMIT")
        assert reader.narrow(state, Filters()).n == 1
    with reader.snapshot() as after:
        assert reader.narrow(after, Filters()).n == 2


# ---------------------------------------------------------------------------------------------
# 6. coverage
# ---------------------------------------------------------------------------------------------


def test_no_ingest_scope_row_is_coverage_unknown_and_never_a_clean_bill_of_health(
    built: Built,
) -> None:
    """07:695 and 07:3335: *"AN ABSENT ROW MEANS 'COVERAGE UNKNOWN', NEVER 'NOTHING WAS EXCLUDED'."*

    `scope_rows == 0` is gate 4's input (07:2184), and `complete` must be `False` alongside it: a
    vacuous `all()` over zero rows is `True`, and that is precisely the confident zero the field
    exists to prevent.
    """
    _seed_one_block(built)
    reader = _reader(built)
    with reader.snapshot() as state:
        coverage = reader.coverage(state, Filters())
    assert coverage.scope_rows == 0
    assert coverage.complete is False
    assert coverage.discovered == 0
    assert coverage.indexed == 0
    assert coverage.gaps == ()


def _scope(
    built: Built,
    scope_id: str,
    *,
    discovered: int,
    indexed: int,
    skipped: int = 0,
    complete: int = 1,
) -> None:
    built.writer.execute(
        "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, complete) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (scope_id, discovered, indexed, skipped, NOW_NS, complete),
    )
    built.writer.commit()


def test_coverage_sums_the_scope_rows_and_counts_document_status_beside_them(
    built: Built,
) -> None:
    """The counts gate 4 reads, from the two tables that hold them.

    `discovered`, `indexed`, `skipped` and `complete` are `ingest_scope` columns of those names
    (07:686-691); `partial` and `failed` have no `ingest_scope` column and come from `doc.status`,
    which is reader.py's DEFECT 4 and the ruling it records.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    producer_id = _producer(conn)
    _doc(conn, 1, uri="file:///corpus/a.pdf", status="ok")
    _doc(conn, 2, uri="file:///corpus/b.pdf", status="partial")
    _doc(conn, 3, uri="file:///corpus/c.pdf", status="failed")
    _block(conn, block_id=1, doc_ord=1, producer_id=producer_id)
    conn.execute("COMMIT")
    _scope(built, "file:///corpus/", discovered=5, indexed=3, skipped=1, complete=0)

    reader = _reader(built)
    with reader.snapshot() as state:
        coverage = reader.coverage(state, Filters())
    assert coverage.scope_rows == 1
    assert (coverage.discovered, coverage.indexed, coverage.skipped) == (5, 3, 1)
    assert coverage.complete is False
    assert (coverage.partial, coverage.failed) == (1, 1)


def test_a_query_scoped_to_documents_reads_only_the_scope_rows_containing_them(
    built: Built,
) -> None:
    """07:706-708, and the containment test is 07:704's `doc.uri GLOB scope_id || '*'`.

    *"A query whose `Filters` name no document scope reads EVERY scope row; a query scoped to
    documents reads the scope rows containing them."* There is no `doc.scope_id` column and there
    must not be one, *"because a document can be reached by two scans"* (07:700-703).
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    _doc(conn, 1, uri="file:///alpha/a.pdf")
    _doc(conn, 2, uri="file:///beta/b.pdf")
    conn.execute("COMMIT")
    _scope(built, "file:///alpha/", discovered=1, indexed=1)
    _scope(built, "file:///beta/", discovered=9, indexed=2, complete=0)

    reader = _reader(built)
    with reader.snapshot() as state:
        everything = reader.coverage(state, Filters())
        alpha = reader.coverage(state, Filters(uri_prefix="file:///alpha/"))
        beta = reader.coverage(state, Filters(doc_keys=frozenset({bytes([2]) * 16})))
    assert everything.scope_rows == 2
    assert everything.discovered == 10
    assert alpha.scope_rows == 1
    assert (alpha.discovered, alpha.indexed, alpha.complete) == (1, 1, True)
    assert beta.scope_rows == 1
    assert (beta.discovered, beta.indexed, beta.complete) == (9, 2, False)


def test_a_job_document_never_pulls_a_scope_row_into_view_or_a_status_into_the_counts(
    built: Built,
) -> None:
    """07:757 lists absence gate 4's scope roll-up among `NO_JOB_DOCS`'s exhaustive sites.

    *"Vacuous in practice -- `ow-job://` matches no enumerated scope prefix -- and the predicate is
    still written, because 'vacuous today' is how a silent miscount arrives."* The fixture makes it
    non-vacuous by giving the job document a URI under the scanned scope, which is the shape the
    predicate defends against.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    _doc(conn, 1, uri="file:///corpus/a.pdf", status="ok")
    _doc(conn, 2, uri="file:///corpus/job", status="failed", fmt="owjob")
    conn.execute("COMMIT")
    _scope(built, "file:///corpus/", discovered=1, indexed=1)

    reader = _reader(built)
    with reader.snapshot() as state:
        coverage = reader.coverage(state, Filters(uri_prefix="file:///corpus/"))
    assert coverage.scope_rows == 1
    assert coverage.failed == 0


def test_coverage_counts_the_queue_and_the_unit_roster(built: Built) -> None:
    """Gates 5 and 8 read these, and P2 creates both tables and leaves them empty.

    07:2185 fixes `pending_work` as `work.status IN ('pending','claimed')`; 07:2229 gives gate 8's
    case -- *"a unit whose path is removed after `ingest_scope` was written"* -- which is
    `unit.state = 'failed'`. `stale_units` is `unit.stale_since IS NOT NULL`, the column the
    `unit_stale` partial index exists to serve.
    """
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    for uri, state, stale in (
        ("file:///corpus/a.pdf", "planned", None),
        ("file:///corpus/b.pdf", "failed", None),
        ("file:///other/c.pdf", "discovered", NOW_NS),
    ):
        conn.execute(
            "INSERT INTO unit(unit_uri, state, last_seen_gen, trust_class, stale_since) "
            "VALUES(?, ?, 1, 'internal', ?)",
            (uri, state, stale),
        )
    for row_id, uri, operator, status in (
        (1, "file:///corpus/a.pdf", "op.identify", "pending"),
        (2, "file:///corpus/a.pdf", "op.converge", "done"),
        (3, "file:///other/c.pdf", "op.identify", "claimed"),
    ):
        conn.execute(
            "INSERT INTO work(id, unit_uri, operator, op_version, cache_key, cost_class, status) "
            "VALUES(?, ?, ?, 1, 'k', 'free', ?)",
            (row_id, uri, operator, status),
        )
    conn.execute("COMMIT")

    reader = _reader(built)
    with reader.snapshot() as state:
        everything = reader.coverage(state, Filters())
        corpus = reader.coverage(state, Filters(uri_prefix="file:///corpus/"))
    assert (everything.pending_work, everything.stale_units, everything.unreadable_units) == (
        2,
        1,
        1,
    )
    assert (corpus.pending_work, corpus.stale_units, corpus.unreadable_units) == (1, 0, 1)


def test_a_unit_rostered_and_not_indexed_is_pending_work_with_or_without_a_work_row(
    built: Built,
) -> None:
    """D567, the user's decision in W7.3w. With work rows alone, 200 rostered and never-parsed
    files fired none of the fifteen gates and `ow_query` answered `absent`: a unit is a hole from
    first sight, and in this build its only work row -- `op.identify` -- is `done`.

    A unit with a live row is counted once, by the row; `settled` and `out_of_scope` are not holes
    and `failed` is gate 8's."""
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    for uri, state in (
        ("file:///corpus/rostered.pdf", "discovered"),
        ("file:///corpus/identified.pdf", "identified"),
        ("file:///corpus/queued.pdf", "planned"),
        ("file:///corpus/done.pdf", "settled"),
        ("file:///corpus/gone.pdf", "out_of_scope"),
        ("file:///corpus/broken.pdf", "failed"),
    ):
        conn.execute(
            "INSERT INTO unit(unit_uri, state, last_seen_gen, trust_class) "
            "VALUES(?, ?, 1, 'internal')",
            (uri, state),
        )
    for row_id, uri, status in (
        (1, "file:///corpus/identified.pdf", "done"),
        (2, "file:///corpus/queued.pdf", "pending"),
    ):
        conn.execute(
            "INSERT INTO work(id, unit_uri, operator, op_version, cache_key, cost_class, status) "
            "VALUES(?, ?, 'op.identify', 1, 'k', 'free', ?)",
            (row_id, uri, status),
        )
    conn.execute("COMMIT")
    reader = _reader(built)
    with reader.snapshot() as state:
        coverage = reader.coverage(state, Filters())
    assert coverage.pending_work == 3, "rostered + identified by state, queued by its row"
    assert rd.IN_FLIGHT_UNIT_STATES == (
        "discovered", "acquiring", "acquired", "identified", "planned", "running",
    )  # fmt: skip


# ---------------------------------------------------------------------------------------------
# The Snapshot guard, across every method that takes one
# ---------------------------------------------------------------------------------------------


def _every_snapshot_method(reader: rd.SqliteReader, state: object) -> list[tuple[str, object]]:
    spec = ChannelSpec(name="exact", budget_ms=25, limit=20, overfetch=1, weight=None, params={})
    narrowing = rd.Narrowing(kind="all", table=None, n=0)
    return [
        ("narrow", lambda: reader.narrow(state, Filters())),  # type: ignore[arg-type]
        ("channel", lambda: reader.channel(state, spec, narrowing)),  # type: ignore[arg-type]
        ("hydrate", lambda: reader.hydrate(state, [1])),  # type: ignore[arg-type]
        ("coverage", lambda: reader.coverage(state, Filters())),  # type: ignore[arg-type]
    ]


def test_every_method_refuses_a_snapshot_issued_by_another_store(
    built: Built, tmp_path: Path
) -> None:
    """A token from another store must RAISE rather than silently read the wrong file.

    `Snapshot.token` is typed `object` so a Postgres backend can construct one (07:72-78), which
    means the type system cannot stop this: threading store A's `Snapshot` through store B's
    `Reader` would answer B's data under A's `generation` and `corpus_id`, and every consistency
    fact carried on the response (07:2896-2905) would describe the wrong store.
    """
    other_path = tmp_path / "other.owstore"
    other_writer = ow.connect(other_path)
    try:
        migrate.apply_pending(other_writer, now_ns=NOW_NS)
        other = rd.SqliteReader(ow.connect_readonly(other_path), now_ns=NOW_NS)
        mine = _reader(built)
        with other.snapshot() as foreign:
            for name, call in _every_snapshot_method(mine, foreign):
                with pytest.raises(StoreError, match="issued by another Reader"):
                    call()  # type: ignore[operator]
                assert name
    finally:
        other_writer.close()


def test_every_method_refuses_a_snapshot_that_has_closed(built: Built) -> None:
    """A `Snapshot` is a Python object that outlives its transaction; a read through it must not."""
    reader = _reader(built)
    with reader.snapshot() as state:
        pass
    for name, call in _every_snapshot_method(reader, state):
        with pytest.raises(StoreError, match="this Snapshot has closed"):
            call()  # type: ignore[operator]
        assert name


def test_every_method_refuses_something_that_is_not_a_snapshot_at_all(built: Built) -> None:
    """`capabilities()` is the one method that takes none (07:3272); the other five require one."""
    reader = _reader(built)
    for name, call in _every_snapshot_method(reader, object()):
        with pytest.raises(StoreError, match="is not a Snapshot"):
            call()  # type: ignore[operator]
        assert name


# ---------------------------------------------------------------------------------------------
# 4f. Above `PREFILTER_MAX`: the filter is a predicate, and `_within` is who applies it
# ---------------------------------------------------------------------------------------------


def _notice(filters: Filters | None = None) -> ChannelSpec:
    """The lexical spec of the three `notice` blocks, bound with the filters or without them."""
    return _lexical_spec(terms=("notice",), filters=filters)


def test_above_the_cap_the_filter_is_applied_to_what_the_channel_ranked(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """07:1671's post-filter, against the case that MEASURED wrong before it existed.

    `_seed_lexical` puts `notice` on block 11 (page 1), block 21 (page 2) and block 30 (page 3).
    Under `Filters(pages=range(1, 2))` the exact narrowing keeps block 11 alone. Above the cap
    there is no `tmp_narrow` to join, so the Channel ranks all three -- and before
    `ChannelInput.filters` this method returned `(21, 30, 11)`, which is two pages the query
    excluded, with `status="ok"` and nothing disclosed. D262.
    """
    _seed_lexical(built)
    keep = Filters(pages=range(1, 2))
    reader = _reader(built)
    with reader.snapshot() as state:
        exact = reader.channel(state, _notice(filters=keep), reader.narrow(state, keep))
    monkeypatch.setattr(rd, "PREFILTER_MAX", 1)
    capped = _reader(built)
    with capped.snapshot() as state:
        proof = capped.narrow(state, keep)
        outcome = capped.channel(state, _notice(filters=keep), proof)
    assert exact.ranked == (11,)
    assert proof.kind == "all"
    assert outcome.status == "ok"
    assert outcome.ranked == (11,)


def test_a_channel_bound_no_filters_will_not_answer_above_the_cap(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ChannelInput.filters = None` means NOT BOUND, never "no filter" -- the ST5 asymmetry.

    `unavailable` forces `degraded` (07:1208), which is the honest price of a caller that skipped
    the bind. An `ok` over the unfiltered ranking would be the jcodemunch failure in its original
    direction: a Channel whose gate went missing, answering confidently.
    """
    _seed_lexical(built)
    monkeypatch.setattr(rd, "PREFILTER_MAX", 1)
    reader = _reader(built)
    with reader.snapshot() as state:
        proof = reader.narrow(state, Filters(pages=range(1, 2)))
        outcome = reader.channel(state, _notice(), proof)
    assert proof.kind == "all"
    assert outcome.status == "unavailable"
    assert "post-filter" in outcome.reason


def test_a_filter_that_excludes_every_ranked_block_is_empty_and_not_a_short_ok(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Filters(kinds={HEADING})` matches the two headings and none of the three `notice` bodies.

    `empty` and not `ok` with an empty tuple: 07:1670-1680 is about exactly this difference, and
    `ChannelOutcome` requires a reason for every status that is not `ok`.
    """
    _seed_lexical(built)
    monkeypatch.setattr(rd, "PREFILTER_MAX", 1)
    headings = Filters(kinds=frozenset({Kind.HEADING}))
    reader = _reader(built)
    with reader.snapshot() as state:
        proof = reader.narrow(state, headings)
        outcome = reader.channel(state, _notice(filters=headings), proof)
    assert proof.kind == "all"
    assert outcome.status == "empty"
    assert outcome.ranked == ()
    assert "outside the filter" in outcome.reason


def test_below_the_cap_the_post_filter_does_not_run_at_all(built: Built) -> None:
    """A `kind="set"` narrowing was already joined inside the Channel's own statement.

    Binding the filters as well must change nothing -- a second application of one predicate is
    the drift 13:1072 names, and the assertion is that the two outcomes are identical objects by
    value rather than merely similar.
    """
    _seed_lexical(built)
    keep = Filters(pages=range(1, 2))
    reader = _reader(built)
    with reader.snapshot() as state:
        narrowing = reader.narrow(state, keep)
        bound = reader.channel(state, _notice(filters=keep), narrowing)
        unbound = reader.channel(state, _notice(), narrowing)
    assert narrowing.kind == "set"
    assert bound == unbound
    assert bound.ranked == (11,)


def test_the_post_filter_shrinks_the_grades_with_the_ranking(
    built: Built, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything a `ChannelOutcome` keys by `block_id` shrinks in one step.

    The constructor refuses a `grades` key that is not in `ranked`, so a post-filter that dropped
    a block and kept its grade would raise rather than mislead -- but it would raise inside a
    query, which is why the filtering is one comprehension over all three mappings.
    """
    _seed_identity(built)
    monkeypatch.setattr(rd, "PREFILTER_MAX", 1)
    keep = Filters(pages=range(1, 3))
    reader = _reader(built)
    with reader.snapshot() as state:
        proof = reader.narrow(state, keep)
        outcome = reader.channel(state, _identity_spec(idents=("Table 3.2",), filters=keep), proof)
    assert proof.kind == "all"
    assert 45 not in outcome.ranked
    assert set(outcome.grades) == set(outcome.ranked)
    assert set(outcome.ranked) == {30, 40}
