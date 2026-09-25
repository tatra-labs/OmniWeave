"""The streaming roster, the cursor, and the four statements that move `unit.state`.

Three things in this file are transcriptions rather than inventions:

* `unit.state`'s CHECK vocabulary is read out of `0004_runtime.sql` and every state this module
  names is checked against it, because a state that is not in the CHECK is an `IntegrityError` a
  thousand rows into a corpus.
* `unit.acq_failure_class`'s fifteen values are rebuilt from `FailureClass` plus the two strings
  `05:370` and `05:375` write, which is D80's open question answered in code.
* `plan.discover`, `plan.pause` and `plan.resume`'s field lists come from `tools/events.toml`, so
  the emitted maps are the declared ones rather than three plausible ones.

## The tests that are defect reports

`test_the_roster_names_no_cas_blob_and_the_unit_table_has_no_column_for_one` reads the `unit` DDL
and shows there is no column any CAS reference could land in, which is why `08:861` wins over
`02:472`'s hop 3. **D165**.

`test_an_oversize_candidate_is_counted_and_never_rostered` shows the row `05:227` asks for -- a
`unit` in `failed` with `acq_failure_class = 'too_large'` -- does not exist, because the walk
refuses before the roster write and a candidate has no `unit_uri` to fail. **D168**.

`test_a_second_process_cannot_claim_an_acquiring_unit_and_no_lease_says_when_it_may` runs two
claims against a real store and then shows the `unit` table has no column `05:400` rule 6's
"unexpired lease" could be read from. **D163**.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import omniweave_core.store.sqlite as ow
import pytest
from omniweave.run import discover as discover_module
from omniweave.run.discover import (
    ACQ_FAILED_SQL,
    ACQ_FAILURE_CLASSES,
    ACQUIRED,
    ACQUIRED_SQL,
    ACQUIRING,
    ACQUIRING_STALE_MS,
    CLAIM_ACQUIRING_SQL,
    FAILED,
    FILTERED,
    MARK_STALE_SQL,
    OUT_OF_SCOPE,
    OUT_OF_SCOPE_SQL,
    PENDING_ACQUISITION_SQL,
    RAW_DIGEST_CODE,
    RESET_ACQUIRING_SQL,
    SKIP_REASON_CLASSES,
    STALE_SCAN_SQL,
    UNCHANGED_SQL,
    UNSEEN,
    WALKED_PATH_KEY,
    Acquired,
    AcquirePass,
    Backpressure,
    RosterFeed,
    StoredStat,
    acq_retryable,
    acquire_pending,
    acquire_unit,
    content_digest,
    discover,
    freshness,
    mark_stale,
    observe,
    pending_params,
    raw,
    reset_stale_acquiring,
    roster_rows,
    stale_params,
    sweep_unseen,
    walked_path,
)
from omniweave_core.acquire import (
    UNIT_UPSERT_SQL,
    IngestGuards,
    RosterRow,
    Scope,
    StatTriple,
    Tally,
    TrustClass,
    scope_id_for,
)
from omniweave_core.cache import unit_salt
from omniweave_core.errors import RouteError
from omniweave_core.events import EVENTS, EventKind
from omniweave_core.store import migrate
from omniweave_ports.types import DriverError, FailureClass

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from conftest import PlanDocs


# ---------------------------------------------------------------------------------------------
# Fixtures and doubles
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ow.StoreThread]:
    """A real migrated store on a real `StoreThread`, pinned so two fixtures write equal rows."""
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1_700_000_000_000_000_000)
    finally:
        connection.close()
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        yield thread


def _reader(tmp_path: Path) -> Any:
    """A second connection for reading back what the store thread committed.

    `Any` for `test_run_manifest.py`'s reason: it is a `sqlite3.Connection` and TID251 bans naming
    that module here, and a ban a type annotation could step around would not be one.
    """
    return ow.connect(tmp_path / "index.owstore")


@dataclass
class RecordingThread:
    """A `StoreThread` stand-in that records one entry per submitted transaction.

    `write_roster`'s and `enqueue`'s contracts are about transaction *boundaries*, and a real store
    lets those pass unobserved. The same double `test_acquire.py` uses, kept local rather than
    imported: a shared test helper across two distributions' test trees would be a third place the
    store boundary is described.
    """

    batches: list[int] = field(default_factory=list)

    def run(self, unit: object, *, timeout_s: float | None = None) -> object:
        del timeout_s
        statements: list[tuple[str, int]] = []

        class _Cursor:
            rowcount = 0

        class _Conn:
            def execute(self, sql: str, parameters: object = (), /) -> object:
                del parameters
                statements.append((sql, 1))
                return _Cursor()

            def executemany(self, sql: str, parameters: Sequence[object], /) -> object:
                statements.append((sql, len(list(parameters))))
                return _Cursor()

        unit.run(_Conn())  # type: ignore[attr-defined] -- the double's whole job.
        self.batches.append(sum(count for sql, count in statements if "INSERT INTO unit" in sql))
        return None


def _tree(root: Path, count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (root / f"doc{i:04d}.txt").write_bytes(b"x" * (i + 1))


def _row(unit_uri: str, *, cursor: str | None = None, gen: int = 1) -> RosterRow:
    return RosterRow(
        unit_uri=unit_uri,
        cursor=cursor,
        stat=StatTriple(size=1, mtime_ns=2, indexed_at_ns=3),
        trust_class=TrustClass.INTERNAL,
        last_seen_gen=gen,
    )


# ---------------------------------------------------------------------------------------------
# 1. `RosterFeed`: the pause boundary and the cursor
# ---------------------------------------------------------------------------------------------


def test_the_feed_evaluates_the_pause_only_at_a_full_batch() -> None:
    """08:880: the generator is *not pulled* -- and the boundary is a committed transaction."""
    asked: list[int] = []
    seen = 0

    def pause() -> bool:
        nonlocal seen
        seen += 1
        asked.append(seen)
        return False

    feed = RosterFeed((_row(f"c:/x/{i}") for i in range(10)), pause=pause, plan_batch=4)
    rows = list(feed)
    assert len(rows) == 10
    # Ten rows at four per batch: boundaries after row 4 and row 8, and none for the open tail.
    assert feed.boundaries == 2
    assert asked == [1, 2]


def test_the_kept_cursor_is_the_last_committed_record_and_never_a_buffered_one() -> None:
    """05:427: *"keeps the last committed record's `next_cursor`"*.

    The difference is a whole batch. Rows 5 and 6 are yielded into an open transaction when the
    pause fires at the boundary after row 4; a feed that kept the last *yielded* cursor would
    resume from row 6 and skip two documents that were never committed.
    """
    fired = iter([False, True, True])
    feed = RosterFeed(
        (_row(f"c:/x/{i}", cursor=f"cur-{i}") for i in range(12)),
        pause=lambda: next(fired),
        plan_batch=4,
    )
    rows = list(feed)
    assert feed.paused is True
    assert len(rows) == 8, "the feed stops at the boundary after the batch that triggered it"
    assert feed.committed_cursor == "cur-7"


def test_a_feed_that_never_reaches_a_boundary_has_no_cursor_to_resume_from() -> None:
    """`None` is honest: a scan that committed nothing must restart, and 05:88 spells that so."""
    feed = RosterFeed(iter([_row("c:/x/a", cursor="cur-a")]), plan_batch=512)
    assert list(feed)
    assert feed.committed_cursor is None
    assert feed.paused is False


def test_the_feed_refuses_a_batch_size_below_one() -> None:
    with pytest.raises(ValueError, match="positive row count"):
        RosterFeed(iter(()), plan_batch=0)


# ---------------------------------------------------------------------------------------------
# 2. `discover()` against a real store: batching, coverage and the resume
# ---------------------------------------------------------------------------------------------


def _scope(root: Path) -> tuple[Scope, IngestGuards]:
    return Scope(roots=(str(root),)), IngestGuards()


def test_a_complete_scan_rosters_every_file_and_records_complete_coverage(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    root = tmp_path / "src"
    _tree(root, 7)
    scope, guards = _scope(root)
    report = discover(
        store, root, scope, guards, indexed_at_ns=10**18, generation=1, scanned_at_ns=5
    )
    assert report.statements == 7
    assert report.complete is True
    assert report.paused is False
    assert report.exhausted_call_bound is False
    with _reader(tmp_path) as conn:
        assert conn.execute("SELECT count(*) FROM unit").fetchone()[0] == 7
        assert conn.execute("SELECT complete FROM ingest_scope").fetchone()[0] == 1


def test_a_paused_scan_leaves_coverage_incomplete_so_nothing_is_marked_out_of_scope(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """05:371 arrives for free: a paused walk never calls `tally.finish()`."""
    root = tmp_path / "src"
    _tree(root, 9)
    scope, guards = _scope(root)
    report = discover(
        store,
        root,
        scope,
        guards,
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=5,
        backpressure=Backpressure(pause=lambda: True),
        plan_batch=4,
    )
    assert report.paused is True
    assert report.complete is False
    assert report.resume_cursor is not None
    with _reader(tmp_path) as conn:
        assert conn.execute("SELECT complete FROM ingest_scope").fetchone()[0] == 0
    with pytest.raises(RouteError, match="did not complete"):
        sweep_unseen(store, scope_id=report.scope_id, generation=2, complete=report.complete)


def test_a_resume_from_the_kept_cursor_rosters_the_rest_and_repeats_nothing(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """The round trip 05:211 prices: a tree in two invocations, no gap and no duplicate."""
    root = tmp_path / "src"
    _tree(root, 9)
    scope, guards = _scope(root)
    first = discover(
        store,
        root,
        scope,
        guards,
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=5,
        backpressure=Backpressure(pause=lambda: True),
        plan_batch=4,
    )
    assert first.statements == 4
    second = discover(
        store,
        root,
        scope,
        guards,
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=6,
        cursor=first.resume_cursor,
        resumed=True,
    )
    assert second.complete is True
    with _reader(tmp_path) as conn:
        uris = [row[0] for row in conn.execute("SELECT unit_uri FROM unit ORDER BY unit_uri")]
    assert len(uris) == 9
    assert len(set(uris)) == 9


def test_the_call_bound_is_reported_separately_from_the_water_mark(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """05:211's `max_units_per_call` and 08:880's water mark stop the same walk for two reasons."""
    root = tmp_path / "src"
    _tree(root, 9)
    scope, guards = _scope(root)
    report = discover(
        store,
        root,
        scope,
        guards,
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=5,
        max_units=4,
    )
    assert report.paused is False
    assert report.exhausted_call_bound is True
    assert report.complete is False


def test_the_roster_write_batches_at_plan_batch_and_the_coverage_row_rides_in_the_last(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _tree(root, 10)
    scope, guards = _scope(root)
    thread = RecordingThread()
    discover(
        thread,  # type: ignore[arg-type] -- the double's whole job.
        root,
        scope,
        guards,
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=5,
        plan_batch=4,
    )
    assert thread.batches == [4, 4, 2]


# ---------------------------------------------------------------------------------------------
# 3. Events: the declared fields, and the two thresholds
# ---------------------------------------------------------------------------------------------


def test_the_three_plan_events_carry_exactly_their_declared_fields(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """`tools/events.toml` declares the field list; this module does not get a fourth key."""
    root = tmp_path / "src"
    _tree(root, 5)
    scope, guards = _scope(root)
    emitted: list[tuple[str, frozenset[str]]] = []

    def emit(*, kind: str, fields: dict[str, object]) -> None:
        emitted.append((str(kind), frozenset(fields)))

    discover(
        store,
        root,
        scope,
        guards,
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=5,
        emit=emit,
        resumed=True,
        backpressure=Backpressure(
            pause=lambda: True, claimable=lambda: 7, high_water=9, low_water=3
        ),
        plan_batch=2,
    )
    kinds = [kind for kind, _ in emitted]
    assert EventKind.PLAN_RESUME.value in kinds
    assert EventKind.PLAN_DISCOVER.value in kinds
    assert EventKind.PLAN_PAUSE.value in kinds
    for kind, keys in emitted:
        assert keys == frozenset(EVENTS[kind].fields), kind


def test_pause_names_the_high_water_mark_and_resume_names_the_low_one() -> None:
    """08:885's 2:1 gap is only legible if each event names the threshold it answers to."""
    marks = Backpressure(claimable=lambda: 31_000, high_water=50_000, low_water=25_000)
    assert marks.pause_fields() == {"claimable": 31_000, "high_water": 50_000}
    assert marks.resume_fields() == {"claimable": 31_000, "low_water": 25_000}


def test_the_default_backpressure_never_pauses_and_reports_nothing() -> None:
    """A caller with no queue yet gets a walk that runs to exhaustion."""
    marks = Backpressure()
    assert marks.pause() is False
    assert marks.claimable() == 0


# ---------------------------------------------------------------------------------------------
# 4. D143: the walked path, and the salt that cannot be recovered without it
# ---------------------------------------------------------------------------------------------


def test_every_roster_row_carries_the_walked_path_the_cache_salt_needs(tmp_path: Path) -> None:
    """08:1364 needs the unresolved path and `canonical_uri()` has already destroyed it. D143."""
    root = tmp_path / "src"
    _tree(root, 3)
    scope, guards = _scope(root)
    rows = list(roster_rows(root, scope, guards, indexed_at_ns=1, generation=1, tally=Tally()))
    assert len(rows) == 3
    for row in rows:
        assert WALKED_PATH_KEY in row.derived
        salt = unit_salt("fs", walked_path=str(row.derived[WALKED_PATH_KEY]), source_root=str(root))
        assert not salt.startswith("/"), "the salt is relative to roots.source, never absolute"
        assert ".." not in salt


def test_the_walked_path_is_relative_to_the_root_as_the_operator_typed_it(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    uri = scope_id_for(discover_module.locator_for(root)) + "a/b.txt"
    assert walked_path(str(root), uri).endswith("a/b.txt")
    assert walked_path(str(root), uri).startswith(str(root).replace("\\", "/"))


def test_the_upsert_never_refreshes_derived_so_a_salt_survives_a_second_walk() -> None:
    """A salt written at first sight must be the salt a resume reproduces."""
    assert "derived = excluded.derived" not in UNIT_UPSERT_SQL
    assert "ON CONFLICT(unit_uri) DO UPDATE SET" in UNIT_UPSERT_SQL


# ---------------------------------------------------------------------------------------------
# 5. D80: the fifteen values of `acq_failure_class`
# ---------------------------------------------------------------------------------------------


def test_the_acq_failure_domain_is_the_thirteen_plus_exactly_two() -> None:
    """D80's open question, answered as a set built from the enum rather than transcribed."""
    assert len(ACQ_FAILURE_CLASSES) == len(FailureClass) + 2
    assert {UNSEEN, FILTERED} <= ACQ_FAILURE_CLASSES
    assert {member.value for member in FailureClass} <= ACQ_FAILURE_CLASSES
    assert UNSEEN not in {member.value for member in FailureClass}
    assert FILTERED not in {member.value for member in FailureClass}


def test_the_two_extras_are_never_retried_and_the_thirteen_are_not_graded_here() -> None:
    assert acq_retryable(UNSEEN) is False
    assert acq_retryable(FILTERED) is False
    assert acq_retryable(FailureClass.RATE_LIMITED.value) is True
    assert acq_retryable(FailureClass.CORRUPT_INPUT.value) is True


def test_an_unknown_acq_failure_class_is_refused_by_name() -> None:
    with pytest.raises(RouteError, match="D80"):
        acq_retryable("vanished")


def test_the_column_carrying_those_fifteen_has_no_check_in_the_ddl(migrations: Path) -> None:
    """D80's other half: `state`, `trust_class` and `scope_rule` carry CHECKs; this one does not."""
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    assert "acq_failure_class TEXT," in ddl
    assert "acq_failure_class TEXT CHECK" not in ddl


# ---------------------------------------------------------------------------------------------
# 6. The change-detection ladder
# ---------------------------------------------------------------------------------------------


def test_the_third_clause_is_what_makes_a_freshly_written_file_not_fresh() -> None:
    """05:341: a file modified inside the mtime granularity window cannot be PROVEN unchanged."""
    stored = StoredStat(
        triple=StatTriple(size=10, mtime_ns=1_000_000_000, indexed_at_ns=1_000_000_001),
        settled_gen=4,
    )
    observed = StatTriple(size=10, mtime_ns=1_000_000_000, indexed_at_ns=9)
    assert freshness(stored, observed) == "changed"

    settled = StoredStat(
        triple=StatTriple(size=10, mtime_ns=1_000_000_000, indexed_at_ns=4_000_000_000),
        settled_gen=4,
    )
    assert freshness(settled, observed) == "unchanged"


def test_a_fresh_unit_that_never_settled_is_a_third_answer_and_not_a_content_change() -> None:
    """08:503's second conjunct: fresh AND settled at a settled_gen is what produces no work."""
    stored = StoredStat(
        triple=StatTriple(size=10, mtime_ns=1_000_000_000, indexed_at_ns=4_000_000_000),
        settled_gen=None,
    )
    observed = StatTriple(size=10, mtime_ns=1_000_000_000, indexed_at_ns=9)
    assert freshness(stored, observed) == "unsettled"


def test_a_changed_size_is_changed_whatever_the_mtime_says() -> None:
    stored = StoredStat(
        triple=StatTriple(size=10, mtime_ns=1_000_000_000, indexed_at_ns=4_000_000_000),
        settled_gen=1,
    )
    assert freshness(stored, StatTriple(size=11, mtime_ns=1_000_000_000, indexed_at_ns=9)) == (
        "changed"
    )


# ---------------------------------------------------------------------------------------------
# 7. The digest, and the normaliser that may not lose a document
# ---------------------------------------------------------------------------------------------


def test_a_raising_normaliser_falls_back_to_the_raw_digest_and_records_nothing_wrong() -> None:
    """05:276: *"the failure mode is 'reparse a document we could have skipped', never 'treat two
    documents as one'."*"""

    def explodes(body: bytes, fmt: str) -> tuple[bytes, str | None]:
        del body, fmt
        raise ValueError("this normaliser is broken")

    digest, name = content_digest(b"hello", fmt="pdf", normalise=explodes)
    assert name is None
    assert digest == content_digest(b"hello")[0]


def test_a_cancelled_normaliser_is_not_converted_into_a_different_identity() -> None:
    """`BaseException` is deliberately not caught: an interrupt cancels, it does not fall back."""

    def cancelled(body: bytes, fmt: str) -> tuple[bytes, str | None]:
        del body, fmt
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        content_digest(b"hello", normalise=cancelled)


def test_a_normaliser_that_projects_changes_the_digest_and_names_itself() -> None:
    def strip_trailer(body: bytes, fmt: str) -> tuple[bytes, str | None]:
        del fmt
        return body.split(b"%%", 1)[0], "pdf_trailer_v1"

    digest, name = content_digest(b"body%%ModDate", fmt="pdf", normalise=strip_trailer)
    assert name == "pdf_trailer_v1"
    assert digest == content_digest(b"body")[0]


def test_the_shipped_normaliser_is_the_row_the_table_calls_everything_else() -> None:
    assert raw(b"abc", "pdf") == (b"abc", None)


# ---------------------------------------------------------------------------------------------
# 8. `acquire_unit`: zero bytes for a skip, the pre-read stat, the bounded read
# ---------------------------------------------------------------------------------------------


def test_an_unchanged_unit_reads_zero_bytes(tmp_path: Path) -> None:
    """05:339 prices the ladder in bytes, so the free rung has to actually be free."""
    path = tmp_path / "a.txt"
    path.write_bytes(b"x" * 32)
    info = path.stat()
    stored = StoredStat(
        triple=StatTriple(
            size=info.st_size, mtime_ns=info.st_mtime_ns, indexed_at_ns=info.st_mtime_ns + 10**10
        ),
        settled_gen=3,
        content_sha256="0" * 64,
    )

    def never(_path: Path, _limit: int) -> bytes:
        raise AssertionError("the free rung must not read")

    result = acquire_unit(
        path,
        "c:/x/a.txt",
        stored,
        indexed_at_ns=10**18,
        max_unit_bytes=1 << 20,
        read=never,
    )
    assert result.skipped is True
    assert result.bytes_read == 0
    assert result.verdict == "unchanged"
    assert result.statement()[0] is UNCHANGED_SQL


def test_a_changed_unit_is_read_digested_and_written_with_the_pre_read_triple(
    tmp_path: Path,
) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"hello")
    stored = StoredStat(triple=StatTriple(size=1, mtime_ns=1, indexed_at_ns=1), settled_gen=1)
    result = acquire_unit(path, "c:/x/a.txt", stored, indexed_at_ns=10**18, max_unit_bytes=1 << 20)
    assert result.skipped is False
    assert result.bytes_read == 5
    assert result.content_sha256 == content_digest(b"hello")[0]
    assert result.normalizer is None
    assert result.diagnostics == (RAW_DIGEST_CODE,)
    sql, params = result.statement()
    assert sql is ACQUIRED_SQL
    assert params["size"] == 5
    assert params["bytes"] == 5


def test_verify_digests_reads_the_bytes_and_a_matching_digest_is_still_a_skip(
    tmp_path: Path,
) -> None:
    """05:361: a re-read whose digest matches *"does not mint a new `gen`"* -- but it was read."""
    path = tmp_path / "a.txt"
    path.write_bytes(b"same")
    info = path.stat()
    stored = StoredStat(
        triple=StatTriple(
            size=info.st_size, mtime_ns=info.st_mtime_ns, indexed_at_ns=info.st_mtime_ns + 10**10
        ),
        settled_gen=3,
        content_sha256=content_digest(b"same")[0],
    )
    result = acquire_unit(
        path,
        "c:/x/a.txt",
        stored,
        indexed_at_ns=10**18,
        max_unit_bytes=1 << 20,
        verify_digests=True,
    )
    assert result.skipped is True
    assert result.bytes_read == 4, "the digest rung is not free and the report says so"


def test_a_bounded_read_refusal_fails_the_unit_and_never_the_corpus(tmp_path: Path) -> None:
    """05:330's mechanism 2. One 3 GiB file must not end a scan."""
    path = tmp_path / "a.txt"
    path.write_bytes(b"x" * 64)

    def too_large(_path: Path, _limit: int) -> bytes:
        raise DriverError(cls=FailureClass.TOO_LARGE, message="over", limit="ingest.max_unit_bytes")

    stored = StoredStat(triple=StatTriple(size=0, mtime_ns=0, indexed_at_ns=0))
    result = acquire_unit(
        path, "c:/x/a.txt", stored, indexed_at_ns=1, max_unit_bytes=8, read=too_large
    )
    assert result.state == FAILED
    assert result.failure_class == FailureClass.TOO_LARGE.value
    assert result.statement()[0] is ACQ_FAILED_SQL


def test_a_file_that_vanished_between_the_walk_and_the_stat_is_a_unit_refusal(
    tmp_path: Path,
) -> None:
    stored = StoredStat(triple=StatTriple(size=0, mtime_ns=0, indexed_at_ns=0))
    result = acquire_unit(
        tmp_path / "gone.txt", "c:/x/gone.txt", stored, indexed_at_ns=1, max_unit_bytes=8
    )
    assert result.state == FAILED
    assert result.failure_class == FailureClass.CORRUPT_INPUT.value


def test_observe_is_a_bare_stat_and_carries_the_callers_index_time(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"abcd")
    triple = observe(path, indexed_at_ns=777)
    assert triple.size == 4
    assert triple.indexed_at_ns == 777


# ---------------------------------------------------------------------------------------------
# 9. `Acquired`'s invariants
# ---------------------------------------------------------------------------------------------


def test_a_failed_unit_carries_the_cause_the_state_machine_gives_the_transition() -> None:
    with pytest.raises(RouteError, match="carries the cause"):
        Acquired(unit_uri="c:/x/a", state=FAILED, verdict="changed")


def test_an_acquired_unit_carries_the_triple_its_digest_was_read_under() -> None:
    with pytest.raises(RouteError, match="stat triple"):
        Acquired(unit_uri="c:/x/a", state=ACQUIRED, verdict="changed", content_sha256="0" * 64)


def test_an_out_of_range_acq_failure_class_is_refused_at_construction() -> None:
    with pytest.raises(RouteError, match="D80"):
        Acquired(unit_uri="c:/x/a", state=FAILED, verdict="changed", failure_class="nope")


def test_the_skip_statement_moves_only_the_index_time() -> None:
    """The point of `UNCHANGED_SQL`: 05:346's asymmetry stops costing a re-read every run."""
    assert "size =" not in UNCHANGED_SQL
    assert "mtime_ns =" not in UNCHANGED_SQL
    assert "indexed_at_ns = :indexed_at_ns" in UNCHANGED_SQL
    assert "content_sha256" not in UNCHANGED_SQL


def test_only_the_acquisition_statement_moves_the_stat_triple() -> None:
    """acquire.py's upsert refuses to, and that refusal is what keeps `stat_fresh` meaningful."""
    for column in ("size", "mtime_ns", "indexed_at_ns"):
        assert f"{column} = excluded.{column}" not in UNIT_UPSERT_SQL
        assert f"{column} = :{column}" in ACQUIRED_SQL


# ---------------------------------------------------------------------------------------------
# 10. The four statements against a real store
# ---------------------------------------------------------------------------------------------


def _unit(conn: Any, uri: str, *, state: str = "discovered", gen: int = 1, **extra: object) -> None:
    columns = {
        "unit_uri": uri,
        "connector": "fs",
        "state": state,
        "trust_class": "internal",
        "last_seen_gen": gen,
        **extra,
    }
    names = ", ".join(columns)
    holes = ", ".join(f":{name}" for name in columns)
    conn.execute(f"INSERT INTO unit({names}) VALUES({holes})", columns)


def test_a_second_process_cannot_claim_an_acquiring_unit_and_no_lease_says_when_it_may(
    tmp_path: Path, migrations: Path
) -> None:
    """05:400 rule 6 asks for an unexpired lease, and `unit` has no column to hold one. **D163.**"""
    connection = ow.connect(tmp_path / "index.owstore")
    migrate.apply_pending(connection, now_ns=1)
    with connection:
        _unit(connection, "c:/x/a.txt")
    first = connection.execute(CLAIM_ACQUIRING_SQL, {"unit_uri": "c:/x/a.txt"})
    assert first.rowcount == 1
    second = connection.execute(CLAIM_ACQUIRING_SQL, {"unit_uri": "c:/x/a.txt"})
    assert second.rowcount == 0, "the compare-and-swap is the claim"
    assert (
        connection.execute(
            "SELECT state, acq_attempts_total, acq_attempts_today FROM unit"
        ).fetchone()
    ) == (ACQUIRING, 1, 1)
    connection.close()

    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    unit_ddl = ddl.split("CREATE TABLE unit (", 1)[1].split(") STRICT;", 1)[0]
    for absent in ("lease_expires", "claimed_by", "claimed_gen"):
        assert absent not in unit_ddl, f"D163 would be discharged by a {absent} column"


def test_a_stale_acquiring_row_is_returned_and_a_fresh_one_is_left_alone(tmp_path: Path) -> None:
    connection = ow.connect(tmp_path / "index.owstore")
    migrate.apply_pending(connection, now_ns=1)
    with connection:
        _unit(connection, "c:/x/stale.txt", state=ACQUIRING, acq_last_attempt_at=0)
        _unit(connection, "c:/x/live.txt", state=ACQUIRING)
        connection.execute(
            "UPDATE unit SET acq_last_attempt_at = CAST(unixepoch('subsec')*1000 AS INTEGER) "
            "WHERE unit_uri = 'c:/x/live.txt'"
        )
    cursor = connection.execute(RESET_ACQUIRING_SQL, {"stale_ms": ACQUIRING_STALE_MS})
    assert cursor.rowcount == 1
    states = dict(connection.execute("SELECT unit_uri, state FROM unit").fetchall())
    assert states["c:/x/stale.txt"] == "discovered"
    assert states["c:/x/live.txt"] == ACQUIRING
    connection.close()


def test_the_reset_does_not_decrement_the_attempt_counter(tmp_path: Path) -> None:
    """Unlike 08:496's lease reap: nothing extends this lease, so the counter is the only bound."""
    assert "attempts_total = acq_attempts_total - 1" not in RESET_ACQUIRING_SQL
    assert "acq_attempts_total" not in RESET_ACQUIRING_SQL
    del tmp_path


def test_the_sweep_marks_only_what_this_generation_did_not_see(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    connection = ow.connect(tmp_path / "index.owstore")
    with connection:
        _unit(connection, "c:/x/seen.txt", state="settled", gen=2)
        _unit(connection, "c:/x/lost.txt", state="settled", gen=1)
        _unit(connection, "c:/x/busy.txt", state=ACQUIRING, gen=1)
        _unit(connection, "c:/y/other.txt", state="settled", gen=1)
    connection.close()

    marked = sweep_unseen(store, scope_id="c:/x/", generation=2, complete=True)
    assert marked == 1
    with _reader(tmp_path) as conn:
        rows = dict(conn.execute("SELECT unit_uri, state FROM unit").fetchall())
    assert rows["c:/x/lost.txt"] == OUT_OF_SCOPE
    assert rows["c:/x/seen.txt"] == "settled"
    assert rows["c:/x/busy.txt"] == ACQUIRING, "a unit another process holds is not seen-and-lost"
    assert rows["c:/y/other.txt"] == "settled", "the prefix bounds the sweep"


def test_the_sweep_deletes_nothing_and_says_only_that_the_unit_is_gone(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """05:370: *"its blocks are **not** deleted, because a shipped `cite` must still resolve."*"""
    assert "DELETE" not in OUT_OF_SCOPE_SQL.upper()
    connection = ow.connect(tmp_path / "index.owstore")
    with connection:
        _unit(connection, "c:/x/lost.txt", state="settled", gen=1)
    connection.close()
    sweep_unseen(store, scope_id="c:/x/", generation=2, complete=True)
    with _reader(tmp_path) as conn:
        cause = conn.execute("SELECT acq_failure_class FROM unit").fetchone()[0]
    assert cause == UNSEEN


def test_the_sweep_is_idempotent_and_never_overwrites_a_filtered_cause(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    connection = ow.connect(tmp_path / "index.owstore")
    with connection:
        _unit(
            connection,
            "c:/x/excluded.txt",
            state=OUT_OF_SCOPE,
            gen=1,
            acq_failure_class=FILTERED,
        )
    connection.close()
    assert sweep_unseen(store, scope_id="c:/x/", generation=2, complete=True) == 0
    with _reader(tmp_path) as conn:
        assert conn.execute("SELECT acq_failure_class FROM unit").fetchone()[0] == FILTERED


def test_reset_stale_acquiring_reaches_the_store_and_reports_what_it_returned(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    connection = ow.connect(tmp_path / "index.owstore")
    with connection:
        _unit(connection, "c:/x/a.txt", state=ACQUIRING, acq_last_attempt_at=0)
    connection.close()
    assert reset_stale_acquiring(store) == 1


def test_the_pending_query_runs_and_reads_the_stores_own_clock(tmp_path: Path) -> None:
    """08:597: a backward NTP step on one worker must not make a row permanently unacquirable."""
    assert "unixepoch('subsec')" in PENDING_ACQUISITION_SQL
    connection = ow.connect(tmp_path / "index.owstore")
    migrate.apply_pending(connection, now_ns=1)
    with connection:
        _unit(connection, "c:/x/a.txt")
        _unit(connection, "c:/x/old.txt", gen=0)
        _unit(connection, "c:/x/done.txt", state="settled")
    rows = connection.execute(PENDING_ACQUISITION_SQL, pending_params(generation=1)).fetchall()
    connection.close()
    assert [row[0] for row in rows] == ["c:/x/a.txt"]


def test_the_states_this_module_writes_are_all_in_the_ddls_check(migrations: Path) -> None:
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    declared = set(re.findall(r"'([a-z_]+)'", ddl.split("state          TEXT NOT NULL CHECK")[1]))
    for state in (ACQUIRING, ACQUIRED, FAILED, OUT_OF_SCOPE, "discovered", "identified"):
        assert state in declared


# ---------------------------------------------------------------------------------------------
# 10a. D169: the stale marker, whose reader has existed since P2
# ---------------------------------------------------------------------------------------------


def test_the_stale_scan_surveys_settled_units_and_skips_the_ones_already_marked(
    tmp_path: Path,
) -> None:
    """08:503's ladder is applied *"for each unit"*, and a settled unit is where a change shows."""
    connection = ow.connect(tmp_path / "index.owstore")
    migrate.apply_pending(connection, now_ns=1)
    with connection:
        _unit(connection, "c:/x/settled.txt", state="settled", size=1, mtime_ns=2)
        _unit(connection, "c:/x/marked.txt", state="settled", stale_since=99)
        _unit(connection, "c:/x/working.txt", state="identified")
        _unit(connection, "c:/x/unseen.txt", state="settled", gen=0)
        _unit(connection, "c:/y/other.txt", state="settled")
    rows = connection.execute(
        STALE_SCAN_SQL, stale_params(scope_id="c:/x/", generation=1)
    ).fetchall()
    connection.close()
    assert [row[0] for row in rows] == ["c:/x/settled.txt"]


def test_the_mark_is_taken_once_and_kept_across_a_reset(tmp_path: Path) -> None:
    """08:1891: *"set on the **first** transition only and **kept across a reset**."*"""
    connection = ow.connect(tmp_path / "index.owstore")
    migrate.apply_pending(connection, now_ns=1)
    with connection:
        _unit(connection, "c:/x/a.txt", state="settled")
    assert connection.execute(MARK_STALE_SQL, {"unit_uri": "c:/x/a.txt", "at_ns": 10}).rowcount == 1
    assert connection.execute(MARK_STALE_SQL, {"unit_uri": "c:/x/a.txt", "at_ns": 20}).rowcount == 0
    assert connection.execute("SELECT stale_since FROM unit").fetchone() == (10,)
    connection.close()


def test_marking_stale_does_not_move_the_state(store: ow.StoreThread, tmp_path: Path) -> None:
    """05:389 draws `settled` as terminal; the re-entry is the `dep` query's, which is W4.6's."""
    assert "state" not in MARK_STALE_SQL
    connection = ow.connect(tmp_path / "index.owstore")
    with connection:
        _unit(connection, "c:/x/a.txt", state="settled")
    connection.close()
    assert mark_stale(store, ["c:/x/a.txt"], at_ns=1_700_000_000) == 1
    with _reader(tmp_path) as conn:
        assert conn.execute("SELECT state, stale_since FROM unit").fetchone() == (
            "settled",
            1_700_000_000,
        )


def test_marking_nothing_takes_no_transaction(store: ow.StoreThread) -> None:
    assert mark_stale(store, [], at_ns=1) == 0


def test_the_column_the_mark_writes_is_the_one_the_reader_already_counts() -> None:
    """`Reader.coverage` has counted `stale_since IS NOT NULL` since P2 with nothing writing it."""
    reader = inspect.getsource(__import__("omniweave_core.store.reader", fromlist=["x"]))
    assert "stale_since IS NOT NULL" in reader
    assert "stale_since = :at_ns" in MARK_STALE_SQL


# ---------------------------------------------------------------------------------------------
# 11. The two defect reports this module ships against
# ---------------------------------------------------------------------------------------------


def test_the_roster_names_no_cas_blob_and_the_unit_table_has_no_column_for_one(
    migrations: Path,
) -> None:
    """02:472's hop 3 writes *"the CAS entry"*; 08:861 says the file is the blob. **D165.**"""
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    unit_ddl = ddl.split("CREATE TABLE unit (", 1)[1].split(") STRICT;", 1)[0]
    for absent in ("store_ref", "blob_ref", "cas_ref", "cas://"):
        assert absent not in unit_ddl
    body = inspect.getsource(discover_module).split('"""', 2)[2]
    assert "blobs" not in body, "acquisition here reads, digests and forgets"


def test_an_oversize_candidate_is_counted_and_never_rostered(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """05:227 asks for a `unit` row in `failed`; the walk refuses before one exists. **D168.**"""
    root = tmp_path / "src"
    root.mkdir()
    (root / "huge.txt").write_bytes(b"x" * 64)
    (root / "small.txt").write_bytes(b"x")
    scope = Scope(roots=(str(root),))
    report = discover(
        store,
        root,
        scope,
        IngestGuards(max_unit_bytes=8),
        indexed_at_ns=10**18,
        generation=1,
        scanned_at_ns=5,
    )
    assert report.coverage is not None
    assert report.coverage.skipped_why == {"too_large": 1}
    with _reader(tmp_path) as conn:
        uris = [row[0] for row in conn.execute("SELECT unit_uri FROM unit")]
    assert len(uris) == 1, "no `failed` row exists for the refused candidate -- D168"
    assert SKIP_REASON_CLASSES["too_large"] == FailureClass.TOO_LARGE.value


def test_the_third_skip_reason_has_no_failure_class_because_it_is_a_refusal() -> None:
    """`path_outside_roots` is OW-A-007, and 05:70 calls it *"a refusal, not a warning"*."""
    assert "path_outside_roots" not in SKIP_REASON_CLASSES


# ---------------------------------------------------------------------------------------------
# 12. Against the plan's own text
# ---------------------------------------------------------------------------------------------


def test_the_state_machine_this_module_walks_is_the_plans(plan: PlanDocs) -> None:
    plan.require()
    text = plan.text("05-ingest-and-routing.md")
    diagram = text.split("## 1.5 The ingest queue contract", 1)[1].split("```", 2)[1]
    for state in ("discovered", "acquiring", "acquired", "identified", "out_of_scope"):
        assert state in diagram
    assert "acq_failure_class='filtered'" in diagram


def test_the_two_extra_failure_values_are_the_plans_own_two(plan: PlanDocs) -> None:
    """Three values are written into the column and exactly one of them is one of the thirteen."""
    plan.require()
    hits = plan.grep(r"acq_failure_class\s*=\s*'", documents=("05-ingest-and-routing.md",))
    written = {
        match
        for hit in hits
        for match in re.findall(r"acq_failure_class\s*=\s*'([a-z_]+)'", hit.text)
    }
    members = {member.value for member in FailureClass}
    assert written & members == {FailureClass.TOO_LARGE.value}
    assert written - members == {UNSEEN, FILTERED}
    assert written <= ACQ_FAILURE_CLASSES


def test_the_cache_layer_table_gives_acquire_fs_no_layer(plan: PlanDocs) -> None:
    """08:861, the row D165 turns on: *"the file *is* the blob; a copy would be a second
    representation."*"""
    plan.require()
    rows = plan.grep(r"^\| `acquire\.fs` \|", documents=("08-runtime.md",))
    assert len(rows) == 1
    cells = [cell.strip() for cell in rows[0].text.strip("|").split("|")]
    assert cells[1] == "none"
    assert "second representation" in cells[2]


def test_the_water_mark_defaults_are_the_plans_two_numbers(plan: PlanDocs) -> None:
    plan.require()
    hits = plan.grep(r"queue_high_water = 50000", documents=("08-runtime.md",))
    assert hits, "08:880's row names both thresholds"
    marks = Backpressure(high_water=50_000, low_water=25_000)
    assert marks.high_water == 2 * marks.low_water, "08:885's 2:1 gap"


# ---------------------------------------------------------------------------------------------
# The acquisition pass: W7.3w's first caller of the four statements above
# ---------------------------------------------------------------------------------------------


LATE_NS = 9 * 10**18
"""Late enough that every stat triple a walk writes reads fresh: `stat_fresh()`'s third clause."""


def _rostered(store: ow.StoreThread, root: Path, *names: str, generation: int = 1) -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(name.encode())
    discover(
        store,
        root,
        Scope(roots=(str(root),)),
        IngestGuards(),
        indexed_at_ns=LATE_NS,
        generation=generation,
        scanned_at_ns=1,
    )


def test_a_pass_reads_every_unit_the_walk_saw_and_writes_its_digest(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """The walk's triple is the WALK's, not an indexing's, so it looks fresh at `indexed_at_ns =
    LATE_NS` -- and the units are read anyway, because none has a digest to preserve (D561)."""
    root = tmp_path / "src"
    _rostered(store, root, "a.txt", "b/c.txt")
    done = acquire_pending(store, generation=1, indexed_at_ns=LATE_NS)
    assert done == AcquirePass(acquired=2, bytes_read=len("a.txt") + len("b/c.txt"))
    rows = (
        _reader(tmp_path)
        .execute("SELECT state, content_sha256 IS NOT NULL, bytes FROM unit")
        .fetchall()
    )
    assert sorted(rows) == [(ACQUIRED, 1, 5), (ACQUIRED, 1, 7)]


def test_a_pass_reads_a_failing_unit_once_and_leaves_the_next_attempt_to_the_next_run(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """`PENDING_ACQUISITION_AFTER_SQL`'s reason: a failure with no `retry_after` satisfies the
    pending query again at once, and without the key it is read `MAX_ATTEMPTS_TODAY` times."""
    root = tmp_path / "src"
    _rostered(store, root, "a.txt", "b.txt")
    reads: list[str] = []

    def unreadable(path: Path, _limit: int) -> bytes:
        reads.append(path.name)
        raise OSError("gone")

    done = acquire_pending(
        store, generation=1, indexed_at_ns=LATE_NS, plan_batch=1, read=unreadable
    )
    assert (done.failed, done.acquired) == (2, 0)
    assert sorted(reads) == ["a.txt", "b.txt"]
    rows = _reader(tmp_path).execute("SELECT state, acq_attempts_total FROM unit").fetchall()
    assert rows == [(FAILED, 1), (FAILED, 1)]


def test_a_pass_reads_only_this_generation_s_units(store: ow.StoreThread, tmp_path: Path) -> None:
    root = tmp_path / "src"
    _rostered(store, root, "a.txt", generation=1)
    _rostered(store, tmp_path / "other", "b.txt", generation=2)
    assert acquire_pending(store, generation=2, indexed_at_ns=LATE_NS).acquired == 1
    rows = _reader(tmp_path).execute("SELECT state FROM unit ORDER BY unit_uri").fetchall()
    assert sorted(rows) == [(ACQUIRED,), ("discovered",)]


def test_the_free_rung_skips_only_a_unit_whose_bytes_were_read_before(tmp_path: Path) -> None:
    """D561. A skip preserves a digest; a stored triple with no digest behind it is a walk's."""
    path = tmp_path / "a.txt"
    path.write_bytes(b"x" * 8)
    info = path.stat()
    triple = StatTriple(size=8, mtime_ns=info.st_mtime_ns, indexed_at_ns=info.st_mtime_ns + 10**10)
    never_read = acquire_unit(
        path, "c:/x/a.txt", StoredStat(triple=triple), indexed_at_ns=LATE_NS, max_unit_bytes=64
    )
    assert (never_read.skipped, never_read.bytes_read) == (False, 8)
    read_before = acquire_unit(
        path,
        "c:/x/a.txt",
        StoredStat(triple=triple, settled_gen=1, content_sha256=never_read.content_sha256),
        indexed_at_ns=LATE_NS,
        max_unit_bytes=64,
    )
    assert (read_before.skipped, read_before.bytes_read) == (True, 0)
