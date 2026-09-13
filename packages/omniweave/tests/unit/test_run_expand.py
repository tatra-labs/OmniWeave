"""`op.identify`: the NULL routing triple, the cache key with no card, and one transaction.

The load-bearing test in this file is
`test_the_part_count_and_the_work_transition_commit_or_roll_back_together`. It runs a real
`SqliteStore` with `IdentifyLedger` wired in as the `derived_rows` contribution, claims the row,
completes it, and asserts both writes landed. The torn state it rules out is the one that cannot be
repaired: `work.status='done'` with `unit.part_count` still NULL leaves a unit in `acquired` with no
queue row that will ever move it again.

Three things are transcriptions rather than inventions:

* the three routing columns' CHECKs are read off `0004_runtime.sql` and exercised against a real
  store in both directions -- an `op.` row with a `decision_id` is refused, and a `parse.` row
  without one is refused;
* `05:2135`'s three `unit.part_count` providers are compared against `PART_COUNT_PROVIDERS`;
* `08:619`'s priority table is parsed for `op.identify`'s number.

## The test that is a defect report

`test_the_per_part_work_rows_this_module_does_not_write_could_not_exist_yet` shows why `02:474`'s
bold *"No `parse.pdf` work row exists yet"* wins over `03:589`'s claim that `op.identify` writes the
per-part `work` rows: the row 03 describes fails a CHECK. **D167.**
"""

from __future__ import annotations

import re
import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import omniweave_core.store.sqlite as ow
import pytest
from omniweave.run.discover import ACQUIRED, WALKED_PATH_KEY
from omniweave.run.expand import (
    IDENTIFIED_SQL,
    IDENTIFY_FAILED_SQL,
    IDENTIFY_INSERT_SQL,
    MAX_PENDING_IDENTIFICATIONS,
    OP_IDENTIFY,
    OP_IDENTIFY_COST_CLASS,
    OP_IDENTIFY_PRIORITY,
    OP_IDENTIFY_VERSION,
    PART_COUNT_PROVIDERS,
    PART_COUNT_SIGNAL,
    PENDING_IDENTIFY_SQL,
    UNIDENTIFIED_PART,
    IdentifyLedger,
    PartCount,
    counted,
    enqueue,
    identify,
    identify_key,
    identity,
    pending_params,
    row_params,
    salt_for,
    single_part,
)
from omniweave_core.errors import RouteError
from omniweave_core.events import EVENTS, EventKind
from omniweave_core.operator import Outcome, StepResult
from omniweave_core.store import migrate
from omniweave_core.store.queue import COMPLETE_PARTICIPANTS, SqliteStore
from omniweave_ports.types import DriverError, FailureClass, UnitRef

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from conftest import PlanDocs
    from omniweave_core.operator import RunContext


DIGEST = "9f" * 32


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1_700_000_000_000_000_000)
    finally:
        connection.close()
    return path


@pytest.fixture
def thread(store_path: Path) -> Iterator[ow.StoreThread]:
    with ow.StoreThread(lambda: ow.connect(store_path)) as handle:
        yield handle


def _conn(store_path: Path) -> Any:
    """A connection for setup and read-back. `Any` because TID251 bans naming `sqlite3` here."""
    return ow.connect(store_path)


def _unit_row(conn: Any, uri: str, *, state: str = ACQUIRED, gen: int = 1, **extra: object) -> None:
    columns = {
        "unit_uri": uri,
        "connector": "fs",
        "state": state,
        "trust_class": "internal",
        "last_seen_gen": gen,
        "content_sha256": DIGEST,
        "bytes": 10,
        **extra,
    }
    names = ", ".join(columns)
    holes = ", ".join(f":{name}" for name in columns)
    conn.execute(f"INSERT INTO unit({names}) VALUES({holes})", columns)


def _ref(uri: str = "c:/x/a.pdf") -> UnitRef:
    return counted(uri, DIGEST, 10)


def _ctx(semantic_digest: str = "sem-1") -> RunContext:
    """The one `RunContext` attribute `cache_key()` reads, cast once rather than ignored four times.

    `RunContext` carries a services registry, a cancel token, a clock and five digests; building
    one here would be constructing the Supervisor to test a digest. `cast` at the seam is the
    honest spelling of "this stands in for the one attribute that is read".
    """
    return cast("RunContext", SimpleNamespace(semantic_digest=semantic_digest))


# ---------------------------------------------------------------------------------------------
# 1. The three columns that make the row core-only
# ---------------------------------------------------------------------------------------------


def test_the_identify_row_leaves_the_routing_triple_null(store_path: Path) -> None:
    """02:474: *"`driver`, `decision_id`, `dispatch_key` all NULL, `cost_class='free'`."*"""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf")
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/a.pdf", "0" * 64))
    row = connection.execute(
        "SELECT operator, op_version, driver, decision_id, dispatch_key, cost_class, "
        "unit_part, status, priority FROM work"
    ).fetchone()
    connection.close()
    assert row == (
        OP_IDENTIFY,
        OP_IDENTIFY_VERSION,
        None,
        None,
        None,
        OP_IDENTIFY_COST_CLASS,
        UNIDENTIFIED_PART,
        "pending",
        OP_IDENTIFY_PRIORITY,
    )


def test_an_op_row_carrying_a_decision_id_is_refused_by_the_check(store_path: Path) -> None:
    """The CHECK is what makes the omission mandatory rather than tidy."""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            "INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, "
            "status, decision_id) VALUES('c:/x/a.pdf', '', 'op.identify', 1, 'k', 'free', "
            "'pending', 'd1')"
        )
    connection.close()


def test_the_per_part_work_rows_this_module_does_not_write_could_not_exist_yet(
    store_path: Path,
) -> None:
    """03:589 gives `op.identify` the per-part rows; 02:474 says in bold they do not. **D167.**

    The row 03 describes -- `operator='parse.pdf'` with the routing triple still NULL, because no
    `route_decision` has been made -- fails `CHECK ((operator LIKE 'op.%') = (decision_id IS
    NULL))`. So it is not a question of preference: the schema refuses it.
    """
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            "INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, "
            "status) VALUES('c:/x/a.pdf', 'p1', 'parse.pdf', 1, 'k', 'free', 'pending')"
        )
    connection.close()


def test_a_second_enqueue_of_one_unit_writes_nothing(store_path: Path) -> None:
    """`work_identity` plus `DO NOTHING`: 08:503's resume re-streams the roster, and must not
    double-enqueue."""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf")
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/a.pdf", "0" * 64))
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/a.pdf", "1" * 64))
    rows = connection.execute("SELECT cache_key FROM work").fetchall()
    connection.close()
    assert rows == [("0" * 64,)], "DO NOTHING, not DO UPDATE: the first key stands"


def test_the_empty_unit_part_is_what_lets_work_identity_hold(store_path: Path) -> None:
    """0004:93: *"`''` folds NULL: NULLs are distinct in a UNIQUE index."*"""
    assert UNIDENTIFIED_PART == ""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf")
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/a.pdf", "0" * 64))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute(
            "INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, "
            "status) VALUES('c:/x/a.pdf', '', 'op.identify', 1, 'k2', 'free', 'pending')"
        )
    connection.close()


# ---------------------------------------------------------------------------------------------
# 2. The queue query
# ---------------------------------------------------------------------------------------------


def test_the_pending_query_selects_acquired_uncounted_units_that_have_no_row_yet(
    store_path: Path,
) -> None:
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/wanted.pdf")
        _unit_row(connection, "c:/x/counted.pdf", part_count=3)
        _unit_row(connection, "c:/x/early.pdf", state="discovered")
        _unit_row(connection, "c:/x/other-gen.pdf", gen=0)
        _unit_row(connection, "c:/x/enqueued.pdf")
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/enqueued.pdf", "0" * 64))
    rows = connection.execute(PENDING_IDENTIFY_SQL, pending_params(generation=1)).fetchall()
    connection.close()
    assert [row[0] for row in rows] == ["c:/x/wanted.pdf"]


def test_the_pending_query_names_the_state_discover_declares() -> None:
    """Two halves of one state machine, one constant."""
    assert f"u.state = '{ACQUIRED}'" in PENDING_IDENTIFY_SQL
    assert f"state = '{ACQUIRED}'" in IDENTIFIED_SQL
    assert f"state = '{ACQUIRED}'" in IDENTIFY_FAILED_SQL


def test_a_compacted_identify_row_is_not_re_enqueued_by_the_part_count_clause(
    store_path: Path,
) -> None:
    """`work_done` archives the row; `part_count IS NULL` is what keeps the query correct after."""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf", part_count=42, state="identified")
    rows = connection.execute(PENDING_IDENTIFY_SQL, pending_params(generation=1)).fetchall()
    connection.close()
    assert rows == []


# ---------------------------------------------------------------------------------------------
# 3. `enqueue`: batching under the water mark
# ---------------------------------------------------------------------------------------------


class _Recorder:
    """A `StoreThread` stand-in recording one entry per transaction."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def run(self, unit: object, *, timeout_s: float | None = None) -> object:
        del timeout_s
        sizes: list[int] = []

        class _Conn:
            def executemany(self, sql: str, parameters: Sequence[object], /) -> object:
                del sql
                sizes.append(len(list(parameters)))
                return None

        unit.run(_Conn())  # type: ignore[attr-defined] -- the double's whole job.
        self.batches.append(sum(sizes))
        return None


def _rows(n: int) -> list[dict[str, object]]:
    return [dict(row_params(f"c:/x/{i}.pdf", "0" * 64)) for i in range(n)]


def test_enqueue_commits_at_plan_batch_and_the_tail_rides_alone() -> None:
    recorder = _Recorder()
    written, paused = enqueue(recorder, _rows(10), plan_batch=4)  # type: ignore[arg-type]
    assert (written, paused) == (10, False)
    assert recorder.batches == [4, 4, 2]


def test_enqueue_stops_at_a_transaction_boundary_and_never_mid_batch() -> None:
    """08:875: the producer *"pauses at a safe boundary and never drops"*."""
    recorder = _Recorder()
    written, paused = enqueue(
        recorder,  # type: ignore[arg-type]
        _rows(10),
        plan_batch=4,
        pause=lambda: True,
    )
    assert paused is True
    assert written == 4
    assert recorder.batches == [4]


def test_enqueue_emits_one_plan_expand_per_committed_transaction() -> None:
    recorder = _Recorder()
    seen: list[tuple[str, dict[str, object]]] = []
    enqueue(
        recorder,  # type: ignore[arg-type]
        _rows(9),
        plan_batch=4,
        emit=lambda *, kind, fields: seen.append((str(kind), dict(fields))),
    )
    assert [fields["rows"] for _, fields in seen] == [4, 4, 1]
    for kind, fields in seen:
        assert kind == EventKind.PLAN_EXPAND.value
        assert frozenset(fields) == frozenset(EVENTS[kind].fields)


def test_enqueue_refuses_a_batch_size_below_one() -> None:
    with pytest.raises(ValueError, match="positive row count"):
        enqueue(_Recorder(), [], plan_batch=0)  # type: ignore[arg-type]


def test_enqueue_writes_nothing_for_an_empty_stream() -> None:
    recorder = _Recorder()
    assert enqueue(recorder, [], plan_batch=4) == (0, False)  # type: ignore[arg-type]
    assert recorder.batches == []


# ---------------------------------------------------------------------------------------------
# 4. The counter and its refusals
# ---------------------------------------------------------------------------------------------


def test_the_builtin_counter_answers_one_for_a_document_granularity_unit() -> None:
    """05:3186: *"op.identify -> part_count = 1 (granularity='document' on the card)."*"""
    answer = single_part(_ref(), fmt="docx")
    assert answer.count == 1
    assert answer.provider == "builtin"


def test_a_part_count_refuses_a_negative_and_an_unregistered_provider() -> None:
    with pytest.raises(RouteError, match="is a count"):
        PartCount(count=-1)
    with pytest.raises(RouteError, match="providers"):
        PartCount(count=1, provider="guesswork")


def test_the_three_providers_are_the_plans_three(plan: PlanDocs) -> None:
    plan.require()
    rows = plan.grep(r"^\| `unit\.part_count` \|", documents=("05-ingest-and-routing.md",))
    assert len(rows) == 1
    cells = [cell.strip() for cell in rows[0].text.strip("|").split("|")]
    declared = tuple(part.strip(" `") for part in cells[-1].split("·"))
    assert declared == PART_COUNT_PROVIDERS


def test_a_counter_that_cannot_answer_fails_the_unit_permanently() -> None:
    """A default of 1 for a 400-page scan would route one part and report a complete document."""

    def refuses(unit: UnitRef, *, fmt: str) -> PartCount:
        del unit
        raise DriverError(cls=FailureClass.UNSUPPORTED_FORMAT, message=f"no reader for {fmt}")

    result, answer = identify(_ref(), count=refuses, cache_key_hex="0" * 64, fmt="dwg")
    assert answer is None
    assert result.outcome is Outcome.FAILED_PERMANENT
    assert result.failure_class is FailureClass.UNSUPPORTED_FORMAT
    assert "dwg" in (result.failure_message or "")


def test_a_successful_identification_reports_one_written_row_and_no_price() -> None:
    """INV-15: the runner prices through the `PriceBook`; the operator never does."""
    result, answer = identify(_ref(), count=single_part, cache_key_hex="0" * 64)
    assert result.outcome is Outcome.OK
    assert answer is not None
    assert result.metrics.rows_written == 1, "the `unit` row, not the `work` row"
    assert result.metrics.micros == 0
    assert result.identity.operator == OP_IDENTIFY
    assert result.identity.op_version == OP_IDENTIFY_VERSION


def test_identify_emits_the_part_count_the_event_declares() -> None:
    seen: list[tuple[str, dict[str, object]]] = []
    identify(
        _ref(),
        count=single_part,
        cache_key_hex="0" * 64,
        emit=lambda *, kind, fields: seen.append((str(kind), dict(fields))),
    )
    assert len(seen) == 1
    kind, fields = seen[0]
    assert kind == EventKind.PLAN_IDENTIFY.value
    assert frozenset(fields) == frozenset(EVENTS[kind].fields)
    assert fields["part_count"] == 1


def test_a_failed_identification_emits_no_part_count() -> None:
    def refuses(unit: UnitRef, *, fmt: str) -> PartCount:
        del unit, fmt
        raise DriverError(cls=FailureClass.UNSUPPORTED_FORMAT, message="no")

    seen: list[object] = []
    identify(
        _ref(),
        count=refuses,
        cache_key_hex="0" * 64,
        emit=lambda *, kind, fields: seen.append((kind, fields)),
    )
    assert seen == []


def test_the_spend_signal_key_is_the_one_the_plan_charges_it_under(plan: PlanDocs) -> None:
    """05:1201: *"records its `Spend` on `route_signal` under `unit.part_count`."*"""
    plan.require()
    assert PART_COUNT_SIGNAL == "unit.part_count"
    charged = plan.grep(
        r"`route_signal` under `unit\.part_count` and is charged to acquisition",
        documents=("05-ingest-and-routing.md",),
    )
    assert charged, "05:1203 is what makes the signal key and the payer one string"


# ---------------------------------------------------------------------------------------------
# 5. D164: the cache key of a row with no card
# ---------------------------------------------------------------------------------------------


def test_an_op_identify_row_has_a_cache_key_and_no_card_to_build_it_from() -> None:
    key = identify_key(_ref(), _ctx(), salt="docs/a.pdf")
    assert len(key) == 64
    assert set(key) <= set("0123456789abcdef")


def test_the_key_moves_with_the_salt_the_op_version_and_the_semantic_digest() -> None:
    base = identify_key(_ref(), _ctx(), salt="docs/a.pdf")
    assert base != identify_key(_ref(), _ctx(), salt="other/a.pdf")
    assert base != identify_key(_ref(), _ctx(), salt="docs/a.pdf", code_fingerprint="v2")
    assert base != identify_key(_ref(), _ctx("sem-2"), salt="docs/a.pdf")


def test_two_units_with_one_digest_and_two_salts_are_two_keys() -> None:
    """08:1364: two symlink aliases of one file are two units with two salts. D143."""
    left = identify_key(_ref("c:/x/a.pdf"), _ctx(), salt="a.pdf")
    right = identify_key(_ref("c:/x/b.pdf"), _ctx(), salt="b.pdf")
    assert left != right


def test_the_identity_is_the_producer_record_and_not_a_second_shape() -> None:
    """03:396: ONE TYPE, TWO LAYERS."""
    ident = identity("fp")
    assert (ident.operator, ident.op_version, ident.code_fingerprint) == (OP_IDENTIFY, 1, "fp")
    assert ident.options_digest == b""


# ---------------------------------------------------------------------------------------------
# 6. D143: the salt read site
# ---------------------------------------------------------------------------------------------


def test_the_salt_comes_from_the_walked_path_discovery_stamped() -> None:
    salt = salt_for({WALKED_PATH_KEY: "c:/corpus/docs/a.pdf"}, source_root="c:/corpus")
    assert salt == "docs/a.pdf"


def test_a_roster_row_without_the_walked_path_refuses_rather_than_guessing() -> None:
    """08:1364 forbids the canonical uri, and a silent fallback would collapse two aliases."""
    with pytest.raises(RouteError, match="D143"):
        salt_for({}, source_root="c:/corpus")


def test_a_non_fs_connector_salts_from_its_locator() -> None:
    salt = salt_for({"locator": "chan/1234"}, source_root="", connector="slack")
    assert salt == "slack/chan/1234"


# ---------------------------------------------------------------------------------------------
# 7. `IdentifyLedger`: the `derived_rows` contribution
# ---------------------------------------------------------------------------------------------


def _result(outcome: Outcome, **extra: object) -> StepResult:
    return StepResult(
        outcome=outcome,
        unit=_ref(),
        identity=identity(),
        cache_key="0" * 64,
        **extra,  # type: ignore[arg-type]
    )


def test_the_ledger_contributes_the_unit_update_for_a_row_it_knows() -> None:
    ledger = IdentifyLedger()
    ledger.record(7, "c:/x/a.pdf", PartCount(count=42))
    statements = ledger(7, _result(Outcome.OK))
    assert len(statements) == 1
    assert statements[0].participant == "derived_rows"
    assert statements[0].sql is IDENTIFIED_SQL
    assert statements[0].params == {"unit_uri": "c:/x/a.pdf", "part_count": 42}


def test_the_ledger_contributes_nothing_for_a_row_it_does_not_know() -> None:
    """One contribution serves a store that completes `parse.*` rows too: the map dispatches."""
    assert IdentifyLedger()(7, _result(Outcome.OK)) == ()


def test_a_permanent_failure_fails_the_unit_rather_than_counting_it() -> None:
    ledger = IdentifyLedger()
    ledger.record(7, "c:/x/a.pdf", None)
    statements = ledger(
        7,
        _result(Outcome.FAILED_PERMANENT, failure_class=FailureClass.UNSUPPORTED_FORMAT),
    )
    assert len(statements) == 1
    assert statements[0].sql is IDENTIFY_FAILED_SQL
    assert statements[0].params["failure_class"] == FailureClass.UNSUPPORTED_FORMAT


def test_the_ledger_does_not_pop_because_a_rolled_back_plan_must_be_retryable() -> None:
    """`complete()` returns False for supersession and rolls the whole transaction back."""
    ledger = IdentifyLedger()
    ledger.record(7, "c:/x/a.pdf", PartCount(count=3))
    assert ledger(7, _result(Outcome.OK))
    assert ledger(7, _result(Outcome.OK)), "the entry survives a plan that did not commit"
    ledger.forget(7)
    assert ledger(7, _result(Outcome.OK)) == ()


def test_forgetting_an_unknown_row_is_not_an_error() -> None:
    ledger = IdentifyLedger()
    ledger.forget(11)
    assert len(ledger) == 0


def test_the_ledger_refuses_to_grow_past_its_ceiling_and_names_the_caller_s_omission() -> None:
    ledger = IdentifyLedger(max_pending=2)
    ledger.record(1, "c:/x/a", PartCount(count=1))
    ledger.record(2, "c:/x/b", PartCount(count=1))
    with pytest.raises(RouteError, match="forget"):
        ledger.record(3, "c:/x/c", PartCount(count=1))
    ledger.record(2, "c:/x/b", PartCount(count=2))  # an update, not growth
    assert len(ledger) == 2


def test_the_default_ceiling_is_more_than_a_single_loop_can_hold_in_flight() -> None:
    assert MAX_PENDING_IDENTIFICATIONS == 8 * 256, "eight claim batches at [runtime.claim] free"


# ---------------------------------------------------------------------------------------------
# 8. One transaction: the whole reason the contribution seam exists
# ---------------------------------------------------------------------------------------------


def test_the_derived_rows_participant_comes_before_the_work_transition() -> None:
    """07:2730-2733's printed order, which is why a rollback undoes the `unit` write too."""
    assert COMPLETE_PARTICIPANTS.index("derived_rows") < COMPLETE_PARTICIPANTS.index(
        "work_transition"
    )


def test_the_part_count_and_the_work_transition_commit_or_roll_back_together(
    thread: ow.StoreThread, store_path: Path
) -> None:
    """The torn state this rules out cannot be repaired: `done` with `part_count` NULL is a unit
    stuck in `acquired` with no queue row that will ever move it again."""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf")
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/a.pdf", "0" * 64))
    connection.close()

    ledger = IdentifyLedger()
    store = SqliteStore(thread, derived_rows=ledger)
    claimed = store.claim(batch=8, gen=3, worker="host:1:t", lease_ms=60_000)
    assert len(claimed) == 1, "a NULL dispatch_key batches alone (08:755)"
    row = claimed[0]
    assert row.operator == OP_IDENTIFY

    def forty_two(unit: UnitRef, *, fmt: str) -> PartCount:
        del unit, fmt
        return PartCount(count=42)

    result, answer = identify(
        counted(row.unit_uri, DIGEST, 10), count=forty_two, cache_key_hex="0" * 64
    )
    assert answer is not None
    ledger.record(row.id, row.unit_uri, answer)
    plan = store.complete_plan(row.id, result)
    assert [statement.participant for statement in plan] == ["derived_rows", "work_transition"]
    assert store.complete(row.id, 3, result) is True
    ledger.forget(row.id)

    check = _conn(store_path)
    assert check.execute("SELECT part_count, state FROM unit").fetchone() == (42, "identified")
    assert check.execute("SELECT status FROM work").fetchone() == ("done",)
    check.close()


def test_a_permanent_failure_lands_the_unit_in_failed_in_the_same_transaction(
    thread: ow.StoreThread, store_path: Path
) -> None:
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.dwg")
        connection.execute(IDENTIFY_INSERT_SQL, row_params("c:/x/a.dwg", "0" * 64))
    connection.close()

    ledger = IdentifyLedger()
    store = SqliteStore(thread, derived_rows=ledger)
    row = store.claim(batch=8, gen=3, worker="host:1:t", lease_ms=60_000)[0]

    def refuses(unit: UnitRef, *, fmt: str) -> PartCount:
        del unit, fmt
        raise DriverError(cls=FailureClass.UNSUPPORTED_FORMAT, message="no reader")

    result, answer = identify(
        counted(row.unit_uri, DIGEST, 10), count=refuses, cache_key_hex="0" * 64
    )
    ledger.record(row.id, row.unit_uri, answer)
    assert store.complete(row.id, 3, result) is True

    check = _conn(store_path)
    assert check.execute("SELECT state, acq_failure_class FROM unit").fetchone() == (
        "failed",
        FailureClass.UNSUPPORTED_FORMAT.value,
    )
    assert check.execute("SELECT status FROM work").fetchone() == ("failed_permanent",)
    check.close()


def test_a_unit_another_process_already_identified_is_not_re_stamped(store_path: Path) -> None:
    """`WHERE state = 'acquired'` is what stops a blind update re-opening a closed window."""
    connection = _conn(store_path)
    with connection:
        _unit_row(connection, "c:/x/a.pdf", state="planned", part_count=9)
    cursor = connection.execute(IDENTIFIED_SQL, {"unit_uri": "c:/x/a.pdf", "part_count": 42})
    assert cursor.rowcount == 0
    assert connection.execute("SELECT part_count FROM unit").fetchone() == (9,)
    connection.close()


# ---------------------------------------------------------------------------------------------
# 9. Against the plan's own text
# ---------------------------------------------------------------------------------------------


def test_the_priority_is_the_one_the_plan_gives_the_operator(plan: PlanDocs) -> None:
    """08:619, and the reason is the opposite of `op.converge`'s."""
    plan.require()
    rows = plan.grep(r"^\| 300 \| `op\.converge`, `op\.identify` \|", documents=("08-runtime.md",))
    assert len(rows) == 1
    assert OP_IDENTIFY_PRIORITY == 300
    assert "creates" in rows[0].text


def test_the_hop_four_row_is_the_specification_this_module_was_built_from(plan: PlanDocs) -> None:
    plan.require()
    rows = plan.grep(
        r"`omniweave\.run\.expand` . `op\.identify`", documents=("02-architecture.md",)
    )
    assert len(rows) == 1
    text = rows[0].text
    for fragment in ("decision_id", "dispatch_key", "cost_class='free'", "batching alone"):
        assert fragment in text
    assert re.search(r"No `parse\.pdf` work row exists yet", text)


def test_the_cache_layer_table_gives_op_identify_no_layer(plan: PlanDocs) -> None:
    """08:861 -- and `work.cache_key` is still NOT NULL, which is D164."""
    plan.require()
    rows = plan.grep(r"^\| `op\.identify` \| none \|", documents=("08-runtime.md",))
    assert len(rows) == 1
    assert "unit.part_count" in rows[0].text


def test_the_state_after_identification_is_the_plans(plan: PlanDocs) -> None:
    plan.require()
    assert plan.grep(
        r"identified ---- unit\.part_count is NOT NULL", documents=("05-ingest-and-routing.md",)
    )
