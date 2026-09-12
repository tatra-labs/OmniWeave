"""Batch formation, AIMD, quarantine and Sequence sessions -- against the plan's own printed tests.

08-runtime.md section 2.2 does not describe the batch invisibility rule, it *prints the test*:
*"a `batch = 32` run with one poison unit asserts 32 transitions, 32 spend rows, 32 unit spans and
exactly one `FAILED_PERMANENT{DRIVER_CRASHED}`."* So that test is written here at that batch size
with that poison unit, and it counts.

Three other things in this file are transcriptions rather than inventions and each says so at its
own docstring: 15-observability.md:140's eighteen `call`-span attributes are read out of the
document and compared to `CALL_SPAN_ATTRIBUTES` in both directions; `SEQUENCE_LEN_SQL` is run
against a real `.owstore` with real `work` rows, because a count of *"the two claimable statuses"*
is only checkable against rows in the other four; and D103's rule -- mechanisms in
`omniweave_core.host`, decisions here -- is asserted over this module's own AST, so a later hand
that re-implemented `adapt_batch`'s arithmetic would fail rather than diverge quietly.

## The one test that is a defect report

`test_a_session_split_by_the_claim_is_caught_after_the_fact_and_released_whole` builds the state
08's rule 1 says cannot happen and shows the widened claim producing it: `:batch` is
`max(cfg_batch, sequence_len)`, the picked set is ordered by `(priority DESC, id)` over the whole
`dispatch_key`, and nothing makes a sequence's parts the rows that survive the LIMIT. The test
asserts the prefix arrives, then asserts `whole_sequences()` hands it back rather than paying
`per_session` twice. Filed.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route.spend import Spend
from omniweave.run import dispatch
from omniweave.run.dispatch import (
    CALL_SPAN_ATTRIBUTES,
    CONFIG_DIGEST_HEX_LEN,
    DISPATCH_KEY_HEX_LEN,
    INVOKE_ID_PREFIX,
    MAX_SEQUENCE_UNITS,
    REGEN_DEGRADATION_KIND,
    SEQUENCE_LEN_SQL,
    SEQUENCE_MICROS_TOLERANCE,
    SEQUENCE_RESERVATION_SCOPE,
    AimdRegistry,
    Batch,
    BatchPolicy,
    UnitOutcome,
    apportion_micros,
    call_attributes,
    check_apportionment,
    defer_together,
    dispatch_key,
    fan_out,
    form_batches,
    invocation_units,
    new_invoke_id,
    partial_sequences,
    regen_reprice_message,
    sequence_claim_size,
    session_failure,
    start_batch,
    whole_sequences,
)
from omniweave_core import budget as budget_mod
from omniweave_core.config import KEYS
from omniweave_core.drivers.resolve import Policy
from omniweave_core.errors import ConfigError, RouteError
from omniweave_core.events import EVENTS, SPAN_ATTRIBUTES
from omniweave_core.host import subproc
from omniweave_core.host.subproc import (
    AIMD_RECOVERY_STREAK,
    AimdState,
    BatchEvent,
    HostVerdict,
    InvokeReport,
    WorkerKey,
    adapt_batch,
    retry_batch_size,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.work import CLAIM_SQL, WORK_COLUMNS, WORK_STATUSES, WorkRow
from omniweave_ports.types import DriverMetrics, DriverResult, Isolation, UnitRef

if TYPE_CHECKING:
    from conftest import PlanDocs

REPO = Path(__file__).resolve().parents[4]
MODULE = REPO / "packages" / "omniweave" / "src" / "omniweave" / "run" / "dispatch.py"

DIGEST = "a" * CONFIG_DIGEST_HEX_LEN
OTHER_DIGEST = "b" * CONFIG_DIGEST_HEX_LEN
URI = "file:///corpus/a.pdf"
KEY = dispatch_key("parse.pdf.pdfium", DIGEST, Isolation.SUBPROC.value)
CONFIGURED = {"free": 256, "local_compute": 32, "billed_api": 8}
NOW_NS = 1_757_400_000_000_000_000


class FakeClock:
    """`Clock`, with a settable wall reading. `new_invoke_id` reads `wall_ns()` and nothing else."""

    def __init__(self, wall: int = NOW_NS) -> None:
        self.wall = wall

    def monotonic_ns(self) -> int:  # pragma: no cover -- a ULID is minted from wall time.
        return 0

    def wall_ns(self) -> int:
        return self.wall


def row(
    row_id: int = 1,
    *,
    part: str = "p1",
    key: str | None = KEY,
    driver: str | None = "parse.pdf.pdfium",
    sequence_id: str | None = None,
    cost_class: str = "free",
    operator: str = "parse.pdf",
    priority: int = 0,
    service: str | None = None,
) -> WorkRow:
    """One `work` row, every column present, built from `WORK_COLUMNS` so a migration breaks it."""
    values: dict[str, object] = {}
    values.update(dict.fromkeys(WORK_COLUMNS))
    values.update(
        id=row_id,
        unit_uri=URI,
        unit_part=part,
        operator=operator,
        op_version=1,
        cache_key="k" * 64,
        decision_id=None if driver is None else f"dec_{row_id}",
        sequence_id=sequence_id,
        driver=driver,
        cost_class=cost_class,
        dispatch_key=key,
        service=service,
        status="claimed",
        attempts_total=1,
        attempts_today=1,
        cost_micros=0,
        queued_ms=0,
        ran_ms=0,
        peak_rss_bytes=0,
        priority=priority,
    )
    return WorkRow.from_row(tuple(values[name] for name in WORK_COLUMNS))


def minted(prefix: str = "iv_") -> Any:
    """A deterministic `mint` for `form_batches`: `iv_0`, `iv_1`, ... in call order."""
    counter = iter(range(1000))
    return lambda: f"{prefix}{next(counter)}"


def batch_of(*rows: WorkRow, invoke_id: str = "iv_test") -> Batch:
    return Batch(invoke_id=invoke_id, rows=rows)


def report_for(batch: Batch, *, poison: int | None = None) -> InvokeReport:
    """One clean `DriverResult` per unit, with an optional crashed one."""
    results: list[DriverResult | None] = []
    failures: list[HostVerdict | None] = []
    for index in range(batch.size):
        if index == poison:
            results.append(None)
            failures.append(HostVerdict.crashed(exit_status=-11, stderr_tail=b"segv"))
            continue
        results.append(DriverResult(outcome="ok", produced=()))
        failures.append(None)
    event = BatchEvent.CLEAN if poison is None else BatchEvent.DRIVER_CRASHED
    return InvokeReport(results=tuple(results), failures=tuple(failures), event=event)


# ---------------------------------------------------------------------------------------------
# 1. `dispatch_key`
# ---------------------------------------------------------------------------------------------


def test_the_key_is_the_sixteen_hex_characters_the_plan_prints() -> None:
    """02-architecture.md:479: `sha256(driver_id||config_digest||isolation)[:16]`.

    Recomputed here from `hashlib` rather than compared to a frozen literal, because a frozen
    literal would pass for a function that hashed the three inputs in a different ORDER -- and the
    order is the thing an independent implementation would have to agree on.
    """
    expected = hashlib.sha256(f"parse.pdf.pdfium{DIGEST}subproc".encode()).hexdigest()[:16]
    assert dispatch_key("parse.pdf.pdfium", DIGEST, "subproc") == expected
    assert len(KEY) == DISPATCH_KEY_HEX_LEN


def test_the_isolation_is_in_the_key_and_the_worker_key_does_not_have_it() -> None:
    """The third field is why `dispatch_key` and `WorkerKey` are two things (subproc.py:2336).

    One driver under one configuration granted `inproc` on one machine and `subproc` on another
    produces two dispatch keys and ONE worker key. A batching key that ignored isolation would put
    an in-process call and a subprocess call in one `INVOKE`.
    """
    inproc = dispatch_key("parse.pdf.pdfium", DIGEST, Isolation.INPROC.value)
    assert inproc != KEY
    assert WorkerKey("parse.pdf.pdfium", DIGEST) == WorkerKey("parse.pdf.pdfium", DIGEST)


def test_the_three_inputs_are_checked_so_the_concatenation_cannot_be_re_bracketed() -> None:
    """The check is what makes an unseparated `a||b||c` unambiguous. Four refusals."""
    with pytest.raises(RouteError, match="needs a driver id"):
        dispatch_key("", DIGEST, "subproc")
    with pytest.raises(RouteError, match="lowercase hex"):
        dispatch_key("d", DIGEST.upper(), "subproc")
    with pytest.raises(RouteError, match="lowercase hex"):
        dispatch_key("d", "a" * 63, "subproc")
    with pytest.raises(RouteError, match="is not an Isolation"):
        dispatch_key("d", DIGEST, "container")


def test_no_two_triples_over_the_shipped_vocabulary_share_a_key() -> None:
    """The property the truncation has to have, over a population the size of a real roster."""
    drivers = [f"parse.pdf.d{n}" for n in range(40)]
    digests = [f"{n:064x}" for n in range(5)]
    keys = {
        dispatch_key(driver, digest, iso.value)
        for driver in drivers
        for digest in digests
        for iso in Isolation
    }
    assert len(keys) == len(drivers) * len(digests) * len(Isolation)


def test_an_invoke_id_is_prefixed_and_sorts_by_mint_time() -> None:
    """`'iv_' + ulid(...)`. Sortable, because a ULID's leading 48 bits are milliseconds."""
    early = new_invoke_id(FakeClock(NOW_NS), b"\x00" * 10)
    late = new_invoke_id(FakeClock(NOW_NS + 5_000_000), b"\x00" * 10)
    assert early.startswith(INVOKE_ID_PREFIX)
    assert len(early) == len(INVOKE_ID_PREFIX) + 26
    assert early < late


def test_the_plan_names_invoke_id_six_times_and_never_prints_a_format(plan: PlanDocs) -> None:
    """D148, as evidence rather than as an assertion about my memory.

    `invoke_id` is a `CANCEL` key and a `call`-span attribute, so its uniqueness scope is
    load-bearing in two directions -- and no document says what it is. The grep is for any line
    that both mentions the name and says something about its shape.
    """
    hits = plan.grep(r"invoke_id")
    assert len(hits) >= 6, [str(hit) for hit in hits]
    shape = [
        hit
        for hit in hits
        if re.search(r"invoke_id[^,}]*(ulid|uuid|hex|sha256|monotonic|counter)", hit.text, re.I)
    ]
    assert shape == [], [str(hit) for hit in shape]


# ---------------------------------------------------------------------------------------------
# 2. `Batch`
# ---------------------------------------------------------------------------------------------


def test_a_batch_keeps_the_claims_order_because_result_unit_index_indexes_it() -> None:
    """`SqliteStore.claim()` returns `(-priority, id)`; `fan_out` maps index i to `rows[i]`."""
    rows = (row(7, part="p1", priority=300), row(9, part="p2", priority=100))
    batch = batch_of(*rows)
    assert batch.row_ids == (7, 9)
    assert batch.parts == ((URI, "p1"), (URI, "p2"))
    assert batch.size == 2
    assert batch.dispatch_key == KEY
    assert batch.driver == "parse.pdf.pdfium"
    assert batch.cost_class == "free"


def test_a_batch_spanning_two_dispatch_keys_is_refused() -> None:
    other = dispatch_key("parse.office.anydoc", DIGEST, "subproc")
    with pytest.raises(RouteError, match="spans 2 dispatch keys"):
        batch_of(row(1), row(2, part="p2", key=other))


def test_a_null_dispatch_key_batches_alone_as_the_ddl_requires() -> None:
    """`0004_runtime.sql:104-105`: *"NULL for an `op.*` row, AND A NULL BATCHES ALONE."*"""
    op_row = row(1, operator="op.identify", key=None, driver=None)
    assert batch_of(op_row).size == 1
    with pytest.raises(RouteError, match="BATCHES ALONE"):
        batch_of(op_row, row(2, part="p2", operator="op.identify", key=None, driver=None))


def test_a_batch_refuses_an_empty_row_set_and_an_empty_invoke_id() -> None:
    with pytest.raises(RouteError, match="no rows"):
        Batch(invoke_id="iv_1", rows=())
    with pytest.raises(RouteError, match="no invoke_id"):
        Batch(invoke_id="", rows=(row(1),))


def test_form_batches_groups_by_key_and_gives_every_op_row_its_own() -> None:
    """One claim is coherent; a retry's re-formed set is not guaranteed to be."""
    other = dispatch_key("parse.office.anydoc", DIGEST, "subproc")
    rows = [
        row(1, part="p1"),
        row(2, part="p2", operator="op.identify", key=None, driver=None),
        row(3, part="p3", key=other, driver="parse.office.anydoc"),
        row(4, part="p4"),
        row(5, part="p5", operator="op.converge", key=None, driver=None),
    ]
    batches = form_batches(rows, mint=minted())
    assert [b.row_ids for b in batches] == [(1, 4), (2,), (3,), (5,)]
    assert [b.invoke_id for b in batches] == ["iv_0", "iv_1", "iv_2", "iv_3"]


def test_form_batches_keeps_the_highest_priority_key_first() -> None:
    """First-appearance order, not sorted order: `priority DESC` survives batching (08:625)."""
    other = dispatch_key("parse.office.anydoc", DIGEST, "subproc")
    rows = [
        row(10, part="p1", key=other, driver="parse.office.anydoc", priority=300),
        row(11, part="p2", priority=100),
        row(12, part="p3", key=other, driver="parse.office.anydoc", priority=300),
    ]
    batches = form_batches(rows, mint=minted())
    assert [b.dispatch_key for b in batches] == [other, KEY]
    assert batches[0].row_ids == (10, 12)


def test_form_batches_of_nothing_is_nothing() -> None:
    assert form_batches((), mint=minted()) == ()


def test_invocation_units_pairs_in_batch_order_and_refuses_a_gap() -> None:
    """A short units list does not truncate an INVOKE -- it mis-attributes every later RESULT."""
    batch = batch_of(row(1, part="p1"), row(2, part="p2"))
    roster = {
        (URI, "p1"): UnitRef(uri=URI, part="p1", content_sha256="c" * 64, byte_len=10),
        (URI, "p2"): UnitRef(uri=URI, part="p2", content_sha256="d" * 64, byte_len=20),
    }
    assert [unit.part for unit in invocation_units(batch, roster)] == ["p1", "p2"]
    del roster[(URI, "p2")]
    with pytest.raises(RouteError, match="no unit for"):
        invocation_units(batch, roster)


def test_invocation_units_refuses_a_roster_entry_that_names_another_part() -> None:
    batch = batch_of(row(1, part="p1"))
    roster = {(URI, "p1"): UnitRef(uri=URI, part="p9", content_sha256="c" * 64, byte_len=10)}
    with pytest.raises(RouteError, match=r"maps .* to a UnitRef for"):
        invocation_units(batch, roster)


# ---------------------------------------------------------------------------------------------
# 3. The size: the configured start, the card clamp, and AIMD between them
# ---------------------------------------------------------------------------------------------


def test_the_card_clamps_the_configured_start_and_never_raises_it() -> None:
    """08:2587: *"the AIMD starting point, clamped by the card."* A `min`, both ways."""
    assert start_batch(CONFIGURED, "free", card_max=32) == 32
    assert start_batch(CONFIGURED, "billed_api", card_max=32) == 8
    assert start_batch(CONFIGURED, "local_compute", card_max=32) == 32


def test_an_undeclared_card_max_is_not_a_clamp_to_zero() -> None:
    """`IsolationSpec.batch_max_units` defaults to 0, and 0 means the card said nothing.

    The consequence is the reason this is a test and not a comment: the value goes on to become
    `AimdState.card_max`, whose recovery arm is `min(batch + 1, card_max)`. A literal zero there
    makes twenty CLEAN batches shrink the batch to nothing.
    """
    assert start_batch(CONFIGURED, "free", card_max=0) == 256
    shrunk = adapt_batch(AimdState(batch=4, clean_streak=19, card_max=0), BatchEvent.CLEAN)
    assert shrunk.batch == 0, "this is what start_batch's 0-is-undeclared rule exists to prevent"


def test_start_batch_refuses_a_missing_class_and_a_nonsense_number() -> None:
    with pytest.raises(ConfigError, match="names no value for"):
        start_batch(CONFIGURED, "gpu", card_max=0)
    with pytest.raises(ConfigError, match="is not a batch"):
        start_batch({"free": 0}, "free", card_max=0)
    with pytest.raises(ConfigError, match="0 means undeclared"):
        start_batch(CONFIGURED, "free", card_max=-1)


def test_the_registry_seeds_the_ceiling_from_start_batch_and_recovery_stops_there() -> None:
    """An operator who lowered `batch.billed_api` to 1 must not watch it climb back to 8."""
    registry = AimdRegistry()
    key = WorkerKey("derive.entity.llm", DIGEST)
    ceiling = start_batch({"billed_api": 1}, "billed_api", card_max=64)
    assert ceiling == 1
    for _ in range(AIMD_RECOVERY_STREAK * 3):
        registry.observe(key, BatchEvent.CLEAN, ceiling=ceiling)
    assert registry.size(key, ceiling=ceiling) == 1


def test_twenty_consecutive_clean_batches_add_exactly_one_unit() -> None:
    """02:831's *"recovers after 20 consecutive clean batches"*, counted.

    Nineteen clean batches, one OOM and one clean batch is NOT twenty: the streak resets, which is
    what "consecutive" means and what `adapt_batch` rule 2 implements.
    """
    registry = AimdRegistry()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    registry.observe(key, BatchEvent.RESOURCE_LIMIT, ceiling=32)  # 32 -> 16
    assert registry.size(key, ceiling=32) == 16
    for _ in range(AIMD_RECOVERY_STREAK - 1):
        registry.observe(key, BatchEvent.CLEAN, ceiling=32)
    assert registry.size(key, ceiling=32) == 16
    registry.observe(key, BatchEvent.CLEAN, ceiling=32)
    assert registry.size(key, ceiling=32) == 17


def test_a_streak_broken_by_an_oom_starts_again_from_zero() -> None:
    registry = AimdRegistry()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    registry.observe(key, BatchEvent.RESOURCE_LIMIT, ceiling=32)
    for _ in range(AIMD_RECOVERY_STREAK - 1):
        registry.observe(key, BatchEvent.CLEAN, ceiling=32)
    registry.observe(key, BatchEvent.RESOURCE_LIMIT, ceiling=32)  # 16 -> 8, streak -> 0
    for _ in range(AIMD_RECOVERY_STREAK - 1):
        registry.observe(key, BatchEvent.CLEAN, ceiling=32)
    assert registry.size(key, ceiling=32) == 8


def test_the_aimd_state_is_per_driver_and_configuration_and_not_shared() -> None:
    """08:760's own key. One driver's OOM must not halve another's batch."""
    registry = AimdRegistry()
    first = WorkerKey("parse.pdf.pdfium", DIGEST)
    second = WorkerKey("parse.pdf.pdfium", OTHER_DIGEST)
    third = WorkerKey("parse.office.anydoc", DIGEST)
    registry.observe(first, BatchEvent.RESOURCE_LIMIT, ceiling=32)
    assert registry.size(first, ceiling=32) == 16
    assert registry.size(second, ceiling=32) == 32
    assert registry.size(third, ceiling=32) == 32
    assert registry.known() == (first, second, third)


def test_the_registry_refuses_a_ceiling_below_one() -> None:
    with pytest.raises(ConfigError, match="would start every batch empty"):
        AimdRegistry().state(WorkerKey("d", DIGEST), ceiling=0)


# ---------------------------------------------------------------------------------------------
# 4. `BatchPolicy`: the retry, the quarantine, and the order the two are decided in
# ---------------------------------------------------------------------------------------------


def policy(**over: object) -> BatchPolicy:
    kwargs: dict[str, Any] = {"configured": CONFIGURED}
    kwargs.update(over)
    return BatchPolicy(**kwargs)


def test_three_crashes_in_sixty_seconds_quarantine_the_driver() -> None:
    """02:831 and 04:1727 -- the DRIVER, not the unit, and for the run."""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    verdicts = [
        pol.observe(
            key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=1_000 + at
        )
        for at in (0, 10_000, 20_000)
    ]
    assert [v.quarantined for v in verdicts] == [False, False, True]
    assert pol.quarantined() == frozenset({"parse.pdf.pdfium"})


def test_three_crashes_spread_past_the_window_do_not_quarantine() -> None:
    """*"a long-running ingest of a corpus with three bad documents in it is not a dead driver."*"""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for at in (0, 61_000, 122_000):
        verdict = pol.observe(
            key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=1_000 + at
        )
        assert not verdict.quarantined
    assert pol.quarantined() == frozenset()


def test_one_batch_records_one_crash_and_the_caller_records_none() -> None:
    """`CrashLedger.record` appends, so a double call quarantines in two batches, not three."""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for at in (0, 1_000):
        pol.observe(key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=at)
    assert pol.quarantined() == frozenset()


def test_a_non_crash_event_never_touches_the_ledger() -> None:
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for event in (BatchEvent.CLEAN, BatchEvent.RESOURCE_LIMIT, BatchEvent.WORKER_DIED):
        for _ in range(5):
            pol.observe(key, event, cost_class="free", card_max=32, now_ms=0)
    assert pol.quarantined() == frozenset()


def test_the_retry_is_offered_once_and_at_batch_one() -> None:
    """04:1720-1722: *"the batch retries ONCE at `batch = 1` to localise the poison unit."*"""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    first = pol.observe(
        key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=0, attempt=0
    )
    assert first.retry_at == 1
    assert first.retries
    second = pol.observe(
        key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=1, attempt=1
    )
    assert second.retry_at is None
    assert not second.retries


def test_only_a_crash_earns_a_retry() -> None:
    """An OOM halves and re-dispatches through the ordinary path; a timeout is permanent."""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for event in (BatchEvent.CLEAN, BatchEvent.RESOURCE_LIMIT, BatchEvent.WORKER_DIED):
        verdict = pol.observe(key, event, cost_class="free", card_max=32, now_ms=0)
        assert verdict.retry_at is None


def test_the_retry_is_still_offered_on_the_batch_that_quarantines() -> None:
    """The retry localises the poison unit, which is what an operator needs at exactly that moment.

    The quarantine takes the driver off the NEXT plan; it does not abandon the batch in hand.
    """
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for at in (0, 1_000, 2_000):
        verdict = pol.observe(
            key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=at, attempt=0
        )
    assert verdict.quarantined
    assert verdict.retry_at == 1


def test_a_quarantine_survives_a_later_clean_batch() -> None:
    """Sticky for the run: *"a ledger that forgot on success would re-offer a driver that crashes
    every fourth document forever."*"""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for at in (0, 1_000, 2_000):
        pol.observe(key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=at)
    clean = pol.observe(key, BatchEvent.CLEAN, cost_class="free", card_max=32, now_ms=3_000)
    assert clean.quarantined
    assert pol.quarantined() == frozenset({"parse.pdf.pdfium"})


def test_a_crash_halves_nothing_and_goes_straight_to_one() -> None:
    """`DRIVER_CRASHED -> 1`, and the AIMD state is adapted even for a quarantined driver."""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    verdict = pol.observe(key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=0)
    assert verdict.next_batch == 1
    assert verdict.clean_streak == 0


def test_the_quarantined_set_is_the_exact_type_policy_holds() -> None:
    """INV-21: the host produces it, `Policy` carries it, `_gate_not_quarantined` reads it."""
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    for at in (0, 1_000, 2_000):
        pol.observe(key, BatchEvent.DRIVER_CRASHED, cost_class="free", card_max=32, now_ms=at)
    quarantined = pol.quarantined()
    assert isinstance(quarantined, frozenset)
    assert Policy(quarantined=quarantined).quarantined == frozenset({"parse.pdf.pdfium"})


def test_the_policy_sizes_a_claim_through_start_batch() -> None:
    pol = policy()
    key = WorkerKey("parse.pdf.pdfium", DIGEST)
    assert pol.size(key, cost_class="free", card_max=32) == 32
    assert pol.size(WorkerKey("x", DIGEST), cost_class="free", card_max=0) == 256
    assert pol.max_sequence_units == MAX_SEQUENCE_UNITS


def test_the_policy_declares_no_number_of_its_own() -> None:
    """`CrashLedger`'s precedent: config.py declares the defaults, the caller reads them.

    The two crash constants are asserted against `config.py`'s shipped default rather than against
    a literal repeated here, so a change to `[drivers] crash_quarantine` moves one place.
    """
    declared = {name: key.default for name, key in KEYS.items()}
    assert declared["drivers.crash_quarantine"] == {"crashes": 3, "window_s": 60}
    assert declared["runtime.claim.batch"] == CONFIGURED
    assert declared["runtime.max_sequence_units"] == MAX_SEQUENCE_UNITS


# ---------------------------------------------------------------------------------------------
# 5. Sequence sessions -- 08 section 2.3's four rules
# ---------------------------------------------------------------------------------------------


def test_the_widened_claim_is_the_max_the_plan_prints() -> None:
    """08:800: `:batch = max(cfg_batch, sequence_len)`."""
    assert sequence_claim_size(8, 42) == 42
    assert sequence_claim_size(256, 42) == 256
    assert sequence_claim_size(8, 1) == 8


def test_a_session_over_max_sequence_units_is_refused_naming_the_knob() -> None:
    """08:804-805, including the symbol the plan names: `SEQUENCE_TOO_LONG`."""
    with pytest.raises(RouteError, match="max_sequence_units") as caught:
        sequence_claim_size(8, MAX_SEQUENCE_UNITS + 1)
    assert caught.value.code() == "OW_SEQUENCE_TOO_LONG"
    assert "max_sequence_units" in caught.value.fix
    assert sequence_claim_size(8, MAX_SEQUENCE_UNITS) == MAX_SEQUENCE_UNITS


def test_the_cap_is_on_the_session_and_not_on_the_returned_size() -> None:
    """A 42-part session under `batch.free = 256` legitimately returns 256, which is over 64."""
    assert sequence_claim_size(256, 42, max_sequence_units=64) == 256


def test_sequence_claim_size_refuses_an_empty_session_and_an_empty_batch() -> None:
    with pytest.raises(RouteError, match="not a session"):
        sequence_claim_size(8, 0)
    with pytest.raises(ConfigError, match="not a claim"):
        sequence_claim_size(0, 4)


def test_sequence_len_sql_counts_exactly_the_two_claimable_statuses(tmp_path: Path) -> None:
    """Against real rows in all six statuses, because *"the two claimable"* is a claim about four.

    The two are `CLAIM_SQL`'s own, asserted against `WORK_STATUSES` so a status added by a
    migration cannot quietly become claimable here without failing.
    """
    named = set(re.findall(r"'(\w+)'", SEQUENCE_LEN_SQL))
    assert named == {"pending", "failed_transient"}
    assert named <= set(WORK_STATUSES)

    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        assert len(migrate.apply_pending(connection, now_ns=NOW_NS)) == 4
        connection.execute(
            "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
            "VALUES(:uri,'planned','internal',1)",
            {"uri": URI},
        )
        for index, status in enumerate(WORK_STATUSES):
            connection.execute(
                "INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, "
                "sequence_id, cost_class, status) "
                "VALUES(:uri, :part, 'op.identify', 1, 'k', 'seq_1', 'free', :status)",
                {"uri": URI, "part": f"p{index}", "status": status},
            )
        connection.commit()
        (count,) = connection.execute(SEQUENCE_LEN_SQL, {"sid": "seq_1"}).fetchone()
        assert count == 2
        assert len(WORK_STATUSES) == 6
        (absent,) = connection.execute(SEQUENCE_LEN_SQL, {"sid": "seq_none"}).fetchone()
        assert absent == 0
    finally:
        connection.close()


def test_a_whole_session_passes_through_untouched() -> None:
    rows = [row(n, part=f"p{n}", sequence_id="seq_1") for n in range(1, 5)]
    keep, release = whole_sequences(rows, lengths={"seq_1": 4})
    assert [r.id for r in keep] == [1, 2, 3, 4]
    assert release == ()
    assert partial_sequences(rows, lengths={"seq_1": 4}) == ()


def test_a_session_split_by_the_claim_is_caught_after_the_fact_and_released_whole() -> None:
    """D147. The widened claim is necessary and NOT sufficient, and this is the state it admits.

    `:batch = max(cfg_batch, sequence_len)` is `max(3, 4) = 4`; the picked set is the four
    highest-priority rows of the `dispatch_key`, which here are three older unsequenced rows and
    the first part of the session. Rule 1 says *"a Sequence is claimed whole or not at all"* and
    the SQL has just claimed a quarter of one.

    `whole_sequences()` is the check that makes the rule true rather than likely: the session's
    single claimed part comes back for release, the three unsequenced rows are dispatched, and
    `per_session` is paid once rather than twice.
    """
    claimed = [
        row(1, part="a1"),
        row(2, part="a2"),
        row(3, part="a3"),
        row(4, part="p1", sequence_id="seq_1"),
    ]
    assert sequence_claim_size(3, 4) == 4
    assert partial_sequences(claimed, lengths={"seq_1": 4}) == ("seq_1",)
    keep, release = whole_sequences(claimed, lengths={"seq_1": 4})
    assert [r.id for r in keep] == [1, 2, 3]
    assert [r.id for r in release] == [4]


def test_the_claim_sql_orders_over_the_dispatch_key_and_not_over_the_sequence() -> None:
    """D147's warrant, read out of the shipped statement rather than asserted from memory."""
    predicate = CLAIM_SQL.split("RETURNING")[0]
    assert "ORDER BY w.priority DESC, w.id" in predicate
    assert "sequence_id" not in predicate
    assert "sequence_id" in CLAIM_SQL, "it is RETURNED, and read by nothing in the statement"


def test_partial_sequences_refuses_a_sequence_it_was_given_no_length_for() -> None:
    with pytest.raises(RouteError, match="no claimable length"):
        partial_sequences([row(1, sequence_id="seq_1")], lengths={})


def test_a_denial_defers_every_part_of_the_session_with_one_dim() -> None:
    """Rule 2: *"a denial defers EVERY part of the Sequence with the same `deferred_dim`."*"""
    rows = [
        row(1, part="p1", sequence_id="seq_1"),
        row(2, part="p2", sequence_id="seq_1"),
        row(3, part="p3"),
        row(4, part="p4", sequence_id="seq_1"),
    ]
    deferrals = defer_together(rows, deferred_dim="tokens_out")
    assert [(d.row_ids, d.sequence_id) for d in deferrals] == [
        ((1, 2, 4), "seq_1"),
        ((3,), None),
    ]
    assert {d.deferred_dim for d in deferrals} == {"tokens_out"}


def test_a_deferral_dim_is_a_budget_dimension_and_a_missing_one_is_refused() -> None:
    assert "tokens_out" in budget_mod.DIMS
    assert SEQUENCE_RESERVATION_SCOPE in budget_mod.SCOPES
    with pytest.raises(RouteError, match="no dimension"):
        defer_together([row(1)], deferred_dim="")


def test_a_dead_session_yields_one_class_and_one_transition_per_part() -> None:
    """Rule 3, and I24 unchanged: `len(sequence)` transitions, not one."""
    rows = [row(n, part=f"p{n}", sequence_id="seq_1") for n in range(1, 7)]
    transitions = session_failure(rows, "driver_crashed")
    assert len(transitions) == len(rows)
    assert {cls for _, cls in transitions} == {"driver_crashed"}
    assert [row_id for row_id, _ in transitions] == [1, 2, 3, 4, 5, 6]
    with pytest.raises(RouteError, match="no class"):
        session_failure(rows, "")


def test_the_regen_message_names_the_amortisation_that_was_lost() -> None:
    """Rule 3: *"a retry silently priced at `per_session` is a cost surprise."*"""
    message = regen_reprice_message("seq_1", part="p7", parts_in_session=42)
    assert "per_session" in message
    assert "per_part" in message
    assert "42" in message
    assert "p7" in message
    assert REGEN_DEGRADATION_KIND == "budget"


def test_apportionment_sums_to_the_session_exactly() -> None:
    """Rule 4, property 1. I30 allows +/-1 micro; this gives 0."""
    shares = apportion_micros(1_000_000, [1100, 900, 350, 17])
    assert sum(shares) == 1_000_000
    assert len(shares) == 4
    check_apportionment(1_000_000, shares)


def test_the_remainder_goes_to_the_highest_token_part() -> None:
    """*"the remainder goes to the highest-token part, deterministically."*

    Three parts over 100 micros with shares 1/1/1: floor division gives 33 each and 1 micro is
    left. It goes to part 0, which is the highest-token part after the tie break.
    """
    assert apportion_micros(100, [1, 1, 1]) == (34, 33, 33)
    assert apportion_micros(100, [1, 5, 1]) == (14, 72, 14)
    assert sum(apportion_micros(100, [1, 5, 1])) == 100


def test_a_tie_goes_to_the_earliest_part_so_two_runs_agree() -> None:
    """The plan does not print a tie break; iteration order is not one."""
    first = apportion_micros(7, [3, 3, 3, 3])
    second = apportion_micros(7, [3, 3, 3, 3])
    assert first == second == (4, 1, 1, 1)


def test_a_zero_token_session_splits_evenly_rather_than_dividing_by_zero() -> None:
    """The gap the plan leaves: a free driver's session reports no tokens at all."""
    shares = apportion_micros(10, [0, 0, 0, 0])
    assert shares == (4, 2, 2, 2)
    assert sum(shares) == 10
    assert apportion_micros(0, [0, 0]) == (0, 0)


def test_apportionment_refuses_nonsense_it_cannot_split() -> None:
    with pytest.raises(RouteError, match="across no parts"):
        apportion_micros(10, [])
    with pytest.raises(RouteError, match="never negative"):
        apportion_micros(-1, [1])
    with pytest.raises(RouteError, match="negative token count"):
        apportion_micros(10, [1, -1])


def test_apportionment_is_exact_over_a_sweep_of_session_sizes() -> None:
    """Property 1 at every remainder a four-part session can produce."""
    for micros in range(0, 400):
        shares = apportion_micros(micros, [7, 3, 3, 1])
        assert sum(shares) == micros
        assert all(share >= 0 for share in shares)
        assert shares[0] == max(shares)


def test_check_apportionment_refuses_a_drift_over_one_micro() -> None:
    """I30's second self-check, against the numbers WRITTEN, not against `apportion_micros`."""
    assert SEQUENCE_MICROS_TOLERANCE == 1
    check_apportionment(100, [50, 49])  # one micro of drift is allowed
    with pytest.raises(RouteError, match="attributable to no part"):
        check_apportionment(100, [50, 48])


def test_the_tokens_apportioned_are_the_two_the_plan_names() -> None:
    """*"in proportion to that part's `tokens_in + tokens_out`"* -- built from real metrics."""
    metrics = (
        DriverMetrics(tokens_in=900, tokens_out=1100),
        DriverMetrics(tokens_in=100, tokens_out=100),
    )
    shares = apportion_micros(2_200, [m.tokens_in + m.tokens_out for m in metrics])
    assert shares == (2_000, 200)
    assert sum(shares) == 2_200


# ---------------------------------------------------------------------------------------------
# 6. I24 -- the plan's own printed test
# ---------------------------------------------------------------------------------------------


def test_a_batch_of_thirty_two_with_one_poison_unit_yields_thirty_two_outcomes() -> None:
    """08:782-784, transcribed: *"a `batch = 32` run with one poison unit asserts 32 transitions,
    32 spend rows, 32 unit spans and exactly one `FAILED_PERMANENT{DRIVER_CRASHED}`."*

    The count is the property. Thirty-one outcomes would have made the batch visible in the work
    table, which is exactly what I24 forbids.
    """
    rows = tuple(row(n, part=f"p{n}") for n in range(1, 33))
    batch = batch_of(*rows)
    assert batch.size == 32
    outcomes = fan_out(batch, report_for(batch, poison=17))
    assert len(outcomes) == 32
    assert [outcome.row.id for outcome in outcomes] == list(range(1, 33))
    crashed = [o for o in outcomes if o.verdict is not None]
    assert len(crashed) == 1
    assert crashed[0].row.id == 18
    assert crashed[0].verdict is not None
    assert crashed[0].verdict.failure_class == "driver_crashed"
    assert crashed[0].verdict.permanent
    assert len([o for o in outcomes if o.result is not None]) == 31


def test_a_silent_unit_gets_a_synthesised_crash_rather_than_a_short_list() -> None:
    """Losing the other answers to one driver's silence would be the batch becoming visible."""
    batch = batch_of(row(1, part="p1"), row(2, part="p2"), row(3, part="p3"))
    report = InvokeReport(
        results=(DriverResult(outcome="ok", produced=()), None, None),
        failures=(None, None, HostVerdict.crashed(exit_status=1, stderr_tail=b"")),
        event=BatchEvent.DRIVER_CRASHED,
    )
    assert report.unanswered() == (1,)
    outcomes = fan_out(batch, report)
    assert len(outcomes) == 3
    assert outcomes[1].verdict is not None
    assert outcomes[1].verdict.failure_class == "driver_crashed"
    assert outcomes[1].verdict.exit_status is None


def test_a_report_from_another_batch_is_refused_rather_than_paired_by_index() -> None:
    batch = batch_of(row(1, part="p1"), row(2, part="p2"))
    short = InvokeReport(
        results=(DriverResult(outcome="ok", produced=()),), failures=(None,), event=BatchEvent.CLEAN
    )
    with pytest.raises(RouteError, match="sent 2 units and the report carries"):
        fan_out(batch, short)


def test_a_unit_outcome_carries_exactly_one_of_the_two() -> None:
    with pytest.raises(RouteError, match="has neither"):
        UnitOutcome(row=row(1))
    with pytest.raises(RouteError, match="has both"):
        UnitOutcome(
            row=row(1),
            result=DriverResult(outcome="ok", produced=()),
            verdict=HostVerdict.crashed(exit_status=1, stderr_tail=b""),
        )


def test_an_op_row_batches_alone_and_still_fans_out_to_one_outcome() -> None:
    op_row = row(1, operator="op.identify", key=None, driver=None)
    batch = batch_of(op_row)
    outcomes = fan_out(batch, report_for(batch))
    assert len(outcomes) == 1
    assert outcomes[0].row.operator == "op.identify"


# ---------------------------------------------------------------------------------------------
# 7. The `call` span -- the only place a Batch is visible
# ---------------------------------------------------------------------------------------------


def test_the_eighteen_call_attributes_are_the_plans_row_in_order(plan: PlanDocs) -> None:
    """15-observability.md:140, read out of the table and compared in BOTH directions.

    Both, because a missing attribute and an extra one are different bugs: the first makes a `call`
    span unanswerable without a join to the spend ledger, and the second is a level the charter
    says may not be added without an amendment (15:85).
    """
    rows = plan.grep(r"^\| `call` \|", documents=("15-observability.md",))
    assert len(rows) == 1, [str(hit) for hit in rows]
    cells = rows[0].text.split("|")
    declared = tuple(name.strip().strip("`") for name in cells[2].split(",") if name.strip())
    assert declared == CALL_SPAN_ATTRIBUTES
    assert len(CALL_SPAN_ATTRIBUTES) == 18


def test_the_dispatchers_eighteen_are_the_event_vocabularys_call_span() -> None:
    """One fact, two cells: `CALL_SPAN_ATTRIBUTES` here and `SPAN_ATTRIBUTES["call"]` in W4.8.

    Both transcribe 15-observability.md:140 and both are used -- this one builds the mapping a span
    carries, that one declares what `call.begin` and `call.end` may hold. INV-21 allows one home for
    a fact and this assertion is the cheapest way to notice the day they stop agreeing; the
    alternative, importing one from the other, would put the trace vocabulary inside the dispatcher.
    """
    assert SPAN_ATTRIBUTES["call"] == CALL_SPAN_ATTRIBUTES
    assert set(EVENTS["call.begin"].fields) | set(EVENTS["call.end"].fields) == set(
        CALL_SPAN_ATTRIBUTES
    )


def test_batch_index_and_batch_size_are_attributes_and_the_plan_says_so(plan: PlanDocs) -> None:
    """15:84: *"`batch_index` and `batch_size` are attributes on `call`, never rows."*"""
    hits = plan.grep(r"batch_index.*batch_size.*attribute", documents=("15-observability.md",))
    assert hits, "15:84's sentence moved"
    assert "batch_index" in CALL_SPAN_ATTRIBUTES
    assert "batch_size" in CALL_SPAN_ATTRIBUTES


def test_a_billed_call_carries_the_spend_vector_and_its_price() -> None:
    batch = batch_of(row(1, part="p1", service="model:olmocr"))
    spend = Spend(wall_ms=31_000, gpu_ms=900, tokens_in=1_200, tokens_out=1_100, calls=1)
    attrs = call_attributes(
        batch,
        batch_index=2,
        driver_version="1.4.0",
        driver_schema_v=7,
        isolation="subproc",
        provider="acme",
        spend=spend,
        micros=99_000,
    )
    assert tuple(attrs) == CALL_SPAN_ATTRIBUTES
    assert attrs["batch_index"] == 2
    assert attrs["batch_size"] == 1
    assert attrs["invoke_id"] == "iv_test"
    assert attrs["dispatch_key"] == KEY
    assert attrs["service"] == "model:olmocr"
    assert attrs["tokens_out"] == 1_100
    assert attrs["micros"] == 99_000


def test_a_free_driver_gets_seven_honest_zeros_rather_than_absent_keys() -> None:
    """A trace consumer must not have to branch on whether a driver was billed."""
    attrs = call_attributes(batch_of(row(1)), batch_index=0)
    assert tuple(attrs) == CALL_SPAN_ATTRIBUTES
    assert [attrs[dim] for dim in ("wall_ms", "cpu_ms", "gpu_ms")] == [0, 0, 0]
    assert [attrs[dim] for dim in ("tokens_in", "tokens_out", "calls", "bytes_egress")] == [0] * 4
    assert attrs["service"] == ""
    assert attrs["provider"] == ""


def test_an_op_batch_names_an_empty_driver_and_an_empty_key() -> None:
    op_row = row(1, operator="op.identify", key=None, driver=None)
    attrs = call_attributes(batch_of(op_row), batch_index=0)
    assert attrs["driver"] == ""
    assert attrs["dispatch_key"] == ""


def test_call_attributes_refuses_a_negative_index_and_returns_a_read_only_mapping() -> None:
    attrs = call_attributes(batch_of(row(1)), batch_index=0)
    with pytest.raises(TypeError):
        attrs["driver"] = "other"  # type: ignore[index]
    with pytest.raises(RouteError, match="ordinal within one claim"):
        call_attributes(batch_of(row(1)), batch_index=-1)


# ---------------------------------------------------------------------------------------------
# 8. D103's rule, asserted over this module's own source
# ---------------------------------------------------------------------------------------------


def test_the_mechanisms_are_imported_and_not_re_implemented() -> None:
    """D103's resolution as a check: mechanisms in `omniweave_core.host`, decisions here.

    Identity, not equality: a `dispatch.adapt_batch` that happened to agree today would be a second
    copy of 08:764-775's `match` statement, and D103's whole point is that two homes for one rule
    can disagree while a run is in flight.
    """
    assert dispatch.adapt_batch is subproc.adapt_batch
    assert dispatch.retry_batch_size is subproc.retry_batch_size
    assert dispatch.CrashLedger is subproc.CrashLedger
    assert dispatch.AimdState is subproc.AimdState
    assert adapt_batch is subproc.adapt_batch
    assert retry_batch_size is subproc.retry_batch_size


def test_this_module_contains_no_aimd_arithmetic_of_its_own() -> None:
    """The halving, the increment and the twenty are `subproc.py`'s and appear in no expression.

    Read off the AST rather than the text so a docstring may still explain the arithmetic -- which
    it must, because a reader of this file should not have to open another one to learn what AIMD
    does.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.FloorDiv):
            # Both floor divisions here are the apportionment's, not AIMD's: 08:818 prints
            # *"Integer division makes the +/-1 real"* as this module's own rule.
            assert isinstance(node.right, ast.Name), ast.unparse(node)
            assert node.right.id in {"count", "total"}, ast.unparse(node)
    constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    assert AIMD_RECOVERY_STREAK not in constants, "20 is subproc.AIMD_RECOVERY_STREAK's"


def test_this_module_holds_no_event_loop_and_no_store_call() -> None:
    """*"a policy that awaited would be a policy that could not be tested without a loop."*"""
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.Await)]
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "asyncio" not in imported
    assert "sqlite3" not in imported
