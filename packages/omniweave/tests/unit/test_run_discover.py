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
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import omniweave_core.store.sqlite as ow
import pytest
from omniweave.run import discover as discover_module
from omniweave.run.discover import (
    ACCEPT_PARTIAL_CLASSES,
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
    reopen_changed_failures,
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


def _refused(store: ow.StoreThread, tmp_path: Path, root: Path, name: str) -> str:
    """One unit acquired, then refused past identify, as `gate.unsupported-source` leaves it."""
    _rostered(store, root, name)
    acquire_pending(store, generation=1, indexed_at_ns=LATE_NS)
    reader = _reader(tmp_path)
    (uri,) = reader.execute("SELECT unit_uri FROM unit").fetchone()
    reader.execute(
        "UPDATE unit SET state = 'failed', part_count = 1, "
        "acq_failure_class = 'unsupported_format' WHERE unit_uri = ?",
        (uri,),
    )
    reader.execute(
        "INSERT INTO work(unit_uri, operator, op_version, cache_key, cost_class, status) "
        "VALUES(?, 'op.identify', 1, 'k', 'free', 'done')",
        (uri,),
    )
    reader.commit()
    return str(uri)


def test_a_refused_unit_whose_file_is_unchanged_stays_refused(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D580's measured case, kept: re-reading unchanged bytes would refuse them again, and
    re-acquiring a unit with a part count is what stranded it."""
    uri = _refused(store, tmp_path, tmp_path / "src", "masked.docx")
    assert reopen_changed_failures(store, generation=1) == 0
    row = _reader(tmp_path).execute(
        "SELECT state, part_count, acq_failure_class FROM unit WHERE unit_uri = ?", (uri,)
    )
    assert row.fetchone() == (FAILED, 1, "unsupported_format")


def test_a_refused_unit_whose_file_changed_is_reopened_and_read_again(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D640. Gate 9's fix for a refused unit is `ow add <path>`, and with the file restored that
    command read nothing: D580 kept every failed unit with a part count out of acquisition. The
    paired-damage suite's `fix fixes` clause found it. A changed file is now re-opened: back to
    `discovered`, its count and class cleared, its terminal work rows gone, and read again."""
    root = tmp_path / "src"
    uri = _refused(store, tmp_path, root, "masked.docx")
    (root / "masked.docx").write_bytes(b"the restored bytes, which are longer")
    assert reopen_changed_failures(store, generation=1) == 1
    reader = _reader(tmp_path)
    row = reader.execute(
        "SELECT state, part_count, acq_failure_class FROM unit WHERE unit_uri = ?", (uri,)
    )
    assert row.fetchone() == ("discovered", None, None)
    assert reader.execute("SELECT count(*) FROM work").fetchone() == (0,)
    assert acquire_pending(store, generation=1, indexed_at_ns=LATE_NS).acquired == 1
    assert reopen_changed_failures(store, generation=1) == 0


def test_accept_partial_reopens_a_corrupt_refusal_whose_file_is_unchanged(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D641. `--accept-partial` exists for bytes the user will not change (05:2821), so the unit
    `gate.corrupt` refused is read again as it stands; a refusal of any other class is not."""
    uri = _refused(store, tmp_path, tmp_path / "src", "torn.pdf")
    reader = _reader(tmp_path)
    reader.execute("UPDATE unit SET acq_failure_class = 'corrupt_input' WHERE unit_uri = ?", (uri,))
    reader.commit()
    assert reopen_changed_failures(store, generation=1) == 0
    assert reopen_changed_failures(store, generation=1, regardless=frozenset({"encrypted"})) == 0
    assert reopen_changed_failures(store, generation=1, regardless=ACCEPT_PARTIAL_CLASSES) == 1
    row = _reader(tmp_path).execute("SELECT state FROM unit WHERE unit_uri = ?", (uri,))
    assert row.fetchone() == ("discovered",)


def test_a_password_mapping_reopens_an_encrypted_refusal_whose_file_is_unchanged(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """ADR-15 D15.3. Nothing about an encrypted file changes when its password is supplied, so
    `reopens` -- `Passwords.reopens` in a run -- is asked for each failed unit and its class, and
    the unit it answers for is read again. It is asked about this unit's class, not any other."""
    uri = _refused(store, tmp_path, tmp_path / "src", "locked.pdf")
    reader = _reader(tmp_path)
    reader.execute("UPDATE unit SET acq_failure_class = 'encrypted' WHERE unit_uri = ?", (uri,))
    reader.commit()
    asked: list[tuple[str, str | None]] = []

    def nothing_maps(unit_uri: str, failure_class: str | None) -> bool:
        asked.append((unit_uri, failure_class))
        return False

    assert reopen_changed_failures(store, generation=1, reopens=nothing_maps) == 0
    assert asked == [(uri, "encrypted")]
    assert reopen_changed_failures(store, generation=1, reopens=lambda _u, c: c == "encrypted") == 1
    row = _reader(tmp_path).execute("SELECT state FROM unit WHERE unit_uri = ?", (uri,))
    assert row.fetchone() == ("discovered",)


def _too_many_parts(tmp_path: Path, uri: str, cause: str) -> None:
    """The decision `gate.too-many-parts` writes for `uri`'s bytes, and the unit's link to it."""
    reader = _reader(tmp_path)
    reader.execute(
        "UPDATE unit SET acq_failure_class = 'resource_limit', content_sha256 = 'c0' "
        "WHERE unit_uri = ?",
        (uri,),
    )
    reader.execute(
        "INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) VALUES('ev', X'00', 1)"
    )
    reader.execute(
        "INSERT INTO route_decision(decision_id, content_sha256, unit_part, lane, rung, "
        "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
        "rule_id, rule_origin, cause, reason, slice_key, evidence_digest, est_spend, est_micros, "
        "reserved_micros, admission, generation, decided_at) VALUES('dec_1', 'c0', '', 'text', 0, "
        "'pd', '', '', '', '', 'free', 'gate.too-many-parts', 'builtin', ?, 'ingest.max_parts', "
        "'', 'ev', '{}', 0, 0, 'admitted', 1, 1)",
        (cause,),
    )
    reader.execute(
        "INSERT INTO route_unit_decision(unit_uri, unit_part, lane, decision_id, first_seen_at) "
        "VALUES(?, '', 'text', 'dec_1', 1)",
        (uri,),
    )
    reader.commit()


@pytest.mark.parametrize(("max_parts", "reopened"), [(3, 0), (4, 1), (10_000, 1)])
def test_a_raised_max_parts_reopens_a_part_count_refusal_whose_file_is_unchanged(
    store: ow.StoreThread, tmp_path: Path, max_parts: int, reopened: int
) -> None:
    """D644. A file `gate.too-many-parts` refused is what it is, and the user's remedy is the cap,
    not the file. So once `[ingest] max_parts` admits the count the decision recorded, the unit
    is read again as it stands; under a cap it still exceeds, it is left alone, since reading it
    would cost an identify and a signal child only to be refused again."""
    uri = _refused(store, tmp_path, tmp_path / "src", "long.pdf")
    _too_many_parts(tmp_path, uri, "unit.part_count=4>3.0")
    raised = discover_module.raised_on(store, max_parts=max_parts)
    assert raised == (frozenset({uri}) if reopened else frozenset())
    reopens = discover_module.reopens_of(None, raised)
    assert (reopens is None) == (not reopened)
    assert reopen_changed_failures(store, generation=1, reopens=reopens) == reopened
    row = _reader(tmp_path).execute("SELECT state FROM unit WHERE unit_uri = ?", (uri,))
    assert row.fetchone() == ("discovered" if reopened else FAILED,)


def test_one_predicate_carries_both_reasons_to_read_an_unchanged_file_again() -> None:
    """`reopens_of` joins the password mapping's predicate and the raised set, and each answers
    for its own class only: a raised unit is not re-opened as `encrypted`, nor a mapped one as
    `resource_limit`. With neither there is no predicate at all."""
    assert discover_module.reopens_of(None) is None
    reopens = discover_module.reopens_of(lambda _u, c: c == "encrypted", frozenset({"c:/a.pdf"}))
    assert reopens is not None
    assert reopens("c:/a.pdf", "resource_limit")
    assert not reopens("c:/b.pdf", "resource_limit")
    assert reopens("c:/b.pdf", "encrypted")
    only_raised = discover_module.reopens_of(None, frozenset({"c:/a.pdf"}))
    assert only_raised is not None
    assert not only_raised("c:/a.pdf", "encrypted")


def _settled(store: ow.StoreThread, tmp_path: Path, root: Path, name: str) -> str:
    """One unit read, identified and parsed, as `SETTLED_SQL` leaves it, with its done rows."""
    _rostered(store, root, name)
    acquire_pending(store, generation=1, indexed_at_ns=LATE_NS)
    reader = _reader(tmp_path)
    (uri,) = reader.execute("SELECT unit_uri FROM unit").fetchone()
    reader.execute(
        "UPDATE unit SET state = 'settled', settled_gen = 1, part_count = 1 WHERE unit_uri = ?",
        (uri,),
    )
    for operator in ("op.identify", "op.parse"):
        reader.execute(
            "INSERT INTO work(unit_uri, operator, op_version, cache_key, cost_class, status) "
            "VALUES(?, ?, 1, 'k', 'free', 'done')",
            (uri, operator),
        )
    reader.commit()
    return str(uri)


def test_an_edited_settled_file_is_marked_stale_and_read_again(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D645, found by a probe: a PDF indexed, edited, then `ow add` and `ow ingest` again, and
    neither read it. The old text answered and the new text was a confident `absent`. A settled
    unit whose file changed is now stamped `stale_since` (gate 6 names it while the old document is
    what a query reads), back to `discovered`, and read again: its done rows are gone."""
    root = tmp_path / "src"
    uri = _settled(store, tmp_path, root, "note.pdf")
    assert discover_module.reenter_changed(store, generation=1, at_ns=5) == 0
    (root / "note.pdf").write_bytes(b"the edited bytes, which are longer than before")
    assert discover_module.reenter_changed(store, generation=1, at_ns=7) == 1
    reader = _reader(tmp_path)
    row = reader.execute(
        "SELECT state, part_count, stale_since, acq_attempts_total FROM unit WHERE unit_uri = ?",
        (uri,),
    )
    assert row.fetchone() == ("discovered", None, 7, 0)
    assert reader.execute("SELECT count(*) FROM work").fetchone() == (0,)
    assert acquire_pending(store, generation=1, indexed_at_ns=LATE_NS).acquired == 1


def test_a_reentry_keeps_the_first_stale_stamp_and_skips_a_vanished_file(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """08:1891: `stale_since` is set on the first transition only, since it measures how long the
    answer has been untrustworthy. A file that no longer stats is the deletion sweep's, not this."""
    root = tmp_path / "src"
    uri = _settled(store, tmp_path, root, "note.pdf")
    reader = _reader(tmp_path)
    reader.execute("UPDATE unit SET stale_since = 3 WHERE unit_uri = ?", (uri,))
    reader.commit()
    (root / "note.pdf").write_bytes(b"the edited bytes, which are longer than before")
    assert discover_module.reenter_changed(store, generation=1, at_ns=9) == 1
    row = _reader(tmp_path).execute("SELECT stale_since FROM unit WHERE unit_uri = ?", (uri,))
    assert row.fetchone() == (3,)
    gone = _settled(store, tmp_path, tmp_path / "other", "gone.pdf")
    (tmp_path / "other" / "gone.pdf").unlink()
    assert discover_module.reenter_changed(store, generation=1, at_ns=9) == 0
    row = _reader(tmp_path).execute("SELECT state FROM unit WHERE unit_uri = ?", (gone,))
    assert row.fetchone() == ("settled",)


def _doc(
    reader: Any, doc_ord: int, uri: str, key: str, *, fmt: str = "pdf", block: bool = False
) -> None:
    """One `doc` row whose `doc_key` is `key` (32 hex digits), and optionally one live block and
    one live segment at its head generation."""
    reader.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "format_evidence, source_bytes, gen, status, model_version, declared, achieved, x) "
        "VALUES(?, ?, X'00', ?, 'application/pdf', ?, '{}', 1, 1, 'ok', '1.1', '{}', '{}', "
        "'{\"x.ow.decrypted\": true}')",
        (doc_ord, bytes.fromhex(key), uri, fmt),
    )
    if not block:
        return
    code = {
        (domain, name): int(ord_)
        for domain, name, ord_ in reader.execute("SELECT domain, name, ord FROM enum_val")
    }
    reader.execute(
        "INSERT OR IGNORE INTO producer(producer_id, operator, op_version, code_fingerprint, "
        "options_digest) VALUES(1, 'op.parse', 1, 'fp', X'00')"
    )
    reader.execute(
        "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(?, 1, 1, ?, ?, 1)",
        (doc_ord, code[("page_kind", "page")], code[("method", "native")]),
    )
    reader.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, label, "
        "text, content_digest, os_kind, producer_id, method, trust, quote, origin_operator, "
        "origin_driver, driver_schema_v, restriction_bits, state) VALUES(?, ?, 1, 1, 'p1/1', ?, "
        "1, ?, ?, NULL, 'old text', X'00', ?, 1, ?, 2, 4, 'op.parse', 'drv', 1, 0, 0)",
        (
            doc_ord * 10,
            doc_ord,
            f"d{doc_ord}#1",
            code[("kind", "paragraph")],
            code[("layer", "body")],
            code[("origin_span_kind", "none")],
            code[("method", "native")],
        ),
    )
    reader.execute(
        "INSERT OR IGNORE INTO segmenter(segmenter_id, driver_id, driver_schema_v, params_digest) "
        "VALUES(1, 'derive.segment.spine', 1, X'00')"
    )
    reader.execute(
        "INSERT INTO segment(segment_id, doc_ord, gen, ord, segmenter_id, layer, heading_path, "
        "n_blocks, n_tokens, n_chars, tokenizer_id, first_page, last_page, trust, quote_min, "
        "kind_mask, content_digest, origin_operator, origin_driver, driver_schema_v) "
        "VALUES(?, ?, 1, 1, 1, ?, '[]', 1, 2, 8, 'tok', 1, 1, 2, 4, 1, X'00', 'op.derive', "
        "'derive.segment.spine', 1)",
        (doc_ord * 10, doc_ord, code[("layer", "body")]),
    )


@pytest.mark.parametrize(("same_bytes", "reentered"), [(True, 0), (False, 1)])
def test_a_file_only_too_recent_to_prove_fresh_is_hashed_and_not_parsed(
    store: ow.StoreThread, tmp_path: Path, same_bytes: bool, reentered: int
) -> None:
    """D645. A file indexed within 2 s of its `mtime` fails `stat_fresh` with its size and `mtime`
    unchanged, so every file indexed right after it was written would be parsed again. Its raw
    bytes are hashed against the head document's `source_sha256` instead: equal, and only its
    index time moves, so the next pass is free; different, and it is read again."""
    import hashlib  # noqa: PLC0415 -- this test's own

    root = tmp_path / "src"
    uri = _settled(store, tmp_path, root, "note.pdf")
    reader = _reader(tmp_path)
    mtime, digest = reader.execute(
        "SELECT mtime_ns, content_sha256 FROM unit WHERE unit_uri = ?", (uri,)
    ).fetchone()
    reader.execute("UPDATE unit SET indexed_at_ns = ? WHERE unit_uri = ?", (mtime, uri))
    raw = hashlib.sha256((root / "note.pdf").read_bytes()).hexdigest()
    _doc(reader, 1, uri, digest[:32])
    reader.execute(
        "UPDATE doc SET source_sha256 = ? WHERE doc_ord = 1",
        (bytes.fromhex(raw if same_bytes else "00" * 32),),
    )
    reader.commit()
    assert discover_module.reenter_changed(store, generation=1, at_ns=LATE_NS) == reentered
    row = (
        _reader(tmp_path)
        .execute("SELECT state, indexed_at_ns FROM unit WHERE unit_uri = ?", (uri,))
        .fetchone()
    )
    assert row == (("settled", LATE_NS) if same_bytes else ("discovered", mtime))
    assert discover_module.reenter_changed(store, generation=1, at_ns=LATE_NS) == 0


def test_settling_the_new_bytes_is_what_ends_the_stale_time(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D645. 08:1891 keeps `stale_since` across a reset: a retry, a failure and a re-open leave
    it. The new bytes settling is the one write that clears it (`parse.SETTLED_SQL`)."""
    from omniweave.run.operators.parse import SETTLED_SQL  # noqa: PLC0415 -- this test's own

    uri = _settled(store, tmp_path, tmp_path / "src", "note.pdf")
    reader = _reader(tmp_path)
    reader.execute("UPDATE unit SET state = 'planned', stale_since = 3 WHERE unit_uri = ?", (uri,))
    reader.execute(SETTLED_SQL, {"unit_uri": uri, "gen": 2})
    reader.commit()
    row = _reader(tmp_path).execute(
        "SELECT state, settled_gen, stale_since FROM unit WHERE unit_uri = ?", (uri,)
    )
    assert row.fetchone() == ("settled", 2, None)


OLD, NEW, COPY = "aa" * 16, "bb" * 16, "cc" * 16


def _unit_with(reader: Any, uri: str, digest: str | None, *, state: str = "settled") -> None:
    reader.execute(
        "INSERT INTO unit(unit_uri, state, last_seen_gen, trust_class, content_sha256) "
        "VALUES(?, ?, 1, 'internal', ?)",
        (uri, state, None if digest is None else digest + "0" * 32),
    )


def test_the_version_an_edit_replaced_leaves_every_read_and_its_cite_still_resolves(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D645. A document is its bytes (03:162), so an edited file is a new document and the old one
    kept answering with what the file used to say. It is retired the way `rebind()` retires a row:
    `state = 1` and a `block_history` row (`source_deleted`, no successor), its segment with it, and
    `doc.x` says so. Nothing is deleted, and a second pass retires nothing more."""
    reader = _reader(tmp_path)
    _unit_with(reader, "c:/docs/note.pdf", NEW)
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    _doc(reader, 2, "c:/docs/note.pdf", NEW)
    reader.commit()
    assert discover_module.retire_replaced(store) == 1
    reader = _reader(tmp_path)
    assert reader.execute("SELECT block_id, state FROM block").fetchall() == [(10, 1)]
    assert reader.execute("SELECT state FROM segment").fetchall() == [(1,)]
    assert reader.execute("SELECT * FROM block_history").fetchall() == [
        (10, 1, 1, None, "source_deleted")
    ]
    xs = dict(reader.execute("SELECT doc_ord, x FROM doc").fetchall())
    assert json.loads(xs[1]) == {
        "x.ow.decrypted": True,
        "x.ow.retired": {"reason": "source_deleted", "gen": 1},
    }
    assert json.loads(xs[2]) == {"x.ow.decrypted": True}
    assert discover_module.retire_replaced(store) == 0


def _graph(reader: Any) -> dict[str, list[tuple[Any, ...]]]:
    return {
        "anchor": reader.execute("SELECT doc_ord, name_norm FROM anchor ORDER BY 1").fetchall(),
        "ref_site": reader.execute("SELECT doc_ord, name_norm FROM ref_site ORDER BY 1").fetchall(),
        "block_link": reader.execute(
            "SELECT src_block, dst_block, bound_by FROM block_link ORDER BY 1, 2"
        ).fetchall(),
    }


def _references(reader: Any) -> None:
    """Document 1 (block 10) defines `section 1`; document 2 (block 20) references it and is
    linked to it; document 1 references document 2's corpus identifier and is linked to it."""
    reader.execute(
        "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, "
        "granularity, card_sha256, schema_version) VALUES('derive.anchor.native', 'derive/1', "
        "'free', 0, 20, '[\"anchor\"]', 'document', 'sha', 1)"
    )
    reader.execute(
        "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
        "origin_operator, origin_driver, driver_schema_v, cost_class, input_digest, cache_key, "
        "status) VALUES(1, NULL, 'derive.anchor.native', 1, 1, 0, 'derive.anchor.native', "
        "'derive.anchor.native', 1, 'free', X'00', 'k', 'ok')"
    )
    reader.execute(
        "INSERT INTO anchor(doc_ord, gen, name_norm, akind, surface, block_id, scope, run_id) "
        "VALUES(1, 1, '1', 'section', '1', 10, 'corpus', 1), "
        "(2, 1, 'gl_4471', 'identifier', 'GL-4471', 20, 'corpus', 1)"
    )
    reader.execute(
        "INSERT INTO ref_site(name_norm, akind, doc_ord, block_id, ts_a, ts_b, surface, scope, "
        "origin_operator) VALUES('1', 'section', 2, 20, 0, 9, 'Section 1', 'document', 'x'), "
        "('gl_4471', 'identifier', 1, 10, 0, 7, 'GL-4471', 'document', 'x')"
    )
    reader.execute(
        "INSERT INTO block_link(src_block, dst_block, relation, site_block, bound_by, "
        "producer_id, trust, origin_operator, origin_driver, driver_schema_v) "
        "VALUES(20, 10, 'refers_to', 20, '1', 1, 2, 'x', 'x', 1), "
        "(10, 20, 'refers_to', 10, 'gl_4471', 1, 2, 'x', 'x', 1)"
    )


def test_the_version_an_edit_replaced_leaves_the_reference_graph_in_the_same_unit(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D673. A retired document whose anchors still resolved kept binding references to tombstoned
    blocks, and its occurrences stayed in `ref_unresolved` one copy per edit. Retiring it now takes
    its anchors, its occurrences and every link either makes out of the live graph."""
    reader = _reader(tmp_path)
    _unit_with(reader, "c:/docs/note.pdf", NEW)
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    _unit_with(reader, "c:/docs/other.pdf", COPY)
    _doc(reader, 2, "c:/docs/other.pdf", COPY, block=True)
    _references(reader)
    reader.commit()
    assert discover_module.retire_replaced(store) == 1
    assert _graph(_reader(tmp_path)) == {
        "anchor": [(2, "gl_4471")],
        "ref_site": [(2, "1")],
        "block_link": [],
    }
    assert _reader(tmp_path).execute("SELECT name_norm FROM ref_unresolved").fetchall() == [("1",)]


def test_a_document_retired_before_the_unbind_existed_is_unbound_on_the_next_pass(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D673. A store whose documents were retired by D645 alone still holds their reference rows;
    the next `retire_replaced` takes them out, though it retires nothing new."""
    reader = _reader(tmp_path)
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    _unit_with(reader, "c:/docs/other.pdf", COPY)
    _doc(reader, 2, "c:/docs/other.pdf", COPY, block=True)
    _references(reader)
    reader.execute(
        "UPDATE doc SET x = json_set(x, '$.\"x.ow.retired\"', json_object('reason', "
        "'source_deleted', 'gen', 1)) WHERE doc_ord = 1"
    )
    reader.execute("UPDATE block SET state = 1 WHERE doc_ord = 1")
    reader.commit()
    assert discover_module.retire_replaced(store) == 0
    assert _graph(_reader(tmp_path))["anchor"] == [(2, "gl_4471")]
    assert _graph(_reader(tmp_path))["block_link"] == []


def _owned_entity(reader: Any) -> None:
    """Document 1 (block 10, segment 10) owns the defined term `lender`, mentioned once."""
    reader.execute(
        "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, "
        "granularity, card_sha256, schema_version) VALUES('derive.anchor.defterm', 'derive/1', "
        "'free', 0, 30, '[\"entity\"]', 'document', 'sha', 1)"
    )
    reader.execute(
        "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
        "origin_operator, origin_driver, driver_schema_v, cost_class, input_digest, cache_key, "
        "status) VALUES(7, NULL, 'derive.anchor.defterm', 1, 1, 0, 'derive.anchor.defterm', "
        "'derive.anchor.defterm', 1, 'free', X'00', 'k', 'ok')"
    )
    reader.execute(
        "INSERT INTO entity(entity_id, cite, scope, etype, key, title, canonical_id, "
        "resolution_method, trust, mention_digest) "
        "VALUES(1, 'e1', 1, 'defined_term', 'lender', 'Lender', 1, 0, 2, X'00')"
    )
    reader.execute(
        "INSERT INTO mention(entity_id, block_id, segment_id, ts_a, ts_b, surface, run_id, trust, "
        "digest) VALUES(1, 10, 10, 0, 4, 'text', 7, 2, X'00')"
    )


def _entity_states(reader: Any) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    return (
        reader.execute("SELECT entity_id, state FROM entity").fetchall(),
        reader.execute("SELECT entity_id, state FROM mention").fetchall(),
    )


def test_the_replaced_versions_defined_terms_are_retired_with_it(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D675. An edited file's old version kept its defined terms as live entities, so a store built
    through an edit held each of them twice; GR8's projection is what saw it."""
    reader = _reader(tmp_path)
    _unit_with(reader, "c:/docs/note.pdf", NEW)
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    _owned_entity(reader)
    reader.commit()
    assert discover_module.retire_replaced(store) == 1
    assert _entity_states(_reader(tmp_path)) == ([(1, 2)], [(1, 1)])


def test_a_retired_document_holding_only_entities_is_swept(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D675. The sweep's own condition: no anchor, no occurrence and no live mention -- the mention
    was orphaned already -- only a live entity the document owns."""
    reader = _reader(tmp_path)
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    _owned_entity(reader)
    reader.execute("UPDATE mention SET state = 1")
    reader.execute(
        "UPDATE doc SET x = json_set(x, '$.\"x.ow.retired\"', json_object('reason', "
        "'source_deleted', 'gen', 1)) WHERE doc_ord = 1"
    )
    reader.commit()
    assert discover_module.retire_replaced(store) == 0
    assert _entity_states(_reader(tmp_path)) == ([(1, 2)], [(1, 1)])


def test_retire_document_alone_takes_a_deleted_document_out_of_the_reads_and_the_graph(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D678. `ow store rm --doc` will issue `retire_document` and no `retire_replaced` follows it,
    so the function must do the whole of 06:2335's deletion row by itself -- not lean on the next
    pass's sweep for the retired, which would repair a half-done retirement and hide it. GR8's
    deletions run it exactly so: one transaction, then nothing."""
    del store  # the fixture creates the store; the function runs on a bare connection
    reader = _reader(tmp_path)
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    _doc(reader, 2, "c:/docs/other.pdf", COPY, block=True)
    _references(reader)
    _owned_entity(reader)
    reader.commit()
    discover_module.retire_document(reader, 1, 1)
    reader.commit()
    after = _reader(tmp_path)
    assert after.execute("SELECT doc_ord, state FROM block ORDER BY 1").fetchall() == [
        (1, 1),
        (2, 0),
    ]
    assert after.execute("SELECT block_id, reason FROM block_history").fetchall() == [
        (10, "source_deleted")
    ]
    assert _graph(after) == {"anchor": [(2, "gl_4471")], "ref_site": [(2, "1")], "block_link": []}
    assert _entity_states(after) == ([(1, 2)], [(1, 1)])
    retired = after.execute("SELECT json_extract(x, '$.\"x.ow.retired\".reason') FROM doc")
    assert retired.fetchall() == [("source_deleted",), (None,)]


# ---------------------------------------------------------------------------------------------
# D679: a settled unit whose parse driver moved its key is read again
# ---------------------------------------------------------------------------------------------

DRIVER = "parse.office.anydoc"
DIGEST = "aa" * 32


def _parsed(
    reader: Any, doc_ord: int, uri: str, key: str, *, version: int = 1, digest: str = DIGEST
) -> None:
    """A settled unit, its live document, and the parse that wrote it: the head page's producer
    is `(parse.office, version, digest)` and a `done` routed row names the driver."""
    _unit_with(reader, uri, key)
    _doc(reader, doc_ord, uri, key, block=True)
    reader.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest) "
        "VALUES(?, 'parse.office', ?, '', ?)",
        (100 + doc_ord, version, bytes.fromhex(digest)),
    )
    reader.execute("UPDATE page SET producer_id = ? WHERE doc_ord = ?", (100 + doc_ord, doc_ord))
    reader.execute(
        "INSERT OR IGNORE INTO route_evidence(evidence_digest, payload, first_seen_at) "
        "VALUES('ev', X'00', 1)"
    )
    reader.execute(
        "INSERT OR IGNORE INTO route_decision(decision_id, content_sha256, unit_part, lane, rung, "
        "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
        "rule_id, rule_origin, cause, reason, slice_key, evidence_digest, est_spend, est_micros, "
        "reserved_micros, admission, generation, decided_at) VALUES('dec_p', 'c0', '', 'text', 0, "
        "'pd', '', '', '', ?, 'free', 'decode.office-native', 'builtin', '', '', '', 'ev', '{}', "
        "0, 0, 'admitted', 1, 1)",
        (DRIVER,),
    )
    reader.execute(
        "INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, "
        "status, priority, driver, decision_id, dispatch_key) VALUES(?, '', 'parse.office', ?, "
        "'k', 'free', 'done', 200, ?, 'dec_p', 'dk')",
        (uri, version, DRIVER),
    )


def _units(reader: Any) -> list[tuple[Any, ...]]:
    return reader.execute("SELECT unit_uri, state, stale_since FROM unit ORDER BY 1").fetchall()


def test_a_unit_parsed_under_the_drivers_current_key_is_left_alone(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D679. The common case, every `ow add`: the key matches, nothing is read again."""
    reader = _reader(tmp_path)
    _parsed(reader, 1, "c:/docs/note.pdf", OLD)
    reader.commit()
    assert discover_module.reenter_reparsed(store, {DRIVER: (1, DIGEST)}, generation=1) == 0
    assert _units(_reader(tmp_path)) == [("c:/docs/note.pdf", "settled", None)]


@pytest.mark.parametrize(
    "now",
    [(1, "bb" * 32), (2, DIGEST)],
    ids=["its-config-moved", "its-schema-version-moved"],
)
def test_a_unit_whose_parse_driver_moved_its_key_is_read_again(
    store: ow.StoreThread, tmp_path: Path, now: tuple[int, str]
) -> None:
    """D679, 08:1550's two rows that re-parse: a semantic config change and a `schema_version`
    bump. The unit goes back to `discovered` with its terminal work rows cleared, as D645's
    re-entry does; its document stays live until the new parse settles; and `stale_since` is not
    set, because the answer is not older than the file -- another driver made it."""
    reader = _reader(tmp_path)
    _parsed(reader, 1, "c:/docs/note.pdf", OLD)
    reader.commit()
    assert discover_module.reenter_reparsed(store, {DRIVER: now}, generation=1) == 1
    after = _reader(tmp_path)
    assert _units(after) == [("c:/docs/note.pdf", "discovered", None)]
    assert after.execute("SELECT count(*) FROM work").fetchall() == [(0,)]
    assert after.execute("SELECT count(*) FROM block WHERE state = 0").fetchall() == [(1,)]


def test_a_driver_this_run_does_not_hold_re_parses_nothing(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """There is nothing to re-parse with. Routing answers a driver that went away."""
    reader = _reader(tmp_path)
    _parsed(reader, 1, "c:/docs/note.pdf", OLD)
    reader.commit()
    assert discover_module.reenter_reparsed(store, {}, generation=1) == 0
    assert _units(_reader(tmp_path))[0][1] == "settled"


def test_only_the_units_this_walk_saw_are_asked(store: ow.StoreThread, tmp_path: Path) -> None:
    """`ow add docs/a` does not re-parse `docs/b`: a unit not seen this generation is outside the
    command's scope, as it is for `reenter_changed`."""
    reader = _reader(tmp_path)
    _parsed(reader, 1, "c:/docs/note.pdf", OLD)
    reader.commit()
    assert discover_module.reenter_reparsed(store, {DRIVER: (2, DIGEST)}, generation=2) == 0


def test_every_page_of_units_is_asked(store: ow.StoreThread, tmp_path: Path) -> None:
    """Paged by unit at `plan_batch`: a moved unit on the second page is found, and a unit with
    two keys -- two producers on its head pages -- is never split across two pages."""
    reader = _reader(tmp_path)
    _parsed(reader, 1, "c:/docs/a.pdf", OLD)
    _parsed(reader, 2, "c:/docs/b.pdf", COPY, digest="bb" * 32)
    reader.commit()
    assert (
        discover_module.reenter_reparsed(store, {DRIVER: (1, DIGEST)}, generation=1, plan_batch=1)
        == 1
    )
    assert [state for _uri, state, _stale in _units(_reader(tmp_path))] == [
        "settled",
        "discovered",
    ]


def _runs_on_one_segment(reader: Any) -> None:
    """Segment 10 of document 1, kept across a re-parse: the table Pass ran on it at generation 1
    (run 21) and again at 2 (run 22), and defterm once (run 23, generation 1). `derive_run`'s
    identity is one run per Pass, Segment and generation. Each run wrote one mention of entity 1
    and one claim about it."""
    _doc(reader, 1, "c:/docs/note.pdf", OLD, block=True)
    reader.execute(
        "INSERT INTO entity(entity_id, cite, scope, etype, key, title, canonical_id, "
        "resolution_method, trust, mention_digest) "
        "VALUES(1, 'e1', 0, 'org', 'acme', 'Acme', 1, 0, 2, X'00')"
    )
    for pass_id in ("derive.entity.table", "derive.anchor.defterm"):
        reader.execute(
            "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, "
            "granularity, card_sha256, schema_version) VALUES(?, 'derive/1', 'free', 0, 20, "
            "'[\"entity\"]', 'document', 'sha', 1)",
            (pass_id,),
        )
    for run_id, pass_id, gen in ((21, "derive.entity.table", 1), (22, "derive.entity.table", 2),
                                 (23, "derive.anchor.defterm", 1)):  # fmt: skip
        reader.execute(
            "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
            "origin_operator, origin_driver, driver_schema_v, cost_class, input_digest, "
            "cache_key, status) VALUES(?, 10, ?, ?, 1, 0, ?, ?, 1, 'free', X'00', 'k', 'ok')",
            (run_id, pass_id, gen, pass_id, pass_id),
        )
        reader.execute(
            "INSERT INTO mention(entity_id, block_id, segment_id, ts_a, ts_b, surface, run_id, "
            "trust, digest) VALUES(1, 10, 10, 0, 4, 'Acme', ?, 2, ?)",
            (run_id, bytes([run_id]) * 16),
        )
        reader.execute(
            "INSERT INTO claim(claim_id, cite, subject_entity, object_literal, object_datatype, "
            "claim_type, predicate, description, status, observed_block, ts_a, ts_b, quote_tier, "
            "run_id, trust) VALUES(?, ?, 1, '17', 'string', 'attribute', 'units', 'd', "
            "'asserted', 10, 0, 2, 4, ?, 2)",
            (run_id, f"k{run_id}", run_id),
        )


def test_a_passes_later_run_retires_its_earlier_runs_rows_on_the_segment(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D681, 08 section 4.8's owner-scoped replacement: run 22 retires run 21's claim and mention
    to `graph_history` as `pass_replaced`, keeps its own, and leaves defterm's run 23 alone."""
    from omniweave.run.converge import Replaced, replace_prior_runs  # noqa: PLC0415

    del store
    reader = _reader(tmp_path)
    _runs_on_one_segment(reader)
    reader.commit()
    before = reader.execute("SELECT mention_digest FROM entity").fetchone()
    assert replace_prior_runs(reader, 22) == Replaced(runs=1, claims=1, edges=0, mentions=1)
    reader.commit()
    after = _reader(tmp_path)
    assert after.execute("SELECT run_id FROM claim ORDER BY 1").fetchall() == [(22,), (23,)]
    assert after.execute("SELECT run_id FROM mention ORDER BY 1").fetchall() == [(22,), (23,)]
    assert after.execute(
        "SELECT kind, row_id, retired_gen, reason, json_extract(payload, '$.run_id') "
        "FROM graph_history ORDER BY 1"
    ).fetchall() == [("claim", 21, 2, "pass_replaced", 21), ("mention", 1, 2, "pass_replaced", 21)]
    assert after.execute("SELECT mention_digest FROM entity").fetchone() != before
    assert replace_prior_runs(after, 22) == Replaced(runs=1, claims=0, edges=0, mentions=0), (
        "idempotent: a second call finds the run and nothing left of it"
    )


def test_the_first_run_on_a_segment_replaces_nothing(store: ow.StoreThread, tmp_path: Path) -> None:
    from omniweave.run.converge import Replaced, replace_prior_runs  # noqa: PLC0415

    del store
    reader = _reader(tmp_path)
    _runs_on_one_segment(reader)
    reader.commit()
    assert replace_prior_runs(reader, 23) == Replaced(runs=0, claims=0, edges=0, mentions=0)
    assert replace_prior_runs(reader, 99) == Replaced(runs=0, claims=0, edges=0, mentions=0)


def test_a_version_some_file_still_holds_is_not_retired(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """The three cases the scan exists to leave alone: a copy of the old bytes in another file; a
    deleted file, whose unit is `out_of_scope` with its digest kept, since 05:370 and 08:1883 make
    a deletion explicit and never inferred; and a document no unit rostered, or a job document."""
    reader = _reader(tmp_path)
    _unit_with(reader, "c:/docs/a.pdf", NEW)
    _unit_with(reader, "c:/docs/copy-of-a.pdf", COPY)
    _doc(reader, 1, "c:/docs/a.pdf", COPY)
    _unit_with(reader, "c:/docs/deleted.pdf", OLD, state="out_of_scope")
    _doc(reader, 2, "c:/docs/deleted.pdf", OLD)
    _doc(reader, 3, "c:/kit/fixture.pdf", "dd" * 16)
    _unit_with(reader, "c:/docs/b.pdf", NEW)
    _doc(reader, 4, "c:/docs/b.pdf", "ee" * 16, fmt="owjob")
    _unit_with(reader, "c:/docs/unread.pdf", None)
    _doc(reader, 5, "c:/docs/unread.pdf", "ff" * 16)
    reader.commit()
    assert discover_module.retire_replaced(store) == 0


def test_a_reopen_clears_the_attempt_count_so_the_fourth_read_still_happens(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """D643. `PENDING_ACQUISITION_SQL` stops at `MAX_ATTEMPTS_TODAY` and nothing lowered the count,
    so a file re-opened for the third time was never read again, and gate 5 held it for ever.
    Found on the password path: three passwords tried, and the right one never read."""
    root = tmp_path / "src"
    uri = _refused(store, tmp_path, root, "masked.docx")
    reader = _reader(tmp_path)
    reader.execute("UPDATE unit SET acq_attempts_total = 3 WHERE unit_uri = ?", (uri,))
    reader.commit()
    (root / "masked.docx").write_bytes(b"the restored bytes, which are longer")
    assert reopen_changed_failures(store, generation=1) == 1
    assert acquire_pending(store, generation=1, indexed_at_ns=LATE_NS).acquired == 1
    row = _reader(tmp_path).execute(
        "SELECT acq_attempts_total FROM unit WHERE unit_uri = ?", (uri,)
    )
    assert row.fetchone() == (1,)


def test_a_reopen_leaves_a_live_work_row_and_another_generation_alone(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """Only terminal rows go: a `pending` row belongs to a run in flight. And only the units this
    generation's walk saw are surveyed, as `STALE_SCAN_SQL` surveys them."""
    root = tmp_path / "src"
    uri = _refused(store, tmp_path, root, "masked.docx")
    reader = _reader(tmp_path)
    reader.execute(
        "INSERT INTO work(unit_uri, operator, op_version, cache_key, cost_class, status) "
        "VALUES(?, 'op.converge', 1, 'k', 'free', 'pending')",
        (uri,),
    )
    reader.commit()
    (root / "masked.docx").write_bytes(b"the restored bytes, which are longer")
    assert reopen_changed_failures(store, generation=2) == 0
    assert reopen_changed_failures(store, generation=1) == 1
    rows = _reader(tmp_path).execute("SELECT operator, status FROM work").fetchall()
    assert rows == [("op.converge", "pending")]


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
