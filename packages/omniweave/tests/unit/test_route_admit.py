"""`omniweave.route.admit` against 05-ingest-and-routing.md sections 6.4, 6.5 and 10.3, and RT9.

**The test that matters is section 10.3's five-pass trace.** The plan prints the whole admission
arithmetic for a 6-page invoice on a site-layer budget -- every reservation, every headroom, every
denial, and the one pass where `budget.exhausted` is finally written -- and a `TraceLedger` here
reproduces `HEADROOM_SQL`'s two subqueries exactly, so the numbers are compared against the plan's
own rather than against a model of it.

The rest of the file is the shape a test of an admission ladder has to be: each of the three
refusals fires on its own condition and not on another's, the first refusal wins, and the free path
touches no ledger at all. And one test that is not about this module: `evaluate()` still cannot see
a ledger, which is INV-14 and is the whole reason this module exists separately.
"""

from __future__ import annotations

import datetime as dt
import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from omniweave.route import admit as ra
from omniweave.route import evidence as ev
from omniweave.route.decision import RouteDecision
from omniweave.route.eval import evaluate
from omniweave.route.rung import Rung
from omniweave_core.budget import (
    Admitted,
    Deferred,
    Degraded,
    Reservation,
    admission_of,
    per_unit_micros,
    reservation_id,
)
from omniweave_core.drivers.licence import Grant
from omniweave_core.drivers.resolve import COST_CLASS_ORDER
from omniweave_core.observe.degradation import Degradation
from omniweave_ports.types import CostClass, LicenceTier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

# --------------------------------------------------------------------------------------------
# Section 10.3's own numbers, transcribed.
# --------------------------------------------------------------------------------------------

LIMITS: Mapping[str, int] = {"micros_base": 4_000, "micros_per_part": 800, "micros_max": 12_000}
"""The trace's SITE-LAYER override, not section 4.4's shipped default: *"an operator's deliberately
tight budget on an invoice corpus"*. Under the shipped default the document never exhausts."""

UNIT = "file:///invoice.pdf"
PART_COUNT = 6
ALREADY_SPENT = 2_000
"""*"2,000 micros already spent this run against that scope key"*, as `committed` rows."""

RESERVED = 2_732
"""`parse.page.olmocr`'s `reserved_micros`, the p95 ceiling each part reserves."""

ACTUAL = 854
"""What a part actually cost. The 1,878 gap is what commit releases -- the p95 model's price."""


@dataclass
class TraceLedger:
    """A `BudgetLedger` whose arithmetic is `HEADROOM_SQL`'s, subquery for subquery.

    `limit - sum(held) - sum(committed)`, and the two states are tracked separately because the
    difference is the whole of 05:2537: a *held* row is money that may come back and a *committed*
    row is money that is gone. A fake that collapsed them would make every headroom in the trace
    below wrong from the first commit.

    `reserve()` checks every dimension before inserting any, which is `SqliteBudgetLedger.reserve`'s
    own two-pass shape: *"a loop that inserted as it checked would leave a partial reservation
    behind when the fourth dimension denied."*
    """

    rows: dict[str, tuple[str, str, str, int, str]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def _used(self, dim: str, scope: str, scope_key: str) -> int:
        return sum(
            amount
            for one_dim, one_scope, key, amount, state in self.rows.values()
            if (one_dim, one_scope, key) == (dim, scope, scope_key)
            and state in {"held", "committed"}
        )

    def headroom(self, dim: str, scope: str, scope_key: str, limit: int) -> int:
        self.calls.append("headroom")
        return limit - self._used(dim, scope, scope_key)

    def reserve(self, reservations: Sequence[Reservation], limits: Mapping[str, int]) -> str | None:
        self.calls.append("reserve")
        for row in reservations:
            limit = limits.get(row.dim)
            if limit is None:
                continue
            if self.headroom(row.dim, row.scope, row.scope_key, limit) < row.amount:
                return row.dim
        for row in reservations:
            self.rows[row.reservation_id] = (
                row.dim,
                row.scope,
                row.scope_key,
                row.amount,
                "held",
            )
        return None

    def commit(self, reservation_id_: str, amount: int, /) -> bool:
        self.calls.append("commit")
        row = self.rows.get(reservation_id_)
        if row is None or row[4] != "held":
            return False
        self.rows[reservation_id_] = (row[0], row[1], row[2], amount, "committed")
        return True

    def release(self, reservation_id_: str, /) -> bool:
        self.calls.append("release")
        row = self.rows.get(reservation_id_)
        if row is None or row[4] != "held":
            return False
        self.rows[reservation_id_] = (row[0], row[1], row[2], 0, "released")
        return True

    # -- what no `BudgetLedger` call exposes, and D211 is about ---------------------------------

    def held(self, dim: str, scope: str, scope_key: str) -> int:
        """`count(*) ... WHERE state='held'` for one scope key. **Not on the Protocol.**"""
        return sum(
            1
            for one_dim, one_scope, key, _, state in self.rows.values()
            if (one_dim, one_scope, key) == (dim, scope, scope_key) and state == "held"
        )


def _decision(part: str = "p1", driver: str = "parse.page.olmocr") -> RouteDecision:
    return RouteDecision(
        content_sha256="a" * 64, unit_part=part, lane="text", rung=Rung.PAGE, driver=driver
    )


def _micros(part: int) -> Reservation:
    """One `micros` reservation at the `unit` scope, which is the cap the trace exhausts."""
    return Reservation(
        reservation_id=reservation_id(part, "dec_x", 1, "micros"),
        run_id="r_1",
        work_id=part,
        decision_id="dec_x",
        dim="micros",
        amount=RESERVED,
        scope="unit",
        scope_key=UNIT,
        claimed_gen=1,
        expires_ms=1_000,
    )


def _request(part: int) -> ra.AdmissionRequest:
    return ra.AdmissionRequest(
        driver_cost_class=CostClass.BILLED_API,
        reservations=(_micros(part),),
        limits={"micros": per_unit_micros(LIMITS, part_count=PART_COUNT)},
    )


# --------------------------------------------------------------------------------------------
# 1. Section 10.3, pass by pass.
# --------------------------------------------------------------------------------------------


def test_the_per_unit_cap_is_the_traces_printed_8800() -> None:
    """`clamp(4000 + 800x6, 0, 12000) = 8,800`, and the clamp is inactive -- which is what makes
    `micros_per_part` the knob the exhaustion message names rather than `micros_max`."""
    assert per_unit_micros(LIMITS, part_count=PART_COUNT) == 8_800
    assert ra.binding_knob(LIMITS, part_count=PART_COUNT) == "micros_per_part"


def test_section_10_3s_five_passes_reproduce_every_printed_headroom() -> None:
    """The whole trace, and every number in it is the plan's.

    ```
    pass 1   p1 reserve 2,732 -> headroom 4,068.  p2 reserve 2,732 -> 1,336.
             p3 requests 2,732 > 1,336 -> Deferred(micros).  Siblings ARE in flight, so
             budget.exhausted is NOT written and on_exhausted is NOT consulted.
             p1 commits 854 -> release 1,878.  p2 commits 854 -> release 1,878.  headroom 5,092.
    pass 2   p3 reserve 2,732 -> 2,360.  p4 denied.  p3 commits -> release -> headroom 4,238.
    pass 3   p4 reserve 2,732 -> 1,506.  p5 denied.  p4 commits -> release -> headroom 3,384.
    pass 4   p5 reserve 2,732 ->   652.  p6 denied.  p5 commits -> release -> headroom 2,530.
    pass 5   p6 requests 2,732 > 2,530 and NOTHING is in flight for this scope key
             -> budget.exhausted IS written into Evidence for part 6.
    ```

    The gap between pass 1's denial and pass 5's is the entire reason 05:2534's clause exists: four
    of the five denials are a p95 model holding money it is about to give back, and treating any of
    them as exhaustion would spill the document to a free driver on a budget that was never spent.
    """
    limit = per_unit_micros(LIMITS, part_count=PART_COUNT)
    ledger = TraceLedger()
    ledger.rows["already"] = ("micros", "unit", UNIT, ALREADY_SPENT, "committed")
    record = ev.Evidence(content_sha256="a" * 64, unit_part="p6")
    headroom = lambda: ledger.headroom("micros", "unit", UNIT, limit)  # noqa: E731
    assert headroom() == 6_800

    # pass 1 -------------------------------------------------------------------------------
    assert ra.admit(_decision("p1"), ledger, _request(1)) == Admitted((_micros(1).reservation_id,))
    assert headroom() == 4_068
    assert ra.admit(_decision("p2"), ledger, _request(2)) == Admitted((_micros(2).reservation_id,))
    assert headroom() == 1_336
    assert ra.admit(_decision("p3"), ledger, _request(3)) == Deferred("micros")
    assert ledger.held("micros", "unit", UNIT) == 2
    assert ra.write_exhausted(record, siblings_in_flight=2) is False
    assert record.read(ra.EXHAUSTED_KEY) is None
    ledger.commit(_micros(1).reservation_id, ACTUAL)
    ledger.commit(_micros(2).reservation_id, ACTUAL)
    assert headroom() == 5_092

    # passes 2 to 4 ------------------------------------------------------------------------
    passes = ((3, 2_360, 4_238), (4, 1_506, 3_384), (5, 652, 2_530))
    for part, after_reserve, after_commit in passes:
        assert isinstance(ra.admit(_decision(f"p{part}"), ledger, _request(part)), Admitted)
        assert headroom() == after_reserve
        assert ra.admit(_decision(f"p{part + 1}"), ledger, _request(part + 1)) == Deferred("micros")
        ledger.commit(_micros(part).reservation_id, ACTUAL)
        assert headroom() == after_commit

    # pass 5 -------------------------------------------------------------------------------
    assert ra.admit(_decision("p6"), ledger, _request(6)) == Deferred("micros")
    assert ledger.held("micros", "unit", UNIT) == 0
    assert ra.write_exhausted(record, siblings_in_flight=0) is True
    assert record.read(ra.EXHAUSTED_KEY) is True

    # the outcome --------------------------------------------------------------------------
    spent = sum(amount for *_, amount, state in ledger.rows.values() if state == "committed")
    assert spent == ALREADY_SPENT + 5 * ACTUAL == 6_270
    assert spent < limit, "71% of the cap, and part 6 still failed -- that gap IS the p95 model"


def test_the_exhaustion_message_is_the_traces_printed_string() -> None:
    """05:3310, character for character. The three clauses are the arithmetic, where the money
    went, and three fixes in increasing order of commitment."""
    degradation = ra.exhaustion(
        limits=LIMITS,
        part_count=PART_COUNT,
        spent=6_270,
        limit=8_800,
        settled_parts=5,
        parts_affected=(6,),
        rung_reached="PAGE",
    )
    assert degradation.message == (
        "[budget.per_unit].micros_per_part gives 8800 for 6 parts; "
        "exhausted at 6270/8800 after part 5/6; "
        "raise micros_per_part, pass --allow-cost, or set on_exhausted=['defer'] in "
        ".omniweave/policy.d/00-builtin-route.toml"
    )
    assert degradation.kind == "budget"
    assert degradation.unit_dim == "micros"
    assert degradation.spent == 6_270
    assert degradation.limit == 8_800
    assert degradation.rung_reached == "PAGE"
    assert degradation.parts_affected == (6,)


def test_the_message_names_micros_max_only_when_the_clamp_actually_binds() -> None:
    """05:2612: *"Naming `micros_max` there would name a knob whose change does nothing."* The
    converse is the test: when the clamp DOES bind, raising `micros_per_part` is what does
    nothing, and section 4.4's own shipped numbers are the case where it does not."""
    clamped = {"micros_base": 4_000, "micros_per_part": 3_000, "micros_max": 10_000}
    assert ra.binding_knob(clamped, part_count=6) == "micros_max"
    assert ra.binding_knob(LIMITS, part_count=1) == "micros_base"
    assert ra.binding_knob(LIMITS, part_count=0) == "micros_base"
    shipped = {"micros_base": 4_000, "micros_per_part": 3_000, "micros_max": 16_000_000}
    assert per_unit_micros(shipped, part_count=6) == 22_000  # never exhausts on this document
    assert ra.binding_knob(shipped, part_count=6) == "micros_per_part"


# --------------------------------------------------------------------------------------------
# 2. Steps 1 to 3, each on its own condition.
# --------------------------------------------------------------------------------------------


def test_a_driver_above_the_gate_ceiling_is_clamped_and_not_denied() -> None:
    """Step 1. `Degraded` is one of three admissions and only `deferred` short-circuits: the work
    still runs, at a cheaper driver, which is what `on_exhausted[0] = "spill_to_free"` does."""
    request = ra.AdmissionRequest(
        driver_cost_class=CostClass.BILLED_API,
        max_cost_class=CostClass.LOCAL_COMPUTE,
        clamped_by=("gate.watcher-may-not-bill",),
    )
    verdict = ra.admit(_decision(), TraceLedger(), request)
    assert isinstance(verdict, Degraded)
    (degradation,) = verdict.degradations
    assert degradation.kind == "budget"
    assert degradation.unit_dim == "max_cost_class"
    assert degradation.wanted_driver == "parse.page.olmocr"
    assert "gate.watcher-may-not-bill" in degradation.message
    assert admission_of(verdict) == "degraded"


def test_a_cost_class_at_or_below_the_ceiling_is_not_clamped() -> None:
    """The mirror, and it exercises the boundary: `LOCAL_COMPUTE` under a `LOCAL_COMPUTE` ceiling
    is admitted, because the ceiling is a maximum and not an exclusive bound."""
    for cost_class in (CostClass.FREE, CostClass.LOCAL_COMPUTE):
        request = ra.AdmissionRequest(
            driver_cost_class=cost_class, max_cost_class=CostClass.LOCAL_COMPUTE
        )
        assert ra.clamp_refusal(_decision(), request) is None


def test_the_clamp_reads_the_same_ordering_the_modifier_merge_does() -> None:
    """`decision._COST_ORDER` is a deliberate copy -- `Modifiers.merge` is on `evaluate()`'s side of
    the purity line -- and this module is the impure half, so it reads `COST_CLASS_ORDER` directly.
    Two orderings for one ladder is a bug waiting for a third member."""
    assert list(COST_CLASS_ORDER) == [
        CostClass.FREE,
        CostClass.LOCAL_COMPUTE,
        CostClass.BILLED_API,
    ]


def test_a_tier_outside_allow_tiers_is_refused_as_driver_unavailable() -> None:
    """Step 2, and section 10.3's `fields` lane: lift's weights are OpenRAIL-M, `compute_tier` is
    `restricted`, and `[licence] allow_tiers = ["open"]` refuses it."""
    request = ra.AdmissionRequest(
        tier=LicenceTier.RESTRICTED, allow_tiers=frozenset({LicenceTier.OPEN})
    )
    verdict = ra.admit(_decision(driver="parse.fields.lift"), TraceLedger(), request)
    assert isinstance(verdict, Degraded)
    (degradation,) = verdict.degradations
    assert degradation.kind == "driver_unavailable"
    assert degradation.wanted_driver == "parse.fields.lift"
    assert "restricted" in degradation.message
    assert degradation.knob == "[licence] allow_tiers"


def test_no_tier_at_all_is_not_a_refusal() -> None:
    """A caller with no card in hand is not asserting the driver is unlicensed. `resolve()`'s check
    already ran and reaches `evaluate()` as `driver.unavailable`; this step is the late half."""
    assert ra.licence_refusal(_decision(), ra.AdmissionRequest()) is None
    permitted = ra.AdmissionRequest(
        tier=LicenceTier.RESTRICTED,
        allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
    )
    assert ra.licence_refusal(_decision(), permitted) is None


def test_egress_with_no_grant_is_refused_and_zero_egress_is_not() -> None:
    """Step 3. `bytes_egress = 0` is the shipped default, so the FIRST hosted call on a fresh
    install reaches this step -- 05:1290's *"0 = NO hosted escalation without a site-layer Grant"*
    is a refusal that fires, not a setting nobody meets."""
    assert ra.egress_refusal(_decision(), ra.AdmissionRequest()) is None
    verdict = ra.admit(_decision(), TraceLedger(), ra.AdmissionRequest(bytes_egress=4_096))
    assert isinstance(verdict, Degraded)
    (degradation,) = verdict.degradations
    assert degradation.kind == "grant_missing"
    assert degradation.limit == 4_096
    assert "dpa_ref" in degradation.message


def test_a_live_grant_admits_and_an_expired_one_does_not() -> None:
    """The clock is the caller's, always: `Grant.is_active` takes `now` as a parameter."""
    grant = Grant(
        grant_id="g_1",
        dpa_ref="DPA-2026-011",
        approver="platform@example.com",
        expires="2030-01-01T00:00:00Z",
        scope="corpus:invoices",
    )
    live = dt.datetime(2026, 9, 15, tzinfo=dt.UTC)
    expired = dt.datetime(2031, 1, 1, tzinfo=dt.UTC)
    assert (
        ra.egress_refusal(_decision(), ra.AdmissionRequest(bytes_egress=1, grant=grant, now=live))
        is None
    )
    stale = ra.egress_refusal(
        _decision(), ra.AdmissionRequest(bytes_egress=1, grant=grant, now=expired)
    )
    assert stale is not None
    assert "g_1" in stale.message
    assert "DPA-2026-011" in stale.message


def test_a_grant_that_was_never_dated_is_refused_rather_than_trusted() -> None:
    """AP-4 is *"the safety mechanism whose default disables it"*, and admitting on the strength of
    a grant nobody checked an expiry against would be exactly that."""
    grant = Grant(
        grant_id="g_1",
        dpa_ref="DPA-2026-011",
        approver="platform@example.com",
        expires="2030-01-01T00:00:00Z",
        scope="corpus:invoices",
    )
    refusal = ra.egress_refusal(_decision(), ra.AdmissionRequest(bytes_egress=1, grant=grant))
    assert refusal is not None
    assert "not checked against a clock" in refusal.message


def test_only_the_first_refusal_is_returned() -> None:
    """A `Degraded` carries a tuple, so all three would fit. They must not: steps 2 and 3 read a
    card and a grant for a driver step 1 has already established will not be used, and a
    degradation naming a licence tier for a clamped driver sends an operator to the wrong knob."""
    request = ra.AdmissionRequest(
        driver_cost_class=CostClass.BILLED_API,
        max_cost_class=CostClass.FREE,
        tier=LicenceTier.COMMERCIAL,
        bytes_egress=4_096,
    )
    verdict = ra.admit(_decision(), TraceLedger(), request)
    assert isinstance(verdict, Degraded)
    assert len(verdict.degradations) == 1
    assert verdict.degradations[0].unit_dim == "max_cost_class"


# --------------------------------------------------------------------------------------------
# 3. The free path, which is the plan's printed two-argument call.
# --------------------------------------------------------------------------------------------


def test_the_free_path_is_the_plans_two_argument_call_and_touches_no_ledger() -> None:
    """02:478's hop 8: *"`Admitted(reservations=())` -- a `free` decision reserves nothing"*, and
    the row's `writes` column is `nothing`. Reaching the ledger to insert no rows would take the
    write lock for a decision that has nothing to hold."""
    ledger = TraceLedger()
    assert ra.admit(_decision(), ledger) == Admitted(())
    assert ledger.calls == []
    assert ra.AdmissionRequest() == ra.FREE


def test_an_admission_request_defaults_to_the_free_decision() -> None:
    request = ra.AdmissionRequest()
    assert request.driver_cost_class is CostClass.FREE
    assert request.max_cost_class is CostClass.BILLED_API
    assert request.tier is None
    assert request.bytes_egress == 0
    assert request.grant is None
    assert request.reservations == ()


def test_a_negative_egress_is_not_a_quantity() -> None:
    with pytest.raises(ValueError, match="not a quantity"):
        ra.AdmissionRequest(bytes_egress=-1)


# --------------------------------------------------------------------------------------------
# 4. The write-back, and the clause that gates it.
# --------------------------------------------------------------------------------------------


def test_the_write_back_is_refused_while_any_sibling_is_in_flight() -> None:
    """05:2534's clause, in one assertion each way. The count is a parameter because no
    `BudgetLedger` call answers it -- `headroom()` subtracts held AND committed in one expression,
    so it cannot distinguish money that may come back from money that is gone. D211."""
    record = ev.Evidence(content_sha256="a" * 64, unit_part="p6")
    assert ra.write_exhausted(record, siblings_in_flight=1) is False
    assert record.read(ra.EXHAUSTED_KEY) is None
    assert ra.write_exhausted(record, siblings_in_flight=0) is True
    assert record.read(ra.EXHAUSTED_KEY) is True


def test_the_written_key_and_version_are_the_shipped_registry_rows() -> None:
    """The constants pinned against `signals.toml`, so the value `Evidence.put()` records into the
    read set is the version the registry declares rather than a second answer."""
    specs = {spec.key: spec for spec in ev.builtin_specs()}
    spec = specs[ra.EXHAUSTED_KEY]
    assert spec.provider == ra.ADMIT_PROVIDER
    assert spec.version == ra.EXHAUSTED_VERSION
    assert spec.dtype == "bool"
    assert spec.scope == "part"


def test_the_key_is_readable_as_an_exists_test_which_is_what_the_shipped_rule_uses() -> None:
    """05:1004's named beneficiary. `degrade.budget-exhausted` reads `{exists = true}`, which is
    TOTAL, which is why that rule alone needs no `on_unknown` -- and why an unwritten key routes
    the document normally instead of through `on_exhausted`."""
    record = ev.Evidence(content_sha256="a" * 64, unit_part="p6")
    assert record.read(ra.EXHAUSTED_KEY) is None
    record.clear_read_log()
    ra.write_exhausted(record, siblings_in_flight=0)
    assert record.read(ra.EXHAUSTED_KEY) is True
    assert record.read_set() == ((ra.EXHAUSTED_KEY, ra.EXHAUSTED_VERSION, True),)


# --------------------------------------------------------------------------------------------
# 5. INV-14, from the other side.
# --------------------------------------------------------------------------------------------


def test_evaluate_takes_no_ledger_and_no_budget_of_any_kind() -> None:
    """05:1182: *"`evaluate()` takes `(policy, evidence, hints, rung, lane, phase)` and nothing
    else -- no ledger, no `RunContext`, no clock."* RT9 is why: a budget change can never alter
    WHICH rung a document would have taken, only whether it ran.

    An absence is what a later contributor adds without noticing, so it is asserted by name.
    """
    names = list(inspect.signature(evaluate).parameters)
    assert names == ["policy", "ev", "hints", "rung", "lane", "phase"]
    for absent in ("ledger", "budget", "admission", "reservations", "spend", "book", "ctx"):
        assert absent not in names


def test_the_only_channel_from_admit_to_evaluate_is_one_boolean_key() -> None:
    """RT9's channel, measured: `admit` writes exactly one evidence key and the router reads it as
    a signal like any other. Nothing else this module produces is visible to `evaluate()`."""
    record = ev.Evidence(content_sha256="a" * 64, unit_part="p6")
    ra.write_exhausted(record, siblings_in_flight=0)
    assert record.read_set() == (), "a put is not a read; the DEGRADE rule's read is"
    assert record.read(ra.EXHAUSTED_KEY) is True
    assert [key for key, _, _ in record.read_set()] == [ra.EXHAUSTED_KEY]
    assert ra.EXHAUSTED_KEY.startswith("budget.")


def test_no_verdict_type_carries_a_rung_a_lane_or_a_rule(repo_root: Path) -> None:
    """*"`admit()` is the sole impure half of routing and runs strictly after `route_decision` is
    written, so a budget change can never alter which rung a document would have taken."* A verdict
    that carried a rung would be an admission proposing a route."""
    source = (repo_root / "packages/omniweave/src/omniweave/route/admit.py").read_text("utf-8")
    one = Degradation(kind="budget", message="a test", knob="micros")
    for verdict in (Admitted(()), Deferred("micros"), Degraded((one,))):
        names = {name for name in dir(verdict) if not name.startswith("_")}
        assert not names & {"rung", "lane", "rule_id", "escalate_to"}
    assert "escalate_to" not in source
    assert "Rung." not in source
